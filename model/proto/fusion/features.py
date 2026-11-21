"""Fallback evidence layer for fusion (spec 4.2 to 4.6), built because model/proto/evidence/ had no outputs.

Derives, from cleaning/claims (snapshot) plus the merge, geo and identity audits:
  atoms.parquet            one row per (claim sentence or specialties tag, service): ownership, role, specificity,
                           counts_as_own, rejected_reason, unit_id (echo collapse), is_unit_rep
  features_pairs.parquet   69,713 (unique_id, service) rows: T, C, N, S, P (+ ablation variants T_noown, T_noecho),
                           bucket, list_truncated, context columns, cited/rejected atom ids, B0/B1/B2 inputs
  features_facility.parquet 9,959 rows: existence witnesses, location votes and flags, p1/p2, leakage group
Differences from the spec are listed in REPORT.md (section "Fallback evidence").
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python features.py
"""
import json
import re
import sys

import duckdb
import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from fcommon import HERE, ROOT, SNAP, SVC, SVC_INV, UnionFind, dump, sha256_file

sys.path[:0] = [str(ROOT / "cleaning/claims"), str(ROOT / "cleaning/geo_identity")]
import lexicon as L  # noqa: E402  read-only import (spec_core tags, prereq tags)

RAW = ROOT / "data/raw/facilities.parquet"
MERGE = ROOT / "audit/merge/out"
IDN = ROOT / "audit/identity/out"
GEO = ROOT / "audit/geo/facility_geo.parquet"

UNIT_RX = re.compile(r"\b(?:units?|cent(?:re|er)s?|departments?|dept|theat(?:re|er)s?|wards?|wing|suites?|labs?|laborator(?:y|ies)"
                     r"|machines?|beds?|scanners?|stations?|ICU|NICU|SNCU|cath)\b", re.I)
NONOFFER_CUES = ["nonoffer", "cue_negation", "cue_referral", "cue_future", "cue_camp", "cue_past"]
SPEC_RANK = {"unit": 0, "quantity": 1, "generic": 2}
LEVELS = [("mc", r"medical college|\bAIIMS\b|institute of medical sciences|\bGMCH?\b"),
          ("dh", r"\bdistrict (hospital|h\.?q\.? hospital|headquarters? hospital)|\bzil+a (hospital|aspatal)|\bsadar hospital"
                 r"|\bcivil hospital|\bDHH\b"),
          ("sdh", r"sub[- ]?divisional|sub[- ]?district hospital|\bSDH\b|taluk(a)? (general )?hospital|tehsil hospital|area hospital"),
          ("chc", r"community health cent|\bCHC\b|rural hospital"),
          ("phc", r"primary health cent|\bU?PHC\b|health (and|&) wellness|health sub[- ]?cent")]
LEVELS = [(k, re.compile(r, re.I)) for k, r in LEVELS]
GENERIC_NAME_TOKENS = {"hospital", "hospitals", "clinic", "care", "centre", "center", "medical", "health", "nursing", "home",
                       "multi", "speciality", "specialty", "super", "the", "and", "of", "dental", "eye", "city", "new", "life",
                       "general", "institute", "research", "sciences", "college", "trust", "memorial", "mission", "children",
                       "women", "heart", "kidney", "cancer", "maternity", "diagnostic", "diagnostics", "pvt", "ltd", "district"}


def jlen(col):
    return f"coalesce(json_array_length(case when json_valid({col}) then {col} end), 0)"


def record_table():
    """Per-record context from the merge audit's record_scores (same 9,959 unique_ids as cleaning)."""
    r = duckdb.sql(f"""select unique_id, name, facilityTypeId ftype, operatorTypeId optype,
        try_cast(capacity as double) beds, try_cast(numberDoctors as double) doctors, q_share, shared_content,
        {jlen('source_urls')} n_urls,
        coalesce(len(list_distinct(json_extract_string(case when json_valid(source_ids) and source_ids like '[%' then source_ids end, '$[*]'))), 0) n_source_ids,
        recency_of_page_update is not null and recency_of_page_update not in ('null', '') has_recency,
        greatest({jlen('procedure')}, {jlen('capability')}, {jlen('equipment')}) >= 50 list_truncated,
        source_content_id
        from read_parquet('{MERGE}/record_scores.parquet')""").df()
    r["bucket"] = np.where((r.q_share >= 0.10) | (r.n_urls >= 30) | r.shared_content, "high",
                           np.where((r.q_share == 0) & (r.n_urls < 8), "low", "mid"))
    r["ftype4"] = r.ftype.where(r.ftype.isin(["hospital", "clinic", "dentist"]), "other")
    lv = []
    for n in r.name.fillna(""):
        lv.append(next((k for k, rx in LEVELS if rx.search(n)), "none"))
    r["level"] = lv
    r["public"] = r.optype.isin(["public", "government"]) | (r.level != "none")
    r["beds_bin"] = pd.cut(r.beds, [-1, 29.5, 99.5, 1e9], labels=["lt30", "30_99", "100p"]).astype(object).fillna("missing").astype(str)
    r["doctors_bin"] = pd.cut(r.doctors, [-1, 4.5, 19.5, 1e9], labels=["lt5", "5_19", "20p"]).astype(object).fillna("missing").astype(str)
    sp = pd.read_parquet(SNAP / "specialties.parquet")
    breadth = sp.groupby("unique_id").spec.nunique()
    r["n_specialties"] = r.unique_id.map(breadth).fillna(0).astype(int)
    r["breadth_bin"] = pd.cut(r.n_specialties, [-1, 4.5, 19.5, 1e9], labels=["lt5", "5_19", "20p"]).astype(str)
    r["scale_contradiction"] = (r.ftype == "clinic") & (r.beds >= 100)
    return r


def classify_atoms(c):
    """Ownership, role, specificity and rejection reason per claim atom (spec 4.2)."""
    own = np.select(
        # named reasons first, so the card can say WHICH other hospital or place; quarantine is the catch-all
        [c.attribution == "other_facility", c.sibling_names != "", c.places_other_state != "",
         c.places_other_district != "", c.quarantine, c.attribution == "ambiguous"],
        ["other_facility", "sibling", "other_place_state", "other_place_district", "quarantined", "ambiguous"],
        default=c.attribution)  # own_anchored | unanchored
    nonoffer = c[NONOFFER_CUES].any(axis=1)
    hedge = c.cue_hedge | c.cue_third_party | c.cue_parttime | (c.kind == "qualified")
    role = np.select([nonoffer, hedge, c.kind.isin(["list", "directory"]), c.kind == "staff",
                      c.kind.isin(["template", "research"]), c.qty_value.notna(), c.text.str.contains(UNIT_RX.pattern, flags=re.I, regex=True)],
                     ["nonoffer", "hedge", "list", "staff", "research_or_template", "quantity", "unit_or_equipment"],
                     default="offer")
    spec = np.select([c.text.str.contains(UNIT_RX.pattern, flags=re.I, regex=True), c.qty_value.notna()], ["unit", "quantity"], default="generic")
    c = c.assign(ownership=own, role=role, specificity=spec)
    c["own_ok"] = c.ownership.isin(["own_anchored", "unanchored"])
    c["counts_as_own"] = c.own_ok & c.role.isin(["offer", "unit_or_equipment", "quantity"])
    reason = {"other_facility": "names_other_facility", "other_place_state": "other_state_place",
              "other_place_district": "other_district_place", "quarantined": "quarantined_merge", "sibling": "sibling_branch",
              "ambiguous": "ambiguous_attribution"}
    rr = c.ownership.map(reason)
    role_reason = c.role.map({"nonoffer": "nonoffer_cue", "list": "directory_or_list", "staff": "staff_only",
                              "hedge": "hedge", "research_or_template": "research_or_template"})
    c["rejected_reason"] = np.where(c.counts_as_own, None, rr.fillna(role_reason))
    c["rejected_for_ownership"] = c.ownership.isin(list(set(reason) - {"ambiguous"}))
    return c


def norm_text(t):
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()


def echo_units(g):
    """Single-link clusters of counts_as_own atoms (equal normalised text or fuzz.ratio >= 85). Returns unit index per row."""
    texts = [norm_text(t) for t in g.text]
    uf = UnionFind()
    for i in range(len(texts)):
        uf.find(i)
        for j in range(i):
            if texts[i] == texts[j] or fuzz.ratio(texts[i], texts[j]) >= 85:
                uf.union(i, j)
    return [uf.find(i) for i in range(len(texts))]


def t_level(units, has_weak):
    """units: list of (rep_field, has_unit_or_qty). T per spec 4.4 (weak-only mentions count as level 1, see REPORT)."""
    if not units:
        return 1 if has_weak else 0
    fields = {f for f, _ in units}
    if len(fields) >= 2:
        return 5 if any(s for _, s in units) else 4
    return 3 if len(units) >= 2 else 2


def pair_families(atoms, prereq_hits, tags):
    """Family values per (unique_id, service) for the shipped rules and two ablations."""
    rows = []
    for (u, s), g in atoms.groupby(["unique_id", "service"], sort=False):
        own = g[g.counts_as_own & (g.field != "specialties")]
        weak = bool(((g.field == "specialties") | (g.own_ok & ~g.counts_as_own & (g.role != "nonoffer"))).any())
        reps = own[own.is_unit_rep]
        T = t_level([(f, sp != "generic") for f, sp in zip(reps.field, reps.specificity)], weak)
        T_noecho = t_level([(f, sp != "generic") for f, sp in zip(own.field, own.specificity)], weak)
        # ablation: ownership filter off -> every positive-role atom counts as own, one unit per atom group
        rpos = g[g.rejected_for_ownership & g.role.isin(["offer", "unit_or_equipment", "quantity"])]
        T_noown = t_level([(f, sp != "generic") for f, sp in zip(pd.concat([reps.field, rpos.field]),
                                                                 pd.concat([reps.specificity, rpos.specificity]))], weak)
        rej = g[g.rejected_for_ownership]
        nrej = len(rej)
        C = 0 if nrej == 0 else (1 if T >= 2 else 2)
        P = min(2, len(prereq_hits.get((u, s), set()) | tags.get((u, s), set())))
        order = reps.assign(o=reps.specificity.map({"unit": 0, "quantity": 1, "generic": 2})).sort_values(["o", "field"])
        rest = order.iloc[3:]  # the stored counterfactual removes the (up to 3) cited units only
        t_wo = t_level([(f, sp != "generic") for f, sp in zip(rest.field, rest.specificity)], weak)
        rows.append(dict(unique_id=u, service=s, T=T, T_noecho=T_noecho, T_noown=T_noown, C=C, N=int((g.role == "nonoffer").any()),
                         P=P, n_atoms=len(g), n_units_own=len(reps), n_fields_own=reps.field.nunique(), n_rejected=nrej,
                         n_tagged=int((g.field != "specialties").sum()), any_mention=True,
                         cited_atom_ids="|".join(order.atom_id.head(3)), rejected_atom_ids="|".join(rej.atom_id.head(5)),
                         t_without_cited=t_wo, c_without_cited=0 if nrej == 0 else (1 if t_wo >= 2 else 2)))
    return pd.DataFrame(rows)


def build_atoms():
    c = pd.read_parquet(SNAP / "claims.parquet")
    q = pd.read_parquet(MERGE / "sentence_decisions.parquet", columns=["unique_id", "field", "idx", "quarantine"])
    c = c.merge(q, on=["unique_id", "field", "idx"], how="left")
    assert c.quarantine.notna().all(), "sentence_decisions does not cover every claim"
    c["svc_list"] = c.services.str.split("|").map(lambda l: [SVC_INV[x] for x in l if x in SVC_INV])
    tagged = c[c.svc_list.map(len) > 0].explode("svc_list").rename(columns={"svc_list": "service"})
    a = classify_atoms(tagged)
    a["atom_id"] = a.claim_id + "|" + a.service
    # specialties-enum atoms (always level-1 evidence, never a unit)
    sp = pd.read_parquet(SNAP / "specialties.parquet")
    srows = []
    for s, key in SVC.items():
        hit = sp[sp.spec.isin(L.SERVICES[key]["spec_core"])]
        for i, r in zip(hit.index, hit.itertuples()):
            srows.append(dict(unique_id=r.unique_id, field="specialties", idx=int(i), text=r.spec, service=s,
                              claim_id=f"{r.unique_id[:8]}:spec:{i}", ownership="unanchored", role="list", specificity="generic",
                              own_ok=True, counts_as_own=False, rejected_reason="directory_or_list", rejected_for_ownership=False,
                              quarantine=False, qty_value=None, qty_unit=None))
    sa = pd.DataFrame(srows)
    sa["atom_id"] = sa.claim_id + "|" + sa.service
    keep = ["atom_id", "claim_id", "unique_id", "field", "idx", "text", "service", "ownership", "role", "specificity", "quarantine",
            "counts_as_own", "own_ok", "rejected_reason", "rejected_for_ownership", "qty_value", "qty_unit",
            "foreign_names", "places_other_state", "places_other_district", "sibling_names"]
    atoms = pd.concat([a[[k for k in keep if k in a]], sa], ignore_index=True)
    atoms["named_entity"] = (atoms.foreign_names.fillna("").where(atoms.foreign_names.fillna("") != "", atoms.sibling_names.fillna(""))
                             .where(lambda x: x != "", atoms.places_other_state.fillna(""))
                             .where(lambda x: x != "", atoms.places_other_district.fillna("")))
    # echo collapse inside (unique_id, service)
    atoms["unit_id"], atoms["is_unit_rep"] = None, False
    own = atoms[atoms.counts_as_own].copy()
    unit_ids, reps = {}, set()
    for (u, s), g in own.groupby(["unique_id", "service"], sort=False):
        lab = echo_units(g)
        for (idx, aid), k in zip(g.atom_id.items(), lab):
            unit_ids[idx] = f"{u[:8]}|{s}|u{k}"
        tmp = g.assign(k=lab, o=g.specificity.map(SPEC_RANK), ln=-g.text.str.len()).sort_values(["k", "o", "ln"])
        reps |= set(tmp.drop_duplicates("k").index)
    atoms.loc[list(unit_ids), "unit_id"] = pd.Series(unit_ids)
    atoms.loc[list(reps), "is_unit_rep"] = True
    # prerequisite flags from sentences that are not atoms of this service (and not other-facility sentences)
    pre = c[(c.prereqs != "") & (c.attribution != "other_facility") & ~c.dup_in_record]
    atom_keys = set(zip(a.claim_id, a.service))
    hits = {}
    for u, cid, ps in zip(pre.unique_id, pre.claim_id, pre.prereqs):
        for p in ps.split("|"):
            sk, name = p.split(".", 1)
            if sk in SVC_INV and (cid, SVC_INV[sk]) not in atom_keys:
                hits.setdefault((u, SVC_INV[sk]), set()).add(name)
    tags = {}
    sp_by = sp.groupby("unique_id").spec.agg(set).to_dict()
    for u, ts in sp_by.items():
        for s, key in SVC.items():
            for name, (_, ptags) in L.SERVICES[key]["prereqs"].items():
                if ts & ptags:
                    tags.setdefault((u, s), set()).add(name)
    return atoms, hits, tags


def location_features(rec):
    # cleaning/claims (via lexicon) already imported a different module named common; places needs geo_identity's
    sys.modules.pop("common", None)
    sys.path.insert(0, str(ROOT / "cleaning/geo_identity"))
    from places import build_layers, city_point
    f = pd.read_parquet(SNAP / "facility_location.parquet")
    gz = pd.read_parquet(ROOT / "cleaning/geo_identity/pin_gazetteer.parquet")
    gz = gz[gz.src.isin(["pin_median", "facility_consensus", "district_median"])].drop_duplicates("pin").set_index("pin")
    geo = pd.read_parquet(GEO, columns=["unique_id", "state_n", "coord_dup_names"]).drop_duplicates("unique_id").set_index("unique_id")
    layers = build_layers()
    dist = layers["district"]
    by_name = dist.groupby("name").size()

    def hav(a1, o1, a2, o2):
        a1, o1, a2, o2 = map(np.radians, (a1, o1, a2, o2))
        h = np.sin((a2 - a1) / 2) ** 2 + np.cos(a1) * np.cos(a2) * np.sin((o2 - o1) / 2) ** 2
        return 6371.0 * 2 * np.arcsin(np.sqrt(h))

    def vote(d, thr):
        return 0 if d is None or not np.isfinite(d) else (1 if d <= thr else -1)

    def name_place(name, state):
        toks = [t for t in re.findall(r"[a-z]+", (name or "").lower()) if len(t) > 3 and t not in GENERIC_NAME_TOKENS]
        for t in toks:
            hit = dist[(dist.state == state) & (dist.name == t)]
            if len(hit) == 0 and by_name.get(t, 0) == 1:
                hit = dist[dist.name == t]
            if len(hit) == 1:
                r = hit.iloc[0]
                return t, float(r.lat), float(r.lon), float(r.spread_km)
        return None

    rows = []
    for r in f.itertuples():
        p1 = (r.loc_lat, r.loc_lon)
        src = r.loc_src
        flags = set(r.loc_flags) if r.loc_flags is not None else set()
        raw_ok = pd.notna(r.raw_lat) and not (abs(r.raw_lat) < 1e-6 and abs(r.raw_lon) < 1e-6)
        d_raw = hav(r.raw_lat, r.raw_lon, *p1) if raw_ok else None
        pin = int(r.pin) if pd.notna(r.pin) else None
        pg = gz.loc[pin] if pin in gz.index else None
        d_pin = hav(pg.lat, pg.lon, *p1) if pg is not None else None
        cp = city_point(r.address_city, r.state_final, layers)
        d_city = hav(cp[0], cp[1], *p1) if cp else None
        npl = name_place(r.name, r.state_final)
        d_name = hav(npl[1], npl[2], *p1) if npl else None
        st = geo.state_n.get(r.unique_id)
        v = dict(
            v_coords=0 if src == "listing_coordinates" else vote(d_raw, 25.0),
            v_pin=0 if src == "postcode_centre" else vote(d_pin, max(25.0, float(pg.radius_km) if pg is not None and pd.notna(pg.radius_km) else 25.0)),
            v_city=0 if src == "address_city_centre" else vote(d_city, max(25.0, cp[3]) if cp else 25.0),
            v_name=vote(d_name, max(25.0, npl[3]) if npl else 25.0),
            v_state=0 if not isinstance(st, str) or not st or not isinstance(r.district_state, str) else (1 if st == r.district_state else -1))
        rows.append(dict(unique_id=r.unique_id, p1_lat=r.loc_lat, p1_lon=r.loc_lon, p1_src=src, p2_lat=r.alt_lat, p2_lon=r.alt_lon,
                         loc_radius_km=r.loc_radius, loc_conf=r.loc_conf, district=r.district, state=r.state_final,
                         d_raw_km=d_raw, d_pin_km=d_pin, d_city_km=d_city, d_name_km=d_name, name_place=npl[0] if npl else None,
                         f_copied_geocode=int("copied_geocode" in flags), f_coords_look_wrong=int("coords_look_wrong" in flags),
                         f_pin_looks_wrong=int("pin_looks_wrong" in flags), f_text_pin_elsewhere=int("other_pin_district_in_text" in flags),
                         coord_dup_names=geo.coord_dup_names.get(r.unique_id), loc_note=r.loc_note, **v))
    return pd.DataFrame(rows)


def existence_features(rec):
    es = pd.read_csv(IDN / "existence_signals.csv", usecols=["unique_id", "web", "name_dom_match", "phone"]).drop_duplicates("unique_id")
    dg = pd.read_csv(IDN / "dup_groups.csv").drop_duplicates("unique_id")
    rt = pd.read_parquet(SNAP / "record_trust.parquet", columns=["unique_id", "trust_flags"])
    e = rec[["unique_id", "ftype", "n_source_ids", "has_recency"]].merge(es, on="unique_id", how="left").merge(
        dg[["unique_id", "grp_strong"]], on="unique_id", how="left").merge(rt, on="unique_id", how="left")
    vet = e.trust_flags.map(lambda x: x is not None and "veterinary" in list(x))
    return pd.DataFrame(dict(
        unique_id=e.unique_id,
        e_web_own=(e.web == "own_domain").astype(int),
        e_web_other=e.web.isin(["directory_or_host", "government_portal"]).astype(int),
        e_phone_shared3=(e.phone == "shared_3plus_cities").astype(int),
        e_phone_none=e.phone.isin(["none", "invalid"]).astype(int),
        e_phone_landline=(e.phone == "landline").astype(int),
        e_multi_source=(e.n_source_ids >= 2).astype(int),
        e_recency=e.has_recency.astype(int),
        e_nonfacility=(e.ftype.isin(["pharmacy", "farmacy"]) | vet).astype(int),
        e_dup_member=e.grp_strong.notna().astype(int),
        web_class=e.web, phone_class=e.phone))


def leakage_groups(rec):
    """Union-find over grp_strong, official phone/domain groups (only when they span < 3 cities), chain, source_content_id."""
    dg = pd.read_csv(IDN / "dup_groups.csv").drop_duplicates("unique_id")
    ch = pd.read_csv(IDN / "chain_membership.csv", usecols=["unique_id", "chain"]).drop_duplicates("unique_id")
    city = duckdb.sql(f"select unique_id, lower(trim(address_city)) c from read_parquet('{MERGE}/record_scores.parquet')").df()
    d = dg.merge(ch, on="unique_id", how="left").merge(city, on="unique_id", how="left").merge(
        rec[["unique_id", "source_content_id"]], on="unique_id", how="left")
    uf = UnionFind()
    for u in d.unique_id:
        uf.find(u)
    for col in ["grp_strong", "grp_official_phone", "grp_official_domain", "chain", "source_content_id"]:
        sub = d[d[col].notna() & (d[col].astype(str) != "")]
        for k, g in sub.groupby(col):
            if col in ("grp_official_phone", "grp_official_domain") and g.c.nunique() >= 3:
                continue
            us = list(g.unique_id)
            for x in us[1:]:
                uf.union(us[0], x)
    lg = pd.DataFrame(dict(unique_id=d.unique_id, leakage_group_id=[uf.find(u) for u in d.unique_id]))
    lg["group_size"] = lg.groupby("leakage_group_id").unique_id.transform("size")
    return lg


def main():
    rec = record_table()
    assert len(rec) == 9959 and rec.unique_id.is_unique
    atoms, hits, tags = build_atoms()
    fam = pair_families(atoms, hits, tags)
    grid = pd.MultiIndex.from_product([rec.unique_id, list(SVC)], names=["unique_id", "service"]).to_frame(index=False)
    pf = grid.merge(fam, on=["unique_id", "service"], how="left")
    for k in ["T", "T_noecho", "T_noown", "C", "N", "n_atoms", "n_units_own", "n_fields_own", "n_rejected", "n_tagged", "t_without_cited", "c_without_cited"]:
        pf[k] = pf[k].fillna(0).astype(int)
    pf["any_mention"] = pf.any_mention.fillna(False).astype(bool)
    # P also counts for pairs with no service atom (prerequisites only), capped at 2
    pf["P"] = [min(2, len(hits.get((u, s), set()) | tags.get((u, s), set()))) for u, s in zip(pf.unique_id, pf.service)]
    pf[["cited_atom_ids", "rejected_atom_ids"]] = pf[["cited_atom_ids", "rejected_atom_ids"]].fillna("")
    g = pd.read_parquet(SNAP / "grades.parquet", columns=["unique_id", "service", "grade", "scope_conflict"])
    g["service"] = g.service.map(SVC_INV)
    pf = pf.merge(g, on=["unique_id", "service"], how="left")
    pf["S"] = pf.scope_conflict.fillna(False).astype(int)
    pf["grade"] = pf.grade.fillna("none")
    pf = pf.drop(columns="scope_conflict").merge(
        rec[["unique_id", "name", "bucket", "list_truncated", "ftype4", "level", "public", "beds_bin", "doctors_bin", "breadth_bin",
             "scale_contradiction"]], on="unique_id", how="left")
    pf["iphs_essential"] = ((pf.level == "dh") & pf.service.isin(["dialysis", "emergency_csection"])).astype(int)
    pf["X"] = None  # no verified external list yet: family X abstains everywhere
    assert len(pf) == 69713
    loc = location_features(rec)
    ex = existence_features(rec)
    lg = leakage_groups(rec)
    ff = rec[["unique_id", "name", "bucket", "n_urls", "q_share"]].merge(loc, on="unique_id").merge(ex, on="unique_id").merge(lg, on="unique_id")
    assert len(ff) == 9959
    atoms.drop(columns=["own_ok"]).to_parquet(HERE / "atoms.parquet", index=False)
    pf.to_parquet(HERE / "features_pairs.parquet", index=False)
    ff.to_parquet(HERE / "features_facility.parquet", index=False)
    stats = dict(
        atoms=len(atoms), atoms_by_ownership=atoms.ownership.value_counts().to_dict(), atoms_by_role=atoms.role.value_counts().to_dict(),
        counts_as_own=int(atoms.counts_as_own.sum()), units=int(atoms.is_unit_rep.sum()),
        T=pf["T"].value_counts().sort_index().to_dict(), T_noecho=pf.T_noecho.value_counts().sort_index().to_dict(),
        T_noown=pf.T_noown.value_counts().sort_index().to_dict(), C=pf.C.value_counts().sort_index().to_dict(),
        N=int(pf.N.sum()), S=int(pf.S.sum()), P=pf.P.value_counts().sort_index().to_dict(),
        bucket_records=rec.bucket.value_counts().to_dict(), level=rec.level.value_counts().to_dict(),
        pairs_T_ge_2=int((pf["T"] >= 2).sum()), pairs_any_mention=int(pf.any_mention.sum()),
        loc_votes={k: ff[k].value_counts().to_dict() for k in ["v_coords", "v_pin", "v_city", "v_name", "v_state"]},
        leakage_groups=int(lg.leakage_group_id.nunique()), largest_group=int(lg.group_size.max()),
        inputs={p.name: sha256_file(p) for p in sorted(SNAP.iterdir())},
        code_sha256=sha256_file(__file__))
    dump(stats, HERE / "features_stats.json")
    print(json.dumps({k: v for k, v in stats.items() if k != "inputs"}, indent=1, default=str))


if __name__ == "__main__":
    main()

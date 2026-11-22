"""Independent verification of the record_loss audit (RL-01..RL-07) plus hunts for missed issues.

Own code only: nothing is imported from ../checks.py. Read-only on every data layer; writes only to
verify/out/. Every check returns dict(name, status, metric, threshold, detail, examples).

Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python validation/record_loss/verify/checks.py
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import time
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
V1 = ROOT / "derived/v1"
RAWF = ROOT / "data/raw/facilities.parquet"
OUT = Path(__file__).resolve().parent / "out"
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
APP = {"csection": "emergency_csection", "nicu": "nicu", "trauma": "trauma_emergency", "burns": "burn_care",
       "dialysis": "dialysis", "mri": "mri", "cardiac_surgery": "cardiac_surgery"}
BAD_GRADES = ("attributed_elsewhere", "counter_evidence")
FOCUS = ("BIHAR", "UTTAR PRADESH", "JHARKHAND", "ODISHA", "ASSAM")
R_EARTH = 6371.0088


def res(name, status, metric, threshold, detail, examples=()):
    return dict(name=name, status=status, metric=metric, threshold=threshold, detail=detail,
                examples=[str(x) for x in examples][:5])


def q(sql: str) -> pd.DataFrame:
    return duckdb.sql(sql).df()


@cache
def usable_ids() -> frozenset:
    return frozenset(q(f"select distinct unique_id from '{RAWF}' where regexp_matches(unique_id, '{UUID}') "
                       "and source = 'kie'").unique_id)


@cache
def pq(name: str) -> pd.DataFrame:
    return pd.read_parquet(V1 / name)


@cache
def jgz(path: str) -> dict:
    return json.loads(gzip.decompress((ROOT / path).read_bytes()))


@cache
def packs() -> dict:
    idx = json.loads((ROOT / "app/packs/out/index.json").read_text())["packs"]
    return {k: jgz(f"app/packs/out/{k}.json.gz") for k in idx}


def unpack(p: dict) -> dict:
    """Decode the delta-encoded columns of a pack (format v1) into absolute values."""
    c = np.cumsum
    return dict(f=c(p["ev"]["f"]), flat=c(p["fac"]["lat"]) / p["scale"]["fac"], flon=c(p["fac"]["lon"]) / p["scale"]["fac"],
                pin=c(p["pins"]["pin"]), plat=c(p["pins"]["lat"]) / p["scale"]["pin"],
                plon=c(p["pins"]["lon"]) / p["scale"]["pin"])


@cache
def uid8() -> dict:
    m = defaultdict(set)
    for u in usable_ids():
        m[u[:8]].add(u)
    assert all(len(v) == 1 for v in m.values()), "uid8 collision"
    return {k: next(iter(v)) for k, v in m.items()}


def trust_level() -> pd.Series:
    return pq("record_trust.parquet").set_index("unique_id").trust_level


# ------------------------------------------------------------------ RL-01
def check_v_rl01_truncated():
    """Recount the 30 truncated rows with SQL, and look for each one elsewhere in the usable set
    (same city, fuzzy name >= 90), which would make the loss smaller than stated."""
    from rapidfuzz import fuzz
    t = q(f"select unique_id, name, address_city city, address_stateOrRegion st, facilityTypeId ft, "
          f"address_zipOrPostcode zip, officialPhone ph from '{RAWF}' "
          f"where regexp_matches(unique_id, '{UUID}') and coalesce(source, '') <> 'kie'")
    u = pq("facility_location.parquet")[["unique_id", "name", "address_city"]].merge(
        q(f"select distinct unique_id, address_zipOrPostcode zip, officialPhone ph from '{RAWF}'"), on="unique_id")
    generic = {"hospital", "hospitals", "clinic", "centre", "center", "multispeciality", "multi", "speciality",
               "super", "dental", "care", "diagnostic", "diagnostics", "and", "the", "of", "in", "dr", "eye", "lab"}
    norm = lambda s: " ".join(w for w in re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).split() if w not in generic)  # noqa: E731
    found = []
    for r in t.itertuples():
        cand = u[u.address_city.fillna("").str.lower() == str(r.city).lower()]
        # same city + similar name + (same PIN or same phone): a surviving copy of the lost record
        hit = [c for c in cand.itertuples() if norm(r.name) and fuzz.ratio(norm(r.name), norm(c.name)) >= 90
               and (c.zip == r.zip or c.ph == r.ph)]
        if hit:
            found.append(f"{r.unique_id} '{r.name}' ~ {hit[0].unique_id} '{hit[0].name}'")
    ids_in_usable = len(set(t.unique_id) & usable_ids())
    detail = (f"types {t.ft.value_counts().to_dict()}; states {t.st.value_counts().to_dict()}; "
              f"{ids_in_usable} ids also usable; {len(found)} have a same-city same-name usable record. "
              "Vasundhara Dental (Ghaziabad) is labelled 'Ncr-delhi', so UP is 7 by geography.")
    t.to_csv(OUT / "truncated_30_recount.csv", index=False)
    return res("v_rl01_truncated", "warn" if len(t) else "pass", f"{len(t)} truncated, {len(found)} recoverable by name",
               "0", detail, found or t.unique_id.head(5))


def check_v_rl01_fragments():
    """Fragments: count rows without a UUID id and those holding a coordinates object (only copy of the tail)."""
    f = q(f"select * from '{RAWF}' where not regexp_matches(coalesce(unique_id, ''), '{UUID}')")
    coords = f.astype(str).apply(lambda r: r.str.contains('"coordinates"', regex=False).any(), axis=1)
    return res("v_rl01_fragments", "warn", f"{len(f)} fragments, {int(coords.sum())} with coordinates", "0",
               "Raw is sorted by unique_id, so fragments sit at the top of the file (rows 0..) and cannot be "
               "re-attached by row order; stitching needs content matching.", f.unique_id.head(3))


# ------------------------------------------------------------------ RL-02
def check_v_rl02_planner_and_pack_exclusions():
    tl = trust_level()
    vet = set(tl[tl == "exclude_review"].index)
    pl = jgz("planner/out/planner_v1.json.gz")
    ids = pl["facilities"]["id"]
    vet_i = {i for i, u in enumerate(ids) if u in vet}
    caps = json.loads((ROOT / "kb/pathways/capabilities.json").read_text())["capabilities"]
    kb = {c["id"]: c.get("kb_service") for c in caps if c.get("kb_status") == "existing"}
    vet_entries = [(c, ids[i], p) for c, v in pl["capabilities"].items() for i, p in zip(v["i"], v["p"]) if i in vet_i]
    d = pq("data_point_scores.parquet")
    d = d[d.dp_type == "service_claim"]
    bad = d[d.grade.isin(BAD_GRADES) | (d.status == "verified_false")]
    badk = set(zip(bad.unique_id, bad.service))
    excl = [(c, ids[i], p) for c, v in pl["capabilities"].items() if c in kb
            for i, p in zip(v["i"], v["p"]) if (ids[i], kb[c]) in badk]
    shown_vet = Counter()
    for k, p in packs().items():
        for u8 in p["fac"]["uid8"]:
            if uid8()[u8] in vet:
                shown_vet[(k, uid8()[u8])] += 1
    # PIN answers that list a vet record
    vet_answers = 0
    for k, p in packs().items():
        dp = unpack(p)
        uids = [uid8()[x] for x in p["fac"]["uid8"]]
        badl = {li for li, lst in enumerate(p["lists"]) if any(uids[dp["f"][e]] in vet for e in lst)}
        vet_answers += sum(li in badl for ix in p["index"].values() for li in ix)
    detail = (f"planner keeps {len(vet_i)} of {len(vet)} exclude_review records; capability entries on them "
              f"{len(vet_entries)} (max p {max((p for *_, p in vet_entries), default=0):.3f}): "
              f"{Counter(c for c, *_ in vet_entries)}; planner entries on pack-excluded pairs {len(excl)} by cap "
              f"{Counter(c for c, *_ in excl)}, max p {max((p for *_, p in excl), default=0):.3f}; vet records in packs "
              f"{dict(shown_vet)}; (PIN, service) answers listing a vet record {vet_answers}. app/itinerary.py:_stop "
              "shows a planner stop even when the facility id is not in facts (phone None).")
    return res("v_rl02_planner_and_pack_exclusions", "warn" if vet_entries or excl or shown_vet else "pass",
               f"vet in planner {len(vet_i)}, vet cap entries {len(vet_entries)}, excluded-pair entries {len(excl)}, "
               f"vet pack answers {vet_answers}", "0", detail,
               [f"{c} {u} p={p}" for c, u, p in vet_entries[:3]] + [f"{c} {u} p={p}" for c, u, p in excl[:2]])


def check_v_rl02_facts_excluded_pairs():
    """facts.pairs keeps every grade, including the ones packs drop; the engine must label them."""
    fx = jgz("app/facts/out/facts.json.gz")
    rows = [(s, r[1], r[3]) for s, rr in fx["pairs"].items() for r in rr]
    n_bad = sum(1 for _, g, st in rows if g in BAD_GRADES or st == "verified_false")
    return res("v_rl02_facts_excluded_pairs", "pass", f"{n_bad} of {len(rows)} facts pairs are pack-excluded grades",
               "labelled unlikely by engine.py:111",
               "facts keeps them on purpose; app/facts/engine.py:111 bands them unlikely and the area view keeps only "
               "OWN_EVIDENCE/tag_only/weak grades, so they are not shown as options. Not an issue, a known divergence.")


def check_h_verified_true_suppressed():
    """Gold verified-true pairs that packs drop and the facts engine bands 'unlikely', because the grade test
    (build_packs.py:79-80, engine.py:111) runs before the gold status."""
    d = pq("data_point_scores.parquet")
    x = d[(d.dp_type == "service_claim") & d.service.isin(APP) & (d.status == "verified_true") & d.grade.isin(BAD_GRADES)]
    shown = {(uid8()[u8], s) for p in packs().values() for u8, s in
             ((p["fac"]["uid8"][f], p["services"][sv]) for f, sv in zip(unpack(p)["f"], p["ev"]["s"]))}
    in_pack = sum((u, APP[s]) in shown for u, s in zip(x.unique_id, x.service))
    return res("h_verified_true_suppressed", "warn" if len(x) else "pass",
               f"{len(x)} gold verified-true app pairs carry an excluded grade; {in_pack} of them in any pack", "0",
               "Packs drop them; engine.py:111 checks grade before verified_true, so online they show as unlikely.",
               [f"{u} {s} {g} split={sp}" for u, s, g, sp in zip(x.unique_id, x.service, x.grade, x.gold_split)])


# ------------------------------------------------------------------ RL-03
def check_v_rl03_pack_duplicate_groups():
    g = pq("facility_groups.parquet").set_index("unique_id").dup_group_id.dropna()
    n_lists = hit_lists = hit_top3 = answers = answers_top3 = 0
    by_state, ex = Counter(), []
    for k, p in packs().items():
        dp = unpack(p)
        uids = [uid8()[x] for x in p["fac"]["uid8"]]
        bad, bad3 = set(), set()
        for li, lst in enumerate(p["lists"]):
            n_lists += 1
            grp = [g.get(uids[dp["f"][e]]) for e in lst]
            grp = [x for x in grp if x is not None]
            if len(grp) != len(set(grp)):
                bad.add(li)
                g3 = [x for x in (g.get(uids[dp["f"][e]]) for e in lst[:3]) if x is not None]
                if len(g3) != len(set(g3)):
                    bad3.add(li)
                if len(ex) < 5:
                    ex.append(f"{k} list {li}: " + " | ".join(p["fac"]["name"][dp["f"][e]][:30] for e in lst))
        hit_lists += len(bad)
        hit_top3 += len(bad3)
        for ix in p["index"].values():
            a = sum(li in bad for li in ix)
            answers += a
            answers_top3 += sum(li in bad3 for li in ix)
            by_state[p["state"]] += a
    tot_answers = sum(len(ix) for p in packs().values() for ix in p["index"].values())
    return res("v_rl03_pack_duplicate_groups", "warn" if hit_lists else "pass",
               f"{hit_lists}/{n_lists} lists, {answers}/{tot_answers} answers; inside top-3 only: {hit_top3} lists, "
               f"{answers_top3} answers", "0",
               f"by state {dict(by_state.most_common(6))}. s4_groups.py docstring says 'the app shows one card per group' "
               "but no file under app/ or planner/ reads dup_group_id or is_canonical.", ex)


def check_v_rl03_facts_noncanonical_pairs():
    """Online exposure: app-service pairs held by non-canonical copies that the facts engine ranks separately."""
    g = pq("facility_groups.parquet")
    nonc = set(g[~g.is_canonical].unique_id)
    fx = jgz("app/facts/out/facts.json.gz")
    ids = fx["fac"]["id"]
    n = sum(1 for rr in fx["pairs"].values() for r in rr if ids[r[0]] in nonc)
    tot = sum(len(rr) for rr in fx["pairs"].values())
    pl = jgz("planner/out/planner_v1.json.gz")
    npl = sum(1 for v in pl["capabilities"].values() for i in v["i"] if pl["facilities"]["id"][i] in nonc)
    return res("v_rl03_facts_noncanonical_pairs", "warn" if n else "pass",
               f"{n}/{tot} facts pairs and {npl} planner capability entries are on the {len(nonc)} non-canonical copies",
               "0", "facts fac keeps all 77 non-canonical records; engine ranks records.", sorted(nonc)[:5])


def check_v_rl03_opendata_shared():
    f = pd.read_parquet(ROOT / "kb/opendata/vf_opendata_facts.parquet", columns=["unique_id", "source", "source_id"])
    m = pd.read_parquet(ROOT / "kb/opendata/vf_opendata_match.parquet", columns=["unique_id", "source", "source_id", "tier"])
    m = m[m.tier.isin(["high", "medium"])]  # untiered rows are best non-matching candidates, conflict is not exported
    g = pq("facility_groups.parquet").set_index("unique_id").dup_group_id
    out = {}
    for name, t in (("facts", f), ("match", m)):
        s = t.drop_duplicates(["unique_id", "source", "source_id"]).groupby(["source", "source_id"]).unique_id.agg(sorted)
        s = s[s.map(len) > 1]
        unexplained = [(k, v) for k, v in s.items() if g.reindex(v).isna().any() or g.reindex(v).nunique() != 1]
        out[name] = (len(s), unexplained)
    nm = pq("facility_location.parquet").set_index("unique_id").name
    ex = [f"{k[0]}:{k[1]} " + " / ".join(f"{u[:8]} {nm.get(u, '')[:28]}" for u in v) for k, v in out["match"][1][:5]]
    return res("v_rl03_opendata_shared", "warn" if out["match"][1] else "pass",
               f"facts: {out['facts'][0]} shared objects, {len(out['facts'][1])} outside one group; match table: "
               f"{out['match'][0]} shared, {len(out['match'][1])} outside one group", "0", "", ex)


# ------------------------------------------------------------------ RL-04
@cache
def pop_by_state() -> pd.Series:
    return pd.read_csv(ROOT / "data/external/worldpop_r2025a/derived/district_population.csv").groupby("state")["pop"].sum()


def check_v_rl04_density_denominator():
    """Records per million by state, with the population join checked: a state with records but no population
    row inflates the national rate the auditor compares against."""
    loc = pq("facility_location.parquet")
    n = loc.state_final.value_counts()
    pop = pop_by_state()
    nopop = {s: int(c) for s, c in n.items() if s not in pop.index}
    pop_only = sorted(set(pop.index) - set(n.index))
    nat_all = n.sum() / pop.sum() * 1e6
    both = n[n.index.isin(pop.index)]
    nat_join = both.sum() / pop[both.index].sum() * 1e6
    per = (n / pop.reindex(n.index) * 1e6).round(2)
    pd.DataFrame({"records": n, "pop": pop.reindex(n.index), "per_m": per}).to_csv(OUT / "density_recount.csv")
    focus = {s: float(per.get(s, np.nan)) for s in FOCUS}
    return res("v_rl04_density_denominator", "warn" if nopop else "pass",
               f"national {nat_all:.2f}/M (all records / all pop), {nat_join:.2f}/M (joined states); focus {focus}",
               "every state with records has population",
               f"states with records but no population row: {nopop}; population-only states: {pop_only}; "
               f"total pop {pop.sum() / 1e6:.1f} M", list(nopop)[:5])


def _hav_matrix(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = (np.radians(x) for x in (lat1[:, None], lon1[:, None], lat2[None, :], lon2[None, :]))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def check_v_rl04_gap_from_v1():
    """Recompute 'share of PINs > 50 km from the nearest candidate' straight from derived/v1 (not from packs)."""
    from sklearn.neighbors import BallTree
    loc = pq("facility_location.parquet")[["unique_id", "loc_lat", "loc_lon"]].dropna()
    d = pq("data_point_scores.parquet")
    c = d[(d.dp_type == "service_claim") & d.service.isin(APP) & ~d.grade.isin(BAD_GRADES) & (d.status != "verified_false")]
    c = c.merge(loc, on="unique_id")
    pins = pq("pin_gazetteer.parquet").dropna(subset=["state", "lat", "lon"])
    rows = []
    for s, grp in c.groupby("service"):
        tree = BallTree(np.radians(grp[["loc_lat", "loc_lon"]].to_numpy()), metric="haversine")
        dist, _ = tree.query(np.radians(pins[["lat", "lon"]].to_numpy()), k=1)
        rows.append(pd.DataFrame({"state": pins.state.to_numpy(), "service": APP[s], "km": dist[:, 0] * R_EARTH}))
    df = pd.concat(rows)
    share = df.assign(gt=df.km > 50).groupby(["state", "service"]).gt.mean().unstack().round(3)
    nat = df.assign(gt=df.km > 50).groupby("service").gt.mean().round(3)
    share.to_csv(OUT / "gap_share_gt50_from_v1.csv")
    aud = pd.read_csv(ROOT / "validation/record_loss/out/pack_pin_gap_share_gt50km.csv", index_col=0)
    diff = (share.reindex_like(aud) - aud).abs().max().max()
    pick = {f"{s}/{v}": float(share.loc[s, v]) for s, v in [("ODISHA", "emergency_csection"), ("BIHAR", "burn_care"),
                                                            ("BIHAR", "cardiac_surgery"), ("ODISHA", "trauma_emergency")]}
    return res("v_rl04_gap_from_v1", "warn", f"max abs diff vs auditor table {diff:.3f}; {pick}; national {nat.to_dict()}",
               "diff < 0.01", "Independent of pack decoding (BallTree haversine on derived/v1 candidates).",
               [f"{k} {v}" for k, v in pick.items()])


# ------------------------------------------------------------------ RL-05
def check_v_rl05_url_repeats():
    """Recount repeated (record, url) rows and measure their effect on the record-level normalised weights
    (service profile) and on source_support, with domain reliabilities held fixed."""
    sys.path.insert(0, str(ROOT / "pipelines/source_scoring"))
    import s5_fit  # read-only: constants only
    u = pq("source_urls.parquet")[["unique_id", "url", "domain", "source_class", "url_kind"]]
    rep = u[u.duplicated(["unique_id", "url"])]
    rel = pq("source_domains.parquet").set_index("domain").reliability

    def support(t, prof):
        w = t.url_kind.map(s5_fit.KIND_W[prof]) * t.source_class.map(lambda c: s5_fit.WEIGHTS[prof].get(c, 1.0))
        e = t.assign(w=w).groupby(["unique_id", "domain"], as_index=False).w.sum()
        e["w"] = e.w / e.groupby("unique_id").w.transform("sum")
        return (e.w * e.domain.map(rel)).groupby(e.unique_id).sum()

    out = {}
    for prof in ("service", "identity", "attribution"):
        a, b = support(u, prof), support(u.drop_duplicates(["unique_id", "url"]), prof)
        dlt = (a - b).abs()
        out[prof] = (round(float(dlt.max()), 4), int((dlt > 0.01).sum()), int((dlt > 1e-9).sum()))
    return res("v_rl05_url_repeats", "warn" if len(rep) else "pass",
               f"{len(rep)} repeated rows in {rep.unique_id.nunique()} records; support change (max, n>0.01, n>0) {out}",
               "0", f"by class {rep.source_class.value_counts().head(4).to_dict()}; s5_fit.record_edges sums w per "
               "(record, domain) over url rows (s5_fit.py:73) with no url dedupe. Reliability held fixed: first-order.",
               rep.unique_id.drop_duplicates().head(5))


# ------------------------------------------------------------------ RL-06
def check_v_rl06_specialties_nraw():
    exp = q(f"""
      with b as (select unique_id, specialties from '{RAWF}' where regexp_matches(unique_id, '{UUID}') and source='kie'
                 qualify row_number() over (partition by unique_id) = 1),
      l as (select unique_id, unnest(from_json(specialties, '["VARCHAR"]')) s from b where json_valid(specialties))
      select unique_id, regexp_replace(lower(s), '[^a-z]', '', 'g') spec, count(*) n_exp from l
      where s is not null and trim(s) <> '' group by 1, 2""")
    s = pq("specialties.parquet")
    m = s.merge(exp, on=["unique_id", "spec"], how="outer", indicator=True)
    wrong = m[(m._merge == "both") & (m.n_raw != m.n_exp)]
    ratio = (wrong.n_raw / wrong.n_exp).value_counts().to_dict()
    users = [str(p.relative_to(ROOT)) for d in ("app", "planner", "pipelines", "kb", "cleaning", "model")
             for p in (ROOT / d).rglob("*.py") if "n_raw" in p.read_text(errors="ignore")]
    return res("v_rl06_specialties_nraw", "warn" if len(wrong) else "pass",
               f"{len(wrong)} rows wrong in {wrong.unique_id.nunique()} records (ratio {ratio}); only-v1 "
               f"{int((m._merge == 'left_only').sum())}, only-raw {int((m._merge == 'right_only').sum())}", "0",
               f"files mentioning n_raw: {users}", wrong.unique_id.drop_duplicates().head(5))


# ------------------------------------------------------------------ RL-07
def check_v_rl07_pins():
    loc = pq("facility_location.parquet")
    nodist = loc[loc.district.isna()]
    gz = pq("pin_gazetteer.parquet")
    ip = pd.read_parquet(ROOT / "data/raw/india_post_pincode_directory.parquet", columns=["pincode", "statename", "district"])
    ip_pins = set(ip.pincode.astype(int))
    fx = set(jgz("app/facts/out/facts.json.gz")["pins"]["pin"])
    miss = sorted(ip_pins - fx)
    st = ip[ip.pincode.isin(miss)].groupby("pincode").statename.first().value_counts().to_dict()
    no_state = gz[gz.state.isna() | gz.lat.isna()].pin.tolist()
    return res("v_rl07_pins", "warn",
               f"no district {len(nodist)} ({nodist.state_final.value_counts().to_dict()}); gazetteer no district "
               f"{int(gz.district.isna().sum())}; India Post PINs not in facts.pins {len(miss)} {st}; no state {no_state}",
               "0", "engine.area() snaps a lat/lon to the nearest facts.pins PIN (engine.py:299), so a dropped PIN is "
               "answered with its neighbour's district rather than failing; the impact is a wrong area, not no answer.",
               nodist.unique_id.head(2).tolist() + miss[:3])


# ------------------------------------------------------------------ hunts
def check_h_gazetteer_pins_not_india_post():
    """PINs in pin_gazetteer (and so in packs, the offline picker and pin_index) that India Post does not list."""
    gz = pq("pin_gazetteer.parquet")
    ip = set(pd.read_parquet(ROOT / "data/raw/india_post_pincode_directory.parquet", columns=["pincode"]).pincode.astype(int))
    extra = gz[~gz.pin.isin(ip)]
    in_pack = {int(x) for p in packs().values() for x in unpack(p)["pin"]}
    ex_pack = extra[extra.pin.isin(in_pack)]
    n_fac = extra.n_fac.fillna(0)
    return res("h_gazetteer_pins_not_india_post", "pass",
               f"{len(extra)}/{len(gz)} gazetteer PINs not in India Post; {len(ex_pack)} of them in packs; src "
               f"{extra.src.value_counts().to_dict()}; with >=1 facility {int((n_fac > 0).sum())}",
               "documented", "Documented repair R2 in cleaning/geo_identity/s1_pin_gazetteer.py:13 (facility PINs missing "
               "from the directory, placed at facility consensus or 3-digit-prefix median). Not an issue.",
               [f"{r.pin} {r.state} {r.district} src={r.src} n_fac={r.n_fac}" for r in ex_pack.head(5).itertuples()])


def check_h_export_staleness():
    """Exports carry the current derived/v1 values: pack scores and planner p equal data_point_scores."""
    d = pq("data_point_scores.parquet")
    d = d[d.dp_type == "service_claim"].set_index(["unique_id", "service"])
    inv = {v: k for k, v in APP.items()}
    bad_pack = n_pack = 0
    for k, p in packs().items():
        dp = unpack(p)
        uids = [uid8()[x] for x in p["fac"]["uid8"]]
        for e in range(len(p["ev"]["s"])):
            key = (uids[dp["f"][e]], inv[p["services"][p["ev"]["s"][e]]])
            n_pack += 1
            if key not in d.index or round(d.loc[key, "score"] * 100) != p["ev"]["p"][e]:
                bad_pack += 1
    pl = jgz("planner/out/planner_v1.json.gz")
    caps = {c["id"]: c.get("kb_service") for c in json.loads((ROOT / "kb/pathways/capabilities.json").read_text())["capabilities"]
            if c.get("kb_status") == "existing"}
    bad_pl = n_pl = 0
    for c, v in pl["capabilities"].items():
        if c not in caps:
            continue
        for i, p in zip(v["i"], v["p"]):
            n_pl += 1
            key = (pl["facilities"]["id"][i], caps[c])
            if key not in d.index or abs(d.loc[key, "score"] - p) > 1e-3:
                bad_pl += 1
    return res("h_export_staleness", "fail" if bad_pack or bad_pl else "pass",
               f"pack ev p mismatches {bad_pack}/{n_pack}; planner p mismatches {bad_pl}/{n_pl}", "0",
               "derived/v1 data_point_scores mtime 14:06; packs/facts/planner built 16:12-16:31 the same day.")


def check_h_manifest_rowcounts():
    man = json.loads((V1 / "MANIFEST.json").read_text())["tables"]
    bad = []
    for t, meta in man.items():
        n = len(pd.read_parquet(V1 / t, columns=[]) if t.endswith(".parquet") else pd.read_csv(V1 / t))
        sz = (V1 / t).stat().st_size
        if n != meta["rows"] or sz != meta["bytes"]:
            bad.append(f"{t}: manifest {meta['rows']} rows {meta['bytes']} B, file {n} rows {sz} B")
    return res("h_manifest_rowcounts", "fail" if bad else "pass", f"{len(man) - len(bad)}/{len(man)} tables match",
               "all", "", bad)


def check_h_pin_index_vs_gazetteer():
    pi = json.loads((ROOT / "app/packs/out/pin_index.json").read_text())
    pins = set(np.cumsum(pi["pin"]).astype(int))
    gz = pq("pin_gazetteer.parquet").dropna(subset=["state", "lat", "lon"])
    return res("h_pin_index_vs_gazetteer", "pass" if pins == set(gz.pin) else "fail",
               f"pin_index {len(pins)} vs gazetteer-with-state {len(gz)}", "equal", "")


def check_h_vet_not_flagged():
    """Animal-care records the name rule misses (claims that talk about dogs/cats/pets, not PET imaging)."""
    t = q(f"""select c.unique_id, r.name, r.trust_level, count(*) n from '{V1}/claims.parquet' c
              join '{V1}/record_trust.parquet' r using (unique_id)
              where regexp_matches(c.text, '(?i)\\b(veterinar\\w*|dogs?|cats|canine|feline|pets)\\b')
              and r.trust_level <> 'exclude_review' group by all having count(*) >= 3 order by n desc""")
    return res("h_vet_not_flagged", "warn" if len(t) else "pass", f"{len(t)} non-excluded records with >= 3 animal sentences",
               "0", "Manual read needed; candidates only.", [f"{r.unique_id} {r.name} n={r.n}" for r in t.itertuples()])


ALL = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]


def run_all() -> list[dict]:
    OUT.mkdir(exist_ok=True)
    out = []
    for fn in ALL:
        t0 = time.time()
        try:
            r = fn()
        except Exception as e:  # a crash is a result, not a silent skip
            r = res(fn.__name__[6:], "fail", "crashed", "runs", f"{type(e).__name__}: {e}")
        r["seconds"] = round(time.time() - t0, 1)
        out.append(r)
        print(f"[{r['status']}] {r['name']}: {r['metric']}\n    {r['detail'][:900]}\n    ex={r['examples']}", flush=True)
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    run_all()

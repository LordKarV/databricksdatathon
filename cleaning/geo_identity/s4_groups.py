"""Step 4: duplicate groups and co-located units. Records are linked, never merged or deleted:
each copy keeps its own cited text, and the app shows one card per group ('listed N times').

Candidate pairs (blocking): same name + city, same name + PIN, < 0.2 km apart, or a shared
'specific' contact (a phone held by records in fewer than 3 cities and by <= 5 records, or an
official domain on <= 5 records that is not a directory). Directory numbers (ID5) never link.
Rules on a pair (identity audit R5, its tier 2, plus the verifier's third path for abbreviations):
  dup R5   token_set >= 95 and (contact or address sim >= 70 or same city), and same city, PIN or < 5 km
  dup T2   contact and token_set >= 90 and (same city or < 5 km)
  soft T3  contact and < 0.5 km and (acronym match or a shared distinctive name word, ratio >= 85)
  unit U   contact and < 0.5 km and address sim >= 70 but no shared name word -> 'co-located', not merged
T3 is a soft 'possibly the same site' link (65% precision on the verifier's pairs), not a merge.
Distances use the step-2 resolved points, so copied geocodes do not make two towns look close.
Groups are connected components of R5/T2 edges. The canonical copy is the one with the best
location confidence (from step 2), then the most claim items.
Writes facility_groups.parquet, group_pairs.parquet, s4_stats.json.
"""
import itertools
import json
import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

import importlib.util

from common import OUT, ROOT, hav_km

# audit/identity/common.py shares this package's module name, so load it by path
_spec = importlib.util.spec_from_file_location("identity_common", ROOT / "audit/identity/common.py")
_ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ic)
domain, load, norm_phone = _ic.domain, _ic.load, _ic.norm_phone

DIRECTORY_HOSTS = re.compile(r"(practo|justdial|business\.site|facebook|g\.page|google|instagram|lybrate|sulekha|"
                             r"hexahealth|bajajfinserv|eka\.care|wikipedia|indiamart|linkedin|youtube|twitter|x\.com|"
                             r"blogspot|wordpress|wixsite|placestars|quickerala|medindia|skedoc|credihealth)")
GENERIC = {"hospital", "hospitals", "clinic", "centre", "center", "multi", "speciality", "specialty", "super",
           "nursing", "home", "dental", "care", "medical", "health", "healthcare", "and", "the", "of", "dr", "research"}
LAB = ROOT / "audit/identity"


def initials(name):
    return "".join(t[0] for t in name.split() if t not in {"and", "of", "the"})


def acronym(a, b):
    ia, ib = initials(b), initials(a)
    ta = [t for t in a.split() if len(t) >= 3 and t.isalpha() and t not in GENERIC]
    tb = [t for t in b.split() if len(t) >= 3 and t.isalpha() and t not in GENERIC]
    return any(t in ia for t in ta if len(ia) >= 3) or any(t in ib for t in tb if len(ib) >= 3)


def shared_token(a, b):
    """A distinctive (non-generic) name word shared by both names, allowing spelling variants."""
    ta = [t for t in a.split() if len(t) >= 3 and t not in GENERIC]
    tb = [t for t in b.split() if len(t) >= 3 and t not in GENERIC]
    return any(fuzz.ratio(x, y) >= 85 for x in ta for y in tb)


def main():
    df = load().drop_duplicates("unique_id").reset_index(drop=True)
    loc = pd.read_parquet(OUT / "facility_location.parquet").set_index("unique_id")
    st = {"records": len(df)}
    df["phones"] = [sorted({norm_phone(p)[0] for p in ([o] if o else []) + l if norm_phone(p)[1] != "invalid"})
                    for o, l in zip(df.officialPhone, df.phone_numbers_l)]
    ex = df[["phones", "ncity"]].explode("phones").dropna(subset=["phones"])
    ph_cities = ex.groupby("phones").ncity.nunique()
    ph_n = ex.groupby("phones").size()
    specific_ph = set(ph_n[(ph_n <= 5) & (ph_cities < 3)].index)
    df["dom"] = df.officialWebsite.map(domain)
    dom_n = df.dom.value_counts()
    ok_dom = set(dom_n[dom_n <= 5].index) - {d for d in dom_n.index if DIRECTORY_HOSTS.search(d)}
    st["phones_specific_vs_all"] = [len(specific_ph), len(ph_n)]

    pairs = set()

    def block(keys):
        for _, idx in pd.Series(range(len(df))).groupby(keys).groups.items():
            if 2 <= len(idx) <= 30:
                pairs.update(itertools.combinations(sorted(idx), 2))

    has_name = df.nname.ne("")
    block(np.where(has_name & df.ncity.ne(""), df.nname + "|" + df.ncity, pd.Series(range(len(df))).astype(str)))
    block(np.where(has_name & df.pin.notna(), df.nname + "|" + df.pin.fillna(""), pd.Series(range(len(df))).astype(str)))
    sp = df[["phones"]].explode("phones").dropna()
    sp = sp[sp.phones.isin(specific_ph)]
    for _, idx in sp.groupby("phones").groups.items():
        pairs.update(itertools.combinations(sorted(set(idx)), 2))
    d2 = df[df.dom.isin(ok_dom)]
    for _, idx in d2.groupby("dom").groups.items():
        pairs.update(itertools.combinations(sorted(idx), 2))
    la, lo = df.latitude.to_numpy(float), df.longitude.to_numpy(float)
    for s in range(0, len(df), 600):
        d = hav_km(la[s:s + 600, None], lo[s:s + 600, None], la, lo)
        ii, jj = np.where(d < 0.2)
        pairs.update((s + i, j) for i, j in zip(ii, jj) if s + i < j)
    st["candidate_pairs"] = len(pairs)
    rla = df.unique_id.map(loc.loc_lat).to_numpy(float)
    rlo = df.unique_id.map(loc.loc_lon).to_numpy(float)

    rows = []
    for i, j in pairs:
        a, b = df.iloc[i], df.iloc[j]
        tset = fuzz.token_set_ratio(a.nname, b.nname)
        km = float(hav_km(rla[i], rlo[i], rla[j], rlo[j]))  # resolved points: copied geocodes (ID4) must not look close
        phone = bool(set(a.phones) & set(b.phones) & specific_ph)
        dom = bool(a.dom) and a.dom == b.dom and a.dom in ok_dom
        addr = fuzz.token_set_ratio(str(a.address_line1 or "").lower(), str(b.address_line1 or "").lower())
        same_city = bool(a.ncity) and a.ncity == b.ncity
        contact = phone or dom
        acr = acronym(a.nname, b.nname)
        tok = shared_token(a.nname, b.nname)
        same_place = same_city or km < 5 or (a.pin is not None and a.pin == b.pin)
        rule = ("R5" if tset >= 95 and (contact or addr >= 70 or same_city) and same_place else
                "T2" if contact and tset >= 90 and (same_city or km < 5) else
                "T3" if contact and km < 0.5 and (acr or tok) else
                "U" if contact and km < 0.5 and addr >= 70 else None)
        if rule:
            rows.append(dict(uid_a=a.unique_id, uid_b=b.unique_id, rule=rule, tset=tset, km=round(km, 3), phone=phone,
                             dom=dom, addr=addr, same_city=same_city, acronym=acr))
    P = pd.DataFrame(rows)
    st["linked_pairs_by_rule"] = P.rule.value_counts().to_dict()

    # union-find over duplicate edges only
    parent = {u: u for u in df.unique_id}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in P[P.rule.isin(["R5", "T2"])].itertuples():
        parent[find(r.uid_a)] = find(r.uid_b)
    df["root"] = df.unique_id.map(find)
    size = df.root.map(df.root.value_counts())
    conf_rank = df.unique_id.map(loc.loc_conf).map({"high": 0, "medium": 1, "low": 2, "disputed": 3, "none": 4})
    n_claims = df.procedure_l.map(len) + df.capability_l.map(len) + df.equipment_l.map(len)
    order = df.assign(cr=conf_rank, nc=-n_claims).sort_values(["root", "cr", "nc"])
    canon = order.drop_duplicates("root").set_index("root").unique_id
    df["dup_group_id"] = np.where(size > 1, df.root.map(canon), None)
    df["is_canonical"] = (size == 1) | (df.unique_id == df.root.map(canon))
    df["group_size"] = size
    soft = P[P.rule == "T3"]
    so = pd.concat([soft[["uid_a", "uid_b"]], soft[["uid_b", "uid_a"]].set_axis(["uid_a", "uid_b"], axis=1)])
    df["possible_same_site"] = df.unique_id.map(so.groupby("uid_a").uid_b.agg(list)).map(lambda x: x if isinstance(x, list) else [])
    units = P[P.rule == "U"]
    co = pd.concat([units[["uid_a", "uid_b"]], units[["uid_b", "uid_a"]].set_axis(["uid_a", "uid_b"], axis=1)])
    df["co_located_with"] = df.unique_id.map(co.groupby("uid_a").uid_b.agg(list)).map(lambda x: x if isinstance(x, list) else [])
    # copies that disagree on location (ID3): spread of the group's raw coordinates
    g = df[size > 1].assign(lat=lambda d: d.latitude.astype(float), lon=lambda d: d.longitude.astype(float))
    gm = g.groupby("root")[["lat", "lon"]].median()
    g = g.join(gm.set_axis(["mla", "mlo"], axis=1), on="root")
    g["d"] = hav_km(g.lat, g.lon, g.mla, g.mlo)
    far_groups = set(g[g.d > 25].root)
    df["group_location_disagrees"] = df.root.isin(far_groups) & (size > 1)
    st["groups"] = int((df.groupby("root").size() > 1).sum())
    st["records_in_groups"] = int((size > 1).sum())
    st["records_marked_non_canonical"] = int((~df.is_canonical).sum())
    st["largest_group"] = int(size.max())
    st["groups_whose_copies_are_gt25km_apart"] = len(far_groups)
    st["records_with_possible_same_site_link"] = int((df.possible_same_site.map(len) > 0).sum())
    st["records_with_co_located_unit"] = int((df.co_located_with.map(len) > 0).sum())

    st["eval"] = evaluate(df, P)
    out = df[["unique_id", "name", "dup_group_id", "is_canonical", "group_size", "possible_same_site", "co_located_with",
              "group_location_disagrees"]]
    out.to_parquet(OUT / "facility_groups.parquet", index=False)
    P.to_parquet(OUT / "group_pairs.parquet", index=False)
    (OUT / "s4_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps(st, indent=1, default=str))


def evaluate(df, P):
    """Score against the identity audit's hand labels (positive = same physical facility).
    These labels were made on candidate sets the rules were designed from, so the numbers are in-sample."""
    grp = df.set_index("unique_id").root
    unit_pairs = {frozenset(x) for x in P[P.rule == "U"][["uid_a", "uid_b"]].values}
    soft_pairs = {frozenset(x) for x in P[P.rule == "T3"][["uid_a", "uid_b"]].values}

    def predicted(a, b):
        if grp.get(a) is not None and grp.get(a) == grp.get(b):
            return "dup"
        if frozenset((a, b)) in soft_pairs:
            return "soft"
        return "unit" if frozenset((a, b)) in unit_pairs else "none"

    out = {}
    # 1) 47 strong-key groups: one representative uid per group; members from the audit's dup_groups.csv
    lab = pd.read_csv(LAB / "labels/strong_groups_hand.csv")
    dg = pd.read_csv(LAB / "out/dup_groups.csv")[["unique_id", "grp_strong"]].dropna()
    mem = dg.groupby("grp_strong").unique_id.agg(list)
    u2g = dict(zip(dg.unique_id, dg.grp_strong))
    res = []
    for r in lab.itertuples():
        ids = mem[u2g[r.unique_id]]
        preds = {predicted(a, b) for a, b in itertools.combinations(ids, 2)}
        res.append((r.label, "dup" if "dup" in preds else "soft" if "soft" in preds else "unit" if "unit" in preds else "none"))
    out["strong_groups_47"] = confusion(res, positive={"true_dup"}, unit_ok={"same_site_unit"})
    # 2) verifier's 42 near-contact pairs (abbreviation and rebrand duplicates, co-located units)
    v = pd.read_csv(LAB / "verify/v_near_contact_hand.csv")
    res = [(r.label, predicted(r.uid_a, r.uid_b)) for r in v.itertuples()]
    out["near_contact_pairs_42"] = confusion(res, positive={"true_dup"}, unit_ok={"same_site_unit"})
    out["near_contact_labels"] = v.label.value_counts().to_dict()
    return out


def confusion(res, positive, unit_ok):
    """Scores the hard merge (dup) and, separately, merge-or-soft-link (dup or soft)."""
    hard = _conf(res, positive, unit_ok, {"dup"})
    hard["with_soft_links"] = _conf(res, positive, unit_ok, {"dup", "soft"})
    return hard


def _conf(res, positive, unit_ok, yes):
    res = [(lab, "dup" if p in yes else p) for lab, p in res]
    tp = sum(1 for lab, p in res if lab in positive and p == "dup")
    fn = sum(1 for lab, p in res if lab in positive and p != "dup")
    fp = sum(1 for lab, p in res if lab not in positive | unit_ok and p == "dup")
    unit_hit = sum(1 for lab, p in res if lab in unit_ok and p in {"unit", "dup"})
    unit_total = sum(1 for lab, _ in res if lab in unit_ok)
    merged_units = sum(1 for lab, p in res if lab in unit_ok and p == "dup")
    return {"n": len(res), "tp": tp, "fp": fp, "fn": fn, "precision": round(tp / max(tp + fp, 1), 2),
            "recall": round(tp / max(tp + fn, 1), 2), "units_linked": [unit_hit, unit_total],
            "units_wrongly_merged": merged_units}


if __name__ == "__main__":
    assert acronym("aiims patna", "all india institute medical sciences patna")
    assert not acronym("city hospital", "care clinic")
    assert shared_token("eras bharati hospital", "bharti children cardiac diabetic hospital")
    assert not shared_token("lotus ent", "kgp hospital")
    main()

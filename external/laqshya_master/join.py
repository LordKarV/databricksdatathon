"""Inspect the parsed LaQshya table and join it to the Virtue Foundation facilities.

Usage: python -I join.py <laqshya_data_dir> <project_root>

Reads <laqshya_data_dir>/laqshya.parquet (from parse.py). Uses, read-only:
cleaning/geo_identity/facility_location.parquet (state_final, district per VF row) and
cleaning/claims/out/grades.parquet (which VF rows claim which service).
Writes laqshya_facilities.parquet, laqshya_vf_matches.parquet, join_stats.json and
handcheck_sample.csv into <laqshya_data_dir>.

LaQshya has no PIN or coordinates, so the gate is state (exact) plus district or
place agreement; the name test runs on the place-like tokens left after removing
generic public-hospital words, in both directions, so "SDH Kadiri" does not match
"Sri Sai Hospital Kadiri".
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

AS_OF = pd.Timestamp("2026-11-21")   # day of the check; validity is judged against this
CORE_MIN = 88                         # token_sort_ratio on core tokens
DIST_MIN = 85                         # ratio on district names
SEED = 7
CLAIM_GRADES = {"strong", "moderate", "weak", "tag_only"}

ABBR = {r"\bdh\b": "district hospital", r"\bsdh\b": "sub district hospital",
        r"\bchc\b": "community health centre", r"\bphc\b": "primary health centre",
        r"\buphc\b": "urban primary health centre",
        r"\bfru\b": "", r"\bgovt\b": "government", r"\bgovernment\b": "government",
        r"\bhosp\b": "hospital", r"\bdist\b": "district", r"\bsub div\b": "sub divisional",
        r"\bcentre\b": "center", r"\bmedcial\b": "medical", r"\bhq\b": "headquarters",
        r"\bdhh\b": "district headquarters hospital", r"\bsdch\b": "sub divisional hospital"}
# LaQshya-only expansions: in VF names "CH" or "AH" are as often private brand initials.
ABBR_LQ = {r"\bah\b": "area hospital", r"\bch\b": "civil hospital", r"\bmch\b": "mother child hospital",
           r"\bgh\b": "general hospital", r"\bmc\b": "medical college", r"\bth\b": "taluk hospital",
           r"\bdwh\b": "district women hospital", r"\bdch\b": "district civil hospital", r"\bzh\b": "zonal hospital"}
GENERIC = set("""district hospital sub divisional division community health center primary urban general
area civil mother child children women womens maternity government taluk taluka headquarters headquarter
sadar referral medical college and institute science sciences research the of model level first unit
memorial combined joint state city rural block new old upgraded ug mcwh wing teaching superspeciality zonal
super specialty speciality multi nagar""".split())
PUBLIC_MARK = re.compile(r"district|sub divisional|sub district|community health|primary health|government|"
                         r"civil hospital|sadar|general hospital|area hospital|taluk|medical college|"
                         r"referral|mother child|women hospital|esi|municipal|headquarters|combined hospital")
KINDS = [("mc", r"medical college|institute of medical|medical science"),
         ("mch", r"mother child|women|maternity|mcwh|matru"),
         ("chc", r"community health|primary health"),
         ("sdh", r"sub divisional|sub district|area hospital|taluk|subdivisional"),
         ("dh", r"district|sadar|civil hospital|general hospital|headquarters|combined hospital")]


def norm(s, lq=False):
    s = str(s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    for k, v in ({**ABBR_LQ, **ABBR} if lq else ABBR).items():
        s = re.sub(k, v, s)
    return re.sub(r"\s+", " ", s).strip()


def core(n):
    return " ".join(t for t in n.split() if t not in GENERIC and len(t) > 1)


def kind(n):
    return next((k for k, pat in KINDS if re.search(pat, n)), None)


def kinds_ok(a, b):
    # ponytail: DH vs SDH is often blurred (an upgraded SDH listed as DH); every other kind is kept apart.
    # pandas stores a missing kind as NaN, not None, so test for str.
    if not (isinstance(a, str) and isinstance(b, str)):
        return True
    return a == b or {a, b} == {"dh", "sdh"}


def state_key(s):
    s = str(s or "").upper().replace("&", "AND")
    s = re.sub(r"[^A-Z]", "", s)
    return {"DNHDANDD": "THEDADRAANDNAGARHAVELIANDDAMANANDDIU"}.get(s, s)


def inspect(lq):
    st = {"rows": len(lq), "pages": int(lq.page.nunique())}
    st["blank_rate"] = {c: round(float((lq[c].astype(str).str.strip().isin(["", "nan", "NaT", "None"])).mean()), 4)
                        for c in lq.columns}
    st["dept"] = lq.dept.replace("", "(blank)").value_counts().to_dict()
    st["status"] = lq.status.value_counts().to_dict()
    st["ftype"] = lq.ftype.value_counts().to_dict()
    st["states"] = int(lq.state.nunique())
    st["date_result_range"] = [str(lq.date_result.min().date()), str(lq.date_result.max().date())]
    st["date_validity_range"] = [str(lq.date_validity.min().date()), str(lq.date_validity.max().date())]
    span = (lq.date_validity - lq.date_result).dt.days
    st["validity_span_days"] = span.round(-1).value_counts().head(6).to_dict()
    st["validity_before_result_rows"] = lq.loc[span < 0, "sno"].tolist()
    st["valid_on_as_of"] = int((lq.date_validity >= AS_OF).sum())
    st["valid_on_as_of_by_dept"] = lq[lq.date_validity >= AS_OF].dept.replace("", "(blank)").value_counts().to_dict()
    key = ["state", "district", "name", "dept", "status", "date_result"]
    st["exact_duplicate_rows"] = int(lq.duplicated(key).sum())
    st["unique_facilities_state_district_name"] = int(lq.drop_duplicates(["state", "district", "name"]).shape[0])
    st["rows_by_result_year"] = lq.date_result.dt.year.value_counts().sort_index().to_dict()
    return st


def facilities(lq):
    """One row per (state, district, name); latest certificate per department."""
    lq = lq.assign(dept=lq.dept.replace("", "Unspecified"))
    last = lq.sort_values("date_result").groupby(["state", "district", "name", "dept"]).tail(1)
    key = ["state", "district", "name"]
    wide = last.pivot_table(index=key, columns="dept", values="date_validity", aggfunc="max").reset_index()
    wide.columns = [str(c) for c in wide.columns]
    g = lq.groupby(key)
    extra = pd.DataFrame({"ftype": g.ftype.agg(lambda s: s.mode().iloc[0]),
                          "snos": g.sno.apply(lambda s: [int(x) for x in s])}).reset_index()
    fac = wide.merge(extra, on=key)
    return fac.reset_index(drop=True).assign(lq_id=lambda d: d.index)


def match(fac, vf):
    vf = vf.assign(n=vf.name.map(norm))
    vf = vf.assign(c=vf.n.map(core), k=vf.n.map(kind), sk=vf.state_final.map(state_key),
                   city=vf.address_city.fillna("").str.lower(), dist=vf.district.fillna("").str.lower(),
                   public=vf.n.str.contains(PUBLIC_MARK))
    by_state = dict(tuple(vf.groupby("sk")))
    out = []
    for r in fac.itertuples():
        n = norm(f"{r.ftype} {r.name}", lq=True)
        c, k, d = core(n), kind(n), r.district.lower()
        cand = by_state.get(state_key(r.state))
        if cand is None:
            continue
        for v in cand.itertuples():
            dist_ok = fuzz.ratio(d, v.dist) >= DIST_MIN or (d and d in v.dist) or (v.dist and v.dist in d)
            # A VF name with no place word ("District Hospital", "Sadar Hospital") takes its city as the place,
            # but only when the name says what kind of hospital it is ("J N Hospital" or "Hospital A" do not).
            vc = v.c or (v.city if isinstance(v.k, str) else "")
            if not c:      # "District Hospital" alone: the district is the place token
                c_eff, vc_eff = d, vc
            else:
                c_eff, vc_eff = c, vc
            if not vc_eff or not kinds_ok(k, v.k) or not (v.public or v.operatorTypeId == "public"):
                continue
            s = fuzz.token_sort_ratio(c_eff, vc_eff)
            vt, lt = set(vc_eff.split()), set(c_eff.split())
            # VF core inside the LaQshya core, and whatever LaQshya adds is only the district name:
            # keeps "SDH Benipur Darbhanga" = "Benipur SDH", rejects "Aland TH Gulbarga" = "GH Gulbarga".
            subset = bool(vt) and vt <= lt and (lt - vt) <= set(d.split())
            place_ok = dist_ok or any(t in v.city for t in c_eff.split() if len(t) > 3)
            same_name = fuzz.ratio(n, v.n) >= 95     # e.g. "Capital Hospital": district spelling may differ
            if ((s >= CORE_MIN or subset) and place_ok) or same_name:
                out.append(dict(lq_id=r.lq_id, lq_state=r.state, lq_district=r.district, lq_type=r.ftype,
                                lq_name=r.name, unique_id=v.unique_id, vf_name=v.name, vf_city=v.address_city,
                                vf_district=v.district, vf_operator=v.operatorTypeId, core_score=round(s, 1),
                                subset=subset, district_ok=bool(dist_ok), vf_public_name=bool(v.public)))
    return pd.DataFrame(out)


def service_table(fac, m, grades):
    claims = grades[grades.service == "csection"].set_index("unique_id").grade
    pairs = m[["lq_id", "unique_id"]].drop_duplicates().assign(g=lambda x: x.unique_id.map(claims))
    per = pairs.groupby("lq_id").g.agg(lambda s: next((g for g in ("strong", "moderate", "weak", "tag_only")
                                                       if g in set(s)), s.dropna().iloc[0] if s.notna().any() else None))
    f = fac.set_index("lq_id").loc[per.index]
    mot = f.get("Maternity OT")
    res = {}
    for label, mask in (("mot_any", mot.notna()), ("mot_valid_as_of", mot >= AS_OF),
                        ("labour_room_only", mot.isna())):
        g = per[mask.values]
        res[label] = {"matched_lq_facilities": int(len(g)),
                      "vf_claims_csection": int(g.isin(CLAIM_GRADES).sum()),
                      "vf_claim_grades": g.value_counts().to_dict(),
                      "vf_silent": int(g.isna().sum())}
    return res


def main():
    d, root = Path(sys.argv[1]), Path(sys.argv[2])
    lq = pd.read_parquet(d / "laqshya.parquet")
    loc = pd.read_parquet(root / "cleaning/geo_identity/facility_location.parquet")
    raw = pd.read_parquet(root / "data/raw/facilities.parquet").drop_duplicates("unique_id")
    vf = loc[["unique_id", "name", "address_city", "state_final", "district"]].merge(
        raw[["unique_id", "operatorTypeId"]], on="unique_id", how="left")
    grades = pd.read_parquet(root / "cleaning/claims/out/grades.parquet")

    stats = {"inspect": inspect(lq)}
    fac = facilities(lq)
    fac.to_parquet(d / "laqshya_facilities.parquet")
    m = match(fac, vf)
    m.to_parquet(d / "laqshya_vf_matches.parquet")

    pub = vf.operatorTypeId.eq("public")
    vpub = vf.name.map(norm).str.contains(PUBLIC_MARK)
    stats["match"] = {
        "lq_facilities": len(fac), "lq_facilities_matched": int(m.lq_id.nunique()),
        "match_rate": round(m.lq_id.nunique() / len(fac), 4),
        "vf_rows": len(vf), "vf_rows_matched": int(m.unique_id.nunique()), "pairs": len(m),
        "lq_with_2plus_vf": int((m.groupby("lq_id").unique_id.nunique() > 1).sum()),
        "vf_with_2plus_lq": int((m.groupby("unique_id").lq_id.nunique() > 1).sum()),
        "vf_operator_public": int(pub.sum()),
        "vf_operator_public_matched": int(vf.loc[pub, "unique_id"].isin(m.unique_id).sum()),
        "vf_public_named": int(vpub.sum()),
        "vf_public_named_matched": int(vf.loc[vpub, "unique_id"].isin(m.unique_id).sum()),
        "matched_vf_operator": m.drop_duplicates("unique_id").vf_operator.fillna("NaN").value_counts().to_dict(),
    }
    stats["csection_vs_vf"] = service_table(fac, m, grades)
    (d / "join_stats.json").write_text(json.dumps(stats, indent=1, default=str))

    best = m.sort_values(["core_score"], ascending=False).drop_duplicates("lq_id")
    sample = best.sample(min(20, len(best)), random_state=SEED)
    sample.to_csv(d / "handcheck_sample.csv", index=False)
    pd.set_option("display.width", 250)
    print(sample[["lq_state", "lq_district", "lq_type", "lq_name", "vf_name", "vf_city", "vf_district",
                  "core_score", "subset"]].to_string())
    print(json.dumps({k: stats[k] for k in ("match", "csection_vs_vf")}, indent=1, default=str))


if __name__ == "__main__":
    main()

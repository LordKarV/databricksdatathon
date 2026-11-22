"""Completeness critic: quick checks that confirm gaps the other validation areas leave open.

Read-only over every data layer. Each check_<name>() returns dict(name, status, metric, threshold, detail,
examples). Run: .venv-viz/bin/python validation/critic/checks.py
"""
import gzip
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "derived/v1"


def result(name, status, metric, threshold, detail, examples):
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail,
            "examples": examples[:5]}


def _num(s: str) -> int:
    return int(s.replace(",", ""))


def _how() -> dict:
    return json.loads((ROOT / "app/howto/out/how.json").read_text())


def _cell(how: dict, table: str, row_prefix: str) -> str:
    return next(r[1] for r in how["tables"][table]["rows"] if r[0].startswith(row_prefix))


def _usable_records() -> pd.DataFrame:
    return pd.read_parquet(V1 / "facility_location.parquet")


def check_report_numbers_shown_in_app() -> dict:
    """REPORT.md tables are copied verbatim into app/howto/out/how.json (the app's "How this works" page)
    and into notebook sections 2 and 3. Recompute the countable cells from derived/v1."""
    how = _how()
    loc = _usable_records()
    claims = pd.read_parquet(V1 / "claims.parquet", columns=["unique_id", "attribution"])
    d = loc.raw_coords_to_pin_km.dropna()
    cells = []  # (where, stated, recomputed)

    f_loc = _cell(how, "findings", "Listing coordinates")
    m = re.search(r"([\d,]+) / ([\d,]+) more than 50 km.*?\(([\d,]+) more than 100 km\)", f_loc)
    cells.append(("findings: far >50 km", f"{m[1]}/{m[2]}", f"{int((d > 50).sum())}/{len(d)}"))
    cells.append(("findings: far >100 km", m[3], str(int((d > 100).sum()))))
    m = re.search(r"([\d,]+) of ([\d,]+) conflict", _cell(how, "flagged", "Coordinates more than 50 km"))
    cells.append(("flagged: far >50 km", f"{m[1]}/{m[2]}", f"{int((d > 50).sum())}/{len(d)}"))

    m = re.search(r"About ([\d,]+) / ([\d,]+) name another", _cell(how, "findings", "Records hold text"))
    n_other = claims.loc[claims.attribution == "other_facility", "unique_id"].nunique()
    cells.append(("findings: records naming another facility", f"{m[1]}/{m[2]}", f"{n_other}/{len(loc)}"))

    m = re.search(r"([\d,]+) / ([\d,]+) with", _cell(how, "fixed", "District and NFHS join"))
    cells.append(("fixed: district and NFHS join", f"{m[1]}/{m[2]}",
                  f"{int(loc.nfhs_district_name.notna().sum())}/{len(loc)}"))

    m = re.search(r"Bihar: ([\d,]+) of ([\d,]+) records, ([\d,]+) in Patna", _cell(how, "cannot", "Thin rural"))
    bihar = loc[loc.state_final.str.upper() == "BIHAR"]
    cells.append(("cannot: Bihar records", f"{m[1]}/{m[2]}", f"{len(bihar)}/{len(loc)}"))
    cells.append(("cannot: Patna records", m[3], str(int((bihar.district.str.upper() == "PATNA").sum()))))

    m = re.search(r"([\d,]+) records", _cell(how, "cannot", "Arrays truncated"))
    gr = pd.read_parquet(V1 / "grades.parquet", columns=["unique_id", "truncated"])
    cells.append(("cannot: records with a truncated array", m[1],
                  f"{gr.loc[gr.truncated.astype(bool), 'unique_id'].nunique()} graded"))

    tr = pd.read_parquet(V1 / "record_trust.parquet", columns=["trust_flags", "website_class"])
    flags = Counter(x for fl in tr.trust_flags if fl is not None for x in fl)
    web = tr.website_class.fillna("none").value_counts()
    stated_web = dict(re.findall(r"(own|directory|government|social|none) ([\d,]+)", _cell(how, "flagged", "Website")))
    for k, v in stated_web.items():
        cells.append((f"flagged: website {k}", v, str(int(web.get(k, 0)))))
    for row, flag in [("Disputed location", "location_disputed"), ("Veterinary", "veterinary"),
                      ("Claims 6 or more", "claims_6plus_of_8_services")]:
        cells.append((f"flagged: {row}", re.search(r"[\d,]+", _cell(how, "flagged", row))[0], str(flags[flag])))
    cells.append(("fixed: directory phones", re.search(r"[\d,]+", _cell(how, "fixed", "Directory phones"))[0],
                  str(flags["official_phone_is_directory"])))

    def same(a, b):
        nums = lambda s: [_num(x) for x in re.findall(r"[\d,]*\d", s)]
        return nums(a) == nums(b)

    bad = [f"{w}: page says {s}, derived/v1 gives {r}" for w, s, r in cells if not same(s, r)]
    return result("report_numbers_shown_in_app", "fail" if bad else "pass",
                  f"{len(bad)} of {len(cells)} REPORT.md cells shown in the app/notebook disagree with derived/v1",
                  "0", "cells recomputed from derived/v1; a mismatch is shown to judges on the How page and in "
                  "notebook sections 2-3; the 50 km finding also disagrees with the Flagged row on the same page",
                  bad)


def _nb_text() -> list[str]:
    nb = json.loads((ROOT / "submission/referral_saathi.ipynb").read_text())
    out = []
    for c in nb["cells"]:
        txt = ""
        for o in c.get("outputs", []):
            txt += "".join(o.get("text", [])) + "".join(o.get("data", {}).get("text/plain", []))
        out.append(txt)
    return out


def check_notebook_outputs_current() -> dict:
    """The committed notebook outputs are what judges read on GitHub. Compare its printed numbers with the
    current exports and taxonomy."""
    txt = "\n".join(_nb_text())
    f = json.load(gzip.open(ROOT / "app/facts/out/facts.json.gz"))
    pairs = sum(len(v["id"]) if isinstance(v, dict) and "id" in v else len(v) for v in f["pairs"].values())
    lex = json.loads((ROOT / "kb/taxonomy/lexicon.json").read_text())
    tax = pd.read_csv(ROOT / "kb/taxonomy/specialty_map.csv", nrows=0)  # touch: file must exist
    how = _how()["facts"]
    loc = _usable_records().raw_coords_to_pin_km.dropna()
    rows = []
    m = re.search(r"engine loaded: ([\d,]+) facilities, ([\d,]+) facility-service pairs, ([\d,]+) quotable", txt)
    rows += [("engine facilities", _num(m[1]), len(f["fac"]["id"])), ("engine pairs", _num(m[2]), pairs),
             ("engine quotable sentences", _num(m[3]), len(f["claims"])),
             ("how.json app_pairs vs engine pairs", how["app_pairs"]["value"], pairs)]
    m = re.search(r"(\d+) services in the taxonomy", txt)
    rows.append(("services in the taxonomy (project and README say 36)", _num(m[1]), 36))
    rows.append(("lexicon.json services (what the cell counts)", len(lex["services"]), 36))
    m = re.search(r"([\d,]+) of ([\d,]+) map points are more than 50 km", txt)
    rows.append(("far pins printed", _num(m[1]), int((loc > 50).sum())))
    bad = [f"{k}: notebook/how {a}, current {b}" for k, a, b in rows if a != b]
    del tax
    return result("notebook_outputs_current", "fail" if bad else "pass",
                  f"{len(bad)} of {len(rows)} committed notebook numbers differ from current data",
                  "0", "submission/referral_saathi.ipynb saved outputs vs app/facts/out/facts.json.gz, "
                  "app/howto/out/how.json, kb/taxonomy/lexicon.json; no validation area opens the notebook", bad)


GOV = re.compile(r"\b(?:govt\.?|government|district hospital|civil hospital|sadar hospital|community health "
                 r"cent(?:re|er)|primary health cent(?:re|er)|\bphc\b|\bchc\b|sub[- ]?divisional hospital|"
                 r"sub[- ]?district hospital|aiims|esic?\b|municipal|railway hospital|"
                 r"rajkiya|zila|referral hospital)", re.I)
HOSP = re.compile(r"\bhospital\b", re.I)
CLINIC = re.compile(r"\b(?:clinic|dental|dentist)\b", re.I)


def check_type_operator_vs_name() -> dict:
    """facilityTypeId and operatorTypeId are extracted fields used as model features (type) and in the v2
    operator column. No area checks them against anything. Cue-based count of names that contradict them."""
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet",
                          columns=["unique_id", "name", "facilityTypeId", "operatorTypeId"])
    u = set(_usable_records().unique_id)
    r = raw[raw.unique_id.isin(u)].drop_duplicates("unique_id").fillna({"name": ""})
    gov_private = r[r.name.str.contains(GOV) & (r.operatorTypeId == "private")]
    gov_any = r[r.name.str.contains(GOV)]
    hosp_as_clinic = r[r.name.str.contains(HOSP) & ~r.name.str.contains(CLINIC) &
                       r.facilityTypeId.isin(["clinic", "dentist", "doctor"])]
    clinic_as_hosp = r[r.name.str.contains(CLINIC) & ~r.name.str.contains(HOSP) & (r.facilityTypeId == "hospital")]
    null_op = int(r.operatorTypeId.isna().sum() + (r.operatorTypeId == "null").sum())
    gov_private.to_csv(ROOT / "validation/critic/out/gov_name_private_operator.csv", index=False)
    pd.concat([hosp_as_clinic.assign(kind="hospital_name_clinic_type"),
               clinic_as_hosp.assign(kind="clinic_name_hospital_type")]).to_csv(
        ROOT / "validation/critic/out/type_vs_name.csv", index=False)
    ex = [f"{x.unique_id} '{x.name}' operator={x.operatorTypeId}" for x in gov_private.head(3).itertuples()]
    ex += [f"{x.unique_id} '{x.name}' type={x.facilityTypeId}" for x in hosp_as_clinic.head(2).itertuples()]
    return result("type_operator_vs_name", "warn",
                  f"government-named records typed private: {len(gov_private)} of {len(gov_any)}; "
                  f"public/government operator on {int(r.operatorTypeId.isin(['public', 'government']).sum())} "
                  f"of {len(r)}; operator null {null_op}; 'Hospital' names typed clinic/dentist/doctor "
                  f"{len(hosp_as_clinic)}; clinic/dental names typed hospital {len(clinic_as_hosp)}",
                  "hand-read precision of each cue before trusting type/operator as features",
                  "cue counts only (not hand-read); lists in validation/critic/out/", ex)


def check_dashboard_sources_vs_v1() -> dict:
    """The Databricks dashboard tables (tables.yaml group: dashboard) are loaded from model/proto and viz
    caches that no validation area opens. Compare them with derived/v1 and the app."""
    loc = _usable_records()[["unique_id", "state_final", "district"]]
    tr = pd.read_parquet(V1 / "record_trust.parquet", columns=["unique_id", "trust_flags"])
    vet = set(tr.loc[[f is not None and "veterinary" in list(f) for f in tr.trust_flags], "unique_id"])
    g = pd.read_parquet(ROOT / "viz/geography/data/_cache/facilities.parquet")
    p = pd.read_parquet(ROOT / "model/proto/fusion/pair_scores.parquet")
    f = json.load(gzip.open(ROOT / "app/facts/out/facts.json.gz"))
    issues = []
    mg = g.merge(loc, on="unique_id", how="outer", suffixes=("_viz", "_v1"), indicator=True)
    only = mg._merge.value_counts().to_dict()
    if only.get("left_only") or only.get("right_only"):
        issues.append(f"geo_facility ids differ from derived/v1: {only}")
    st = mg[(mg._merge == "both") & (mg.state_final_viz.fillna("") != mg.state_final_v1.fillna(""))]
    ds = mg[(mg._merge == "both") & (mg.district_viz.fillna("") != mg.district_v1.fillna(""))]
    if len(st) or len(ds):
        issues.append(f"geo_facility state differs on {len(st)}, district on {len(ds)} records "
                      f"(e.g. {ds.unique_id.head(3).tolist()})")
    vet_claimed = g[g.unique_id.isin(vet) & g.filter(like="_claimed").any(axis=1)]
    if len(vet_claimed):
        issues.append(f"{len(vet_claimed)} exclude_review (veterinary) records count as service claims in "
                      f"geo_facility: {vet_claimed.unique_id.head(3).tolist()}")
    vet_scored = p[p.unique_id.isin(vet)]
    if len(vet_scored):
        issues.append(f"pair_scores scores {vet_scored.unique_id.nunique()} veterinary records "
                      f"({len(vet_scored)} rows)")
    app_svc = {"burn_care": "burns", "cardiac_surgery": "cardiac_surgery", "dialysis": "dialysis",
               "emergency_csection": "csection", "mri": "mri", "nicu": "nicu", "trauma_emergency": "trauma"}
    pb = p[p.service.isin(set(app_svc) | set(app_svc.values()))].band.value_counts().to_dict()
    issues.append(f"pair_scores bands for the 7 app services {pb} (prototype model) vs app interim rule "
                  f"Likely on {_how()['facts']['app_likely']['value']} pairs: the dashboard and the app can "
                  "show different bands for the same pair")
    return result("dashboard_sources_vs_v1", "fail" if len(issues) > 1 else "warn",
                  f"{len(issues)} discrepancies", "0",
                  "sources: viz/geography/data/_cache/facilities.parquet (UC geo_facility), "
                  "model/proto/fusion/pair_scores.parquet (UC pair_scores); databricks/VERIFY.md checked row "
                  "counts and keys only", issues)


if __name__ == "__main__":
    (ROOT / "validation/critic/out").mkdir(parents=True, exist_ok=True)
    res = []
    for n, fn in list(globals().items()):
        if n.startswith("check_"):
            try:
                res.append(fn())
            except Exception as e:  # report, never hide
                res.append(result(n[6:], "fail", f"crashed: {type(e).__name__}: {e}", "", "", []))
            print(json.dumps(res[-1], indent=1, default=str))
    (ROOT / "validation/critic/out/results.json").write_text(json.dumps(res, indent=1, default=str))

"""Inspect the India Data Portal NFHS district CSV and join-test it.

Usage: python -I inspect_join.py <districtlevel-nfhs.csv> <state-level-nfhs.csv> <out_dir>

Join chain tested (read-only inputs from data/raw and audit/geo):
  IDP 2019-21 row  <-> data/raw/nfhs_5 parquet row  (state + normalised district name, fuzzy)
  matched pairs are value-checked on 6 indicators that both files carry (precision check)
  IDP district_code 2019-21 -> 2023-24 row (same LGD code)
  facility -> audit/geo/facility_district.parquet (PIN directory district) -> IDP 2023-24
    (a) via the audit's NFHS-5 district, (b) directly by directory district name.
Writes inspect_stats.json, nfhs5_idp_district_map.csv, handcheck_20.csv into out_dir and
facility_idp_district.csv next to the downloaded CSV (it carries facility ids).
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

ROOT = Path("/Users/karthikvattem/projects/datathon")
NFHS5 = ROOT / "data/raw/nfhs_5_district_health_indicators.parquet"
FAC = ROOT / "data/raw/facilities.parquet"
FAC_DIST = ROOT / "audit/geo/facility_district.parquet"
FUZZ_MIN = 85
# indicator pairs present in both files, used to confirm a name match is the same district
VALUE_PAIRS = {
    "births_c_section": "births_delivered_by_csection_5y_pct",
    "institutional_births": "institutional_birth_5y_pct",
    "women_high_blood_sugar_140plus": "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
    "men_high_blood_sugar_140plus": "m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
    "women_elevated_bp_140plus": "w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
    "under5_stunted": "child_u5_who_are_stunted_height_for_age_18_pct",
}
NOT_PERCENT = {"id", "delivery_out_of_pocket_expenditure", "sex_ratio_birth", "sex_ratio_total"}
STATE_FIX = {"maharastra": "maharashtra", "delhi": "nct of delhi",
             "the dadra and nagar haveli and daman and diu": "dadra and nagar haveli and daman and diu"}
# directory spellings that differ from LGD names beyond fuzzy reach (normalised)
DIR_ALIAS = {("maharashtra", "aurangabad"): "chhatrapati sambhajinagar",
             ("maharashtra", "ahmednagar"): "ahilyanagar", ("maharashtra", "osmanabad"): "dharashiv",
             ("odisha", "cuttack"): "kataka", ("odisha", "sundargarh"): "sundaragada",
             ("odisha", "nayagarh"): "nayagada", ("odisha", "anugul"): "anugola", ("odisha", "angul"): "anugola",
             ("odisha", "bargarh"): "baragada", ("odisha", "deogarh"): "debagada",
             ("odisha", "kandhamal"): "kandhamala", ("odisha", "kendrapara"): "kendrapada",
             ("odisha", "keonjhar"): "kendujhar", ("odisha", "balasore"): "baleshwar",
             ("madhya pradesh", "hoshangabad"): "narmadapuram",
             ("madhya pradesh", "khargone"): "khargone west nimar", ("madhya pradesh", "east nimar"): "khandwa east nimar",
             ("gujarat", "dohad"): "dahod", ("assam", "karimganj"): "sribhumi",
             ("karnataka", "ramanagara"): "bengaluru south", ("tamil nadu", "tuticorin"): "thoothukkudi",
             ("chhattisgarh", "kabirdham"): "kabeerdham", ("chhattisgarh", "baloda bazar"): "balodabazar bhatapara",
             ("andhra pradesh", "anantapur"): "ananthapuramu", ("andhra pradesh", "y s r"): "y s r kadapa",
             ("andhra pradesh", "spsr nellore"): "sri potti sriramulu nellore",
             ("puducherry", "pondicherry"): "puducherry",
             # ponytail: Sikkim 2021 renames; Pakyong and Soreng were carved out later, so approximate
             ("sikkim", "east district"): "gangtok", ("sikkim", "south district"): "namchi",
             ("sikkim", "west district"): "gyalshing", ("sikkim", "north district"): "mangan"}
DIR_ALIAS_ANY = {"24 paraganas north": "north 24 parganas", "24 paraganas south": "south 24 parganas",
             "medinipur east": "purba medinipur", "medinipur west": "paschim medinipur",
             "dinajpur dakshin": "dakshin dinajpur", "dinajpur uttar": "uttar dinajpur",
             "coochbehar": "cooch behar", "east singhbhum": "east singhbum"}


def norm(s) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).lower().replace("&", " and ")
    s = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()
    return STATE_FIX.get(s, s)


def match_within_state(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    """One-to-one name match per state: exact first, then best fuzzy >= FUZZ_MIN among unused."""
    rows = []
    for st, lg in left.groupby("st"):
        rg = right[right.st == st]
        # exact stage ignores spaces ("barabanki" == "bara banki")
        free_ns = dict(zip(rg.dn.str.replace(" ", ""), rg.dn))
        free = dict(zip(rg.dn, rg.key))
        for _, r in lg.iterrows():
            hit = free_ns.get(r.dn.replace(" ", ""))
            if hit in free:
                rows.append((r.key, free.pop(hit), "exact", 100.0))
        for _, r in lg[~lg.key.isin([x[0] for x in rows])].iterrows():
            hit = process.extractOne(r.dn, list(free), scorer=fuzz.token_sort_ratio) if free else None
            if hit and hit[1] >= FUZZ_MIN:
                rows.append((r.key, free.pop(hit[0]), "fuzzy", round(hit[1], 1)))
    return pd.DataFrame(rows, columns=["lkey", "rkey", "how", "score"])


def match_by_values(n5: pd.DataFrame, i19: pd.DataFrame) -> pd.DataFrame:
    """Fallback for renamed districts: same state and all VALUE_PAIRS equal to 0.1 (unique pair only)."""
    rows = []
    for _, r in n5.iterrows():
        cand = i19[i19.st == r.st]
        ok = np.ones(len(cand), bool)
        for a, b in VALUE_PAIRS.items():
            ok &= ((cand[a] - r[b]).abs() <= 0.11).to_numpy() | (pd.isna(r[b]) & cand[a].isna()).to_numpy()
        if ok.sum() == 1:
            rows.append((r.key, cand[ok].key.iloc[0], "values", 0.0))
    out = pd.DataFrame(rows, columns=["lkey", "rkey", "how", "score"])
    return out[~out.rkey.duplicated(keep=False)]


def inspect(d: pd.DataFrame, s: pd.DataFrame) -> dict:
    pct_cols = [c for c in d.columns[6:] if c not in NOT_PERCENT]
    num = d[pct_cols]
    out_of_range = {c: int(((num[c] < 0) | (num[c] > 100)).sum()) for c in pct_cols}
    nulls = {y: g[d.columns[6:]].isna().mean().round(3).to_dict() for y, g in d.groupby("year")}
    all_null = {y: [c for c, v in n.items() if v == 1.0] for y, n in nulls.items()}
    codes = {y: set(g.district_code) for y, g in d.groupby("year")}
    # state-level sanity: the state Total value should sit inside its districts' min..max
    st = s[s.residence == "Total"]
    inside, total = 0, 0
    for col in ["births_c_section", "institutional_births", "women_high_blood_sugar_140plus"]:
        rng = d.groupby(["year", "state_code"])[col].agg(["min", "max"]).reset_index()
        m = st[["year", "state_code", col]].merge(rng, on=["year", "state_code"]).dropna()
        total += len(m)
        inside += int(((m[col] >= m["min"]) & (m[col] <= m["max"])).sum())
    key_fields = ["births_c_section", "private_births_c_section", "public_births_c_section",
                  "institutional_births", "men_high_blood_sugar_140plus", "women_high_blood_sugar_140plus",
                  "women_elevated_bp_140plus", "men_elevated_bp_140plus"]
    return {
        "rows": len(d), "columns": len(d.columns), "rows_by_year": d.year.value_counts().to_dict(),
        "states_by_year": d.groupby("year").state_code.nunique().to_dict(),
        "dup_year_district_code": int(d.duplicated(["year", "district_code"]).sum()),
        "dup_year_state_name": int(d.duplicated(["year", "state_name", "district_name"]).sum()),
        "non_numeric_district_code": int((~d.district_code.str.fullmatch(r"\d+")).sum()),
        "percent_cells_out_of_0_100": {c: v for c, v in out_of_range.items() if v},
        "columns_all_null_by_year": {y: len(v) for y, v in all_null.items()},
        "key_field_null_rate_by_year": {y: {k: nulls[y][k] for k in key_fields} for y in nulls},
        "codes_2019_in_2023": len(codes["2019-21"] & codes["2023-24"]),
        "codes_2023_not_in_2019": sorted(codes["2023-24"] - codes["2019-21"]),
        "codes_2019_not_in_2023": sorted(codes["2019-21"] - codes["2023-24"]),
        "states_2023_24": sorted(d[d.year == "2023-24"].state_name.unique()),
        "state_total_inside_district_range": f"{inside}/{total}",
        "births_c_section_2023_24_describe": d[d.year == "2023-24"].births_c_section.describe().round(2).to_dict(),
    }


def join_nfhs5(d: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    n5 = pd.read_parquet(NFHS5)
    n5 = n5.assign(**{b: pd.to_numeric(n5[b], errors="coerce") for b in VALUE_PAIRS.values()})
    n5 = n5.assign(st=n5.state_ut.map(norm), dn=n5.district_name.map(norm), key=n5.index)
    i19 = d[d.year == "2019-21"]
    i19 = i19.assign(st=i19.state_name.map(norm), dn=i19.district_name.map(norm), key=i19.index)
    m = match_within_state(n5, i19)
    m = pd.concat([m, match_by_values(n5[~n5.key.isin(m.lkey)], i19[~i19.key.isin(m.rkey)])], ignore_index=True)
    m = m.merge(n5[["key", "state_ut", "district_name", *VALUE_PAIRS.values()]], left_on="lkey", right_on="key")
    m = m.merge(i19[["key", "state_code", "district_code", "district_name", *VALUE_PAIRS]],
                left_on="rkey", right_on="key", suffixes=("_nfhs5", "_idp"))
    agree = pd.DataFrame({a: (m[a] - pd.to_numeric(m[b], errors="coerce")).abs() <= 0.11
                          for a, b in VALUE_PAIRS.items()})
    present = pd.DataFrame({a: m[a].notna() & pd.to_numeric(m[b], errors="coerce").notna()
                            for a, b in VALUE_PAIRS.items()})
    m["values_compared"] = present.sum(axis=1)
    m["values_agree"] = (agree & present).sum(axis=1)
    m["value_confirmed"] = (m.values_compared > 0) & (m.values_agree == m.values_compared)
    unmatched_n5 = n5[~n5.key.isin(m.lkey)][["state_ut", "district_name"]].values.tolist()
    unmatched_idp = i19[~i19.key.isin(m.rkey)][["state_name", "district_name"]].values.tolist()
    stats = {
        "nfhs5_rows": len(n5), "idp_2019_rows": len(i19), "matched": len(m),
        "matched_by_how": m.how.value_counts().to_dict(),
        "value_confirmed": int(m.value_confirmed.sum()),
        "value_confirmed_by_how": m.groupby("how").value_confirmed.sum().astype(int).to_dict(),
        "per_indicator_agree": {a: f"{int((agree[a] & present[a]).sum())}/{int(present[a].sum())}" for a in VALUE_PAIRS},
        "unmatched_nfhs5": unmatched_n5, "unmatched_idp_2019": unmatched_idp,
    }
    cols = ["state_ut", "district_name_nfhs5", "district_name_idp", "state_code", "district_code", "how", "score",
            "values_compared", "values_agree", "value_confirmed"]
    return m[cols], stats


def join_facilities(d: pd.DataFrame, nmap: pd.DataFrame, out: Path) -> dict:
    total_fac = len(pd.read_parquet(FAC, columns=["name"]))
    fd = pd.read_parquet(FAC_DIST)
    i23 = d[d.year == "2023-24"]
    has_cs = set(i23[i23.births_c_section.notna()].district_code)
    # (a) via audit NFHS-5 district -> IDP code (2019-21) -> 2023-24
    nm = nmap.assign(st=nmap.state_ut.map(norm), dn=nmap.district_name_nfhs5.map(norm))
    nm_key = dict(zip(zip(nm.st, nm.dn), nm.district_code))
    fd = fd.assign(st=fd.dstate.map(norm))
    fd["code_via_nfhs5"] = [nm_key.get((s, dn)) for s, dn in zip(fd.st, fd.nfhs_district_norm.fillna(""))]
    # (b) direct: directory district name -> IDP 2023-24 district name within state
    fd["dn"] = fd.district.map(norm)
    dirs = fd[["st", "dn"]][fd.dn != ""].drop_duplicates()
    dirs = dirs.assign(raw=dirs.dn, key=range(len(dirs)))
    dirs["dn"] = [DIR_ALIAS.get((s, x), DIR_ALIAS_ANY.get(x, x)) for s, x in zip(dirs.st, dirs.dn)]
    i23k = i23.assign(st=i23.state_name.map(norm), dn=i23.district_name.map(norm), key=i23.district_code)
    dm = match_within_state(dirs, i23k)
    dirs = dirs.merge(dm, left_on="key", right_on="lkey", how="left")
    dkey = dict(zip(zip(dirs.st, dirs.raw), dirs.rkey))
    fd["code_direct"] = [dkey.get((s, x)) for s, x in zip(fd.st, fd.dn)]
    fd["code_best"] = fd.code_direct.fillna(fd.code_via_nfhs5)
    a, b = fd.code_via_nfhs5, fd.code_direct
    both = a.notna() & b.notna()
    fd[["unique_id", "dstate", "district", "code_via_nfhs5", "code_direct", "code_best"]].to_csv(
        out / "facility_idp_district.csv", index=False)
    return {
        "facilities_in_raw": total_fac, "facilities_in_audit_district_table": len(fd),
        "facilities_with_district": int(fd.district.notna().sum()),
        "via_nfhs5_code_found": int(a.notna().sum()),
        "via_nfhs5_with_2023_24_c_section": int((a.notna() & a.isin(has_cs)).sum()),
        "direct_code_found": int(b.notna().sum()),
        "direct_with_2023_24_c_section": int((b.notna() & b.isin(has_cs)).sum()),
        "best_with_2023_24_c_section": int((fd.code_best.notna() & fd.code_best.isin(has_cs)).sum()),
        "best_by_state_missing": fd[~(fd.code_best.notna() & fd.code_best.isin(has_cs))].dstate.value_counts().head(12).to_dict(),
        "either_code_found": int((a.notna() | b.notna()).sum()),
        "both_found": int(both.sum()), "both_agree": int((both & (a == b)).sum()),
        "directory_districts": len(dirs), "directory_districts_direct_matched": int(dirs.rkey.notna().sum()),
        "directory_districts_direct_by_how": dirs.how.value_counts().to_dict(),
        "directory_districts_unmatched": dirs[dirs.rkey.isna()][["st", "raw"]].values.tolist(),
        "disagree_examples": fd[both & (a != b)][["dstate", "district", "nfhs_district_norm", "code_via_nfhs5",
                                                  "code_direct"]].drop_duplicates().head(15).values.tolist(),
    }


def handcheck(nmap: pd.DataFrame) -> pd.DataFrame:
    """20 rows for a manual name check: 7 fuzzy, 7 value-fingerprint, 6 exact, fixed seed."""
    take = {"fuzzy": 7, "values": 7, "exact": 6}
    return pd.concat([nmap[nmap.how == h].sample(k, random_state=7) for h, k in take.items()])


def main() -> None:
    dist_csv, state_csv, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    d = pd.read_csv(dist_csv, dtype={"state_code": str, "district_code": str})
    # ponytail: 8 rows (Shahdara, Mahe, Yanam) have no LGD code; give them a stable surrogate
    d["district_code"] = d.district_code.fillna("NA-" + d.district_name.map(norm).str.replace(" ", "_"))
    s = pd.read_csv(state_csv, dtype={"state_code": str})
    stats = {"inspect": inspect(d, s)}
    nmap, stats["join_nfhs5"] = join_nfhs5(d)
    # facility ids are Virtue Foundation data: keep that file next to the gitignored download
    stats["join_facilities"] = join_facilities(d, nmap, Path(dist_csv).parent)
    nmap.to_csv(out / "nfhs5_idp_district_map.csv", index=False)
    handcheck(nmap).to_csv(out / "handcheck_20.csv", index=False)
    (out / "inspect_stats.json").write_text(json.dumps(stats, indent=1, default=str))
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    main()

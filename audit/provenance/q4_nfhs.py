"""Q4 + Q5: NFHS-5 district table quality, join to the PIN directory, and need indicators.
Outputs q4_results.json, nfhs_district_crosswalk.csv (PIN-directory district -> NFHS row),
nfhs_clean.parquet (numeric values + small-sample flags), handcheck_q4_*.csv."""
import json
import re
import sys

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/provenance")
from common import OUT, facilities, nfhs, norm_pin, pincodes  # noqa: E402

NFHS_STATE_FIX = {
    "ANDAMAN AND NICOBAR ISLANDS": "ANDAMAN AND NICOBAR ISLANDS", "MAHARASTRA": "MAHARASHTRA",
    "NCT OF DELHI": "DELHI", "JAMMU AND KASHMIR": "JAMMU AND KASHMIR",
    "DADRA AND NAGAR HAVELI AND DAMAN AND DIU": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
}
# PIN-directory district -> NFHS-5 district (same state). RENAMES are the same territory under a
# new or different spelling; SPLITS are districts carved out after NFHS-5 (2019-21) and point to
# the parent district, so the NFHS value is an estimate for the parent, not the new district.
RENAMES = {
    "GURUGRAM": "Gurgaon", "NUH": "Mewat", "S.A.S NAGAR": "Sahibzada Ajit Singh Nagar",
    "SRI MUKTSAR SAHIB": "Muktsar", "POONCH": "Punch", "HATHRAS": "Mahamaya Nagar",
    "KASGANJ": "Kanshiram Nagar", "PRAYAGRAJ": "Allahabad", "BHADOHI": "Sant Ravidas Nagar (Bhadohi)",
    "AYODHYA": "Faizabad", "AMROHA": "Jyotiba Phule Nagar", "PAURI GARHWAL": "Garhwal",
    "DANG": "The Dangs", "RAIGAD": "Raigarh", "BEED": "Bid", "EAST NIMAR": "Khandwa (East Nimar)",
    "KANKER": "Uttar Bastar Kanker", "KOREA": "Koriya", "SPSR NELLORE": "Sri Potti Sriramulu Nello",
    "HANUMAKONDA": "Warangal Urban", "WARANGAL": "Warangal Rural",
    "BENGALURU URBAN": "Bangalore", "BENGALURU RURAL": "Bangalore Rural", "MYSURU": "Mysore",
    "BALLARI": "Bellary", "KALABURAGI": "Gulbarga", "VIJAYAPURA": "Bijapur", "BELAGAVI": "Belgaum",
    "PONDICHERRY": "Puducherry", "TUTICORIN": "Thoothukkudi",
    "24 PARAGANAS NORTH": "North Twenty Four Pargana", "24 PARAGANAS SOUTH": "South Twenty Four Pargana",
    "HOWRAH": "Haora", "HOOGHLY": "Hugli", "MEDINIPUR WEST": "Paschim Medinipur",
    "MEDINIPUR EAST": "Purba Medinipur", "DINAJPUR DAKSHIN": "Dakshin Dinajpur",
    "DINAJPUR UTTAR": "Uttar Dinajpur", "COOCHBEHAR": "Koch Bihar", "SONEPUR": "Subarnapur",
    "EAST SINGHBUM": "Purbi Singhbhum", "WEST SINGHBHUM": "Pashchimi Singhbhum",
}
SPLITS = {
    "PARVATHIPURAM MANYAM": "Vizianagaram", "ALLURI SITHARAMA RAJU": "Visakhapatnam",
    "ANAKAPALLI": "Visakhapatnam", "KAKINADA": "East Godavari", "KONASEEMA": "East Godavari",
    "ELURU": "West Godavari", "NTR": "Krishna", "BAPATLA": "Guntur", "PALNADU": "Guntur",
    "NANDYAL": "Kurnool", "SRI SATHYA SAI": "Anantapur", "ANNAMAYYA": "Y.S.R.", "TIRUPATI": "Chittoor",
    "MULUGU": "Jayashankar Bhupalapally", "NARAYANPET": "Mahabubnagar", "NIWARI": "Tikamgarh",
    "GAURELLA PENDRA MARWAHI": "Bilaspur", "MALERKOTLA": "Sangrur", "VIJAYNAGAR": "Bellary",
    "CHENGALPATTU": "Kancheepuram", "RANIPET": "Vellore", "TIRUPATHUR": "Vellore",
    "KALLAKURICHI": "Viluppuram", "TENKASI": "Tirunelveli", "MAYILADUTHURAI": "Nagapattinam",
    "JHARGRAM": "Paschim Medinipur", "KALIMPONG": "Darjiling", "ALIPURDUAR": "Jalpaiguri",
    "PAKYONG": "East District", "SORENG": "West District", "BAJALI": "Barpeta",
    "PAKKE KESSANG": "East Kameng", "SHI YOMI": "West Siang", "LOWER SIANG": "West Siang",
    "LEPARADA": "West Siang", "KAMLE": "Lower Subansiri", "KANGPOKPI": "Senapati",
    "PHERZAWL": "Churachandpur", "KAMJONG": "Ukhrul", "KAKCHING": "Thoubal", "JIRIBAM": "Imphal East",
    "TENGNOUPAL": "Chandel", "NONEY": "Tamenglong", "SAITUAL": "Aizawl", "KHAWZAWL": "Champhai",
    "HNAHTHIAL": "Lunglei", "NOKLAK": "Tuensang",
}
NEED = {
    "births_delivered_by_csection_5y_pct": "C-section / obstetric surgery demand (all births)",
    "births_in_a_public_fac_that_were_delivered_by_csection_5y_pct": "public-sector C-section access",
    "births_in_a_private_fac_that_were_delivered_by_csection_5y_pct": "private C-section share",
    "institutional_birth_5y_pct": "low value = home births, high unmet need for delivery care",
    "institutional_birth_in_public_facility_5y_pct": "reliance on public facilities",
    "home_birth_that_were_conducted_by_skilled_hp_5y_10_pct": "home-birth skilled attendance",
    "mothers_who_had_at_least_4_anc_visits_lb5y_pct": "antenatal coverage (high-risk pregnancy detection)",
    "pregnant_w15_49_who_are_anaemic_lt_11_0_g_dl_22_pct": "obstetric risk (anaemia in pregnancy)",
    "w15_19_who_were_already_mothers_or_pregnant_at_the_time_of_pct": "adolescent pregnancy risk",
    "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct": "diabetes proxy (dialysis, cardiac)",
    "m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct": "diabetes proxy (dialysis, cardiac)",
    "w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct": "hypertension proxy (dialysis, cardiac, stroke)",
    "m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct": "hypertension proxy (dialysis, cardiac, stroke)",
    "hh_member_covered_health_insurance_pct": "ability to pay / PM-JAY reach",
    "average_out_of_pocket_expenditure_per_delivery_in_a_public_fac": "cost barrier for delivery (rupees)",
    "child_u5_who_are_wasted_weight_for_height_18_pct": "paediatric / NICU-adjacent need",
    "child_u5_who_are_severe_wasted_weight_for_height_19_pct": "severe acute malnutrition, paediatric admissions",
    "all_w15_49_who_are_anaemic_pct": "general anaemia burden",
    "women_age_30_49_years_ever_undergone_a_cervical_screen_pct": "cancer screening reach (oncology)",
    "m15_plus_who_use_any_kind_of_tobacco_pct": "oral cancer / cardiac risk",
    "children_with_fever_or_symptoms_of_ari_2wk_taken_to_a_healt_pct": "paediatric care seeking",
}
NUM = re.compile(r"-?\d+(\.\d+)?")


def up(s):
    return re.sub(r"\s+", " ", str(s).replace("&", " AND ")).strip().upper()


def key(s):
    return re.sub(r"[^A-Z0-9]", "", up(s))


def parse_cell(v):
    """NFHS-5 fact-sheet notation: '(x)' = based on 25-49 unweighted cases, '*' = fewer than
    25 unweighted cases, value suppressed. Returns (value, flag)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan, "missing"
    t = str(v).strip()
    if NUM.fullmatch(t):
        return float(t), "ok"
    if re.fullmatch(r"\(" + NUM.pattern + r"\)", t):
        return float(t[1:-1]), "small_n_25_49"
    if t == "*":
        return np.nan, "suppressed_lt25"
    return np.nan, "other:" + t


def match_districts(n, p):
    """Tiered match of each PIN-directory (state, district) to an NFHS row in the same state."""
    nf = n.assign(st=n.state_ut.map(up).map(lambda s: NFHS_STATE_FIX.get(s, s)),
                  dk=n.district_name.map(key))
    pd_ = (p[(p.district != "NA") & (p.statename != "NA")][["statename", "district"]]
           .drop_duplicates())
    by_state = {s: g for s, g in nf.groupby("st")}
    rows = []
    for st, d in zip(pd_.statename, pd_.district):
        g = by_state.get(st)
        k = key(d)
        tier, idx = "unmatched", None
        manual = RENAMES.get(up(d)) or SPLITS.get(up(d))
        if g is not None and manual:
            hit = g.index[g.district_name.map(up) == up(manual)]
            if len(hit):
                tier = "manual_rename" if up(d) in RENAMES else "manual_split_parent"
                idx = hit[0]
        if g is not None and idx is None:
            exact = g.index[g.district_name.map(up) == up(d)]
            norm = g.index[g.dk == k]
            pref = g.index[[len(x) >= 8 and (k.startswith(x) or x.startswith(k)) for x in g.dk]]
            if len(exact):
                tier, idx = "exact", exact[0]
            elif len(norm):
                tier, idx = "normalized", norm[0]
            elif len(pref) == 1:
                tier, idx = "prefix_truncated", pref[0]
            else:
                best = process.extractOne(k, dict(zip(g.index, g.dk)), scorer=fuzz.ratio)
                if best and best[1] >= 80:
                    tier, idx = "fuzzy_ge80", best[2]
        rows.append({"statename": st, "district": d, "tier": tier,
                     "nfhs_state": None if idx is None else nf.at[idx, "state_ut"].strip(),
                     "nfhs_district": None if idx is None else nf.at[idx, "district_name"].strip()})
    return pd.DataFrame(rows), nf


def main():
    n, p = nfhs(), pincodes()
    res = {"rows": len(n), "columns": len(n.columns)}
    res["name_whitespace"] = {
        "district_name_leading_or_trailing_space": int((n.district_name != n.district_name.str.strip()).sum()),
        "state_ut_leading_or_trailing_space": int((n.state_ut != n.state_ut.str.strip()).sum())}
    res["states_in_nfhs"] = int(n.state_ut.str.strip().nunique())
    res["duplicate_state_district"] = int(n.assign(a=n.state_ut.map(up), b=n.district_name.map(up))
                                          .duplicated(["a", "b"]).sum())
    res["district_name_len_max"] = int(n.district_name.str.strip().str.len().max())
    res["district_names_at_max_len"] = n.district_name.str.strip()[
        n.district_name.str.strip().str.len() >= 24].tolist()
    ind = n.columns[2:]
    dtype_str = [c for c in ind if n[c].dtype == object or str(n[c].dtype) in ("str", "string")]
    res["indicator_columns"] = len(ind)
    res["double_columns"] = len(ind) - len(dtype_str)
    res["string_columns"] = len(dtype_str)
    res["double_columns_with_nan"] = {c: int(n[c].isna().sum()) for c in ind
                                      if c not in dtype_str and n[c].isna().any()}
    flags, cols = {}, {}
    for c in ind:
        parsed = n[c].map(parse_cell) if c in dtype_str else n[c].map(
            lambda v: (v, "ok") if pd.notna(v) else (np.nan, "missing"))
        cols[c] = parsed.map(lambda t: t[0])
        cols[c + "__flag"] = parsed.map(lambda t: t[1])
        flags[c] = cols[c + "__flag"].value_counts().to_dict()
    clean = pd.concat([n[["district_name", "state_ut"]], pd.DataFrame(cols)], axis=1)
    tot = pd.Series(dtype=float)
    for c in ind:
        tot = tot.add(pd.Series(flags[c]), fill_value=0)
    res["cell_flags_all_indicators"] = {k: int(v) for k, v in tot.items()}
    res["string_cells_trailing_space"] = int(sum(
        (n[c].astype(str) != n[c].astype(str).str.strip()).sum() for c in dtype_str))
    worst = sorted(((c, flags[c].get("suppressed_lt25", 0) + flags[c].get("small_n_25_49", 0))
                    for c in ind), key=lambda t: -t[1])[:12]
    res["most_small_sample_columns"] = {c: flags[c] for c, _ in worst}
    # rows whose 107 indicator values are identical to another row (copy errors)
    vals = n[ind].astype(str).apply(lambda r: "|".join(x.strip() for x in r), axis=1)
    dup = n[vals.duplicated(keep=False)]
    res["identical_indicator_rows"] = [f"{a.strip()} / {b.strip()}" for a, b in
                                       zip(dup.state_ut, dup.district_name)]
    # Q5: candidate need indicators, with how often each is usable
    res["need_indicators"] = {}
    for c, use in NEED.items():
        v = clean[c]
        res["need_indicators"][c] = {
            "use": use, "dtype": str(n[c].dtype), "flags": flags[c],
            "min": float(np.nanmin(v)), "median": float(np.nanmedian(v)), "max": float(np.nanmax(v))}
    clean["state_ut"] = clean.state_ut.str.strip()
    clean["district_name"] = clean.district_name.str.strip()
    clean.to_parquet(f"{OUT}/nfhs_clean.parquet", index=False)

    cw, nf = match_districts(n, p)
    cw.to_csv(f"{OUT}/nfhs_district_crosswalk.csv", index=False)
    res["pin_districts_total"] = int(len(cw))
    res["pin_district_match_tiers"] = cw.tier.value_counts().to_dict()
    matched_nfhs = set(zip(cw.nfhs_state.dropna(), cw.nfhs_district.dropna()))
    res["nfhs_rows_matched_by_some_pin_district"] = int(len(matched_nfhs))
    um_n = nf[[(s.strip(), d.strip()) not in matched_nfhs for s, d in zip(nf.state_ut, nf.district_name)]]
    res["nfhs_rows_unmatched"] = int(len(um_n))
    um_n[["state_ut", "district_name"]].to_csv(f"{OUT}/handcheck_q4_nfhs_unmatched.csv", index=False)
    cw[cw.tier == "unmatched"].to_csv(f"{OUT}/handcheck_q4_pin_unmatched.csv", index=False)
    cw[cw.tier.isin(["prefix_truncated", "fuzzy_ge80"])].to_csv(
        f"{OUT}/handcheck_q4_fuzzy.csv", index=False)
    res["pin_unmatched_by_state"] = cw[cw.tier == "unmatched"].statename.value_counts().to_dict()
    # facility-weighted join: facility PIN -> directory district(s) -> NFHS
    f = facilities()
    pins = f.address_zipOrPostcode.map(norm_pin)
    pdist = (p[(p.district != "NA")][["pincode", "statename", "district"]].drop_duplicates()
             .merge(cw, on=["statename", "district"], how="left"))
    best = (pdist.assign(ok=pdist.tier.ne("unmatched"))
            .sort_values("ok", ascending=False).drop_duplicates("pincode"))
    fj = pd.DataFrame({"pin": pins}).merge(best, left_on="pin", right_on="pincode", how="left")
    res["facility_join"] = {
        "facilities": int(len(f)), "with_valid_pin": int(pins.notna().sum()),
        "pin_in_directory_with_district": int(fj.tier.notna().sum()),
        "reach_nfhs_row": int((fj.tier.notna() & fj.tier.ne("unmatched")).sum()),
        "by_tier": fj.tier.fillna("no_pin_or_district").value_counts().to_dict()}
    with open(f"{OUT}/q4_results.json", "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    assert parse_cell("(92.6)") == (92.6, "small_n_25_49")
    assert parse_cell("*")[1] == "suppressed_lt25"
    assert parse_cell("31.3 ") == (31.3, "ok")
    assert key("North & Middle Andaman ") == "NORTHANDMIDDLEANDAMAN"
    main()

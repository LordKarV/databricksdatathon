"""Side-by-side table: analyst numbers (data/*_numbers.json) vs the independent recomputation (verify/out).

Run after v_base.py, v_stories.py and v_travel.py. Writes verify/out/comparison.csv and prints it.
A row "agrees" when the relative difference is under 5% (counts: under 2% or 2 units).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"


def load(name: str) -> dict:
    return json.loads((DATA / f"{name}_numbers.json").read_text())


def main() -> None:
    a = {k: load(k) for k in ("s1", "s2", "s3", "s4", "s5", "s6")}
    v = json.loads((HERE / "out/stories_numbers.json").read_text())
    t = json.loads((HERE / "out/travel_numbers.json").read_text())
    cls = {c["code"]: c for c in a["s5"]["classes"]}
    rows = [
        ("s1", "Bihar records", a["s1"]["bihar_records"], v["s1"]["bihar_records"]),
        ("s1", "Bihar per million", a["s1"]["bihar_per_m"], v["s1"]["bihar_per_m"][0]),
        ("s1", "India per million", a["s1"]["national_per_m"], v["s1"]["national_per_m"]),
        ("s1", "Delhi / Bihar", a["s1"]["ratio_delhi_bihar"], v["s1"]["delhi_over_bihar"]),
        ("s1", "Chandigarh per million", a["s1"]["top_per_m"], v["s1"]["top_per_m"]),
        ("s1", "Bihar stunting %", a["s1"]["bihar_stunting"], v["s1"]["bihar_stunt_popw"]),
        ("s1", "rho records vs stunting", a["s1"]["rho_stunting"][0], v["s1"]["rho"][0]),
        ("s1", "Patna records", a["s1"]["bihar_patna"], v["s1"]["patna"]),
        ("s1", "Bihar zero-record districts", a["s1"]["bihar_zero_districts"], v["s1"]["bihar_zero"]),
        ("s1", "zero-record districts", a["s1"]["zero_districts"], v["s1"]["zero_districts"]),
        ("s1", "people in zero-record districts (M)", a["s1"]["zero_pop"] / 1e6, v["s1"]["zero_pop_m"]),
        ("s2", "dialysis claims", a["s2"]["n_claim"], v["s2"]["n_claim"]),
        ("s2", "dialysis confirmed", a["s2"]["n_corr"], v["s2"]["n_conf"]),
        ("s2", "hot districts", a["s2"]["hot_districts"], t["s2"]["hot_districts"]),
        ("s2", "hot people (M)", a["s2"]["hot_pop"] / 1e6, t["s2"]["hot_pop_m"]),
        ("s2", "rho need vs access", a["s2"]["rho_ncd_share60"], t["s2"]["rho_ncd_share60"]),
        ("s2", "East Godavari median min", a["s2"]["top_hot"][0][5], t["s2"]["east_godavari"]["median_min"]),
        ("s2", "Q4 per million", a["s2"]["by_quartile"][3]["per_m"], v["s2"]["by_quartile"][3]["per_m"]),
        ("s2", "Q1 per million", a["s2"]["by_quartile"][0]["per_m"], v["s2"]["by_quartile"][0]["per_m"]),
        ("s2", "PMNDP centres", a["s2"]["pmndp_centres"], v["s2"]["pmndp_centres"]),
        ("s2", "public records claiming dialysis", a["s2"]["public_claim"], v["s2"]["public_records_claiming_dialysis"]),
        ("s2", "districts with confirmed dialysis", a["s2"]["lgd_districts_with_corr"], v["s2"]["lgd_districts_with_conf"]),
        ("s3", "low-rate districts", a["s3"]["low_districts"], v["s3"]["low_districts"]),
        ("s3", "claims in low-rate districts", a["s3"]["low_claimed"], v["s3"]["low_claim"]),
        ("s3", "LaQshya MOT in low-rate districts", a["s3"]["low_laqshya"], v["s3"]["low_lq"]),
        ("s3", "claims ratio high vs low", a["s3"]["ratio_claimed_high_vs_low"], v["s3"]["ratio_claim_hi_vs_low"]),
        ("s3", "LaQshya ratio high vs low", 1 / a["s3"]["ratio_laqshya_low_vs_high"], v["s3"]["ratio_lq_hi_vs_low"]),
        ("s3", "private > public share", a["s3"]["priv_gt_pub_share"], v["s3"]["priv_gt_pub"][2]),
        ("s3", "median gap (points)", a["s3"]["priv_minus_pub_median"], v["s3"]["gap_median"]),
        ("s4", "MAP within 60", a["s4"]["india_share_map"], t["india_share60"]["map"]),
        ("s4", "any record within 60", a["s4"]["india_share_any"], t["india_share60"]["any"]),
        ("s4", "trauma claim within 60", a["s4"]["india_share_claim"], t["india_share60"]["trauma_claim"]),
        ("s4", "trauma confirmed within 60", a["s4"]["india_share_corr"], t["india_share60"]["trauma_conf"]),
        ("s4", "people outside confirmed (M)", a["s4"]["people_outside_corr"] / 1e6, t["people_outside_trauma_conf_m"]),
        ("s4", "Bihar confirmed within 60", a["s4"]["bihar"]["corr"], t["states"]["BIHAR"]["conf"]),
        ("s4", "Arunachal confirmed within 60", a["s4"]["lowest_corr_states"][0][1], t["states"]["ARUNACHAL PRADESH"]["conf"]),
        ("s4", "Mizoram confirmed within 60", a["s4"]["lowest_corr_states"][1][1], t["states"]["MIZORAM"]["conf"]),
        ("s4", "MP people outside (M)", a["s4"]["gap_largest"][2][2] / 1e6, t["states"]["MADHYA PRADESH"]["outside_conf_m"]),
        ("s5", "urban centre pop share", cls[3]["pop_share"], t["s5"]["urban"]["pop_share"]),
        ("s5", "rural pop share", cls[1]["pop_share"], t["s5"]["rural"]["pop_share"]),
        ("s5", "records in urban centres", cls[3]["records"], t["s5"]["urban"]["records"]),
        ("s5", "rural trauma within 60", cls[1]["trauma_within60"], t["s5"]["rural"]["trauma_conf_60"]),
        ("s5", "urban trauma within 60", cls[3]["trauma_within60"], t["s5"]["urban"]["trauma_conf_60"]),
        ("s5", "rural C-section within 60", cls[1]["csection_within60"], t["s5"]["rural"]["csection_conf_60"]),
        ("s6", "confirmed with site", a["s6"]["any_claim_site"][2], v["s6"]["any_site1"][2]),
        ("s6", "confirmed without site", a["s6"]["any_claim_nosite"][2], v["s6"]["any_site0"][2]),
        ("s6", "public with site", a["s6"]["coverage"][1]["rate"], v["s6"]["coverage"]["public"][2]),
        ("s6", "web confirmations from cited site", a["s6"]["web_conf_site_in_vf_sources"][0],
         sum(x[0] for x in v["s6"]["site_in_vf_sources"].values())),
    ]
    df = pd.DataFrame(rows, columns=["story", "number", "analyst", "independent"])
    df["rel_diff"] = (df.independent - df.analyst).abs() / df.analyst.abs().where(df.analyst != 0, 1)
    df["agrees"] = df.rel_diff < 0.05
    df.to_csv(HERE / "out/comparison.csv", index=False)
    with pd.option_context("display.width", 160, "display.max_rows", 100):
        print(df.round(4).to_string(index=False))
    print(f"\n{int(df.agrees.sum())} of {len(df)} within 5%")


if __name__ == "__main__":
    main()

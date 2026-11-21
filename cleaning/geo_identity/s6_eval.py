"""Step 6: check the location decisions against the web ground truth, and score the hand checks.

Ground truth: audit/ground_truth (36 stratified pairs, web check by a separate agent). Only pairs
where the web check reached a location verdict (yes / no) are scored; 'unclear' is reported apart.
Before = the audit rule (raw coordinates more than 50 km from the audit PIN centroid is the only flag).
After  = this pipeline (loc_conf high/medium = trusted; low/disputed = flagged).
For the 'no' pairs the web notes name the true town; we measure how far the raw coordinates and the
chosen point are from that town's centre (directory-only place layer).
Writes ground_truth_eval.csv and s6_stats.json.
"""
import json

import pandas as pd

from common import AUDIT_GEO, OUT, ROOT, hav_km
from places import build_layers, city_point

GT = ROOT / "audit/ground_truth"
TRUE_TOWN = {"emergency_csection_suspect_1": ("Kaithal", "HARYANA"), "nicu_suspect_2": ("Punalur", "KERALA"),
             "trauma_emergency_suspect_1": ("Firozabad", "UTTAR PRADESH"), "trauma_emergency_suspect_2": ("Satna", "MADHYA PRADESH")}


def main():
    s = pd.DataFrame(json.load(open(GT / "sample.json")))
    w = pd.concat([pd.DataFrame(json.load(open(GT / f"web_{i}.json"))["results"]) for i in (1, 2, 3)])
    s = s.merge(w[["pair_id", "exists", "location_matches", "service", "notes"]].rename(columns={"service": "web_service"}), on="pair_id")
    loc = pd.read_parquet(OUT / "facility_location.parquet").set_index("unique_id")
    tr = pd.read_parquet(OUT / "record_trust.parquet").set_index("unique_id")
    old = pd.read_parquet(AUDIT_GEO / "facility_geo.parquet").drop_duplicates("unique_id").set_index("unique_id")
    s = s.join(loc[["loc_src", "loc_conf", "loc_flags", "loc_lat", "loc_lon", "raw_lat", "raw_lon", "loc_note"]], on="unique_id")
    s = s.join(tr[["trust_level", "trust_flags"]], on="unique_id")
    s["before_flag"] = s.unique_id.map(old.d_pin_km) > 50
    s["after_flag"] = s.loc_conf.isin(["low", "disputed", "none"])
    L = build_layers()
    for pid, (town, state) in TRUE_TOWN.items():
        p = city_point(town, state, L)
        i = s.index[s.pair_id == pid][0]
        s.loc[i, "true_town"] = town
        s.loc[i, "raw_km_from_true_town"] = round(float(hav_km(s.raw_lat[i], s.raw_lon[i], p[0], p[1])), 1)
        s.loc[i, "chosen_km_from_true_town"] = round(float(hav_km(s.loc_lat[i], s.loc_lon[i], p[0], p[1])), 1)
    s["chosen_moved_km"] = hav_km(s.raw_lat, s.raw_lon, s.loc_lat, s.loc_lon).round(1)

    st = {}
    v = s[s.location_matches.isin(["yes", "no"])]
    for k in ("before_flag", "after_flag"):
        st[k] = {"verdict_pairs": len(v),
                 "no_and_flagged(caught)": int((v.location_matches.eq("no") & v[k]).sum()),
                 "no_and_trusted(missed)": int((v.location_matches.eq("no") & ~v[k]).sum()),
                 "yes_and_trusted": int((v.location_matches.eq("yes") & ~v[k]).sum()),
                 "yes_and_flagged(false_alarm)": int((v.location_matches.eq("yes") & v[k]).sum())}
    st["location_verdicts"] = s.location_matches.value_counts().to_dict()
    st["unclear_pairs_after_conf"] = s[s.location_matches == "unclear"].loc_conf.value_counts().to_dict()
    st["yes_pairs_where_point_moved_gt5km"] = s[(s.location_matches == "yes") & (s.chosen_moved_km > 5)][["pair_id", "loc_src", "chosen_moved_km"]].values.tolist()
    st["true_town_distance_raw_vs_chosen"] = s.dropna(subset=["true_town"])[["pair_id", "true_town", "raw_km_from_true_town", "chosen_km_from_true_town", "loc_conf"]].values.tolist()
    st["exists_vs_trust_level"] = pd.crosstab(s.exists, s.trust_level).to_dict()
    st["service_contradicted_vs_trust_level"] = pd.crosstab(s.web_service, s.trust_level).to_dict()

    h = pd.read_csv(OUT / "handcheck_location.csv")
    st["handcheck_location"] = h.groupby(["rule", "chosen_right"]).size().unstack(fill_value=0).to_dict(orient="index")

    cols = ["pair_id", "name", "location_matches", "exists", "web_service", "before_flag", "after_flag", "loc_src", "loc_conf",
            "loc_flags", "trust_level", "trust_flags", "chosen_moved_km", "true_town", "raw_km_from_true_town",
            "chosen_km_from_true_town", "loc_note"]
    s[cols].to_csv(OUT / "ground_truth_eval.csv", index=False)
    (OUT / "s6_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps(st, indent=1, default=str))


if __name__ == "__main__":
    main()

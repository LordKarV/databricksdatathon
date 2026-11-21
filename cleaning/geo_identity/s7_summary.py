"""Step 7: before/after numbers for REPORT.md, computed from the outputs of steps 1-6.
Writes summary.json."""
import json

import pandas as pd

from common import AUDIT_GEO, OUT, facilities, hav_km, load_facilities, parse_pin


def main():
    s = {}
    raw = load_facilities()
    s["rows_before_after_dedup"] = [len(raw), int(raw.unique_id.nunique())]

    # PIN point precision on busy PINs: facility consensus vs directory point (before) and repaired point (after)
    f = facilities()
    f["pin"] = f.address_zipOrPostcode.map(parse_pin)
    gz = pd.read_parquet(OUT / "pin_gazetteer.parquet").set_index("pin")
    g = f.dropna(subset=["pin"]).groupby("pin").agg(n=("unique_id", "size"), la=("latitude", "median"), lo=("longitude", "median"))
    g = g[g.n >= 3].join(gz[["lat", "lon", "dir_lat", "dir_lon"]], how="inner")
    before = hav_km(g.la, g.lo, g.dir_lat, g.dir_lon)
    after = hav_km(g.la, g.lo, g.lat, g.lon)
    s["busy_pins_gt25km_from_facility_median_before_after"] = [int((before > 25).sum()), int((after > 25).sum()), len(g)]
    s["busy_pins_gt10km_before_after"] = [int((before > 10).sum()), int((after > 10).sum()), len(g)]

    loc = pd.read_parquet(OUT / "facility_location.parquet")
    s2 = json.loads((OUT / "s2_stats.json").read_text())
    s["coords_gt50km_from_pin_before(audit)_after(repaired)"] = [s2["raw_coords_gt50km_from_audit_pin"], s2["raw_coords_gt50km_from_repaired_pin"]]
    s["coords_10_50km_band_before_after"] = s2["raw_coords_10_50km_audit_vs_repaired"]
    s["loc_src"], s["loc_conf"] = s2["loc_src"], s2["loc_conf"]
    moved = hav_km(loc.raw_lat, loc.raw_lon, loc.loc_lat, loc.loc_lon)
    s["records_whose_ranking_point_moved_gt25km"] = int((moved > 25).sum())
    s["records_ranked_on_raw_coords_that_conflict_gt50km"] = int(((loc.raw_coords_to_pin_km > 50) & (moved < 0.01)).sum())
    s["conflict_resolution_rules"] = {k: v for k, v in s2["flag_counts"].items() if k in {
        "map_link_used", "city_confirms_coords", "city_confirms_pin", "both_points_elsewhere", "coords_other_state",
        "pin_other_state", "pin_looks_wrong", "coords_look_wrong", "location_disputed", "city_points_elsewhere"}}
    old = pd.read_parquet(AUDIT_GEO / "facility_geo.parquet").drop_duplicates("unique_id")
    s["coords_outside_india_before_used_after"] = [int(old.coord_outside.sum()), 0]
    s["stated_state_resolved_before_after"] = s2["stated_state_resolved_before_after"]
    s["state_for_filter_missing_after"] = s2["state_final_missing"]
    s["district_assigned_after"] = int(loc.district.notna().sum())
    s["nfhs_joined_after"] = s2["nfhs_joined"]
    s["nfhs_how_after"] = s2["nfhs_how"]
    s["district_boundary_notes"] = s2["district_boundary_note"]
    s["resolver"] = {k: v for k, v in json.loads((OUT / "s3_stats.json").read_text()).items() if k in {"tests", "passed", "status_counts"}}
    s4 = json.loads((OUT / "s4_stats.json").read_text())
    s["groups"] = {k: s4[k] for k in ["groups", "records_in_groups", "records_marked_non_canonical", "records_with_possible_same_site_link",
                                      "records_with_co_located_unit", "groups_whose_copies_are_gt25km_apart", "linked_pairs_by_rule", "eval"]}
    s5 = json.loads((OUT / "s5_stats.json").read_text())
    s["trust"] = {k: s5[k] for k in ["flag_counts", "trust_level", "records_with_display_phone",
                                     "records_official_phone_directory_before_display", "emails_before_after", "email_issue",
                                     "phones_directory_vs_chain_helpline", "website_class"]}
    s["ground_truth"] = json.loads((OUT / "s6_stats.json").read_text())
    (OUT / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    print(json.dumps(s, indent=1, default=str))


if __name__ == "__main__":
    main()

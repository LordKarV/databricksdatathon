"""Build the facility-level table for pattern discovery: one row per usable record (9,959).

Inputs (read-only): derived/v1 (facility_location, record_trust, facility_groups, claims, grades),
kb/taxonomy/out/lexicon_matches, kb/vf_details/out/facility_details, kb/web_evidence/out/web_service_summary,
viz/features/out/features_pairs (record-level b_/c_/d_/e_/f_/g_ columns), model/proto/evidence/pair_features
(type, operator, size), data/raw/facilities (yearEstablished, operatorTypeId, social presence).
facility_trust scores are NOT used: their location and service scores carry gold overrides.

Split: duplicate groups (facility_groups.dup_group_id) are assigned whole to discovery (70%) or holdout (30%)
with seed 20261121, so two copies of one hospital never sit on both sides.
Outputs: data/facility.parquet, data/services_matrix.parquet, data/build_summary.json.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import DATA, SEED, read_input, save_json


def rp(rel: str, cols: list[str] | None = None) -> pd.DataFrame:
    return read_input(rel, cols)


def split(groups: pd.DataFrame) -> pd.Series:
    g = groups.dup_group_id.fillna(groups.unique_id)
    keys = np.sort(g.unique())
    rng = np.random.default_rng(SEED)
    hold = set(rng.choice(keys, size=int(round(0.3 * len(keys))), replace=False))
    return pd.Series(np.where(g.isin(hold), "holdout", "discovery"), index=groups.unique_id)


def service_matrix(uids: pd.Index) -> pd.DataFrame:
    """Own positive dataset text per service, same filter as viz/geography evidence_flags (text_pos)."""
    m = rp("kb/taxonomy/out/lexicon_matches.parquet")
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility")
            & ~m.kind.isin(["staff", "directory"])]
    x = pd.crosstab(pos.unique_id, pos.service).clip(upper=1)
    return x.reindex(uids, fill_value=0).astype(np.int8)


def details(uids: pd.Index) -> pd.DataFrame:
    d = rp("kb/vf_details/out/facility_details.parquet")
    d = d[d.n_usable > 0]
    out = pd.DataFrame(index=uids)
    for col, ft, attr in [("pmjay", "empanelment", "pmjay"), ("cghs", "empanelment", "cghs"),
                          ("private_insurance", "empanelment", "private_insurance"),
                          ("nabh_text", "accreditation", "NABH"), ("h24_facility", "hours_24x7", "facility"),
                          ("h24_emergency", "hours_24x7", "emergency"), ("ambulance", "ambulance", "ambulance_service"),
                          ("blood_bank_text", "blood_centre", "blood_bank")]:
        ids = set(d[(d.fact_type == ft) & (d.attribute == attr)].unique_id)
        out[col] = uids.isin(ids).astype(int)
    out["h24_any"] = out[["h24_facility", "h24_emergency"]].max(axis=1)
    return out


def main() -> None:
    loc = rp("derived/v1/facility_location.parquet").set_index("unique_id")
    uids = loc.index
    grp = rp("derived/v1/facility_groups.parquet")
    rt = rp("derived/v1/record_trust.parquet").set_index("unique_id")
    raw = rp("data/raw/facilities.parquet").drop_duplicates("unique_id").set_index("unique_id").reindex(uids)
    pf = rp("model/proto/evidence/pair_features.parquet").drop_duplicates("unique_id").set_index("unique_id").reindex(uids)
    fp = rp("viz/features/out/features_pairs.parquet").drop_duplicates("unique_id").set_index("unique_id").reindex(uids)

    f = pd.DataFrame(index=uids)
    f["name"] = loc.name
    f["split"] = split(grp).reindex(uids)
    f["state"] = loc.state_final
    f["nfhs_state"] = loc.nfhs_state_ut.str.strip()
    f["nfhs_district"] = loc.nfhs_district_name.str.strip()
    f["city"] = loc.address_city
    f["lat"], f["lon"] = loc.loc_lat, loc.loc_lon
    f["ftype"] = pf.facility_type
    op = raw.operatorTypeId.str.strip().str.lower()
    f["operator"] = np.select([op.isin(["public", "government"]), op.eq("private")], ["public", "private"], "unknown")
    f["public_level"] = pf.public_level
    f["beds"] = pf.beds
    f["doctors"] = pf.doctors
    f["n_specialties"] = pf.n_specialties
    yr = pd.to_numeric(raw.yearEstablished, errors="coerce")
    f["year_est"] = yr.where((yr >= 1800) & (yr <= 2026))
    f["social_count"] = pd.to_numeric(raw.distinct_social_media_presence_count, errors="coerce")
    f["followers"] = pd.to_numeric(raw.engagement_metrics_n_followers, errors="coerce")
    f["n_source_ids"] = fp.b_n_source_ids
    for c in ["c_n_urls", "c_share_official", "c_share_aggregator", "c_share_social", "c_share_business_dir",
              "c_share_government", "c_share_maps", "c_share_about_pages", "e_has_website", "e_site_alive",
              "f_osm_match", "f_wikidata_match", "d_nabh_listed", "b_directory_phone", "b_no_phone",
              "b_copied_geocode", "b_list_truncated" if "b_list_truncated" in fp else "a_list_truncated"]:
        f[c.split("_", 1)[1]] = fp[c]
    f["website_class"] = rt.website_class.fillna("none")
    f = f.join(details(uids))

    # outcomes: contamination, location drift, claim breadth
    cl = rp("derived/v1/claims.parquet", ["unique_id", "attribution", "dup_in_record"])
    cl = cl[~cl.dup_in_record]
    g = cl.groupby("unique_id").attribution
    f["n_sentences"] = g.size().reindex(uids, fill_value=0)
    f["n_other_facility"] = g.apply(lambda s: int((s == "other_facility").sum())).reindex(uids, fill_value=0)
    f["contaminated"] = (f.n_other_facility > 0).astype(int)
    f["coord_pin_km"] = loc.raw_coords_to_pin_km
    f["drift50"] = (loc.raw_coords_to_pin_km > 50).astype(float).where(loc.raw_coords_to_pin_km.notna())
    f["loc_conf"] = loc.loc_conf
    f["disputed"] = loc.loc_conf.eq("disputed").astype(int)
    flags = rt.trust_flags.apply(lambda a: set(a))
    f["claims_6plus"] = flags.apply(lambda s: "claims_6plus_of_8_services" in s).astype(int)

    sm = service_matrix(uids)
    f["n_services"] = sm.sum(axis=1)
    gr = rp("derived/v1/grades.parquet", ["unique_id", "service", "grade", "scope_conflict"])
    gg = gr.groupby("unique_id")
    f["n_grades"] = gg.size().reindex(uids, fill_value=0)
    f["n_strong"] = gg.grade.apply(lambda s: int((s == "strong").sum())).reindex(uids, fill_value=0)
    f["n_scope_conflict"] = gg.scope_conflict.sum().reindex(uids, fill_value=0)
    ws = rp("kb/web_evidence/out/web_service_summary.parquet")
    ws = ws[ws.web_positive & (ws.scope != "chain_home")]
    f["n_web_services"] = ws.groupby("unique_id").service_id.nunique().reindex(uids, fill_value=0)

    f = f.reset_index()
    f.to_parquet(DATA / "facility.parquet", index=False)
    sm.to_parquet(DATA / "services_matrix.parquet")
    summ = dict(rows=len(f), discovery=int((f.split == "discovery").sum()), holdout=int((f.split == "holdout").sum()),
                contaminated=int(f.contaminated.sum()), drift50=int(f.drift50.sum()), drift_n=int(f.drift50.notna().sum()),
                year_known=int(f.year_est.notna().sum()), services=sm.shape[1],
                facilities_with_any_service=int((f.n_services > 0).sum()),
                operator=f.operator.value_counts().to_dict(), ftype=f.ftype.value_counts().to_dict())
    save_json(summ, "build_summary")
    print(summ)


if __name__ == "__main__":
    main()

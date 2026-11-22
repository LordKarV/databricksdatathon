"""Build the candidate feature table for the core model (#11): one row per (facility, service).

Grain: the 9,959 usable records x 7 core services = 69,713 pairs, taken from
model/proto/evidence/pair_features.parquet. Every input is read-only; the output is
viz/features/out/features_pairs.parquet. Column prefixes name the family:

  a_  provided-dataset claims (sentences in the record, model/proto/evidence + derived/v1/claims)
  k_  structured details read from the dataset text (kb/vf_details)
  b_  record forensics (location, merge, phone, scale)
  c_  sources cited by the record (derived/v1)
  d_  official lists (NABH, NMC, e-RaktKosh, LaQshya, MoHFW trauma)
  e_  the facility's own website (kb/crawl, kb/web_evidence)
  f_  open data (OSM, Wikidata via kb/opendata)
  g_  facility type / operator / size / IPHS level prior
  h_  district and neighbourhood context (NFHS-5, MAP travel time, WorldPop): context, not evidence

Missing values stay NaN where the source cannot speak (for example no NABH code exists for MRI),
so coverage can be measured honestly. Binary flags are 0/1 floats.

Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python viz/features/build_features.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
OUT = ROOT / "viz/features/out"
OUT.mkdir(parents=True, exist_ok=True)

SERVICES = ["dialysis", "emergency_csection", "nicu", "cardiac_surgery", "mri", "burn_care", "trauma_emergency"]
WEB_ID = {s: s for s in SERVICES} | {"trauma_emergency": "trauma_care"}
NABH_CODES = {"dialysis": ["DIA", "NPH"], "emergency_csection": ["OBG"],
              "trauma_emergency": ["EMD"], "cardiac_surgery": ["CAR"]}  # CAR = cardiology, a proxy only
NMC_SVC = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu",
           "cardiac_surgery": "cardiac_surgery", "mri": "mri", "burn_care": "burns",
           "trauma_emergency": "trauma"}
OSM_SPEC = {"dialysis": ["nephrology", "dialysis"], "emergency_csection": ["gynaecology", "obstetrics", "maternity", "gynecolog"],
            "nicu": ["neonatology", "paediatrics", "pediatrics"], "cardiac_surgery": ["cardiac surgery", "cardiothoracic", "cardiology"],
            "mri": ["radiology", "mri"], "burn_care": ["plastic surgery", "burn"], "trauma_emergency": ["emergency", "trauma", "orthopaedics"]}
# equipment counts and 24x7 attributes from the dataset text (kb/vf_details), mapped to the service they speak for
EQUIP = {"dialysis": "dialysis_machines", "mri": "mri_tesla", "cardiac_surgery": "cath_labs"}
H24 = {"dialysis": "dialysis", "trauma_emergency": "emergency", "emergency_csection": "labour_room", "nicu": "icu"}
TODAY = pd.Timestamp("2026-11-21")
NFHS_COLS = {
    "institutional_birth_5y_pct": "h_nfhs_institutional_birth_pct",
    "births_delivered_by_csection_5y_pct": "h_nfhs_csection_pct",
    "hh_member_covered_health_insurance_pct": "h_nfhs_insurance_pct",
    "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct": "h_nfhs_women_high_sugar_pct",
}


def rp(rel):
    return pd.read_parquet(ROOT / rel)


def flag(s):
    return s.astype(float)


def claims_family(pf: pd.DataFrame) -> pd.DataFrame:
    a = rp("model/proto/evidence/claim_atoms.parquet")
    key = ["unique_id", "service"]
    per_field = (a.pivot_table(index=key, columns="field", values="atom_id", aggfunc="count", fill_value=0)
                 .add_prefix("a_m_").reset_index())
    own = a[a.counts_as_own]
    agg = a.groupby(key).agg(
        a_own_atoms=("counts_as_own", "sum"),
        a_own_anchored=("ownership", lambda s: int((s == "own_anchored").sum())),
        a_quantity=("role", lambda s: int((s == "quantity").sum() > 0)),
        a_list_role=("role", lambda s: int((s == "list").sum())),
    ).reset_index()
    qty = own.groupby(key).qty_value.apply(lambda s: int(s.notna().any())).rename("a_qty_own").reset_index()
    d = pf[key].merge(per_field, on=key, how="left").merge(agg, on=key, how="left").merge(qty, on=key, how="left")
    d = d.fillna(0)
    d["a_quantity"] = np.maximum(d.a_quantity, d.a_qty_own)
    d = d.drop(columns="a_qty_own")
    ft = rp("derived/v1/facility_trust.parquet")[["unique_id", "n_sentences", "n_sentences_other_facility"]]
    ft["a_quarantine_share"] = ft.n_sentences_other_facility / ft.n_sentences.replace(0, np.nan)
    d = d.merge(ft[["unique_id", "a_quarantine_share"]], on="unique_id", how="left")
    out = pd.DataFrame({
        "a_any_mention": flag(pf.n_atoms > 0),
        "a_n_atoms": pf.n_atoms.astype(float),
        "a_T": pf["T"].astype(float),
        "a_tag_only": flag(pf["T"] == 1),
        "a_n_fields_own": pf.n_fields_own.astype(float),
        "a_n_units_own": pf.n_units_own.astype(float),
        "a_prereq": pf["P"].astype(float),
        "a_negation": pf["N"].astype(float),
        "a_contamination": pf["C"].astype(float),
        "a_rejected_ownership": pf.n_rejected_ownership.astype(float),
        "a_scope_conflict": pf["S"].astype(float),
        "a_list_truncated": flag(pf.list_truncated),
        "a_grade": pf.grade.map({"no_mention": 0, "counter_evidence": 0, "attributed_elsewhere": 0,
                                 "tag_only": 1, "weak": 2, "moderate": 3, "strong": 4}).astype(float),
    })
    for f in ["procedure", "capability", "equipment", "description", "specialties"]:
        out[f"a_m_{f}"] = d[f"a_m_{f}"].values
    out["a_echo_dupes"] = np.maximum(d.a_own_atoms.values - pf.n_units_own.values, 0).astype(float)
    out["a_own_anchored"] = d.a_own_anchored.values
    out["a_quantity"] = d.a_quantity.values.astype(float)
    out["a_quarantine_share"] = d.a_quarantine_share.values
    out["a_pair_quarantine_share"] = np.where(pf.n_atoms > 0, pf.n_rejected_ownership / pf.n_atoms.replace(0, 1), np.nan)
    return out


def details_family(pf: pd.DataFrame) -> pd.DataFrame:
    fd = rp("kb/vf_details/out/facility_details.parquet")
    fd = fd[fd.n_usable > 0]
    has = lambda ft, at: set(fd[(fd.fact_type == ft) & (fd.attribute == at)].unique_id)
    uid = pf.unique_id
    out = pd.DataFrame(index=pf.index)
    out["k_text_nabh"] = flag(uid.isin(has("accreditation", "NABH")))
    out["k_text_pmjay"] = flag(uid.isin(has("empanelment", "pmjay")))
    out["k_text_cghs_echs"] = flag(uid.isin(has("empanelment", "cghs") | has("empanelment", "echs")))
    out["k_text_blood_bank"] = flag(uid.isin(has("blood_centre", "blood_bank")))
    out["k_text_ot_count"] = flag(uid.isin(has("equipment_count", "operation_theatres")))
    out["k_text_24x7_any"] = flag(uid.isin(set(fd[fd.fact_type == "hours_24x7"].unique_id)))
    eq = np.full(len(pf), np.nan)
    h24 = np.full(len(pf), np.nan)
    for s, at in EQUIP.items():
        m = (pf.service == s).values
        eq[m] = uid[m].isin(has("equipment_count", at)).astype(float)
    for s, at in H24.items():
        m = (pf.service == s).values
        h24[m] = uid[m].isin(has("hours_24x7", at)).astype(float)
    out["k_text_service_equipment_count"] = eq
    out["k_text_service_24x7"] = h24
    return out


def forensics_family(pf: pd.DataFrame) -> pd.DataFrame:
    fl = rp("derived/v1/facility_location.parquet")
    ff = rp("model/proto/evidence/facility_features.parquet")
    rt = rp("derived/v1/record_trust.parquet")
    fg = rp("derived/v1/facility_groups.parquet")
    lf = fl.set_index("unique_id").loc_flags.apply(lambda x: set(x) if x is not None else set())
    tf = rt.set_index("unique_id").trust_flags.apply(lambda x: set(x) if x is not None else set())
    sf = rt.set_index("unique_id").scale_flags.apply(lambda x: set(x) if x is not None else set())
    f = pd.DataFrame({"unique_id": fl.unique_id}).set_index("unique_id")
    flx = fl.set_index("unique_id")
    f["b_coord_pin_km"] = flx.raw_coords_to_pin_km
    f["b_coords_far_50km"] = (flx.raw_coords_to_pin_km > 50).astype(float).where(flx.raw_coords_to_pin_km.notna())
    f["b_loc_conf"] = flx.loc_conf.map({"high": 3, "medium": 2, "low": 1, "disputed": 0}).astype(float)
    f["b_disputed"] = flag(flx.loc_conf.eq("disputed"))
    f["b_city_points_elsewhere"] = flag(lf.apply(lambda s: bool(s & {"city_points_elsewhere", "both_points_elsewhere"})))
    f["b_copied_geocode"] = flag(lf.apply(lambda s: "copied_geocode" in s))
    ffx = ff.set_index("unique_id")
    f["b_votes_against"] = ffx.n_votes_against.astype(float)
    f["b_coord_shared_3plus"] = flag(ffx.coord_shared_3plus_names)
    f["b_n_source_ids"] = ffx.n_source_ids.astype(float)
    f["b_directory_phone"] = flag(ffx.phone_class.eq("shared_3plus"))
    f["b_no_phone"] = flag(ffx.phone_class.isin(["none", "invalid"]))
    f["b_dup_group"] = flag(fg.set_index("unique_id").group_size.gt(1))
    f["b_email_placeholder"] = flag(rt.set_index("unique_id").email_issue.eq("email_placeholder"))
    f["b_breadth_exceeds_size"] = flag(sf.apply(lambda s: "breadth_exceeds_size" in s))
    f["b_scale_implausible"] = flag(sf.apply(lambda s: bool(s & {"doctors_implausible", "capacity_implausible",
                                                                   "clinic_with_100plus_beds", "doctors_1_large_facility"})))
    f["b_claims_6plus_services"] = flag(tf.apply(lambda s: "claims_6plus_of_8_services" in s))
    f["b_website_other_org"] = flag(tf.apply(lambda s: "website_may_belong_to_other_org" in s))
    pfx = pf.drop_duplicates("unique_id").set_index("unique_id")
    f["b_merge_bucket"] = pfx.bucket.map({"low": 0, "mid": 1, "high": 2}).astype(float)
    out = pf[["unique_id"]].join(f, on="unique_id").drop(columns="unique_id")
    out["b_scale_contradiction"] = flag(pf.scale_contradiction)
    return out


def sources_family(pf: pd.DataFrame) -> pd.DataFrame:
    su = rp("derived/v1/source_urls.parquet")
    ft = rp("derived/v1/facility_trust.parquet").set_index("unique_id")
    g = su.groupby("unique_id")
    f = pd.DataFrame({"c_n_urls": g.size().astype(float)})
    mix = pd.crosstab(su.unique_id, su.source_class, normalize="index")
    for cls, col in [("official", "c_share_official"), ("health_aggregator", "c_share_aggregator"),
                     ("social", "c_share_social"), ("business_dir", "c_share_business_dir"),
                     ("government", "c_share_government"), ("maps_geo", "c_share_maps")]:
        f[col] = mix.get(cls, 0.0)
    kind = pd.crosstab(su.unique_id, su.url_kind, normalize="index")
    f["c_share_about_pages"] = kind.get("about", 0.0)
    f["c_mean_domain_reliability"] = g.domain_reliability.mean()
    f["c_source_support"] = ft.source_support
    # review fix: facility_trust.location_score is overwritten with the gold verdict (0.97 / 0.03) for 56 DEV and
    # 56 TEST facilities, so it copied sealed TEST labels into this table. Use score_model (before the override).
    dp = rp("derived/v1/data_point_scores.parquet")[["dp_type", "unique_id", "score_model"]]
    f["c_location_score_v1"] = dp[dp.dp_type == "location"].set_index("unique_id").score_model
    out = pf[["unique_id"]].join(f, on="unique_id").drop(columns="unique_id")
    # page check: was any cited sentence of this pair found on the page it is attributed to
    pc = rp("derived/v1/source_page_checks.parquet").dropna(subset=["claim_id"])
    tested = set(pc.claim_id)
    supported = set(pc[pc.supported == True].claim_id)  # noqa: E712
    import re
    claim_re = re.compile(r"[0-9a-f]{8}:[a-z]{4}:\d+")  # atom ids are "<claim_id>|<service>", joined by a separator

    def ids(s):
        return claim_re.findall(s) if isinstance(s, str) else []
    cited = pf.cited_atom_ids.apply(ids)
    t = cited.apply(lambda c: any(x in tested for x in c))
    out["c_pagecheck_supported"] = np.where(t, cited.apply(lambda c: float(any(x in supported for x in c))), np.nan)
    return out


def lists_family(pf: pd.DataFrame, loc: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=pf.index)
    uid, svc = pf.unique_id, pf.service
    nb = rp("data/external/nabh_accredited/nabh_vf_match.parquet")
    nb = nb[nb.accept]
    out["d_nabh_listed"] = flag(uid.isin(set(nb.unique_id)))
    full = set(nb[nb.prefix.isin(["H", "SHCO"])].unique_id)
    out["d_nabh_full_accreditation"] = flag(uid.isin(full))
    codes = nb.set_index("unique_id").nabh_specs.apply(lambda x: set(x) if x is not None else set())
    has_codes = set(codes[codes.apply(len) > 0].index)
    v = np.full(len(pf), np.nan)
    for s, cs in NABH_CODES.items():
        m = (svc == s).values
        v[m] = uid[m].map(lambda u: float(bool(codes.get(u, set()) & set(cs)))).values
        # NABH silence only means something for facilities NABH lists with at least one fetched code
    out["d_nabh_service_code"] = v
    out["d_nabh_code_known"] = flag(uid.isin(has_codes))
    nm = rp("data/external/nmc_colleges/nmc_vf_matches.parquet")
    nl = rp("data/external/nmc_colleges/nmc_service_labels.parquet")
    nmx = nm.merge(nl, on="college_id")
    out["d_nmc_college"] = flag(uid.isin(set(nm.unique_id)))
    strong = set(zip(nmx[nmx.tier == "strong"].unique_id, nmx[nmx.tier == "strong"].service))
    support = set(zip(nmx.unique_id, nmx.service))
    out["d_nmc_course_strong"] = [float((u, NMC_SVC[s]) in strong) for u, s in zip(uid, svc)]
    out["d_nmc_course_any"] = [float((u, NMC_SVC[s]) in support) for u, s in zip(uid, svc)]
    er = rp("data/external/eraktkosh_blood_centres/erk_vf_matches.parquet")
    out["d_erk_blood_centre_on_site"] = flag(uid.isin(set(er.unique_id)))
    # distance to the nearest e-RaktKosh centre with a usable coordinate (shared by < 3 centres)
    ec = rp("data/external/eraktkosh_blood_centres/erk_centres.parquet").dropna(subset=["latitude", "longitude"])
    ec = ec[ec.groupby(["latitude", "longitude"]).name.transform("size") < 3]
    from sklearn.neighbors import BallTree
    tree = BallTree(np.radians(ec[["latitude", "longitude"]].values), metric="haversine")
    ok = loc.loc_lat.notna() & loc.loc_lon.notna()
    dist = pd.Series(np.nan, index=loc.index)
    dd, _ = tree.query(np.radians(loc.loc[ok, ["loc_lat", "loc_lon"]].values), k=1)
    dist[ok] = dd[:, 0] * 6371.0
    km = uid.map(dist)
    out["d_erk_nearest_km"] = km.values
    out["d_erk_within_10km"] = (km <= 10).astype(float).where(km.notna()).values
    lq = rp("data/external/laqshya_master/laqshya_vf_matches.parquet")
    lf = rp("data/external/laqshya_master/laqshya_facilities.parquet")
    lqm = lq.merge(lf[["lq_id", "Maternity OT", "Labour Room"]], on="lq_id", how="left")
    ot_valid = set(lqm[lqm["Maternity OT"] >= TODAY].unique_id)
    ot_any = set(lqm[lqm["Maternity OT"].notna()].unique_id)
    lr_any = set(lqm[lqm["Labour Room"].notna()].unique_id)
    cs = (svc == "emergency_csection").values
    for col, st in [("d_laqshya_ot_valid", ot_valid), ("d_laqshya_ot_ever", ot_any), ("d_laqshya_labour_room", lr_any)]:
        v = np.full(len(pf), np.nan)
        v[cs] = uid[cs].isin(st).astype(float)
        out[col] = v
    tc = pd.read_csv(ROOT / "data/external/mohfw_trauma_196/tcf_vf_matches.csv")
    v = np.full(len(pf), np.nan)
    tr = (svc == "trauma_emergency").values
    v[tr] = uid[tr].isin(set(tc.vf_id)).astype(float)
    out["d_mohfw_trauma_centre"] = v
    return out


def website_family(pf: pd.DataFrame) -> pd.DataFrame:
    uid, svc = pf.unique_id, pf.service
    tg = rp("kb/crawl/targets.parquet").explode("unique_ids")
    sites = rp("kb/crawl/sites.parquet")
    alive_t = set(sites[sites.site_status.isin(["ok", "ok_thin"])].target_id)
    out = pd.DataFrame(index=pf.index)
    out["e_has_website"] = flag(uid.isin(set(tg.unique_ids)))
    alive = set(tg[tg.target_id.isin(alive_t)].unique_ids)
    out["e_site_alive"] = np.where(out.e_has_website == 1, uid.isin(alive).astype(float), np.nan)
    si = rp("kb/web_evidence/out/site_identity.parquet")
    conf = si.assign(c=si.confidence.map({"high": 3, "medium": 2, "low": 1, "none": 0})).groupby("unique_id").c.max()
    out["e_identity_conf"] = np.where(out.e_site_alive == 1, uid.map(conf).fillna(0), np.nan)
    attributable = set(si[si.attributable].unique_id)
    ws = rp("kb/web_evidence/out/web_service_summary.parquet")
    ws = ws[ws.unique_id.isin(attributable)]
    key = set(zip(ws[ws.web_positive].unique_id, ws[ws.web_positive].service_id))
    keys = set(zip(ws[ws.web_positive_strong].unique_id, ws[ws.web_positive_strong].service_id))
    keyp = set(zip(ws[ws.positive_on_services_page].unique_id, ws[ws.positive_on_services_page].service_id))
    keyn = set(zip(ws[ws.n_negated_rows > 0].unique_id, ws[ws.n_negated_rows > 0].service_id))
    crawled = uid.isin(attributable)
    for col, k in [("e_web_service", key), ("e_web_service_strong", keys), ("e_web_service_page", keyp),
                   ("e_web_negated", keyn)]:
        out[col] = np.where(crawled, [float((u, WEB_ID[s]) in k) for u, s in zip(uid, svc)], np.nan)
    wh = rp("kb/web_evidence/out/web_hours.parquet")
    wh = wh[(wh.status == "ok") & wh.attributable]
    out["e_web_hours_found"] = np.where(crawled, uid.isin(set(wh.unique_id)).astype(float), np.nan)
    em = set(wh[(wh.fact_type == "hours_24x7") & (wh.attribute == "emergency")].unique_id)
    out["e_web_24x7_emergency"] = np.where(crawled, uid.isin(em).astype(float), np.nan)
    wf = rp("kb/web_evidence/out/web_facility_details.parquet")
    nab = set(wf[(wf.fact_type == "accreditation") & (wf.attribute == "NABH") & (wf.n_usable > 0)].unique_id)
    out["e_web_nabh_claim"] = np.where(crawled, uid.isin(nab).astype(float), np.nan)
    return out


def opendata_family(pf: pd.DataFrame) -> pd.DataFrame:
    uid, svc = pf.unique_id, pf.service
    m = rp("kb/opendata/vf_opendata_match.parquet")
    osm = m[m.source == "osm"].set_index("unique_id")
    wd = m[m.source == "wikidata"].set_index("unique_id")
    out = pd.DataFrame(index=pf.index)
    out["f_osm_match"] = uid.map(osm.tier.isin(["high", "medium"]).astype(float)).fillna(0).values
    out["f_osm_conflict"] = uid.map(osm.tier.eq("conflict").astype(float)).fillna(0).values
    out["f_wikidata_match"] = uid.map(wd.tier.isin(["high", "medium"]).astype(float)).fillna(0).values
    of = rp("kb/opendata/vf_opendata_facts.parquet")
    matched = out.f_osm_match == 1
    emerg = set(of[(of.field == "emergency") & (of.value == "yes")].unique_id)
    hours = set(of[of.field == "opening_hours"].unique_id)
    h24 = set(of[(of.field == "is_24x7") & (of.value == "True")].unique_id)
    out["f_osm_emergency_yes"] = np.where(matched, uid.isin(emerg).astype(float), np.nan)
    out["f_osm_opening_hours"] = np.where(matched, uid.isin(hours).astype(float), np.nan)
    out["f_osm_24x7"] = np.where(matched, uid.isin(h24).astype(float), np.nan)
    sp = of[of.field == "speciality"].groupby("unique_id").value.apply(lambda s: ";".join(s).lower())
    has_sp = uid.isin(set(sp.index))
    out["f_osm_speciality_service"] = np.where(
        has_sp, [float(any(w in sp.get(u, "") for w in OSM_SPEC[s])) for u, s in zip(uid, svc)], np.nan)
    return out


def type_family(pf: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=pf.index)
    for t in ["hospital", "clinic", "dentist"]:
        out[f"g_type_{t}"] = flag(pf.facility_type.eq(t))
    out["g_public"] = flag(pf.operator_public)
    out["g_public_level"] = pf.public_level.map({"none": np.nan, "phc": 1, "chc": 2, "sdh": 3, "dh": 4, "mc": 5}).values
    out["g_medical_college"] = flag(pf.public_level.eq("mc"))
    out["g_iphs_essential"] = flag(pf.iphs_essential)
    out["g_log_beds"] = np.log10(pf.beds.where(pf.beds > 0))
    out["g_log_doctors"] = np.log10(pf.doctors.where(pf.doctors > 0))
    out["g_n_specialties"] = pf.n_specialties.astype(float)
    return out


def context_family(pf: pd.DataFrame, loc: pd.DataFrame) -> pd.DataFrame:
    nf = rp("data/raw/nfhs_5_district_health_indicators.parquet")
    key = loc[["nfhs_state_ut", "nfhs_district_name"]]
    nf = nf.rename(columns={"state_ut": "nfhs_state_ut", "district_name": "nfhs_district_name"})
    j = key.reset_index().merge(nf[["nfhs_state_ut", "nfhs_district_name", *NFHS_COLS]], how="left",
                                on=["nfhs_state_ut", "nfhs_district_name"]).drop_duplicates("unique_id").set_index("unique_id")
    out = pd.DataFrame(index=pf.index)
    for src, col in NFHS_COLS.items():
        out[col] = pf.unique_id.map(pd.to_numeric(j[src], errors="coerce")).values
    fa = rp("data/external/map_travel_time_healthcare_2020/derived/facility_access.parquet").drop_duplicates("unique_id").set_index("unique_id")
    out["h_tt_motor_min"] = pf.unique_id.map(fa.tt_motor).values
    wp = rp("data/external/worldpop_r2025a/derived/facility_population.parquet").drop_duplicates("unique_id").set_index("unique_id")
    out["h_log_pop_25km"] = np.log10(pf.unique_id.map(wp.pop_25km).where(lambda s: s > 0)).values
    # supply around the point: other VF records within 25 km (any service), from the ranking points
    from sklearn.neighbors import BallTree
    ok = loc.dropna(subset=["loc_lat", "loc_lon"])
    tree = BallTree(np.radians(ok[["loc_lat", "loc_lon"]].values), metric="haversine")
    cnt = tree.query_radius(np.radians(ok[["loc_lat", "loc_lon"]].values), r=25 / 6371.0, count_only=True) - 1
    out["h_vf_records_25km"] = pf.unique_id.map(pd.Series(np.log10(cnt + 1), index=ok.index)).values
    return out


def main():
    pf = rp("model/proto/evidence/pair_features.parquet")
    assert len(pf) == 69_713 and set(pf.service) == set(SERVICES), (len(pf), set(pf.service))
    loc = rp("derived/v1/facility_location.parquet").set_index("unique_id")
    parts = [pf[["unique_id", "service"]],
             claims_family(pf), details_family(pf), forensics_family(pf), sources_family(pf),
             lists_family(pf, loc), website_family(pf), opendata_family(pf), type_family(pf),
             context_family(pf, loc)]
    for p in parts[1:]:
        p.index = pf.index
    d = pd.concat(parts, axis=1)
    d["state"] = d.unique_id.map(loc.state_final)
    lg = rp("model/proto/evidence/facility_features.parquet").set_index("unique_id").leakage_group_id
    d["leakage_group_id"] = d.unique_id.map(lg)
    assert d.unique_id.notna().all() and len(d) == len(pf)
    d.to_parquet(OUT / "features_pairs.parquet", index=False)
    feats = [c for c in d.columns if c[:2] in {"a_", "k_", "b_", "c_", "d_", "e_", "f_", "g_", "h_"}]
    summ = {c: dict(coverage=round(float(d[c].notna().mean()), 4),
                    nonzero=round(float((d[c].fillna(0) != 0).mean()), 4)) for c in feats}
    (OUT / "build_summary.json").write_text(json.dumps(dict(rows=len(d), n_features=len(feats), features=summ), indent=1))
    print(len(d), "rows", len(feats), "features")
    for c in feats:
        print(f"{c:34s} cov {summ[c]['coverage']:.3f} nonzero {summ[c]['nonzero']:.4f}")


if __name__ == "__main__":
    main()

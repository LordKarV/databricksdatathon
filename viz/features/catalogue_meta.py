"""Hand-written metadata for every candidate feature: family, definition, source, expected direction,
the phrase a card would show, and source tags used to derive leakage risk per label source.

Direction: "+" more of it should mean a public check is more likely to confirm the service,
"-" less likely, "context" not evidence about this facility (district or neighbourhood),
"?" no prior expectation. {svc} in a phrase is replaced by the service name on the card.

Tags (what the value is built from): text (the record's own sentences), struct (structured record
fields), loc (location fields), src (the record's cited source URLs), gold (fitted or updated with
gold DEV labels), web (the facility's own website crawl), nabh, nmc, erk, laqshya, mohfw, osm,
type (type/operator/size), ctx (district context).
"""

FAMILIES = {
    "a": "Dataset claims", "k": "Dataset details", "b": "Record forensics", "c": "Cited sources",
    "d": "Official lists", "e": "Own website", "f": "Open data", "g": "Type and size", "h": "District context",
}

DS = "model/proto/evidence/pair_features.parquet"
CA = "model/proto/evidence/claim_atoms.parquet"
VD = "kb/vf_details/out/facility_details.parquet"
FL = "derived/v1/facility_location.parquet"
FF = "model/proto/evidence/facility_features.parquet"
RT = "derived/v1/record_trust.parquet"
SU = "derived/v1/source_urls.parquet"
WS = "kb/web_evidence/out/web_service_summary.parquet"
SI = "kb/web_evidence/out/site_identity.parquet"
OD = "kb/opendata/vf_opendata_match.parquet + vf_opendata_facts.parquet"

# name: (definition, source, direction, card phrase, tags)
META = {
    "a_any_mention": ("Any claim sentence or specialty tag names the service", DS, "+", "its listing mentions {svc}", "text"),
    "a_n_atoms": ("Number of claim atoms (sentence x service) before ownership and echo rules", CA, "+", "{svc} appears {n} times in its listing", "text"),
    "a_T": ("Text level 0-5: 0 none, 1 tag or list only, 2 one own unit, 3 two units in one field, 4 units in 2+ fields, 5 level 4 plus a quantity", DS, "+", "its own listing describes {svc} (text level {n} of 5)", "text"),
    "a_tag_only": ("Only a specialty tag or list item names the service (T = 1)", DS, "?", "only a specialty tag mentions {svc}", "text"),
    "a_n_fields_own": ("Distinct record fields with an own, offer-type sentence about the service", DS, "+", "{svc} is described in {n} different fields", "text"),
    "a_n_units_own": ("Own offer units after echo collapse (near-identical sentences across fields count once)", DS, "+", "{n} distinct sentences say it offers {svc}", "text"),
    "a_prereq": ("Distinct clinical prerequisites for the service (ICU, OT, blood bank...) named in other sentences, 0-2", DS, "+", "it lists what {svc} needs (for example an ICU or operating theatre)", "text"),
    "a_negation": ("A sentence about the service carries a non-offer cue (referral, camp, future, negation)", DS, "-", "a sentence suggests {svc} may not be offered here routinely (referral, camp, plan or negation)", "text"),
    "a_contamination": ("Rejected-for-ownership atoms beside the claim: 1 with T >= 2, 2 with T <= 1", DS, "-", "some {svc} text is about another hospital", "text"),
    "a_rejected_ownership": ("Atoms about the service rejected because they name another facility, branch or state", DS, "-", "we ignored {n} sentences that name another facility", "text"),
    "a_scope_conflict": ("Facility is an eye, dental, IVF or lab centre by name or type (S = 1 on every service of that facility)", DS, "-", "an eye, dental or lab centre, unlikely to offer {svc}", "text struct"),
    "a_list_truncated": ("The record's list fields look truncated", DS, "?", "part of its listing is cut off", "text"),
    "a_grade": ("Rule grade of the claim: 0 none, 1 tag, 2 weak, 3 moderate, 4 strong (derived/v1/grades.parquet logic)", DS, "+", "rule grade: {grade}", "text gold"),
    "a_m_procedure": ("Claim atoms about the service in the procedure field", CA, "+", "named as a procedure", "text"),
    "a_m_capability": ("Claim atoms about the service in the capability field", CA, "+", "named as a capability", "text"),
    "a_m_equipment": ("Claim atoms about the service in the equipment field", CA, "+", "named in its equipment list", "text"),
    "a_m_description": ("Claim atoms about the service in the free-text description", CA, "+", "named in its description", "text"),
    "a_m_specialties": ("Specialty-enum hits mapped to the service", CA, "?", "listed among its specialties", "text"),
    "a_echo_dupes": ("Own atoms removed by echo collapse (copies of one sentence across fields)", CA, "?", "{n} repeated copies of the same sentence were counted once", "text"),
    "a_own_anchored": ("Atoms whose sentence names the facility itself", CA, "+", "a sentence names this hospital and {svc} together", "text"),
    "a_quantity": ("An own atom carries a quantity (beds, machines, cases)", CA, "+", "it gives a number for {svc} (for example beds or machines)", "text"),
    "a_quarantine_share": ("Share of the record's sentences quarantined as about another facility", "derived/v1/facility_trust.parquet", "-", "{pct} of its sentences are about other facilities", "text"),
    "a_pair_quarantine_share": ("Share of this service's atoms rejected for ownership (pairs with a mention)", DS, "-", "{pct} of its {svc} text is about other facilities", "text"),
    "k_text_nabh": ("Dataset text claims NABH accreditation", VD, "+", "its listing says it is NABH accredited (not checked)", "text"),
    "k_text_pmjay": ("Dataset text claims PM-JAY empanelment", VD, "+", "its listing says it takes PM-JAY", "text"),
    "k_text_cghs_echs": ("Dataset text claims CGHS or ECHS empanelment", VD, "+", "its listing says CGHS or ECHS empanelled", "text"),
    "k_text_blood_bank": ("Dataset text says there is an on-site blood bank", VD, "+", "its listing says it has a blood bank", "text"),
    "k_text_ot_count": ("Dataset text gives a number of operation theatres", VD, "+", "its listing gives an operation theatre count", "text"),
    "k_text_24x7_any": ("Dataset text says some service is 24x7", VD, "+", "its listing says something runs 24x7", "text"),
    "k_text_service_equipment_count": ("Dataset text gives a count for the service's key equipment (dialysis machines, MRI tesla, cath labs)", VD, "+", "its listing gives a {svc} equipment count", "text"),
    "k_text_service_24x7": ("Dataset text says the matching unit is 24x7 (dialysis, emergency, labour room, ICU)", VD, "+", "its listing says the {svc} unit runs 24x7", "text"),
    "b_coord_pin_km": ("Distance from the raw coordinate to its own PIN centroid, km", FL, "-", "its map pin is {n} km from its postcode", "loc"),
    "b_coords_far_50km": ("Raw coordinate more than 50 km from its own PIN centroid", FL, "-", "its map pin is more than 50 km from its postcode", "loc"),
    "b_loc_conf": ("Cleaning location confidence: 3 high, 2 medium, 1 low, 0 disputed", FL, "+", "location confidence: {conf}", "loc gold"),
    "b_disputed": ("Location disputed by the cleaning step", FL, "-", "where it is, is disputed", "loc"),
    "b_city_points_elsewhere": ("Stated city lies far from the chosen point", FL, "-", "its stated town points somewhere else", "loc"),
    "b_copied_geocode": ("Coordinate copied from another record (same point, different names)", FL, "-", "its map pin is shared with other facilities", "loc"),
    "b_votes_against": ("Location witnesses voting against the chosen point (0-7)", FF, "-", "{n} location clues disagree", "loc"),
    "b_coord_shared_3plus": ("Coordinate shared by 3 or more names", FF, "-", "its map pin is shared by 3 or more names", "loc"),
    "b_n_source_ids": ("Number of source records merged into this row", FF, "?", "built from {n} source records", "src"),
    "b_directory_phone": ("Official phone appears in 3 or more cities (a directory number)", FF, "-", "its phone number is a directory number used in 3+ cities", "struct"),
    "b_no_phone": ("No usable phone number", FF, "-", "no phone number in the listing", "struct"),
    "b_dup_group": ("Member of a strong duplicate group", "derived/v1/facility_groups.parquet", "?", "this facility appears more than once in the data", "struct"),
    "b_email_placeholder": ("Email is a Cloudflare placeholder, not an address", RT, "-", "its email is a placeholder", "struct"),
    "b_breadth_exceeds_size": ("More specialties than its stated size supports", RT, "-", "claims more specialties than its size suggests", "struct"),
    "b_scale_implausible": ("Implausible doctors, beds or capacity values", RT, "-", "its size numbers look implausible", "struct"),
    "b_claims_6plus_services": ("Claims 6 or more of the 8 audit services", RT, "-", "claims nearly every service we track", "text"),
    "b_website_other_org": ("The website may belong to another organisation", RT, "-", "its website may belong to someone else", "struct web"),
    "b_merge_bucket": ("Merged-record bucket from the audit: 0 low, 1 mid, 2 high (how many pages the record was built from)", DS, "?", "built from many web pages", "src"),
    "b_scale_contradiction": ("Stated size contradicts the service (for example a 5-bed clinic claiming cardiac surgery)", DS, "-", "too small for {svc} by its own numbers", "struct"),
    "c_n_urls": ("Number of source URLs cited by the record", SU, "+", "its listing cites {n} web pages", "src"),
    "c_share_official": ("Share of cited URLs on the facility's own domain", SU, "+", "{pct} of its sources are its own website", "src"),
    "c_share_aggregator": ("Share of cited URLs on health aggregators (Practo, Justdial...)", SU, "?", "{pct} of its sources are health directories", "src"),
    "c_share_social": ("Share of cited URLs on social media", SU, "?", "{pct} of its sources are social media", "src"),
    "c_share_business_dir": ("Share of cited URLs on business directories", SU, "-", "{pct} of its sources are business directories", "src"),
    "c_share_government": ("Share of cited URLs on government domains", SU, "+", "{pct} of its sources are government sites", "src"),
    "c_share_maps": ("Share of cited URLs on map services", SU, "?", "{pct} of its sources are map pages", "src"),
    "c_share_about_pages": ("Share of cited URLs that are about-this-facility pages (not lists)", SU, "+", "{pct} of its sources are pages about it", "src"),
    "c_mean_domain_reliability": ("Mean reliability of the cited domains (derived/v1 fit)", SU, "+", "its sources are usually right ({n})", "src gold"),
    "c_source_support": ("Identity-profile weighted source reliability (derived/v1)", "derived/v1/facility_trust.parquet", "+", "source reliability {n}", "src gold"),
    "c_location_score_v1": ("derived/v1 location score before the gold override (score_model); its evidence rates and source reliabilities were updated with gold DEV labels", "derived/v1/data_point_scores.parquet", "+", "location score {n}", "loc src gold"),
    "c_pagecheck_supported": ("A cited sentence about the service was found on the page it is attributed to (tested pairs only)", "derived/v1/source_page_checks.parquet", "+", "we found this sentence on its cited page", "src"),
    "d_nabh_listed": ("Matched to the NABH list (any programme)", "data/external/nabh_accredited/nabh_vf_match.parquet", "+", "listed by NABH ({status})", "nabh"),
    "d_nabh_full_accreditation": ("NABH full hospital accreditation (H or SHCO programme), not entry-level", "data/external/nabh_accredited/nabh_vf_match.parquet", "+", "fully accredited by NABH", "nabh"),
    "d_nabh_service_code": ("NABH lists the service's specialty code (DIA/NPH dialysis, OBG C-section, EMD trauma, CAR cardiology as a proxy for cardiac surgery); missing for NICU, MRI, burns", "data/external/nabh_accredited/nabh_hco_specialty.parquet", "+", "NABH lists its {code} department (a department, not proof of this service)", "nabh"),
    "d_nabh_code_known": ("NABH lists at least one of the 7 fetched specialty codes for this facility", "data/external/nabh_accredited/nabh_vf_match.parquet", "+", "NABH lists its specialties", "nabh"),
    "d_nmc_college": ("Matched to an NMC MBBS teaching college", "data/external/nmc_colleges/nmc_vf_matches.parquet", "+", "an NMC-recognised teaching hospital", "nmc"),
    "d_nmc_course_strong": ("NMC lists the matching super-specialty course (DM Nephrology, MS OBG, DM Neonatology, MCh CTVS, MCh Plastic, MS Ortho / MD EM / MCh Neuro)", "data/external/nmc_colleges/nmc_service_labels.parquet", "+", "NMC lists {course} seats here", "nmc"),
    "d_nmc_course_any": ("NMC lists a strong or supporting course for the service (adds MD Paediatrics, MD Radiology, DM Cardiology)", "data/external/nmc_colleges/nmc_service_labels.parquet", "+", "NMC lists a {svc}-related department here", "nmc"),
    "d_erk_blood_centre_on_site": ("Matched to an e-RaktKosh blood centre", "data/external/eraktkosh_blood_centres/erk_vf_matches.parquet", "+", "e-RaktKosh lists a blood centre here", "erk"),
    "d_erk_nearest_km": ("Distance to the nearest e-RaktKosh blood centre with a usable coordinate, km", "data/external/eraktkosh_blood_centres/erk_centres.parquet", "-", "nearest government-listed blood centre: {n} km", "erk loc"),
    "d_erk_within_10km": ("An e-RaktKosh blood centre within 10 km", "data/external/eraktkosh_blood_centres/erk_centres.parquet", "+", "a listed blood centre within 10 km", "erk loc"),
    "d_laqshya_ot_valid": ("LaQshya Maternity OT certificate valid on 2026-11-21 (C-section only)", "data/external/laqshya_master/laqshya_vf_matches.parquet", "+", "LaQshya-certified maternity OT, valid to {date}", "laqshya"),
    "d_laqshya_ot_ever": ("Any LaQshya Maternity OT certificate, current or expired (C-section only)", "data/external/laqshya_master/laqshya_vf_matches.parquet", "+", "held a LaQshya maternity OT certificate (may have expired)", "laqshya"),
    "d_laqshya_labour_room": ("Any LaQshya Labour Room certificate (C-section only)", "data/external/laqshya_master/laqshya_vf_matches.parquet", "+", "LaQshya-certified labour room", "laqshya"),
    "d_mohfw_trauma_centre": ("On the MoHFW list of 196 trauma care facilities (trauma only)", "data/external/mohfw_trauma_196/tcf_vf_matches.csv", "+", "on the MoHFW trauma care facility list", "mohfw"),
    "e_has_website": ("The record names a website that the crawl targeted", "kb/crawl/targets.parquet", "+", "has a website", "web"),
    "e_site_alive": ("The website answered with usable pages (sites with a target)", "kb/crawl/sites.parquet", "+", "its website is live", "web"),
    "e_identity_conf": ("Confidence that the live site is this facility (name, PIN, locality found): 0-3", SI, "+", "its website matches this facility ({conf} confidence)", "web"),
    "e_web_service": ("Its own attributable website mentions the service positively", WS, "+", "its own website mentions {svc}", "web"),
    "e_web_service_strong": ("Its own website mentions the service in an offer sentence (strong)", WS, "+", "its own website says it offers {svc}", "web"),
    "e_web_service_page": ("The service is on the site's services or departments page", WS, "+", "{svc} is on its website's services page", "web"),
    "e_web_negated": ("Its own website negates the service", WS, "-", "its own website says it does not offer {svc}", "web"),
    "e_web_hours_found": ("Opening hours or 24x7 statement found on its own site", "kb/web_evidence/out/web_hours.parquet", "+", "its website gives opening hours", "web"),
    "e_web_24x7_emergency": ("Its own site says the emergency runs 24x7", "kb/web_evidence/out/web_hours.parquet", "+", "its website says emergency is open 24x7", "web"),
    "e_web_nabh_claim": ("Its own site claims NABH accreditation", "kb/web_evidence/out/web_facility_details.parquet", "+", "its website says NABH accredited", "web"),
    "f_osm_match": ("Matched to an OpenStreetMap health facility (high or medium tier)", OD, "+", "found on OpenStreetMap", "osm loc"),
    "f_osm_conflict": ("An OSM candidate with the same name sits far from the record's point", OD, "-", "a same-name OpenStreetMap facility is somewhere else", "osm loc"),
    "f_wikidata_match": ("Matched to a Wikidata medical facility", OD, "+", "has a Wikidata entry", "osm"),
    "f_osm_emergency_yes": ("OSM emergency=yes (OSM-matched only)", OD, "+", "OpenStreetMap tags an emergency department", "osm"),
    "f_osm_opening_hours": ("OSM opening_hours present (OSM-matched only)", OD, "+", "OpenStreetMap gives opening hours", "osm"),
    "f_osm_24x7": ("OSM opening_hours is 24/7 (OSM-matched only)", OD, "+", "OpenStreetMap says open 24/7", "osm"),
    "f_osm_speciality_service": ("OSM healthcare:speciality matches the service (OSM-matched with a speciality tag only)", OD, "+", "OpenStreetMap lists the matching speciality", "osm"),
    "g_type_hospital": ("Facility type hospital", DS, "+", "a hospital", "type"),
    "g_type_clinic": ("Facility type clinic", DS, "-", "a clinic", "type"),
    "g_type_dentist": ("Facility type dentist", DS, "-", "a dental clinic", "type"),
    "g_public": ("Public operator", DS, "?", "a government facility", "type"),
    "g_public_level": ("Public facility level from the name: 1 PHC, 2 CHC, 3 SDH, 4 DH, 5 medical college (public only)", DS, "+", "a {level}", "type"),
    "g_medical_college": ("Name or type says medical college", DS, "+", "a medical college hospital", "type"),
    "g_iphs_essential": ("IPHS 2022 lists the service as essential at this public level", DS, "+", "the public standard (IPHS 2022) expects {svc} at a {level}", "type"),
    "g_log_beds": ("log10 stated beds", DS, "+", "{n} beds (stated)", "struct type"),
    "g_log_doctors": ("log10 stated doctors", DS, "+", "{n} doctors (stated)", "struct type"),
    "g_n_specialties": ("Number of specialty tags", DS, "+", "{n} specialties listed", "text type"),
    "h_nfhs_institutional_birth_pct": ("District share of births in a facility (NFHS-5)", "data/raw/nfhs_5_district_health_indicators.parquet", "context", "district: {pct} of births happen in a facility", "ctx"),
    "h_nfhs_csection_pct": ("District share of births by C-section (NFHS-5)", "data/raw/nfhs_5_district_health_indicators.parquet", "context", "district: {pct} of births are by C-section", "ctx"),
    "h_nfhs_insurance_pct": ("District share of households with health insurance (NFHS-5)", "data/raw/nfhs_5_district_health_indicators.parquet", "context", "district: {pct} of households have health insurance", "ctx"),
    "h_nfhs_women_high_sugar_pct": ("District share of women 15+ with high blood sugar (NFHS-5)", "data/raw/nfhs_5_district_health_indicators.parquet", "context", "district: {pct} of women have high blood sugar", "ctx"),
    "h_tt_motor_min": ("Motorised travel time from the point to the nearest healthcare facility, MAP 2020 raster, minutes", "data/external/map_travel_time_healthcare_2020/derived/facility_access.parquet", "context", "{n} min by road to the nearest facility of any kind", "ctx loc"),
    "h_log_pop_25km": ("log10 population within 25 km (WorldPop 2025)", "data/external/worldpop_r2025a/derived/facility_population.parquet", "context", "about {n} people live within 25 km", "ctx loc"),
    "h_vf_records_25km": ("log10(1 + other VF records within 25 km)", FL, "context", "{n} other listed facilities within 25 km", "ctx loc"),
}


def family_of(name: str) -> str:
    return FAMILIES[name[0]]


def leakage(name: str) -> dict:
    """Leakage risk of a feature against each label source, from its tags.

    Levels (worst first): direct (the label is read off the same list), fitted (weights or rules
    were updated with gold DEV labels), shared (feature and label read the same pages),
    selection (the list matcher's gates or the list's scope depend on this feature),
    design (the gold sample was stratified on this feature), none.
    """
    tags = set(META[name][4].split())
    gold = ("fitted" if "gold" in tags else "shared" if tags & {"web", "src", "nabh"} else
            "design" if "text" in tags else "none")
    nabh = ("direct" if "nabh" in tags else "shared" if name in {"k_text_nabh", "e_web_nabh_claim"} else
            "none")
    lists = ("direct" if tags & {"nabh", "nmc", "laqshya", "mohfw"} else
             "shared" if name in {"k_text_nabh", "e_web_nabh_claim"} else
             "selection" if tags & {"loc", "type"} or name in {"f_osm_match"} else "none")
    return {"gold_web_check": gold, "nabh_codes": nabh, "official_lists": lists}


if __name__ == "__main__":
    assert all(len(v) == 5 for v in META.values())
    assert leakage("d_nabh_service_code")["nabh_codes"] == "direct"
    assert leakage("a_T")["gold_web_check"] == "design"
    assert leakage("c_location_score_v1")["gold_web_check"] == "fitted"
    print(len(META), "features described; self-check OK")

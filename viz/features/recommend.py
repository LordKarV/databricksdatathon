"""Turn the measured statistics into a recommendation per feature and write the catalogue.

Decisions are hand-made from out/univariate.parquet (read the numbers in features_catalogue.csv
next to each reason). Heads: S service (P_S), L location (P_L), E existence (P_E), X official-list
evidence (family X of MODEL_SPEC, never a label for the same list), R hard rule or guard,
D display on the card only, C context only (never evidence about the facility).

Writes viz/features/features_catalogue.csv and viz/features/recommended_feature_set.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import catalogue_meta as M

HERE = Path(__file__).parent

# feature: (recommendation, head, reason)
K, KX, D, C, X = "keep", "keep (list evidence)", "display only", "context only", "drop"
DECISIONS = {
    "a_any_mention": (X, "-", "Same cluster as a_T (rho 0.998); a_T >= 1 is the same flag."),
    "a_n_atoms": (X, "-", "Highest DEV AUROC among text counts but counts echoes; same cluster as a_T. Use a_T."),
    "a_T": (K, "S", "Cluster representative for own-text strength; agrees in direction on all three label sources."),
    "a_tag_only": (X, "-", "Encoded by a_T = 1; no association on any label source."),
    "a_n_fields_own": (X, "-", "rho 0.999 with a_n_units_own; both are inside a_T levels 3-4."),
    "a_n_units_own": (X, "-", "Inside a_T; keep the echo-collapsed count for the card text only."),
    "a_prereq": (K, "S", "Strongest text feature on both PU label sets and positive on DEV; independent of the service sentence."),
    "a_negation": (K, "R", "Fires on 43 pairs, too rare to measure; a hand-checked rule (34 of 40 non-offer). Keep as a guard."),
    "a_contamination": (K, "S", "Negative by construction; drives 'What we ignored'. Too rare to measure (0.2% of pairs)."),
    "a_rejected_ownership": (D, "D", "rho 1.0 with a_contamination; show the rejected sentences, do not score them twice."),
    "a_scope_conflict": (K, "S", "Strongly negative on official lists (AUROC 0.35); no DEV pair has it, so the weight must be a prior."),
    "a_list_truncated": (K, "S", "Positive on all label sets; a truncated list makes silence less informative. Correlates with c_n_urls (0.55)."),
    "a_grade": (X, "-", "Rule grade v2 was written after reading the 36 v1 web verdicts (fitted); rho 0.996 with a_T."),
    "a_m_procedure": (D, "D", "Component of a_T; use to say which field the quote came from."),
    "a_m_capability": (D, "D", "Component of a_T; use to say which field the quote came from."),
    "a_m_equipment": (D, "D", "Component of a_T; use to say which field the quote came from."),
    "a_m_description": (D, "D", "Component of a_T; use to say which field the quote came from."),
    "a_m_specialties": (X, "-", "A specialty tag is a_T = 1; no added signal."),
    "a_echo_dupes": (D, "D", "Explains echo collapse on the card ('3 copies counted once'); not a score term."),
    "a_own_anchored": (X, "-", "0.8% of pairs, no association on any label source."),
    "a_quantity": (X, "-", "Inside a_T level 5; 0.5% of pairs."),
    "a_quarantine_share": (K, "L", "Best text predictor of a wrong location (DEV location AUROC 0.21, so 0.79 for 'wrong'); weak for service."),
    "a_pair_quarantine_share": (X, "-", "rho 1.0 with a_contamination."),
    "k_text_nabh": (K, "S", "Positive on DEV and lists; pair it with d_nabh_listed so the card can say 'claim not found in NABH list'."),
    "k_text_pmjay": (D, "D", "Direction flips under IPW on DEV (0.60 raw, 0.42 IPW); show as a fact, do not score."),
    "k_text_cghs_echs": (D, "D", "2.8% of pairs, 3 DEV pairs; show as a fact."),
    "k_text_blood_bank": (X, "-", "Covered by a_prereq (blood bank is a prerequisite cue) and d_erk_blood_centre_on_site."),
    "k_text_ot_count": (X, "-", "2.6% of pairs; covered by a_prereq."),
    "k_text_24x7_any": (K, "S", "Positive on all three label sets (lists 0.69); marks an inpatient, round-the-clock facility."),
    "k_text_service_equipment_count": (X, "-", "0.4% of pairs; rho 0.87 with a_quantity, inside a_T level 5."),
    "k_text_service_24x7": (D, "D", "Weak (lists 0.54); useful as the card's hours line."),
    "b_coord_pin_km": (K, "L", "Continuous form of the 50 km flag; DEV location AUROC 0.17 (0.83 for 'wrong'). No service signal, as expected."),
    "b_coords_far_50km": (X, "-", "Binarised b_coord_pin_km; same cluster as b_loc_conf."),
    "b_loc_conf": (K, "L", "DEV location 0.98; 0.97 on the 37 v2 facilities alone, so the v1 verdicts do not explain it. The cleaning code was last edited after the v2 labels were written, so treat it as tuned and disclose."),
    "b_disputed": (X, "-", "rho 0.89 with b_city_points_elsewhere; both feed b_loc_conf."),
    "b_city_points_elsewhere": (K, "L", "The city witness MODEL_SPEC found strongest for location; cluster representative over b_disputed."),
    "b_copied_geocode": (K, "L", "Rare rule (1.6%); a copied pin cannot locate the facility."),
    "b_votes_against": (K, "L", "Strongest location feature on DEV (AUROC 0.02 for 'right', 0.98 for 'wrong'; 12 wrong of 52)."),
    "b_coord_shared_3plus": (X, "-", "0.1% of pairs; covered by b_copied_geocode."),
    "b_n_source_ids": (X, "-", "rho 0.84 with c_n_urls; keep one web-footprint term."),
    "b_directory_phone": (K, "E", "No service signal; it changes the call script and the existence head (directory numbers)."),
    "b_no_phone": (K, "E", "Existence and call-script input; no service signal."),
    "b_dup_group": (D, "D", "Used for backups from distinct groups and for leakage-safe splits, not as a score term."),
    "b_email_placeholder": (D, "D", "Contact display only; no signal."),
    "b_breadth_exceeds_size": (X, "-", "No association on any label source (0.49 to 0.54)."),
    "b_scale_implausible": (X, "-", "1.2% of pairs, no association."),
    "b_claims_6plus_services": (X, "-", "0.8% of pairs, no association."),
    "b_website_other_org": (K, "E", "Rare guard: the cited website may be another organisation's, so web features must not count."),
    "b_merge_bucket": (X, "-", "rho 0.84 with c_n_urls; MODEL_SPEC showed its positive weight is a web-visibility effect."),
    "b_scale_contradiction": (K, "R", "0.2% of pairs; a 5-bed clinic claiming cardiac surgery is a rule, not a weight."),
    "c_n_urls": (K, "S", "Web footprint term (lists 0.72, DEV 0.66). Label it truthfully: records built from many pages are confirmed more often."),
    "c_share_official": (X, "-", "No association on DEV (0.46) or lists (0.54)."),
    "c_share_aggregator": (X, "-", "Weak (lists 0.56); inside the web-footprint signal."),
    "c_share_social": (K, "S", "Measured negative on every label set (lists 0.34, NABH 0.42, DEV 0.43): social-only records are small clinics."),
    "c_share_business_dir": (X, "-", "No association."),
    "c_share_government": (X, "-", "Lists 0.59 is mostly selection: lists are public programmes. No DEV signal."),
    "c_share_maps": (X, "-", "No association."),
    "c_share_about_pages": (X, "-", "Negative (lists 0.41) only because big records have more list pages; duplicates c_n_urls."),
    "c_mean_domain_reliability": (X, "-", "Fitted with gold DEV and points the wrong way (lists 0.35, DEV 0.41): social pages score highest."),
    "c_source_support": (X, "-", "Same as c_mean_domain_reliability (rho 0.91), fitted with gold DEV."),
    "c_location_score_v1": (X, "-", "Before the review fix this column was the gold verdict itself (DEV and TEST). Now score_model: built on b_loc_conf rules with evidence rates updated on gold DEV; redundant with b_loc_conf."),
    "c_pagecheck_supported": (X, "-", "0.6% coverage (443 pairs)."),
    "d_nabh_listed": (K, "E", "Existence and quality witness from a list we did not build; DEV 0.59."),
    "d_nabh_full_accreditation": (KX, "X", "Quality tier for the card (full accreditation vs entry-level certificate)."),
    "d_nabh_service_code": (KX, "X", "The only per-service list fact for dialysis, C-section, trauma; self-declared. Never a label when used as a feature."),
    "d_nabh_code_known": (X, "-", "Defines the PU population (missing vs silent), not evidence."),
    "d_nmc_college": (X, "-", "rho 0.76 with d_nmc_course_any; use the course-level fact."),
    "d_nmc_course_strong": (KX, "X", "Regulator-approved department (DM Nephrology, MCh CTVS...). 160 pairs; card cites NMC."),
    "d_nmc_course_any": (X, "-", "Adds supporting courses (MD Paediatrics for NICU) that do not show the service runs."),
    "d_erk_blood_centre_on_site": (KX, "X", "Government-listed blood centre on site: a prerequisite for C-section, trauma, burns, cardiac surgery."),
    "d_erk_nearest_km": (C, "C", "Neighbourhood blood supply; context for the planner, not evidence about the facility."),
    "d_erk_within_10km": (X, "-", "True for 95.7% of pairs; no information."),
    "d_laqshya_ot_valid": (KX, "X", "Current maternity OT certificate (C-section); combine with d_laqshya_ot_ever as one 3-level term."),
    "d_laqshya_ot_ever": (KX, "X", "Expired certificates still show the OT existed; show as expired."),
    "d_laqshya_labour_room": (X, "-", "A labour room is not a C-section theatre; rho 0.95 with d_laqshya_ot_ever."),
    "d_mohfw_trauma_centre": (KX, "X", "20 matched records, 19 of 20 correct on hand check; the only list for trauma."),
    "e_has_website": (X, "-", "No association on DEV (0.51); e_site_alive carries the useful part."),
    "e_site_alive": (K, "E", "Existence witness (DEV location 0.74); gate for website features."),
    "e_identity_conf": (K, "E", "Gate: website facts count only when the site is this facility. Already applied inside e_web_*."),
    "e_web_service": (K, "S", "Independent of the dataset text and positive on all three label sets (DEV 0.65, NABH 0.62, lists 0.63)."),
    "e_web_service_strong": (X, "-", "Same cluster as e_web_service (rho 0.83)."),
    "e_web_service_page": (X, "-", "Same cluster as e_web_service (rho 0.75)."),
    "e_web_negated": (K, "R", "Rare guard; a site saying it does not offer the service must override."),
    "e_web_hours_found": (D, "D", "Card hours line; weak service signal (lists 0.55)."),
    "e_web_24x7_emergency": (K, "S", "Positive on DEV (0.67) and lists (0.66); use for trauma and C-section."),
    "e_web_nabh_claim": (X, "-", "Covered by k_text_nabh and d_nabh_listed."),
    "f_osm_match": (K, "E", "Existence witness (DEV location 0.78); lists 0.65 is partly selection (big hospitals are mapped)."),
    "f_osm_conflict": (K, "L", "Same-name facility elsewhere on OSM; location warning."),
    "f_wikidata_match": (X, "-", "2.1% of pairs, weak."),
    "f_osm_emergency_yes": (D, "D", "1.6% of pairs; show as 'OpenStreetMap tags an emergency department'."),
    "f_osm_opening_hours": (D, "D", "Card hours line only."),
    "f_osm_24x7": (D, "D", "Card hours line only."),
    "f_osm_speciality_service": (X, "-", "0.3% of pairs."),
    "g_type_hospital": (K, "S", "DEV interval excludes 0.5 (0.58 [0.53, 0.64]); lists 0.72. Cluster representative over g_type_clinic."),
    "g_type_clinic": (X, "-", "rho 0.89 with g_type_hospital."),
    "g_type_dentist": (K, "R", "Fold into a_scope_conflict (MODEL_SPEC v2 fix 2: derive from name)."),
    "g_public": (X, "-", "No association on DEV or lists; selection driver for public lists."),
    "g_public_level": (K, "S", "IPHS level prior for public facilities (2.9% of pairs); with g_iphs_essential it answers 'what should exist'."),
    "g_medical_college": (X, "-", "rho 0.98 with g_public_level among public records."),
    "g_iphs_essential": (K, "S", "Public-standard prior; the outside option ('the standard says this level should offer it')."),
    "g_log_beds": (K, "S", "Lists 0.70, NABH 0.69; DEV 0.44 on 38 pairs (too small to trust either way). Missing beds as its own bin."),
    "g_log_doctors": (X, "-", "Same size signal as beds with more implausible values (doctors_1_large_facility)."),
    "g_n_specialties": (K, "S", "Strongest single feature on lists (0.79) and positive on DEV (0.67 [0.52, 0.80])."),
    "h_nfhs_institutional_birth_pct": (C, "C", "District context for C-section and NICU cards; not about the facility."),
    "h_nfhs_csection_pct": (C, "C", "District context for C-section cards."),
    "h_nfhs_insurance_pct": (C, "C", "District context."),
    "h_nfhs_women_high_sugar_pct": (C, "C", "District context for dialysis demand."),
    "h_tt_motor_min": (C, "C", "Remoteness of the point; candidate location flag f_remote_cell per MODEL_SPEC, test on DEV first."),
    "h_log_pop_25km": (C, "C", "Planner context (people served)."),
    "h_vf_records_25km": (C, "C", "Planner context (alternatives nearby)."),
}


EXAMPLE = {"{svc}": "dialysis", "{n}": "3", "{pct}": "40%", "{status}": "Accredited, H-2024-1234",
           "{code}": "dialysis (DIA)", "{course}": "D.M. Nephrology", "{date}": "16 Mar 2027",
           "{level}": "district hospital", "{conf}": "high", "{grade}": "strong"}


def example(phrase: str) -> str:
    """The card phrase filled with illustrative values (dialysis at a district hospital); not real data."""
    for k, v in EXAMPLE.items():
        phrase = phrase.replace(k, v)
    return phrase


def main():
    u = pd.read_parquet(HERE / "out/univariate.parquet")
    assert set(DECISIONS) == set(M.META) == set(u.feature), set(M.META) ^ set(DECISIONS)
    rows = []
    for r in u.itertuples():
        f = r.feature
        d, src, dirn, phrase, tags = M.META[f]
        rec, head, why = DECISIONS[f]
        rows.append(dict(feature=f, family=M.family_of(f), definition=d, source_file=src, expected_direction=dirn,
                         card_phrase=phrase, card_phrase_example=example(phrase), source_tags=tags, recommendation=rec, head=head, reason=why))
    cat = pd.DataFrame(rows).merge(u, on="feature")
    # observed direction on the two larger label sets, for a quick agreement check
    def obs(a):
        return "" if pd.isna(a) else "+" if a > 0.5 else "-"
    cat["observed_direction_dev"] = cat.dev_auc.map(obs)
    cat["observed_direction_lists"] = cat.lists_auc.map(obs)
    num = cat.select_dtypes("float").columns
    cat[num] = cat[num].round(4)
    cat.to_csv(HERE / "features_catalogue.csv", index=False)
    rec = {h: sorted(cat[(cat["head"] == h) & cat.recommendation.str.startswith("keep")].feature)
           for h in ["S", "X", "L", "E", "R"]}
    rec["display_only"] = sorted(cat[cat.recommendation == D].feature)
    rec["context_only"] = sorted(cat[cat.recommendation == C].feature)
    rec["dropped"] = sorted(cat[cat.recommendation == X].feature)
    rec["counts"] = {k: len(v) for k, v in rec.items() if isinstance(v, list)}
    rec["notes"] = ("S = service head terms, X = official-list evidence (family X), L = location head, E = existence head, "
                    "R = hard rules or guards. See FEATURES.md for reasons and the leakage rules.")
    (HERE / "recommended_feature_set.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec["counts"]), cat.recommendation.value_counts().to_dict())


if __name__ == "__main__":
    main()

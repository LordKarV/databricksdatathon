"""Genie space "Referral Saathi planner": definition, SQL check, create or update.

    python databricks/genie/space.py check     # run every example SQL on the warehouse, print row counts
    python databricks/genie/space.py build     # write genie_space.json (the serialized_space payload)
    python databricks/genie/space.py deploy    # check, build, then create the space (or update it if
                                               # space_id.txt exists)

Uses the Databricks CLI with DATABRICKS_CONFIG_PROFILE (default vf). Reads only; the only write is the
Genie space itself.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID", "6a2f5637720a2c17")
S = "workspace.referral_saathi"
TITLE = "Referral Saathi planner"
DESCRIPTION = (
    "For district health planners in India: where facilities show public evidence of a service "
    "(trauma or 24x7 emergency, dialysis, emergency C-section, ICU, NICU, MRI and more), how strong that "
    "evidence is (dataset claim, text grade, facility website, OpenStreetMap, official lists such as NABH, "
    "LaQshya, NMC and the MoHFW trauma list), and which districts have none. Built on the Virtue Foundation "
    "records (9,959 facilities, 88% private). Every answer is about evidence, not about care that exists.\n\n"
    "Capabilities:\n"
    "- Facilities near a district for a service, model v2 band Likely first, then straight-line km, with the "
    "cited claim ids and sentences\n"
    "- Districts with no corroborated dialysis or C-section evidence, with people and need\n"
    "- Share of claims confirmed by a second source (website, OpenStreetMap, official list), by state or district\n"
    "- Official list facts (NABH, LaQshya, NMC, MoHFW trauma, e-RaktKosh) with citation links\n"
    "- Model v2 band counts by service, state and owner\n"
    "Not here: travel time, phone calls and the emergency order. The Referral Saathi app adds those."
)
PATNA = (25.5941, 85.1376)  # Patna city centre, used by the "near Patna" example


def hid(text):
    """Stable 32-hex id, so a rebuild keeps the same ids and the same sort order."""
    return hashlib.md5(text.encode()).hexdigest()


def km_from(lat, lon, alias="g"):
    """Haversine km from a fixed point to the facility's cleaned point."""
    return (f"2 * 6371 * ASIN(SQRT(POWER(SIN(RADIANS({alias}.loc_lat - {lat}) / 2), 2) + "
            f"COS(RADIANS({lat})) * COS(RADIANS({alias}.loc_lat)) * "
            f"POWER(SIN(RADIANS({alias}.loc_lon - {lon}) / 2), 2)))")


def col(name, desc=None, syn=None, match=False, exclude=False):
    c = {"column_name": name}
    if desc:
        c["description"] = [desc]
    if syn:
        c["synonyms"] = syn
    if match:
        c["enable_format_assistance"] = True
        c["enable_entity_matching"] = True
    if exclude:
        c["exclude"] = True
    return c


def flag_cols():
    out = []
    for svc, label in (("trauma", "trauma or 24x7 emergency"), ("dialysis", "dialysis"),
                       ("csection", "emergency C-section")):
        out += [
            col(f"{svc}_claimed", f"A dataset sentence names {label} for this facility, with non-offer, negated, "
                "other-facility, staff and directory lines removed. A claim, not a fact."),
            col(f"{svc}_independent", f"At least one second check (website, OSM, official list) mentions {label}."),
            col(f"{svc}_corroborated", f"Claimed AND at least one second check agrees: the evidence level planners "
                "call confirmed.", ["confirmed", "verified by a second source", "corroborated"]),
            col(f"{svc}_web", f"The facility's own website states {label} (quote-verified). Not fully independent of "
                "the dataset."),
            col(f"{svc}_osm", f"OpenStreetMap feature matched to this facility supports {label}."),
            col(f"{svc}_tcf", "Matched to the MoHFW list of 196 trauma care facilities (trauma only)."),
            col(f"{svc}_laqshya", "Holds an NHSRC LaQshya maternity OT certificate (C-section only)."),
        ]
    return out


TABLES = {
    f"{S}.geo_facility": [
        col("unique_id", "Facility record id; joins every facility-level table."),
        col("name", "Facility name as the record writes it.", ["facility", "hospital"]),
        col("stname", "LGD state of the facility's cleaned point, UPPER CASE (BIHAR).", ["state"], match=True),
        col("dtname", "LGD district of the facility's cleaned point, title case (Patna).", ["district"], match=True),
        col("nfhs_state", "NFHS-5 state key, title case (Bihar); joins geo_dialysis_district."),
        col("nfhs_district", "NFHS-5 district key; joins geo_dialysis_district."),
        col("loc_lat", "Cleaned latitude used for distance."),
        col("loc_lon", "Cleaned longitude used for distance."),
        col("loc_conf", "Location confidence: high, medium, low or disputed.", match=True),
        col("facilityTypeId", "hospital, clinic, dentist, doctor or farmacy; may be the string 'null'.", match=True),
        col("degurba", "Settlement class of the point: 3 urban centre, 2 town or semi-dense, 1 rural."),
        col("is_canonical", "False for 77 duplicate records; filter is_canonical = true to count facilities once."),
        *flag_cols(),
        *[col(c, exclude=True) for c in ("row", "col", "on_grid", "snapped", "grid_id", "state_final", "district",
                                         "nfhs_state_ut", "nfhs_district_name", "operatorTypeId")],
    ],
    f"{S}.facility_service_scores_v2": [
        col("unique_id", "Facility record id; 9,947 eligible records (exclude_review records are not scored)."),
        col("service_id", "Taxonomy service id, 36 services (dialysis, icu, emergency_csection, trauma_care, "
            "emergency_24x7 ...); joins services.service_id.", ["service"], match=True),
        col("band", "Model v2 band: LIKELY, CALL_FIRST, NO_SERVICE_TEXT (no sentence about the service as its own "
            "unit; show the band, never p) or UNLIKELY.", ["badge", "likely", "model band"], match=True),
        col("p", "P_S: chance that a web check which finds a decisive answer confirms the service. Not the chance a "
            "phone call finds it. Only shown when band is not NO_SERVICE_TEXT.", ["score", "P_S"]),
        col("lo", "Score bin track record, low: observed confirmed rate of DEV pairs in the same 0.2 score bin. "
            "Not an interval around p."),
        col("hi", "Score bin track record, high: observed confirmed rate of DEV pairs in the same 0.2 score bin. "
            "Not an interval around p."),
        col("p_location", "P(cleaned location is right)."),
        col("p_exists", "P(facility exists)."),
        col("operator", "public, private or unknown.", ["owner", "ownership"], match=True),
        col("overlays", "Flags beside the band: BORDERLINE, PLACE_UNCLEAR, ON_A_PUBLIC_LIST:list:date."),
        col("contributions", "JSON array of score parts; each has evidence_ids, the claim ids behind the band. Parse "
            "with FROM_JSON(contributions, 'array<struct<evidence_ids:array<string>>>') and join claims.claim_id "
            "for the sentence.", ["claim ids", "evidence", "citations"]),
        *[col(c, exclude=True) for c in ("base", "as_of", "model_version", "is_24x7", "hours_text")],
    ],
    f"{S}.facility_attributes_v2": [
        col("unique_id", "Facility record id (9,959 records)."),
        col("operator", "Owner: public (469), private (8,805) or unknown (685).", ["owner", "ownership"], match=True),
        col("facility_level", "Public level from the name: mc, dh, sdh, phc, chc or unknown.", match=True),
        col("facility_type", "Facility type (hospital, clinic, dentist ...).", match=True),
        col("beds", "Beds from the cleaned capacity field."),
        col("empanel_pmjay", "PM-JAY empanelment from text or web."),
    ],
    f"{S}.grades": [
        col("unique_id", "Facility record id."),
        col("service", "Service key: trauma (trauma or 24x7 emergency), dialysis, csection, icu, nicu, mri, "
            "cardiac_surgery, burns.", match=True),
        col("grade", "Text evidence grade from the dataset alone: strong, moderate, weak, tag_only (a specialty tag "
            "only), counter_evidence, attributed_elsewhere (the text is about another facility).",
            ["evidence grade", "evidence strength"], match=True),
        col("rule", "Grader rule that fired (G_strong, G_mod, G_scope ...)."),
        col("n_own", "Sentences attributed to this facility that name the service."),
        col("cite_evidence", "JSON array of {claim_id, field, text}: the claim sentences behind the grade. Cite these "
            "claim_ids.", ["citations", "claim ids", "evidence"]),
        col("cite_counter", "JSON array of claim sentences that argue against the service."),
        col("risks", "Comma list of risk flags (location, name collision, service elsewhere ...)."),
    ],
    f"{S}.claims": [
        col("claim_id", "Claim sentence id uid8:field4:idx; the id to cite."),
        col("unique_id", "Facility record id."),
        col("text", "The claim sentence as written in the record."),
        col("attribution", "own_anchored, unanchored, ambiguous or other_facility.", match=True),
        col("nonoffer", "True when the sentence does not offer the service (referral, future, camp, negation ...)."),
        *[col(c, exclude=True) for c in ("foreign_names", "sibling_names", "self_names", "places_other_state",
                                         "places_other_district", "prereqs", "qty_value", "qty_unit", "idx")],
    ],
    f"{S}.facility_trust": [
        col("unique_id", "Facility record id."),
        col("existence_score", "P(facility exists), 0 to 1."),
        col("location_score", "P(cleaned location is right), 0 to 1."),
        col("overall_score", "existence x location x attribution, 0 to 1. A record-quality score, not a service score.",
            ["trust score"]),
        col("trust_level_cleaning", "no_concerns, minor, caution or exclude_review.", ["trust level"], match=True),
        col("drivers", "Plain-English reasons for the score."),
        col("top_sources", exclude=True),
    ],
    f"{S}.facility_list_facts": [
        col("unique_id", "Facility record id."),
        col("list_slug", "nabh, laqshya, nmc, mohfw_trauma, eraktkosh or pmndp_goa.",
            ["official list", "accreditation list"], match=True),
        col("service", "Service the list fact is about (trauma_emergency, emergency_csection, dialysis, icu ...). "
            "NULL means a facility-level fact (all NABH rows): it does not confirm any one service.", match=True),
        col("status", "What the list says: NABH Accredited, Certified, Renewed or Empaneled; LaQshya "
            "'certified, valid' or 'certified, expired'; MoHFW trauma level and functional status.", match=True),
        col("valid_to", "Certificate end date (LaQshya)."),
        col("citation_url", "Where the fact can be checked. '#' or 'Not Found' means no usable link."),
        col("licence_note", exclude=True),
    ],
    f"{S}.services": [
        col("service_id", "Taxonomy service id (dialysis, emergency_24x7, trauma_care, emergency_csection ...).",
            match=True),
        col("name_en", "Plain name of the service.", match=True),
        col("aliases", "JSON list of the older ids used in grades and geo_facility (trauma, csection, burns)."),
    ],
    f"{S}.specialties": [
        col("unique_id", "Facility record id."),
        col("spec", "Specialty tag from the record, lower case without spaces (nephrology, cardiology ...). "
            "A tag is the weakest evidence: a claim with no sentence.", ["specialty", "department"]),
    ],
    f"{S}.web_service_summary": [
        col("unique_id", "Facility record id."),
        col("service_id", "Taxonomy service id (dialysis, icu, emergency_24x7, trauma_care ...).", match=True),
        col("web_positive", "The facility's own website states the service (attributable page)."),
        col("web_positive_strong", "Website statement is strong (explicit, on a services page or sentence)."),
        col("best_quote", "Exact quote from the website."),
        col("best_url", "Page the quote was read from; cite it."),
    ],
    f"{S}.geo_dialysis_district": [
        col("nfhs_state", "NFHS-5 state, title case (Bihar).", ["state"], match=True),
        col("nfhs_district", "NFHS-5 district (704 districts).", ["district"], match=True),
        col("pop", "People (WorldPop 2025)."),
        col("ncd", "Dialysis need proxy in percent: mean of four NFHS-5 high blood pressure and blood sugar rates."),
        col("burden_q", "Need quartile of ncd."),
        col("n_claim", "Facilities in the district whose records claim dialysis."),
        col("n_corr", "Facilities with confirmed dialysis (claimed plus a second source).", ["confirmed dialysis"]),
        col("share60", "Share of people (0 to 1) within 60 minutes' drive of confirmed dialysis."),
        col("median_min", "Population-weighted median drive minutes to confirmed dialysis."),
        col("hot", "Top need quarter AND under half the people within 60 minutes of confirmed dialysis."),
        *[col(c, exclude=True) for c in ("cx", "cy")],
    ],
    f"{S}.geo_district": [
        col("stname", "LGD state, UPPER CASE.", ["state"], match=True),
        col("dtname", "LGD district (784 districts, including those with no records).", ["district"], match=True),
        col("pop", "People (WorldPop 2025)."),
        col("records", "Facility records whose point falls in the district."),
        col("per_m", "Records per million people.", ["records per million", "density"]),
        col("cx", "Longitude of the district centre. 'Near <city>' means within 50 km of its district's centre."),
        col("cy", "Latitude of the district centre. 'Near <city>' means within 50 km of its district's centre."),
    ],
}

TEXT_INSTRUCTIONS = """## PURPOSE
- Planners ask where facilities show public evidence of a service and how strong it is.
- Every row is a claim from the Virtue Foundation records (88% private), not a verified fact.
- Your km are straight line. Travel time and call-ahead come from the Referral Saathi app, which in an emergency calls the nearest plausible place first; say so for a patient.

## DISAMBIGUATION
- "Confirmed", "corroborated" or "second source" means the *_corroborated flags in geo_facility or n_corr in geo_dialysis_district. "Claims" means *_claimed or grades rows.
- "Trauma" in geo_facility and grades means trauma or 24x7 emergency.
- "Near X" with no radius: 50 km straight line from the centre of district X (geo_district cx, cy); say so.
- geo_facility and geo_district states are UPPER CASE; NFHS tables title case.

## DATA QUALITY NOTES
- NABH rows are facility-level (service null): they confirm the facility, not a service.
- citation_url '#' or 'Not Found' means no usable link.

## MODEL V2 SCORES
- "Likely", "can handle", band, score or P_S mean facility_service_scores_v2; state and district from geo_facility. Order by band (LIKELY, CALL_FIRST, NO_SERVICE_TEXT, UNLIKELY), then p or km. Never show p for NO_SERVICE_TEXT. lo/hi are a score bin's track record, not an interval.
- Owner is facility_attributes_v2.operator. The score cannot rank public facilities: say so.

## CONSTRAINTS
- Never rank facilities on claims alone. Order by evidence level (model band, or official list or confirmed, then grade), then distance, and show the level.
- Never say a place has "no care" or "no facility". Say "no public evidence in this dataset" and give n.

## Instructions you must follow when providing summaries
- Always state n (facilities, claims or districts) and the evidence level behind each number.
- Cite claim_ids for every facility named (grades.cite_evidence or v2 contributions), and citation_url for list facts.
- Percentages to one decimal, with numerator and denominator."""

GEO = f"{S}.geo_facility"
EXAMPLES = [
    ("Which districts in Bihar have no corroborated dialysis?",
     f"""SELECT d.nfhs_district, ROUND(d.pop / 1e6, 2) AS pop_millions, d.n_claim AS facilities_claiming_dialysis,
  d.n_corr AS facilities_confirmed_dialysis, ROUND(100 * d.share60, 1) AS pct_people_within_60_min_confirmed, d.hot
FROM {S}.geo_dialysis_district d
WHERE d.nfhs_state = 'Bihar' AND d.n_corr = 0
ORDER BY d.pop DESC""",
     "District with no corroborated service: use geo_dialysis_district for dialysis; report n districts, people, "
     "and that zero means no public evidence, not no care."),
    ("Which facilities with a NABH listing and a nephrology service are near Patna?",
     f"""WITH nabh AS (
  SELECT l.unique_id, l.status AS nabh_status, l.citation_url AS nabh_citation
  FROM {S}.facility_list_facts l WHERE l.list_slug = 'nabh'),
neph AS (
  SELECT s.unique_id, CONCAT_WS(', ', COLLECT_SET(s.spec)) AS nephrology_tags
  FROM {S}.specialties s WHERE s.spec ILIKE '%nephro%' GROUP BY s.unique_id)
SELECT g.unique_id, g.name, g.dtname, ROUND({km_from(*PATNA)}, 1) AS km_from_patna,
  nabh.nabh_status, nabh.nabh_citation, neph.nephrology_tags,
  gr.grade AS dialysis_text_grade, gr.cite_evidence AS dialysis_cited_claims,
  g.dialysis_corroborated, ROUND(t.overall_score, 2) AS record_trust
FROM {GEO} g
JOIN nabh ON nabh.unique_id = g.unique_id
JOIN neph ON neph.unique_id = g.unique_id
LEFT JOIN {S}.grades gr ON gr.unique_id = g.unique_id AND gr.service = 'dialysis'
LEFT JOIN {S}.facility_trust t ON t.unique_id = g.unique_id
WHERE {km_from(*PATNA)} <= 50
ORDER BY g.dialysis_corroborated DESC,
  CASE gr.grade WHEN 'strong' THEN 1 WHEN 'moderate' THEN 2 WHEN 'weak' THEN 3 ELSE 4 END,
  km_from_patna""",
     "Facility list near a place: NABH is facility-level, the service comes from specialties, grades and "
     "geo_facility flags. Order by evidence level, then distance."),
    ("What share of trauma claims is confirmed by a second source, by state?",
     f"""SELECT g.stname, COUNT(*) AS n_trauma_claims,
  SUM(CASE WHEN g.trauma_corroborated THEN 1 ELSE 0 END) AS n_confirmed,
  ROUND(100 * SUM(CASE WHEN g.trauma_corroborated THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_confirmed
FROM {GEO} g
WHERE g.trauma_claimed
GROUP BY g.stname
ORDER BY n_trauma_claims DESC""",
     "Confirmation share: denominator is claimed facilities, numerator corroborated. Same shape for dialysis_ and "
     "csection_ flags."),
    ("Show the claim sentences behind dialysis claims in Patna district",
     f"""WITH cited AS (
  SELECT gr.unique_id, gr.grade,
    EXPLODE(FROM_JSON(gr.cite_evidence, 'array<struct<claim_id:string,field:string,text:string>>')) AS e
  FROM {S}.grades gr WHERE gr.service = 'dialysis')
SELECT g.name, cited.grade, cited.e.claim_id AS claim_id, cited.e.field AS field, cited.e.text AS claim_text,
  c.attribution
FROM cited
JOIN {GEO} g ON g.unique_id = cited.unique_id
LEFT JOIN {S}.claims c ON c.claim_id = cited.e.claim_id
WHERE g.dtname = 'Patna'
ORDER BY CASE cited.grade WHEN 'strong' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END, g.name""",
     "Citing claim_ids: explode grades.cite_evidence; join claims for attribution."),
    ("Which districts in Bihar have the fewest facility records per million people?",
     f"""SELECT d.dtname, ROUND(d.pop / 1e6, 2) AS pop_millions, d.records, ROUND(d.per_m, 2) AS records_per_million
FROM {S}.geo_district d
WHERE d.stname = 'BIHAR'
ORDER BY d.per_m ASC, d.pop DESC
LIMIT 10""",
     "Coverage of the dataset by district; zero records means the dataset is thin there, not that care is absent."),
    ("How many LaQshya certificates are still valid, by state?",
     f"""SELECT g.stname,
  COUNT(DISTINCT CASE WHEN l.status = 'certified, valid' THEN l.unique_id END) AS facilities_valid,
  COUNT(DISTINCT CASE WHEN l.status = 'certified, expired' THEN l.unique_id END) AS facilities_with_expired,
  COUNT(DISTINCT l.unique_id) AS facilities_listed
FROM {S}.facility_list_facts l
JOIN {GEO} g ON g.unique_id = l.unique_id
WHERE l.list_slug = 'laqshya'
GROUP BY g.stname
ORDER BY facilities_listed DESC""",
     "Official list counts by state: count distinct facilities, a facility has one row per certified department."),
    ("What is the evidence for emergency C-section at each facility in Patna district?",
     f"""SELECT g.name, gr.grade AS text_grade, g.csection_claimed, g.csection_corroborated, g.csection_web,
  g.csection_laqshya, ROUND(t.overall_score, 2) AS record_trust, gr.cite_evidence
FROM {GEO} g
LEFT JOIN {S}.grades gr ON gr.unique_id = g.unique_id AND gr.service = 'csection'
LEFT JOIN {S}.facility_trust t ON t.unique_id = g.unique_id
WHERE g.dtname = 'Patna' AND (g.csection_claimed OR gr.grade IS NOT NULL)
ORDER BY g.csection_corroborated DESC,
  CASE gr.grade WHEN 'strong' THEN 1 WHEN 'moderate' THEN 2 WHEN 'weak' THEN 3 ELSE 4 END, g.name""",
     "Evidence ladder for one service in one district: grade, claimed, confirmed and which second source."),
    ("Which ICUs in Patna district are confirmed on the facility's own website?",
     f"""SELECT g.name, w.web_positive_strong, w.best_quote, w.best_url, gr.grade AS text_grade, gr.cite_evidence
FROM {S}.web_service_summary w
JOIN {GEO} g ON g.unique_id = w.unique_id
LEFT JOIN {S}.grades gr ON gr.unique_id = w.unique_id AND gr.service = 'icu'
WHERE w.service_id = 'icu' AND w.web_positive AND g.dtname = 'Patna'
ORDER BY w.web_positive_strong DESC, g.name""",
     "Website evidence for services other than trauma, dialysis and C-section: web_service_summary with taxonomy "
     "service_id; cite best_url."),
    ("How many people live in high-need districts far from confirmed dialysis, by state?",
     f"""SELECT d.nfhs_state, COUNT(*) AS hot_districts, ROUND(SUM(d.pop) / 1e6, 1) AS pop_millions,
  SUM(CASE WHEN d.n_corr = 0 THEN 1 ELSE 0 END) AS hot_districts_with_no_confirmed_facility
FROM {S}.geo_dialysis_district d
WHERE d.hot
GROUP BY d.nfhs_state
ORDER BY pop_millions DESC""",
     "Need against access: hot = top need quarter and under half within 60 minutes of confirmed dialysis."),
    ("How are trauma claims graded in Bihar?",
     f"""SELECT gr.grade, COUNT(*) AS n_facilities
FROM {S}.grades gr
JOIN {GEO} g ON g.unique_id = gr.unique_id
WHERE gr.service = 'trauma' AND g.stname = 'BIHAR'
GROUP BY gr.grade
ORDER BY CASE gr.grade WHEN 'strong' THEN 1 WHEN 'moderate' THEN 2 WHEN 'weak' THEN 3 WHEN 'tag_only' THEN 4 ELSE 5 END""",
     "Grade distribution: strong and moderate rest on the facility's own sentences; tag_only is a specialty tag."),
]

EXAMPLES += [
    ("Which facilities in Patna district are likely to offer dialysis?",
     f"""SELECT g.name, s.band, CASE WHEN s.band <> 'NO_SERVICE_TEXT' THEN ROUND(s.p, 2) END AS p_s,
  ROUND(s.lo, 2) AS bin_confirmed_rate_lo, ROUND(s.hi, 2) AS bin_confirmed_rate_hi, s.operator, s.overlays
FROM {S}.facility_service_scores_v2 s
JOIN {GEO} g ON g.unique_id = s.unique_id
WHERE s.service_id = 'dialysis' AND g.dtname = 'Patna' AND s.band IN ('LIKELY', 'CALL_FIRST')
ORDER BY CASE s.band WHEN 'LIKELY' THEN 1 ELSE 2 END, s.p DESC""",
     "Model v2 shortlist for one service and district: LIKELY then CALL_FIRST, by p. State the public-facility "
     "caveat when public rows appear."),
    ("How many facilities in Bihar does the model band Likely for each service, public against private?",
     f"""SELECT s.service_id, a.operator, COUNT(*) AS n_likely
FROM {S}.facility_service_scores_v2 s
JOIN {GEO} g ON g.unique_id = s.unique_id
JOIN {S}.facility_attributes_v2 a ON a.unique_id = s.unique_id
WHERE g.stname = 'BIHAR' AND s.band = 'LIKELY'
GROUP BY s.service_id, a.operator
ORDER BY s.service_id, a.operator""",
     "Band counts by owner: operator from facility_attributes_v2; ranking ability for public facilities is not "
     "demonstrated."),
]



def near_sql(service, district, state, km=50, limit=10):
    """Facilities near a district centre for one v2 service: Likely first, then straight-line km, with the claim
    ids behind the band and one own sentence. Shared by the example and the brief's benchmark questions."""
    return f"""WITH c AS (SELECT cy AS lat, cx AS lon FROM {S}.geo_district WHERE dtname = '{district}' AND stname = '{state}'),
near AS (
  SELECT g.unique_id, g.name, g.dtname, s.band, s.p, s.contributions, {km_from('c.lat', 'c.lon')} AS km
  FROM {S}.facility_service_scores_v2 s
  JOIN {GEO} g ON g.unique_id = s.unique_id
  CROSS JOIN c
  WHERE s.service_id = '{service}' AND s.band IN ('LIKELY', 'CALL_FIRST')),
ev AS (
  SELECT n.unique_id,
    EXPLODE(FLATTEN(TRANSFORM(FROM_JSON(n.contributions, 'array<struct<evidence_ids:array<string>>>'),
                              x -> x.evidence_ids))) AS claim_id
  FROM near n WHERE n.km <= {km})
SELECT n.name, n.dtname AS district, n.band, ROUND(n.p, 2) AS p_s, ROUND(n.km, 1) AS km_straight_line,
  ARRAY_JOIN(ARRAY_SORT(COLLECT_SET(cl.claim_id)), ', ') AS claim_ids, MIN_BY(cl.text, cl.claim_id) AS claim_text
FROM near n
LEFT JOIN ev e ON e.unique_id = n.unique_id
LEFT JOIN {S}.claims cl ON cl.claim_id = e.claim_id AND cl.attribution <> 'other_facility'
WHERE n.km <= {km}
GROUP BY n.unique_id, n.name, n.dtname, n.band, n.p, n.km
ORDER BY CASE n.band WHEN 'LIKELY' THEN 1 ELSE 2 END, n.km
LIMIT {limit}"""


EXAMPLES += [
    ("Which facilities near Patna are likely to have an ICU?", near_sql("icu", "Patna", "BIHAR"),
     "Service near a place: model v2 band (LIKELY, then CALL_FIRST), then straight-line km from the district "
     "centre in geo_district; cite claim ids from contributions with the claim text. Say the app adds travel "
     "time and call-ahead."),
]

# Benchmarks: the 7 test_space.py questions, the 3 from VERIFY.md (verify/verify_genie.py) and the brief's two.
# Ground-truth SQL is ours, run on the warehouse by `check`; none of these questions is an example above.
BENCHMARKS = [
    ("How many districts in Uttar Pradesh have no confirmed dialysis facility, and how many people live in them?",
     f"SELECT COUNT(*) AS districts, ROUND(SUM(pop) / 1e6, 1) AS pop_millions FROM {S}.geo_dialysis_district "
     "WHERE nfhs_state = 'Uttar Pradesh' AND n_corr = 0"),
    ("Among states with at least 100 trauma or emergency claims, which has the lowest share confirmed by a second "
     "source?",
     f"SELECT stname, COUNT(*) AS n_claims, ROUND(100 * AVG(CASE WHEN trauma_corroborated THEN 1 ELSE 0 END), 1) "
     f"AS pct_confirmed FROM {GEO} WHERE trauma_claimed GROUP BY stname HAVING COUNT(*) >= 100 "
     "ORDER BY pct_confirmed LIMIT 1"),
    ("Cite the claim ids behind the dialysis claim of Ford Hospital And Research Center in Patna.",
     f"SELECT e.claim_id FROM (SELECT EXPLODE(FROM_JSON(gr.cite_evidence, "
     "'array<struct<claim_id:string,field:string,text:string>>')) e "
     f"FROM {S}.grades gr JOIN {GEO} g ON g.unique_id = gr.unique_id "
     "WHERE gr.service = 'dialysis' AND g.name = 'Ford Hospital And Research Center' AND g.dtname = 'Patna')"),
    ("How many facilities in Maharashtra hold a LaQshya certificate that is still valid?",
     f"SELECT COUNT(DISTINCT l.unique_id) AS facilities FROM {S}.facility_list_facts l JOIN {GEO} g "
     "ON g.unique_id = l.unique_id WHERE l.list_slug = 'laqshya' AND l.status = 'certified, valid' "
     "AND g.stname = 'MAHARASHTRA'"),
    ("Which Bihar districts have zero facility records?",
     f"SELECT dtname FROM {S}.geo_district WHERE stname = 'BIHAR' AND records = 0 ORDER BY dtname"),
    ("Is there dialysis care in Madhubani district of Bihar?",
     f"SELECT n_claim, n_corr FROM {S}.geo_dialysis_district WHERE nfhs_state = 'Bihar' "
     "AND nfhs_district = 'Madhubani'"),
    ("How many facilities in Bihar does model v2 band Likely for dialysis?",
     f"SELECT COUNT(*) AS facilities FROM {S}.facility_service_scores_v2 s JOIN {GEO} g "
     "ON g.unique_id = s.unique_id WHERE s.service_id = 'dialysis' AND s.band = 'LIKELY' AND g.stname = 'BIHAR'"),
    ("Which three states have the most facilities on the e-RaktKosh blood bank list?",
     f"SELECT g.stname, COUNT(DISTINCT l.unique_id) AS facilities FROM {S}.facility_list_facts l JOIN {GEO} g "
     "ON g.unique_id = l.unique_id WHERE l.list_slug = 'eraktkosh' GROUP BY g.stname ORDER BY facilities DESC LIMIT 3"),
    ("In Kerala, how many facility records claim emergency C-section, and how many of those are confirmed by a "
     "second source?",
     "SELECT SUM(CASE WHEN csection_claimed THEN 1 ELSE 0 END) AS claimed, "
     "SUM(CASE WHEN csection_claimed AND csection_corroborated THEN 1 ELSE 0 END) AS confirmed "
     f"FROM {GEO} WHERE stname = 'KERALA'"),
    ("Which district in Odisha with no confirmed dialysis facility has the largest population?",
     f"SELECT nfhs_district, ROUND(pop / 1e6, 2) AS pop_millions, n_claim, n_corr FROM {S}.geo_dialysis_district "
     "WHERE lower(nfhs_state) = 'odisha' AND n_corr = 0 ORDER BY pop DESC LIMIT 1"),
    ("Where can a patient get dialysis near Jaipur?", near_sql("dialysis", "Jaipur", "RAJASTHAN")),
    ("Which hospital near Lucknow can handle an emergency C-section?",
     near_sql("emergency_csection", "Lucknow", "UTTAR PRADESH")),
]

SAMPLE_QUESTIONS = [
    "Which districts in Bihar have no corroborated dialysis?",
    "Which NABH-listed facilities near Patna have a nephrology service?",
    "What share of trauma claims is confirmed by a second source, by state?",
    "Which Bihar districts have the fewest facility records per million people?",
    "Which facilities in Patna district are likely to offer dialysis?",
    "How many people live in high-need districts far from confirmed dialysis?",
]

JOINS = [  # (left table, right table, left col, right col, relationship)
    ("geo_facility", "grades", "unique_id", "unique_id", "ONE_TO_MANY"),
    ("geo_facility", "facility_trust", "unique_id", "unique_id", "ONE_TO_ONE"),
    ("geo_facility", "facility_list_facts", "unique_id", "unique_id", "ONE_TO_MANY"),
    ("geo_facility", "specialties", "unique_id", "unique_id", "ONE_TO_MANY"),
    ("geo_facility", "web_service_summary", "unique_id", "unique_id", "ONE_TO_MANY"),
    ("geo_facility", "claims", "unique_id", "unique_id", "ONE_TO_MANY"),
    ("geo_facility", "geo_dialysis_district", "nfhs_district", "nfhs_district", "MANY_TO_ONE"),
    ("geo_facility", "facility_service_scores_v2", "unique_id", "unique_id", "ONE_TO_MANY"),
    ("geo_facility", "facility_attributes_v2", "unique_id", "unique_id", "ONE_TO_ONE"),
]


def join_specs():
    out = []
    for lt, rt, lc, rc, rel in JOINS:
        cond = f"`{lt}`.`{lc}` = `{rt}`.`{rc}`"
        if rt == "geo_dialysis_district":
            cond += f" AND `{lt}`.`nfhs_state` = `{rt}`.`nfhs_state`"
        out.append({"id": hid(f"join:{lt}:{rt}"),
                    "left": {"identifier": f"{S}.{lt}", "alias": lt},
                    "right": {"identifier": f"{S}.{rt}", "alias": rt},
                    "sql": [cond, f"--rt=FROM_RELATIONSHIP_TYPE_{rel}--"]})
    return sorted(out, key=lambda j: j["id"])


def serialized_space():
    tables = [{"identifier": t, "column_configs": sorted(cc, key=lambda c: c["column_name"])}
              for t, cc in sorted(TABLES.items())]
    examples = sorted([{"id": hid("ex:" + q), "question": [q], "sql": [sql], "usage_guidance": [g]}
                       for q, sql, g in EXAMPLES], key=lambda e: e["id"])
    samples = sorted([{"id": hid("sq:" + q), "question": [q]} for q in SAMPLE_QUESTIONS], key=lambda e: e["id"])
    bench = sorted([{"id": hid("bm:" + q), "question": [q], "answer": [{"format": "SQL", "content": [sql]}]}
                    for q, sql in BENCHMARKS], key=lambda e: e["id"])
    return {
        "version": 2,
        "config": {"sample_questions": samples},
        "data_sources": {"tables": tables},
        "instructions": {
            "text_instructions": [{"id": hid("text"), "content": [TEXT_INSTRUCTIONS]}],
            "example_question_sqls": examples,
            "join_specs": join_specs(),
        },
        "benchmarks": {"questions": bench},
    }


def cli(*args, payload=None):
    cmd = ["databricks", *args, "-o", "json"]
    if payload is not None:
        cmd += ["--json", json.dumps(payload)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={**os.environ, "DATABRICKS_CONFIG_PROFILE": os.environ.get("DATABRICKS_CONFIG_PROFILE", "vf")})
    if r.returncode:
        sys.exit(f"databricks {args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[:2000]}")
    return json.loads(r.stdout)


def run_sql(sql):
    """Run one statement, return (columns, rows). Raises on failure."""
    r = cli("api", "post", "/api/2.0/sql/statements",
            payload={"warehouse_id": WAREHOUSE_ID, "statement": sql, "wait_timeout": "50s",
                     "disposition": "INLINE", "format": "JSON_ARRAY"})
    state = r["status"]["state"]
    if state != "SUCCEEDED":
        raise RuntimeError(f"{state}: {r['status'].get('error', {}).get('message', 'still running')}")
    cols = [c["name"] for c in r["manifest"]["schema"]["columns"]]
    return cols, r.get("result", {}).get("data_array", [])


def check():
    ok = True
    for q, sql in [(q, sql) for q, sql, _ in EXAMPLES] + BENCHMARKS:
        try:
            cols, rows = run_sql(sql)
            print(f"ok   {len(rows):5d} rows  {q}\n       {cols}\n       first: {rows[:1]}")
            ok &= len(rows) > 0
        except RuntimeError as e:
            ok = False
            print(f"FAIL {q}: {e}")
    print(f"text instructions: {len(TEXT_INSTRUCTIONS)} chars (limit 2,000)")
    return ok and len(TEXT_INSTRUCTIONS) <= 2000


def build():
    path = HERE / "genie_space.json"
    path.write_text(json.dumps(serialized_space(), indent=1))
    print(f"wrote {path}")
    return path


def deploy():
    if not check():
        sys.exit("example SQL check failed; not deploying")
    space = json.dumps(serialized_space())
    build()
    id_file = HERE / "space_id.txt"
    if id_file.exists():
        sid = id_file.read_text().strip()
        r = cli("genie", "update-space", sid, payload={"title": TITLE, "description": DESCRIPTION,
                                                       "warehouse_id": WAREHOUSE_ID, "serialized_space": space})
    else:
        me = cli("current-user", "me")["userName"]
        r = cli("genie", "create-space", payload={"title": TITLE, "description": DESCRIPTION,
                                                  "warehouse_id": WAREHOUSE_ID,
                                                  "parent_path": f"/Workspace/Users/{me}",
                                                  "serialized_space": space})
        id_file.write_text(r["space_id"] + "\n")
    print(f"space_id {r['space_id']}  title {r.get('title')}")


if __name__ == "__main__":
    {"check": check, "build": build, "deploy": deploy}[sys.argv[1] if len(sys.argv) > 1 else "check"]()

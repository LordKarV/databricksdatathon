"""Build, test and deploy the district planner AI/BI dashboard.

Spec: viz/dashboard/DASHBOARD_SPEC.md. Tables: workspace.referral_saathi (loaded by
databricks/load_tables.py). Dataset SQL uses bare table names; the catalog and schema are
passed separately, both to the Statement API when testing and to `lakeview create/update`.

Usage (from the project root, profile vf):
  python databricks/dashboard/build_dashboard.py build    # write planner_dashboard.json
  python databricks/dashboard/build_dashboard.py test     # run every dataset query + spec checks
  python databricks/dashboard/build_dashboard.py deploy   # create or update, then publish
  python databricks/dashboard/build_dashboard.py all      # build, test, deploy (stops if a test fails)

Re-runs update the same dashboard (id kept in dashboard_id.txt), so the link does not change.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "planner_dashboard.json"
TEST_JSON = HERE / "query_tests.json"
ID_FILE = HERE / "dashboard_id.txt"

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "vf")
WAREHOUSE = os.environ.get("WAREHOUSE_ID", "6a2f5637720a2c17")
CATALOG, SCHEMA = "workspace", "referral_saathi"
DISPLAY_NAME = "Referral Saathi: district planner"
POLL_SECONDS = 5  # ponytail: plain sleep between polls, only hit when a query outlives the 50 s wait

# viz/style.py tokens
BLUE, ORANGE, GREEN, AMBER, PINK, DKGREEN = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"
LIKELY, UNVERIFIED, UNLIKELY = "#6da7ec", "#c3c2b7", "#e34948"
PUBLIC_CAVEAT = ("Public facilities: the v2 score has no demonstrated ranking ability for public facilities "
                 "(31 public DEV pairs, AUROC interval spans 0.5 widely), so do not rank public records by P_S.")
SHARED_CAVEAT = ("A record is a listing in one private-leaning dataset (88% private). "
                 "No evidence here is not no care: read every gap as \"no public evidence of care\".")
SERVICES = ["trauma_emergency", "dialysis", "emergency_csection", "nicu", "cardiac_surgery", "mri", "burn_care"]


def wilson(k, n, side):
    sign = "-" if side == "lo" else "+"
    return (f"({k}/{n} + 1.9208/{n} {sign} 1.96*sqrt(({k}/{n})*(1 - {k}/{n})/{n} + 0.9604/({n}*{n})))"
            f" / (1 + 3.8416/{n})")


# ---------------------------------------------------------------- datasets
DATASETS = {}


def ds(name, display, sql):
    DATASETS[name] = {"name": name, "displayName": display, "sql": sql.strip()}


ds("ds_facility", "Records (one row per facility record)", """
WITH direct AS (SELECT DISTINCT unique_id FROM claims WHERE context = 'direct'),
quar AS (SELECT DISTINCT unique_id FROM claims WHERE attribution = 'other_facility'),
anon AS (SELECT DISTINCT c.unique_id FROM claims c JOIN quar q ON c.unique_id = q.unique_id
         WHERE c.attribution = 'unanchored' AND coalesce(c.services, '') <> ''),
trunc AS (SELECT DISTINCT unique_id FROM grades WHERE coalesce(truncated, false)),
base AS (
  SELECT g.stname AS state, upper(g.dtname) AS district, l.unique_id, l.name,
         l.loc_lat, l.loc_lon, l.loc_conf, l.loc_note, round(l.raw_coords_to_pin_km, 1) AS pin_km,
         CASE WHEN l.loc_conf = 'high' THEN 1 ELSE 0 END AS is_high_conf,
         CASE WHEN l.raw_coords_to_pin_km > 50 THEN 1 ELSE 0 END AS pin_far,
         CASE WHEN d.unique_id IS NOT NULL THEN 1 ELSE 0 END AS names_other_facility,
         CASE WHEN array_contains(r.trust_flags, 'official_phone_is_directory') THEN 1 ELSE 0 END AS directory_phone,
         r.trust_level, r.website_class,
         CASE g.degurba WHEN 3 THEN 'Urban centre' WHEN 2 THEN 'Town or semi-dense' WHEN 1 THEN 'Rural' END AS settlement,
         CASE fa.operator WHEN 'public' THEN 'Public' WHEN 'private' THEN 'Private' ELSE 'Not stated' END AS operator,
         CASE WHEN l.loc_src <> 'listing_coordinates' THEN 1 ELSE 0 END AS fixed_corrected_point,
         CASE WHEN q.unique_id IS NOT NULL THEN 1 ELSE 0 END AS fixed_quarantined_text,
         CASE WHEN l.loc_conf IN ('low', 'disputed') THEN 1 ELSE 0 END AS flagged_location,
         CASE WHEN size(r.scale_flags) > 0 THEN 1 ELSE 0 END AS flagged_size,
         CASE WHEN a.unique_id IS NOT NULL OR d.unique_id IS NOT NULL OR t.unique_id IS NOT NULL
              THEN 1 ELSE 0 END AS cannot_fix,
         CASE WHEN r.trust_level = 'no_concerns' THEN 1 ELSE 0 END AS rated_no_concerns,
         CASE WHEN h.dataset_any_hours OR h.web_any_hours OR h.osm_any_hours THEN 1 ELSE 0 END AS any_hours,
         CASE WHEN h.dataset_emerg24 OR h.web_emerg24 OR h.osm_emerg24 THEN 1 ELSE 0 END AS emergency_24x7,
         CASE WHEN h.dataset_schedule OR h.web_schedule OR h.osm_schedule THEN 1 ELSE 0 END AS clock_schedule,
         CASE WHEN w.own_site THEN 1 ELSE 0 END AS own_site
  FROM facility_location l
  JOIN geo_facility g ON g.unique_id = l.unique_id
  JOIN record_trust r ON r.unique_id = l.unique_id
  LEFT JOIN facility_attributes_v2 fa ON fa.unique_id = l.unique_id
  LEFT JOIN facility_hours h ON h.unique_id = l.unique_id
  LEFT JOIN geo_facility_site w ON w.unique_id = l.unique_id
  LEFT JOIN direct d ON d.unique_id = l.unique_id
  LEFT JOIN quar q ON q.unique_id = l.unique_id
  LEFT JOIN anon a ON a.unique_id = l.unique_id
  LEFT JOIN trunc t ON t.unique_id = l.unique_id)
SELECT *,
       CASE WHEN pin_far = 1 OR flagged_location = 1 OR names_other_facility = 1 THEN 1 ELSE 0 END AS call_first,
       concat_ws('; ',
         CASE WHEN pin_far = 1 THEN concat('pin ', pin_km, ' km from postcode') END,
         CASE WHEN flagged_location = 1 THEN concat('location ', loc_conf) END,
         CASE WHEN names_other_facility = 1 THEN 'text names another facility' END) AS call_reason
FROM base
""")

ds("ds_state", "States and UTs over 1 million people (national)", """
SELECT d.stname AS state, d.label, d.pop / 1e6 AS pop_m, d.records,
       d.per_m, d.per_m_lo, d.per_m_hi,
       d.child_u5_who_are_stunted_height_for_age_18_pct / 100 AS stunting,
       a.corr AS share_60_confirmed_trauma, a.corr_lo, a.corr_hi,
       a.`any` AS share_60_any_record, a.`map` AS share_60_any_clinic,
       a.people_outside_corr / 1e6 AS people_outside_m, a.n_corr
FROM geo_state_density d
JOIN geo_state_access a USING (stname)
WHERE d.pop >= 1e6
ORDER BY d.per_m DESC
""")

ds("ds_district", "LGD districts", """
SELECT stname AS state, upper(dtname) AS district, dist_lgd, nfhs_district, pop / 1e6 AS pop_m, records, per_m,
       CASE WHEN records = 0 THEN 'no record' ELSE '' END AS no_record_flag
FROM geo_district
ORDER BY per_m ASC
""")

# NFHS-keyed tables: one row per LGD district via geo_district's NFHS keys (the same keys as
# nfhs_lgd_crosswalk), so the LGD state and district filters act on them. An NFHS district split
# into several LGD districts repeats once per LGD district. dist_lgd 0 rows (Muzaffarabad, Mirpur)
# are left out because they would repeat Jammu.
ds("ds_dialysis_district", "Dialysis need and access by district (NFHS keys mapped to LGD)", """
SELECT g.stname AS state, upper(g.dtname) AS district, d.nfhs_district, d.pop / 1e6 AS pop_m,
       d.ncd / 100 AS need_proxy, d.burden_q, d.n_claim, d.n_corr, d.corr_per_m, d.corr_per_m_lo, d.corr_per_m_hi,
       d.share60, d.median_min, CASE WHEN d.hot THEN 'high need, over 1 h' ELSE '' END AS hot_flag,
       CASE WHEN d.hot THEN 1 ELSE 0 END AS hot
FROM geo_dialysis_district d
JOIN geo_district g ON g.nfhs_state = d.nfhs_state AND g.nfhs_district = d.nfhs_district AND g.dist_lgd > 0
ORDER BY hot DESC, d.share60 ASC
""")

ds("ds_csection_district", "Low caesarean districts (NFHS keys mapped to LGD)", """
SELECT g.stname AS state, upper(g.dtname) AS district, c.nfhs_district, c.wra / 1e6 AS women_15_49_m,
       c.births_delivered_by_csection_5y_pct / 100 AS csection_rate, c.band,
       c.n_claimed, c.n_corroborated, c.n_laqshya
FROM geo_csection_district c
JOIN geo_district g ON g.nfhs_state = c.nfhs_state AND g.nfhs_district = c.nfhs_district AND g.dist_lgd > 0
WHERE c.band IN ('under 5%', '5-10%')
ORDER BY csection_rate ASC
""")

ds("ds_dialysis_burden", "Weekly road travel for dialysis", """
SELECT coalesce(g.stname, upper(b.state)) AS state, upper(coalesce(g.dtname, b.district)) AS district,
       b.population / 1e6 AS pop_m,
       b.median_weekly_km_claimed, b.median_weekly_km_graded, b.median_weekly_km_corroborated,
       b.median_weekly_hours_corroborated
FROM dialysis_burden_district b
LEFT JOIN (SELECT * FROM geo_district WHERE dist_lgd > 0) g ON g.dist_lgd = b.dist_lgd
WHERE b.road_estimate_valid
ORDER BY b.median_weekly_km_corroborated DESC
""")

ds("ds_settlement", "Within an hour of confirmed care, by settlement class (national)", """
SELECT cls AS settlement, code, pop / 1e6 AS pop_m, pop_share, records, records_share,
       care, within60, confirmed_facilities
FROM geo_settlement
LATERAL VIEW stack(3, 'Trauma', trauma_within60, trauma_corr,
                      'Dialysis', dialysis_within60, dialysis_corr,
                      'Emergency C-section', csection_within60, csection_corr) s AS care, within60, confirmed_facilities
ORDER BY code DESC
""")

ds("ds_pmndp", "PMNDP public dialysis centres by state", """
SELECT state_lgd AS state, nhsrc_functional_centres AS pmndp_centres,
       nhsrc_functional_districts AS pmndp_districts, vf_records, vf_dialysis, vf_public_dialysis
FROM pmndp_state
ORDER BY pmndp_centres DESC
""")

ds("ds_funnel", "Evidence ladder (one row per record and service)", """
SELECT g.stname AS state, upper(g.dtname) AS district, -- v1 named trauma trauma_emergency; v2 calls it trauma_care, so one service filter covers both datasets
       CASE p.service WHEN 'trauma_emergency' THEN 'trauma_care' ELSE p.service END AS service,
       CAST(p.mentioned AS INT) AS mentioned,
       CAST(p.mentioned AND p.fields2 AS INT) AS in_2plus_fields,
       CAST(p.mentioned AND p.fields2 AND p.prereq AS INT) AS own_checks,
       CAST(p.mentioned AND (p.web OR p.listed) AS INT) AS outside_check,
       CAST(p.mentioned AND p.fields2 AND p.prereq AND (p.web OR p.listed) AS INT) AS own_and_outside,
       CAST(NOT p.mentioned AND (p.web OR p.listed) AS INT) AS outside_not_mentioned
FROM claims_funnel_pairs p
JOIN geo_facility g USING (unique_id)
""")

# Model v2 (derived/v2, facility_service_scores_v2). Bands keep the model's four values; NO_SERVICE_TEXT rows
# show no P_S (README: show the band, not p). lo/hi are the score bin's DEV track record, not an interval
# around p. display_phones stays out of the published dashboard (#82).
ds("ds_pairs", "Facility and service scores, model v2 (one row per record and service)", """
SELECT g.stname AS state, upper(g.dtname) AS district, s.service_id AS service, s.unique_id, l.name,
       CASE s.band WHEN 'LIKELY' THEN 'Likely' WHEN 'CALL_FIRST' THEN 'Call first'
                   WHEN 'NO_SERVICE_TEXT' THEN 'No service text' WHEN 'UNLIKELY' THEN 'Unlikely' END AS band,
       CASE WHEN s.band <> 'NO_SERVICE_TEXT' THEN s.p END AS p_s,
       s.lo AS bin_lo, s.hi AS bin_hi, s.p_location AS p_l, s.p_exists AS p_e,
       CASE s.operator WHEN 'public' THEN 'Public' WHEN 'private' THEN 'Private' ELSE 'Not stated' END AS operator,
       array_join(s.overlays, ', ') AS flags, l.loc_conf, r.website_class,
       CASE WHEN s.band IN ('LIKELY', 'CALL_FIRST') THEN 1 ELSE 0 END AS shortlisted
FROM facility_service_scores_v2 s
JOIN geo_facility g ON g.unique_id = s.unique_id
JOIN facility_location l ON l.unique_id = s.unique_id
JOIN record_trust r ON r.unique_id = s.unique_id
ORDER BY s.p DESC
""")

# service is renamed list_service so the global service filter does not drop NABH facts (no service).
ds("ds_list_facts", "Official list facts per matched facility, with citation", """
SELECT g.stname AS state, upper(g.dtname) AS district, f.unique_id, l.name AS facility, f.list_name, f.status,
       nullif(f.service, '') AS list_service, f.valid_to, f.as_of, f.citation_url
FROM facility_list_facts f
JOIN geo_facility g ON g.unique_id = f.unique_id
JOIN facility_location l ON l.unique_id = f.unique_id
ORDER BY state, district, facility, f.list_name
""")

# Checks quoted in DASHBOARD_SPEC.md, run against the dataset SQL itself.
CHECKS = [
    ("ds_facility national: records, high conf, names other, directory phones (spec 9959, 7762, 1232, 292)",
     "SELECT COUNT(*), SUM(is_high_conf), SUM(names_other_facility), SUM(directory_phone) FROM ({ds_facility})"),
    ("ds_facility cleaning: cannot_fix, rated_no_concerns, both (spec 2610, 7812, 1589)",
     "SELECT SUM(cannot_fix), SUM(rated_no_concerns), SUM(cannot_fix * rated_no_concerns) FROM ({ds_facility})"),
    ("ds_facility hours: any, 24x7, schedule (spec 6074, 2829, 2808)",
     "SELECT SUM(any_hours), SUM(emergency_24x7), SUM(clock_schedule) FROM ({ds_facility})"),
    ("ds_state Bihar per_m, lo, hi, records, pop_m (spec 1.95, 1.72, 2.20, 260, 133.5)",
     "SELECT round(per_m, 2), round(per_m_lo, 2), round(per_m_hi, 2), records, round(pop_m, 1) FROM ({ds_state}) WHERE state = 'BIHAR'"),
    ("geo_dialysis_district hot districts and people (spec 69, 103.8 M)",
     "SELECT SUM(CAST(hot AS INT)), round(SUM(CASE WHEN hot THEN pop END) / 1e6, 1) FROM geo_dialysis_district"),
    ("geo_csection_district districts in the two low bands (spec 152 = 39 + 113)",
     "SELECT band, COUNT(*) FROM geo_csection_district WHERE band IN ('under 5%', '5-10%') GROUP BY band ORDER BY band"),
    ("ds_funnel national: mentioned, own checks, own and outside (spec 7969, 1798, 837)",
     "SELECT SUM(mentioned), SUM(own_checks), SUM(own_and_outside) FROM ({ds_funnel})"),
    ("ds_pairs v2 bands (derived/v2: Likely 20073, Call first 1671, No service text 242131, Unlikely 94217)",
     "SELECT band, COUNT(*) FROM ({ds_pairs}) GROUP BY band ORDER BY band"),
    ("ds_pairs v2 contract: rows (358092), exclude_review ids (0), NO_SERVICE_TEXT with P_S (0), operators",
     "SELECT COUNT(*), SUM(CASE WHEN unique_id IN (SELECT unique_id FROM record_trust WHERE trust_level = "
     "'exclude_review') THEN 1 ELSE 0 END), SUM(CASE WHEN band = 'No service text' AND p_s IS NOT NULL THEN 1 "
     "ELSE 0 END), COUNT(DISTINCT operator) FROM ({ds_pairs})"),
    ("ds_dialysis_district coverage: NFHS districts reached and LGD rows",
     "SELECT COUNT(DISTINCT state, nfhs_district), COUNT(*) FROM ({ds_dialysis_district})"),
    ("filter values: states in ds_facility, districts in ds_facility",
     "SELECT COUNT(DISTINCT state), COUNT(DISTINCT state, district) FROM ({ds_facility})"),
]


# ---------------------------------------------------------------- widgets
def pos(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def text(name, lines, p):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": lines}}, "position": p}


def frame(title, desc=None):
    f = {"showTitle": True, "title": title}
    if desc:
        f.update(showDescription=True, description=desc)
    return f


def query(dataset, fields, disaggregated, filters=None):
    q = {"datasetName": dataset, "fields": [{"name": n, "expression": e} for n, e in fields],
         "disaggregated": disaggregated}
    if filters:
        q["filters"] = [{"expression": f} for f in filters]
    return [{"name": "main_query", "query": q}]


PCT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}
NUM0 = {"type": "number", "decimalPlaces": {"type": "max", "places": 0}}
NUM1 = {"type": "number", "decimalPlaces": {"type": "max", "places": 1}}
NUM2 = {"type": "number", "decimalPlaces": {"type": "exact", "places": 2}}


def counter(name, dataset, expr, title, desc, p, fmt=None):
    value = {"fieldName": "v", "displayName": title}
    if fmt:
        value["format"] = fmt
    return {"widget": {"name": name, "queries": query(dataset, [("v", expr)], False),
                       "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": value},
                                "frame": frame(title, desc)}}, "position": p}


def table(name, dataset, cols, title, desc, p, filters=None):
    """cols: (field, display, format or None)."""
    columns = []
    for f, d, fmt in cols:
        c = {"fieldName": f, "displayName": d}
        if fmt:
            c["format"] = fmt
        columns.append(c)
    return {"widget": {"name": name, "queries": query(dataset, [(f, f"`{f}`") for f, _, _ in cols], True, filters),
                       "spec": {"version": 2, "widgetType": "table", "encodings": {"columns": columns},
                                "frame": frame(title, desc)}}, "position": p}


def vega(name, dataset, fields, disaggregated, spec, title, desc, p):
    spec = {"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "data": {"name": "databricks_query"},
            "width": "container", "height": "container",
            "config": {"autosize": {"type": "fit", "contains": "padding"}}, **spec}
    return {"widget": {"name": name, "queries": query(dataset, fields, disaggregated),
                       "spec": {"version": 1, "widgetType": "custom-vega-viz",
                                "data": {"queryName": "main_query"},
                                "encodings": {"fields": [{"fieldName": n} for n, _ in fields]},
                                "jsonSpec": {"type": "vega-lite", "spec": json.dumps(spec)},
                                "frame": frame(title, desc)}}, "position": p}


INK = {"expr": "colors.textPrimary.default"}
WILSON_VL = [
    {"calculate": "datum.n > 0 ? datum.k / datum.n : null", "as": "p"},
    {"calculate": "(datum.p + 1.9208/datum.n - 1.96*sqrt(datum.p*(1-datum.p)/datum.n + 0.9604/(datum.n*datum.n)))"
                  " / (1 + 3.8416/datum.n)", "as": "lo"},
    {"calculate": "(datum.p + 1.9208/datum.n + 1.96*sqrt(datum.p*(1-datum.p)/datum.n + 0.9604/(datum.n*datum.n)))"
                  " / (1 + 3.8416/datum.n)", "as": "hi"},
    {"calculate": "format(datum.k, ',') + ' of ' + format(datum.n, ',') + ' (' + format(datum.p, '.1%') + ')'"
                  " + (datum.n < 30 ? ', small sample' : '')", "as": "lbl"},
]


def case_expr(field, mapping):
    """Nested ternary: Vega expressions have no lookup table."""
    out = "''"
    for key, val in reversed(mapping):
        out = f"datum.{field} === '{key}' ? '{val}' : ({out})"
    return out


def rate_bars(name, dataset, items, denom_expr, title, desc, p, x_title="Share of records"):
    """Rates computed from the filtered rows: k per item, one shared n, Wilson 95% interval.

    items: (key, sum expression, label, group). One aggregated row comes back; Vega folds it.
    """
    fields = [(k, e) for k, e, _, _ in items] + [("n", denom_expr)]
    keys = [k for k, _, _, _ in items]
    labels = [lab for _, _, lab, _ in items]
    groups = sorted({g for _, _, _, g in items}, key=[g for *_, g in items].index)
    spec = {
        "transform": [{"fold": keys, "as": ["key", "k"]},
                      {"calculate": case_expr("key", [(k, lab) for k, _, lab, _ in items]), "as": "measure"},
                      {"calculate": case_expr("key", [(k, g) for k, _, _, g in items]), "as": "group"},
                      *WILSON_VL],
        "encoding": {"y": {"field": "measure", "type": "nominal", "sort": labels, "title": None,
                           "axis": {"labelLimit": 260}}},
        "layer": [
            {"mark": {"type": "bar", "opacity": 0.85},
             "encoding": {"x": {"field": "p", "type": "quantitative", "scale": {"domain": [0, 1]},
                                "axis": {"format": "%"}, "title": x_title + " (bar), 95% Wilson interval (line)"},
                          "color": {"field": "group", "type": "nominal", "sort": groups,
                                    "scale": {"domain": groups, "range": [BLUE, AMBER, ORANGE, GREEN][:len(groups)]},
                                    "legend": None if len(groups) == 1 else {"orient": "bottom", "title": None}},
                          "tooltip": [{"field": "measure", "title": "Measure"}, {"field": "lbl", "title": "k of n"},
                                      {"field": "lo", "format": ".1%", "title": "95% low"},
                                      {"field": "hi", "format": ".1%", "title": "95% high"}]}},
            {"mark": {"type": "rule", "color": INK}, "encoding": {"x": {"field": "lo"}, "x2": {"field": "hi"}}},
            {"mark": {"type": "text", "align": "left", "dx": 4, "color": INK},
             "encoding": {"x": {"field": "hi"}, "text": {"field": "lbl"}}},
        ]}
    return vega(name, dataset, fields, False, spec, title, desc, p)


def page(name, display, layout):
    return {"name": name, "displayName": display, "pageType": "PAGE_TYPE_CANVAS", "layoutVersion": "GRID_V1",
            "layout": layout}


def header(prefix, title, caveat):
    return [text(f"{prefix}_title", [f"## {title}\n"], pos(0, 0, 12, 1)),
            text(f"{prefix}_caveat", [f"{caveat}\n"], pos(0, 1, 12, 2))]


def page1():
    rates = [("k_high", "SUM(`is_high_conf`)", "High-confidence location", "Location"),
             ("k_pin", "SUM(`pin_far`)", "Map pin 50+ km from its postcode", "Location"),
             ("k_other", "SUM(`names_other_facility`)", "Text places care at another named facility", "Text"),
             ("k_dir", "SUM(`directory_phone`)", "Official phone is a directory number (hidden)", "Contact")]
    state_spec = {
        "encoding": {"y": {"field": "label", "type": "nominal", "sort": {"field": "per_m", "order": "descending"},
                           "title": None}},
        "layer": [
            {"mark": {"type": "bar", "color": BLUE, "opacity": 0.85},
             "encoding": {"x": {"field": "per_m", "type": "quantitative", "title": "Records per million people"},
                          "tooltip": [{"field": "label", "title": "State"},
                                      {"field": "records", "title": "Records (n)", "format": ","},
                                      {"field": "pop_m", "title": "People (M)", "format": ".1f"},
                                      {"field": "per_m", "title": "Per million", "format": ".2f"},
                                      {"field": "per_m_lo", "title": "95% low", "format": ".2f"},
                                      {"field": "per_m_hi", "title": "95% high", "format": ".2f"}]}},
            {"mark": {"type": "rule", "color": INK}, "encoding": {"x": {"field": "per_m_lo"}, "x2": {"field": "per_m_hi"}}},
        ]}
    return page("district_glance", "1. District at a glance", header(
        "p1", "District at a glance",
        SHARED_CAVEAT + " Tile 1.4 is national (every state over 1 million people); the rest follow the state "
        "and district filters. A district with no record has no public evidence of care in this dataset, which "
        "is not the same as no care.") + [
        counter("p1_records", "ds_facility", "COUNT(`unique_id`)", "1.1 Records here",
                "Facility records in the selected state and district (n for the rates on this page)", pos(0, 3, 4, 3)),
        counter("p1_highconf", "ds_facility", "AVG(`is_high_conf`)", "1.2 High-confidence location",
                "Share of the records in 1.1; k, n and 95% interval in 1.x below", pos(4, 3, 4, 3), PCT),
        counter("p1_other", "ds_facility", "AVG(`names_other_facility`)", "1.3 Names another facility",
                "Share of records whose own text places care at another named facility; n in 1.1", pos(8, 3, 4, 3), PCT),
        rate_bars("p1_rates", "ds_facility", rates, "COUNT(`unique_id`)", "1.x Record checks here, k of n",
                  "Wilson 95% intervals from the filtered records; n under 30 is marked small sample. The other-facility "
                  "flag was right on about 20 of 30 sentences in a hand check.", pos(0, 6, 12, 4)),
        vega("p1_state", "ds_state", [(c, f"`{c}`") for c in ("label", "per_m", "per_m_lo", "per_m_hi", "records", "pop_m")],
             True, state_spec, "1.4 Records per million people by state, 95% Poisson interval",
             "National, states and UTs over 1 million people. Bihar 1.95 (1.72 to 2.20): 260 records for 133.5 M people.",
             pos(0, 10, 6, 11)),
        {"widget": {"name": "p1_points",
                    "queries": query("ds_facility", [("loc_lon", "`loc_lon`"), ("loc_lat", "`loc_lat`"),
                                                     ("loc_conf", "`loc_conf`")], True),
                    "spec": {"version": 3, "widgetType": "scatter",
                             "encodings": {"x": {"fieldName": "loc_lon", "scale": {"type": "quantitative", "zero": False},
                                                 "displayName": "Longitude"},
                                           "y": {"fieldName": "loc_lat", "scale": {"type": "quantitative", "zero": False},
                                                 "displayName": "Latitude"},
                                           "color": {"fieldName": "loc_conf", "displayName": "Location confidence",
                                                     "scale": {"type": "categorical", "mappings": [
                                                         {"value": "high", "color": BLUE},
                                                         {"value": "medium", "color": LIKELY},
                                                         {"value": "low", "color": AMBER},
                                                         {"value": "disputed", "color": UNLIKELY}]}}},
                             "frame": frame("1.6 Facility points by location confidence",
                                            "Cleaned ranking point, longitude against latitude, no basemap and no boundaries.")}},
         "position": pos(6, 10, 6, 11)},
        table("p1_districts", "ds_district",
              [("state", "State", None), ("district", "District (LGD)", None), ("pop_m", "People (M)", NUM1),
               ("records", "Records", None), ("per_m", "Records per million", NUM2),
               ("no_record_flag", "No record", None)],
              "1.5 Districts: people, records, records per million",
              "\"no record\" means no public evidence of care in this dataset, not no care. 227 of 784 districts "
              "(163 M people) have no record.", pos(0, 21, 12, 7)),
    ])


def page2():
    access_spec = {
        "encoding": {"y": {"field": "label", "type": "nominal",
                           "sort": {"field": "share_60_confirmed_trauma", "order": "ascending"}, "title": None}},
        "layer": [
            {"mark": {"type": "bar", "color": BLUE, "opacity": 0.85},
             "encoding": {"x": {"field": "share_60_confirmed_trauma", "type": "quantitative",
                                "scale": {"domain": [0, 1]}, "axis": {"format": "%"},
                                "title": "Share of people within 60 min"},
                          "tooltip": [{"field": "label", "title": "State"},
                                      {"field": "share_60_confirmed_trauma", "format": ".1%", "title": "Confirmed trauma"},
                                      {"field": "corr_lo", "format": ".1%", "title": "Route error low"},
                                      {"field": "corr_hi", "format": ".1%", "title": "Route error high"},
                                      {"field": "n_corr", "title": "Confirmed trauma facilities (n)"},
                                      {"field": "share_60_any_record", "format": ".1%", "title": "Any record"},
                                      {"field": "share_60_any_clinic", "format": ".1%", "title": "Any clinic (MAP)"}]}},
            {"mark": {"type": "rule", "color": INK}, "encoding": {"x": {"field": "corr_lo"}, "x2": {"field": "corr_hi"}}},
            {"mark": {"type": "point", "filled": True, "color": ORANGE, "size": 40},
             "encoding": {"x": {"field": "share_60_any_record"}}},
            {"mark": {"type": "point", "shape": "square", "filled": True, "color": GREEN, "size": 30},
             "encoding": {"x": {"field": "share_60_any_clinic"}}},
        ]}
    access_fields = [(c, f"`{c}`") for c in ("label", "share_60_confirmed_trauma", "corr_lo", "corr_hi", "n_corr",
                                              "share_60_any_record", "share_60_any_clinic")]
    return page("access", "2. Access to confirmed care", header(
        "p2", "Access to confirmed care",
        SHARED_CAVEAT + " Drive times are free-flow over the MAP 2020 friction surface with no dispatch delay. "
        "Whiskers are measured route error (34 to 85 minutes), not sampling error. The dialysis need proxy is "
        "risk (NCD prevalence), not kidney-failure counts. PMNDP is a state count, not a list of locations.") + [
        vega("p2_golden", "ds_state", access_fields, True, access_spec,
             "2.1 Within 60 minutes of confirmed trauma care, by state",
             "National. Bar: confirmed trauma claim, whisker: route error. Orange dot: any record; green square: "
             "any clinic (MAP 2020). About 500 M people (283 M to 821 M) are over an hour from confirmed trauma care.",
             pos(0, 3, 6, 11)),
        {"widget": {"name": "p2_outside",
                    "queries": query("ds_state", [("label", "`label`"), ("people_outside_m", "`people_outside_m`")], True),
                    "spec": {"version": 3, "widgetType": "bar",
                             "encodings": {"x": {"scale": {"type": "quantitative"},
                                                 "fields": [{"fieldName": "people_outside_m",
                                                             "displayName": "People over 1 h from confirmed trauma care (M)"}]},
                                           "y": {"fieldName": "label", "displayName": "State",
                                                 "scale": {"type": "categorical", "sort": {"by": "value"}}}},
                             "frame": frame("2.2 People more than an hour from confirmed trauma care (millions)",
                                            "National. Small north-eastern states rest on one confirmed facility each.")}},
         "position": pos(6, 3, 6, 11)},
        table("p2_dialysis", "ds_dialysis_district",
              [("state", "State", None), ("district", "District (LGD)", None), ("nfhs_district", "NFHS district", None),
               ("pop_m", "People (M)", NUM1), ("need_proxy", "Need proxy (NCD risk)", PCT),
               ("burden_q", "Need quintile", None), ("n_claim", "Records claiming dialysis", None),
               ("n_corr", "Confirmed (n)", None), ("corr_per_m", "Confirmed per million", NUM2),
               ("share60", "People within 1 h of confirmed", PCT), ("median_min", "Median minutes", NUM0),
               ("hot_flag", "Flag", None)],
              "2.3 Dialysis need against access to confirmed dialysis, by district",
              "Flag = high need and over an hour from confirmed dialysis (69 NFHS districts nationally, 103.8 M people). "
              "An NFHS district split into several LGD districts repeats once per LGD district.", pos(0, 14, 12, 7)),
        table("p2_csection", "ds_csection_district",
              [("state", "State", None), ("district", "District (LGD)", None), ("nfhs_district", "NFHS district", None),
               ("women_15_49_m", "Women 15-49 (M)", NUM2), ("csection_rate", "Births by caesarean", PCT),
               ("band", "Band", None), ("n_claimed", "Records claiming C-section", None),
               ("n_corroborated", "Confirmed (n)", None), ("n_laqshya", "LaQshya theatres (n)", None)],
              "2.4 Districts where under 10% of births are caesareans",
              "152 NFHS districts nationally (39 under 5%, 113 at 5-10%). LaQshya is a public subset list, so "
              "zero here is no public evidence, not no theatre.", pos(0, 21, 12, 6)),
        table("p2_burden", "ds_dialysis_burden",
              [("state", "State", None), ("district", "District (LGD)", None), ("pop_m", "People (M)", NUM1),
               ("median_weekly_km_claimed", "Weekly km, nearest claim", NUM0),
               ("median_weekly_km_graded", "Weekly km, nearest graded", NUM0),
               ("median_weekly_km_corroborated", "Weekly km, nearest confirmed", NUM0),
               ("median_weekly_hours_corroborated", "Weekly hours, nearest confirmed", NUM1)],
              "2.5 Weekly road km for three dialysis sessions, by district and evidence tier",
              "Median over the district's people, three round trips a week, free-flow road travel.", pos(0, 27, 12, 6)),
        {"widget": {"name": "p2_settlement",
                    "queries": query("ds_settlement", [("settlement", "`settlement`"), ("care", "`care`"),
                                                       ("avg(within60)", "AVG(`within60`)")], False),
                    "spec": {"version": 3, "widgetType": "bar",
                             "encodings": {"x": {"fieldName": "settlement", "displayName": "Settlement class",
                                                 "scale": {"type": "categorical", "sort": {"by": "custom-order",
                                                           "orderedValues": ["Urban centre", "Town or semi-dense", "Rural"]}}},
                                           "y": {"fieldName": "avg(within60)", "displayName": "People within 1 h of confirmed care",
                                                 "scale": {"type": "quantitative"}, "format": PCT},
                                           "color": {"fieldName": "care", "displayName": "Care",
                                                     "scale": {"type": "categorical"}},
                                           "label": {"show": True}},
                             "mark": {"layout": "group"},
                             "frame": frame("2.6 Within an hour of confirmed care, by settlement class",
                                            "National population shares (whole population, not a sample). Classes are GHS "
                                            "degree of urbanisation.")}},
         "position": pos(0, 33, 6, 7)},
        table("p2_pmndp", "ds_pmndp",
              [("state", "State", None), ("pmndp_centres", "PMNDP centres", None),
               ("pmndp_districts", "PMNDP districts", None), ("vf_records", "Records", NUM0),
               ("vf_dialysis", "Records mentioning dialysis", NUM0),
               ("vf_public_dialysis", "Public records mentioning dialysis", NUM0)],
              "2.7 Public dialysis centres (PMNDP) against public records that mention dialysis",
              "PMNDP is a state count reported by the government (1,994 centres nationally), not a list of locations.",
              pos(6, 33, 6, 7)),
    ])


def page3():
    steps = [("k_m", "SUM(`mentioned`)", "1 Mentioned", "Own record"),
             ("k_f2", "SUM(`in_2plus_fields`)", "2 In 2+ fields", "Own record"),
             ("k_own", "SUM(`own_checks`)", "3 Plus prerequisite", "Own record"),
             ("k_out", "SUM(`own_and_outside`)", "4 Plus outside check", "Outside check")]
    return page("services", "3. Claimed against confirmed", header(
        "p3", "Services: claimed against confirmed",
        SHARED_CAVEAT + " Use the service filter. List coverage is structural: NABH scopes cover 7 codes, LaQshya "
        "and MoHFW are public subsets, NMC is teaching hospitals only and no list covers MRI. Websites are not "
        "independent of the record: an unconfirmed claim at a facility with no website is missing evidence, "
        "not evidence against.") + [
        counter("p3_records", "ds_facility", "COUNT(`unique_id`)", "Records here",
                "n for the two hours rates", pos(0, 3, 4, 3)),
        counter("p3_hours", "ds_facility", "AVG(`any_hours`)", "3.3 Any stated hours",
                "Dataset, website or OpenStreetMap; national 6,074 of 9,959", pos(4, 3, 4, 3), PCT),
        counter("p3_24x7", "ds_facility", "AVG(`emergency_24x7`)", "3.3 A 24x7 emergency statement",
                "A statement, not a staffing check; national 2,829 of 9,959", pos(8, 3, 4, 3), PCT),
        rate_bars("p3_funnel", "ds_funnel", steps, "SUM(`mentioned`)", "3.1 Evidence ladder for the service, k of mentions",
                  "Each step keeps the previous ones. The outside step counts a website only where a site was found, "
                  "or an official list. National, all services: 7,969 mentioned, 1,798 own checks, 837 also outside.",
                  pos(0, 6, 12, 4), x_title="Share of mentions"),
        table("p3_facilities", "ds_pairs",
              [("name", "Facility", None), ("district", "District", None), ("service", "Service", None),
               ("band", "Band (model v2)", None), ("operator", "Operator", None),
               ("p_s", "P_S: chance a decisive web check confirms it", NUM2),
               ("bin_lo", "Score bin confirmed rate, low", NUM2), ("bin_hi", "Score bin confirmed rate, high", NUM2),
               ("p_l", "Location score P_L", NUM2), ("p_e", "Existence score P_E", NUM2),
               ("loc_conf", "Location confidence", None), ("website_class", "Website", None),
               ("flags", "Flags", None)],
              "3.2 Facilities for the service, ranked by P_S (model v2)",
              "Rows banded Likely or Call first (the record describes the service as its own unit). P_S is the "
              "chance a web check that finds a decisive answer confirms the service, not the chance a phone call "
              "finds it. The two bin columns are the observed confirmed rate of DEV pairs in the same 0.2-wide "
              "score bin, not an interval around P_S. " + PUBLIC_CAVEAT + " Call before referring.",
              pos(0, 10, 12, 8), filters=["`shortlisted` = 1"]),
        table("p3_lists", "ds_list_facts",
              [("facility", "Facility (dataset record)", None), ("district", "District", None),
               ("list_name", "Official list", None), ("status", "Status on the list", None),
               ("list_service", "Service the list covers", None), ("valid_to", "Valid to", None),
               ("as_of", "List as of", None), ("citation_url", "Citation", None)],
              "3.4 Official list facts for matched facilities",
              "Per-facility matched facts with their citation, never the lists themselves (NABH, NMC and MoHFW are "
              "restricted). Matcher recall was not measured, so an unmatched facility is not evidence against it. "
              "Follows state and district only.", pos(0, 18, 12, 7)),
    ])


def page4():
    cleaning = [("k_fix_pt", "SUM(`fixed_corrected_point`)", "Ranked on a corrected point", "Fixed"),
                ("k_fix_tx", "SUM(`fixed_quarantined_text`)", "Text about other facilities quarantined", "Fixed"),
                ("k_flag_loc", "SUM(`flagged_location`)", "Location low or disputed", "Flagged"),
                ("k_flag_sz", "SUM(`flagged_size`)", "Size claims flagged", "Flagged"),
                ("k_cant", "SUM(`cannot_fix`)", "Keeps a problem no rule can fix", "Cannot fix"),
                ("k_ok", "SUM(`rated_no_concerns`)", "Rated no concerns (location and contact only)", "Rating")]
    return page("check_by_phone", "4. Records to check by phone", header(
        "p4", "Records to check by phone",
        SHARED_CAVEAT + " A far pin is sometimes right and the postcode wrong (coordinates right 14 of 40 in a hand "
        "check). \"No concerns\" covers location and contact data only, so it overlaps with copied text by design. "
        "Call first is the default on every card.") + [
        counter("p4_records", "ds_facility", "COUNT(`unique_id`)", "Records here", "n for the rates on this page",
                pos(0, 3, 4, 3)),
        counter("p4_pinfar", "ds_facility", "AVG(`pin_far`)", "4.1 Map pin 50+ km from its postcode",
                "Share of records here; national 13.9%", pos(4, 3, 4, 3), PCT),
        counter("p4_dirphone", "ds_facility", "SUM(`directory_phone`)", "4.3 Directory phones hidden",
                "Records whose official phone is a directory number; national 292", pos(8, 3, 4, 3)),
        {"widget": {"name": "p4_locconf",
                    "queries": query("ds_facility", [("loc_conf", "`loc_conf`"), ("count(unique_id)", "COUNT(`unique_id`)")], False),
                    "spec": {"version": 3, "widgetType": "bar",
                             "encodings": {"x": {"fieldName": "loc_conf", "displayName": "Location confidence",
                                                 "scale": {"type": "categorical", "sort": {"by": "custom-order",
                                                           "orderedValues": ["high", "medium", "low", "disputed"]}}},
                                           "y": {"fieldName": "count(unique_id)", "displayName": "Records",
                                                 "scale": {"type": "quantitative"}},
                                           "color": {"fieldName": "loc_conf", "displayName": "Location confidence",
                                                     "scale": {"type": "categorical", "mappings": [
                                                         {"value": "high", "color": BLUE},
                                                         {"value": "medium", "color": LIKELY},
                                                         {"value": "low", "color": AMBER},
                                                         {"value": "disputed", "color": UNLIKELY}]}},
                                           "label": {"show": True}},
                             "frame": frame("4.2 Location confidence mix", "Records here by location confidence")}},
         "position": pos(0, 6, 5, 7)},
        rate_bars("p4_cleaning", "ds_facility", cleaning, "COUNT(`unique_id`)",
                  "4.4 What cleaning fixed, flagged and could not fix, k of n",
                  "Bars overlap; one record can be in several. National: 2,610 of 9,959 cannot be fixed by a rule, "
                  "1,589 of them rated no concerns. Copied text that names no facility is undercounted.",
                  pos(5, 6, 7, 7)),
        table("p4_callfirst", "ds_facility",
              [("name", "Facility", None), ("district", "District", None), ("call_reason", "Why call first", None),
               ("loc_conf", "Location confidence", None), ("pin_km", "Pin to postcode (km)", NUM1),
               ("loc_note", "Location note", None), ("trust_level", "Trust level", None),
               ("website_class", "Website", None)],
              "4.5 Records to call first",
              "Far pin, low or disputed location, or text that names another facility. Confirm the address and the "
              "service by phone before sending anyone.", pos(0, 13, 12, 8), filters=["`call_first` = 1"]),
    ])


def page5():
    site_spec = {
        "transform": WILSON_VL,
        "encoding": {"y": {"field": "operator", "type": "nominal", "sort": ["Public", "Private", "Not stated"],
                           "title": None},
                     "yOffset": {"field": "settlement", "sort": ["Urban centre", "Town or semi-dense", "Rural"]}},
        "layer": [
            {"mark": {"type": "bar", "opacity": 0.85},
             "encoding": {"x": {"field": "p", "type": "quantitative", "scale": {"domain": [0, 1]},
                                "axis": {"format": "%"}, "title": "Records with a crawlable own website"},
                          "color": {"field": "settlement", "type": "nominal",
                                    "sort": ["Urban centre", "Town or semi-dense", "Rural"],
                                    "scale": {"range": [BLUE, AMBER, GREEN]},
                                    "legend": {"orient": "bottom", "title": None}},
                          "tooltip": [{"field": "operator"}, {"field": "settlement"}, {"field": "lbl", "title": "k of n"},
                                      {"field": "lo", "format": ".1%", "title": "95% low"},
                                      {"field": "hi", "format": ".1%", "title": "95% high"}]}},
            {"mark": {"type": "rule", "color": INK}, "encoding": {"x": {"field": "lo"}, "x2": {"field": "hi"}}},
            {"mark": {"type": "text", "align": "left", "dx": 4, "color": INK, "fontSize": 10},
             "encoding": {"x": {"field": "hi"}, "text": {"field": "lbl"}}},
        ]}
    site_fields = [("operator", "`operator`"), ("settlement", "`settlement`"), ("k", "SUM(`own_site`)"),
                   ("n", "COUNT(`unique_id`)")]
    return page("trust_scores", "5. How far to trust the scores", header(
        "p6", "How far to trust the scores",
        SHARED_CAVEAT + " Bands are model v2 (derived/v2, A_platt) over 36 services and 9,947 eligible records. "
        + PUBLIC_CAVEAT + " The sealed v2 TEST is in the notebook (referral_saathi.ipynb).") + [
        {"widget": {"name": "p6_bands",
                    "queries": query("ds_pairs", [("band", "`band`"), ("count(unique_id)", "COUNT(`unique_id`)")], False),
                    "spec": {"version": 3, "widgetType": "bar",
                             "encodings": {"x": {"fieldName": "band", "displayName": "Band (model v2)",
                                                 "scale": {"type": "categorical", "sort": {"by": "custom-order",
                                                           "orderedValues": ["Likely", "Call first",
                                                                             "No service text", "Unlikely"]}}},
                                           "y": {"fieldName": "count(unique_id)", "displayName": "Facility-service pairs",
                                                 "scale": {"type": "quantitative"}},
                                           "color": {"fieldName": "band", "displayName": "Band (model v2)",
                                                     "scale": {"type": "categorical", "mappings": [
                                                         {"value": "Likely", "color": LIKELY},
                                                         {"value": "Call first", "color": AMBER},
                                                         {"value": "No service text", "color": UNVERIFIED},
                                                         {"value": "Unlikely", "color": UNLIKELY}]}},
                                           "label": {"show": True}},
                             "frame": frame("5.1 Model v2 bands for the service",
                                            "No service text: the record has no sentence about the service as its "
                                            "own unit, so P_S rests on context only. Unlikely means little or "
                                            "contaminated evidence, not that the service is absent. National, 36 "
                                            "services: 20,073 Likely, 1,671 Call first, 242,131 No service text, "
                                            "94,217 Unlikely.")}},
         "position": pos(0, 3, 6, 7)},
        vega("p6_website", "ds_facility", site_fields, False, site_spec,
             "5.2 Records with a crawlable own website, by operator and settlement class",
             "k of n with 95% Wilson intervals. Confirmation mostly means having a website (80.3% with a site, 2.5% "
             "without), so public and rural records are under-confirmed, not under-served.", pos(6, 3, 6, 7)),
    ])


def multi_filter(name, title, field, datasets, widget_type, default=None, p=None):
    queries = [{"name": f"{name}_{d}", "query": {"datasetName": d, "fields": [{"name": field, "expression": f"`{field}`"}],
                                                 "disaggregated": False}} for d in datasets]
    spec = {"version": 2, "widgetType": widget_type,
            "encodings": {"fields": [{"fieldName": field, "displayName": title, "queryName": q["name"]} for q in queries]},
            "frame": frame(title)}
    if default:
        spec["selection"] = {"defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": default}]}}}
    return {"widget": {"name": name, "queries": queries, "spec": spec}, "position": p}


STATE_DS = ["ds_facility", "ds_district", "ds_dialysis_district", "ds_csection_district", "ds_dialysis_burden",
            "ds_pmndp", "ds_funnel", "ds_pairs", "ds_list_facts"]
DISTRICT_DS = ["ds_facility", "ds_district", "ds_dialysis_district", "ds_csection_district", "ds_dialysis_burden",
               "ds_funnel", "ds_pairs", "ds_list_facts"]
SERVICE_DS = ["ds_funnel", "ds_pairs"]


def filters_page():
    return {"name": "filters", "displayName": "Filters", "pageType": "PAGE_TYPE_GLOBAL_FILTERS",
            "layoutVersion": "GRID_V1", "layout": [
                multi_filter("f_state", "State", "state", STATE_DS, "filter-multi-select", "BIHAR", pos(0, 0, 4, 2)),
                multi_filter("f_district", "District", "district", DISTRICT_DS, "filter-multi-select", None, pos(0, 2, 4, 2)),
                multi_filter("f_service", "Service", "service", SERVICE_DS, "filter-single-select", "dialysis",
                             pos(0, 4, 4, 2)),
            ]}


def build():
    dashboard = {
        "datasets": [{"name": d["name"], "displayName": d["displayName"],
                      "queryLines": [line + "\n" for line in d["sql"].splitlines()]} for d in DATASETS.values()],
        "pages": [page1(), page2(), page3(), page4(), page5(), filters_page()],
        "uiSettings": {"theme": {
            "canvasBackgroundColor": {"light": "#fcfcfb", "dark": "#1b1b1a"},
            "widgetBackgroundColor": {"light": "#ffffff", "dark": "#242423"},
            "widgetBorderColor": {"light": "#ffffff", "dark": "#242423"},
            "fontColor": {"light": "#0b0b0b", "dark": "#f0efe9"},
            "selectionColor": {"light": BLUE, "dark": LIKELY},
            "visualizationColors": [BLUE, ORANGE, GREEN, AMBER, PINK, DKGREEN],
            "widgetHeaderAlignment": "LEFT"}},
    }
    validate(dashboard)
    OUT_JSON.write_text(json.dumps(dashboard, indent=1))
    print(f"wrote {OUT_JSON} ({len(DATASETS)} datasets, {sum(len(p['layout']) for p in dashboard['pages'])} widgets)")
    return dashboard


def validate(d):
    """Structural checks from the skill's quality checklist; raises on the first problem."""
    names = {x["name"] for x in d["datasets"]}
    for p in d["pages"]:
        assert p.get("layoutVersion") == "GRID_V1" and p.get("pageType"), p["name"]
        for item in p["layout"]:
            w, pp = item["widget"], item["position"]
            assert pp["x"] + pp["width"] <= 12, (w["name"], pp)
            assert all(c.isalnum() or c in "-_" for c in w["name"]), w["name"]
            for q in w.get("queries", []):
                assert q["query"]["datasetName"] in names, (w["name"], q["query"]["datasetName"])
            spec = w.get("spec", {})
            if spec.get("widgetType") == "custom-vega-viz":
                inner = json.loads(spec["jsonSpec"]["spec"])
                assert inner["data"] == {"name": "databricks_query"}
                got = {f["name"] for f in w["queries"][0]["query"]["fields"]}
                assert got == {f["fieldName"] for f in spec["encodings"]["fields"]}, w["name"]
            elif spec.get("widgetType") in ("counter", "table", "bar", "scatter"):
                got = {f["name"] for f in w["queries"][0]["query"]["fields"]}
                enc = json.dumps(spec["encodings"])
                for f in got:
                    assert f'"fieldName": "{f}"' in enc, (w["name"], f)


# ---------------------------------------------------------------- warehouse
def cli(*args, check=True):
    r = subprocess.run(["databricks", *args, "--profile", PROFILE], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"databricks {args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[:800]}")
    return r.stdout


def run_sql(sql):
    body = {"warehouse_id": WAREHOUSE, "catalog": CATALOG, "schema": SCHEMA, "statement": sql,
            "wait_timeout": "50s", "disposition": "INLINE", "format": "JSON_ARRAY"}
    r = json.loads(cli("api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body)))
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(POLL_SECONDS)
        r = json.loads(cli("api", "get", f"/api/2.0/sql/statements/{r['statement_id']}"))
    if r["status"]["state"] != "SUCCEEDED":
        return r["status"]["state"], r["status"].get("error", {}).get("message", "")[:500]
    return "SUCCEEDED", r.get("result", {}).get("data_array", [])


def test():
    results, ok = {"datasets": {}, "checks": []}, True
    sqls = {k: v["sql"] for k, v in DATASETS.items()}
    for name, sql in sqls.items():
        t0 = time.time()
        state, rows = run_sql(f"SELECT COUNT(*) FROM ({sql}) t")
        rec = {"state": state, "rows": int(rows[0][0]) if state == "SUCCEEDED" else None,
               "seconds": round(time.time() - t0, 1)}
        if state != "SUCCEEDED":
            rec["error"], ok = rows, False
        elif rec["rows"] == 0:
            ok = False
        results["datasets"][name] = rec
        print(f"{name:26s} {state:10s} rows={rec['rows']} {rec['seconds']}s {rec.get('error', '')}")
    for label, tmpl in CHECKS:
        state, rows = run_sql(tmpl.format(**sqls))
        results["checks"].append({"check": label, "state": state, "result": rows})
        ok = ok and state == "SUCCEEDED"
        print(f"CHECK {label}\n      {state} {rows}")
    results["run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    TEST_JSON.write_text(json.dumps(results, indent=1))
    print(f"wrote {TEST_JSON}; all ok: {ok}")
    return ok


def deploy():
    me = json.loads(cli("current-user", "me", "-o", "json"))["userName"]
    parent = f"/Workspace/Users/{me}/databricksdatathon/dashboards"
    cli("workspace", "mkdirs", parent)
    serialized = OUT_JSON.read_text()
    common = ["--dataset-catalog", CATALOG, "--dataset-schema", SCHEMA, "--serialized-dashboard", serialized]
    if ID_FILE.exists():
        dash_id = ID_FILE.read_text().strip()
        cli("lakeview", "update", dash_id, "--display-name", DISPLAY_NAME, "--warehouse-id", WAREHOUSE, *common,
            "-o", "json")
        print(f"updated {dash_id}")
    else:
        out = cli("lakeview", "create", "--display-name", DISPLAY_NAME, "--warehouse-id", WAREHOUSE, *common,
                  "--json", json.dumps({"parent_path": parent}), "-o", "json")
        dash_id = json.loads(out)["dashboard_id"]
        ID_FILE.write_text(dash_id + "\n")
        print(f"created {dash_id} in {parent}")
    cli("lakeview", "publish", dash_id, "--warehouse-id", WAREHOUSE, "--embed-credentials")
    pub = json.loads(cli("lakeview", "get-published", dash_id, "-o", "json"))
    host = json.loads(cli("auth", "env", "-o", "json"))["env"]["DATABRICKS_HOST"].rstrip("/")
    print(f"published: embed_credentials={pub.get('embed_credentials')} revised={pub.get('revision_create_time')}")
    print(f"draft:     {host}/sql/dashboardsv3/{dash_id}")
    print(f"published: {host}/sql/dashboardsv3/{dash_id}/published")
    return dash_id


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd in ("build", "all", "deploy"):
        build()
    if cmd in ("test", "all") and not test():
        sys.exit("a dataset query failed or returned no rows; not deploying")
    if cmd in ("deploy", "all"):
        deploy()

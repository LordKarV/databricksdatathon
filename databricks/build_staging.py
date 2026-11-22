"""Builders for tables that have no ready parquet file: JSON flattened to rows, and per-facility
official-list facts assembled from the matcher outputs. Each builder writes one parquet file into
build/databricks_staging/ and returns its path. load_tables.py calls them by the `build` name in
tables.yaml, so a reload always rebuilds from the current local files.
"""
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "build" / "databricks_staging"
EXT = ROOT / "data" / "external"


def _cell(v):
    """Keep scalars and lists of strings; everything else becomes a JSON string."""
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return v
    return json.dumps(v, ensure_ascii=False)


def _write(rows, name):
    """Write dict rows to parquet. A column whose values mix types is stored as JSON text."""
    cols = list(dict.fromkeys(k for r in rows for k in r))
    data = {}
    for c in cols:
        vals = [_cell(r.get(c)) for r in rows]
        kinds = {type(v) for v in vals if v is not None}
        if kinds == {int, float}:
            vals = [None if v is None else float(v) for v in vals]
        elif len(kinds) > 1:
            vals = [None if v is None else (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for v in vals]
        data[c] = vals
    STAGING.mkdir(parents=True, exist_ok=True)
    path = STAGING / f"{name}.parquet"
    pq.write_table(pa.table(data), path)
    return path


def services():
    s = json.loads((ROOT / "kb/taxonomy/services.json").read_text())
    rows = []
    for cat in s["categories"]:
        for sv in cat["services"]:
            r = {"service_id": sv["id"], "category_id": cat["id"], "category_name": cat["name"],
                 "name_en": (sv.get("names") or {}).get("en", [None])[0],
                 "urgency_profile": (sv.get("urgency") or {}).get("profile"),
                 "urgency_window": (sv.get("urgency") or {}).get("window")}
            r.update({k: v for k, v in sv.items() if k != "id"})
            rows.append(r)
    for sv in s.get("candidates_not_included", []):
        r = {"service_id": sv["id"], "category_id": "candidate", "category_name": "Candidate, not answered",
             "name_en": (sv.get("names") or {}).get("en", [None])[0]}
        r.update({k: v for k, v in sv.items() if k != "id"})
        rows.append(r)
    return _write(rows, "services")


def _pathways():
    return json.loads((ROOT / "kb/pathways/care_pathways.json").read_text())["pathways"]


def care_pathways():
    rows = [{"pathway_id": p["id"], "n_stages": len(p["stages"]), "n_rules": len(p["rules"]),
             **{k: v for k, v in p.items() if k not in ("id", "stages", "rules")}} for p in _pathways()]
    return _write(rows, "care_pathways")


def pathway_stages():
    rows = []
    for p in _pathways():
        for i, st in enumerate(p["stages"], 1):
            w, d = st.get("window") or {}, st.get("dwell_minutes") or {}
            rows.append({"pathway_id": p["id"], "stage_order": i, "stage_id": st["id"],
                         "is_last_stage": i == len(p["stages"]),
                         "window_minutes": w.get("minutes"), "window_from": w.get("from"),
                         "window_basis": w.get("basis"), "dwell_typical_minutes": d.get("typical"),
                         "dwell_basis": d.get("basis"),
                         **{k: v for k, v in st.items() if k != "id"}})
    return _write(rows, "pathway_stages")


def pathway_rules():
    rows = [{"pathway_id": p["id"], "rule_id": r["id"],
             "definitive_travel_minutes_gt": (r.get("condition") or {}).get("definitive_travel_minutes_gt"),
             **{k: v for k, v in r.items() if k != "id"}}
            for p in _pathways() for r in p["rules"]]
    return _write(rows, "pathway_rules")


def pathway_capabilities():
    caps = json.loads((ROOT / "kb/pathways/capabilities.json").read_text())["capabilities"]
    return _write([{"capability_id": c["id"], **{k: v for k, v in c.items() if k != "id"}} for c in caps],
                  "pathway_capabilities")


def model_test_metrics():
    """Every leaf of the two published test-metric files as (source_file, path, value). Quoted, not recomputed."""
    rows = []

    def walk(x, path, src):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{path}.{k}" if path else k, src)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]", src)
        else:
            num = float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None
            rows.append({"source_file": src, "path": path, "value_num": num,
                         "value_text": None if x is None else str(x)})

    for src in ("model/review/stats/results.json", "model/proto/fusion/test_metrics.json"):
        walk(json.loads((ROOT / src).read_text()), "", src)
    return _write(rows, "model_test_metrics")


def pmndp_state():
    """claims story 4 PMNDP table with an LGD-spelled `state` column so it joins the state filter."""
    con = duckdb.connect()
    path = STAGING / "pmndp_state.parquet"
    STAGING.mkdir(parents=True, exist_ok=True)
    con.execute(f"""COPY (SELECT *, CASE upper(state)
          WHEN 'JAMMU AND KASHMIR' THEN 'JAMMU & KASHMIR'
          WHEN 'ANDAMAN AND NICOBAR ISLANDS' THEN 'ANDAMAN & NICOBAR'
          WHEN 'THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU' THEN 'DADRA,NAGAR HAVELI,DAMAN & DIU'
          ELSE upper(state) END AS state_lgd
        FROM read_csv_auto('{ROOT}/viz/claims/data/s4_pmndp.csv')) TO '{path}' (FORMAT parquet)""")
    return path


# Service ids follow the dashboard filter (derived/v1 gold ids); other lists use kb/taxonomy ids.
NMC_SERVICE = {"csection": "emergency_csection", "trauma": "trauma_emergency", "burns": "burn_care"}
LISTS_AS_OF = "2026-11-21"  # day every list below was read or downloaded (per external/<slug>/README.md)

LIST_FACTS_SQL = f"""
WITH nabh AS (
  SELECT 'nabh' AS list_slug, 'NABH accredited healthcare organisations' AS list_name,
         m.unique_id, CAST(NULL AS VARCHAR) AS service, m.status, m.acc_no AS list_record_id,
         m.name_nb AS listed_name, CAST(NULL AS DATE) AS valid_to,
         'name and location match' AS match_method, m.raw_score AS match_score,
         m.cert_url AS citation_url, array_to_string(m.nabh_specs, '|') AS detail,
         'NABH terms: per-facility fact with link to the NABH certificate only; never republish the list' AS licence_note
  FROM '{EXT}/nabh_accredited/nabh_vf_match.parquet' m WHERE m.accept),
lq AS (
  SELECT 'laqshya' AS list_slug, 'LaQshya certification status (NHSRC, file dated 08-04-2026)' AS list_name,
         m.unique_id, d.service,
         CASE WHEN d.valid_to >= DATE '{LISTS_AS_OF}' THEN 'certified, valid' ELSE 'certified, expired' END AS status,
         CAST(m.lq_id AS VARCHAR) AS list_record_id, m.lq_name AS listed_name, d.valid_to,
         'name core and district match' AS match_method, m.core_score AS match_score,
         'https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf' AS citation_url,
         d.department AS detail, 'NHSRC: reproduce with credit' AS licence_note
  FROM '{EXT}/laqshya_master/laqshya_vf_matches.parquet' m
  JOIN (SELECT lq_id, 'institutional_delivery' AS service, 'Labour Room' AS department, CAST("Labour Room" AS DATE) AS valid_to
          FROM '{EXT}/laqshya_master/laqshya_facilities.parquet' WHERE "Labour Room" IS NOT NULL
        UNION ALL
        SELECT lq_id, 'emergency_csection', 'Maternity OT', CAST("Maternity OT" AS DATE)
          FROM '{EXT}/laqshya_master/laqshya_facilities.parquet' WHERE "Maternity OT" IS NOT NULL
        UNION ALL
        SELECT lq_id, NULL, 'Unspecified department', CAST("Unspecified" AS DATE)
          FROM '{EXT}/laqshya_master/laqshya_facilities.parquet' WHERE "Unspecified" IS NOT NULL) d USING (lq_id)),
nmc_base AS (
  SELECT m.*, c.updated_date FROM '{EXT}/nmc_colleges/nmc_vf_matches.parquet' m
  LEFT JOIN '{EXT}/nmc_colleges/nmc_colleges.parquet' c USING (college_id)),
nmc AS (
  SELECT 'nmc' AS list_slug, 'NMC medical colleges and approved courses' AS list_name, b.unique_id,
         s.service, CASE WHEN s.service IS NULL THEN 'NMC-listed medical college'
                         ELSE 'NMC-approved course, ' || s.tier || ' evidence' END AS status,
         CAST(b.college_id AS VARCHAR) AS list_record_id, b.college_name AS listed_name,
         CAST(NULL AS DATE) AS valid_to, b.gate || ' gate' AS match_method, b.score AS match_score,
         'https://nmc.org.in/college-courses/detail/' || CAST(b.college_id AS VARCHAR) AS citation_url,
         CASE WHEN s.service IS NULL THEN 'updated ' || b.updated_date
              ELSE array_to_string(s.courses, '|') || ' (' || CAST(s.seats AS VARCHAR) || ' seats), updated ' || b.updated_date END AS detail,
         'NMC terms: per-facility fact with citation only; never republish the list' AS licence_note
  FROM nmc_base b
  LEFT JOIN (SELECT college_id, courses, seats, tier,
                    CASE service {' '.join(f"WHEN '{k}' THEN '{v}'" for k, v in NMC_SERVICE.items())} ELSE service END AS service
               FROM '{EXT}/nmc_colleges/nmc_service_labels.parquet'
             UNION ALL SELECT DISTINCT college_id, NULL, NULL, NULL, NULL
               FROM '{EXT}/nmc_colleges/nmc_vf_matches.parquet') s USING (college_id)),
tcf AS (
  SELECT 'mohfw_trauma' AS list_slug, 'MoHFW trauma care facilities (196, Wayback copy)' AS list_name,
         vf_id AS unique_id, 'trauma_emergency' AS service,
         'level ' || level || coalesce(', ' || status, '') AS status, CAST(sno AS VARCHAR) AS list_record_id,
         tcf_name AS listed_name, CAST(NULL AS DATE) AS valid_to, 'same state, place and name tokens' AS match_method,
         CAST(score AS DOUBLE) AS match_score,
         'https://web.archive.org/web/20231215043518id_/https://main.mohfw.gov.in/sites/default/files/List%20of%20Trauma%20Care.pdf' AS citation_url,
         'trauma care facility level ' || level AS detail,
         'MoHFW: per-facility fact with citation only; never republish the list' AS licence_note
  FROM read_csv_auto('{EXT}/mohfw_trauma_196/tcf_vf_matches.csv')),
erk AS (
  SELECT 'eraktkosh' AS list_slug, 'e-RaktKosh blood centre directory' AS list_name, unique_id,
         'blood_bank' AS service, erk_type || ' (' || erk_category || ')' AS status,
         CAST(CAST(hospital_code AS BIGINT) AS VARCHAR) AS list_record_id, erk_name AS listed_name,
         CAST(NULL AS DATE) AS valid_to, gate || ' gate' AS match_method, score AS match_score,
         'https://eraktkosh.mohfw.gov.in/eraktkoshPortal/' AS citation_url,
         CASE WHEN gate = 'distance' THEN 'matched by name and distance (' || CAST(round(km, 1) AS VARCHAR) || ' km)'
              ELSE 'matched by district only' END AS detail,
         'e-RaktKosh: no reuse licence stated; per-facility fact with citation only' AS licence_note
  FROM '{EXT}/eraktkosh_blood_centres/erk_vf_matches.parquet'),
pmndp AS (
  SELECT 'pmndp_goa' AS list_slug, 'Goa NHM PMNDP haemodialysis centres (status as on 29/06/2020)' AS list_name,
         vf_unique_id AS unique_id, 'dialysis' AS service, 'operational haemodialysis centre in 2020' AS status,
         pmndp_name AS list_record_id, pmndp_name AS listed_name, CAST(NULL AS DATE) AS valid_to,
         'name and PIN match' AS match_method, score AS match_score,
         'https://nhm.goa.gov.in/wp-content/uploads/2020/07/PMNDP-List-of-centres.pdf' AS citation_url,
         'PIN ' || CAST(pmndp_pin AS VARCHAR) AS detail, 'NHM Goa: no stated licence; cite with URL' AS licence_note
  FROM read_csv_auto('{EXT}/pmndp_counts_and_state_lists/goa_matches.csv') WHERE matched)
SELECT list_slug || ':' || list_record_id || ':' || unique_id || ':' || coalesce(service, '-') AS fact_id,
       *, DATE '{LISTS_AS_OF}' AS as_of
FROM (SELECT * FROM nabh UNION ALL BY NAME SELECT * FROM lq UNION ALL BY NAME SELECT * FROM nmc
      UNION ALL BY NAME SELECT * FROM tcf UNION ALL BY NAME SELECT * FROM erk UNION ALL BY NAME SELECT * FROM pmndp)
"""


def facility_list_facts():
    STAGING.mkdir(parents=True, exist_ok=True)
    path = STAGING / "facility_list_facts.parquet"
    duckdb.connect().execute(f"COPY ({LIST_FACTS_SQL}) TO '{path}' (FORMAT parquet)")
    return path


if __name__ == "__main__":
    # Self-check: every builder runs and the list facts carry a citation and a facility on every row.
    for fn in (services, care_pathways, pathway_stages, pathway_rules, pathway_capabilities,
               model_test_metrics, pmndp_state, facility_list_facts):
        print(fn.__name__, pq.read_metadata(fn()).num_rows)
    con = duckdb.connect()
    f = STAGING / "facility_list_facts.parquet"
    bad = con.execute(f"SELECT count(*) FROM '{f}' WHERE citation_url IS NULL OR unique_id IS NULL OR fact_id IS NULL").fetchone()[0]
    dup = con.execute(f"SELECT count(*) - count(DISTINCT fact_id) FROM '{f}'").fetchone()[0]
    assert bad == 0 and dup == 0, (bad, dup)
    print(con.execute(f"SELECT list_slug, service, count(*) FROM '{f}' GROUP BY ALL ORDER BY 1, 2").fetchall())

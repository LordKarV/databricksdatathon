"""specialty_map.csv: every distinct raw specialties value -> service id | too_general | out_of_scope | not_a_service.

Order: (1) deterministic normalisation + ordered keyword rules (specialty_rules.py); (2) fuzzy match (rapidfuzz ratio
>= 90) of the normalised value to a rule-labelled value; (3) ai_query batches with databricks-meta-llama-3-3-70b-instruct,
strict JSON schema, for the remainder. LLM answers are cached in out/llm_labels.json so re-runs make no Databricks call.

Run: /Users/karthikvattem/projects/datathon/.venv/bin/python build_specialty_map.py
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time

import duckdb
import pandas as pd
from rapidfuzz import fuzz, process

import specialty_rules as R

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
USABLE = "/Users/karthikvattem/projects/datathon/cleaning/geo_identity/facility_location.parquet"  # 9,959 usable records
LLM_CACHE = os.path.join(OUT, "llm_labels.json")
MODEL = "databricks-meta-llama-3-3-70b-instruct"
WAREHOUSE = "6a2f5637720a2c17"
CHUNK = 60
FUZZY_MIN = 94  # on space-stripped strings; 90 let 'neuromuscular' match 'neurovascular' and 'neuro oncology' match 'uro oncology'
MAX_STATEMENTS = 8

# Hand review of the LLM labels (every non-out_of_scope LLM label was read) and of the two hand-check samples.
# Applied last, method = manual. Each entry: value -> (label, prereq_for, reason).
OVERRIDES = {
    "emergencyMedicalServices": ("emergency_24x7", "", "LLM said emergency_csection"),
    "CBCT": ("out_of_scope", "", "dental cone-beam CT, not a CT scanner service; LLM said ct_scan"),
    "heartFailureClinic": ("too_general", "cath_lab_angioplasty;cardiac_surgery", "clinic, not surgery; LLM said cardiac_surgery"),
    "kidneyHealthCentre": ("too_general", "dialysis;kidney_transplant", "does not by itself show dialysis; LLM said dialysis"),
    "kidneySciences": ("too_general", "dialysis;kidney_transplant", "does not by itself show dialysis; LLM said dialysis"),
    "wellWomenClinic": ("out_of_scope", "", "LLM said institutional_delivery"),
    "Bone Tumor Treatment": ("surgical_oncology", "", "LLM said orthopaedic_trauma_surgery"),
    "Onco Care": ("too_general", "chemotherapy;radiotherapy;surgical_oncology", "LLM said surgical_oncology"),
    "neurologyTests": ("out_of_scope", "", "random hand check: diagnostic tests, not a broad specialty"),
    "pulmonaryVascularMedicineSpecialist": ("out_of_scope", "", "random hand check: narrow specialty"),
    "paediatricCardiacCentre": ("too_general", "cath_lab_angioplasty;cardiac_surgery", "consistency with pediatricCardiacCentre"),
    "paediatricOrthopaedic": ("too_general", "orthopaedic_trauma_surgery", "consistency with pediatricOrthopaedic"),
    "PaediatricOrthopedics": ("too_general", "orthopaedic_trauma_surgery", "consistency with pediatricOrthopedic"),
    "Traumatology": ("trauma_care", "", "consistency with traumatology"),
    "independentDivisions": ("not_a_service", "", "v1.1: the old unanchored 'dent' rule had caught it; not a clinical value"),
    # v1.1: multi-service values (review issue 23). service_id may be a ';' list of service ids.
    "NICU/ PICU/ Neonatology": ("nicu;picu", "", "names both units"),
    "addictionPsychiatry": ("de_addiction;psychiatric_care", "", "names both"),
    "psychiatryAndDeaddictionTherapy": ("psychiatric_care;de_addiction", "", "names both"),
    "neuropsychiatryAndDrugDeAddiction": ("psychiatric_care;de_addiction", "", "names both"),
    "neurocriticalCareNeurosurgery": ("neurosurgery;icu", "", "names both"),
    "neuroCriticalCareNeurosurgery": ("neurosurgery;icu", "", "names both"),
    "pediatricNeurosurgeryAndTrauma": ("neurosurgery;trauma_care", "", "names both"),
    "traumaCriticalCare": ("trauma_care;icu", "", "names both"),
    "polytraumaAndFracture": ("trauma_care;orthopaedic_trauma_surgery", "", "names both"),
}
# v1.1: trauma_emergency was split (review issue 2). Cached LLM answers that used the old id are re-pointed here.
TRAUMA_WORDS = r"trauma|accident|injur|polytrauma"


def remap_old_label(label: str, normalized: str) -> str:
    if label != "trauma_emergency":
        return label
    return "trauma_care" if re.search(TRAUMA_WORDS, normalized) else "emergency_24x7"


def split_ids(service_id: str) -> list[str]:
    return [x for x in str(service_id).split(";") if x]


def services() -> dict[str, str]:
    """Taxonomy services plus the candidates (kept as labels so their specialty values stay findable)."""
    s = json.load(open(os.path.join(D, "services.json")))
    svc = [v for c in s["categories"] for v in c["services"]] + s.get("candidates_not_included", [])
    return {v["id"]: v["definition"] for v in svc}


def distinct_values() -> pd.DataFrame:
    q = f"""
    with x as (select unique_id, unnest(from_json(specialties, '["VARCHAR"]')) s from read_parquet('{RAW}') where json_valid(specialties)),
    u as (select unique_id from read_parquet('{USABLE}'))
    select s as specialty,
           count(distinct case when x.unique_id in (select unique_id from u) then x.unique_id end) n_facilities,
           count(distinct x.unique_id) n_facilities_all_rows
    from x where s is not null group by s order by n_facilities desc, s"""
    return duckdb.sql(q).df()


def label_rules(v: pd.DataFrame) -> pd.DataFrame:
    v = v.copy()
    v["normalized"] = v.specialty.map(R.normalize)
    hits = v.normalized.map(R.apply_rules)
    v["service_id"] = hits.map(lambda h: h[0] if h else None)
    v["confidence"] = hits.map(lambda h: h[1] if h else None)
    v["prereq_for"] = hits.map(lambda h: h[2] if h else "")
    v["basis"] = hits.map(lambda h: f"rule {h[3]}" if h else "")
    v["method"] = hits.map(lambda h: "rule" if h else None)
    empty = v.normalized == ""
    v.loc[empty, ["service_id", "confidence", "method", "basis"]] = ["not_a_service", 1.0, "rule", "empty or whitespace"]
    return v


def label_fuzzy(v: pd.DataFrame) -> pd.DataFrame:
    v = v.copy()
    anchors = v[v.method == "rule"].assign(key=lambda d: d.normalized.str.replace(" ", "")).drop_duplicates("key").set_index("key")
    names = list(anchors.index)
    todo = v.method.isna()
    for i in v.index[todo]:
        m = process.extractOne(v.at[i, "normalized"].replace(" ", ""), names, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN)
        if m:
            a = anchors.loc[m[0]]
            v.loc[i, ["service_id", "confidence", "prereq_for", "method", "basis"]] = [
                a.service_id, round(a.confidence * m[1] / 100, 3), a.prereq_for, "fuzzy", f"~ '{m[0]}' ({m[1]:.0f})"]
    return v


def prompt(values: list[str], svc: dict[str, str]) -> str:
    lines = "\n".join(f"- {k}: {d}" for k, d in svc.items())
    items = "\n".join(f"{i}. {s}" for i, s in enumerate(values))
    return (
        "You label entries of a 'specialties' field scraped from Indian health facility web pages. For each numbered entry pick ONE label.\n"
        "Use a service id only when the entry itself names that service, its dedicated unit, or its core procedure (a job title counts as its specialty, "
        "e.g. 'cardiac surgeon' -> cardiac_surgery).\nService ids:\n" + lines + "\n"
        "Other labels:\n- too_general: a broad specialty that contains some of the services above but does not by itself show any "
        "(e.g. internal medicine, cardiology, nephrology, neurology, general surgery, pediatrics, obstetrics and gynecology, radiology, oncology).\n"
        "- out_of_scope: a real clinical specialty, procedure, condition or test that none of the services above cover "
        "(e.g. dermatology, dentistry, ENT, IVF, physiotherapy, gastroenterology, a named disease like diabetes).\n"
        "- not_a_service: not a clinical service at all (academic subject, administration, research, generic words, unreadable text).\n"
        "confidence: your probability (0 to 1) that the label is right.\nEntries:\n" + items
    )


def schema(labels: list[str]) -> str:
    s = {"type": "json_schema", "json_schema": {"name": "labels", "strict": True, "schema": {
        "type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
            "type": "object", "required": ["i", "label", "confidence"],
            "properties": {"i": {"type": "integer"}, "label": {"type": "string", "enum": labels}, "confidence": {"type": "number"}}}}}}}}
    return json.dumps(s)


def run_statement(sql: str) -> list[list]:
    """Submit one SQL statement, poll until done, return data_array rows."""
    env = {**os.environ, "DATABRICKS_CONFIG_PROFILE": "vf"}
    body = json.dumps({"warehouse_id": WAREHOUSE, "statement": sql, "wait_timeout": "30s", "on_wait_timeout": "CONTINUE",
                       "disposition": "INLINE", "format": "JSON_ARRAY"})
    r = json.loads(subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements", "--json", body],
                                  capture_output=True, text=True, check=True, env=env).stdout)
    sid = r["statement_id"]
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(10)
        r = json.loads(subprocess.run(["databricks", "api", "get", f"/api/2.0/sql/statements/{sid}"],
                                      capture_output=True, text=True, check=True, env=env).stdout)
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"statement {sid}: {r['status']}")
    rows = r.get("result", {}).get("data_array", []) or []
    if r.get("manifest", {}).get("total_chunk_count", 1) > 1:
        raise RuntimeError("result spans several chunks; lower the batch size")
    return rows


def label_llm(v: pd.DataFrame, svc: dict[str, str]) -> pd.DataFrame:
    v = v.copy()
    todo = list(v.loc[v.method.isna(), "specialty"])
    cache = json.load(open(LLM_CACHE)) if os.path.exists(LLM_CACHE) else {"model": MODEL, "statements": 0, "labels": {}}
    need = [s for s in todo if s not in cache["labels"] and s not in OVERRIDES]  # overrides need no LLM answer
    labels = list(svc) + ["too_general", "out_of_scope", "not_a_service"]
    if need:
        print(f"{len(need)} values not in the LLM cache: {need[:20]}")
        if cache["statements"] >= MAX_STATEMENTS:
            raise RuntimeError("ai_query statement cap reached")
        chunks = [need[i:i + CHUNK] for i in range(0, len(need), CHUNK)]
        vals = ", ".join(f"({k}, CAST(unbase64('{base64.b64encode(prompt(c, svc).encode()).decode()}') AS STRING))"
                         for k, c in enumerate(chunks))
        fmt = schema(labels).replace("'", "''")
        sql = (f"SELECT k, r.result, r.errorMessage FROM (SELECT k, ai_query('{MODEL}', p, responseFormat => '{fmt}', "
               f"modelParameters => named_struct('temperature', 0.0, 'max_tokens', 6000), failOnError => false) r "
               f"FROM VALUES {vals} AS t(k, p))")
        rows = run_statement(sql)
        cache["statements"] += 1
        for k, res, err in rows:
            chunk = chunks[int(k)]
            if err or not res:
                print("chunk", k, "error:", err)
                continue
            for it in json.loads(res)["items"]:
                i = it["i"]
                if 0 <= i < len(chunk) and it["label"] in labels:
                    cache["labels"][chunk[i]] = {"label": it["label"], "confidence": float(it["confidence"])}
        json.dump(cache, open(LLM_CACHE, "w"), indent=1, ensure_ascii=False)
    for i in v.index[v.method.isna()]:
        got = cache["labels"].get(v.at[i, "specialty"])
        if got:
            v.loc[i, ["service_id", "confidence", "method", "basis"]] = [remap_old_label(got["label"], v.at[i, "normalized"]),
                                                                        round(min(max(got["confidence"], 0), 1), 3), "llm", MODEL]
    return v


def apply_overrides(v: pd.DataFrame) -> pd.DataFrame:
    v = v.copy()
    missing = set(OVERRIDES) - set(v.specialty)
    assert not missing, missing
    for i in v.index[v.specialty.isin(OVERRIDES)]:
        lab, pre, why = OVERRIDES[v.at[i, "specialty"]]
        v.loc[i, ["service_id", "prereq_for", "method", "confidence", "basis"]] = [lab, pre, "manual", 0.9, f"was {v.at[i, 'method']} {v.at[i, 'service_id']}: {why}"]
    return v


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    svc = services()
    v = apply_overrides(label_llm(label_fuzzy(label_rules(distinct_values())), svc))
    bad = {x for sid in v.service_id.dropna() for x in split_ids(sid)} - set(svc) - {"too_general", "out_of_scope", "not_a_service"}
    bad |= {x for pre in v.prereq_for.fillna("") for x in split_ids(pre)} - set(svc)
    assert not bad, bad
    cols = ["specialty", "normalized", "service_id", "method", "confidence", "n_facilities", "n_facilities_all_rows", "prereq_for", "basis"]
    v[cols].to_csv(os.path.join(D, "specialty_map.csv"), index=False)
    st = {"distinct_values": len(v), "unlabelled": int(v.service_id.isna().sum()),
          "by_method": v.method.value_counts(dropna=False).to_dict(),
          "by_label_kind": v.service_id.map(lambda x: x if x in ("too_general", "out_of_scope", "not_a_service") else ("service" if x else "none")).value_counts().to_dict(),
          "facility_weighted_by_method": v.groupby("method", dropna=False).n_facilities.sum().to_dict(),
          "llm_statements_used": json.load(open(LLM_CACHE))["statements"] if os.path.exists(LLM_CACHE) else 0}
    json.dump(st, open(os.path.join(OUT, "specialty_map_stats.json"), "w"), indent=1, default=int)
    print(json.dumps(st, indent=1, default=int))


if __name__ == "__main__":
    main()

"""LLM baselines through ai_query (Statement Execution API, read-only SELECT).

Two jobs, both with databricks-meta-llama-3-3-70b-instruct and strict JSON:
  sent : the 224 hand-labelled sentences -> {about, offers_service, other_entity}  (role-classifier check, spec 4.8)
  pair : B3 LLM judge on gold pairs (v2 test, v1, labelled v2 dev) + the two known contaminated records
         -> {offers, confidence, quote}, prompt = record name, city, state and its service and prerequisite
         sentences, truncated to 3,000 characters (spec section 8). No web-check content enters any prompt.
Budget for this layer: at most 6 statements and 400 rows. Every call is cached by sha256(model + prompt) in
llm_cache.parquet; a cached prompt is never sent again.
Run: .venv/bin/python llm.py sent|pair [--dry]
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time

import pandas as pd

from common import HERE, INPUTS, LEX_KEY, split_cell
from gold import load_gold

MODEL = "databricks-meta-llama-3-3-70b-instruct"
WAREHOUSE = "6a2f5637720a2c17"
CACHE = HERE / "llm_cache.parquet"
LOG = HERE / "llm_statements.log"
MAX_STATEMENTS, MAX_ROWS = 6, 400
SVC_TEXT = {"dialysis": "dialysis", "emergency_csection": "emergency caesarean section (C-section)",
            "nicu": "neonatal intensive care (NICU)", "cardiac_surgery": "cardiac surgery", "mri": "MRI scanning",
            "burn_care": "burn care", "trauma_emergency": "trauma and emergency care"}
CONTAMINATED = [("3ac5ae50-9ce2-4de3-a13c-d95a4ef218ee", "dialysis"), ("b8a5401f-42f1-422a-8cd9-686a15b4cb76", "dialysis")]

SCHEMA_SENT = {"type": "json_schema", "json_schema": {"name": "sent", "strict": True, "schema": {
    "type": "object", "properties": {
        "about": {"type": "string", "enum": ["this_facility", "other_facility", "unclear"]},
        "offers_service": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "other_entity": {"type": ["string", "null"]}},
    "required": ["about", "offers_service", "other_entity"]}}}
SCHEMA_PAIR = {"type": "json_schema", "json_schema": {"name": "judge", "strict": True, "schema": {
    "type": "object", "properties": {
        "offers": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "confidence": {"type": "number"},
        "quote": {"type": ["string", "null"]}},
    "required": ["offers", "confidence", "quote"]}}}


def key(prompt: str) -> str:
    return hashlib.sha256(f"{MODEL}|{prompt}".encode()).hexdigest()


def sent_prompts() -> pd.DataFrame:
    s = pd.read_csv(HERE / "sentence_sample.csv")
    p = [("A sentence was extracted from a web listing about a health facility. Such listings often mix in text "
          "about other hospitals, other branches or other towns.\n"
          f"Facility: {r.name} (type: {r.facilityTypeId}), {r.address_city}, {r.address_stateOrRegion}.\n"
          f"Service: {SVC_TEXT[r.service]}.\nSentence: \"{r.text}\"\n"
          "Answer in JSON. about: is the sentence about this facility (this_facility), about a different hospital, "
          "branch or place (other_facility), or impossible to tell (unclear)? offers_service: does the sentence say "
          "the service is currently provided by the facility it describes (yes, no, unclear)? other_entity: the "
          "other facility or place it names, or null.") for r in s.itertuples()]
    return pd.DataFrame({"id": s.sid, "kind": "sent", "prompt": p})


def pair_prompts() -> pd.DataFrame:
    g = load_gold()
    sel = g[(g.version == "v2") & (g.split == "test") | (g.version == "v1") | (g.version == "v2") & (g.split == "dev") & g.label.notna()]
    pairs = list(dict.fromkeys(list(zip(sel.unique_id, sel.service)) + CONTAMINATED))
    c = pd.read_parquet(INPUTS["claims"], columns=["unique_id", "field", "idx", "text", "services", "prereqs"])
    c = c[c.unique_id.isin({u for u, _ in pairs})]
    rs = pd.read_parquet(INPUTS["record_scores"], columns=["unique_id", "name", "address_city", "address_stateOrRegion"]).set_index("unique_id")
    order = {"procedure": 0, "capability": 1, "equipment": 2, "description": 3}
    rows = []
    for u, s in pairs:
        lk = LEX_KEY[s]
        cc = c[c.unique_id == u]
        hit = cc[cc.services.map(lambda x: lk in split_cell(x)) | cc.prereqs.map(lambda x: any(p.startswith(lk + ".") for p in split_cell(x)))]
        hit = hit.assign(o=hit.field.map(order)).sort_values(["o", "idx"])
        body = "\n".join(f"- {t}" for t in hit.text)[:3000] or "(no sentences mention this service)"
        r = rs.loc[u]
        prompt = (f"From this facility record, decide whether the facility offers {SVC_TEXT[s]}. Use only the record text.\n"
                  f"Name: {r['name']}. City: {r.address_city}. State: {r.address_stateOrRegion}.\n"
                  f"Record sentences about the service and its prerequisites:\n{body}\n"
                  "Answer in JSON: offers (yes, no or unclear), confidence (0 to 1), quote (the exact supporting sentence, or null).")
        rows.append(dict(id=f"{u}|{s}", kind="pair", prompt=prompt))
    return pd.DataFrame(rows)


def run_sql(sql: str) -> dict:
    body = json.dumps({"warehouse_id": WAREHOUSE, "statement": sql, "wait_timeout": "50s",
                       "disposition": "INLINE", "format": "JSON_ARRAY", "on_wait_timeout": "CONTINUE"})
    env = {**os.environ, "DATABRICKS_CONFIG_PROFILE": "vf"}
    r = json.loads(subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements", "--json", body],
                                  capture_output=True, text=True, env=env).stdout or "{}")
    if "statement_id" not in r:
        raise RuntimeError(f"submit failed: {str(r)[:500]}")
    sid = r["statement_id"]
    for _ in range(120):
        if r["status"]["state"] not in ("PENDING", "RUNNING"):
            return r
        time.sleep(10)
        r = json.loads(subprocess.run(["databricks", "api", "get", f"/api/2.0/sql/statements/{sid}"],
                                      capture_output=True, text=True, env=env, check=True).stdout)
    raise RuntimeError(f"statement {sid} still running after 20 min")


def statements_used() -> int:
    return sum(1 for ln in open(LOG) if '"kind"' in ln) if LOG.exists() else 0


def main(kind: str, dry: bool, batch: int = 120):
    todo = sent_prompts() if kind == "sent" else pair_prompts()
    todo["key"] = todo.prompt.map(key)
    cache = pd.read_parquet(CACHE) if CACHE.exists() else pd.DataFrame(columns=["key", "id", "kind", "response", "error"])
    todo = todo[~todo.key.isin(cache.key)]
    rows_used = len(cache)
    print(f"{len(todo)} prompts to send; rows used {rows_used}/{MAX_ROWS}; statements used {statements_used()}/{MAX_STATEMENTS}")
    if dry or todo.empty:
        return
    if rows_used + len(todo) > MAX_ROWS:
        raise SystemExit("row budget exceeded")
    schema = json.dumps(SCHEMA_SENT if kind == "sent" else SCHEMA_PAIR).replace("'", "\\'")
    for i in range(0, len(todo), batch):
        if statements_used() >= MAX_STATEMENTS:
            raise SystemExit("statement budget exhausted")
        b = todo.iloc[i:i + batch]
        vals = ",\n".join(f"('{k}', '{base64.b64encode(p.encode()).decode()}')" for k, p in zip(b.key, b.prompt))
        sql = (f"SELECT k, to_json(ai_query('{MODEL}', cast(unbase64(p) AS STRING), responseFormat => '{schema}', "
               f"failOnError => false)) AS r FROM VALUES {vals} AS t(k, p)")
        with open(LOG, "a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "rows": len(b)}) + "\n")
        res = run_sql(sql)
        if res["status"]["state"] != "SUCCEEDED":
            raise SystemExit(f"statement failed: {res['status']}")
        out = []
        for k, r in res.get("result", {}).get("data_array", []):
            d = json.loads(r) if r else {}
            out.append(dict(key=k, id=b.set_index("key").at[k, "id"], kind=kind, response=d.get("result"), error=d.get("errorMessage")))
        cache = pd.concat([cache, pd.DataFrame(out)], ignore_index=True)
        cache.to_parquet(CACHE, index=False)
        print(f"batch {i // batch + 1}: {len(out)} rows, errors {sum(1 for o in out if o['error'])}")


if __name__ == "__main__":
    main(sys.argv[1], "--dry" in sys.argv, batch=120 if sys.argv[1] == "sent" else 130)

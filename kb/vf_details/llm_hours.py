"""Read ambiguous hour sentences with ai_query (llama-3-3-70b, strict JSON schema) and keep only verifiable outputs.

Input: out/hour_candidates.parquet (from extract.py). Output: out/llm_hours.parquet, out/llm_hours_raw.json.
A row is kept only when (1) the returned quote is an exact substring of the source sentence, (2) the model says
the sentence states regular hours, and (3) every returned open/close hour (and non-zero minute) appears as a
number in that quote, read as a 12- or 24-hour clock. The task cap is 4 SQL statements; out/llm_statements.json
counts every statement sent, including failed ones.
Run: .venv/bin/python llm_hours.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time

import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
WAREHOUSE = "6a2f5637720a2c17"
MODEL = "databricks-meta-llama-3-3-70b-instruct"
MAX_STATEMENTS = 4
COUNTER = os.path.join(OUT, "llm_statements.json")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SCOPES = ["opd", "doctor_session", "lab", "pharmacy", "dialysis", "emergency", "visiting", "general"]

PROMPT = ("You read one sentence from an Indian health facility record. Decide whether it states the facility's regular operating "
          "hours (not a one-off dated event, not a validity period of a certificate). If it does, list each schedule entry with the days "
          "(three-letter lowercase: mon tue wed thu fri sat sun) and open and close times as 24-hour HH:MM. Indian clinics often write "
          "12-hour times without am/pm, so 10:00-07:00 means 10:00 to 19:00; resolve such times by what a clinic would plausibly keep. "
          "Use an empty days list if no days are given. scope is one of: " + ", ".join(SCOPES) + ". quote must be copied character for "
          "character from the sentence and must contain all the times. Sentence: ")
SCHEMA = {"type": "json_schema", "json_schema": {"name": "hours", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["is_operating_hours", "scope", "entries", "quote"],
    "properties": {
        "is_operating_hours": {"type": "boolean"},
        "scope": {"type": "string", "enum": SCOPES},
        "quote": {"type": "string"},
        "entries": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["days", "open", "close"],
                                               "properties": {"days": {"type": "array", "items": {"type": "string", "enum": DAYS}},
                                                              "open": {"type": "string"}, "close": {"type": "string"}}}}}}}}


def sql_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def bump_counter() -> int:
    n = json.load(open(COUNTER))["statements"] if os.path.exists(COUNTER) else 0
    if n >= MAX_STATEMENTS:
        raise SystemExit(f"statement cap reached ({n}/{MAX_STATEMENTS})")
    json.dump({"statements": n + 1}, open(COUNTER, "w"))
    return n + 1


def run_sql(sql: str) -> list[list]:
    """Submit one statement, poll until done, return data rows. GET polling is a read of the same statement."""
    env = {**os.environ, "DATABRICKS_CONFIG_PROFILE": "vf"}
    body = json.dumps({"warehouse_id": WAREHOUSE, "statement": sql, "wait_timeout": "50s", "disposition": "INLINE", "format": "JSON_ARRAY"})
    r = json.loads(subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements", "--json", body], env=env, capture_output=True, text=True, check=True).stdout)
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(10)
        r = json.loads(subprocess.run(["databricks", "api", "get", f"/api/2.0/sql/statements/{r['statement_id']}"], env=env, capture_output=True, text=True, check=True).stdout)
    if r["status"]["state"] != "SUCCEEDED":
        raise SystemExit(f"{r['status']['state']}: {r['status'].get('error', {}).get('message')}")
    assert r["manifest"].get("total_chunk_count", 1) == 1, "result chunked; lower the batch size"
    return r.get("result", {}).get("data_array", [])


def time_in_quote(t: str, quote: str) -> bool:
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", t)
    if not m:
        return False
    h, mi = int(m.group(1)), int(m.group(2))
    nums = {int(x) for x in re.findall(r"\d{1,2}", quote)}
    return (h in nums or (h % 12 or 12) in nums) and (mi == 0 or f"{mi:02d}" in quote)


def verify(text: str, out: dict) -> tuple[bool, str]:
    if out.get("quote", "") == "" or out["quote"] not in text:
        return False, "quote_not_in_source"
    if not out.get("is_operating_hours"):
        return False, "not_operating_hours"
    # a "Sunday closed" entry comes back as 00:00-00:00 or empty times: drop it, it is not an opening
    out["entries"] = [e for e in out.get("entries", []) if e["open"] not in ("", e["close"]) or not re.search(r"closed|holiday", text, re.I)]
    if not out["entries"]:
        return False, "no_entries"
    for e in out["entries"]:
        if not (time_in_quote(e["open"], out["quote"]) and time_in_quote(e["close"], out["quote"])):
            return False, "time_not_in_quote"
        d = [x for x in DAYS if x in e["days"]]
        if d and not all(re.search(r"\b" + x, text, re.I) for x in (d[0], d[-1])) and not (len(d) == 7 and re.search(r"daily|all days|7 days|every ?day|all week", text, re.I)):
            return False, "days_not_in_source"
        o, c = (int(t[:2]) * 60 + int(t[3:]) for t in (e["open"], e["close"]))
        explicit = bool(re.search(r"\d\s*(am|pm|a\.m|p\.m)", out["quote"], re.I))
        overnight_ok = explicit and o >= 12 * 60 and c <= 10 * 60  # "2 PM to 8 AM" lab shift
        if o == c or o < 5 * 60 or (c < o and not overnight_ok):
            return False, "implausible_schedule"  # the model left a 12-hour reading unresolved
    return True, "kept"


def sched_text(entries: list[dict]) -> str:
    parts = []
    for e in entries:
        d = [x for x in DAYS if x in e["days"]]
        ds = "days?" if not d else (f"{d[0]}-{d[-1]}" if len(d) > 2 and d == DAYS[DAYS.index(d[0]):DAYS.index(d[0]) + len(d)] else ",".join(d))
        parts.append(f"{ds} {e['open']}-{e['close']}")
    return "; ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reverify", action="store_true", help="re-apply verify() to saved raw outputs; sends no statement")
    a = ap.parse_args()
    if a.reverify:
        raw = json.load(open(os.path.join(OUT, "llm_hours_raw.json")))
        rows = [(r["claim_id"], json.dumps(r["output"])) for r in raw]
        return write(rows, {r["claim_id"]: r["text"] for r in raw}, save=True)
    hc = pd.read_parquet(os.path.join(OUT, "hour_candidates.parquet")).drop_duplicates("claim_id")
    if a.limit:
        hc = hc.head(a.limit)
    values = ",\n".join(f"({sql_str(r.claim_id)}, {sql_str(r.text)})" for r in hc.itertuples())
    sql = (f"SELECT claim_id, ai_query('{MODEL}', concat({sql_str(PROMPT)}, text), responseFormat => {sql_str(json.dumps(SCHEMA))}) AS out "
           f"FROM VALUES {values} AS t(claim_id, text)")
    n = bump_counter()
    print(f"statement {n}/{MAX_STATEMENTS}: {len(hc)} sentences")
    write(run_sql(sql), dict(zip(hc.claim_id, hc.text)), save=not a.limit)


def write(rows: list, text: dict[str, str], save: bool) -> None:
    raw, keep = [], []
    for cid, o in rows:
        try:
            out = json.loads(o)
            ok, why = verify(text[cid], out)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            out, ok, why = {"raw": o}, False, f"bad_json:{type(e).__name__}"
        raw.append({"claim_id": cid, "text": text[cid], "output": out, "verdict": why})
        keep.append({"claim_id": cid, "keep": ok, "verdict": why, "scope": out.get("scope"), "quote": out.get("quote"),
                     "schedule_text": sched_text(out["entries"]) if ok else None, "entries_json": json.dumps(out.get("entries"))})
    json.dump(raw, open(os.path.join(OUT, "llm_hours_raw.json"), "w"), indent=1)
    k = pd.DataFrame(keep)
    if save:
        k.to_parquet(os.path.join(OUT, "llm_hours.parquet"), index=False)
    print(k.verdict.value_counts().to_dict())


if __name__ == "__main__":
    main()

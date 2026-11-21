"""Read ambiguous hour lines from facility websites with ai_query (llama-3-3-70b, strict JSON) and keep only verifiable output.

Input: out/hour_candidates.parquet (lines with clock times and an hours word that the deterministic parser could not
read cleanly, from build_web_evidence.py). Output: out/llm_hours.parquet and out/llm_hours_raw.json.
The JSON schema and the keep rules are the VF-details ones (kb/vf_details/llm_hours.py, imported): the quote must be an
exact substring of the line, the model must say the line gives regular hours, every returned hour must appear in the
quote, returned days must appear in the line, and the schedule must be plausible. The task cap is 6 SQL statements;
out/llm_statements.json counts every statement sent, failed ones included.
Run: .venv/bin/python web_llm_hours.py --limit 3   (test), then .venv/bin/python web_llm_hours.py --batches 2
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os

import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
_spec = importlib.util.spec_from_file_location("vf_llm", "/Users/karthikvattem/projects/datathon/kb/vf_details/llm_hours.py")
VL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VL)
MAX_STATEMENTS = 6
COUNTER = os.path.join(OUT, "llm_statements.json")
PROMPT = VL.PROMPT.replace("one sentence from an Indian health facility record", "one line of text from an Indian health facility's website")


def bump_counter() -> int:
    n = json.load(open(COUNTER))["statements"] if os.path.exists(COUNTER) else 0
    if n >= MAX_STATEMENTS:
        raise SystemExit(f"statement cap reached ({n}/{MAX_STATEMENTS})")
    json.dump({"statements": n + 1}, open(COUNTER, "w"))
    return n + 1


def run_batch(hc: pd.DataFrame) -> list:
    values = ",\n".join(f"({VL.sql_str(r.cand_key)}, {VL.sql_str(r.text)})" for r in hc.itertuples())
    sql = (f"SELECT k, ai_query('{VL.MODEL}', concat({VL.sql_str(PROMPT)}, text), responseFormat => {VL.sql_str(json.dumps(VL.SCHEMA))}) AS out "
           f"FROM VALUES {values} AS t(k, text)")
    n = bump_counter()
    print(f"statement {n}/{MAX_STATEMENTS}: {len(hc)} lines")
    return VL.run_sql(sql)


def judge(rows: list, text: dict[str, str]) -> pd.DataFrame:
    raw, keep = [], []
    for k, o in rows:
        try:
            out = json.loads(o)
            ok, why = VL.verify(text[k], out)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            out, ok, why = {"raw": o}, False, f"bad_json:{type(e).__name__}"
        ok = ok and out["quote"] in text[k]  # asserted again below; verify() already requires it
        raw.append({"cand_key": k, "text": text[k], "output": out, "verdict": why})
        keep.append({"cand_key": k, "keep": ok, "verdict": why, "scope": out.get("scope"), "quote": out.get("quote"),
                     "schedule_text": VL.sched_text(out["entries"]) if ok else None, "entries_json": json.dumps(out.get("entries"))})
    k = pd.DataFrame(keep)
    for r in k[k.keep].itertuples():
        assert r.quote in text[r.cand_key]
    return k, raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="test on the first N lines; nothing is saved")
    ap.add_argument("--batches", type=int, default=2)
    a = ap.parse_args()
    hc = pd.read_parquet(os.path.join(OUT, "hour_candidates.parquet")).drop_duplicates("text").reset_index(drop=True)
    text = dict(zip(hc.cand_key, hc.text))
    if a.limit:
        k, _ = judge(run_batch(hc.head(a.limit)), text)
        print(k.to_string())
        return
    rows = []
    for i in range(a.batches):
        rows += run_batch(hc.iloc[i::a.batches])
    k, raw = judge(rows, text)
    json.dump(raw, open(os.path.join(OUT, "llm_hours_raw.json"), "w"), indent=1)
    k.to_parquet(os.path.join(OUT, "llm_hours.parquet"), index=False)
    print(f"{len(hc)} candidates, {len(k)} answers:", k.verdict.value_counts().to_dict())


if __name__ == "__main__":
    main()

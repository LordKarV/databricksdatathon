"""Baseline B3: LLM judge over gold pairs only (v1 36 + v2 140 = 176 rows, cap 200), in 2 SQL statements (cap 3).

Model databricks-meta-llama-3-3-70b-instruct, strict JSON {offers: yes|no|unclear, confidence: 0..1, quote}. The prompt
holds only the record's own text: name, city, state, specialties, and its sentences that mention the service or one
of its prerequisites (rejected sentences included, since an LLM sees the raw record), truncated to 3,000 characters.
Nothing from the web checks. Cached in llm_judge.parquet keyed by sha256 of the prompt; a re-run sends only misses.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python llm_judge.py [--dry-run]
"""
import base64
import json
import subprocess
import sys
import time

import pandas as pd

from fcommon import HERE, ROOT, SNAP, SVC, SVC_INV, sha256_str

MODEL = "databricks-meta-llama-3-3-70b-instruct"
WAREHOUSE = "6a2f5637720a2c17"
MAX_ROWS, MAX_STATEMENTS = 200, 3
DESC = {"dialysis": "dialysis (haemodialysis or peritoneal dialysis)", "emergency_csection": "emergency caesarean section (C-section)",
        "nicu": "a neonatal intensive care unit (NICU)", "cardiac_surgery": "cardiac surgery (open-heart, CABG or valve surgery)",
        "mri": "MRI scanning", "burn_care": "burn care (a burns unit or burn treatment)",
        "trauma_emergency": "emergency and trauma care (a 24-hour emergency department or casualty)"}
SCHEMA = json.dumps({"type": "json_schema", "json_schema": {"name": "judge", "strict": True, "schema": {
    "type": "object", "properties": {"offers": {"type": "string", "enum": ["yes", "no", "unclear"]},
                                     "confidence": {"type": "number"}, "quote": {"type": ["string", "null"]}},
    "required": ["offers", "confidence", "quote"]}}})


def gold_pairs():
    sp = json.load(open(ROOT / "model/gold/splits.json"))["pairs"]  # pair ids and keys only, no labels
    return pd.DataFrame(sp)[["pair_id", "unique_id", "service", "version", "split"]]


def prompts(pairs):
    c = pd.read_parquet(SNAP / "claims.parquet", columns=["unique_id", "field", "idx", "text", "services", "prereqs"])
    c = c[c.unique_id.isin(set(pairs.unique_id))]
    sp = pd.read_parquet(SNAP / "specialties.parquet")
    sp = sp[sp.unique_id.isin(set(pairs.unique_id))].groupby("unique_id").spec.agg(lambda x: ", ".join(sorted(x)))
    rec = pd.read_parquet(SNAP / "facility_location.parquet", columns=["unique_id", "name", "address_city", "address_stateOrRegion"]).set_index("unique_id")
    out = []
    for r in pairs.itertuples():
        key = SVC[r.service]
        g = c[c.unique_id == r.unique_id]
        hit = g[g.services.str.split("|").map(lambda l: key in l) | g.prereqs.str.contains(rf"(?:^|\|){key}\.", regex=True)]
        lines = "\n".join(f"- [{f}] {t}" for f, t in zip(hit.field, hit.text)) or "- (no sentence mentions the service or its prerequisites)"
        m = rec.loc[r.unique_id]
        body = (f"Name: {m['name']}\nCity: {m.address_city}\nState: {m.address_stateOrRegion}\n"
                f"Specialties: {sp.get(r.unique_id, '')[:600]}\nSentences from the record:\n{lines}")
        p = (f"You are checking one health facility record from India. Using only the record text below, decide whether "
             f"this facility itself offers {DESC[r.service]}. Answer yes, no or unclear, give your confidence from 0 to 1, "
             f"and quote the single most relevant sentence from the record (or null).\n\n{body}")[:3000]
        out.append(dict(pair_id=r.pair_id, unique_id=r.unique_id, service=r.service, prompt=p, prompt_sha256=sha256_str(p)))
    return pd.DataFrame(out)


def run_sql(stmt):
    body = json.dumps({"warehouse_id": WAREHOUSE, "statement": stmt, "wait_timeout": "50s", "disposition": "INLINE", "format": "JSON_ARRAY"})
    r = json.loads(subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements", "--json", body, "-p", "vf"],
                                  capture_output=True, text=True, check=True).stdout)
    sid = r["statement_id"]
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(10)
        r = json.loads(subprocess.run(["databricks", "api", "get", f"/api/2.0/sql/statements/{sid}", "-p", "vf"],
                                      capture_output=True, text=True, check=True).stdout)
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"{r['status']['state']}: {r['status'].get('error')}")
    return r["result"].get("data_array", [])


def main(dry=False):
    pr = prompts(gold_pairs())
    assert len(pr) <= MAX_ROWS
    cache_p = HERE / "llm_judge.parquet"
    cache = pd.read_parquet(cache_p) if cache_p.exists() else pd.DataFrame(columns=["prompt_sha256", "raw"])
    todo = pr[~pr.prompt_sha256.isin(set(cache.prompt_sha256))].drop_duplicates("prompt_sha256")
    print(len(pr), "prompts,", len(todo), "not cached; example:\n", pr.prompt.iloc[0][:900])
    if dry or todo.empty:
        return
    chunks = [todo.iloc[i:i + 100] for i in range(0, len(todo), 100)]
    assert len(chunks) <= MAX_STATEMENTS
    got = []
    for ch in chunks:
        vals = ",\n".join(f"('{h}', '{base64.b64encode(p.encode()).decode()}')" for h, p in zip(ch.prompt_sha256, ch.prompt))
        stmt = (f"SELECT h, ai_query('{MODEL}', cast(unbase64(p) AS STRING), responseFormat => '{SCHEMA}') AS r "
                f"FROM VALUES {vals} AS t(h, p)")
        rows = run_sql(stmt)
        got += [dict(prompt_sha256=h, raw=r) for h, r in rows]
        print("statement done:", len(rows), "rows")
    cache = pd.concat([cache, pd.DataFrame(got)], ignore_index=True).drop_duplicates("prompt_sha256", keep="last")
    cache.to_parquet(cache_p, index=False)
    res = pr.merge(cache, on="prompt_sha256", how="left")

    def parse(x):
        try:
            d = json.loads(x)
            return d.get("offers"), float(d.get("confidence")), d.get("quote")
        except Exception:  # noqa: BLE001  malformed output is kept as missing, counted in the report
            return None, None, None

    res[["offers", "confidence", "quote"]] = pd.DataFrame([parse(x) for x in res.raw], index=res.index)
    res.drop(columns=["prompt"]).to_parquet(HERE / "llm_judge_pairs.parquet", index=False)
    print(res.offers.value_counts(dropna=False).to_dict())


if __name__ == "__main__":
    main(dry="--dry-run" in sys.argv)

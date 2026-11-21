"""Baseline B3 at query level: LLM judge on the top-10 B1 candidates per benchmark query (spec 8).

Prompt builder, model, JSON schema and SQL runner are reused from model/proto/fusion/llm_judge.py, so a candidate that
is also a gold pair hits the fusion cache (read-only) and costs no call. New answers are cached here in
llm_b3_cache.parquet keyed by sha256 of the prompt. Call budget: the spec caps B3 at 520 calls in total; fusion spent
176, so this pass refuses to send more than 520 - 176 = 344. One pass, batches of 100 rows per SQL statement.
Run: .venv/bin/python -B llm_b3.py [--dry-run]   (needs b1_candidates.parquet from decide.py)
"""
import base64
import json
import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "fusion"))
from llm_judge import MODEL, SCHEMA, prompts, run_sql  # noqa: E402

BUDGET = 520 - 176


def parse(x):
    try:
        d = json.loads(x)
        return d.get("offers"), float(d.get("confidence")), d.get("quote")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, None, None  # malformed output kept as missing and counted


def main(dry=False):
    c = pd.read_parquet(HERE / "b1_candidates.parquet")
    c["pair_id"] = c.query_id + ":" + c.unique_id
    pr = prompts(c)
    pr = pr.merge(c[["pair_id", "query_id", "rank"]], on="pair_id")
    fus = pd.read_parquet(HERE.parent / "fusion/llm_judge.parquet")
    mine_p = HERE / "llm_b3_cache.parquet"
    mine = pd.read_parquet(mine_p) if mine_p.exists() else pd.DataFrame(columns=["prompt_sha256", "raw"])
    cache = pd.concat([fus, mine]).drop_duplicates("prompt_sha256", keep="last")
    todo = pr[~pr.prompt_sha256.isin(set(cache.prompt_sha256))].drop_duplicates("prompt_sha256")
    stats = dict(candidates=len(pr), distinct_prompts=int(pr.prompt_sha256.nunique()), fusion_cache_hits=int(pr.prompt_sha256.isin(set(fus.prompt_sha256)).sum()),
                 to_send=len(todo), budget=BUDGET)
    print(stats)
    if len(todo) > BUDGET:
        raise SystemExit("over the call budget; nothing sent")
    if not dry and len(todo):
        got = []
        for i in range(0, len(todo), 100):
            ch = todo.iloc[i:i + 100]
            vals = ",\n".join(f"('{h}', '{base64.b64encode(p.encode()).decode()}')" for h, p in zip(ch.prompt_sha256, ch.prompt))
            rows = run_sql(f"SELECT h, ai_query('{MODEL}', cast(unbase64(p) AS STRING), responseFormat => '{SCHEMA}') AS r "
                           f"FROM VALUES {vals} AS t(h, p)")
            got += [dict(prompt_sha256=h, raw=r) for h, r in rows]
            print("statement done:", len(rows))
        mine = pd.concat([mine, pd.DataFrame(got)], ignore_index=True).drop_duplicates("prompt_sha256", keep="last")
        mine.to_parquet(mine_p, index=False)
        cache = pd.concat([fus, mine]).drop_duplicates("prompt_sha256", keep="last")
        stats["sent"] = len(got)
    if dry:
        return
    res = pr.merge(cache, on="prompt_sha256", how="left")
    res[["offers", "confidence", "quote"]] = pd.DataFrame([parse(x) for x in res.raw], index=res.index)
    res.drop(columns=["prompt"]).to_parquet(HERE / "llm_b3_pairs.parquet", index=False)
    stats["offers"] = res.offers.value_counts(dropna=False).to_dict()
    (HERE / "llm_b3_stats.json").write_text(json.dumps(stats, indent=1, default=str))
    print(stats)


if __name__ == "__main__":
    main(dry="--dry-run" in sys.argv)

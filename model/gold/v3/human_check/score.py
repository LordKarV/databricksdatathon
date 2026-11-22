"""Score the filled human spot-check sheet (issue #103): agreement between the person and the agent labeller.

    .venv-app/bin/python model/gold/v3/human_check/score.py [sheet.csv] [result.json] [--answers agent_answers.csv]

Defaults: sheet.csv, result.json and agent_answers.csv in this folder. The agent's verdicts are joined from
agent_answers.csv on pair_id. Reads Excel's "CSV UTF-8" (with a byte-order mark), skips blank rows, and accepts
verdicts in any case or with a space or hyphen ("Cannot tell"). Agreement is over rows the person could decide
(confirmed or contradicted); cannot_tell rows are counted apart. Wilson 95% intervals. Refuses a sheet with an
empty or unknown human_verdict, or whose pair_ids do not match agent_answers.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWED = {"confirmed", "contradicted", "cannot_tell"}


def wilson(k: int, n: int) -> dict:
    if not n:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    z, p = 1.96, k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"k": k, "n": n, "rate": round(p, 3), "ci95": [round(c - h, 3), round(c + h, 3)]}


def read_csv(path: Path) -> list[dict]:
    """Rows with stripped, lower-cased headers and stripped values; fully blank rows dropped."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]
    return [r for r in rows if any(r.values())]


def norm(verdict: str) -> str:
    return "_".join(verdict.lower().replace("-", " ").split())


def join(sheet: list[dict], answers: list[dict]) -> list[dict]:
    agent = {a["pair_id"]: a for a in answers}
    ids = [r.get("pair_id", "") for r in sheet]
    if dups := sorted(k for k, n in Counter(ids).items() if n > 1):
        raise SystemExit(f"pair_ids appear more than once: {dups}")
    if set(ids) != set(agent):
        raise SystemExit(f"sheet and answers differ: missing {sorted(set(agent) - set(ids))}, "
                         f"unknown {sorted(set(ids) - set(agent))}")
    rows = [{**r, "human_verdict": norm(r.get("human_verdict", "")), "agent_verdict": agent[r["pair_id"]]
             ["agent_verdict"], "split": agent[r["pair_id"]]["split"]} for r in sheet]
    if bad := [r.get("row") or r["pair_id"] for r in rows if r["human_verdict"] not in ALLOWED]:
        raise SystemExit(f"rows {bad}: human_verdict must be one of {sorted(ALLOWED)}")
    return rows


def score(rows: list[dict]) -> dict:
    told = [r for r in rows if r["human_verdict"] != "cannot_tell"]
    return {
        "rows": len(rows), "cannot_tell": len(rows) - len(told),
        "agreement": wilson(sum(r["human_verdict"] == r["agent_verdict"] for r in told), len(told)),
        "by_agent_verdict": {v: wilson(sum(r["human_verdict"] == v for r in told if r["agent_verdict"] == v),
                                       sum(r["agent_verdict"] == v for r in told))
                             for v in ("confirmed", "contradicted")},
        "confusion_agent_to_human": dict(Counter(f"{r['agent_verdict']}->{r['human_verdict']}" for r in rows)),
        "by_split": {s: wilson(sum(r["human_verdict"] == r["agent_verdict"] for r in told if r["split"] == s),
                               sum(r["split"] == s for r in told)) for s in ("dev", "test")},
        "note": "a person read the cited pages; agreement is with the agent's verdict, on decided pairs only",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Score the filled human spot-check sheet against the agent labels.")
    ap.add_argument("sheet", nargs="?", type=Path, default=HERE / "sheet.csv")
    ap.add_argument("out", nargs="?", type=Path, default=HERE / "result.json")
    ap.add_argument("--answers", type=Path, default=HERE / "agent_answers.csv")
    a = ap.parse_args()
    res = score(join(read_csv(a.sheet), read_csv(a.answers)))
    a.out.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

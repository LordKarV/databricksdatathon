"""Score the filled human spot-check sheet (issue #103): agreement between the person and the agent labeller.

    .venv-app/bin/python model/gold/v3/human_check/score.py [sheet.csv]     # writes result.json and prints it

Agreement is over rows the person could decide (confirmed or contradicted); cannot_tell rows are counted apart.
Wilson 95% intervals. Refuses a sheet with an empty or unknown human_verdict.
"""
from __future__ import annotations

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


def score(rows: list[dict]) -> dict:
    bad = [r["row"] for r in rows if r["human_verdict"].strip().lower() not in ALLOWED]
    if bad:
        raise SystemExit(f"rows {bad}: human_verdict must be one of {sorted(ALLOWED)}")
    for r in rows:
        r["human_verdict"] = r["human_verdict"].strip().lower()
    told = [r for r in rows if r["human_verdict"] != "cannot_tell"]
    out = {
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
    return out


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "sheet.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        res = score(list(csv.DictReader(fh)))
    (HERE / "result.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

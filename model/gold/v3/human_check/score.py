"""Score the filled human spot-check sheets (issue #103): agreement between the people and the agent labeller.

    .venv-app/bin/python model/gold/v3/human_check/score.py [filled/karthik.csv ...] [--out result.json]
        [--answers agent_answers.csv] [--partial]

Defaults: filled/karthik.csv, filled/aayan.csv and filled/aarav.csv, result.json and agent_answers.csv in this
folder. The person is the file name (a "sheet_" prefix is dropped). The agent's verdicts are joined from
agent_answers.csv on pair_id. Reads Excel's "CSV UTF-8" (with a byte-order mark), skips blank rows, and accepts
verdicts in any case or with a space or hyphen ("Cannot tell"). Agreement is over rows the person could decide
(confirmed or contradicted); cannot_tell rows are counted apart. Wilson 95% intervals. Refuses an empty or unknown
human_verdict, a pair_id that repeats or is not in agent_answers.csv, and (without --partial) missing pairs.
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
PEOPLE = ["karthik", "aayan", "aarav"]
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


def person(path: Path) -> str:
    return path.stem.lower().removeprefix("sheet_")


def join(sheets: dict[str, list[dict]], answers: list[dict], partial: bool = False) -> list[dict]:
    agent = {a["pair_id"]: a for a in answers}
    rows = [{**r, "person": p} for p, rs in sheets.items() for r in rs]
    ids = [r.get("pair_id", "") for r in rows]
    if dups := sorted(k for k, n in Counter(ids).items() if n > 1):
        raise SystemExit(f"pair_ids appear more than once: {dups}")
    if unknown := sorted(set(ids) - set(agent)):
        raise SystemExit(f"pair_ids not in the agent answers: {unknown}")
    if (missing := sorted(set(agent) - set(ids))) and not partial:
        raise SystemExit(f"pair_ids missing (pass --partial to score what is there): {missing}")
    rows = [{**r, "human_verdict": norm(r.get("human_verdict", "")), "agent_verdict": agent[r["pair_id"]]
             ["agent_verdict"], "split": agent[r["pair_id"]]["split"]} for r in rows]
    if bad := [f"{r['person']} row {r.get('row') or r['pair_id']}" for r in rows if r["human_verdict"] not in ALLOWED]:
        raise SystemExit(f"{bad}: human_verdict must be one of {sorted(ALLOWED)}")
    return rows


def agreement(rows: list[dict]) -> dict:
    told = [r for r in rows if r["human_verdict"] != "cannot_tell"]
    return {"rows": len(rows), "cannot_tell": len(rows) - len(told),
            "agreement": wilson(sum(r["human_verdict"] == r["agent_verdict"] for r in told), len(told))}


def score(rows: list[dict]) -> dict:
    told = [r for r in rows if r["human_verdict"] != "cannot_tell"]
    return {
        **agreement(rows),
        "by_person": {p: agreement([r for r in rows if r["person"] == p]) for p in dict.fromkeys(r["person"]
                                                                                                   for r in rows)},
        "by_agent_verdict": {v: wilson(sum(r["human_verdict"] == v for r in told if r["agent_verdict"] == v),
                                       sum(r["agent_verdict"] == v for r in told))
                             for v in ("confirmed", "contradicted")},
        "confusion_agent_to_human": dict(Counter(f"{r['agent_verdict']}->{r['human_verdict']}" for r in rows)),
        "by_split": {s: wilson(sum(r["human_verdict"] == r["agent_verdict"] for r in told if r["split"] == s),
                               sum(r["split"] == s for r in told)) for s in ("dev", "test")},
        "note": "people read the cited pages; agreement is with the agent's verdict, on decided pairs only",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Score the filled human spot-check sheets against the agent labels.")
    ap.add_argument("sheets", nargs="*", type=Path, default=[HERE / "filled" / f"{p}.csv" for p in PEOPLE])
    ap.add_argument("--out", type=Path, default=HERE / "result.json")
    ap.add_argument("--answers", type=Path, default=HERE / "agent_answers.csv")
    ap.add_argument("--partial", action="store_true", help="score even if some pairs have no filled sheet yet")
    a = ap.parse_args()
    if absent := [str(s) for s in a.sheets if not s.exists()]:
        raise SystemExit(f"no such file: {absent}")
    res = score(join({person(s): read_csv(s) for s in a.sheets}, read_csv(a.answers), a.partial))
    a.out.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

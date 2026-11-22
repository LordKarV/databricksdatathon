"""Draw the human spot-check sheet for gold v3 (issue #103): 25 decided pairs, about 15 confirmed / 10 contradicted.

    .venv-app/bin/python model/gold/v3/human_check/build_sheet.py      # writes sheet.csv (refuses to overwrite)

The draw is stable: seed SEED, pairs sorted by pair_id before sampling. Within each verdict the DEV / TEST split
is kept in proportion to the decided pairs in each split. Rows are shuffled so verdicts are not grouped.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
V3 = HERE.parent
ROOT = V3.parents[2]
SEED = 20261122
TAKE = {"confirmed": 15, "contradicted": 10}
OUT = HERE / "sheet.csv"
COLS = ["row", "pair_id", "split", "facility", "place", "service", "evidence_urls", "quote", "agent_verdict",
        "human_verdict", "note"]


def decided() -> list[dict]:
    names = {}
    for s in ("dev", "test"):
        for p in json.loads((V3 / f"{s}_sample.json").read_text()):
            if "name" in p:
                names[p["unique_id"]] = (p["name"], ", ".join(x for x in (p.get("city"), p.get("state")) if x))
    missing = {r["unique_id"] for s in ("dev", "test") for r in json.loads((V3 / f"{s}_labels.json").read_text())
               ["results"] if r["unique_id"] not in names}
    if missing:  # TEST samples carry ids only: names and places from derived/v1
        import pandas as pd
        f = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet",
                            columns=["unique_id", "name", "address_city", "state_final"])
        f = f[f.unique_id.isin(missing)]
        for r in f.itertuples():
            names[r.unique_id] = (r.name, ", ".join(str(x).title() for x in (r.address_city, r.state_final) if x))
    rows = []
    for s in ("dev", "test"):
        for r in json.loads((V3 / f"{s}_labels.json").read_text())["results"]:
            if r["service"] in TAKE:
                rows.append({"pair_id": r["pair_id"], "split": s, "facility": names[r["unique_id"]][0],
                             "place": names[r["unique_id"]][1], "service": r["service_id"],
                             "evidence_urls": " ".join(r.get("evidence_urls") or []), "quote": r.get("quote") or "",
                             "agent_verdict": r["service"], "human_verdict": "", "note": ""})
    return sorted(rows, key=lambda r: r["pair_id"])


def draw(rows: list[dict]) -> list[dict]:
    rng = np.random.default_rng(SEED)
    out = []
    for verdict, k in TAKE.items():
        pool = [r for r in rows if r["agent_verdict"] == verdict]
        n_dev = round(k * sum(r["split"] == "dev" for r in pool) / len(pool))
        for split, n in (("dev", n_dev), ("test", k - n_dev)):
            sub = [r for r in pool if r["split"] == split]
            out += [sub[i] for i in sorted(rng.choice(len(sub), n, replace=False))]
    order = rng.permutation(len(out))
    return [{"row": i + 1, **out[j]} for i, j in enumerate(order)]


def main() -> int:
    if OUT.exists():
        print(f"{OUT.name} exists; the draw is fixed (delete it only to redo a draw nobody has started)")
        return 1
    sheet = draw(decided())
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(sheet)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(sheet)} rows, seed {SEED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

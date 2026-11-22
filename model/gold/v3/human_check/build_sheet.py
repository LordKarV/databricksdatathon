"""Draw the human spot-check sheet for gold v3 (issue #103): 25 decided pairs, about 15 confirmed / 10 contradicted.

    .venv-app/bin/python model/gold/v3/human_check/build_sheet.py            # writes sheet.csv + agent_answers.csv
    .venv-app/bin/python model/gold/v3/human_check/build_sheet.py --force    # rewrite both while sheet.csv is blank

The draw is stable: seed SEED, pairs sorted by pair_id before sampling. Within each verdict the DEV / TEST split
is kept in proportion to the decided pairs in each split. Rows are shuffled so verdicts are not grouped.

sheet.csv is what the checker fills and carries no agent verdict; agent_answers.csv holds the agent's verdict and
split per pair_id, joined back by score.py. The quote is the last column so the checker reads the page first.
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
ANSWERS = HERE / "agent_answers.csv"
COLS = ["row", "pair_id", "facility", "place", "service", "service_means", "evidence_urls", "human_verdict",
        "url_used", "note", "quote"]
ANSWER_COLS = ["pair_id", "split", "agent_verdict"]
# One line per service, from RUBRIC.md, plus the edge cases the agents applied (see README "Services").
MEANS = {
    "dialysis": "haemodialysis is offered at this facility",
    "emergency_csection": "emergency caesarean sections are done here (obstetric operating theatre)",
    "nicu": "a neonatal intensive care unit, or a special newborn care unit (SNCU)",
    "cardiac_surgery": "open-heart or cardiac surgery (bypass/CABG, valve) done here; a cath lab alone is not enough",
    "mri": "an MRI scanner on site; MRI sent out to another centre does not count",
    "burn_care": "a burn unit or ward, or burns treated as a service; hair restoration or scar cosmetics is not",
    "trauma_care": "a trauma centre, or a 24x7 emergency that takes accident and injury cases",
    "emergency_24x7": "an emergency department open 24 hours",
    "stemi_thrombolysis": "treats heart attacks (clot-busting thrombolysis or primary angioplasty)",
}


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
                             "service_means": MEANS[r["service_id"]],
                             "evidence_urls": " ".join(r.get("evidence_urls") or []), "human_verdict": "",
                             "url_used": "", "note": "", "quote": r.get("quote") or "",
                             "agent_verdict": r["service"]})
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


def started(path: Path) -> bool:
    """True once anyone has written a verdict, URL or note into the sheet."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return any((r.get(c) or "").strip() for r in csv.DictReader(fh) for c in ("human_verdict", "url_used", "note"))


def write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    if OUT.exists() and "--force" not in sys.argv[1:]:
        print(f"{OUT.name} exists; the draw is fixed (--force rewrites it with the same seed while it is blank)")
        return 1
    if OUT.exists() and started(OUT):
        print(f"{OUT.name} has answers in it; refusing to overwrite")
        return 1
    sheet = draw(decided())
    write(OUT, COLS, sheet)
    write(ANSWERS, ANSWER_COLS, sheet)
    print(f"wrote {OUT.relative_to(ROOT)} and {ANSWERS.name}: {len(sheet)} rows, seed {SEED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

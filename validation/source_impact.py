"""What each outside source adds to the frozen model v2 scores and to the app's first answer (WS5 5d, issue #140).

    python validation/source_impact.py      # from the repo root, after app/facts/build.py

For every outside source that feeds a scorecard term, it removes that source's points from each pair's stored
additive contributions (derived/v2/facility_service_scores.parquet; 20 points = one doubling of the odds) and asks:
- pairs fired, and LIKELY pairs it fires on, over the 7 app services;
- likely_lost: LIKELY pairs whose p would fall below t_L without it;
- per service, how often the app's first option changes without it, over 300 seeded PIN centres
  (Engine._ranked with the source-free p; the band stays as shipped).
The frozen model is not touched: this is a counterfactual on the published points, never a refit. Writes
validation/out/source_impact.csv and prints it.
"""
from __future__ import annotations

import csv
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import pandas as pd  # noqa: E402
from facts.engine import SERVICES, Engine  # noqa: E402

OUT = ROOT / "validation" / "out" / "source_impact.csv"
TAXONOMY = {"trauma_emergency": "trauma_care"}  # app service id -> score service id where they differ
POINTS_PER_LOGIT = 20 / math.log(2)
N_ORIGINS, SEED, TOP_N = 300, 7, 30
# term label prefix -> (source, where it shows in the app)
SOURCES = {
    "x_nabh": ("NABH accreditation list", "Why page ledger row; 'Official lists' line"),
    "x_nmc": ("NMC medical colleges", "Why page ledger row; 'Official lists' line"),
    "x_erk_prereq": ("e-RaktKosh blood centres", "Why page ledger row (blood centre as a C-section prerequisite)"),
    "x_laqshya": ("NHSRC LaQshya certification", "Why page ledger row; Area government list"),
    "x_mohfw_tcf": ("MoHFW trauma care facilities", "Why page ledger row"),
    "x_pmndp": ("PMNDP dialysis lists", "Why page ledger row"),
    "o_": ("OpenStreetMap (HOT export)", "Why page ledger row"),
    "k_iphs": ("IPHS 2022 public standard", "Why page ledger row; public-standard option"),
}
ALL_LISTS = "all lists and OSM (X and O families)"


def source_of(label: str) -> str | None:
    return next((k for k in SOURCES if label.startswith(k)), None)


def load_points() -> tuple[pd.DataFrame, dict]:
    """One row per app pair: p, band, and points per source key (plus ALL_LISTS)."""
    s = pd.read_parquet(ROOT / "derived/v2/facility_service_scores.parquet",
                        columns=["unique_id", "service_id", "p", "band", "contributions"])
    s = s[s.service_id.isin({TAXONOMY.get(k, k) for k in SERVICES})]
    pts: dict = {}
    for r in s.itertuples(index=False):
        d: dict[str, float] = {}
        for t in json.loads(r.contributions):
            k = source_of(t["label"])
            if k:
                d[k] = d.get(k, 0.0) + t["points"]
            if t["family"] in ("X", "O"):
                d[ALL_LISTS] = d.get(ALL_LISTS, 0.0) + t["points"]
        if d:
            pts[(r.unique_id, r.service_id)] = d
    return s, pts


def without(p: float, points: float) -> float:
    return 1 / (1 + math.exp(-(math.log(p / (1 - p)) - points / POINTS_PER_LOGIT)))


def top1_changes(e: Engine, key: str, pts: dict, origins: list) -> dict[str, str]:
    """Per app service: 'changed of answered' when this source's points are removed."""
    out = {}
    for svc in SERVICES:
        sid = TAXONOMY.get(svc, svc)
        changed = n = 0
        for lat, lon in origins:
            pool, _ = e._ranked(svc, lat, lon)
            if not pool:
                continue
            n += 1
            ov = {}
            for row in pool[:TOP_N]:
                fid = e._f("id", row[2].fi)
                v = pts.get((fid, sid), {}).get(key)
                if v:
                    b, p, lo, hi, c, ev = e.score(fid, svc)
                    ov[fid] = (b, without(p, v), lo, hi, c, ev)
            if ov:
                pool2, _ = e._ranked(svc, lat, lon, scores=ov)
                changed += pool2[0][2].fi != pool[0][2].fi
        out[svc] = f"{changed} of {n}"
    return out


def main() -> None:
    t_l = json.loads((ROOT / "derived/v2/model_card.json").read_text())["band_thresholds"]["likely"]["p"]
    s, pts = load_points()
    band = {(r.unique_id, r.service_id): (r.band, r.p) for r in s.itertuples(index=False)}
    e = Engine.load()
    assert e is not None, "app/facts/out is missing: run app/facts/build.py first"
    rng = random.Random(SEED)
    origins = [(e.pins["lat"][j], e.pins["lon"][j]) for j in rng.sample(range(len(e.pins["pin"])), N_ORIGINS)]
    rows = []
    for key in [*SOURCES, ALL_LISTS]:
        fired = [k for k, d in pts.items() if d.get(key)]
        likely = [k for k in fired if band[k][0] == "LIKELY"]
        name, where = SOURCES.get(key, (ALL_LISTS, "as above"))
        rows.append({"source": name, "term_prefix": key if key in SOURCES else "X,O",
                     "family": {"o_": "O", "k_iphs": "K", ALL_LISTS: "X+O"}.get(key, "X"),
                     "pairs_fired": len(fired), "likely_pairs": len(likely),
                     "likely_lost": sum(without(band[k][1], pts[k][key]) < t_l for k in likely),
                     **{f"top1_changes_{svc}": v for svc, v in top1_changes(e, key, pts, origins).items()},
                     "where_it_shows": where})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(pd.DataFrame(rows).drop(columns=["where_it_shows"]).to_string(index=False))


if __name__ == "__main__":
    main()

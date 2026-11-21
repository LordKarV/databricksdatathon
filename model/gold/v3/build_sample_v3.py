"""Gold v3 sample (issue #51): 300 DEV and 150 sealed TEST (facility, service) pairs, stratified, fixed seed.

Run from the repo root (pandas, pyarrow):
    .venv-app/bin/python model/gold/v3/build_sample_v3.py
Writes, next to this script:
  dev_sample.json        DEV pairs with what a labeller needs (name, place, website) - committed
  test_sample.json       TEST pair ids only (pair_id, unique_id, service) - committed; labels stay off the repo
  overlap.json           pair ids double-labelled by an independent labeller (25% of each set)
  sample_stats.json      frame, pool sizes and inclusion probabilities per cell

Design
- Services: the 7 core app services plus emergency_24x7 and stemi_thrombolysis (kb/taxonomy capabilities, scored in
  planner/out as emergency_24x7 and thrombolysis).
- Strata per service:
    strong      core: grade "strong"; extra: 2+ own evidence sentences
    weak        core: grade "moderate", "weak" or "tag_only"; extra: exactly 1 evidence sentence
    suspect     a positive claim AND (grade attributed_elsewhere / counter_evidence, or a location, name-collision or
                service-elsewhere risk, or the map point is more than 50 km from its own PIN)
    no_mention  no claim at all for the service, and a public facility by name (district/civil/government hospital,
                medical college, CHC ...) - the pairs where a missing mention may still mean the service exists
- Frame ("a verdict is reachable"): the facility has its own website, or is a public facility. Inclusion
  probabilities are within this frame; sample_stats.json gives its size.
- Excluded: every facility in model/gold (any file) or derived/v1/gold_pairs, and their duplicate groups.
- One pair per facility across DEV and TEST together.
- Each (service, stratum) cell is split into focus states (Bihar, UP, Jharkhand, Odisha, Assam) and the rest; each
  sub-cell is a simple random sample, so the inclusion probability is exactly k / N per sub-cell.
  Half the slots go to the focus sub-cell when it has enough pairs.
"""
from __future__ import annotations

import gzip
import json
import random
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
V1 = ROOT / "derived" / "v1"
sys.path.insert(0, str(ROOT / "app"))
from facts.build import facilities

SEED = 20261121
CORE = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "cardiac_surgery": "cardiac_surgery",
        "mri": "mri", "burn_care": "burns", "trauma_care": "trauma"}
EXTRA = {"emergency_24x7": "emergency_24x7", "stemi_thrombolysis": "thrombolysis"}
STRATA = ["strong", "weak", "suspect", "no_mention"]
DEV_PER_CELL = {"strong": 9, "weak": 8, "suspect": 8, "no_mention": 8}    # x 9 services = 297, topped up to 300
TEST_PER_CELL = {"strong": 4, "weak": 4, "suspect": 4, "no_mention": 5}   # x 9 = 153, trimmed to 150
N_DEV, N_TEST = 300, 150
OVERLAP = 0.25
FOCUS = {"BIHAR", "UTTAR PRADESH", "JHARKHAND", "ODISHA", "ASSAM"}
RISKS = re.compile(r"risk_location|risk_name_collision|risk_service_elsewhere|location|collision|elsewhere")


def excluded_ids() -> set[str]:
    """Every facility in earlier gold sets, plus its duplicate group."""
    uid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    ids = set()
    for f in (ROOT / "model" / "gold").glob("*.json"):
        ids |= set(uid.findall(f.read_text()))
    ids |= set(pd.read_parquet(V1 / "gold_pairs.parquet", columns=["unique_id"]).unique_id)
    g = pd.read_parquet(V1 / "facility_groups.parquet", columns=["unique_id", "dup_group_id"])
    groups = set(g[g.unique_id.isin(ids)].dup_group_id.dropna())
    return ids | set(g[g.dup_group_id.isin(groups)].unique_id)


def core_cells(fr: pd.DataFrame) -> pd.DataFrame:
    gr = pd.read_parquet(V1 / "grades.parquet", columns=["unique_id", "service", "grade", "risks"])
    rows = []
    for svc, v1 in CORE.items():
        g = gr[gr.service == v1].merge(fr[["unique_id", "far"]], on="unique_id")
        risky = g.risks.astype(str).str.contains(RISKS) | g.far | g.grade.isin(["attributed_elsewhere",
                                                                                 "counter_evidence"])
        stratum = pd.Series("weak", index=g.index)
        stratum[g.grade == "strong"] = "strong"
        stratum[risky] = "suspect"
        rows.append(pd.DataFrame({"unique_id": g.unique_id, "service": svc, "stratum": stratum}))
        rows.append(no_mention(fr, set(g.unique_id), svc))
    return pd.concat(rows)


def extra_cells(fr: pd.DataFrame) -> pd.DataFrame:
    path = ROOT / "planner" / "out" / "planner_v1.json.gz"
    if not path.is_file():
        raise SystemExit("build planner/out first: .venv-app/bin/python planner/export_v1.py")
    with gzip.open(path, "rt") as fh:
        doc = json.load(fh)
    ids = doc["facilities"]["id"]
    rows = []
    for svc, cap in EXTRA.items():
        c = doc["capabilities"][cap]
        df = pd.DataFrame({"unique_id": [ids[i] for i in c["i"]], "n_ev": [len(e) for e in c["e"]]})
        df = df[df.n_ev > 0].merge(fr[["unique_id", "far"]], on="unique_id")
        stratum = pd.Series("weak", index=df.index)
        stratum[df.n_ev >= 2] = "strong"
        stratum[df.far] = "suspect"
        rows.append(pd.DataFrame({"unique_id": df.unique_id, "service": svc, "stratum": stratum}))
        rows.append(no_mention(fr, set(df.unique_id), svc))
    return pd.concat(rows)


def no_mention(fr: pd.DataFrame, mentioned: set[str], svc: str) -> pd.DataFrame:
    pub = fr[fr.public_standard & ~fr.unique_id.isin(mentioned)]
    return pd.DataFrame({"unique_id": pub.unique_id, "service": svc, "stratum": "no_mention"})


def frame() -> pd.DataFrame:
    f, _ = facilities()
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id", "raw_coords_to_pin_km"])
    f = f.merge(loc, on="unique_id", how="left")
    f["far"] = f.raw_coords_to_pin_km.fillna(0) > 50
    f["focus"] = f.state_final.fillna("").str.upper().isin(FOCUS)
    f["reachable"] = (f.website_class == "own") | f.public_standard
    return f


def draw(cells: pd.DataFrame, fr: pd.DataFrame, rng: random.Random) -> tuple[list[dict], dict]:
    """Pass 1 fills each cell's quota; pass 2 tops up from cells with spare pairs until N_DEV + N_TEST."""
    cells = cells.merge(fr[["unique_id", "focus"]], on="unique_id")
    taken: set[str] = set()
    pools: dict[tuple[str, str, str], list[str]] = {}
    for svc in [*CORE, *EXTRA]:
        for st in STRATA:
            pool = cells[(cells.service == svc) & (cells.stratum == st)]
            for sub, mask in (("focus", pool.focus), ("rest", ~pool.focus)):
                ids = sorted(pool[mask].unique_id)
                rng.shuffle(ids)
                pools[(svc, st, sub)] = ids
    got: dict[tuple[str, str, str], list[str]] = {k: [] for k in pools}

    def take(key: tuple[str, str, str], n: int) -> int:
        free = [u for u in pools[key] if u not in taken and u not in got[key]][:n]
        got[key] += free
        taken.update(free)
        return len(free)

    for svc in [*CORE, *EXTRA]:
        for st in STRATA:
            k = DEV_PER_CELL[st] + TEST_PER_CELL[st]
            k_focus = take((svc, st, "focus"), k // 2)
            if take((svc, st, "rest"), k - k_focus) < k - k_focus:
                take((svc, st, "focus"), k)  # rest ran short: more from focus
    order = [(svc, st) for st in ("weak", "strong", "suspect", "no_mention") for svc in [*CORE, *EXTRA]]
    while sum(map(len, got.values())) < N_DEV + N_TEST:
        added = 0
        for svc, st in order:
            if sum(map(len, got.values())) >= N_DEV + N_TEST:
                break
            added += take((svc, st, "focus"), 1) or take((svc, st, "rest"), 1)
        if not added:
            break
    picks, stats = [], {}
    for (svc, st, sub), ids in got.items():
        n = len(pools[(svc, st, sub)])
        prob = round(len(ids) / n, 6) if n else None
        stats[f"{svc}|{st}|{sub}"] = {"pool": n, "picked": len(ids), "inclusion_prob": prob}
        picks += [{"unique_id": u, "service": svc, "stratum": st, "sub": sub, "inclusion_prob": prob} for u in ids]
    return picks, stats


def main() -> None:
    rng = random.Random(SEED)
    fr = frame()
    excl = excluded_ids()
    reach = fr[fr.reachable & ~fr.unique_id.isin(excl)]
    cells = pd.concat([core_cells(reach), extra_cells(reach)]).drop_duplicates(["unique_id", "service"])
    picks, stats = draw(cells, reach, rng)
    # TEST = every third pick within each (service, stratum) cell, after a shuffle: exactly 1 in 3, stratified
    dev, test = [], []
    by_cell: dict[tuple[str, str], list[dict]] = {}
    for p in picks:
        by_cell.setdefault((p["service"], p["stratum"]), []).append(p)
    flat = []
    for key in sorted(by_cell):
        ps = by_cell[key]
        rng.shuffle(ps)
        flat += ps
    for i, p in enumerate(flat):
        (test if i % 3 == 2 else dev).append(p)
    info = fr.set_index("unique_id")
    for k, p in enumerate(sorted(dev, key=lambda x: (x["service"], x["stratum"], x["unique_id"])), 1):
        r = info.loc[p["unique_id"]]
        p.update(pair_id=f"v3d_{k:03d}", name=r["name"], city=r.get("address_city") or None,
                 district=r.get("district") or None, state=r.get("state_final") or None, website=r.get("url") or None,
                 public=bool(r["public_standard"]))
    for k, p in enumerate(sorted(test, key=lambda x: (x["service"], x["stratum"], x["unique_id"])), 1):
        p["pair_id"] = f"v3t_{k:03d}"
    dev.sort(key=lambda p: p["pair_id"])
    test.sort(key=lambda p: p["pair_id"])
    overlap = {"dev": sorted(rng.sample([p["pair_id"] for p in dev], round(OVERLAP * len(dev)))),
               "test": sorted(rng.sample([p["pair_id"] for p in test], round(OVERLAP * len(test))))}
    keep_dev = ["pair_id", "unique_id", "service", "stratum", "sub", "inclusion_prob", "name", "city", "district",
                "state", "website", "public"]
    (HERE / "dev_sample.json").write_text(json.dumps([{k: p[k] for k in keep_dev} for p in dev], indent=1,
                                                     ensure_ascii=False))
    (HERE / "test_sample.json").write_text(json.dumps(
        [{k: p[k] for k in ("pair_id", "unique_id", "service")} for p in test], indent=1))
    (HERE / "overlap.json").write_text(json.dumps(overlap, indent=1))
    summary = {"seed": SEED, "frame_facilities": len(reach), "all_facilities": len(fr),
               "excluded_earlier_gold": len(excl), "n_dev": len(dev), "n_test": len(test),
               "n_overlap": {k: len(v) for k, v in overlap.items()},
               "dev_by_service_stratum": pd.DataFrame(dev).groupby(["service", "stratum"]).size()
               .unstack(fill_value=0).to_dict(orient="index"),
               "focus_share": {"dev": round(sum(p["sub"] == "focus" for p in dev) / len(dev), 3),
                               "test": round(sum(p["sub"] == "focus" for p in test) / len(test), 3)},
               "cells": stats}
    (HERE / "sample_stats.json").write_text(json.dumps(summary, indent=1))
    print(f"frame {len(reach):,} of {len(fr):,} facilities; DEV {len(dev)}, TEST {len(test)}; overlap "
          f"{summary['n_overlap']}; focus share {summary['focus_share']}")


if __name__ == "__main__":
    main()

"""Gold v3 TEST, redrawn after review (PR #76): disjoint from all earlier gold by leakage group, stratified by operator.

Run from the repo root after build_sample_v3.py (DEV is frozen as labelled; this script never changes it):
    .venv-app/bin/python model/gold/v3/build_test_v3.py
Writes test_sample.json (pair_id, unique_id, service only), and updates overlap.json["test"] and
sample_stats.json["test"]. Fails if any check in check_disjoint() fails.

Design (decisions on PR #76)
- Excluded: every facility named in any earlier gold set (all of model/gold/**, the e2e pairs in
  model/proto/decision/e2e_pairs_to_label.json, model/v2/labels/out/gold_dev_pairs and gold_dev_facility,
  derived/v1/gold_pairs) and every v3 DEV facility, then every facility in the same leakage_group_id
  (derived/v2/facility_features) or duplicate group. So no leakage group spans TEST and any training label.
- Frame by operator (derived/v2/facility_attributes.operator):
    public    every eligible public facility (labelled from government lists and pages; no own website needed)
    private   private or unknown operator, with a reachable own website (the DEV frame, see build_sample_v3.py)
- Cells: service x stratum (strong / weak / suspect / no_mention, as DEV) x operator. Each (service, stratum) gets
  TEST_PER_CELL pairs, PUBLIC_SHARE of them public where the public pool allows, the rest private. Each sub-cell is a
  simple random sample (fixed seed), inclusion_prob = k / N per sub-cell; scarcest cells drawn first; one pair per
  leakage group.
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import build_sample_v3 as v3  # noqa: E402, RUF100

SEED = 20261122
N_TEST = 150
TEST_PER_CELL = {"strong": 4, "weak": 4, "suspect": 4, "no_mention": 5}  # x 9 services = 153, trimmed to 150
PUBLIC_SHARE = 0.4
UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
GOLD_PARQUETS = [ROOT / "model/v2/labels/out/gold_dev_pairs.parquet",
                 ROOT / "model/v2/labels/out/gold_dev_facility.parquet", ROOT / "derived/v1/gold_pairs.parquet"]


def earlier_gold_ids() -> set[str]:
    """Facility ids in every earlier gold set (excluding this v3 TEST's own files)."""
    ids: set[str] = set()
    own = {HERE / "test_sample.json", HERE / "overlap.json", HERE / "sample_stats.json"}
    for f in (ROOT / "model" / "gold").rglob("*.json"):
        if f not in own:
            ids |= set(UID.findall(f.read_text()))
    ids |= set(UID.findall((ROOT / "model/proto/decision/e2e_pairs_to_label.json").read_text()))
    for p in GOLD_PARQUETS:
        if not p.is_file():
            raise SystemExit(f"missing {p.relative_to(ROOT)}: the exclusion would be incomplete")
        ids |= set(pd.read_parquet(p, columns=["unique_id"]).unique_id)
    return ids


def groups() -> pd.DataFrame:
    """unique_id -> leakage group and duplicate group."""
    lk = pd.read_parquet(ROOT / "derived/v2/facility_features.parquet",
                         columns=["unique_id", "leakage_group_id"]).drop_duplicates("unique_id")
    dg = pd.read_parquet(v3.V1 / "facility_groups.parquet", columns=["unique_id", "dup_group_id"])
    g = lk.merge(dg, on="unique_id", how="outer")
    g["leakage_group_id"] = g.leakage_group_id.fillna("u:" + g.unique_id)
    g["dup_group_id"] = g.dup_group_id.fillna("d:" + g.unique_id)
    return g


def blocked(seed_ids: set[str], g: pd.DataFrame) -> set[str]:
    """seed_ids plus every facility sharing a leakage or duplicate group with one, to a fixed point."""
    out = set(seed_ids)
    while True:
        lg = set(g[g.unique_id.isin(out)].leakage_group_id)
        dg = set(g[g.unique_id.isin(out)].dup_group_id)
        grown = out | set(g[g.leakage_group_id.isin(lg) | g.dup_group_id.isin(dg)].unique_id)
        if grown == out:
            return out
        out = grown


def test_frame(fr: pd.DataFrame, excl: set[str]) -> pd.DataFrame:
    op = pd.read_parquet(ROOT / "derived/v2/facility_attributes.parquet", columns=["unique_id", "operator"])
    f = fr.merge(op, on="unique_id", how="left")
    f["operator_stratum"] = (f.operator == "public").map({True: "public", False: "private"})
    ok = (f.operator_stratum == "public") | f.reachable
    return f[ok & ~f.unique_id.isin(excl)].reset_index(drop=True)


def draw(cells: pd.DataFrame, g: pd.DataFrame, rng: random.Random) -> tuple[list[dict], dict]:
    lg = dict(zip(g.unique_id, g.leakage_group_id, strict=True))
    pools: dict[tuple[str, str, str], list[str]] = {}
    for (svc, st, op), d in cells.groupby(["service", "stratum", "operator_stratum"]):
        ids = sorted(d.unique_id)
        rng.shuffle(ids)
        pools[(svc, st, op)] = ids
    services = [*v3.CORE, *v3.EXTRA]
    got: dict[tuple[str, str, str], list[str]] = {(s, st, op): [] for s in services for st in v3.STRATA
                                                  for op in ("public", "private")}
    used_groups: set[str] = set()

    def take(key: tuple[str, str, str], n: int) -> int:
        k = 0
        for u in pools.get(key, []):
            if k == n:
                break
            if lg.get(u, u) not in used_groups:
                got[key].append(u)
                used_groups.add(lg.get(u, u))
                k += 1
        return k

    size = {c: sum(len(pools.get((*c, op), [])) for op in ("public", "private")) for c in
            ((s, st) for s in services for st in v3.STRATA)}
    for svc, st in sorted(size, key=lambda c: (size[c], c)):
        k = TEST_PER_CELL[st]
        k_pub = take((svc, st, "public"), math.ceil(k * PUBLIC_SHARE))
        short = k - k_pub - take((svc, st, "private"), k - k_pub)
        if short:
            take((svc, st, "public"), short)
    # Top up to N_TEST one pair at a time, cycling the cells in a fixed order (public first in each cell).
    while sum(map(len, got.values())) < N_TEST:
        added = 0
        for svc, st in sorted(size, key=lambda c: (size[c], c)):
            if sum(map(len, got.values())) >= N_TEST:
                break
            added += take((svc, st, "public"), 1) or take((svc, st, "private"), 1)
        if not added:
            break
    picks = []
    stats = {}
    for key, ids in got.items():
        n = len(pools.get(key, []))
        prob = round(len(ids) / n, 6) if n else None
        stats["|".join(key)] = {"pool": n, "picked": len(ids), "inclusion_prob": prob}
        picks += [{"unique_id": u, "service": key[0], "stratum": key[1], "operator_stratum": key[2],
                   "inclusion_prob": prob} for u in ids]
    # Trim to N_TEST from the largest cells (their pairs carry the least design weight per pair).
    while len(picks) > N_TEST:
        cell = max(stats, key=lambda c: (stats[c]["picked"], stats[c]["pool"], c))
        svc, st, op = cell.split("|")
        drop = next(p for p in reversed(picks) if (p["service"], p["stratum"], p["operator_stratum"]) == (svc, st, op))
        picks.remove(drop)
        stats[cell]["picked"] -= 1
        n = stats[cell]["pool"]
        stats[cell]["inclusion_prob"] = round(stats[cell]["picked"] / n, 6)
        for p in picks:
            if (p["service"], p["stratum"], p["operator_stratum"]) == (svc, st, op):
                p["inclusion_prob"] = stats[cell]["inclusion_prob"]
    return picks, stats


def check_disjoint(test: list[dict], dev: list[dict], g: pd.DataFrame, gold: set[str]) -> dict[str, int]:
    """The review's assertions (PR #76, items 1 and 2). Raises on any overlap."""
    ids = {p["unique_id"] for p in test}
    lg = g.set_index("unique_id").leakage_group_id
    tg = set(lg.reindex(list(ids)).dropna())
    dev_ids = {p["unique_id"] for p in dev}
    checks = {
        "test_facilities_in_earlier_gold": len(ids & gold),
        "test_facilities_in_dev_v3": len(ids & dev_ids),
        "test_groups_shared_with_earlier_gold": len(tg & set(lg.reindex(list(gold)).dropna())),
        "test_groups_shared_with_dev_v3": len(tg & set(lg.reindex(list(dev_ids)).dropna())),
        "test_pairs_sharing_a_group": len(test) - len(tg),
    }
    bad = {k: v for k, v in checks.items() if v}
    if bad:
        raise SystemExit(f"TEST is not disjoint: {bad}")
    pu = pd.read_parquet(ROOT / "model/v2/labels/out/pu_labels.parquet", columns=["unique_id", "service"])
    checks["test_facilities_with_pu_rows_lead_drops_these"] = int(pu.unique_id.isin(ids).any() and
                                                                 pu[pu.unique_id.isin(ids)].unique_id.nunique())
    return checks


def main() -> None:
    rng = random.Random(SEED)
    dev = json.loads((HERE / "dev_sample.json").read_text())
    g = groups()
    gold = earlier_gold_ids()
    excl = blocked(gold | {p["unique_id"] for p in dev}, g)
    fr = v3.frame()
    tf = test_frame(fr, excl)
    cells = pd.concat([v3.core_cells(tf), v3.extra_cells(tf)]).drop_duplicates(["unique_id", "service"])
    cells = cells.merge(tf[["unique_id", "operator_stratum"]], on="unique_id")
    picks, stats = draw(cells, g, rng)
    picks.sort(key=lambda p: (p["service"], p["stratum"], p["operator_stratum"], p["unique_id"]))
    for k, p in enumerate(picks, 1):
        p["pair_id"] = f"v3t2_{k:03d}"
    checks = check_disjoint(picks, dev, g, gold)
    (HERE / "test_sample.json").write_text(json.dumps(
        [{k: p[k] for k in ("pair_id", "unique_id", "service")} for p in picks], indent=1) + "\n")
    overlap = json.loads((HERE / "overlap.json").read_text())
    overlap["test"] = sorted(rng.sample([p["pair_id"] for p in picks], round(v3.OVERLAP * len(picks))))
    (HERE / "overlap.json").write_text(json.dumps(overlap, indent=1))
    st = json.loads((HERE / "sample_stats.json").read_text())
    st["test"] = {
        "redrawn": "after review on PR #76: leakage-group disjoint, operator stratified", "seed": SEED,
        "earlier_gold_facilities": len(gold), "blocked_with_groups_and_dev": len(excl),
        "frame_public": int((tf.operator_stratum == "public").sum()),
        "frame_private": int((tf.operator_stratum == "private").sum()),
        "n_test": len(picks), "public_pairs": sum(p["operator_stratum"] == "public" for p in picks),
        "checks": checks, "cells": stats}
    st["n_test"] = len(picks)
    st["n_overlap"]["test"] = len(overlap["test"])
    (HERE / "sample_stats.json").write_text(json.dumps(st, indent=1))
    # Private to the custodian: what each labeller needs, by pair (blinded: no scores, no claims, no stratum).
    info = fr.set_index("unique_id")
    labeller = [{"pair_id": p["pair_id"], "service": p["service"], "name": info.at[p["unique_id"], "name"],
                 "city": info.at[p["unique_id"], "address_city"] or None,
                 "state": info.at[p["unique_id"], "state_final"] or None,
                 "website": (f"https://{info.at[p['unique_id'], 'website_domain']}/"
                             if p["operator_stratum"] == "private" else None),
                 "_meta": {k: p[k] for k in ("stratum", "operator_stratum", "inclusion_prob", "unique_id")}}
                for p in picks]
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.write_text(json.dumps(labeller, indent=1, ensure_ascii=False))
    print(json.dumps({k: st["test"][k] for k in ("earlier_gold_facilities", "blocked_with_groups_and_dev",
                                                  "frame_public", "frame_private", "n_test", "public_pairs",
                                                  "checks")}, indent=1))


if __name__ == "__main__":
    main()

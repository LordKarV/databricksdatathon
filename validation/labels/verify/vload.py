"""Independent read-only loaders for the verification of the gold-label audit.

Written from the raw label files, not from validation/labels/common.py. v3 is never opened: the label
file list is pinned by name (web_1..3, labels_p1..7, labels_o1..2, labels_e1..3).
"""
from __future__ import annotations

import json
from functools import lru_cache
from math import sqrt
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "validation/labels/verify"
OUT = HERE / "out"
G = ROOT / "model/gold"
V1 = ROOT / "audit/ground_truth"
D1 = ROOT / "derived/v1"

FILES = ([V1 / f"web_{i}.json" for i in (1, 2, 3)] + [G / f"labels_p{i}.json" for i in range(1, 8)]
         + [G / f"labels_o{i}.json" for i in (1, 2)] + [G / f"labels_e{i}.json" for i in (1, 2, 3)])
S2_MAP = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "mri": "mri",
          "cardiac_surgery": "cardiac_surgery", "burn_care": "burns", "trauma_emergency": "trauma"}


def wilson(k, n, z=1.959964):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 3), round(c + h, 3)


def res(name, status, metric, threshold, detail, examples=()):
    return dict(name=name, status=status, metric=metric, threshold=threshold, detail=detail,
                examples=[str(x) for x in list(examples)[:5]])


def kind(f: Path) -> str:
    n = f.name
    if n.startswith("web_"):
        return "v1"
    return {"p": "v2p", "o": "v2o", "e": "e2e"}[n[7]]


@lru_cache(None)
def recs() -> pd.DataFrame:
    rows = []
    for f in FILES:
        for r in json.loads(f.read_text())["results"]:
            loc = r["location_ok"] if "location_ok" in r else r.get("location_matches")
            rows.append(dict(file=f.name, kind=kind(f), pair_id=r["pair_id"], exists=r.get("exists"), location=loc,
                             service=r.get("service"), conf=r.get("confidence"), urls=tuple(r.get("evidence_urls") or ()),
                             quote=r.get("quote"), notes=r.get("notes") or ""))
    d = pd.DataFrame(rows)
    d["nurl"] = d.urls.map(len)
    return d


def primary() -> pd.DataFrame:
    d = recs()
    return d[d.kind != "v2o"].reset_index(drop=True)


@lru_cache(None)
def split_tab() -> pd.DataFrame:
    return pd.DataFrame(json.loads((G / "splits.json").read_text())["pairs"])


@lru_cache(None)
def samples() -> pd.DataFrame:
    rows = [dict(p, set="v1") for p in json.loads((V1 / "sample.json").read_text())]
    rows += [dict(p, set="v2") for p in json.loads((G / "sample_v2.json").read_text())]
    rows += [dict(p, set="e2e") for p in json.loads((ROOT / "model/proto/decision/e2e_pairs_to_label.json").read_text())]
    return pd.DataFrame(rows)


@lru_cache(None)
def gold_pairs() -> pd.DataFrame:
    return pd.read_parquet(D1 / "gold_pairs.parquet")

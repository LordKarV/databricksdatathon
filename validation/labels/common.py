"""Read-only loaders for the gold-label audit (validation/labels).

Every input is opened read-only. v3 TEST is never opened: nothing here globs for v3 files, and the label
globs below are pinned to the v1 web batches and the model/gold labels_{e,o,p}*.json batches.
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
from functools import lru_cache
from math import sqrt
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "validation/labels"
OUT = HERE / "out"
G = ROOT / "model/gold"
V1 = ROOT / "audit/ground_truth"
D1 = ROOT / "derived/v1"
SEED = 20261121

ENUMS = {"exists": {"yes", "no", "unclear"}, "location": {"yes", "no", "unclear"},
         "service": {"confirmed", "contradicted", "no_info"}, "confidence": {"high", "medium", "low"}}
INFORMATIVE = {"exists": {"yes", "no"}, "location": {"yes", "no"}, "service": {"confirmed", "contradicted"}}
# Notes that say the labeller did not (fully) search. Written from reading every no_info note once.
NOT_SEARCHED = re.compile(r"not (?:web-)?(?:searched|checked|researched|run|judged)|budget|no web evidence|unchecked"
                          r"|no lookups|for lack of|name-only|name-based|not verified|no page fetched", re.I)
NAME_ONLY = re.compile(r"name-only|name-based|from (?:the )?(?:facility )?names? only", re.I)
PIN_DIR = re.compile(r"india post|pin directory|pincode directory|local .*directory", re.I)


def wilson(k, n, z=1.959964):
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def result(name, status, metric, threshold, detail, examples=()):
    assert status in ("pass", "warn", "fail"), status
    return dict(name=name, status=status, metric=metric, threshold=threshold, detail=detail,
                examples=[str(x) for x in list(examples)[:5]])


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def label_files() -> list[Path]:
    v1 = sorted(V1.glob("web_*.json"))
    v2 = [Path(f) for f in sorted(glob.glob(str(G / "labels_*.json"))) if re.fullmatch(r"labels_[epo]\d+\.json", Path(f).name)]
    return v1 + v2


def kind_of(f: Path) -> str:
    n = f.name
    return "v1" if n.startswith("web_") else {"p": "v2_primary", "o": "v2_overlap", "e": "e2e"}[n[len("labels_")]]


@lru_cache(None)
def labels() -> pd.DataFrame:
    """One row per label record in every label file, with the location field unified."""
    rows = []
    for f in label_files():
        d = json.loads(f.read_text())
        for i, r in enumerate(d["results"]):
            rows.append(dict(file=f.name, kind=kind_of(f), idx=i, pair_id=r.get("pair_id"), exists=r.get("exists"),
                             location=r.get("location_ok", r.get("location_matches")), service=r.get("service"),
                             confidence=r.get("confidence"), evidence_urls=list(r.get("evidence_urls") or []),
                             quote=r.get("quote"), notes=r.get("notes") or "", keys=tuple(sorted(r))))
    df = pd.DataFrame(rows)
    df["n_urls"] = df.evidence_urls.map(len)
    return df


@lru_cache(None)
def e2e_not_run() -> tuple:
    return tuple(json.loads((G / "labels_e2.json").read_text()).get("not_run", []))


@lru_cache(None)
def pairs() -> pd.DataFrame:
    """Pair universe: v1 sample (36), v2 sample (140), end-to-end pool (158), with the frozen split for v1/v2."""
    rows = []
    for p in json.loads((V1 / "sample.json").read_text()):
        rows.append(dict(p, set="v1"))
    for p in json.loads((G / "sample_v2.json").read_text()):
        rows.append(dict(p, set="v2"))
    for p in json.loads((ROOT / "model/proto/decision/e2e_pairs_to_label.json").read_text()):
        rows.append(dict(p, set="e2e"))
    df = pd.DataFrame(rows)[["pair_id", "set", "unique_id", "name", "city", "state", "pin", "service", "stratum"]]
    sp = splits()[["pair_id", "split", "group", "version"]]
    return df.merge(sp, on="pair_id", how="left")


@lru_cache(None)
def splits() -> pd.DataFrame:
    return pd.DataFrame(json.loads((G / "splits.json").read_text())["pairs"])


@lru_cache(None)
def taxonomy() -> dict:
    """service id or alias -> taxonomy id (36 services; the candidate category is skipped)."""
    s = json.loads((ROOT / "kb/taxonomy/services.json").read_text())
    m = {}
    for c in s["categories"]:
        if c.get("id") == "candidate":
            continue
        for sv in c["services"]:
            m[sv["id"]] = sv["id"]
            for a in sv.get("aliases") or []:
                m.setdefault(a, sv["id"])
    return m


@lru_cache(None)
def raw() -> pd.DataFrame:
    return pd.read_parquet(ROOT / "data/raw/facilities.parquet",
                           columns=["unique_id", "name", "address_city", "address_zipOrPostcode", "officialWebsite"])


@lru_cache(None)
def gold_pairs() -> pd.DataFrame:
    return pd.read_parquet(D1 / "gold_pairs.parquet")


def norm(s) -> str:
    s = str(s or "").lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)

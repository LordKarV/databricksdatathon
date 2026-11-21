"""Shared paths, constants and small statistics helpers for the fusion prototype (numpy only)."""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "model/proto/fusion"
SNAP = HERE / "inputs_snapshot"  # frozen copies of cleaning outputs that were still changing during the build
SEED = 20261122
sys.dont_write_bytecode = True  # imports from read-only trees (cleaning, audit) must not write .pyc there

# gold service key -> claims/cleaning service key
SVC = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "cardiac_surgery": "cardiac_surgery",
       "mri": "mri", "burn_care": "burns", "trauma_emergency": "trauma"}
SVC_INV = {v: k for k, v in SVC.items()}
SERVICES = list(SVC)
BUCKETS = ("low", "mid", "high")
PTS = 20.0 / math.log(2.0)  # 20 points doubles the odds


def sigmoid(z):
    z = np.asarray(z, dtype=float)
    return np.where(z >= 0, 1.0 / (1.0 + np.exp(-np.abs(z))), np.exp(-np.abs(z)) / (1.0 + np.exp(-np.abs(z))))


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return np.log(p / (1 - p))


def wilson(k, n, z=1.959964):
    """95% Wilson interval for k successes out of n; (nan, nan) when n = 0."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256_str(s):
    return hashlib.sha256(s.encode()).hexdigest()


def hkey(s, salt="vf-gold-split-v1"):
    return int(hashlib.sha256(f"{salt}:{s}".encode()).hexdigest(), 16)


def dump(obj, path):
    Path(path).write_text(json.dumps(obj, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def weighted_auc(score, y, w):
    """IPW Mann-Whitney AUROC: sum_{i pos, j neg} w_i w_j (1[s_i > s_j] + 0.5 1[=]) / (W_pos W_neg)."""
    score, y, w = map(np.asarray, (score, y, w))
    pos, neg = y == 1, y == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return float("nan")
    sp, wp, sn, wn = score[pos], w[pos], score[neg], w[neg]
    gt = (sp[:, None] > sn[None, :]).astype(float) + 0.5 * (sp[:, None] == sn[None, :])
    return float((wp[:, None] * wn[None, :] * gt).sum() / (wp.sum() * wn.sum()))


def weighted_logloss(p, y, w):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return -(w * (y * np.log(p) + (1 - y) * np.log(1 - p)))


def ece(p, y, w, bins=5):
    """Equal-count bins (by p), weighted |observed - mean p|, weighted by bin weight share."""
    p, y, w = map(np.asarray, (p, y, w))
    o = np.argsort(p, kind="stable")
    tot = w.sum()
    e = 0.0
    for idx in np.array_split(o, bins):
        if len(idx) == 0:
            continue
        wb = w[idx].sum()
        e += wb / tot * abs((w[idx] * y[idx]).sum() / wb - (w[idx] * p[idx]).sum() / wb)
    return float(e)


class UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


if __name__ == "__main__":
    assert abs(wilson(34, 40)[0] - 0.709) < 0.01 and abs(wilson(34, 40)[1] - 0.929) < 0.01
    assert weighted_auc([3, 2, 1], [1, 0, 0], [1, 1, 1]) == 1.0
    assert abs(float(sigmoid(logit(0.3))) - 0.3) < 1e-12
    u = UnionFind(); u.union("b", "a"); u.union("c", "b"); assert u.find("c") == "a"
    print("common ok")

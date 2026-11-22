"""Metrics with 95% group-bootstrap intervals (resampling leakage groups) for out-of-fold predictions."""
from __future__ import annotations

import numpy as np

EPS = 1e-12
B = 2000
SEED = 20261121


def logloss(p: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    w = np.ones_like(p) if w is None else w
    return float(np.sum(-w * (y * np.log(p) + (1 - y) * np.log(1 - p))) / np.sum(w))


def brier(p: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> float:
    w = np.ones_like(p) if w is None else w
    return float(np.sum(w * (p - y) ** 2) / np.sum(w))


def auroc(p: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> float:
    """Weighted AUROC, ties count half."""
    w = np.ones_like(p) if w is None else w
    pos, neg = y == 1, y == 0
    if not pos.any() or not neg.any():
        return float("nan")
    pp, wp, pn, wn = p[pos], w[pos], p[neg], w[neg]
    gt = (pp[:, None] > pn[None, :]).astype(float) + 0.5 * (pp[:, None] == pn[None, :])
    return float((wp[:, None] * wn[None, :] * gt).sum() / (wp.sum() * wn.sum()))


def ece(p: np.ndarray, y: np.ndarray, bins: int = 5) -> float:
    """Expected calibration error over equal-count bins (MODEL_SPEC 4.3 uses 5)."""
    order = np.argsort(p, kind="stable")
    parts = np.array_split(order, bins)
    return float(sum(len(ix) * abs(p[ix].mean() - y[ix].mean()) for ix in parts if len(ix)) / len(p))


FUNS = {"log_loss": logloss, "auroc": auroc, "brier": brier, "ece": lambda p, y, w=None: ece(p, y)}


def _boot_index(groups: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    ug, inv = np.unique(groups, return_inverse=True)
    members = [np.where(inv == g)[0] for g in range(len(ug))]
    pick = rng.integers(0, len(ug), len(ug))
    return np.concatenate([members[g] for g in pick])


def summary(p: np.ndarray, y: np.ndarray, groups: np.ndarray, w: np.ndarray | None = None, b: int = B) -> dict:
    """Point and 95% percentile group-bootstrap interval for each metric. ECE ignores w."""
    out = {"n": int(len(y)), "n_pos": int(y.sum())}
    rng = np.random.default_rng(SEED)
    reps = {k: [] for k in FUNS}
    for _ in range(b):
        ix = _boot_index(groups, rng)
        for k, f in FUNS.items():
            reps[k].append(f(p[ix], y[ix], None if w is None else w[ix]))
    for k, f in FUNS.items():
        r = np.array(reps[k], float)
        r = r[~np.isnan(r)]
        out[k] = [f(p, y, w), float(np.quantile(r, 0.025)) if len(r) else None, float(np.quantile(r, 0.975)) if len(r) else None]
    return out


def paired_logloss(p_a: np.ndarray, p_b: np.ndarray, y: np.ndarray, groups: np.ndarray, b: int = B) -> dict:
    """Mean per-pair log-loss difference a - b with a cluster SE (by group) and a 95% group-bootstrap interval."""
    la = -(y * np.log(np.clip(p_a, EPS, 1)) + (1 - y) * np.log(np.clip(1 - p_a, EPS, 1)))
    lb = -(y * np.log(np.clip(p_b, EPS, 1)) + (1 - y) * np.log(np.clip(1 - p_b, EPS, 1)))
    d = la - lb
    ug, inv = np.unique(groups, return_inverse=True)
    gs = np.bincount(inv, weights=d - d.mean())
    se = float(np.sqrt((gs ** 2).sum()) / len(d))
    rng = np.random.default_rng(SEED)
    reps = [d[_boot_index(groups, rng)].mean() for _ in range(b)]
    return {"diff": float(d.mean()), "cluster_se": se, "ci95": [float(np.quantile(reps, 0.025)), float(np.quantile(reps, 0.975))]}


def wilson(k: int, n: int, z: float = 1.959964) -> list:
    if n == 0:
        return [None, None]
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return [float(c - h), float(c + h)]


if __name__ == "__main__":
    y = np.array([0, 0, 1, 1.0])
    assert auroc(np.array([0.1, 0.4, 0.35, 0.8]), y) == 0.75
    assert abs(logloss(np.full(4, 0.5), y) - np.log(2)) < 1e-12
    assert ece(np.array([0.0, 0.0, 1.0, 1.0]), y, bins=2) == 0.0
    s = summary(np.array([0.1, 0.4, 0.35, 0.8]), y, np.array(["a", "b", "c", "d"]), b=50)
    assert s["auroc"][0] == 0.75 and s["n_pos"] == 2
    print("metrics ok")

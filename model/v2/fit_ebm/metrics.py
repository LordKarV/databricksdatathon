"""Out-of-fold metrics with group-bootstrap 95% intervals (resampling leakage groups)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

EPS = 1e-12
N_BOOT = 2000
ECE_BINS = 5   # equal-count bins, as in MODEL_SPEC 4.3
LIKELY_PREC, UNLIKELY_NPV, MIN_BEYOND = 0.85, 0.90, 20
FALLBACK_TL, FALLBACK_TU = 0.70, 0.20


def logloss(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(np.average(-(y * np.log(p) + (1 - y) * np.log(1 - p)), weights=w))


def brier(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    return float(np.average((p - y) ** 2, weights=w))


def auroc(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    if y.min() == y.max():
        return float("nan")
    return float(roc_auc_score(y, p, sample_weight=w))


def ece(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    order = np.argsort(p, kind="stable")
    total = 0.0
    for idx in np.array_split(order, ECE_BINS):
        if len(idx):
            total += w[idx].sum() * abs(np.average(y[idx], weights=w[idx])
                                        - np.average(p[idx], weights=w[idx]))
    return float(total / w.sum())


METRICS = {"log_loss": logloss, "auroc": auroc, "brier": brier, "ece": ece}


def _boot_index(groups: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    uniq, inv = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inv == g) for g in range(len(uniq))]
    pick = rng.integers(0, len(uniq), len(uniq))
    return np.concatenate([members[g] for g in pick])


def summarize(y: np.ndarray, preds: dict[str, np.ndarray], groups: np.ndarray,
              w: np.ndarray | None = None, ref: str | None = None,
              seed: int = 7) -> pd.DataFrame:
    """Point estimate and percentile 95% CI per (model, metric); paired deltas against `ref`."""
    w = np.ones(len(y)) if w is None else w
    rng = np.random.default_rng(seed)
    boots = [_boot_index(groups, rng) for _ in range(N_BOOT)]
    rows = []
    for name, p in preds.items():
        for mname, f in METRICS.items():
            point = f(y, p, w)
            draws = np.array([f(y[b], p[b], w[b]) for b in boots])
            row = dict(model=name, metric=mname, n=len(y), k=int(y.sum()), value=point,
                       lo=np.nanpercentile(draws, 2.5), hi=np.nanpercentile(draws, 97.5),
                       boot_se=np.nanstd(draws))
            if ref is not None and name != ref:
                pr = preds[ref]
                d = np.array([f(y[b], p[b], w[b]) - f(y[b], pr[b], w[b]) for b in boots])
                row.update(delta_vs_ref=point - f(y, pr, w), delta_lo=np.nanpercentile(d, 2.5),
                           delta_hi=np.nanpercentile(d, 97.5), delta_se=np.nanstd(d))
            rows.append(row)
    return pd.DataFrame(rows)


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    z, ph = 1.959964, k / n
    den = 1 + z * z / n
    mid = (ph + z * z / (2 * n)) / den
    half = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (float(mid - half), float(mid + half))


def thresholds(y: np.ndarray, p: np.ndarray, gate: np.ndarray) -> dict:
    """MODEL_SPEC 3.2 badge thresholds on out-of-fold scores.

    t_L: smallest threshold with precision >= 0.85 among gated pairs (T >= 2) with P >= t, when at
    least 20 pairs lie beyond it; else the fallback 0.70. t_U: largest threshold with NPV >= 0.90
    among pairs with P <= t, with the same count rule; else 0.20. P_L and P_E gates are not
    applied here (they are separate heads; see FIT.md).
    """
    out = {}
    cand = np.unique(p[gate])
    t_l = next((t for t in cand if (sel := gate & (p >= t)).sum() >= MIN_BEYOND
                and y[sel].mean() >= LIKELY_PREC), None)
    out["t_L"], out["t_L_fallback"] = (t_l, False) if t_l is not None else (FALLBACK_TL, True)
    sel = gate & (p >= out["t_L"])
    k, n = int(y[sel].sum()), int(sel.sum())
    out["likely_n"], out["likely_k"] = n, k
    out["likely_precision"] = k / n if n else float("nan")
    out["likely_wilson"] = wilson(k, n)
    t_u = next((t for t in np.unique(p)[::-1] if (sel := p <= t).sum() >= MIN_BEYOND
                and 1 - y[sel].mean() >= UNLIKELY_NPV), None)
    out["t_U"], out["t_U_fallback"] = (t_u, False) if t_u is not None else (FALLBACK_TU, True)
    sel = p <= out["t_U"]
    kn, n = int((1 - y[sel]).sum()), int(sel.sum())
    out["unlikely_n"], out["unlikely_npv"] = n, (kn / n if n else float("nan"))
    out["unlikely_wilson"] = wilson(kn, n)
    # Best precision reachable with >= 20 gated pairs beyond, for context.
    precs = [(t, y[gate & (p >= t)].mean()) for t in cand if (gate & (p >= t)).sum() >= MIN_BEYOND]
    out["max_precision_20"] = max((pr for _, pr in precs), default=float("nan"))
    return {k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in out.items()}



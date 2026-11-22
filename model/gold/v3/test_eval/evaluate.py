"""Score the frozen model v2 predictions against the opened gold v3 TEST labels (issue #51), once.

    .venv-app/bin/python model/gold/v3/test_eval/evaluate.py      # writes test_eval/results.json and prints it

Headline (as for DEV, PR #76): decided pairs only (confirmed = 1, contradicted = 0); no_info is not evidence of
absence. Sensitivity (MODEL_SPEC 3.2): a searched no_info counts as 0. Intervals: 2,000 bootstrap resamples of
pairs (percentile 95%); Wilson 95% for proportions. Agent-labelled, not human-checked.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRED = ROOT / "model/v2/test_predictions.parquet"
FROZEN = "1b85f4c81afd936a057d9349247c716f7fa65091931d51e30ccdcef83f6e3ff4"
rng = np.random.default_rng(20261122)


def auroc(p: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    return float(((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum())
                 / (len(pos) * len(neg)))


def ece(p: np.ndarray, y: np.ndarray, bins: int = 5) -> float:
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean() for b in range(bins)
                     if (idx == b).any()))


def boot(f, p: np.ndarray, y: np.ndarray) -> list[float | None]:
    vals = []
    for _ in range(2000):
        i = rng.integers(0, len(p), len(p))
        v = f(p[i], y[i])
        if v is not None:
            vals.append(v)
    return [round(float(np.percentile(vals, 2.5)), 3), round(float(np.percentile(vals, 97.5)), 3)] if vals else None


def wilson(k: int, n: int) -> dict:
    if not n:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    z, ph = 1.96, k / n
    c = (ph + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"k": k, "n": n, "rate": round(ph, 3), "ci95": [round(c - h, 3), round(c + h, 3)]}


def metrics(d: pd.DataFrame) -> dict:
    p, y = d.p.to_numpy(float), d.y.to_numpy(int)
    ll = lambda p, y: float(-np.mean(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1))))  # noqa: E731
    br = lambda p, y: float(np.mean((p - y) ** 2))  # noqa: E731
    base = y.mean() if len(y) else None
    out = {"n": len(d), "confirmed": int(y.sum()), "contradicted": int((1 - y).sum())}
    if len(d) >= 2:
        a = auroc(p, y)
        out |= {"auroc": None if a is None else round(a, 3), "auroc_ci95": boot(auroc, p, y),
                "log_loss": round(ll(p, y), 3), "log_loss_ci95": boot(ll, p, y),
                "base_rate_log_loss": round(ll(np.full_like(p, base), y), 3),
                "brier": round(br(p, y), 3), "ece5": round(ece(p, y), 3), "mean_p": round(float(p.mean()), 3),
                "confirmed_rate": round(float(base), 3)}
    for band in ("LIKELY", "CALL_FIRST", "NO_SERVICE_TEXT", "UNLIKELY"):
        b = d[d.band == band]
        out[f"{band}_confirmed"] = wilson(int(b.y.sum()), len(b))
    return out


def main() -> None:
    assert hashlib.sha256(PRED.read_bytes()).hexdigest() == FROZEN, "test_predictions.parquet is not the frozen file"
    lab = pd.DataFrame(json.loads((HERE.parent / "test_labels.json").read_text())["results"])
    pred = pd.read_parquet(PRED)
    d = lab.merge(pred[["pair_id", "p", "band", "model_version"]], on="pair_id", how="left", validate="1:1")
    assert d.p.notna().all() and len(d) == 150
    ops = pd.read_parquet(ROOT / "derived/v2/facility_attributes.parquet", columns=["unique_id", "operator"])
    d = d.merge(ops, on="unique_id", how="left")
    dec = d[d.service != "no_info"].assign(y=lambda x: (x.service == "confirmed").astype(int))
    sens = d.assign(y=(d.service == "confirmed").astype(int))
    res = {
        "about": "Gold v3 TEST, opened once (OPENING_LOG.md), against frozen model v2 predictions. Agent-labelled, "
                 "not human-checked.",
        "model_version": d.model_version.iloc[0], "test_predictions_sha256": FROZEN,
        "verdicts": d.service.value_counts().to_dict(), "pairs_by_method": d.method.value_counts().to_dict(),
        "headline_decided": metrics(dec),
        "sensitivity_no_info_as_0": metrics(sens),
        "by_operator_decided": {k: metrics(g) for k, g in dec.groupby(dec.operator.fillna("unknown"))},
        "by_method_decided": {k: metrics(g) for k, g in dec.groupby("method")},
        "no_info_by_operator": {k: wilson(int((g.service == "no_info").sum()), len(g))
                                for k, g in d.groupby(d.operator.fillna("unknown"))},
        "by_service_decided": {k: {"n": len(g), "confirmed": int(g.y.sum())} for k, g in dec.groupby("service_id")},
    }
    (HERE / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

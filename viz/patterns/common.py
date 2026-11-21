"""Shared paths, the 70/30 split, statistics helpers and the test registry for viz/patterns.

Every analysis script registers each hypothesis test with `register()`; p9_multiple.py applies
Benjamini-Hochberg across all of them. Gold labels (model/gold) are never read here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "viz" / "patterns"
DATA = HERE / "data"
CHARTS = HERE / "charts"
sys.path.insert(0, str(ROOT / "viz"))
import style as S  # noqa: E402

SEED = 20261121
TEST_COLS = ["test_id", "family", "description", "effect_type", "effect", "lo", "hi", "p", "n",
             "ho_effect", "ho_lo", "ho_hi", "ho_p", "ho_n", "headline"]


# Inputs mapped to Unity Catalog tables (set by notebook.py on Databricks); anything unmapped is read from ROOT.
UC_TABLES: dict[str, str] = {}


def read_input(rel: str, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a project input by its path relative to ROOT, or from its Unity Catalog table when mapped."""
    if rel in UC_TABLES:
        from pyspark.sql import SparkSession  # only on Databricks
        df = SparkSession.builder.getOrCreate().table(UC_TABLES[rel])
        return (df.select(*columns) if columns else df).toPandas()
    return pd.read_parquet(ROOT / rel, columns=columns)


def facility() -> pd.DataFrame:
    return pd.read_parquet(DATA / "facility.parquet")


def services() -> pd.DataFrame:
    """Facility x 36 service 0/1 matrix (own, positive dataset text), index unique_id."""
    return pd.read_parquet(DATA / "services_matrix.parquet")


def register(rows: list[dict], name: str) -> pd.DataFrame:
    """Write one script's tests to data/tests_<name>.csv (discovery and holdout columns)."""
    t = pd.DataFrame(rows).reindex(columns=TEST_COLS)
    t.to_csv(DATA / f"tests_{name}.csv", index=False)
    return t


def bh(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values (monotone, capped at 1)."""
    p = np.asarray(p, float)
    n = len(p)
    o = np.argsort(p)
    adj = np.empty(n)
    adj[o] = np.minimum.accumulate((p[o] * n / np.arange(1, n + 1))[::-1])[::-1]
    return np.minimum(adj, 1)


def wilson(k: float, n: float) -> tuple[float, float, float]:
    return S.wilson(k, n)


def newcombe(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """Difference of two proportions p1 - p2 with the Newcombe (Wilson hybrid) 95% interval."""
    p1, l1, u1 = S.wilson(k1, n1)
    p2, l2, u2 = S.wilson(k2, n2)
    d = p1 - p2
    return d, d - np.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + np.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)


def two_prop_p(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided p for a 2x2 table: Fisher exact when any cell is small, chi-square otherwise."""
    tab = np.array([[k1, n1 - k1], [k2, n2 - k2]])
    if tab.min() < 10:
        return float(stats.fisher_exact(tab)[1])
    return float(stats.chi2_contingency(tab, correction=False)[1])


def spearman_ci(x: np.ndarray, y: np.ndarray, n_boot: int = 2000, seed: int = SEED) -> tuple[float, float, float, float, int]:
    """Spearman rho with a percentile bootstrap 95% interval and a permutation p (2,000 shuffles)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = stats.rankdata(x[m]), stats.rankdata(y[m])
    n = len(x)
    r = float(np.corrcoef(x, y)[0, 1])
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        boots.append(np.corrcoef(stats.rankdata(x[i]), stats.rankdata(y[i]))[0, 1])
    perm = np.array([np.corrcoef(x, rng.permutation(y))[0, 1] for _ in range(n_boot)])
    p = (1 + np.sum(np.abs(perm) >= abs(r))) / (n_boot + 1)
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return r, float(lo), float(hi), float(p), n


def save_json(obj: dict, name: str) -> None:
    (DATA / f"{name}.json").write_text(json.dumps(obj, indent=1, default=float))


if __name__ == "__main__":
    # ponytail: tiny self-check of the two hand-written statistics
    a = bh(np.array([0.01, 0.04, 0.03, 0.5]))
    assert np.allclose(a, [0.04, 0.04 * 4 / 3 * 0 + 0.0533333, 0.0533333, 0.5], atol=1e-4), a
    d, lo, hi = newcombe(50, 100, 30, 100)
    assert lo < 0.2 < hi and abs(d - 0.2) < 1e-9
    print("common.py self-check ok")

"""Paths and labels shared by the journey story scripts.

Environment (all optional; defaults are this laptop's checkout):
  DATATHON_CODE  repo root holding planner/, geo/, viz/style.py
  DATATHON_ROOT  data root holding derived/v1, kb/, model/gold, data/external (a Volume on Databricks)
  JOURNEYS_OUT   where data/ and charts/ are written
"""
import os
import sys
from pathlib import Path

import numpy as np

CODE = Path(os.environ.get("DATATHON_CODE", "/Users/karthikvattem/projects/datathon"))
ROOT = Path(os.environ.get("DATATHON_ROOT", str(CODE)))
sys.path.insert(0, str(CODE / "viz"))
sys.path.insert(0, str(CODE))
import style as S  # noqa: E402,F401

HERE = Path(os.environ.get("JOURNEYS_OUT", str(CODE / "viz" / "journeys")))
DATA = HERE / "data"
SOURCES = CODE / "viz" / "journeys" / "data" / "sources"  # hand-transcribed external tables, shipped with the code
CHARTS = HERE / "charts"
STUB_NOTE = ("Probabilities: derived/v1 stub (planner/data_v1.py), not the fitted model; "
             "travel: geo.travel straight-line x road-factor estimate.")

PATHWAY_LABEL = {
    "stemi": "Heart attack (STEMI)", "major_trauma": "Major trauma", "obstetric_emergency": "Obstetric emergency",
    "burns": "Burns", "sick_newborn": "Sick newborn", "snakebite": "Snakebite", "dialysis_start": "Dialysis start",
}
SETS = ["Benchmark (40 queries)", "Bihar", "Uttar Pradesh", "Maharashtra"]
STATE_SETS = SETS[1:]
STATE_COLOR = dict(zip(STATE_SETS, S.CATEGORICAL[:3]))


def boot_mean_ci(x, n_boot=2000, seed=7):
    """Mean and 95% percentile-bootstrap interval of x (resampling origins)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    m = rng.choice(x, (n_boot, len(x)), replace=True).mean(axis=1)
    return (x.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5))


def boot_median_ci(x, n_boot=2000, seed=7):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    m = np.median(rng.choice(x, (n_boot, len(x)), replace=True), axis=1)
    return (float(np.median(x)), np.percentile(m, 2.5), np.percentile(m, 97.5))


def note(fig, text, width=175):
    """Wrapped source note (style.source_note does not wrap)."""
    import textwrap
    S.source_note(fig, textwrap.fill(text, width))

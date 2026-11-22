"""Candidate A (fit_prior/prior_a.py reused unchanged): expert prior-only scorecards, written to out/A/.

A reads no label; LABELS is pointed at the cc view only to list the gold pairs for contrib_gold_A.parquet.
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "fit_prior"))
import prior_a  # noqa: E402

prior_a.OUT = HERE / "out" / "A"
prior_a.LABELS = HERE / "out" / "labels_cc"
prior_a.main()

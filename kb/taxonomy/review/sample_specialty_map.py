"""Draw the reviewer's own specialty_map samples: 80 random values (excluding values the builder hand-checked) and the
top 30 by facility count. Writes review/specialty_sample_random80.csv and review/specialty_top30.csv with an empty
'verdict' column that the reviewer fills by hand.

Run: /Users/karthikvattem/projects/datathon/.venv/bin/python review/sample_specialty_map.py
"""
from __future__ import annotations

import os

import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
T = os.path.dirname(D)
SEED = 4242  # builder used 20261121 and 11
COLS = ["specialty", "normalized", "service_id", "method", "n_facilities", "prereq_for"]


def main() -> None:
    m = pd.read_csv(os.path.join(T, "specialty_map.csv"))
    seen = set()
    for f in ("handcheck_specialty_map.csv", "handcheck_specialty_map_service_labels.csv"):
        seen |= set(pd.read_csv(os.path.join(T, "out", f)).specialty)
    pool = m[~m.specialty.isin(seen)]
    print(f"map rows {len(m)}, builder-checked {len(seen)}, pool {len(pool)}")
    pool.sample(80, random_state=SEED)[COLS].assign(verdict="", note="").to_csv(os.path.join(D, "specialty_sample_random80.csv"), index=False)
    m.nlargest(30, "n_facilities")[COLS].assign(verdict="", note="").to_csv(os.path.join(D, "specialty_top30.csv"), index=False)


if __name__ == "__main__":
    main()

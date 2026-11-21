"""Benjamini-Hochberg across every test registered by p1..p7, plus the holdout replication verdict.

significant: BH-adjusted discovery p (q) below 0.05 over ALL registered tests.
replicated:  significant, same direction on the holdout, and the holdout 95% interval excludes the null
             (1 for ratios and lift, 0 for differences and correlations).
Outputs: data/all_tests.csv, data/multiple_summary.json
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

from common import DATA, bh, save_json

ALPHA = 0.05


def main() -> pd.DataFrame:
    t = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(str(DATA / "tests_p*.csv")))], ignore_index=True)
    t = t[t.p.notna()].copy()
    t["q"] = bh(t.p.to_numpy())
    t["significant"] = t.q < ALPHA
    null = np.where(t.effect_type.str.contains("ratio|lift"), 1.0, 0.0)
    same = np.sign(t.effect - null) == np.sign(t.ho_effect - null)
    excl = (t.ho_lo > null) | (t.ho_hi < null)
    t["replicated"] = t.significant & same & excl
    t.to_csv(DATA / "all_tests.csv", index=False)
    sig = t[t.significant]
    summ = dict(n_tests=len(t), n_significant=int(t.significant.sum()), n_replicated=int(t.replicated.sum()),
                bh_threshold_raw_p=float(sig.p.max()) if len(sig) else None,
                by_family=t.groupby("family").agg(tests=("p", "size"), significant=("significant", "sum"),
                                                  replicated=("replicated", "sum")).to_dict("index"))
    save_json(summ, "multiple_summary")
    print(summ)
    return t


if __name__ == "__main__":
    main()

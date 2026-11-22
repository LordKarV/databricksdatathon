"""Candidate C (EBM, fit_ebm/fit_ps.py reused unchanged) on a label view: grouped 5-fold CV only (fold5, all terms).

Run: python run_c.py cc   -> out/C_cc/ps_oof.parquet. `python run_c.py cc final` also runs the final fit + scoring.
The noweb and held-out-state CV of fit_ps.py are skipped for time.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "fit_ebm"))
import features as F  # noqa: E402
import fit_ps  # noqa: E402

view = sys.argv[1]
F.LABEL_DIR = str(HERE / "out" / f"labels_{view}")
fit_ps.OUT = HERE / "out" / f"C_{view}"
fit_ps.OUT.mkdir(parents=True, exist_ok=True)
blk = set(pd.read_parquet(HERE / "out" / f"labels_{view}" / "test_blocked_facilities.parquet").unique_id)

t0 = time.time()
ff, gold, pu, plan = fit_ps.load()
assert not gold.unique_id.isin(blk).any() and not pu.unique_id.isin(blk).any()
terms = F.active_terms(F.PS_TERMS, ff)
masks = F.family_mask_columns(plan, terms)
print(f"gold {len(gold)} pos {int(gold.y_S.sum())} PU {len(pu)} terms {len(terms)}", flush=True)
if "final" not in sys.argv[2:]:
    oof = fit_ps.run_cv(gold, pu, terms, masks, "fold5", "")
    oof = oof.assign(p=expit(oof.z), pair_id=gold.pair_id.to_numpy()[oof.row.to_numpy()])
    oof[["pair_id", "variant", "fold", "z", "p", "base"]].to_parquet(fit_ps.OUT / "ps_oof.parquet", index=False)
else:
    terms_nw = F.active_terms(F.PS_TERMS, ff, drop=F.WEB_ABLATE)
    fit_ps.final_stage(ff, gold, pu, terms, terms_nw, masks)
print(f"done {time.time() - t0:.0f}s", flush=True)

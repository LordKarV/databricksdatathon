"""Candidate B (fit_scorecard reused unchanged): fitted monotone PU+gold scorecard, grouped 5-fold OOF on a label view.

Run: python run_b.py cc        -> out/B_cc/oof.parquet (variants B and B_platt, scheme group5), out/B_cc/platt.json
     python run_b.py cc final  -> also the full fit on all DEV rows: out/B_cc/{params,pair_scores,pair_contributions}.parquet
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "fit_scorecard"))
import design as D  # noqa: E402

view = sys.argv[1]
D.LAB = HERE / "out" / f"labels_{view}"
D.OUT = HERE / "out" / f"B_{view}"
D.OUT.mkdir(parents=True, exist_ok=True)
import core as K  # noqa: E402
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("sc_fit", HERE.parent / "fit_scorecard" / "fit.py")  # proto/fusion also has a fit.py
fit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fit)

ctx = fit.Ctx()
blk = set(pd.read_parquet(D.LAB / "test_blocked_facilities.parquet").unique_id)
assert not ctx.gold.unique_id.isin(blk).any() and not ctx.pu.unique_id.isin(blk).any()
assert not (ctx.pu.service == "trauma_care").any()
fit.log("gold", len(ctx.gold), "pos", int(ctx.gold.y_S.sum()), "PU rows", len(ctx.pu), "terms", len(ctx.terms))
oof = fit.cross_validate(ctx, "B", "group5")
plat, pl_rows = fit.platt_check(ctx, oof, "group5")
fit.log("platt", plat)
oof = pd.concat([oof, pl_rows], ignore_index=True)
oof.to_parquet(D.OUT / "oof.parquet", index=False)
(D.OUT / "platt.json").write_text(json.dumps(plat, indent=1, default=float))
if "final" in sys.argv[2:]:
    r = fit.fit_variant(ctx, "B", np.ones(len(ctx.gold), bool), np.ones(len(ctx.pu), bool))
    Xp = K.pu_design(ctx.pu, ctx.terms, frozenset())
    fit.params_table(ctx, "B", r, ctx.Xg(frozenset()), (Xp != 0).sum(0)).to_parquet(D.OUT / "params.parquet", index=False)
    sc, lg = fit.full_grid(ctx, r["beta"], plat)
    sc.to_parquet(D.OUT / "pair_scores.parquet", index=False)
    lg.to_parquet(D.OUT / "pair_contributions.parquet", index=False)
    fit.log("full fit", dict(em_iters=r["em_iters"], converged=r["converged"]))
fit.log("done")

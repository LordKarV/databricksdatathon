"""Dev-side reference metrics: shipped model out-of-fold, unfitted baselines (B0-B4) and B3 on dev rows. Writes dev_metrics.json.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python dev_metrics.py"""
import json

import numpy as np
import pandas as pd

from fcommon import HERE, weighted_auc

GRADE = {"strong": 0.9, "moderate": 0.6, "weak": 0.3, "tag_only": 0.2}
d = pd.read_parquet(HERE / "dev_oof.parquet")
pf = pd.read_parquet(HERE / "features_pairs.parquet")[["unique_id", "service", "any_mention", "n_tagged", "grade"]]
var = pd.read_parquet(HERE / "variant_scores.parquet")[["unique_id", "service", "p_B4_prior_only"]]
llm = pd.read_parquet(HERE / "llm_judge_pairs.parquet")[["pair_id", "offers", "confidence"]]
d = d.merge(pf, on=["unique_id", "service"]).merge(var, on=["unique_id", "service"]).merge(llm, on="pair_id", how="left")
sc = {"shipped_oof": d.p_oof, "B0_any_mention": d.any_mention.astype(float), "B1_keyword_count": d.n_tagged.astype(float),
      "B2_rule_grade": d.grade.map(GRADE).fillna(0.1), "B4_prior_only": d.p_B4_prior_only,
      "B3_llm_judge": pd.Series(np.where(d.offers == "yes", d.confidence, np.where(d.offers == "no", 1 - d.confidence, 0.5)))}
y, w = d.y.to_numpy(), d.w_ipw.to_numpy()
out = dict(n=len(d), n_pos=int(y.sum()), note="dev = v1 36 + v2 dev, checked labels only; B4 priors used the v1 rates, so B4 on v1 rows is not out of sample",
           auroc={k: dict(raw=weighted_auc(v.to_numpy(), y, np.ones(len(y))), ipw=weighted_auc(v.to_numpy(), y, w)) for k, v in sc.items()})
(HERE / "dev_metrics.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))

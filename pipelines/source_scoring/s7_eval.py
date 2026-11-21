"""Step 7: held-out evaluation on the frozen gold TEST split, and Goal 3 support rates.

Test pairs never entered the fit (s5 hides their verdicts). For each test data point with an informative
verdict (service confirmed/contradicted; location yes/no) we compare three scores:
  baseline     q_ev: evidence rule only (grade tier or location tier), ignores sources
  model        score_model: q_ev shifted by source support (the published score before gold overrides)
  sources_only source_support: weighted mean reliability of the record's sources
AUC (Mann-Whitney, ties = 0.5) with a 90% bootstrap interval (2,000 resamples, seed 20261121), and the
true rate by source-support tercile with 90% Wilson intervals.
Writes derived/v1/evaluation.json.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from ss_common import OUT

SEED = 20261121


def auc(y: np.ndarray, s: np.ndarray) -> float:
    pos, neg = s[y], s[~y]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def auc_ci(y: np.ndarray, s: np.ndarray, n_boot: int = 2000) -> dict:
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        a = auc(y[i], s[i])
        if not math.isnan(a):
            bs.append(a)
    lo, hi = np.quantile(bs, [0.05, 0.95])
    return {"auc": round(auc(y, s), 3), "ci90": [round(float(lo), 3), round(float(hi), 3)]}


def wilson(k: int, n: int, z: float = 1.645) -> list[float]:
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(c - h, 3), round(c + h, 3)]


def evaluate(t: pd.DataFrame) -> dict:
    y = t.gold_true.astype(bool).to_numpy()
    out = {"n": len(t), "n_true": int(y.sum()), "n_false": int((~y).sum())}
    for name, col in (("baseline_no_sources", "q_ev"), ("model", "score_model"), ("sources_only", "source_support")):
        out[name] = auc_ci(y, t[col].to_numpy(float))
    terc = pd.qcut(t.source_support.rank(method="first"), 3, labels=["low", "mid", "high"])
    out["true_rate_by_source_tercile"] = {
        str(k): {"n": int(len(g)), "true": int(g.gold_true.astype(bool).sum()),
                 "rate": round(float(g.gold_true.astype(bool).mean()), 3), "wilson90": wilson(int(g.gold_true.astype(bool).sum()), len(g)),
                 "source_support_range": [round(float(g.source_support.min()), 3), round(float(g.source_support.max()), 3)]}
        for k, g in t.groupby(terc, observed=True)}
    return out


def goal3() -> dict:
    pc = pd.read_parquet(OUT / "source_page_checks.parquet")
    urls = pc.drop_duplicates("url")
    fetched = pc[pc.claim_id.notna()]
    res = {"urls_checked": int(len(urls)),
           "fetch_status": urls.fetch_status.value_counts().to_dict(),
           "urls_with_text": int(fetched.url.nunique()), "sentences_tested": int(len(fetched))}
    by = {}
    for key, g in fetched.groupby("stratum"):
        sv = g[g.is_service_sentence.astype(bool)]
        per_url = g.groupby("url").supported.any()
        by[key] = {"urls_with_text": int(g.url.nunique()), "urls_checked": int((urls.stratum == key).sum()),
                   "unreachable": int(((urls.stratum == key) & (urls.fetch_status == "unreachable")).sum()),
                   "sentences": int(len(g)), "supported": int(g.supported.sum()),
                   "supported_rate": round(float(g.supported.mean()), 3), "supported_wilson90": wilson(int(g.supported.sum()), len(g)),
                   "token_supported_rate": round(float(g.token_supported.mean()), 3),
                   "service_sentences": int(len(sv)), "service_supported": int(sv.supported.sum()),
                   "service_supported_rate": round(float(sv.supported.mean()), 3) if len(sv) else None,
                   "service_supported_wilson90": wilson(int(sv.supported.sum()), len(sv)),
                   "urls_with_any_supported_sentence": int(per_url.sum())}
    res["by_stratum"] = by
    res["by_attribution"] = {k: {"sentences": int(len(g)), "supported_rate": round(float(g.supported.mean()), 3)}
                             for k, g in fetched.groupby("attribution")}
    res["overall_supported_rate"] = round(float(fetched.supported.mean()), 3)
    res["overall_token_supported_rate"] = round(float(fetched.token_supported.mean()), 3)
    return res


def main() -> None:
    dp = pd.read_parquet(OUT / "data_point_scores.parquet")
    gold = dp[(dp.gold_split == "test") & dp.status.isin(["verified_true", "verified_false"])].copy()
    gold["gold_true"] = gold.status == "verified_true"
    res = {"note": "Gold TEST split (model/gold/splits.json); verdicts hidden from the fit.",
           "service_claim": evaluate(gold[gold.dp_type == "service_claim"]),
           "location": evaluate(gold[gold.dp_type == "location"])}
    both = gold[gold.dp_type.isin(["service_claim", "location"])]
    res["service_and_location_pooled"] = evaluate(both)
    res["goal3_page_check"] = goal3()
    (OUT / "evaluation.json").write_text(json.dumps(res, indent=1, default=int))
    print(json.dumps(res, indent=1, default=int))


if __name__ == "__main__":
    assert auc(np.array([True, False]), np.array([0.9, 0.1])) == 1.0
    assert auc(np.array([True, False]), np.array([0.5, 0.5])) == 0.5
    main()

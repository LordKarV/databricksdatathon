"""Score the rule baseline and the reader on the hand-labelled eval set.

    .venv/bin/python model/reader/evaluate.py                    rules only
    .venv/bin/python model/reader/evaluate.py --run minilm       rules and the reader from weights/minilm

Both heads are reported for the class that matters to the product:
  about_this  detecting "NOT about this facility" (label 0): a miss puts another hospital's service on the card
  offers      detecting "does NOT offer" (label 0): a miss counts a referral or a plan as a service
and also for the positive class. Precision and recall carry 95% Wilson intervals. The difference in
F1 (reader minus rules) carries a paired bootstrap interval over eval rows (2,000 resamples).
The reader's decision threshold is 0.5 on the calibrated probability; it is not tuned on this set.

Writes model/reader/eval/results_<run or rules>.json and, for a reader run, eval_predictions_<run>.csv.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, ROOT, Lexicon, context  # noqa: E402


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def prf(y, pred, cls):
    tp = int(((pred == cls) & (y == cls)).sum())
    fp = int(((pred == cls) & (y != cls)).sum())
    fn = int(((pred != cls) & (y == cls)).sum())
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": None if p is None else round(p, 3), "precision_ci95": wilson(tp, tp + fp),
            "recall": None if r is None else round(r, 3), "recall_ci95": wilson(tp, tp + fn), "f1": round(f1, 3)}


def f1_of(y, pred, cls):
    return prf(y, pred, cls)["f1"]


def summarise(y, pred):
    return {"n": int(len(y)), "positives": int((y == 1).sum()), "negatives": int((y == 0).sum()),
            "accuracy": round(float((y == pred).mean()), 3), "accuracy_ci95": wilson(int((y == pred).sum()), len(y)),
            "class_0": prf(y, pred, 0), "class_1": prf(y, pred, 1)}


def paired_bootstrap(y, a, b, cls, n=2000, seed=7):
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        diffs.append(f1_of(y[i], b[i], cls) - f1_of(y[i], a[i], cls))
    return {"f1_reader_minus_rules": round(f1_of(y, b, cls) - f1_of(y, a, cls), 3),
            "ci95": [round(float(np.quantile(diffs, .025)), 3), round(float(np.quantile(diffs, .975)), 3)],
            "share_of_resamples_reader_better": round(float(np.mean(np.array(diffs) > 0)), 3)}


def calibration(y, p, bins=5):
    edges = np.linspace(0, 1, bins + 1)
    rows, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.sum():
            rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "mean_p": round(float(p[m].mean()), 3),
                         "observed": round(float(y[m].mean()), 3)})
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return {"bins": rows, "ece": round(float(ece), 3), "brier": round(float(np.mean((p - y) ** 2)), 3)}


def load_eval(lex):
    e = pd.read_csv(HERE / "eval" / "eval_set.csv")
    e = e[(e.label >= 0) & e.in_claims].copy()
    c = pd.read_parquet(ROOT / "derived/v1/claims.parquet", columns=["claim_id", "attribution", "kind"])
    fac = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "name", "address_city"]).fillna("")
    e = e.merge(c, on="claim_id", how="left").merge(fac, on="unique_id", how="left").fillna({"name": "", "address_city": ""})
    e["service"] = e.service_canonical.where(e.service_canonical.notna(), None)
    known = e.service.isna() | e.service.isin(lex.services)
    e = e[(e.target == "about_this") | (e.service.notna() & known)].reset_index(drop=True)
    e["rule"] = [int(a != "other_facility") if t == "about_this" else lex.rule_offers(x, s, k)
                 for t, a, x, s, k in zip(e.target, e.attribution, e.text, e.service, e.kind)]
    return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    a = ap.parse_args()
    lex = Lexicon()
    e = load_eval(lex)
    res = {"eval_rows": int(len(e)), "facilities": int(e.unique_id.nunique()), "rules": {}, "by_source_rules": {}}
    for t, g in e.groupby("target"):
        res["rules"][t] = summarise(g.label.values, g.rule.values)
        res["by_source_rules"][t] = {s: {"n": int(len(x)), "accuracy": round(float((x.label == x.rule).mean()), 3)}
                                     for s, x in g.groupby("source_file")}
    name = "rules"
    if a.run:
        from common import load_reader, predict
        model, tok, cfg, device = load_reader(HERE / "weights" / a.run)
        ctx = [context(n, c, lex.label.get(s, "") if isinstance(s, str) else "") for n, c, s in zip(e.name, e.address_city, e.service)]
        p = predict(model, tok, device, ctx, e.text.tolist(), temperature=cfg["temperature"], max_len=cfg.get("max_len", 160))
        e["p_reader"] = np.where(e.target == "about_this", p[:, 0], p[:, 1])
        e["reader"] = (e.p_reader >= 0.5).astype(int)
        res.update({"model_version": cfg["model_version"], "backbone": cfg["backbone"], "temperature": cfg["temperature"],
                    "threshold": 0.5, "reader": {}, "reader_vs_rules": {}, "calibration_reader": {}, "by_source_reader": {},
                    "disagreements_on_eval": {}})
        for t, g in e.groupby("target"):
            y, r, m = g.label.values, g.rule.values, g.reader.values
            res["reader"][t] = summarise(y, m)
            res["reader_vs_rules"][t] = {"class_0": paired_bootstrap(y, r, m, 0), "class_1": paired_bootstrap(y, r, m, 1),
                                         "accuracy_reader_minus_rules": round(float((y == m).mean() - (y == r).mean()), 3)}
            res["calibration_reader"][t] = calibration(y.astype(float), g.p_reader.values.astype(float))
            res["by_source_reader"][t] = {s: {"n": int(len(x)), "accuracy": round(float((x.label == x.reader).mean()), 3)}
                                          for s, x in g.groupby("source_file")}
            d = g[g.rule != g.reader]
            res["disagreements_on_eval"][t] = {"n": int(len(d)), "reader_right": int((d.reader == d.label).sum()),
                                               "rules_right": int((d.rule == d.label).sum())}
        name = a.run
        e[["claim_id", "target", "service", "label", "rule", "reader", "p_reader", "source_file", "source_item", "name", "text"]] \
            .to_csv(HERE / "eval" / f"eval_predictions_{name}.csv", index=False)
    (HERE / "eval" / f"results_{name}.json").write_text(json.dumps(res, indent=1))
    show = {k: res[k] for k in ("eval_rows", "rules", "reader", "reader_vs_rules", "disagreements_on_eval") if k in res}
    print(json.dumps(show, indent=1))


if __name__ == "__main__":
    main()

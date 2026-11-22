"""Score the frozen model v2 predictions against the opened gold v3 TEST labels (issue #51), once.

    .venv-app/bin/python model/gold/v3/test_eval/evaluate.py      # writes test_eval/results.json and prints it

Headline (as for DEV, PR #76): decided pairs only (confirmed = 1, contradicted = 0); no_info is not evidence of
absence. Sensitivity (MODEL_SPEC 3.2): a searched no_info counts as 0. Intervals: 2,000 bootstrap resamples of
pairs (percentile 95%); Wilson 95% for proportions. Agent-labelled, not human-checked.

Added for #66 (new keys only; the keys above are unchanged and keep their own random stream):
- calibration_by_score_bin: model_card's bins (width 0.2) on the frozen TEST p, next to model_card's DEV row.
- location_head / existence_head: P_L and P_E from derived/v2/facility_service_scores.parquet at the frozen
  model_version (not in test_predictions.parquet), against the labels' location_ok and exists.
- conformal: model_card's top-k rule rebuilt on TEST (service, state) pseudo-queries.
- e2e_top1_benchmark: copied from top1_benchmark.json (run top1_benchmark.py first; it needs app/facts/out).
Then writes derived/v2/model_card_test.json, the compact summary for the app, How page, notebook and README.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRED = ROOT / "model/v2/test_predictions.parquet"
FROZEN = "1b85f4c81afd936a057d9349247c716f7fa65091931d51e30ccdcef83f6e3ff4"
MODEL_VERSION = "eed29abe3b7d857800e31103e702da866299739f7d19d13375585bf7dbf1d69a"
CARD = ROOT / "derived/v2/model_card.json"
SCORES = ROOT / "derived/v2/facility_service_scores.parquet"
TOP1 = HERE / "top1_benchmark.json"
CARD_TEST = ROOT / "derived/v2/model_card_test.json"
BINS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0 + 1e-12]  # model/v2/final/export.py, model_card calibration_by_score_bin
rng = np.random.default_rng(20261122)
rng2 = np.random.default_rng(20261123)  # #66 additions: a separate stream so the original keys do not move


def auroc(p: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    return float(((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum())
                 / (len(pos) * len(neg)))


def ece(p: np.ndarray, y: np.ndarray, bins: int = 5) -> float:
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean() for b in range(bins)
                     if (idx == b).any()))


def boot(f, p: np.ndarray, y: np.ndarray, gen: np.random.Generator | None = None) -> list[float | None]:
    vals, gen = [], gen or rng
    for _ in range(2000):
        i = gen.integers(0, len(p), len(p))
        v = f(p[i], y[i])
        if v is not None:
            vals.append(v)
    return [round(float(np.percentile(vals, 2.5)), 3), round(float(np.percentile(vals, 97.5)), 3)] if vals else None


def wilson(k: int, n: int) -> dict:
    if not n:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    z, ph = 1.96, k / n
    c = (ph + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"k": k, "n": n, "rate": round(ph, 3), "ci95": [round(c - h, 3), round(c + h, 3)]}


def metrics(d: pd.DataFrame) -> dict:
    p, y = d.p.to_numpy(float), d.y.to_numpy(int)
    ll = lambda p, y: float(-np.mean(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1))))  # noqa: E731
    br = lambda p, y: float(np.mean((p - y) ** 2))  # noqa: E731
    base = y.mean() if len(y) else None
    out = {"n": len(d), "confirmed": int(y.sum()), "contradicted": int((1 - y).sum())}
    if len(d) >= 2:
        a = auroc(p, y)
        out |= {"auroc": None if a is None else round(a, 3), "auroc_ci95": boot(auroc, p, y),
                "log_loss": round(ll(p, y), 3), "log_loss_ci95": boot(ll, p, y),
                "base_rate_log_loss": round(ll(np.full_like(p, base), y), 3),
                "brier": round(br(p, y), 3), "ece5": round(ece(p, y), 3), "mean_p": round(float(p.mean()), 3),
                "confirmed_rate": round(float(base), 3)}
    for band in ("LIKELY", "CALL_FIRST", "NO_SERVICE_TEXT", "UNLIKELY"):
        b = d[d.band == band]
        out[f"{band}_confirmed"] = wilson(int(b.y.sum()), len(b))
    return out


def calibration_by_bin(d: pd.DataFrame, card: dict) -> list[dict]:
    """model_card's score bins on the frozen TEST p. Confirmed rate on decided pairs, Wilson 95%."""
    b = np.digitize(d.p, BINS) - 1
    out = []
    for dev in card["calibration_by_score_bin"]:
        g = d[b == dev["bin"]]
        dec = g[g.service != "no_info"]
        k = int((dec.service == "confirmed").sum())
        out.append({"bin": dev["bin"], "p_min": dev["p_min"], "p_max": dev["p_max"], "n": len(g),
                    "n_decided": len(dec), "k_confirmed": k, "k_contradicted": len(dec) - k,
                    "k_no_info": int((g.service == "no_info").sum()),
                    "mean_p": round(float(g.p.mean()), 3) if len(g) else None,
                    "mean_p_decided": round(float(dec.p.mean()), 3) if len(dec) else None,
                    "confirmed_rate": wilson(k, len(dec)),
                    "dev": {"n_decided": dev["n_decided"], "k_confirmed": dev["k_confirmed"],
                            "mean_p": round(dev["mean_p"], 3),
                            "confirmed_rate": round(dev["k_confirmed"] / dev["n_decided"], 3),
                            "ci95": [round(x, 3) for x in dev["wilson95"]]}})
    return out


def head(p: np.ndarray, y: np.ndarray, label: str) -> dict:
    """AUROC (bootstrap 95%) when both classes exist, else why not; calibration as mean p against the observed rate."""
    out = {"target": label, "n": len(y), "positives": int(y.sum()), "negatives": int((1 - y).sum()),
           "mean_p": round(float(p.mean()), 3), "observed_rate": wilson(int(y.sum()), len(y)),
           "share_p_at_least_0_7": round(float((p >= 0.7).mean()), 3)}
    a = auroc(p, y)
    if a is None:
        out |= {"auroc": None, "auroc_ci95": None, "auroc_why_none": "no negative rows: AUROC is undefined"}
    else:
        out |= {"auroc": round(a, 3), "auroc_ci95": boot(auroc, p, y, rng2),
                "brier": round(float(np.mean((p - y) ** 2)), 3), "ece5": round(ece(p, y), 3),
                "ece5_ci95": boot(ece, p, y, rng2)}
    return out


def heads(lab: pd.DataFrame) -> tuple[dict, dict]:
    """P_L and P_E of the TEST facilities from the published v2 table, against location_ok and exists."""
    s = pd.read_parquet(SCORES, columns=["unique_id", "service_id", "p_location", "p_exists", "model_version"])
    d = lab.merge(s, on=["unique_id", "service_id"], how="left", validate="1:1")
    assert d.p_location.notna().all() and (d.model_version == MODEL_VERSION).all(), "v2 table is not the frozen version"
    src = ("derived/v2/facility_service_scores.parquet (p_location, p_exists), model_version column checked equal to "
           "the frozen model_version; not in the frozen test_predictions.parquet")
    loc = d[d.location_ok.isin(["yes", "no"])]
    location = {"source": src, "counts": d.location_ok.value_counts().to_dict(),
                "yes_no_rows": head(loc.p_location.to_numpy(float), (loc.location_ok == "yes").to_numpy(int),
                                    "location_ok yes 1, no 0; unclear excluded (model/v2/labels y_L rule)"),
                "mean_p_unclear": round(float(d[d.location_ok == "unclear"].p_location.mean()), 3)}
    ex = d[d.exists.isin(["yes", "no"])]
    searched = d.evidence_urls.map(lambda u: len(u or []) > 0)
    ye = d[(d.exists != "unclear") | searched]  # y_E rule: yes 1; no, or searched and unclear, 0
    existence = {"source": src, "counts": d.exists.value_counts().to_dict(),
                 "unclear_searched": int(((d.exists == "unclear") & searched).sum()),
                 "yes_no_rows": head(ex.p_exists.to_numpy(float), (ex.exists == "yes").to_numpy(int),
                                     "exists yes 1, no 0; unclear excluded"),
                 "y_E_rule": head(ye.p_exists.to_numpy(float), (ye.exists == "yes").to_numpy(int),
                                  "model/v2/labels y_E rule, the DEV target behind model_card existence_head: yes 1; "
                                  "no, or unclear after a search (evidence URLs read), 0; unclear and never searched "
                                  "excluded"),
                 "mean_p_unclear": round(float(d[d.exists == "unclear"].p_exists.mean()), 3)}
    return location, existence


def conformal(d: pd.DataFrame, card: dict) -> dict:
    """model_card's rule (model/v2/final/selection.py conformal) on TEST: pseudo-query = (service, state) among decided
    pairs, at least 2 pairs and 1 confirmed; covered when the first confirmed pair ranks within model_card's k (by p,
    ties against the model)."""
    st = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "state_final"])
    dec = d[d.service != "no_info"].merge(st, on="unique_id", how="left").assign(y=lambda x: x.service == "confirmed")
    out = {}
    for cls, c in card["conformal"].items():
        rows, n_nopos, n_small = [], 0, 0
        for (svc, state), q in dec[dec.service_id.isin(c["services"])].groupby(["service_id", "state_final"]):
            if len(q) < 2:
                n_small += 1
                continue
            if not q.y.any():
                n_nopos += 1
                continue
            q = q.sort_values(["p", "y"], ascending=[False, True])
            m, npos, kk = len(q), int(q.y.sum()), min(c["k"], len(q))
            rows.append({"service": svc, "state": state, "size": m, "confirmed": npos,
                         "first_confirmed_rank": int(np.argmax(q.y.to_numpy())) + 1,
                         "random_order_coverage": round(1 - math.comb(m - npos, kk) / math.comb(m, kk), 3),
                         "informative": bool(m > c["k"] and npos < m - c["k"] + 1)})
        cov = sum(r["first_confirmed_rank"] <= c["k"] for r in rows)
        out[cls] = {"claimed": {"k": c["k"], "alpha": c["alpha"], "level": 1 - c["alpha"],
                                "dev_coverage": c["coverage"], "dev_n_queries": c["n_queries"]},
                    "n_queries": len(rows), "queries_without_confirmed": n_nopos, "single_pair_groups": n_small,
                    "coverage": wilson(cov, len(rows)),
                    "random_order_coverage": round(float(np.mean([r["random_order_coverage"] for r in rows])), 3)
                    if rows else None,
                    "n_informative": sum(r["informative"] for r in rows), "queries": rows}
    n_inf = sum(c["n_informative"] for c in out.values())
    sizes = sorted({r["size"] for c in out.values() for r in c["queries"]})
    out["why"] = ("TEST is single pairs drawn one per leakage group, not query lists. Grouping decided TEST pairs by "
                  f"(service, state), model_card's own pseudo-query rule, gives groups of size {sizes}. A query is "
                  "informative only if it has more than k pairs and could miss with k picks: "
                  + ("none is, so coverage is 1 by construction and says nothing about live queries. "
                     if not n_inf else f"{n_inf} are. ")
                  + "The end-to-end top-1 check (e2e_top1_benchmark) is the closest real-query evidence.")
    return out


def summary(res: dict, card: dict) -> dict:
    """Compact derived/v2/model_card_test.json: each metric with its interval, plus limitations."""
    h, s = res["headline_decided"], res["sensitivity_no_info_as_0"]
    seal = dict(line.split()[::-1] for line in (HERE.parent / "test_labels.sha256").read_text().splitlines())

    def auc(m: dict) -> dict:
        return {"n": m["n"], "value": m.get("auroc"), "ci95": m.get("auroc_ci95")}

    loc, ex = res["location_head"], res["existence_head"]
    top = res.get("e2e_top1_benchmark")
    out = {
        "about": "Frozen model v2 on the sealed gold v3 TEST, opened once (model/gold/v3/OPENING_LOG.md). "
                 "Read-only summary of model/gold/v3/test_eval/results.json; model_card.json is unchanged.",
        "model_version": res["model_version"], "test_predictions_sha256": FROZEN,
        "labels_sha256_full": seal["test_labels.full.canonical"],
        "labels_sha256_verdicts": seal["test_labels.verdicts.canonical"],
        "model_card_sha256": hashlib.sha256(CARD.read_bytes()).hexdigest(),
        "code": ["model/gold/v3/test_eval/evaluate.py", "model/gold/v3/test_eval/top1_benchmark.py"],
        "intervals": "95%: pair bootstrap (2,000 resamples, seeded) for AUROC, log loss and ECE; Wilson for rates",
        "verdicts": res["verdicts"],
        "service": {
            "auroc_decided": auc(h), "dev_oof_auroc": [round(x, 3) for x in card["selection_headline"]["table"]
                                                       ["A_platt"]["auroc"]],
            "log_loss_decided": {"value": h["log_loss"], "ci95": h["log_loss_ci95"],
                                 "base_rate": h["base_rate_log_loss"]},
            "ece5_decided": {"value": h["ece5"], "ci95": res["ece5_decided_ci95"]},
            "likely_precision_decided": h["LIKELY_confirmed"],
            "likely_precision_dev": card["thresholds"]["likely"],
            "auroc_public": auc(res["by_operator_decided"]["public"]),
            "auroc_private": auc(res["by_operator_decided"]["private"]),
            "sensitivity_no_info_as_0": {"auroc": auc(s), "likely_precision": s["LIKELY_confirmed"]},
        },
        "calibration_by_score_bin": [{k: r[k] for k in ("bin", "p_min", "p_max", "n", "mean_p_decided",
                                                         "confirmed_rate", "dev")}
                                     for r in res["calibration_by_score_bin"]],
        "location_head": {"counts": loc["counts"], "auroc_yes_no": loc["yes_no_rows"]["auroc"],
                          "auroc_yes_no_ci95": loc["yes_no_rows"]["auroc_ci95"],
                          "why": loc["yes_no_rows"].get("auroc_why_none"),
                          "mean_p_yes_no_rows": loc["yes_no_rows"]["mean_p"],
                          "observed_yes": loc["yes_no_rows"]["observed_rate"]},
        "existence_head": {"counts": ex["counts"], "auroc_yes_no": ex["yes_no_rows"]["auroc"],
                           "auroc_yes_no_ci95": ex["yes_no_rows"]["auroc_ci95"],
                           "why": ex["yes_no_rows"].get("auroc_why_none"),
                           "y_E_rule": {k: ex["y_E_rule"][k] for k in ("n", "positives", "negatives", "auroc",
                                                                         "auroc_ci95", "mean_p", "observed_rate",
                                                                         "ece5", "ece5_ci95")}},
        "head_source": loc["source"],
        "conformal": {cls: {"k": c["claimed"]["k"], "claimed_level": c["claimed"]["level"],
                            "n_queries": c["n_queries"], "n_informative": c["n_informative"],
                            "coverage": c["coverage"]} for cls, c in res["conformal"].items() if cls != "why"}
        | {"why": res["conformal"]["why"]},
    }
    if top:
        out["e2e_top1_benchmark"] = {
            col: {k: top[col].get(k) for k in ("commit", "engine_blob", "answered", "n_with_gold_verdict",
                                               "confirmed", "contradicted", "unknown", "unknown_no_info",
                                               "unknown_no_label", "no_answer", "confirmed_of_decided",
                                               "decided_by_source", "trauma_top1_emergency_24x7_verdicts")}
            for col in ("current", "alt")} | {"alt_is": top["alt"]["engine"], "n_queries": 40,
                                              "same_top1": top["same_top1"]}
    no_info = res["verdicts"].get("no_info", 0)
    n_all = sum(res["verdicts"].values())
    lc, ec = loc["counts"], ex["counts"]
    informative = sum(c["n_informative"] for k, c in res["conformal"].items() if k != "why")
    out["notes"] = [
        "Agent-labelled, not human-checked: no person has read the cited URLs.",
        f"{no_info} of {n_all} TEST pairs ({no_info / n_all:.0%}) are no_info; the headline uses the {h['n']} decided "
        "pairs, so intervals are wide.",
        "TEST was opened once; nothing was refitted or retuned on it. model_card.json (DEV) is unchanged.",
        "P_L and P_E come from derived/v2/facility_service_scores.parquet at the frozen model_version, not from the "
        "frozen predictions file.",
        f"Location: {lc.get('no', 0)} 'no' and {lc.get('unclear', 0)} 'unclear' of {sum(lc.values())}; existence: "
        f"{ec.get('no', 0)} 'no' and {ec.get('unclear', 0)} 'unclear'. AUROC on yes/no rows needs both classes.",
        "ECE intervals are percentile bootstrap; ECE is biased upward in small samples.",
        f"Conformal: {informative} informative TEST pseudo-queries (more than k pairs and able to miss); "
        "the TEST coverage does not test the top-k claim." if not informative else
        f"Conformal: only {informative} informative TEST pseudo-queries.",
    ]
    ci = out["service"]["auroc_public"]["ci95"]
    if ci and ci[0] <= 0.5:
        out["notes"].append("Public facilities: the AUROC interval includes 0.5, so TEST shows no ranking ability "
                            "there.")
    if top:
        out["notes"].append(
            f"End-to-end top-1: decided verdicts by gold source {top['current']['decided_by_source']}; only v3_test is "
            "held out from the fit, and e2e labels were drawn from prototype top-1 answers. Trauma top-1s are looked "
            "up as trauma_care, which has v3 labels only.")
    return out


def main() -> None:
    assert hashlib.sha256(PRED.read_bytes()).hexdigest() == FROZEN, "test_predictions.parquet is not the frozen file"
    lab = pd.DataFrame(json.loads((HERE.parent / "test_labels.json").read_text())["results"])
    pred = pd.read_parquet(PRED)
    d = lab.merge(pred[["pair_id", "p", "band", "model_version"]], on="pair_id", how="left", validate="1:1")
    assert d.p.notna().all() and len(d) == 150
    ops = pd.read_parquet(ROOT / "derived/v2/facility_attributes.parquet", columns=["unique_id", "operator"])
    d = d.merge(ops, on="unique_id", how="left")
    dec = d[d.service != "no_info"].assign(y=lambda x: (x.service == "confirmed").astype(int))
    sens = d.assign(y=(d.service == "confirmed").astype(int))
    res = {
        "about": "Gold v3 TEST, opened once (OPENING_LOG.md), against frozen model v2 predictions. Agent-labelled, "
                 "not human-checked.",
        "model_version": d.model_version.iloc[0], "test_predictions_sha256": FROZEN,
        "verdicts": d.service.value_counts().to_dict(), "pairs_by_method": d.method.value_counts().to_dict(),
        "headline_decided": metrics(dec),
        "sensitivity_no_info_as_0": metrics(sens),
        "by_operator_decided": {k: metrics(g) for k, g in dec.groupby(dec.operator.fillna("unknown"))},
        "by_method_decided": {k: metrics(g) for k, g in dec.groupby("method")},
        "no_info_by_operator": {k: wilson(int((g.service == "no_info").sum()), len(g))
                                for k, g in d.groupby(d.operator.fillna("unknown"))},
        "by_service_decided": {k: {"n": len(g), "confirmed": int(g.y.sum())} for k, g in dec.groupby("service_id")},
    }
    # #66 additions (rng2 only)
    card = json.loads(CARD.read_text())
    assert card["model_version"] == res["model_version"] == MODEL_VERSION
    res["ece5_decided_ci95"] = boot(ece, dec.p.to_numpy(float), dec.y.to_numpy(int), rng2)
    res["calibration_by_score_bin"] = calibration_by_bin(d, card)
    res["location_head"], res["existence_head"] = heads(lab)
    res["conformal"] = conformal(d, card)
    if TOP1.is_file():
        top = json.loads(TOP1.read_text())
        res["e2e_top1_benchmark"] = {k: ({kk: vv for kk, vv in v.items() if kk != "per_query"}
                                         if isinstance(v, dict) else v) for k, v in top.items()}
    (HERE / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    CARD_TEST.write_text(json.dumps(summary(res, card), indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

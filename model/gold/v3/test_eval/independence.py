"""How much of the TEST result is the model and the web check reading the same page? (WS5 5b, issue #140)

    python model/gold/v3/test_eval/independence.py      # writes test_eval/independence.json and prints it

Read-only on the frozen model: it reads model/v2/test_predictions.parquet (sha256 checked), the stored additive
contributions in derived/v2/facility_service_scores.parquet, and the gold v3 labels. It never writes results.json.

Splits of the decided TEST pairs (confirmed = 1, contradicted = 0), each with AUROC and a 2,000-resample pair
bootstrap 95% interval:
- website family W: points > 0 (the facility's own site states the service) vs <= 0;
- label evidence source: the label cites the same URL or domain the dataset record was built from
  (derived/v1/source_urls.parquet) vs an independent domain.
Also: a per-band table, AUROC of the band itself, the services with no TEST negative, the existence head on the
DEV y_E rule, and how often UNLIKELY is right by route (p <= t_U, or the c2 override with p > t_U) on DEV and
TEST. DEV is the fit set, so DEV figures are in-sample. Agent-labelled, not human-checked.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
from evaluate import FROZEN, PRED, auroc, wilson  # noqa: E402

BANDS = ("LIKELY", "CALL_FIRST", "NO_SERVICE_TEXT", "UNLIKELY")
SEED = 20261123


def boot(s: np.ndarray, y: np.ndarray, rng: np.random.Generator) -> list[float] | None:
    vals = []
    for _ in range(2000):
        i = rng.integers(0, len(y), len(y))
        v = auroc(s[i], y[i])
        if v is not None:
            vals.append(v)
    return [round(float(np.percentile(vals, q)), 3) for q in (2.5, 97.5)] if vals else None


def split_stats(d: pd.DataFrame, score: str = "p", rng: np.random.Generator | None = None) -> dict:
    s, y = d[score].to_numpy(float), d.y.to_numpy(int)
    a = auroc(s, y)
    return {"n": len(d), "confirmed": int(y.sum()), "contradicted": int((1 - y).sum()),
            "auroc": None if a is None else round(a, 3), "auroc_ci95": boot(s, y, rng) if a is not None else None}


def w_points(contribs: str) -> float:
    return sum(t["points"] for t in json.loads(contribs) if t["family"] == "W")


def host(u: str) -> str:
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def evidence_source(row, src_dom: dict, src_url: dict) -> str:
    """Same record source (URL or domain the dataset row came from), independent domain, or no URL."""
    urls = row["evidence_urls"] or []
    if not len(urls):
        return "no_url"
    doms, seen = src_dom.get(row["unique_id"], set()), src_url.get(row["unique_id"], set())
    for u in urls:
        h = host(u)
        if u.rstrip("/").lower() in seen or any(h == x or h.endswith("." + x) or x.endswith("." + h) for x in doms):
            return "record_source"
    return "independent_domain"


def unlikely_by_route(d: pd.DataFrame, t_u: float) -> dict:
    """UNLIKELY is right when the label is contradicted. Route p: p <= t_U. Route c2: p > t_U (the c2 override)."""
    u = d[d.band == "UNLIKELY"]
    out = {}
    for name, g in (("p_route", u[u.p <= t_u]), ("c2_route", u[u.p > t_u])):
        out[name] = wilson(int((g.y == 0).sum()), len(g)) | {"pairs": sorted(g.pair_id)}
    return out


def existence_head(t: pd.DataFrame, rng: np.random.Generator) -> dict:
    """P_E against TEST exists. No label says "no", so use the DEV y_E rule: unclear after a search counts as 0.

    The AUROC and its interval are copied from extras.json (evaluate.py, the scored-TEST script) so every doc cites
    one interval; the bootstrap here still runs, as the last rng consumer, and only the point value is checked."""
    searched = t.evidence_urls.map(lambda u: len(u if u is not None else []) > 0)
    d = t[(t.exists != "unclear") | searched].assign(y=lambda x: (x.exists == "yes").astype(int))
    s = split_stats(d, "p_exists", rng)
    ref = json.loads((HERE / "extras.json").read_text())["existence_head"]["y_E_rule"]
    assert s["auroc"] == ref["auroc"] and s["n"] == ref["n"], f"existence AUROC {s['auroc']} != extras.json {ref['auroc']}"
    return {"counts": t.exists.value_counts().to_dict(),
            "y_E_rule": s | {"auroc_ci95": ref["auroc_ci95"],
                             "rule": "confirmed = exists yes (1); contradicted = no, or unclear after a search (0); "
                                     "unclear and never searched excluded (model/v2/labels y_E rule)",
                             "ci_source": "extras.json existence_head.y_E_rule (evaluate.py)"}}


def main() -> None:
    assert hashlib.sha256(PRED.read_bytes()).hexdigest() == FROZEN, "test_predictions.parquet is not the frozen file"
    rng = np.random.default_rng(SEED)
    card = json.loads((ROOT / "derived/v2/model_card.json").read_text())
    t_u = card["thresholds"]["t_U"]
    sc = pd.read_parquet(ROOT / "derived/v2/facility_service_scores.parquet",
                         columns=["unique_id", "service_id", "p", "band", "p_exists", "contributions"])
    lab = pd.DataFrame(json.loads((HERE.parent / "test_labels.json").read_text())["results"])
    pred = pd.read_parquet(PRED)
    t = lab.merge(pred[["pair_id", "p", "band"]], on="pair_id", validate="1:1").merge(
        sc[["unique_id", "service_id", "p", "p_exists", "contributions"]].rename(columns={"p": "p_scores"}),
        on=["unique_id", "service_id"], how="left", validate="1:1")
    assert len(t) == 150 and (t.p - t.p_scores).abs().max() < 1e-9, "scores file disagrees with frozen predictions"
    t["W"] = t.contributions.map(w_points)
    su = pd.read_parquet(ROOT / "derived/v1/source_urls.parquet", columns=["unique_id", "url", "domain"])
    src_dom = su.groupby("unique_id").domain.apply(lambda s: {x.lower() for x in s if isinstance(x, str)}).to_dict()
    src_url = su.groupby("unique_id").url.apply(
        lambda s: {x.rstrip("/").lower() for x in s if isinstance(x, str)}).to_dict()
    t["evidence_source"] = t.apply(evidence_source, axis=1, src_dom=src_dom, src_url=src_url)
    dec = t[t.service != "no_info"].assign(y=lambda x: (x.service == "confirmed").astype(int))

    order = {"UNLIKELY": 0, "NO_SERVICE_TEXT": 1, "CALL_FIRST": 2, "LIKELY": 3}
    dec = dec.assign(band_ordinal=dec.band.map(order), likely_vs_rest=(dec.band == "LIKELY").astype(int))
    bands = []
    for b in BANDS:
        g = t[t.band == b]
        k, c = int((g.service == "confirmed").sum()), int((g.service == "contradicted").sum())
        bands.append({"band": b, "pairs": len(g), "confirmed": k, "contradicted": c,
                      "no_info": int((g.service == "no_info").sum()),
                      "no_info_share": round(float((g.service == "no_info").mean()), 3) if len(g) else None,
                      "confirmed_of_decided": wilson(k, k + c)})
    by_service = dec.groupby("service_id").y.agg(["size", "sum"])

    g = pd.read_parquet(ROOT / "model/v2/labels/out/gold_dev_pairs.parquet")
    g = g[g.primary & g.label_service.isin(["confirmed", "contradicted"])]
    dev = g.merge(sc, left_on=["unique_id", "service"], right_on=["unique_id", "service_id"], validate="1:1")
    dev = dev.assign(y=(dev.label_service == "confirmed").astype(int))

    res = {
        "about": "Independence checks on the gold v3 TEST, frozen model v2. Code: independence.py. Decided pairs "
                 "only. Agent-labelled, not human-checked. DEV rows are the fit set (in-sample).",
        "test_predictions_sha256": FROZEN,
        "overall": split_stats(dec, rng=rng),
        "by_website_family": {
            "W_gt_0": split_stats(dec[dec.W > 0], rng=rng),
            "W_le_0": split_stats(dec[dec.W <= 0], rng=rng),
            "note": "W > 0: the facility's own website states the service, so the model and the web check read "
                    "the same page.",
        },
        "by_label_evidence_source": {
            k: split_stats(dec[dec.evidence_source == k], rng=rng)
            for k in ("record_source", "independent_domain", "no_url")
        } | {"note": "record_source: a label URL is the same URL or domain the dataset record was built from "
                     "(derived/v1/source_urls.parquet)."},
        "bands": bands,
        "band_as_score": {
            "band_ordinal": split_stats(dec, "band_ordinal", rng),
            "likely_vs_rest": split_stats(dec, "likely_vs_rest", rng),
            "note": "AUROC of the band the app shows (UNLIKELY < NO_SERVICE_TEXT < CALL_FIRST < LIKELY), and of "
                    "LIKELY against every other band.",
        },
        "services_with_0_test_negatives": sorted(by_service.index[by_service["size"] == by_service["sum"]]),
        "decided_by_service": {k: {"n": int(r["size"]), "confirmed": int(r["sum"])} for k, r in by_service.iterrows()},
        "existence_head": existence_head(t, rng),
        "unlikely_by_route": {"t_U": t_u, "TEST": unlikely_by_route(dec, t_u), "DEV": unlikely_by_route(dev, t_u)},
    }
    headline = json.loads((HERE / "results.json").read_text())["headline_decided"]
    assert res["overall"]["auroc"] == headline["auroc"], \
        f"overall AUROC {res['overall']['auroc']} != results.json {headline['auroc']}"
    # One overall interval everywhere: results.json's. The bootstrap above still ran, so later splits keep their draws.
    res["overall"] = res["overall"] | {"auroc_ci95": headline["auroc_ci95"], "ci_source": "results.json headline_decided"}
    (HERE / "independence.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

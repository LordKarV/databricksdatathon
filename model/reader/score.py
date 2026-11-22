"""Score every claim sentence with the reader and write derived/v2/reader_scores.parquet.

Rows
  - one row per (claim, service) where the service's lexicon 'include' pattern hits the sentence
    (this includes sentences the rules then reject, so the model can use the reader's view of them)
  - one row per claim with service_id = "" carrying p_about_this only (p_offers is null)

Columns: claim_id, service_id, p_about_this, p_offers, top_tokens_about, top_tokens_offers, model_version
  top_tokens_* are "|"-joined, up to 3 words of the sentence that most support the predicted class
  (gradient x input, see common.top_tokens). They are computed for every service row and for
  service-less rows with p_about_this < 0.5; elsewhere they are empty.

Also writes model/reader/eval/disagreements_<run>.csv: 20 sentences each way where the reader and
the rules disagree, per head (seed 7), for hand checking.

Run: .venv/bin/python model/reader/score.py --run minilm
"""
import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, NON_OFFER_KINDS, ROOT, Lexicon, context, load_reader, predict, top_tokens  # noqa: E402

OUT = ROOT / "derived" / "v2" / "reader_scores.parquet"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--limit", type=int, default=0, help="score only this many claims (smoke test)")
    a = ap.parse_args()
    warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
    t0 = time.time()
    lex = Lexicon()
    model, tok, cfg, device = load_reader(HERE / "weights" / a.run)
    c = pd.read_parquet(ROOT / "derived/v1/claims.parquet", columns=["claim_id", "unique_id", "text", "attribution", "kind"])
    c = c[c.text.notna()].reset_index(drop=True)
    if a.limit:
        c = c.iloc[:a.limit].copy()
    fac = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id", "name", "address_city"]).fillna("")
    c = c.merge(fac, on="unique_id", how="left").fillna({"name": "", "address_city": ""})

    parts = [c.assign(service_id="")]
    for s in lex.services:
        parts.append(c[c.text.str.contains(lex.rx[s]["include"], na=False)].assign(service_id=s))
    d = pd.concat(parts, ignore_index=True)
    ctx = [context(n, ci, lex.label.get(s, "")) for n, ci, s in zip(d.name, d.address_city, d.service_id)]
    sent = d.text.tolist()
    p = predict(model, tok, device, ctx, sent, batch_size=256, temperature=cfg["temperature"], max_len=cfg.get("max_len", 160))
    d["p_about_this"] = p[:, 0].round(4)
    d["p_offers"] = np.where(d.service_id == "", np.nan, p[:, 1]).round(4)
    t_pred = time.time() - t0

    need = np.where((d.service_id != "") | (d.p_about_this < 0.5))[0]
    ta, to = top_tokens(model, tok, device, [ctx[i] for i in need], [sent[i] for i in need], max_len=cfg.get("max_len", 160))
    d["top_tokens_about"] = ""
    d["top_tokens_offers"] = ""
    d.loc[need, "top_tokens_about"] = ["|".join(x) for x in ta]
    d.loc[need, "top_tokens_offers"] = ["|".join(x) if s else "" for x, s in zip(to, d.service_id.values[need])]
    d["model_version"] = cfg["model_version"]
    out_cols = ["claim_id", "service_id", "p_about_this", "p_offers", "top_tokens_about", "top_tokens_offers", "model_version"]
    if not a.limit:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        d[out_cols].to_parquet(OUT, index=False)

    # rule view of the same rows, for the disagreement samples
    d["rule_about"] = (d.attribution != "other_facility").astype(int)
    svc = d.service_id != ""
    d["rule_offers"] = -1
    d.loc[svc, "rule_offers"] = [lex.rule_offers(t, s, k) for t, s, k in zip(d.text[svc], d.service_id[svc], d.kind[svc])]
    base = d[~svc]
    picks = []
    for head, frame, rule, prob in (("about_this", base, "rule_about", "p_about_this"), ("offers", d[svc], "rule_offers", "p_offers")):
        for way, m in (("rules_1_reader_0", (frame[rule] == 1) & (frame[prob] < 0.5)), ("rules_0_reader_1", (frame[rule] == 0) & (frame[prob] >= 0.5))):
            g = frame[m]
            picks.append(g.sample(min(20, len(g)), random_state=7).assign(head=head, way=way, n_in_corpus=len(g)))
    dis = pd.concat(picks, ignore_index=True)
    dis[["head", "way", "n_in_corpus", "claim_id", "service_id", "name", "address_city", "text", "p_about_this", "p_offers",
         "top_tokens_about", "top_tokens_offers", "attribution", "kind"]].to_csv(HERE / "eval" / f"disagreements_{a.run}.csv", index=False)

    stats = {"model_version": cfg["model_version"], "rows": int(len(d)), "claim_rows": int((~svc).sum()), "service_rows": int(svc.sum()),
             "seconds_predict": round(t_pred), "seconds_total": round(time.time() - t0), "device": str(device),
             "rows_with_tokens": int(len(need)),
             "file_mb": None if a.limit else round(OUT.stat().st_size / 1e6, 1),
             "about_this": {"rules_other_facility": int((base.rule_about == 0).sum()), "reader_below_0.5": int((base.p_about_this < 0.5).sum()),
                            "both": int(((base.rule_about == 0) & (base.p_about_this < 0.5)).sum())},
             "offers": {"rules_offer": int((d[svc].rule_offers == 1).sum()), "reader_at_least_0.5": int((d[svc].p_offers >= 0.5).sum()),
                        "both": int(((d[svc].rule_offers == 1) & (d[svc].p_offers >= 0.5)).sum())},
             "disagreement_counts": dis.groupby(["head", "way"]).n_in_corpus.first().to_dict().__repr__()}
    (HERE / "eval" / f"score_stats_{a.run}.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()

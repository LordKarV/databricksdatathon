"""Sentence-level accuracy of the ownership filter and the role rules against the 224 hand labels, and the
LLM sentence classifier (llama-3-3-70b, spec 4.8 check) on the same sentences.

Labels (sentence_labels.csv, written blind to rule outputs): attr o = about this facility, x = about another
facility / branch / place, u = cannot tell; sup y = says the service is provided (by whatever it describes),
n = says it is not / planned / research / amenity, u = cannot tell. Precision metrics drop u and report it.

Writes attribution_rates.csv (display rates, all labels), sentence_metrics.json (dev and test separately).
"""
import json

import numpy as np
import pandas as pd

from atoms import _ownership
from common import HERE, INPUTS, OWN_CLASSES, wilson

RNG = np.random.default_rng(20261122)


def load() -> pd.DataFrame:
    s = pd.read_csv(HERE / "sentence_sample.csv")
    lab = pd.read_csv(HERE / "sentence_labels.csv")
    assert len(lab) == len(s) and set(lab.sid) == set(s.sid), "every sampled sentence needs a label"
    d = s.merge(lab, on="sid")
    c = pd.read_parquet(HERE / "llm_cache.parquet")
    c = c[c.kind == "sent"].set_index("id")
    d["llm"] = d.sid.map(lambda i: json.loads(c.at[i, "response"]) if i in c.index else None)
    d["llm_about"] = d.llm.map(lambda r: r["about"] if r else None)
    d["llm_offers"] = d.llm.map(lambda r: r["offers_service"] if r else None)
    # ownership under both rule versions, recomputed from the claim rows (the sample was drawn under v0)
    cl = pd.read_parquet(INPUTS["claims"])
    cl = cl[cl.claim_id.isin(d.claim_id)].merge(pd.read_parquet(INPUTS["record_scores"], columns=["unique_id", "name"]), on="unique_id")
    for col in ["foreign_names", "sibling_names", "places_other_state", "places_other_district"]:
        cl[col] = cl[col].fillna("")
    for v in ["v0", "v1"]:
        m = {r.claim_id: _ownership(r, v)[0] for r in cl.itertuples(index=False)}
        d[f"own_{v}"] = d.claim_id.map(m)
    return d


def rate(df, cond_col, pos, neg="x") -> dict:
    """k/n with k = label == pos among decided labels."""
    dec = df[df[cond_col].isin([pos, neg] if neg else [pos])]
    k, n = int((dec[cond_col] == pos).sum()), len(dec)
    lo, hi = wilson(k, n)
    return dict(k=k, n=n, unclear=int(len(df) - n), p=round(k / n, 4) if n else None, wilson_lo=lo, wilson_hi=hi)


def classifier_report(d: pd.DataFrame, pred_other: pd.Series) -> dict:
    """Binary 'about another facility' detection on decided attribution labels (o vs x)."""
    m = d.attr.isin(["o", "x"])
    y, p = (d.attr[m] == "x").to_numpy(), pred_other[m].to_numpy()
    tp, fp, fn, tn = int((y & p).sum()), int((~y & p).sum()), int((y & ~p).sum()), int((~y & ~p).sum())
    acc = (tp + tn) / len(y)
    return dict(n=int(len(y)), tp=tp, fp=fp, fn=fn, tn=tn, accuracy=round(acc, 4), accuracy_ci=wilson(tp + tn, len(y)),
                precision_other=round(tp / (tp + fp), 4) if tp + fp else None, precision_ci=wilson(tp, tp + fp),
                recall_other=round(tp / (tp + fn), 4) if tp + fn else None, recall_ci=wilson(tp, tp + fn))


def paired_diff(d: pd.DataFrame, a: pd.Series, b: pd.Series, n_boot=5000) -> dict:
    """Accuracy(a) - accuracy(b) on decided labels, bootstrap over records (sentences of a record move together)."""
    m = d.attr.isin(["o", "x"])
    y = (d.attr == "x")
    ca, cb = ((a == y) & m).astype(int), ((b == y) & m).astype(int)
    g = pd.DataFrame({"u": d.unique_id, "a": ca, "b": cb, "m": m.astype(int)}).groupby("u").sum()
    est = (g.a.sum() - g.b.sum()) / g.m.sum()
    idx = RNG.integers(0, len(g), size=(n_boot, len(g)))
    A, B, M = g.a.to_numpy()[idx].sum(1), g.b.to_numpy()[idx].sum(1), g.m.to_numpy()[idx].sum(1)
    diffs = (A - B) / M
    return dict(diff=round(float(est), 4), ci95=[round(float(np.quantile(diffs, 0.025)), 4), round(float(np.quantile(diffs, 0.975)), 4)])


def misattribution_weighted(d: pd.DataFrame, atoms: pd.DataFrame, bucket_of: dict) -> dict:
    """Share of counting (citable) unanchored/own atoms whose sentence is about another facility, weighted to the
    population by bucket stratum (strata were sampled at different rates)."""
    pop = atoms[atoms.counts_as_own].assign(bucket=lambda x: x.unique_id.map(bucket_of))
    pop["stratum"] = np.where(pop.ownership == "own_anchored", "own_anchored", "unanch_" + pop.bucket)
    sizes = pop.drop_duplicates("claim_id").stratum.value_counts()
    rows, tot, w_sum = {}, 0.0, 0.0
    for st, N in sizes.items():
        sub = d[d.stratum == st]
        r = rate(sub, "attr", "x", "o")
        rows[st] = dict(pop_sentences=int(N), **r)
        if r["n"]:
            tot += N * r["k"] / r["n"]
            w_sum += N
    return dict(by_stratum=rows, weighted_share_other=round(tot / w_sum, 4) if w_sum else None)


def main():
    d = load()
    atoms = pd.read_parquet(HERE / "claim_atoms.parquet", columns=["claim_id", "unique_id", "ownership", "counts_as_own"])
    pf = pd.read_parquet(HERE / "pair_features.parquet", columns=["unique_id", "bucket"]).drop_duplicates("unique_id")
    bucket_of = dict(zip(pf.unique_id, pf.bucket))
    d["attr_class"] = np.where(d.own_v1 == "unanchored", "ownership:unanchored|" + d.bucket, "ownership:" + d.own_v1)
    rule_v0 = ~d.own_v0.isin(OWN_CLASSES)    # sentence does not count as this facility's own evidence
    rule_v1 = ~d.own_v1.isin(OWN_CLASSES)
    llm_other = d.llm_about == "other_facility"
    out = {}
    for split in ["dev", "test", "all"]:
        x = d if split == "all" else d[d.split == split]
        o = {"n_sentences": len(x),
             "attribution_by_class": {c: rate(g, "attr", "o") for c, g in x.groupby("attr_class")},
             "support_by_role": {r: rate(g, "sup", "y", "n") for r, g in x.groupby("role")},
             "rules_v0_cleaning_attribution": classifier_report(x, rule_v0.loc[x.index]),
             "rules_v1_dev_tuned": classifier_report(x, rule_v1.loc[x.index]),
             "llm_about_other": classifier_report(x, llm_other.loc[x.index]),
             "rules_v1_or_llm": classifier_report(x, (rule_v1 | llm_other).loc[x.index]),
             "v1_minus_v0_accuracy": paired_diff(x, rule_v1.loc[x.index], rule_v0.loc[x.index]),
             "llm_minus_v1_accuracy": paired_diff(x, llm_other.loc[x.index], rule_v1.loc[x.index]),
             "support_rules_counting_role": rate(x[x.role.isin(["offer", "unit_or_equipment", "quantity"])], "sup", "y", "n"),
             "support_rules_noncounting_role": rate(x[~x.role.isin(["offer", "unit_or_equipment", "quantity"])], "sup", "y", "n")}
        sup_dec = x[x.sup.isin(["y", "n"])]
        rc = sup_dec.role.isin(["offer", "unit_or_equipment", "quantity"])
        lc = sup_dec.llm_offers == "yes"
        o["support_rules_accuracy"] = dict(k=int((rc == (sup_dec.sup == "y")).sum()), n=len(sup_dec),
                                           ci=wilson(int((rc == (sup_dec.sup == "y")).sum()), len(sup_dec)))
        o["support_llm_accuracy"] = dict(k=int((lc == (sup_dec.sup == "y")).sum()), n=len(sup_dec),
                                         ci=wilson(int((lc == (sup_dec.sup == "y")).sum()), len(sup_dec)))
        o["misattribution_among_citable"] = misattribution_weighted(x, atoms, bucket_of)
        out[split] = o
    (HERE / "sentence_metrics.json").write_text(json.dumps(out, indent=1, default=float))

    # display rates: all hand labels of this check plus the earlier audit hand checks for reference
    rows = []
    for c, g in d.groupby("attr_class"):
        r = rate(g, "attr", "o")
        rows.append(dict(**{"class": c}, kind="attribution", k=r["k"], n=r["n"], unclear=r["unclear"], wilson_lo=r["wilson_lo"],
                         wilson_hi=r["wilson_hi"], source_file="model/proto/evidence/sentence_labels.csv", use_for_display=r["n"] > 0))
    for c, g in d.groupby("role"):
        r = rate(g, "sup", "y", "n")
        rows.append(dict(**{"class": f"role:{c}"}, kind="support", k=r["k"], n=r["n"], unclear=r["unclear"], wilson_lo=r["wilson_lo"],
                         wilson_hi=r["wilson_hi"], source_file="model/proto/evidence/sentence_labels.csv", use_for_display=r["n"] > 0))
    seeds = [("seed:core_topic", "support", 196, 200, "audit/claims/out/handcheck_summary.json"),
             ("seed:nonoffer_v2_cue_correct", "support", 34, 40, "audit/claims/out/handcheck_summary.json"),
             ("seed:named_other_v3", "attribution", 9, 40, "audit/claims/out/handcheck_summary.json"),
             ("seed:cross_state_place_B", "attribution", 8, 14, "audit/claims/out/handcheck_summary.json"),
             ("seed:cleaning_other_facility_TP", "attribution", 17, 23, "cleaning/claims/out/handcheck.json"),
             ("seed:cleaning_unanchored_in_contaminated_own", "attribution", 18, 20, "cleaning/claims/out/handcheck.json"),
             ("seed:cleaning_nonoffer_correct", "support", 14, 15, "cleaning/claims/out/handcheck.json")]
    for c, kind, k, n, src in seeds:
        lo, hi = wilson(k, n)
        rows.append({"class": c, "kind": kind, "k": k, "n": n, "unclear": None, "wilson_lo": lo, "wilson_hi": hi,
                     "source_file": src, "use_for_display": False})
    pd.DataFrame(rows).to_csv(HERE / "attribution_rates.csv", index=False)
    for split in ["dev", "test"]:
        o = out[split]
        print(f"== {split} ({o['n_sentences']} sentences)")
        for k in ["rules_v0_cleaning_attribution", "rules_v1_dev_tuned", "llm_about_other", "rules_v1_or_llm"]:
            print(f"  {k}: {o[k]}")
        print("  v1 - v0:", o["v1_minus_v0_accuracy"], " llm - v1:", o["llm_minus_v1_accuracy"])
        print("  support rules:", o["support_rules_accuracy"], "llm:", o["support_llm_accuracy"])
        print("  misattribution among citable:", o["misattribution_among_citable"]["weighted_share_other"])
        for c, r in o["attribution_by_class"].items():
            print(f"   attr {c}: {r['k']}/{r['n']} (+{r['unclear']} unclear) {r['wilson_lo']}-{r['wilson_hi']}")
        for c, r in o["support_by_role"].items():
            print(f"   sup {c}: {r['k']}/{r['n']} (+{r['unclear']} unclear)")


if __name__ == "__main__":
    main()

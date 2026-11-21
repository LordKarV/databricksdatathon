"""Step 6: final data-point scores and the published tables (data_point_scores, source_domains, source_classes,
source_urls, facility_trust). Original values are copied, never changed.

Score of an unverified data point (logit scale):
    s = logit q_ev + GAMMA * (logit sigma_d - mean logit sigma for its type)
    90% interval: s +- 1.645 * sqrt(1/a + 1/b + GAMMA^2 * sum_s w_sd^2 (1/alpha_s + 1/beta_s))
    (a, b = Beta posterior of the evidence rule; alpha_s, beta_s = Beta posterior of each source).
Verified points: gold 'confirmed'/'yes' -> 0.97 [0.90, 0.995]; gold 'contradicted'/'no' -> 0.03 [0.005, 0.10];
the deterministic placeholder email -> 0.01 [0.001, 0.03]. Gold TEST verdicts are applied here (they are
facts the app should show) but were not used to fit sources; score_model keeps the pre-override score.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from s5_fit import GAMMA, expit, logit
from ss_common import OUT, ROOT, WORK

Z90 = 1.645
VERIFIED = {"true": (0.97, 0.90, 0.995), "false": (0.03, 0.005, 0.10), "deterministic_false": (0.01, 0.001, 0.03)}
RULE_SCRIPT = {"location": "cleaning/geo_identity/s2_facility_location.py", "existence": "model/gold/labels_*.json",
               "service_claim": "cleaning/claims/grade.py (v2, quarantine on)", "claim_attribution": "cleaning/claims/build_claims.py + audit/merge/detect.py",
               "phone": "cleaning/geo_identity/s5_trust.py", "email": "cleaning/geo_identity/s5_trust.py"}


def score_points(dp: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    ab = rules.set_index("rule")[["a", "b", "citation"]]
    a, b = dp.rule.map(ab.a).to_numpy(float), dp.rule.map(ab.b).to_numpy(float)
    s = logit(dp.q_ev.to_numpy(float)) + GAMMA * dp.source_logit_shift.to_numpy(float)
    sd = np.sqrt(1 / a + 1 / b + GAMMA ** 2 * dp.source_var.to_numpy(float))
    dp = dp.assign(score_model=expit(s), score=expit(s), score_lo=expit(s - Z90 * sd), score_hi=expit(s + Z90 * sd))
    gt = dp.gold_true.astype("boolean")
    status = np.where(gt.fillna(False), "verified_true", np.where((~gt).fillna(False), "verified_false", "unverified"))
    det = (dp.rule == "EMAIL_PLACEHOLDER").to_numpy()
    status = np.where(det, "verified_false", status)
    dp["status"] = status
    for key, m in (("true", status == "verified_true"), ("false", (status == "verified_false") & ~det), ("deterministic_false", det)):
        dp.loc[m, ["score", "score_lo", "score_hi"]] = VERIFIED[key]
    # reason codes and evidence references
    rc = dp.rule.copy()
    rc = rc.where(~gt.fillna(False).to_numpy(), "GOLD_TRUE|" + rc)
    rc = rc.where(~(~gt).fillna(False).to_numpy(), "GOLD_FALSE|" + rc)
    shift = dp.source_logit_shift
    rc = rc + np.where(shift > 0.3, "|SOURCES_ABOVE_AVERAGE", np.where(shift < -0.3, "|SOURCES_BELOW_AVERAGE", ""))
    rc = rc + np.where(dp.page_attributed, "|PAGE_CHECKED", "")
    dp["reason_codes"] = rc
    cite = dp.rule.map(ab.citation) + " ; script: " + dp.dp_type.map(RULE_SCRIPT)
    dp["evidence_refs"] = np.where(dp.gold_ref.notna(), "gold: " + dp.gold_ref.fillna("") + " ; " + cite, "audit rule " + dp.rule + ": " + cite)
    return dp


def domain_table(u: pd.DataFrame, fd: pd.DataFrame, bt: pd.DataFrame, dp: pd.DataFrame) -> pd.DataFrame:
    rd = u.drop_duplicates(["unique_id", "domain"])[["unique_id", "domain"]]
    fit = dp[dp.fit_strength > 0]
    per_rec = pd.DataFrame({
        "vt": fit[(fit.fit_fixed_q > 0.5)].groupby("unique_id").size(),
        "vf": fit[(fit.fit_fixed_q < 0.5)].groupby("unique_id").size(),
        "flag": fit[fit.fit_fixed_q.isna() & (fit.q_ev < 0.5)].groupby("unique_id").size(),
        "test": dp[(dp.gold_split == "test") & dp.gold_true.notna()].groupby("unique_id").size()}).fillna(0)
    agg = rd.join(per_rec, on="unique_id").fillna(0).groupby("domain")[["vt", "vf", "flag", "test"]].sum().astype(int)
    base = u.groupby("domain").agg(n_records=("unique_id", "nunique"), n_urls=("url", "size"), n_distinct_urls=("url", "nunique"),
                                   share_about=("url_kind", lambda s: round(float((s == "about").mean()), 3)),
                                   share_list=("url_kind", lambda s: round(float((s == "list").mean()), 3)),
                                   class_mix=("source_class", lambda s: json.dumps(s.value_counts().head(3).to_dict())))
    top = bt.loc[bt.groupby("domain").blame.idxmax(), ["domain", "dp_type", "blame"]].set_index("domain")
    tot_blame = bt.groupby("domain").blame.sum()
    d = fd.set_index("domain").join(base).join(agg).rename(columns={"vt": "n_verified_true", "vf": "n_verified_false",
                                                                     "flag": "n_flagged_false", "test": "n_test_gold_points"})
    d["top_blame_type"] = top.dp_type
    d["top_blame_share"] = (top.blame / tot_blame.replace(0, np.nan)).round(3)
    pc_path = OUT / "source_page_checks.parquet"
    if pc_path.exists():
        pc = pd.read_parquet(pc_path)
        pu = pc.drop_duplicates("url").groupby("domain").agg(page_urls_checked=("url", "size"),
                                                              page_urls_fetched=("fetch_status", lambda s: int(s.str.startswith("ok").sum())))
        ps = pc[pc.claim_id.notna()].groupby("domain").agg(page_sentences_tested=("claim_id", "size"), page_sentences_supported=("supported", "sum"))
        d = d.join(pu).join(ps)
    d["reason"] = [reason(r) for r in d.itertuples()]
    return d.reset_index().sort_values("n_records", ascending=False)


def reason(r) -> str:
    rel = "above" if r.ci05 > r.class_prior_mean else "below" if r.ci95 < r.class_prior_mean else "close to"
    s = (f"Cited by {r.n_records} records ({r.n_urls} URLs, {r.share_about:.0%} about-pages, {r.share_list:.0%} list pages); "
         f"class {r.source_class} (class mean {r.class_prior_mean:.2f}). Reliability {r.reliability:.2f} "
         f"(90% {r.ci05:.2f}-{r.ci95:.2f}), {rel} its class.")
    if r.n_records < 5:
        s += " Few records, so the estimate is mostly the class prior."
    s += f" Touches {r.n_verified_true} verified-true and {r.n_verified_false} verified-false points (gold dev labels and placeholder emails) and {r.n_flagged_false} audit-flagged points."
    if r.blame > 0.05 and isinstance(r.top_blame_type, str):
        s += f" Most blame comes from {r.top_blame_type.replace('_', ' ')} points ({r.top_blame_share:.0%})."
    return s


def class_table(u: pd.DataFrame, d: pd.DataFrame, s5: dict) -> pd.DataFrame:
    """Per URL class (as assigned per record by domains.classify): pooled credit/blame of its modal domains."""
    rng = np.random.default_rng(7)
    rows = []
    for c, g in d.groupby("source_class"):
        a, b = 1 + g.credit.sum(), 1 + g.blame.sum()
        lo, hi = np.quantile(rng.beta(a, b, 20000), [0.05, 0.95])
        uc = u[u.source_class == c]
        rows.append(dict(source_class=c, n_domains=len(g), n_urls=len(uc), n_records=uc.unique_id.nunique(),
                         reliability=a / (a + b), ci05=lo, ci95=hi,
                         median_domain_reliability=float(g.reliability.median()),
                         domain_reliability_p10=float(g.reliability.quantile(0.1)), domain_reliability_p90=float(g.reliability.quantile(0.9)),
                         n_verified_true=int(g.n_verified_true.sum()), n_verified_false=int(g.n_verified_false.sum()),
                         effective_true=float(g.credit.sum()), effective_false=float(g.blame.sum())))
    return pd.DataFrame(rows).sort_values("reliability", ascending=False)


def facility_table(dp: pd.DataFrame, edges: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    tr = pd.read_parquet(ROOT / "cleaning/geo_identity/record_trust.parquet").set_index("unique_id")
    def pick(t: str) -> pd.DataFrame:
        x = dp[dp.dp_type == t].set_index("unique_id")
        return x[["score", "score_lo", "score_hi", "status", "reason_codes"]]
    ex, lo = pick("existence"), pick("location")
    s = dp[dp.dp_type == "claim_attribution"].groupby("unique_id").agg(
        n_sentences=("dp_id", "size"), attribution_score=("score", "mean"),
        n_sentences_other_facility=("rule", lambda r: int((r == "ATTR_OTHER_FACILITY").sum())))
    sv = dp[dp.dp_type == "service_claim"].groupby("unique_id").agg(
        n_service_claims=("dp_id", "size"), service_score_mean=("score", "mean"),
        n_service_verified_true=("status", lambda x: int((x == "verified_true").sum())),
        n_service_verified_false=("status", lambda x: int((x == "verified_false").sum())))
    e = edges[edges.group.str.startswith("rec:identity:")].copy()
    e["w"] = e.w / e.groupby("unique_id").w.transform("sum")
    e = e.merge(d[["domain", "reliability"]], on="domain")
    top = e.sort_values("w", ascending=False).groupby("unique_id").head(3)
    top_json = top.groupby("unique_id").apply(lambda g: json.dumps([dict(domain=a, weight=round(w, 3), reliability=round(r, 3))
                                                                     for a, w, r in zip(g.domain, g.w, g.reliability)]), include_groups=False)
    supp = e.assign(x=e.w * e.reliability).groupby("unique_id").x.sum()
    f = pd.DataFrame(index=ex.index)
    f["name"] = tr.name
    f["existence_score"], f["existence_status"] = ex.score, ex.status
    f["location_score"], f["location_lo"], f["location_hi"], f["location_status"] = lo.score, lo.score_lo, lo.score_hi, lo.status
    f["location_reason_codes"] = lo.reason_codes
    f = f.join(s).join(sv)
    cnt = ["n_sentences", "n_sentences_other_facility", "n_service_claims", "n_service_verified_true", "n_service_verified_false"]
    f[cnt] = f[cnt].fillna(0).astype(int)
    f["attribution_score"] = f.attribution_score.fillna(1.0)  # no claim sentences: nothing to misattribute
    f["source_support"] = supp
    f["top_sources"] = top_json
    f["overall_score"] = f.existence_score * f.location_score * f.attribution_score
    f["overall_lo"] = ex.score_lo * lo.score_lo * f.attribution_score
    f["trust_level_cleaning"] = tr.trust_level
    f["drivers"] = [drivers(r, tr.trust_reasons.get(u, [])) for u, r in f.iterrows()]
    return f.reset_index()


def drivers(r: pd.Series, trust_reasons: list) -> str:
    out = []
    codes = str(r.location_reason_codes)
    if "GOLD_FALSE" in codes:
        out.append("web check found the location wrong")
    elif "LOC_CITY_ELSEWHERE" in codes:
        out.append("address city points elsewhere than PIN and coordinates")
    elif "LOC_COORDS_FAR" in codes:
        out.append("listing coordinates more than 50 km from the PIN")
    if r.n_sentences_other_facility:
        out.append(f"{int(r.n_sentences_other_facility)} sentences name another facility")
    if r.n_service_verified_false:
        out.append(f"{int(r.n_service_verified_false)} service claims contradicted by web check")
    if "SOURCES_BELOW_AVERAGE" in codes:
        out.append("its sources are less reliable than average")
    out += list(trust_reasons)[:2]
    return "; ".join(out) if out else "no concerns found"


def main() -> None:
    u = pd.read_parquet(WORK / "record_urls.parquet")
    dp = pd.read_parquet(WORK / "dp_fit.parquet")
    rules = pd.read_parquet(WORK / "evidence_rules.parquet")
    fd = pd.read_parquet(WORK / "fit_domains.parquet")
    bt = pd.read_parquet(WORK / "fit_blame_by_type.parquet")
    edges = pd.read_parquet(WORK / "fit_edges.parquet")
    s5 = json.loads((WORK / "s5_stats.json").read_text())
    dp = score_points(dp, rules)
    d = domain_table(u, fd, bt, dp)
    c = class_table(u, d, s5)
    f = facility_table(dp, edges, d)
    pc_path = OUT / "source_page_checks.parquet"
    su = u.merge(d[["domain", "reliability", "ci05", "ci95"]].rename(columns={"reliability": "domain_reliability"}), on="domain", how="left")
    if pc_path.exists():
        pc = pd.read_parquet(pc_path)
        pcu = pc.groupby(["unique_id", "url"]).agg(page_fetch_status=("fetch_status", "first"),
                                                   page_sentences_tested=("claim_id", "count"),
                                                   page_sentences_supported=("supported", lambda s: int(s.fillna(False).sum()))).reset_index()
        su = su.merge(pcu, on=["unique_id", "url"], how="left")
    keep = ["dp_id", "dp_type", "unique_id", "claim_id", "service", "field", "original_value", "score", "score_lo", "score_hi",
            "status", "reason_codes", "evidence_refs", "rule", "q_ev", "source_support", "score_model", "gold_split", "grade", "attribution"]
    dp[keep].to_parquet(OUT / "data_point_scores.parquet", index=False, compression="zstd")
    d.to_parquet(OUT / "source_domains.parquet", index=False)
    c.to_parquet(OUT / "source_classes.parquet", index=False)
    su.to_parquet(OUT / "source_urls.parquet", index=False, compression="zstd")
    f.to_parquet(OUT / "facility_trust.parquet", index=False)
    d.to_csv(OUT / "source_domains.csv", index=False)
    c.to_csv(OUT / "source_classes.csv", index=False)
    f.to_csv(OUT / "facility_trust.csv", index=False)
    st = {"data_points": dp.dp_type.value_counts().to_dict(),
          "status_by_type": dp.groupby("dp_type").status.value_counts().unstack(fill_value=0).to_dict("index"),
          "verified_false_by_source": {"gold_dev": int(((dp.status == "verified_false") & (dp.gold_split == "dev")).sum()),
                                       "gold_test": int(((dp.status == "verified_false") & (dp.gold_split == "test")).sum()),
                                       "deterministic": int((dp.rule == "EMAIL_PLACEHOLDER").sum())}}
    (WORK / "s6_stats.json").write_text(json.dumps(st, indent=1, default=int))
    print(json.dumps(st, indent=1, default=int))
    cols = ["domain", "source_class", "n_records", "n_urls", "reliability", "ci05", "ci95", "n_verified_true", "n_verified_false"]
    big = d[d.n_records >= 30]
    print("most reliable (n_records>=30)\n", big.sort_values("reliability", ascending=False).head(10)[cols].to_string(index=False))
    print("least reliable (n_records>=30)\n", big.sort_values("reliability").head(10)[cols].to_string(index=False))
    print(c[["source_class", "n_domains", "n_urls", "reliability", "ci05", "ci95", "median_domain_reliability"]].to_string(index=False))


if __name__ == "__main__":
    main()

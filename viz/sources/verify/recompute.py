"""Independent recomputation of the six "Who said so?" headline numbers.

Written separately from the story scripts: it does not import _common.py or any s*.py, re-derives the
record set and URL counts from data/raw/facilities.parquet where it can, uses its own interval code
(statsmodels Wilson, multinomial cluster bootstrap), and adds robustness checks the stories did not run
(finer size strata, claim-count control). No gold label is read.
Run: .venv-viz/bin/python viz/sources/verify/recompute.py  -> prints a report and writes verify/results.json
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.proportion import proportion_confint

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = Path(__file__).parent
OUT = {}
rng = np.random.default_rng(7)  # different seed from the stories on purpose


def wil(k, n):
    lo, hi = proportion_confint(k, n, method="wilson")
    return round(100 * k / n, 2), round(100 * lo, 2), round(100 * hi, 2)


def boot_cluster(df, flag, cluster, B=4000):
    """Multinomial bootstrap of whole clusters (the stories used a Poisson bootstrap)."""
    g = df.groupby(cluster)[flag].agg(["sum", "size"])
    k, n = g["sum"].to_numpy(float), g["size"].to_numpy(float)
    idx = rng.integers(0, len(g), (B, len(g)))
    r = k[idx].sum(1) / n[idx].sum(1)
    return round(100 * k.sum() / n.sum(), 2), *np.round(100 * np.percentile(r, [2.5, 97.5]), 2), int(k.sum()), int(n.sum()), len(g)


# ------------------------------------------------------------------ story 1, from the raw table
raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet")
uuid = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
raw = raw[(raw.source == "kie") & raw.unique_id.str.match(uuid, na=False)].drop_duplicates()


def urls_of(s):
    try:
        v = json.loads(s) if isinstance(s, str) and s.startswith("[") else []
    except ValueError:
        v = []
    return [x.strip() for x in v if isinstance(x, str) and x.strip()]


n_per = raw.source_urls.map(lambda s: len(urls_of(s)))
allurls = [u for s in raw.source_urls for u in urls_of(s)]
hosts = pd.Series([re.sub(r"^www\.", "", re.sub(r"^[a-z]+://", "", u.lower()).split("/")[0].split(":")[0]) for u in allurls])
fb_recs = sum(any("facebook.com" in u.lower().split("/")[2 if "://" in u else 0] for u in urls_of(s)) for s in raw.source_urls)
su = pd.read_parquet(ROOT / "derived/v1/source_urls.parquet", columns=["unique_id", "domain", "source_class", "url_kind"])
cls = su.source_class.value_counts()
kind = su.url_kind.value_counts()
OUT["s1"] = dict(records=len(raw), urls_raw=len(allurls), urls_table=len(su),
                 per_record_counts_match=bool((su.groupby("unique_id").size().reindex(raw.unique_id).fillna(0).to_numpy() == n_per.to_numpy()).all()),
                 median_urls=float(n_per.median()), at_50=int((n_per == 50).sum()), over_50=int((n_per > 50).sum()),
                 practo_host_urls=int(hosts.str.endswith("practo.com").sum()), facebook_records_raw=int(fb_recs),
                 pct_class={k: round(100 * v / len(su), 2) for k, v in cls.items()},
                 n_class={k: int(v) for k, v in cls.items()},
                 pct_kind={k: round(100 * v / len(su), 2) for k, v in kind.items()},
                 n_kind={k: int(v) for k, v in kind.items()},
                 own_site_incl_likely_pct=round(100 * (cls["official"] + cls["official_like"]) / len(su), 2))

# ------------------------------------------------------------------ story 2
sc = pd.read_parquet(ROOT / "derived/v1/source_classes.parquet").set_index("source_class")
from scipy.stats import beta as B_  # noqa: E402
a, b = 1 + sc.effective_true, 1 + sc.effective_false
OUT["s2_panelA"] = {c: [round(a[c] / (a[c] + b[c]), 3), round(B_.ppf(.025, a[c], b[c]), 3), round(B_.ppf(.975, a[c], b[c]), 3),
                        round(sc.reliability[c], 3)] for c in ["social", "official", "health_aggregator"]}
OUT["s2_rank_social"] = int(sc.reliability.rank(ascending=False)["social"])
R = pd.read_parquet(ROOT / "audit/provenance/q1_records.parquet")
classcols = [c for c in R.columns if c.startswith("n_") and c[2:] in sc.index]
OUT["s2_classcols_sum_eq_n_urls"] = bool((R[classcols].sum(axis=1) == R.n_urls).all())
dirty = R.p3c_foreign_claim.fillna(False).astype(bool) | R.p4_coord_far_from_pin.fillna(False).astype(bool)
R["clean"] = (~dirty).astype(float)
R["band"] = pd.cut(R.n_urls, [0, 5, 10, 20, 50], labels=["1-5", "6-10", "11-20", "21-50"])
s2 = {}
for c in ["social", "official", "health_aggregator"]:
    w = R[f"n_{c}"] / R.n_urls
    row = {"pooled": round(100 * (w * R.clean).sum() / w.sum(), 2)}
    for bd, g in R.groupby("band", observed=True):
        wg = w[g.index]
        row[bd] = round(100 * (wg * g.clean).sum() / wg.sum(), 2)
        row[f"share_{bd}"] = round(100 * wg.sum() / w.sum(), 1)
    # finer control: direct standardisation over exact URL count (1..50) to the all-record size mix
    per = R.assign(w=w, wy=w * R.clean).groupby("n_urls")[["w", "wy"]].sum()
    mix = R.n_urls.value_counts(normalize=True)
    ok = per.w > 0
    row["std_exact_size"] = round(100 * ((per.wy[ok] / per.w[ok]) * mix[per.index[ok]]).sum() / mix[per.index[ok]].sum(), 2)
    s2[c] = row
# bootstrap the within-band social minus aggregator gap and the exact-size standardised gap (records resampled)
ws, wa = (R.n_social / R.n_urls).to_numpy(), (R.n_health_aggregator / R.n_urls).to_numpy()
y, nb = R.clean.to_numpy(), R.n_urls.to_numpy()
mix = np.bincount(nb, minlength=51) / len(nb)
def std_rate(idx, w):
    num = np.bincount(nb[idx], weights=w[idx] * y[idx], minlength=51)
    den = np.bincount(nb[idx], weights=w[idx], minlength=51)
    ok = den > 0
    return (num[ok] / den[ok] * mix[ok]).sum() / mix[ok].sum()
gaps = []
for _ in range(1000):
    idx = rng.integers(0, len(R), len(R))
    gaps.append(std_rate(idx, ws) - std_rate(idx, wa))
full = std_rate(np.arange(len(R)), ws) - std_rate(np.arange(len(R)), wa)
s2["std_gap_social_minus_agg_pts"] = [round(100 * full, 2), *np.round(100 * np.percentile(gaps, [2.5, 97.5]), 2)]
s2["band_flag_rate"] = {bd: round(100 * (1 - g.clean.mean()), 1) for bd, g in R.groupby("band", observed=True)}
OUT["s2"] = s2

# ------------------------------------------------------------------ story 3
pc = pd.read_parquet(ROOT / "derived/v1/source_page_checks.parquet")
t = pc[pc.claim_id.notna()].copy()
t["sup"], t["tok"] = t.supported.astype(bool), t.token_supported.astype(bool)
s3 = {"urls_sampled": int(pc.url.nunique()), "pages_tested": int(t.url.nunique()), "tests": len(t),
      "tok_superset_of_sup": bool((t.tok | ~t.sup).all())}
for key, g in [("all", t)] + list(t.groupby("stratum")):
    s3[key] = {"wording": boot_cluster(g, "sup", "url"), "most_words": boot_cluster(g, "tok", "url")}
# Are tested sentences tied to the page? No: page checks test the record's sentences, not sentences sourced from that page.
cl = pd.read_parquet(ROOT / "derived/v1/claims.parquet", columns=["claim_id", "unique_id", "text"])
ex = t.merge(cl, on=["claim_id", "unique_id"])
ex = ex[(ex.domain == "kimayaheart.com") & ex.text.str.startswith("Interventional cardiology")]
s3["example"] = ex[["text", "partial_ratio", "token_coverage"]].head(1).to_dict("records")
s3["urls_per_unique_record_pairs_dupe"] = int(pc.drop_duplicates(["url", "unique_id"]).shape[0])
OUT["s3"] = s3

# ------------------------------------------------------------------ story 4
f = R.p3c_foreign_claim.astype(bool)
s4 = {}
for key, has in [("research", R.n_research > 0), ("list", R.n_url_list > 0)]:
    d = {"with": wil(int(f[has].sum()), int(has.sum())) + (int(f[has].sum()), int(has.sum())),
         "without": wil(int(f[~has].sum()), int((~has).sum())) + (int(f[~has].sum()), int((~has).sum()))}
    # four-band indirect standardisation as in the story, then exact-URL-count, then URL count x claim-count quartile
    for name, strata in [("bands4", pd.cut(R.n_urls, [0, 10, 20, 30, 50])),
                         ("exact_urls", R.n_urls),
                         ("urls_x_claims", pd.cut(R.n_urls, [0, 10, 20, 30, 49, 50]).astype(str) + "|" +
                          pd.qcut(R.n_claims, 4, duplicates="drop").astype(str))]:
        strata = strata.astype(str)
        rate_wo = f[~has].groupby(strata[~has]).mean()
        exp_ = strata[has].map(rate_wo).astype(float)
        cover = exp_.notna()
        obs = f[has][cover].mean()
        exp = exp_[cover].mean()
        base = f[~has].mean()
        d[name] = dict(observed=round(100 * obs, 2), expected=round(100 * exp, 2),
                       share_of_gap_from_strata=round((exp - base) / (obs - base), 3), with_records_covered=int(cover.sum()))
    at50 = R.n_urls == 50
    d["exactly_50_urls"] = dict(with_=wil(int(f[has & at50].sum()), int((has & at50).sum())) + (int((has & at50).sum()),),
                                without=wil(int(f[~has & at50].sum()), int((~has & at50).sum())) + (int((~has & at50).sum()),))
    b4 = pd.cut(R.n_urls, [0, 10, 20, 30, 50], labels=["1-10", "11-20", "21-30", "31-50"])
    d["by_band"] = {bd: dict(with_=wil(int(f[has & (b4 == bd)].sum()), int((has & (b4 == bd)).sum())) + (int((has & (b4 == bd)).sum()),),
                             without=wil(int(f[~has & (b4 == bd)].sum()), int((~has & (b4 == bd)).sum())) + (int((~has & (b4 == bd)).sum()),))
                    for bd in ["1-10", "11-20", "21-30", "31-50"]}
    s4[key] = d
hr = R.n_research > 0
s4["lang"] = [int(R.n_research_lang_claims[hr].sum()), int(R.n_claims[hr].sum()),
              int(R.n_research_lang_claims[~hr].sum()), int(R.n_claims[~hr].sum())]
s4["median_urls"] = [float(R.n_urls[hr].median()), float(R.n_urls[~hr].median())]
s4["median_claims"] = [float(R.n_claims[hr].median()), float(R.n_claims[~hr].median())]
OUT["s4"] = s4

# ------------------------------------------------------------------ story 5
u1 = pc.groupby("url").agg(stratum=("stratum", "first"), status=("fetch_status", lambda s: "|".join(sorted(set(s)))))
s5 = {"urls": len(u1), "multi_status_urls": int(u1.status.str.contains(r"\|").sum()),
      "by_stratum_unreachable": {k: [int((g.status == "unreachable").sum()), len(g)] for k, g in u1.groupby("stratum")},
      "by_stratum_refused": {k: [int(g.status.isin(["blocked_http_403", "robots_disallowed", "login_redirect", "skipped_after_blocked"]).sum()), len(g)] for k, g in u1.groupby("stratum")}}
pt = pd.read_csv(HERE.parent / "s5_portal_types.csv")
s5["gov_types"] = {k: [int((g.fetch_status == "unreachable").sum()), len(g), wil(int((g.fetch_status == "unreachable").sum()), len(g))]
                   for k, g in pt.groupby("portal_type")}
OUT["s5"] = s5

# ------------------------------------------------------------------ story 6
dm = pd.read_parquet(ROOT / "derived/v1/source_domains.parquet")
rec_per_dom = su.groupby("domain").unique_id.nunique()
one = dm[dm.n_records == 1]
OUT["s6"] = dict(domains=len(dm), one_record=len(one), share=round(len(one) / len(dm), 4),
                 n_records_matches_urls_table=bool((rec_per_dom.reindex(dm.domain).to_numpy() == dm.n_records.to_numpy()).all()),
                 median_dev_one=round(float((one.reliability - one.class_prior_mean).abs().median()), 4),
                 median_ci90_one=round(float((one.ci95 - one.ci05).median()), 3),
                 n_100plus=int((dm.n_records >= 100).sum()),
                 median_dev_100plus=round(float((dm.reliability - dm.class_prior_mean).abs()[dm.n_records >= 100].median()), 4),
                 min_rel=round(float(dm.reliability.min()), 4), max_rel=round(float(dm.reliability.max()), 4),
                 top={d: [round(float(r), 3), round(float(l), 3), round(float(h), 3), int(n)] for d, r, l, h, n in
                      dm[dm.domain.isin(["facebook.com", "justdial.com", "practo.com", "onefivenine.com"])][["domain", "reliability", "ci05", "ci95", "n_records"]].itertuples(index=False)},
                 sd_rel_one=round(float(one.reliability.std()), 4), sd_prior_one=round(float(one.class_prior_mean.std()), 4),
                 corr_rel_prior_one=round(float(np.corrcoef(one.reliability, one.class_prior_mean)[0, 1]), 4))

(HERE / "results.json").write_text(json.dumps(OUT, indent=1, default=str))
print(json.dumps(OUT, indent=1, default=str))


# ------------------------------------------------------------------ extra checks (appended after the first pass)
EXTRA = {}
# Story 5 population: own re-implementation of the page-kind rule from its written description (host is a
# .gov.in/.nic.in/.edu.in/.ac.in host; "public-utilit" in path = district directory; scheme keywords in host+path).
KEYS = ["esic", "hryesi", "cghs", "pmjay", "ayushman", "cashless", "empanel", "arogya", "swasthya", "pcpndt", "kpme",
        "transtan", "sotto", "notto", "covidcbrs", "atalamrit", "asbtc", "blood", "hosplist", "registeredhospital"]
gv = pd.read_parquet(ROOT / "derived/v1/source_urls.parquet", columns=["unique_id", "url", "source_class"])
gv = gv[gv.source_class == "government"].copy()
def kind5(u):
    rest = re.sub(r"^[a-z]+://", "", u.lower())
    h = rest.split("/")[0].split(":")[0].removeprefix("www.")
    p = rest[len(rest.split("/")[0]):]
    if not any(h.endswith(s) for s in (".gov.in", ".nic.in", ".edu.in", ".ac.in")):
        return "misfiled"
    if "public-utilit" in p:
        return "district"
    if any(k in h + p for k in KEYS) or h == "ors.gov.in" or h.endswith(".ors.gov.in"):
        return "scheme"
    return "other"
gv["k"] = gv.url.map(kind5)
EXTRA["s5_population"] = gv.groupby("k").agg(urls=("url", "size"), records=("unique_id", "nunique")).to_dict("index")
EXTRA["s5_gov_urls_total"] = len(gv)
# Story 3 example as quoted
e3 = t.merge(cl, on=["claim_id", "unique_id"])
e3 = e3[e3.text.str.startswith("Interventional cardiology program with Dr")]
EXTRA["s3_example"] = e3[["domain", "text", "partial_ratio", "token_coverage", "snippet"]].to_dict("records")
# Story 3 framing check: how were sentences chosen? share of tested sentences that are service sentences
EXTRA["s3_service_sentence_share"] = round(float(t.is_service_sentence.astype(bool).mean()), 3)
# Story 2 mechanism: across the 16 classes, does the published reliability track how much of the class's
# citation weight sits in small (1-5 URL) records?
sh = {}
for c in sc.index:
    w = R[f"n_{c}"] / R.n_urls
    sh[c] = float(w[R.n_urls <= 5].sum() / w.sum())
from scipy.stats import spearmanr  # noqa: E402
rho = spearmanr(pd.Series(sh)[sc.index], sc.reliability)
EXTRA["s2_spearman_rel_vs_small_record_share"] = [round(float(rho.statistic), 3), round(float(rho.pvalue), 4), len(sc)]
EXTRA["s2_small_share_by_class"] = {c: round(v, 3) for c, v in sorted(sh.items(), key=lambda x: -x[1])}
OUT["extra"] = EXTRA
(HERE / "results.json").write_text(json.dumps(OUT, indent=1, default=str))
print(json.dumps(EXTRA, indent=1, default=str))

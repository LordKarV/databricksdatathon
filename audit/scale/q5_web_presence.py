"""Q5: web-presence / engagement fields: content, coverage, internal consistency, usefulness as an 'active' signal."""
import json
from collections import Counter
import pandas as pd
from common import df, num, jlist, NULLS

d = df()
N = len(d)
out = {"denominator_rows": N}
DATE_COLS = ["recency_of_page_update", "post_metrics_most_recent_social_media_post_date"]
NUM_COLS = ["distinct_social_media_presence_count", "number_of_facts_about_the_organization", "post_metrics_post_count",
            "engagement_metrics_n_followers", "engagement_metrics_n_likes", "engagement_metrics_n_engagements"]
BOOL_COLS = ["affiliated_staff_presence", "custom_logo_presence"]
nullish = lambda s: s.isna() | s.isin(NULLS)

for c in DATE_COLS:
    s = d[c]
    nn = ~nullish(s)
    p = pd.to_datetime(s.where(nn), format="%Y-%m-%d", errors="coerce")
    d[c + "_dt"] = p
    bad = nn & p.isna()
    out[c] = {"non_null": int(nn.sum()), "iso_date": int(p.notna().sum()), "non_iso": int(bad.sum()),
              "non_iso_values": s[bad].value_counts().head(15).to_dict(),
              "min": str(p.min().date()), "max": str(p.max().date()),
              "by_year": p.dt.year.value_counts().sort_index().astype(int).to_dict(),
              "top_dates": s[p.notna()].value_counts().head(6).to_dict(),
              "in_dec_2025": int(((p >= "2025-12-01") & (p <= "2025-12-31")).sum()),
              "after_2025_12_31": int((p > "2025-12-31").sum())}
for c in NUM_COLS:
    v = d[c].map(num)
    d[c + "_n"] = v
    out[c] = {"non_null": int(v.notna().sum()), "zero": int((v == 0).sum()),
              "p50_p90_p99_max": [float(x) for x in v.quantile([0.5, 0.9, 0.99]).tolist()] + [float(v.max())]}
for c in BOOL_COLS:
    out[c] = d[c].fillna("<SQL NULL>").value_counts().to_dict()

f = d["engagement_metrics_n_followers_n"]
out["followers_rounding"] = {"ge_1000": int((f >= 1000).sum()), "ge_1000_multiple_of_100": int(((f >= 1000) & (f % 100 == 0)).sum())}

# internal consistency
fb = ~nullish(d["facebookLink"])
smc = d["distinct_social_media_presence_count_n"]
pc = d["post_metrics_post_count_n"]
pdt = d["post_metrics_most_recent_social_media_post_date_dt"]
out["consistency"] = {
    "facebookLink_present": int(fb.sum()),
    "no_facebookLink_but_followers_gt_0": int((~fb & (f > 0)).sum()),
    "social_count_0_but_followers_gt_0": int(((smc == 0) & (f > 0)).sum()),
    "post_count_0_but_post_date_present": int(((pc == 0) & pdt.notna()).sum()),
    "post_count_gt_0_but_no_post_date": int(((pc > 0) & pdt.isna()).sum()),
    "post_date_present": int(pdt.notna().sum()),
}

# shared values across records point at a directory/aggregator page rather than the facility's own page
for c in ["engagement_metrics_n_followers", "engagement_metrics_n_likes"]:
    v = d[c + "_n"]
    big = v[v >= 10000]
    vc = big.value_counts()
    exact = big[big % 1000 != 0]  # round values like 10000 collide because "10K" was rounded, not because pages are shared
    evc = exact.value_counts()
    shared_vals = evc[evc >= 2].index
    out[c + "_ge_10000_shared_by_2plus_records"] = {
        "records_ge_10000": int(len(big)), "records_ge_10000_non_round": int(len(exact)),
        "non_round_records_whose_exact_value_is_shared": int(exact.isin(shared_vals).sum()),
        "examples": [[float(val), d.loc[v == val, "name"].tolist()[:4]] for val in list(shared_vals)[:6]]}
top = d.sort_values("engagement_metrics_n_followers_n", ascending=False).head(15)
out["top_followers"] = top[["unique_id", "name", "address_city", "engagement_metrics_n_followers_n"]].values.tolist()

# does presence track other quality proxies? (no ground truth for 'real and active')
d["n_urls"] = d["source_urls"].map(lambda v: len(set(jlist(v))))
d["has_site"] = ~nullish(d["officialWebsite"])
d["has_phone"] = ~nullish(d["officialPhone"])
g = d.groupby(pd.cut(smc, [-1, 0, 2, 4, 6, 20], labels=["0", "1-2", "3-4", "5-6", "7+"]), observed=True)
out["by_social_count"] = {str(k): {"rows": int(len(x)), "has_official_website_pct": round(100 * x["has_site"].mean(), 1),
                                   "has_official_phone_pct": round(100 * x["has_phone"].mean(), 1),
                                   "median_source_urls": float(x["n_urls"].median()),
                                   "post_date_2025_pct": round(100 * (x["post_metrics_most_recent_social_media_post_date_dt"].dt.year == 2025).mean(), 1)}
                          for k, x in g}
rec = d["recency_of_page_update_dt"]
pdy = pdt.dt.year
out["activity_tiers"] = {
    "post_date_in_2025": int((pdy == 2025).sum()),
    "post_date_2023_2024": int(pdy.isin([2023, 2024]).sum()),
    "post_date_before_2023": int((pdy < 2023).sum()),
    "no_post_date": int(pdt.isna().sum()),
    "page_update_in_2025": int((rec.dt.year == 2025).sum()),
    "neither_post_nor_page_date": int((pdt.isna() & rec.isna()).sum()),
}
json.dump(out, open("/Users/karthikvattem/projects/datathon/audit/scale/q5_web_presence.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))

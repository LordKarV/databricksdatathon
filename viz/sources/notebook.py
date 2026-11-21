# Databricks notebook source
# MAGIC %md
# MAGIC # Who said so? Source stories
# MAGIC Six charts on where the facility records' evidence comes from. Each cell writes a PNG, SVG, alt-text TXT and tidy CSV to `OUT`. Story notes: `viz/sources/STORIES.md`.

# COMMAND ----------

# Config: inputs come from local parquet unless UC_SCHEMA is set.
# Config and shared helpers for the "Who said so?" source stories.
# make_notebook.py copies this file verbatim into the first cell of notebook.py.
import json
import math
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
OUT = ROOT / "viz" / "sources"
sys.path.insert(0, str(ROOT / "viz"))
import style as S  # noqa: E402

# Set UC_SCHEMA (for example "workspace.referral_saathi") to read the same tables from Unity Catalog
# with spark.table(); None reads the local parquet files below.
UC_SCHEMA = None
INPUTS = {
    "source_urls": ROOT / "derived/v1/source_urls.parquet",
    "source_classes": ROOT / "derived/v1/source_classes.parquet",
    "source_domains": ROOT / "derived/v1/source_domains.parquet",
    "source_page_checks": ROOT / "derived/v1/source_page_checks.parquet",
    "claims": ROOT / "derived/v1/claims.parquet",
    "q1_records": ROOT / "audit/provenance/q1_records.parquet",
    "handcheck_research_lang": ROOT / "audit/provenance/handcheck_research_lang.csv",
}
SEED = 20261121
N_BOOT = 2000


def load(name, columns=None):
    """One input table as pandas, from Unity Catalog when UC_SCHEMA is set, else local parquet."""
    if UC_SCHEMA:
        sdf = spark.table(f"{UC_SCHEMA}.{name}")  # noqa: F821  (spark exists on Databricks)
        return (sdf.select(*columns) if columns else sdf).toPandas()
    path = INPUTS[name]
    if path.suffix == ".csv":
        return pd.read_csv(path, usecols=columns)
    return pd.read_parquet(path, columns=columns)


def src(*names):
    """Source line for a chart: the files each input came from."""
    return "Source: " + "; ".join(str(INPUTS[n].relative_to(ROOT)) for n in names)


PRETTY = {
    "health_aggregator": "Health aggregators", "social": "Social media", "official": "Facility's own site",
    "business_dir": "Business directories", "other_health_site": "Other health sites", "other": "Unclassified",
    "insurance_scheme": "Insurance and scheme lists", "maps_geo": "Maps", "official_like": "Own site (likely)",
    "government": "Government portals", "research": "Research papers", "wikipedia": "Wikipedia",
    "news": "News", "education": "Education sites", "docs_repo": "Document hosts",
    "crowdfunding_ngo": "Crowdfunding and NGO",
}

SIZE_BANDS = [0, 5, 10, 20, 50]
SIZE_LABELS = ["1-5", "6-10", "11-20", "21-50"]


def size_band(n_urls):
    return pd.cut(n_urls, SIZE_BANDS, labels=SIZE_LABELS)


def weighted_rate_ci(y, w, n_boot=N_BOOT, seed=SEED):
    """Weighted mean of 0/1 outcome y with weights w, and a 95% Poisson-bootstrap interval over rows."""
    y, w = np.asarray(y, float), np.asarray(w, float)
    keep = w > 0
    y, w = y[keep], w[keep]
    p = (w * y).sum() / w.sum()
    rng = np.random.default_rng(seed)
    reps = []
    for _ in range(n_boot):
        k = rng.poisson(1.0, len(w))
        d = (k * w).sum()
        if d > 0:
            reps.append((k * w * y).sum() / d)
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return p, lo, hi


def cluster_rate_ci(df, flag, cluster, n_boot=N_BOOT, seed=SEED):
    """Rate of boolean column `flag` with a 95% bootstrap interval that resamples whole clusters."""
    g = df.groupby(cluster)[flag].agg(["sum", "size"])
    k, n = g["sum"].to_numpy(float), g["size"].to_numpy(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n_boot, len(g)))
    reps = k[idx].sum(1) / n[idx].sum(1)
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return k.sum() / n.sum(), lo, hi, int(k.sum()), int(n.sum()), len(g)


def write_csv(df, stem):
    path = OUT / f"{stem}.csv"
    df.to_csv(path, index=False)
    return path


# COMMAND ----------

# Story 1: what a record's sources are. URL share by source class and kind, and URLs per record.

u = load("source_urls", ["unique_id", "domain", "source_class", "url_kind"])
N_URLS, N_REC = len(u), u.unique_id.nunique()

by = (u.groupby(["source_class", "url_kind"]).size().unstack(fill_value=0)
      .reindex(columns=["about", "list", "unverified"], fill_value=0))
by["urls"] = by.sum(axis=1)
by["records"] = u.groupby("source_class").unique_id.nunique()
by = by.sort_values("urls", ascending=False)
SHOW = by.index[by.urls / N_URLS >= 0.015]  # classes under 1.5% of URLs fold into one row
tail = by.loc[~by.index.isin(SHOW)]
folded = tail[["about", "list", "unverified", "urls"]].sum()
folded["records"] = u[~u.source_class.isin(SHOW)].unique_id.nunique()
plot = pd.concat([by.loc[SHOW], folded.to_frame(f"{len(tail)} smaller classes").T])
plot["label"] = [PRETTY.get(c, c) for c in plot.index]
plot["pct_urls"] = 100 * plot.urls / N_URLS
plot["pct_records"] = 100 * plot.records / N_REC

per_rec = u.groupby("unique_id").size()
hist = per_rec.value_counts().reindex(range(1, 51), fill_value=0)
top = u.domain.value_counts()
practo, fb = top["practo.com"], u[u.domain == "facebook.com"].unique_id.nunique()
kind_pct = 100 * u.url_kind.value_counts() / N_URLS
at_cap = int(hist[50])

tidy = plot.reset_index(names="source_class")[
    ["source_class", "label", "about", "list", "unverified", "urls", "pct_urls", "records", "pct_records"]]
write_csv(tidy, "s1_composition_by_class")
write_csv(hist.rename_axis("urls_in_record").reset_index(name="records"), "s1_urls_per_record")

fig, (ax, bx) = S.new_figure(S.SLIDE_SIZE, 1, 2, gridspec_kw={"width_ratios": [1.75, 1]})
S.fig_title(fig, f"Half of the {N_URLS:,} source links behind the records go to health aggregators; "
                 f"only {plot.loc['official', 'pct_urls']:.1f}% are the facility's own website")
y = np.arange(len(plot))[::-1]
left = np.zeros(len(plot))
KIND = [("about", "Names this facility", S.CATEGORICAL[0]), ("list", "Listing page", S.CATEGORICAL[1]),
        ("unverified", "Not shown to be about it", S.OTHER)]
for col, lab, colr in KIND:
    ax.barh(y, plot[col] / 1000, left=left, color=colr, label=lab, height=0.68, **S.bar_style())
    left += plot[col].to_numpy() / 1000
for yi, (_, r) in zip(y, plot.iterrows()):
    ax.text(r.urls / 1000 + 0.8, yi, f"{r.pct_urls:.1f}%  ({r.records:,} records)", va="center",
            fontsize=10.5, color=S.INK)
ax.set_yticks(y, plot.label)
ax.set_xlabel("Source URLs (thousands)")
ax.set_xlim(0, plot.urls.max() / 1000 * 1.38)
ax.grid(axis="y", visible=False)
ax.legend(loc="lower right", title="URL kind", title_fontsize=11)
S.panel_title(ax, f"URLs by source class, n = {N_URLS:,} URLs in {N_REC:,} records")
ax.text(52, y[0] - 0.5, f"practo.com alone: {practo:,} URLs ({100 * practo / N_URLS:.1f}%)",
        fontsize=10, color=S.INK_2, va="center")

bars = bx.bar(hist.index, hist.values, width=1.0, color=S.CATEGORICAL[0], edgecolor=S.SURFACE, linewidth=0.6)
bars[-1].set_color(S.INK_2)  # not orange: orange means "listing page" in the left panel
med = int(per_rec.median())
bx.axvline(med, color=S.INK_2, lw=1)
bx.text(med + 0.8, hist.max() * 0.95, f"median {med}", fontsize=10.5, color=S.INK_2, va="top")
bx.annotate(f"{at_cap:,} records ({100 * at_cap / N_REC:.0f}%)\nstop at exactly 50:\nthe list was capped",
            (49.5, at_cap * 0.8), xytext=(46, at_cap * 0.8), fontsize=10.5, color=S.INK, ha="right", va="center",
            arrowprops=dict(arrowstyle="-", color=S.INK_2, lw=0.8))
bx.set_xlabel("Source URLs in the record")
bx.set_ylabel("Records")
bx.set_xlim(0, 52)
bx.grid(axis="x", visible=False)
S.panel_title(bx, f"URLs per record, n = {N_REC:,} records")
S.source_note(fig, src("source_urls") + ". URL kind from audit/provenance/q1_sources.py url_kind "
                   "(own-site URLs count as 'names this facility' by definition).")
S.save(fig, OUT / "s1_composition", alt_text=(
    f"Horizontal stacked bars of {N_URLS:,} source URLs by class. Health aggregators hold "
    f"{plot.loc['health_aggregator', 'pct_urls']:.1f}% of URLs, social media {plot.loc['social', 'pct_urls']:.1f}%, "
    f"the facility's own website {plot.loc['official', 'pct_urls']:.1f}%. Only {kind_pct['about']:.1f}% of all URLs "
    f"name the facility; {kind_pct['unverified']:.1f}% are not shown to be about it. practo.com alone supplies "
    f"{practo:,} URLs and facebook.com appears in {fb:,} of {N_REC:,} records. A histogram shows records carry a "
    f"median of {med} URLs and {at_cap:,} records stop at exactly 50, a cap in the source list."))
print(f"s1: {N_URLS} urls, {N_REC} records, agg {plot.loc['health_aggregator','pct_urls']:.2f}%, "
      f"social {plot.loc['social','pct_urls']:.2f}%, official {plot.loc['official','pct_urls']:.2f}%, "
      f"about {kind_pct['about']:.1f}%, median {med}, cap50 {at_cap}, practo {practo}, fb records {fb}")

# COMMAND ----------

# Story 2: source reliability by class, and the record-size confound behind "social media is most reliable".
from scipy.stats import beta as beta_dist

# Panel A: the published class reliability. Pooled Beta(1 + effective true, 1 + effective false), as in
# derived/v1/README.md; we redraw the interval at 95% from the same Beta.
sc = load("source_classes").set_index("source_class")
a, b = 1 + sc.effective_true, 1 + sc.effective_false
sc["rel"] = a / (a + b)
sc["lo95"], sc["hi95"] = beta_dist.ppf(0.025, a, b), beta_dist.ppf(0.975, a, b)
assert np.allclose(sc.rel, sc.reliability, atol=1e-6), "class reliability no longer matches the published Beta"
sc = sc.sort_values("rel")

# Panels B and C: a record "has a contamination sign" when a claim sentence names another institution (p3c)
# or its coordinates sit more than 50 km from its PIN (p4); audit/provenance/q1_sources.py. Each record counts
# toward a class in proportion to that class's share of its URLs (a record with 4 URLs, 2 on Facebook,
# counts half toward social), the same per-record normalisation the reliability fit uses, without its
# hand-set kind and class multipliers.
R = load("q1_records")
clean = ~(R.p3c_foreign_claim.fillna(False).astype(bool) | R.p4_coord_far_from_pin.fillna(False).astype(bool))
band = size_band(R.n_urls)
FOCUS = [("social", S.CATEGORICAL[0]), ("official", S.CATEGORICAL[1]), ("health_aggregator", S.CATEGORICAL[2])]
rows = []
for c, _ in FOCUS:
    w = (R[f"n_{c}"] / R.n_urls).to_numpy()
    for lab in SIZE_LABELS + ["All sizes"]:
        m = np.ones(len(R), bool) if lab == "All sizes" else (band == lab).to_numpy()
        p, lo, hi = weighted_rate_ci(clean[m], w[m])
        rows.append(dict(source_class=c, size_band=lab, clean_rate=p, lo95=lo, hi95=hi,
                         class_weight=w[m].sum(), records_citing=int(((w > 0) & m).sum())))
st = pd.DataFrame(rows)
tot = st[st.size_band == "All sizes"].set_index("source_class").class_weight
st["weight_share"] = st.class_weight / st.source_class.map(tot)
# Finer size control than four bands: direct standardisation over the exact URL count (1-50) to the size mix
# of all records; record bootstrap for the social minus aggregator gap (added in verification).
nb, yv = R.n_urls.to_numpy(), clean.to_numpy(float)
mix = np.bincount(nb, minlength=51) / len(nb)


def std_clean(idx, w):
    num = np.bincount(nb[idx], weights=w[idx] * yv[idx], minlength=51)
    den = np.bincount(nb[idx], weights=w[idx], minlength=51)
    ok = den > 0
    return (num[ok] / den[ok] * mix[ok]).sum() / mix[ok].sum()


W = {c: (R[f"n_{c}"] / R.n_urls).to_numpy() for c, _ in FOCUS}
std_rate = {c: std_clean(np.arange(len(R)), W[c]) for c in W}
rng = np.random.default_rng(SEED)
gaps = [std_clean(i, W["social"]) - std_clean(i, W["health_aggregator"])
        for i in (rng.integers(0, len(R), len(R)) for _ in range(N_BOOT))]
std_gap = (std_rate["social"] - std_rate["health_aggregator"], *np.percentile(gaps, [2.5, 97.5]))
assert std_gap[2] < 0, "social is no longer below aggregators after exact-size standardisation; reword panel C"
# Does the published score track size across all 16 classes? (It does not; reported, not hidden.)
small_share = pd.Series({c: (R[f"n_{c}"] / R.n_urls)[R.n_urls <= 5].sum() / (R[f"n_{c}"] / R.n_urls).sum()
                         for c in sc.index})
rho = small_share[sc.index].corr(sc.rel, method="spearman")
write_csv(pd.DataFrame([dict(source_class=c, exact_size_standardised_clean_rate=v) for c, v in std_rate.items()]
                       + [dict(source_class="social_minus_aggregator_gap", exact_size_standardised_clean_rate=std_gap[0],
                               lo95=std_gap[1], hi95=std_gap[2])]
                       + [dict(source_class="spearman_reliability_vs_small_record_share_16_classes",
                               exact_size_standardised_clean_rate=rho)]), "s2_size_standardised")
band_rate = R.assign(b=band).groupby("b", observed=True).apply(lambda g: (~clean[g.index]).mean(), include_groups=False)

write_csv(sc.reset_index()[["source_class", "rel", "lo95", "hi95", "effective_true", "effective_false",
                            "n_domains", "n_urls", "n_records"]].rename(columns={"rel": "reliability"}),
          "s2_class_reliability")
write_csv(st, "s2_stratified_clean_rate")

fig = S.plt.figure(figsize=(13.5, 7.6), constrained_layout=True)
ax = fig.subplot_mosaic([["A", "B"], ["A", "C"]], width_ratios=[1, 1.25], height_ratios=[1, 2.3])
S.fig_title(fig, "Social media tops the source-reliability table, but its links sit in small, clean "
                 "records; within records of the same size it is no cleaner than aggregators (lower in all four bands)", wrap=105)

A = ax["A"]
colour = dict(FOCUS)
yy = np.arange(len(sc))
for yi, (c, r) in zip(yy, sc.iterrows()):
    col = colour.get(c, S.OTHER)
    A.plot([r.lo95, r.hi95], [yi, yi], color=col, lw=2, solid_capstyle="butt")
    A.plot(r.rel, yi, "o", color=col, ms=8, mec=S.SURFACE, mew=2)
A.set_yticks(yy, [f"{PRETTY[c]} ({sc.n_records[c]:,})" for c in sc.index], fontsize=10.5)
for t, c in zip(A.get_yticklabels(), sc.index):
    if c in colour:
        t.set_color(S.INK); t.set_fontweight("bold")
A.set_xlabel("Published reliability (posterior mean, 95% credible interval)")
A.grid(axis="y", visible=False)
S.panel_title(A, "A. The published score: 16 source classes\n(records citing the class in brackets)")

B = ax["B"]
for i, (c, col) in enumerate(FOCUS):
    left = 0
    shares = st[(st.source_class == c) & (st.size_band != "All sizes")].weight_share.to_numpy()
    for j, s_ in enumerate(shares):
        B.barh(i, s_ * 100, left=left, color=S.SEQUENTIAL_ORDINAL[2 + 2 * j], height=0.7, **S.bar_style())
        if s_ > 0.08:
            B.text(left + s_ * 50, i, f"{s_ * 100:.0f}%", ha="center", va="center", fontsize=10,
                   color=S.INK if j < 2 else "#ffffff")
        left += s_ * 100
B.set_yticks(range(len(FOCUS)), [PRETTY[c] for c, _ in FOCUS])
B.invert_yaxis()
B.set_xlim(0, 100)
B.set_xlabel("Share of the class's citation weight (%)")
B.grid(axis="y", visible=False)
B.legend(handles=[S.matplotlib.patches.Patch(color=S.SEQUENTIAL_ORDINAL[2 + 2 * j], label=f"{lab} URLs")
                  for j, lab in enumerate(SIZE_LABELS)], ncol=4, loc="upper left", bbox_to_anchor=(0, -0.42),
         fontsize=10, handlelength=1.2, columnspacing=1.2, borderaxespad=0)
S.panel_title(B, "B. Where each class's links sit, by record size (URLs in the record)")

C = ax["C"]
xpos = {lab: i for i, lab in enumerate(SIZE_LABELS)} | {"All sizes": len(SIZE_LABELS) + 0.6}
for k, (c, col) in enumerate(FOCUS):
    d = st[st.source_class == c]
    off = (k - 1) * 0.13
    xs = np.array([xpos[l] for l in d.size_band]) + off
    inb = (d.size_band != "All sizes").to_numpy()
    C.plot(xs[inb], 100 * d.clean_rate[inb], color=col, lw=2)
    for x, r in zip(xs, d.itertuples()):
        C.plot([x, x], [100 * r.lo95, 100 * r.hi95], color=col, lw=1.6)
        C.plot(x, 100 * r.clean_rate, "o", color=col, ms=8, mec=S.SURFACE, mew=2)
    pooled = d[d.size_band == "All sizes"].iloc[0]
    C.text(xs[-1] + 0.12, 100 * pooled.clean_rate + {"social": -1.6, "official": 1.6}.get(c, 0),
           f"{PRETTY[c]} {100 * pooled.clean_rate:.0f}%",
           va="center", fontsize=10.5, color=S.INK)
C.axvline(len(SIZE_LABELS) - 0.2, color=S.AXIS, lw=0.8)
C.tick_params(axis="x", labelsize=10.5)
C.set_xticks(list(xpos.values()), [f"{l}\n({band_rate[l]:.0%})" for l in SIZE_LABELS] + ["All sizes\npooled"])
C.set_xlim(-0.4, len(SIZE_LABELS) + 2.3)
C.set_ylim(40, 100)
C.set_ylabel("Weighted share of records with no\ncontamination sign (%, 95% CI)")
C.set_xlabel("URLs in the record (share of all records in the band with a sign)")
C.grid(axis="x", visible=False)
pg = st[st.size_band == "All sizes"].set_index("source_class").clean_rate
S.panel_title(C, f"C. Pooled, social looks {100 * (pg['social'] - pg['health_aggregator']):.0f} points cleaner than aggregators;\n"
                 f"at equal record size it is {-100 * std_gap[0]:.1f} points less clean "
                 f"(95% CI {-100 * std_gap[2]:.1f} to {-100 * std_gap[1]:.1f})")
C.text(0.01, 0.03, "Axis starts at 40% to show within-band gaps; values are rates, not bar lengths.",
       transform=C.transAxes, fontsize=9.5, color=S.MUTED)
S.source_note(fig, src("source_classes", "q1_records") + ".\nContamination sign = a claim names another "
                   "institution or coordinates are over 50 km from the PIN (proxies, not verdicts). "
                   "CI: 2,000 Poisson bootstrap draws over records.\n"
                   f"Across all 16 classes the published score does not track the share of links in 1-5 URL records "
                   f"(Spearman {rho:.2f}): size explains the social vs aggregator contrast, not the whole table.")

g = st.set_index(["source_class", "size_band"])
S.save(fig, OUT / "s2_simpson", alt_text=(
    f"Panel A ranks 16 source classes by the published reliability score; social media is highest at "
    f"{sc.rel['social']:.3f} (95% credible interval {sc.lo95['social']:.3f} to {sc.hi95['social']:.3f}), facility "
    f"websites {sc.rel['official']:.3f}, health aggregators {sc.rel['health_aggregator']:.3f}. Panel B shows "
    f"{100 * g.weight_share['social', '1-5']:.0f}% of social media's citation weight sits in records with 1 to 5 "
    f"URLs, against {100 * g.weight_share['official', '1-5']:.0f}% for own websites and "
    f"{100 * g.weight_share['health_aggregator', '1-5']:.0f}% for aggregators, and small records are cleaner "
    f"({band_rate['1-5']:.0%} flagged vs {band_rate['21-50']:.0%} for 21 to 50 URLs). Panel C: pooled over all "
    f"sizes, social-weighted records are {100 * g.clean_rate['social', 'All sizes']:.0f}% clean against "
    f"{100 * g.clean_rate['health_aggregator', 'All sizes']:.0f}% for aggregators, but within each size band "
    f"social is equal or lower ({100 * g.clean_rate['social', '21-50']:.0f}% vs "
    f"{100 * g.clean_rate['health_aggregator', '21-50']:.0f}% in 21 to 50 URL records); matched on exact record size, "
    f"social is {-100 * std_gap[0]:.1f} points less clean (95% CI {-100 * std_gap[2]:.1f} to {-100 * std_gap[1]:.1f}). A Simpson's "
    f"reversal on the audit proxy. Across all 16 classes the published score does not track the share of links in small "
    f"records (Spearman {rho:.2f}), so record size explains this contrast, not the whole table."))
print("s2:\n", st.round(3).to_string(), "\n", band_rate.round(3).to_dict())

# COMMAND ----------

# Story 3: the paraphrase gap. How often a record's claim sentence appears on the page it cites.

pc = load("source_page_checks")
t = pc[pc.claim_id.notna()].copy()  # one row per (fetched page, claim sentence) test
t["supported"] = t.supported.astype(bool)
t["token_supported"] = t.token_supported.astype(bool)
STRATA = [("official_about", "Facility's own site"), ("aggregator_about", "Aggregator page about it"),
          ("list_page", "Listing page"), ("government", "Government portal"), ("research", "Research paper")]
rows = []
for key, lab in STRATA + [("all", "All tested pages")]:
    d = t if key == "all" else t[t.stratum == key]
    for meas, mlab in [("supported", "Wording found (exact or 90% fuzzy)"),
                       ("token_supported", "Most words found (70% of content words)")]:
        p, lo, hi, k, n, urls = cluster_rate_ci(d, meas, "url")
        rows.append(dict(stratum=key, label=lab, measure=meas, measure_label=mlab, rate=p, lo95=lo, hi95=hi,
                         sentences_supported=k, sentences_tested=n, pages=urls))
res = pd.DataFrame(rows)
write_csv(res, "s3_paraphrase_gap")

ex = t.merge(load("claims", ["claim_id", "text"]), on="claim_id")
ex = ex[(ex.domain == "kimayaheart.com") & ex.text.str.startswith("Interventional cardiology program")].iloc[0]
allr = res[(res.stratum == "all") & (res.measure == "supported")].iloc[0]
allt = res[(res.stratum == "all") & (res.measure == "token_supported")].iloc[0]
offr = res[(res.stratum == "official_about") & (res.measure == "supported")].iloc[0]

fig, ax = S.new_figure((13, 7))
S.finding_title(ax, f"Only {allr.rate:.1%} of a record's claim sentences appear near-verbatim on a page from its own "
                    f"source list; even on the facility's own site only {offr.rate:.1%} do",
                subtitle=f"{allr.sentences_tested:,} tests on {allr.pages} fetched pages (stratified sample of 385 source URLs); "
                         f"up to 25 of the record's sentences per page, not tied to that URL", wrap=88)
labels = [lab for _, lab in STRATA] + ["All tested pages"]
yb = np.arange(len(labels))[::-1] * 1.0
H = 0.36
for j, (meas, col) in enumerate([("supported", S.CATEGORICAL[0]), ("token_supported", S.SEQUENTIAL[3])]):
    d = res[res.measure == meas].set_index("label").loc[labels]
    yy = yb + (H / 2 if j == 0 else -H / 2)
    bars = ax.barh(yy, 100 * d.rate, height=H, color=col, label=d.measure_label.iloc[0], **S.bar_style())
    S.add_interval(ax, yy, 100 * d.lo95, 100 * d.hi95, horizontal=True, cap=3)
    for y_, r in zip(yy, d.itertuples()):
        ax.text(100 * r.hi95 + 0.8, y_, f"{100 * r.rate:.1f}%  ({r.sentences_supported:,} of {r.sentences_tested:,}"
                f"{', ' + str(r.pages) + ' pages' if j == 0 else ''})", va="center", fontsize=10, color=S.INK)
ax.set_yticks(yb, labels)
ax.get_yticklabels()[-1].set_fontweight("bold")
ax.axhline(yb[-1] + 0.6, color=S.AXIS, lw=0.8)
ax.set_xlim(0, 75)
ax.set_xlabel("Record's claim sentences found on the sampled source page (%, 95% CI resampling pages)")
ax.grid(axis="y", visible=False)
ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.0))
quote = (f"Record says: \"{ex.text}\"\n"
         f"{ex.domain} says: \"...{ex.snippet[:120]}...\"\n"
         f"Same fact, different words: fuzzy score {ex.partial_ratio:.0f} (needs 90), "
         f"{ex.token_coverage:.0%} of content words present.")
ax.text(0.985, 0.78, "\n".join(textwrap.fill(line, 66) for line in quote.split("\n")), transform=ax.transAxes,
        ha="right", va="top", fontsize=10, color=S.INK_2, linespacing=1.4, multialignment="left",
        bbox=dict(boxstyle="round,pad=0.6", fc=S.NEUTRAL, ec="none"))
S.source_note(fig, src("source_page_checks", "claims") + " (built by pipelines/source_scoring/s3_pagecheck.py). "
                   "Sample is stratified by source type, not weighted to all 158,444 URLs.")
S.save(fig, OUT / "s3_paraphrase", alt_text=(
    f"Grouped horizontal bars of how often a record's claim sentences are found on one sampled page from the "
    f"record's own source list (sentences are not tied to a specific URL). Across "
    f"{allr.sentences_tested:,} tests on {allr.pages} pages, {allr.rate:.1%} are found in near-verbatim wording "
    f"(95% CI {allr.lo95:.1%} to {allr.hi95:.1%}) and {allt.rate:.1%} when only most content words must appear. "
    + "; ".join(f"{r.label} {r.rate:.1%} ({r.sentences_supported} of {r.sentences_tested})"
                for r in res[(res.measure == 'supported') & (res.stratum != 'all')].itertuples())
    + f". The records paraphrase their sources: '{ex.text}' sits on {ex.domain} as different wording."))
print("s3:\n", res.round(4).to_string())

# COMMAND ----------

# Story 4: research papers and listing pages as contamination vectors, compared within record size.

R = load("q1_records")
foreign = R.p3c_foreign_claim.astype(bool)  # a claim sentence names an institution other than this record
BANDS, BLABELS = [0, 10, 20, 30, 50], ["1-10", "11-20", "21-30", "31-50"]
R["band4"] = pd.cut(R.n_urls, BANDS, labels=BLABELS)
VECTORS = [("research", R.n_research > 0, "cites a research paper"),
           ("list", R.n_url_list > 0, "cites a listing page")]
rows = []
for key, has, lab in VECTORS:
    for grp, m in [("with", has), ("without", ~has)]:
        for band in BLABELS + ["All sizes"]:
            mm = m & ((R.band4 == band) if band != "All sizes" else True)
            k, n = int(foreign[mm].sum()), int(mm.sum())
            p, lo, hi = S.wilson(k, n)
            rows.append(dict(vector=key, group=grp, size_band=band, records_flagged=k, records=n,
                             rate=p, lo95=lo, hi95=hi))
res = pd.DataFrame(rows)
write_csv(res, "s4_vectors_stratified")

# Indirect standardisation: the rate the "with" records would show if they had the "without" records' rate in
# their own size band. The gap from that expected rate is what record size does not explain.
std = {}
for key, _, _ in VECTORS:
    d = res[(res.vector == key) & (res.size_band != "All sizes")].pivot(index="size_band", columns="group")
    expected = (d.records["with"] * d.rate["without"]).sum() / d.records["with"].sum()
    obs = res.query("vector == @key and group == 'with' and size_band == 'All sizes'").rate.iloc[0]
    base = res.query("vector == @key and group == 'without' and size_band == 'All sizes'").rate.iloc[0]
    std[key] = dict(vector=key, observed=obs, expected_from_size=expected, others=base,
                    share_of_gap_from_size=(expected - base) / (obs - base))
# Robustness (added in verification): match on the exact URL count instead of four bands, and compare records
# at the 50-URL cap only, where the band is no longer coarse.
for key, has, _ in VECTORS:
    rate_wo = foreign[~has].groupby(R.n_urls[~has]).mean()
    exp_exact = R.n_urls[has].map(rate_wo).mean()
    base = std[key]["others"]
    std[key]["expected_exact_urls"] = exp_exact
    std[key]["share_of_gap_exact_urls"] = (exp_exact - base) / (std[key]["observed"] - base)
    for grp, m in [("with", has), ("without", ~has)]:
        k, n = int(foreign[m & (R.n_urls == 50)].sum()), int((m & (R.n_urls == 50)).sum())
        std[key][f"at50_{grp}_rate"], std[key][f"at50_{grp}_lo95"], std[key][f"at50_{grp}_hi95"] = S.wilson(k, n)
        std[key][f"at50_{grp}_records"] = n
write_csv(pd.DataFrame(std.values()), "s4_size_standardised")

hr = R.n_research > 0
lang_in, cl_in = int(R.n_research_lang_claims[hr].sum()), int(R.n_claims[hr].sum())
lang_out, cl_out = int(R.n_research_lang_claims[~hr].sum()), int(R.n_claims[~hr].sum())
med_r, med_o = R.n_urls[hr].median(), R.n_urls[~hr].median()
quote = load("handcheck_research_lang")
quote = quote[quote.claim.str.startswith("E. coli was the causative agent")].iloc[0]
write_csv(pd.DataFrame([dict(group="cites research", research_language_claims=lang_in, claims=cl_in,
                             median_urls=med_r, records=int(hr.sum())),
                        dict(group="no research", research_language_claims=lang_out, claims=cl_out,
                             median_urls=med_o, records=int((~hr).sum()))]), "s4_research_language")

fig, axes = S.new_figure((13.5, 7.2), 1, 2, sharey=True)
g = res.set_index(["vector", "group", "size_band"])
sr = std["research"]
S.fig_title(fig, f"Records that cite research papers carry another institution's claims {sr['observed'] / sr['others']:.1f}x "
                 f"as often ({sr['observed']:.1%} vs {sr['others']:.1%}); record size explains "
                 f"about half of the gap ({sr['share_of_gap_from_size']:.0%} to {sr['share_of_gap_exact_urls']:.0%}); the rest survives "
                 f"a same-size comparison", wrap=105)
xs = np.arange(len(BLABELS))
for ax, (key, _, lab) in zip(axes, VECTORS):
    for j, (grp, col, name) in enumerate([("with", S.CATEGORICAL[1], f"Record {lab}"),
                                          ("without", S.CATEGORICAL[0], "All other records")]):
        d = res[(res.vector == key) & (res.group == grp) & (res.size_band != "All sizes")]
        x = xs + (j - 0.5) * 0.24
        ax.plot(x, 100 * d.rate, color=col, lw=2)
        S.add_interval(ax, x, 100 * d.lo95, 100 * d.hi95, color=col, cap=0, lw=1.6)
        ax.plot(x, 100 * d.rate, "o", color=col, ms=8, mec=S.SURFACE, mew=2)
        ax.text(x[-1] + 0.15, 100 * d.rate.iloc[-1] + (2.5 if j == 0 else -2.5), name, fontsize=10.5,
                color=S.INK, ha="left", va="center")
        small = d[d.records < S.SMALL_N]
        for xi, r in zip(x[(d.records < S.SMALL_N).to_numpy()], small.itertuples()):
            ax.annotate("small n", (xi, 100 * r.hi95), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=9, color=S.INK_2, style="italic")
    w, wo = g.loc[(key, "with", "All sizes")], g.loc[(key, "without", "All sizes")]
    S.panel_title(ax, f"{'Research papers' if key == 'research' else 'Listing pages'}: pooled {100 * w.rate:.1f}% "
                      f"({int(w.records_flagged):,} of {int(w.records):,}) vs {100 * wo.rate:.1f}% ({int(wo.records_flagged):,} of {int(wo.records):,});\n"
                      f"same-size expectation {std[key]['expected_from_size']:.1%}, so size explains "
                      f"{std[key]['share_of_gap_from_size']:.0%} of the gap")
    nw = res[(res.vector == key) & (res.group == "with")].set_index("size_band").records
    nwo = res[(res.vector == key) & (res.group == "without")].set_index("size_band").records
    ax.set_xticks(xs, [f"{b}\nn = {nw[b]:,} / {nwo[b]:,}" for b in BLABELS], fontsize=10.5)
    ax.set_xlim(-0.4, len(BLABELS) + 0.6)
    ax.set_xlabel("Source URLs in the record (n = records citing / not citing)")
    ax.grid(axis="x", visible=False)
axes[0].set_ylim(0, 70)  # headroom so the note box clears the 11-20 and 21-30 intervals
axes[0].set_ylabel("Records with a claim naming another institution\n(%, 95% Wilson interval)")
axes[0].text(0.02, 0.97, textwrap.fill(f"Research text becomes service claims: {lang_in} of {cl_in:,} claims "
             f"({100 * lang_in / cl_in:.2f}%) in research-citing records read like study findings, against "
             f"{lang_out} of {cl_out:,} ({100 * lang_out / cl_out:.2f}%) elsewhere. Example, stored as a capability "
             f"of {quote['name'].split(',')[0]}: \"{quote.claim}\"", 62),
             transform=axes[0].transAxes, va="top", fontsize=9.8, color=S.INK_2, linespacing=1.35,
             bbox=dict(boxstyle="round,pad=0.5", fc=S.NEUTRAL, ec="none"))
S.source_note(fig, src("q1_records", "handcheck_research_lang") + ".\nFlag p3c_foreign_claim from "
                   "audit/provenance/q1_sources.py, a proxy: REPORT.md PROV-04 found 17 of 40 hand-checked flags real.\n"
                   f"Size share of the gap: {sr['share_of_gap_from_size']:.0%} matching 4 size bands, "
                   f"{sr['share_of_gap_exact_urls']:.0%} matching exact URL count. At the 50-URL cap: research-citing {sr['at50_with_rate']:.1%} ({sr['at50_with_lo95']:.1%} to "
                   f"{sr['at50_with_hi95']:.1%}, n = {sr['at50_with_records']}) vs {sr['at50_without_rate']:.1%} "
                   f"({sr['at50_without_lo95']:.1%} to {sr['at50_without_hi95']:.1%}, n = {sr['at50_without_records']}).")
S.save(fig, OUT / "s4_vectors", alt_text=(
    f"Two panels of the share of records where a claim sentence names another institution, by number of source "
    f"URLs. Records citing research papers: {100 * g.rate['research', 'with', 'All sizes']:.1f}% pooled vs "
    f"{100 * g.rate['research', 'without', 'All sizes']:.1f}% for other records; among records with 31 to 50 URLs "
    f"{100 * g.rate['research', 'with', '31-50']:.1f}% vs {100 * g.rate['research', 'without', '31-50']:.1f}%. "
    f"Records citing listing pages: {100 * g.rate['list', 'with', 'All sizes']:.1f}% vs "
    f"{100 * g.rate['list', 'without', 'All sizes']:.1f}% pooled, but within size bands the gap is small until "
    f"31 to 50 URLs ({100 * g.rate['list', 'with', '31-50']:.1f}% vs {100 * g.rate['list', 'without', '31-50']:.1f}%). "
    f"Research-style claims are {100 * lang_in / cl_in:.2f}% of claims in research-citing records vs "
    f"{100 * lang_out / cl_out:.2f}% elsewhere."))
print("s4:\n", res.round(3).to_string(), "\n", pd.DataFrame(std.values()).round(3).to_string(), f"\nlang {lang_in}/{cl_in} vs {lang_out}/{cl_out}; median urls {med_r} vs {med_o}")

# COMMAND ----------

# Story 5: government portals that do not answer from our network, and what that does to verification.
import re  # noqa: E402
from urllib.parse import urlparse  # noqa: E402


OUTCOME = {"ok_html": "Text read", "unreachable": "No answer (timeout or connection)",
           "blocked_http_403": "Refused (403, robots, login)", "robots_disallowed": "Refused (403, robots, login)",
           "login_redirect": "Refused (403, robots, login)", "skipped_after_blocked": "Refused (403, robots, login)",
           "ok_empty": "Empty page or 404", "http_404": "Empty page or 404"}
OUT_ORDER = ["Text read", "No answer (timeout or connection)", "Refused (403, robots, login)", "Empty page or 404"]
OUT_COL = [S.CATEGORICAL[0], S.CATEGORICAL[1], S.CATEGORICAL[6], S.OTHER]  # purple, not yellow: orange-yellow failed the normal-vision floor (13.7)
STRATA = [("official_about", "Facility's own site"), ("aggregator_about", "Aggregator page about it"),
          ("list_page", "Listing page"), ("research", "Research paper"), ("government", "Government portal")]
SCHEME = re.compile(r"esic|hryesi|cghs|pmjay|ayushman|cashless|empanel|arogya|swasthya|pcpndt|kpme|transtan|sotto|"
                    r"(^|\.)ors\.gov|notto|covidcbrs|atalamrit|asbtc|blood|hosplist|registeredhospital", re.I)


def portal_type(url):
    """Hand-written rule for the kind of government page; printed in s5_portal_types.csv for checking."""
    pu = urlparse(url)
    host = pu.netloc.lower().removeprefix("www.")
    if not re.search(r"\.(gov|nic|edu|ac)\.in$", host):
        return "Not a government host (misfiled)"
    if "public-utilit" in pu.path.lower():
        return "District portal directory page"
    if SCHEME.search(host + pu.path):
        return "Scheme, empanelment or registry portal"
    return "Other government page"


pc = load("source_page_checks", ["url", "stratum", "fetch_status"]).drop_duplicates("url")
pc["outcome"] = pc.fetch_status.map(OUTCOME)
assert pc.outcome.notna().all(), pc.fetch_status[pc.outcome.isna()].unique()
a = (pc.groupby(["stratum", "outcome"]).size().unstack(fill_value=0).reindex(columns=OUT_ORDER, fill_value=0))
a["urls"] = a.sum(axis=1)
write_csv(a.reset_index(), "s5_fetch_outcomes")

gov = pc[pc.stratum == "government"].copy()
gov["portal_type"] = gov.url.map(portal_type)
gov["timed_out"] = gov.fetch_status == "unreachable"
TYPES = ["District portal directory page", "Other government page", "Scheme, empanelment or registry portal",
         "Not a government host (misfiled)"]
b_rows = []
for t in TYPES:
    d = gov[gov.portal_type == t]
    p, lo, hi = S.wilson(int(d.timed_out.sum()), len(d))
    b_rows.append(dict(portal_type=t, timed_out=int(d.timed_out.sum()), urls=len(d), rate=p, lo95=lo, hi95=hi))
B = pd.DataFrame(b_rows)
write_csv(B, "s5_government_by_type")
write_csv(gov[["url", "portal_type", "fetch_status"]].sort_values(["portal_type", "url"]), "s5_portal_types")

# How much of the dataset's government evidence is the kind that does not answer.
u = load("source_urls", ["unique_id", "url", "source_class"])
ug = u[u.source_class == "government"].copy()
ug["portal_type"] = ug.url.map(portal_type)
pop = ug.groupby("portal_type").agg(urls=("url", "size"), records=("unique_id", "nunique")).reindex(TYPES)
write_csv(pop.reset_index(), "s5_government_population")
scheme_recs = pop.loc["Scheme, empanelment or registry portal", "records"]

# Registry hosts probed by hand on 2026-11-21, copied from research/discover/registries/CANDIDATES.md.
PROBE_NO_ANSWER = ["data.gov.in", "api.data.gov.in", "hospitals.pmjay.gov.in", "pmjay.gov.in",
                   "dashboard.pmjay.gov.in", "cghs.mohfw.gov.in", "cghs.nic.in", "nhrr.mohfw.gov.in",
                   "www.esic.gov.in", "hmis.mohfw.gov.in", "indianrailways.gov.in", "www.jeevandayee.gov.in",
                   "www.echsbpa.utiitsl.com", "cdsco.gov.in", "cmhis.nagaland.gov.in"]
PROBE_403 = ["facility.abdm.gov.in", "abdm.gov.in", "nha.gov.in"]
PROBE_OK = ["nabh.co", "nmc.org.in", "aikosh.indiaai.gov.in", "www.mohfw.gov.in", "www.echs.gov.in",
            "nin.mohfw.gov.in", "nhm.gov.in", "cbhidghs.mohfw.gov.in", "www.bis.gov.in", "cdnbbsr.s3waas.gov.in",
            "journals.plos.org"]

g = a.loc["government"]
fig, (ax, bx) = S.new_figure((13.5, 8.0), 1, 2, gridspec_kw={"width_ratios": [1.15, 1]})
sch = B.set_index("portal_type").loc["Scheme, empanelment or registry portal", ["timed_out", "urls"]].astype(int)
S.fig_title(fig, f"{g['No answer (timeout or connection)']} of {g.urls} sampled government pages did not answer our one fetch; "
                 f"{sch.timed_out} of those are the scheme and registry portals that could confirm empanelment "
                 f"({sch.timed_out} of {sch.urls} such portals)", wrap=105)
y = np.arange(len(STRATA))[::-1]
for yi, (key, lab) in zip(y, STRATA):
    r = a.loc[key]
    left = 0
    for o, col in zip(OUT_ORDER, OUT_COL):
        share = 100 * r[o] / r.urls
        ax.barh(yi, share, left=left, color=col, height=0.62, label=o if yi == y[0] else None, **S.bar_style())
        if share >= 7:
            ax.text(left + share / 2, yi, f"{r[o]}", ha="center", va="center", fontsize=10,
                    color="#ffffff" if col in (S.CATEGORICAL[0], S.CATEGORICAL[1], S.CATEGORICAL[6]) else S.INK)
        left += share
ax.set_yticks(y, [f"{lab}\n(n = {a.loc[k, 'urls']} URLs)" for k, lab in STRATA])
ax.set_xlim(0, 100)
ax.set_xlabel("Share of sampled source URLs (%); counts inside bars")
ax.grid(axis="y", visible=False)
ax.legend(ncol=2, loc="upper left", bbox_to_anchor=(0, -0.13), fontsize=10.5)
S.panel_title(ax, "A. What happened when we fetched each sampled source page")

yb = np.arange(len(B))[::-1]
bars = bx.barh(yb, 100 * B.rate, color=S.CATEGORICAL[1], height=0.6, **S.bar_style())
S.add_interval(bx, yb, 100 * B.lo95, 100 * B.hi95, horizontal=True, cap=3)
for yi, r in zip(yb, B.itertuples()):
    bx.text(100 * r.hi95 + 2, yi, f"{r.timed_out} of {r.urls}" + ("  (small n)" if r.urls < S.SMALL_N else ""),
            va="center", fontsize=10.5, color=S.INK)
bx.set_yticks(yb, [textwrap.fill(t, 22) for t in B.portal_type], fontsize=10.5)
bx.set_xlim(0, 140)
bx.set_xticks([0, 20, 40, 60, 80, 100])
bx.set_xlabel("No answer (%, 95% Wilson interval)")
bx.grid(axis="y", visible=False)
S.panel_title(bx, f"B. Government URLs by kind of page (n = {len(gov)})")
note = (f"In the whole dataset, {pop.loc['Scheme, empanelment or registry portal', 'urls']:,} government URLs in "
        f"{scheme_recs:,} records point at scheme or registry portals. National registries probed by hand: "
        f"{len(PROBE_NO_ANSWER)} hosts timed out or refused (PM-JAY, CGHS, NHRR, ESIC, HMIS, data.gov.in), "
        f"{len(PROBE_403)} returned 403 (the ABDM facility registry, ABDM, NHA); {len(PROBE_OK)} answered "
        f"(NABH, NMC, MoHFW, NHM). Geo-blocking is suspected, not verified.")
bx.text(-0.3, -0.16, textwrap.fill(note, 92), transform=bx.transAxes, va="top", fontsize=9.5, color=S.INK_2,
        linespacing=1.35, bbox=dict(boxstyle="round,pad=0.5", fc=S.NEUTRAL, ec="none"))
S.source_note(fig, src("source_page_checks", "source_urls") + "; research/discover/registries/CANDIDATES.md (probe, "
                   "2026-11-21).\nOne fetch per URL, 15 s timeout, robots.txt obeyed (pipelines/source_scoring/s3_pagecheck.py).")
S.save(fig, OUT / "s5_reachability", alt_text=(
    f"Stacked bars of fetch outcomes for 385 sampled source URLs. Government portals: {g['No answer (timeout or connection)']} of "
    f"{g.urls} gave no answer, against {a.loc['official_about', 'No answer (timeout or connection)']} of {a.loc['official_about', 'urls']} "
    f"facility sites and 0 of {a.loc['research', 'urls']} research pages, though research publishers refused "
    f"{a.loc['research', 'Refused (403, robots, login)']} of {a.loc['research', 'urls']}. By kind of government page: "
    + "; ".join(f"{r.portal_type} {r.timed_out} of {r.urls} without an answer" for r in B.itertuples())
    + f". District NIC directory pages answer; scheme, empanelment and registry portals (ESIC, CGHS, state cashless "
      f"schemes, PCPNDT, organ registries) mostly do not, so claims of empanelment could not be checked from our network "
      f"(one fetch each; geo-blocking suspected, not verified)."))
print("s5:\n", a.to_string(), "\n", B.round(3).to_string(), "\n", pop.to_string())

# COMMAND ----------

# Story 6 (model card): most source domains are seen once, so their reliability is the class prior.

d = load("source_domains", ["domain", "source_class", "n_records", "reliability", "ci05", "ci95",
                            "class_prior_mean"])
d["dev_from_prior"] = (d.reliability - d.class_prior_mean).abs()
d["ci90_width"] = d.ci95 - d.ci05
BINS, BLAB = [0, 1, 4, 19, 99, 10**6], ["1", "2-4", "5-19", "20-99", "100+"]
d["records_band"] = pd.cut(d.n_records, BINS, labels=BLAB)
summ = d.groupby("records_band", observed=True).agg(
    domains=("domain", "size"), median_dev_from_prior=("dev_from_prior", "median"),
    median_ci90_width=("ci90_width", "median"), min_rel=("reliability", "min"), max_rel=("reliability", "max"))
summ["share_of_domains"] = summ.domains / len(d)
write_csv(summ.reset_index(), "s6_shrinkage_by_records")
write_csv(d.drop(columns="records_band"), "s6_domain_points")

one = summ.loc["1"]
fig, ax = S.new_figure((13, 7))
S.finding_title(ax, f"{int(one.domains):,} of {len(d):,} source domains ({one.share_of_domains:.0%}) are cited by one "
                    f"record, so their reliability is the class prior: all scores sit between "
                    f"{d.reliability.min():.2f} and {d.reliability.max():.2f}",
                subtitle="Each dot is a registrable domain; the 12 most-cited carry their 90% credible interval "
                         "(as published)", wrap=80)
rng = np.random.default_rng(SEED)
x = d.n_records * np.exp(rng.uniform(-0.18, 0.18, len(d)))  # jitter so the stacked low-count columns show their density
ax.scatter(x, d.reliability, s=7, color=S.CATEGORICAL[0], alpha=0.12, linewidths=0)
top = d.nlargest(12, "n_records")
for r in top.itertuples():
    ax.plot([r.n_records, r.n_records], [r.ci05, r.ci95], color=S.INK_2, lw=1.4)
    ax.plot(r.n_records, r.reliability, "o", color=S.CATEGORICAL[1], ms=7, mec=S.SURFACE, mew=1.5)
LABEL = {"facebook.com": (0, 8), "justdial.com": (8, 6), "practo.com": (8, -2), "medindia.net": (8, -4),
         "onefivenine.com": (-6, -14), "proptiger.com": (-8, -14)}
for r in top[top.domain.isin(LABEL)].itertuples():
    dx, dy = LABEL[r.domain]
    ax.annotate(f"{r.domain} ({r.n_records:,} records)\n{r.reliability:.3f} [{r.ci05:.3f}, {r.ci95:.3f}]",
                (r.n_records, r.reliability), xytext=(dx, dy), textcoords="offset points", fontsize=9.5,
                color=S.INK, ha="left" if dx >= 0 else "right", va="center")
ax.set_xscale("log")
ax.xaxis.set_major_formatter(S.matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
ax.set_xlabel("Records that cite the domain (log scale; points jittered sideways)")
ax.set_ylabel("Published domain reliability (posterior mean)")
ax.set_ylim(0.76, 0.94)
txt = "Records citing: domains;\nmedian gap to class prior;\nmedian 90% interval width\n" + "\n".join(
    f"{b}: {int(r.domains):,}; {r.median_dev_from_prior:.3f}; {r.median_ci90_width:.2f}"
                for b, r in summ.iterrows())
ax.text(0.2, 0.03, txt, transform=ax.transAxes, ha="left", va="bottom", fontsize=9.8, color=S.INK_2,
        linespacing=1.4, bbox=dict(boxstyle="round,pad=0.5", fc=S.NEUTRAL, ec="none"))
ax.text(0.01, 0.97, "y axis spans 0.76 to 0.94: the full range of all 10,951 scores", transform=ax.transAxes,
        fontsize=9.5, color=S.MUTED, va="top")
S.source_note(fig, src("source_domains") + ". Fit: pipelines/source_scoring/s5_fit.py, prior strength KAPPA = 10 "
                   "records' worth of evidence toward the class mean.")
S.save(fig, OUT / "s6_shrinkage", alt_text=(
    f"Scatter of {len(d):,} source domains: reliability against the number of records citing them (log scale). "
    f"{int(one.domains):,} domains ({one.share_of_domains:.0%}) are cited by one record; their scores sit a median "
    f"{one.median_dev_from_prior:.4f} from the class prior with 90% intervals about {one.median_ci90_width:.2f} wide. "
    f"Only the most-cited domains move: facebook.com 0.919, justdial.com 0.861, practo.com 0.838, onefivenine.com "
    f"0.802. All scores lie between {d.reliability.min():.3f} and {d.reliability.max():.3f}, so a source score "
    f"cannot separate a good page from a bad one."))
print("s6:\n", summ.round(4).to_string())

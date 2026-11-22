# Story 4: research papers and listing pages as contamination vectors, compared within record size.
from _common import *  # noqa: F401,F403  # NOTEBOOK-SKIP

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

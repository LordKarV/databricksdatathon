# Story 3: the paraphrase gap. How often a record's claim sentence appears on the page it cites.
from _common import *  # noqa: F401,F403  # NOTEBOOK-SKIP

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

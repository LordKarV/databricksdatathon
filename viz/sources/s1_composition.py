# Story 1: what a record's sources are. URL share by source class and kind, and URLs per record.
from _common import *  # noqa: F401,F403  # NOTEBOOK-SKIP

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

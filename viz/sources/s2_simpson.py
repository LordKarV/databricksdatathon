# Story 2: source reliability by class, and the record-size confound behind "social media is most reliable".
from _common import *  # noqa: F401,F403  # NOTEBOOK-SKIP
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

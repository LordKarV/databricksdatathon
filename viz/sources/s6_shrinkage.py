# Story 6 (model card): most source domains are seen once, so their reliability is the class prior.
from _common import *  # noqa: F401,F403  # NOTEBOOK-SKIP

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

"""Story 5: what each evidence family contributes.

Panel data are label-free: stored per-term contributions for all 69,713 (facility, service) pairs, and
the weight table fitted on dev labels only (prior mean vs posterior, 90% interval). Writes
s5_points_by_text_level.* and s5_prior_vs_fitted.* (png, svg, txt, csv).
Run: .venv-viz/bin/python viz/model/s5_families.py
"""
import textwrap

import numpy as np
import pandas as pd

import _inputs as I
import style as S

# Only the first 3 categorical hues validate under --pairs all (viz/style.py), and these lines cross, so the
# two remaining families are neutral inks told apart by line style.
FAMS = [("text", S.CATEGORICAL[0]), ("hints", S.CATEGORICAL[1]), ("web", S.CATEGORICAL[2]),
        ("type_size", S.INK_2), ("flags", S.MUTED)]
LS = {"flags": (0, (4, 2))}
T_NAMES = {0: "0 none", 1: "1 tag/list", 2: "2 one sent.", 3: "3 2+ sent.", 4: "4 2+ fields", 5: "5 + unit"}
TERMS = [  # (term, label) service head, global terms, grouped by family
    ("t1", "t1 any own mention"), ("t2", "t2 one own sentence"), ("t3", "t3 2+ sentences"),
    ("t4", "t4 2+ fields"), ("t5", "t5 plus unit or quantity"), ("trunc0", "trunc0 list cut short"),
    ("tb_mid", "tb_mid text on mid-merge record"), ("tb_high", "tb_high text on high-merge record"),
    ("p1", "p1 one prerequisite hint"), ("p2", "p2 two prerequisite hints"),
    ("c1", "c1 foreign sentence, with own text"), ("c2", "c2 foreign sentence, no own text"),
    ("n1", "n1 non-offer cue"), ("s1", "s1 eye/dental/IVF/lab scope"),
    ("g_mid", "g_mid web footprint, mid"), ("g_high", "g_high web footprint, high"),
    ("level_dh", "level_dh district hospital"), ("iphs_essential", "iphs_essential"),
    ("breadth_20p", "breadth_20p 20+ specialties"), ("public", "public"), ("type_clinic", "type_clinic"),
]


def pair_points(load):
    pc = load("pair_contributions")
    pts = (pc.assign(fam=pc.term.map(I.family))
             .pivot_table(index=["unique_id", "service"], columns="fam", values="points", aggfunc="sum", fill_value=0.0))
    ps = load("pair_scores").set_index(["unique_id", "service"])[["T", "p_s", "z_cal"]]
    d = pts.join(ps, how="inner")
    assert len(d) == len(ps) == 69713, len(d)
    err = (d[I.FAMILY_ORDER].sum(axis=1) / I.POINTS_PER_LOGIT - d.z_cal).abs().max()
    assert err < 1e-9, err  # the families add up to the stored logit
    return d


def level_table(d):
    g = d.groupby("T")
    t = g[[f for f, _ in FAMS]].mean()
    t["n_pairs"] = g.size()
    t["p_s_p10"], t["p_s_median"], t["p_s_p90"] = g.p_s.quantile(0.1), g.p_s.median(), g.p_s.quantile(0.9)
    t["share_context_beats_text"] = g.apply(lambda x: ((x.web + x.type_size).abs() > x.text.abs()).mean())
    t["share_hints_gt_text"] = g.apply(lambda x: (x.hints > x.text).mean())
    return t.reset_index()


def levels_chart(t, out):
    fig = S.plt.figure(figsize=(13, 6.8), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.45, 1])
    ax, bx = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    x = t["T"].values
    nudge = {"flags": 9, "type_size": -9}  # points; keeps the two near-zero end labels apart
    for f, c in FAMS:
        ax.plot(x, t[f], color=c, marker="o", ms=8, mec=S.SURFACE, mew=1.5, ls=LS.get(f, "-"),
                label=I.FAMILY_LABEL[f])
        ax.annotate(I.FAMILY_LABEL[f], (x[-1], t[f].iloc[-1]), xytext=(10, nudge.get(f, 0)),
                    textcoords="offset points", va="center", fontsize=10.5, color=S.INK)
    sh = t.share_hints_gt_text
    ax.annotate("Own text: " + ", ".join(f"{v:.1f}" for v in t.text[1:]) + " points at levels 1 to 5.\n"
                f"Hints beat text for {sh[1:5].min():.0%} to {sh[1:5].max():.0%} of pairs at levels 1 to 4",
                (-0.1, 16.5), fontsize=10.5, color=S.INK, va="center")
    ax.legend(loc="lower right", fontsize=9.5, frameon=True, facecolor=S.SURFACE, edgecolor="none")
    ax.axhline(0, color=S.INK_2, lw=0.9)
    labels = [f"{T_NAMES[v]}\nn = {n:,}" for v, n in zip(x, t.n_pairs)]
    ax.set_xticks(x, labels, fontsize=9.5)
    ax.set_xlim(-0.3, 7.2)
    ax.set_xlabel("Own-text level T of the pair")
    ax.set_ylabel("Mean points per pair (+20 doubles the odds)")
    ax.grid(axis="x", visible=False)
    S.panel_title(ax, "Where the points come from, all 69,713 pairs (exact means, not estimates)")
    bx.vlines(x, t.p_s_p10, t.p_s_p90, color=S.CATEGORICAL[0], lw=5, alpha=0.35)
    bx.plot(x, t.p_s_median, color=S.CATEGORICAL[0], marker="o", ms=8, mec=S.SURFACE, mew=1.5, lw=0)
    for xi, v in zip(x, t.p_s_median):
        bx.annotate(f"{v:.2f}", (xi, v), xytext=(9, 0), textcoords="offset points", va="center", fontsize=9.5,
                    color=S.INK)
    bx.set_xticks(x, [str(v) for v in x])
    bx.set_ylim(0, 0.8)
    bx.set_xlabel("Own-text level T")
    bx.set_ylabel("P_S, median (dot) and 10th-90th percentile (bar)")
    bx.grid(axis="x", visible=False)
    S.panel_title(bx, "Resulting service score P_S")
    S.fig_title(fig, f"Own service text earns {t.text[1]:.1f} points for a tag and only {t.text[4]:.1f} for sentences "
                     f"in several fields; prerequisite hints (ICU, OT, blood bank) out-earn the text on average at "
                     f"levels 1 to 4")
    S.source_note(fig, textwrap.fill(I.source("pair_contributions", "pair_scores") + ". Families sum to the stored "
                  "logit for every pair (checked to 1e-9). 'Flags' = contamination, non-offer and scope terms. "
                  "Model hash de82eeee9ea0d0f6-fallback.", 190))
    alt = ("Left: line chart of mean points per pair by own-text level T over all 69,713 pairs. Own service text: " +
           ", ".join(f"T{v} {p:.1f}" for v, p in zip(x, t.text)) + ". Related-service hints: " +
           ", ".join(f"T{v} {p:.1f}" for v, p in zip(x, t.hints)) + ". Facility type and size: " +
           ", ".join(f"T{v} {p:.1f}" for v, p in zip(x, t.type_size)) + ". Right: median P_S by level: " +
           ", ".join(f"T{v} {p:.2f}" for v, p in zip(x, t.p_s_median)) +
           ". Text points are flat from level 1 to 4 and jump only at level 5. Hints exceed text for " +
           ", ".join(f"T{v} {p:.0%}" for v, p in zip(x[1:5], t.share_hints_gt_text[1:5])) + " of pairs.")
    t.to_csv(out / "s5_points_by_text_level.csv", index=False)
    S.save(fig, out / "s5_points_by_text_level", alt)


def weights_table(load):
    w = load("weights")
    w = w[(w["head"] == "service")].set_index("term")
    a = load("platt")["service"]["a"]
    rows = []
    for term, lab in TERMS:
        r = w.loc[term]
        rows.append(dict(term=term, label=lab, family=I.family(term), prior_mean=r.prior_mean, prior_sd=r.prior_sd,
                         post_mean=r.post_mean, ci90_lo=r.ci90_lo, ci90_hi=r.ci90_hi, at_bound=bool(r.at_bound),
                         n_fired_dev=int(r.n_fired_dev), n_fired_all=int(r.n_fired_all),
                         shipped_points=r.post_mean * a * I.POINTS_PER_LOGIT))
    return pd.DataFrame(rows), a


def prior_chart(w, a, out):
    fig, ax = S.new_figure(size=(13, 8.4))
    k = I.POINTS_PER_LOGIT
    y = -np.arange(len(w))
    for yi, r in zip(y, w.itertuples()):
        moved = abs(r.post_mean - r.prior_mean) >= 0.5
        col = S.CATEGORICAL[0] if moved else S.MUTED
        ax.plot([r.ci90_lo * k, r.ci90_hi * k], [yi, yi], color=col, lw=2, alpha=0.5, solid_capstyle="round")
        ax.annotate("", (r.post_mean * k, yi), (r.prior_mean * k, yi),
                    arrowprops=dict(arrowstyle="->", color=S.INK_2, lw=1, shrinkA=5, shrinkB=5))
        ax.scatter(r.prior_mean * k, yi, s=70, facecolors=S.SURFACE, edgecolors=S.INK_2, lw=1.5, zorder=3)
        ax.scatter(r.post_mean * k, yi, s=80, color=col, edgecolors=S.SURFACE, lw=1.2, zorder=4)
        note = f"dev n = {r.n_fired_dev}" + ("  at bound" if r.at_bound else "")
        ax.text(1.005, yi, note, transform=ax.get_yaxis_transform(), va="center", fontsize=9, color=S.INK_2)
    ax.axvline(0, color=S.INK_2, lw=0.9)
    ax.set_yticks(y, w.label, fontsize=10)
    ax.set_xlabel("Weight in points before Platt scaling (shipped points = this x "
                  f"{a:.2f}; +20 doubles the odds)")
    ax.grid(axis="y", visible=False)
    for b in np.where(w.family.values[:-1] != w.family.values[1:])[0]:
        ax.axhline(y[b] - 0.5, color=S.GRID, lw=1)
    ax.scatter([], [], s=70, facecolors=S.SURFACE, edgecolors=S.INK_2, lw=1.5, label="Expert prior mean")
    ax.scatter([], [], s=80, color=S.CATEGORICAL[0], label="Fitted, moved 0.5 logit or more (line: 90% interval)")
    ax.scatter([], [], s=80, color=S.MUTED, label="Fitted, moved less")
    ax.legend(loc="upper left", fontsize=10, frameon=True, facecolor=S.SURFACE, edgecolor="none")
    r = w.set_index("term")
    pt = lambda v: f"{v * k:+.0f}" if abs(v * k) >= 0.5 else "0"  # noqa: E731
    S.fig_title(fig, f"Fitting on about 22 effective dev labels pushed the expert's 'more text' steps to their 0 bound "
                     f"(t3 {pt(r.prior_mean['t3'])} to {pt(r.post_mean['t3'])} points before Platt) and moved the "
                     f"web-footprint term g_mid from {pt(r.prior_mean['g_mid'])} to {pt(r.post_mean['g_mid'])}, "
                     f"90% interval {pt(r.ci90_lo['g_mid'])} to {pt(r.ci90_hi['g_mid'])}")
    S.panel_title(ax, "Service head, global terms; per-service deviations and intercepts omitted. 'dev n' = dev pairs "
                      "where the term fired")
    S.source_note(fig, textwrap.fill(I.source("weights", "platt") + ". Fitted on dev labels only (grouped 5-fold "
                  "selection; MODEL_SPEC 3.2). Sign constraints hold evidence steps >= 0 and flags <= 0, so a weight "
                  "'at bound' was pushed to 0.", 190))
    alt = ("Dumbbell chart of service-head weights, expert prior mean against fitted posterior with 90% interval, in "
           "points before Platt scaling. " + "; ".join(
               f"{t.term}: prior {t.prior_mean * k:+.1f}, fitted {t.post_mean * k:+.1f}" for t in w.itertuples()) +
           f". Shipped contributions multiply these by the Platt slope {a:.2f}.")
    w.to_csv(out / "s5_prior_vs_fitted.csv", index=False)
    S.save(fig, out / "s5_prior_vs_fitted", alt)


def build(load=I.local_load, out=I.OUT):
    t = level_table(pair_points(load))
    levels_chart(t, out)
    w, a = weights_table(load)
    prior_chart(w, a, out)
    return t


if __name__ == "__main__":
    print(build().round(3).to_string())

"""Story 4: the label problem, from published label counts and agreement (no new test computation).

Inputs: model/review/stats/results.json (label counts, never-searched counts, batch position, kappa
crosstabs, AUROC under each label treatment). Dev never-searched = all-v2 never-searched minus the
published test count. Writes s4_label_budget.* and s4_label_agreement.* (png, svg, txt, csv).
Run: .venv-viz/bin/python viz/model/s4_labels.py
"""
import textwrap

import numpy as np
import pandas as pd

import _inputs as I
import style as S

STATES = [("confirmed", "Confirmed", S.SEMANTIC["verified"], "#ffffff"),
          ("contradicted", "Contradicted", S.SEMANTIC["unlikely"], "#ffffff"),
          ("searched_no_info", "Searched, nothing found", S.SEMANTIC["not_verified"], S.INK),
          ("never_searched", "Never searched (budget ran out)", S.SEMANTIC["flagged"], S.INK)]
LAB3 = ["confirmed", "contradicted", "no_info"]


def composition(res):
    inp, vis = res["inputs"], res["visibility_bias_all_v2"]
    ns_all = sum(v["never_searched"] for v in vis["stratum"].values())
    ns = {"test": inp["test_never_searched"], "dev": ns_all - inp["test_never_searched"]}
    rows = []
    for split, cnt, n in (("test", inp["test_label_counts"], inp["n_test"]), ("dev", inp["dev_label_counts"], inp["n_dev"])):
        r = dict(split=split, n=n, confirmed=cnt["confirmed"], contradicted=cnt["contradicted"],
                 searched_no_info=cnt["no_info"] - ns[split], never_searched=ns[split])
        assert sum(r[k] for k, *_ in STATES) == n, r
        rows.append(r)
    return pd.DataFrame(rows), ns_all


def budget_chart(res, out):
    comp, ns_all = composition(res)
    half = res["visibility_bias_all_v2"]["never_searched_by_batch_half"]
    fig = S.plt.figure(figsize=(13, 6.6), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.6, 1])
    ax, bx = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    for yi, r in zip([1, 0], comp.itertuples()):
        left = 0
        for key, lab, col, ink in STATES:
            v = getattr(r, key)
            ax.barh(yi, v, left=left, height=0.55, color=col, **S.bar_style())
            if v >= 3:
                ax.text(left + v / 2, yi, f"{v}", ha="center", va="center", fontsize=11, color=ink)
            left += v
    for key, lab, col, _ in STATES:  # legend row above the test bar, in text ink
        ax.scatter([], [], marker="s", s=90, color=col, label=lab)
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.0), ncols=2, fontsize=10.5)
    ax.set_yticks([1, 0], [f"Test split\n(n = {comp.n[0]})", f"Dev split\n(n = {comp.n[1]})"])
    ax.set_xlim(0, 72)
    ax.set_ylim(-0.5, 2.0)
    ax.set_xlabel("Labelled (facility, service) pairs")
    ax.grid(axis="y", visible=False)
    S.panel_title(ax, "What the v2 gold labels say")
    rows = [("First 10 pairs\nof each batch", half["first10"]), ("Last 10 pairs\nof each batch", half["last10"])]
    for i, (lab, h) in enumerate(rows):
        p, lo, hi = S.wilson(h["never_searched"], h["n"])
        bx.bar(i, p * 100, width=0.55, color=S.SEMANTIC["flagged"], **S.bar_style())
        S.add_interval(bx, [i], [lo * 100], [hi * 100])
        bx.annotate(f"{h['never_searched']} of {h['n']}\n[{lo:.2f}, {hi:.2f}]", (i, hi * 100), xytext=(0, 5),
                    textcoords="offset points", ha="center", va="bottom", fontsize=10.5, color=S.INK)
    bx.set_xticks([0, 1], [r[0] for r in rows])
    bx.set_ylim(0, 100)
    bx.set_ylabel("Pairs never searched (%, 95% Wilson)")
    bx.grid(axis="x", visible=False)
    S.panel_title(bx, "7 batches of 20 pairs shared one 200-search budget\n(position = order in the label file)")
    t = comp.iloc[0]
    S.fig_title(fig, f"{t.searched_no_info + t.never_searched} of {t.n} test labels say 'no public information', "
                     f"and {t.never_searched} of those were never searched; pairs late in a labelling batch went "
                     f"unsearched {half['last10']['never_searched']} of 70 times against "
                     f"{half['first10']['never_searched']} of 70 early on")
    S.source_note(fig, textwrap.fill(I.source("results") + f" (inputs, visibility_bias_all_v2). Dev never-searched "
                  f"= {ns_all} across all 140 v2 pairs minus the {t.never_searched} published for test. Both panels "
                  f"count labels only; no model score is used. Batch-position intervals treat pairs as independent; "
                  f"dev pairs alone show the same pattern (9 of 35 early vs 17 of 34 late, verify/v34_published.py).", 190))
    alt = (f"Left: stacked bars of gold label outcomes. Test, {t.n} pairs: {t.confirmed} confirmed, {t.contradicted} "
           f"contradicted, {t.searched_no_info} searched with nothing found, {t.never_searched} never searched. Dev, "
           f"{comp.n[1]} pairs: {comp.confirmed[1]} confirmed, {comp.contradicted[1]} contradicted, "
           f"{comp.searched_no_info[1]} searched with nothing found, {comp.never_searched[1]} never searched. Right: "
           f"never-searched share by position in the labelling batch, {half['first10']['never_searched']} of 70 for "
           f"the first 10 pairs against {half['last10']['never_searched']} of 70 for the last 10.")
    comp.to_csv(out / "s4_label_budget.csv", index=False)
    pd.DataFrame([dict(position=k, **v) for k, v in half.items()]).to_csv(out / "s4_label_budget_batch.csv", index=False)
    S.save(fig, out / "s4_label_budget", alt)
    return comp


def treatment_table(res):
    pt = res["pair_level_test"]
    a, s = pt["primary_target_all"]["auroc"], pt["primary_target_searched"]["auroc"]
    rows = []
    for k, lab in (("WL_shipped", "Witness Ledger"), ("B4_prior_only", "Expert priors, unfitted (B4)")):
        rows += [dict(system=lab, treatment="All 71, never-searched = not confirmed", auroc=a[k]["raw"],
                      lo=a[k]["raw_boot"]["ci95"][0], hi=a[k]["raw_boot"]["ci95"][1]),
                 dict(system=lab, treatment="Searched 39 only", auroc=s[k]["raw"],
                      lo=s[k]["raw_boot"]["ci95"][0], hi=s[k]["raw_boot"]["ci95"][1]),
                 dict(system=lab, treatment="All 71 as first column, reweighted to the population (IPW)", auroc=a[k]["ipw"],
                      lo=a[k]["ipw_boot"]["ci95"][0], hi=a[k]["ipw_boot"]["ci95"][1])]
    return pd.DataFrame(rows)


def agreement_chart(res, out):
    k = res["kappa"]["all"]["service"]
    # results.json stores pandas crosstab(primary, overlap).to_dict(): outer key = overlap (second) label,
    # inner key = primary label. Rows here = primary labeller, columns = second labeller.
    ct = k["crosstab_overlap_by_primary"]
    m = np.array([[ct.get(c, {}).get(r, 0) for c in LAB3] for r in LAB3])
    fig = S.plt.figure(figsize=(13, 6.6), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 1.25])
    ax, bx = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    from matplotlib.colors import LinearSegmentedColormap
    ax.imshow(m, cmap=LinearSegmentedColormap.from_list("s", [S.SURFACE] + S.SEQUENTIAL[2:9]), vmin=0, vmax=m.max())
    for i in range(3):
        for j in range(3):
            ax.text(j, i, str(m[i, j]), ha="center", va="center", fontsize=15,
                    color="#ffffff" if m[i, j] >= 9 else S.INK, fontweight="bold" if i == j else "normal")
    names = ["Confirmed", "Contradicted", "No info"]
    ax.set_xticks(range(3), names)
    ax.set_yticks(range(3), names)
    ax.set_xlabel("Second (overlap) labeller")
    ax.set_ylabel("Primary labeller")
    ax.grid(False)
    S.panel_title(ax, f"{k['n']} double-labelled pairs: kappa {k['kappa']:.2f} "
                      f"[{k['kappa_boot95'][0]:.2f}, {k['kappa_boot95'][1]:.2f}]")
    t = treatment_table(res)
    xs = {tr: i for i, tr in enumerate(t.treatment.unique())}
    for j, (sysname, col) in enumerate((("Witness Ledger", S.CATEGORICAL[0]), ("Expert priors, unfitted (B4)", S.CATEGORICAL[1]))):
        d = t[t.system == sysname]
        x = np.array([xs[v] for v in d.treatment]) + (j - 0.5) * 0.18
        bx.errorbar(x, d.auroc, yerr=[d.auroc - d.lo, d.hi - d.auroc], fmt="o", color=col, ms=9, capsize=4,
                    elinewidth=1.6, mec=S.SURFACE, label=sysname)
        for xi, v in zip(x, d.auroc):
            bx.annotate(f"{v:.3f}", (xi, v), xytext=(-8 if j == 0 else 8, 0), textcoords="offset points",
                        ha="right" if j == 0 else "left", va="center", fontsize=10, color=S.INK)
    bx.axhline(0.5, color=S.MUTED, lw=1, ls="--")
    bx.set_xticks(range(3), [textwrap.fill(v, 22) for v in xs], fontsize=10)
    bx.set_ylim(0.3, 1.0)
    bx.set_ylabel("Test AUROC (95% interval)")
    bx.grid(axis="x", visible=False)
    bx.legend(loc="upper right", fontsize=10)
    S.panel_title(bx, "Same scores: two ways to count unsearched pairs,\nthen the first one reweighted (IPW, ESS 29)")
    dec = res["kappa"]["both_decisive_service"]
    w = t.set_index(["system", "treatment"]).auroc
    S.fig_title(fig, f"When both labellers reached a verdict they agreed {dec['agree']} of {dec['n']} times; all "
                     f"{int(m.sum() - np.trace(m))} disagreements pair a verdict with 'no info'. Dropping unsearched "
                     f"pairs moves ledger AUROC from {w.iloc[0]:.3f} to {w.iloc[1]:.3f}; reweighting moves it to "
                     f"{w.iloc[2]:.3f}")
    S.source_note(fig, textwrap.fill(I.source("results") + " (kappa, pair_level_test; published). Overlap pairs "
                  "span dev (13) and test (17); kappa interval is a bootstrap over 30 pairs. IPW keeps never-searched "
                  "pairs as not confirmed and reweights the stratified sample to the population (effective sample "
                  "size 29.0).", 190))
    off = m.sum() - np.trace(m)
    alt = (f"Left: 3 by 3 agreement table for {k['n']} pairs labelled twice, rows primary labeller, columns second "
           f"labeller. Diagonal: {m[0,0]} both confirmed, "
           f"{m[1,1]} both contradicted, {m[2,2]} both no info; all {off} disagreements pair a decisive label with "
           f"no info. Cohen's kappa {k['kappa']:.3f}. Right: test AUROC of the ledger and the unfitted expert "
           f"scorecard under three label treatments: " + "; ".join(
               f"{r.system}, {r.treatment}: {r.auroc:.3f} [{r.lo:.3f}, {r.hi:.3f}]" for r in t.itertuples()) + ".")
    pd.DataFrame(m, index=["primary_" + x for x in LAB3], columns=["second_" + x for x in LAB3]).to_csv(
        out / "s4_label_agreement_crosstab.csv")
    t.to_csv(out / "s4_label_agreement_auroc.csv", index=False)
    S.save(fig, out / "s4_label_agreement", alt)


def build(load=I.local_load, out=I.OUT):
    res = load("results")
    comp = budget_chart(res, out)
    agreement_chart(res, out)
    return comp


if __name__ == "__main__":
    print(build().to_string())

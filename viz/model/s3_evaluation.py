"""Story 3: honest evaluation, quoted from the published sealed-test results (no new test computation).

Inputs: model/review/stats/results.json (statistical reviewer's recomputation, the numbers MODEL_SPEC
section 4 uses) and model/proto/fusion/test_metrics.json (location head). Writes s3_auroc_forest.* and
s3_calibration_location.* (png, svg, txt, csv).
Run: .venv-viz/bin/python viz/model/s3_evaluation.py
"""
import textwrap

import numpy as np
import pandas as pd

import _inputs as I
import style as S

SYSTEMS = [  # results.json key -> label, highlight colour
    ("B4_prior_only", "Same scorecard, expert priors, no fitting (B4)", S.CATEGORICAL[1]),
    ("WL_shipped", "Witness Ledger, fitted and shipped", S.CATEGORICAL[0]),
    ("B1_keyword_count", "Keyword count (B1)", S.INK_2),
    ("B2_rule_grade", "Rule grade (B2)", S.INK_2),
    ("B5_M0", "Scorecard fitted from zero priors (B5)", S.INK_2),
    ("stratum_only", "Sampling stratum alone", S.INK_2),
    ("T_only", "Own-text level T alone", S.INK_2),
    ("B3_llm_judge", "LLM judge, llama-3.3-70b (B3)", S.INK_2),
    ("B0_any_mention", "Any mention of the service (B0)", S.INK_2),
]


def auroc_table(res, tm):
    pt = res["pair_level_test"]
    ipw39 = tm["headline_checked"]["auroc_ipw_shipped_minus_system"]  # published; only 6 baselines have it
    a, s, dif = pt["primary_target_all"]["auroc"], pt["primary_target_searched"]["auroc"], pt["paired_diff_raw_primary"]
    rows = []
    for k, lab, _ in SYSTEMS:
        rows.append(dict(system=k, label=lab, auroc_all71=a[k]["raw"], lo=a[k]["raw_boot"]["ci95"][0],
                         hi=a[k]["raw_boot"]["ci95"][1], auroc_searched39=s[k]["raw"], auroc_ipw71=a[k]["ipw"],
                         wl_minus=dif[k]["point"] if k in dif else np.nan,
                         wl_minus_lo=dif[k]["boot"]["ci95"][0] if k in dif else np.nan,
                         wl_minus_hi=dif[k]["boot"]["ci95"][1] if k in dif else np.nan,
                         ipw39_minus=ipw39[k]["mean"] if k in ipw39 else np.nan,
                         ipw39_lo=ipw39[k]["ci95"][0] if k in ipw39 else np.nan,
                         ipw39_hi=ipw39[k]["ci95"][1] if k in ipw39 else np.nan))
    return pd.DataFrame(rows)


def forest(t, res, out):
    fig = S.plt.figure(figsize=(13, 7), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1])
    ax = fig.add_subplot(gs[0])
    bx = fig.add_subplot(gs[1], sharey=ax)
    y = -np.arange(len(t))
    cols = [c for _, _, c in SYSTEMS]
    for yi, r, c in zip(y, t.itertuples(), cols):
        ax.plot([r.lo, r.hi], [yi, yi], color=c, lw=2.2, solid_capstyle="round")
        ax.scatter(r.auroc_all71, yi, s=90, color=c, zorder=3, edgecolors=S.SURFACE, lw=1.5)
        ax.annotate(f"{r.auroc_all71:.3f}", (r.hi, yi), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=10.5, color=S.INK)
    ax.axvline(0.5, color=S.MUTED, lw=1, ls="--")
    ax.text(0.502, y[-1] - 0.75, "0.5 = coin flip", fontsize=9.5, color=S.MUTED, va="center")
    ax.set_yticks(y, t.label)
    ax.set_xlim(0.4, 1.0)
    ax.set_ylim(y[-1] - 1.7, 0.6)  # bottom room for the right panel's legend
    ax.set_xlabel("Test AUROC, confirmed vs not (95% cluster-bootstrap interval)")
    ax.grid(axis="y", visible=False)
    S.panel_title(ax, "Discrimination on the sealed test: 71 pairs, 17 confirmed")
    keep = (t.system != "WL_shipped").values
    d, yd = t[keep].reset_index(drop=True), y[keep]
    for yi, r in zip(yd, d.itertuples()):
        excl = r.wl_minus_lo > 0 or r.wl_minus_hi < 0
        c = S.INK if excl else S.MUTED
        bx.plot([r.wl_minus_lo, r.wl_minus_hi], [yi + 0.14] * 2, color=c, lw=2.2, solid_capstyle="round")
        bx.scatter(r.wl_minus, yi + 0.14, s=70, color=c, zorder=3, edgecolors=S.SURFACE, lw=1.5)
        bx.annotate(f"{r.wl_minus:+.3f} [{r.wl_minus_lo:+.3f}, {r.wl_minus_hi:+.3f}]", (max(r.wl_minus_hi, 0.0), yi + 0.14),
                    xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color=S.INK)
        if np.isfinite(r.ipw39_minus):
            c2 = S.INK if (r.ipw39_lo > 0 or r.ipw39_hi < 0) else S.MUTED
            bx.plot([r.ipw39_lo, r.ipw39_hi], [yi - 0.2] * 2, color=c2, lw=1.4, ls=(0, (3, 2)))
            bx.scatter(r.ipw39_minus, yi - 0.2, s=60, facecolors=S.SURFACE, edgecolors=c2, lw=1.6, zorder=3)
            bx.annotate(f"{r.ipw39_minus:+.3f} [{r.ipw39_lo:+.3f}, {r.ipw39_hi:+.3f}]", (max(r.ipw39_hi, 0.0), yi - 0.2),
                        xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color=S.INK_2)
    bx.axvline(0, color=S.INK_2, lw=1)
    bx.tick_params(axis="y", labelleft=False)
    bx.text(0.0, y[1], "  (reference row)", va="center", fontsize=9.5, color=S.MUTED)
    bx.set_xlim(-0.36, 1.05)
    bx.set_xticks([-0.2, 0, 0.2, 0.4])
    bx.set_xlabel("Ledger minus system (paired, 95% interval)")
    bx.grid(axis="y", visible=False)
    bx.scatter([], [], s=70, color=S.INK, label="All 71, raw (results.json)")
    bx.scatter([], [], s=60, facecolors=S.SURFACE, edgecolors=S.INK, lw=1.6, label="Searched 39, IPW (test_metrics.json)")
    bx.legend(loc="lower right", fontsize=9.5, frameon=True, facecolor=S.SURFACE, edgecolor="none")
    S.panel_title(bx, "Paired difference; dark = interval excludes 0,\ngray = it does not")
    w, b4 = t.set_index("system").loc["WL_shipped"], t.set_index("system").loc["B4_prior_only"]
    S.fig_title(fig, f"On all 71 test pairs the fitted ledger (AUROC {w.auroc_all71:.3f}) does not beat the same "
                     f"scorecard with unfitted expert priors ({b4.auroc_all71:.3f}) but beats the LLM judge and "
                     f"any-mention; on the 39 searched pairs reweighted, expert priors win by "
                     f"{-b4.ipw39_minus:.3f} and no other gain survives")
    S.source_note(fig, textwrap.fill(I.source("results", "test_metrics") + " (pair_level_test and headline_checked, "
                  "published; nothing recomputed here). Left panel: all 71 pairs, never-searched counted as not "
                  "confirmed; story 4 shows how that choice moves AUROC. Hollow markers: fusion's IPW comparison on the "
                  "39 searched pairs (ESS 13.4); not published for stratum-only and T-only.", 190))
    alt = ("Forest plot of test AUROC with 95% intervals for 9 systems on 71 sealed test pairs: " +
           "; ".join(f"{r.label} {r.auroc_all71:.3f} [{r.lo:.3f}, {r.hi:.3f}]" for r in t.itertuples()) +
           ". Right panel: paired differences, ledger minus each system. Intervals exclude zero against "
           "any mention (+0.216), the LLM judge (+0.191), zero-prior fitting (+0.088) and own-text level alone "
           "(+0.149); against the unfitted expert scorecard the difference is -0.013 [-0.076, 0.048]. On the 39 "
           "searched pairs reweighted to the population (IPW), the ledger minus expert priors is -0.129 [-0.252, "
           "-0.026] and no interval against any other baseline excludes 0 (LLM judge -0.016 [-0.269, 0.316]).")
    t.to_csv(out / "s3_auroc_forest.csv", index=False)
    S.save(fig, out / "s3_auroc_forest", alt)


def calib_table(res):
    c = res["pair_level_test"]["calibration_primary_all"]
    return pd.DataFrame([dict(bin=b["bin"], n=b["n"], p_min=b["p_min"], p_max=b["p_max"], mean_p=b["mean_p"],
                              observed=b["observed"], lo=max(b["wilson95"][0], 0.0), hi=b["wilson95"][1],
                              k_confirmed=b["k_confirmed"], k_contradicted=b["k_contradicted"],
                              k_no_info=b["k_no_info"]) for b in c["table"]]), c


def calibration_location(res, tm, out):
    t, c = calib_table(res)
    loc = tm["location_head"]
    hi_n, hi_k = loc["p_l_ge_0_7"]["n"], loc["p_l_ge_0_7"]["yes"]
    lo_n, lo_k = loc["n"] - hi_n, loc["n_yes"] - hi_k  # arithmetic on the published counts
    fig = S.plt.figure(figsize=(13, 6.9), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.3, 1])
    ax, bx = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    ax.plot([0, 0.8], [0, 0.8], color=S.MUTED, lw=1, ls="--")
    ax.text(0.62, 0.66, "perfect calibration", rotation=37, fontsize=9.5, color=S.MUTED)
    ax.errorbar(t.mean_p, t.observed, yerr=[t.observed - t.lo, t.hi - t.observed], fmt="none",
                ecolor=S.INK_2, elinewidth=1.4, capsize=4)
    ax.plot(t.mean_p, t.observed, color=S.CATEGORICAL[0], marker="o", ms=9, mec=S.SURFACE, mew=1.5)
    for r in t.itertuples():
        left = r.bin == 1  # bins 1 and 2 sit close together; push bin 1's label left of its whisker
        ax.annotate(f"{r.k_confirmed}/{r.n} confirmed\n{r.k_no_info} no info", (r.mean_p, r.hi),
                    xytext=(-6 if left else 0, 6), textcoords="offset points", ha="right" if left else "center",
                    va="bottom", fontsize=9, color=S.INK_2)
    ax.set_xlim(0, 0.8)
    ax.set_ylim(0, 0.95)
    ax.set_xlabel("Mean P_S in bin (5 equal-count bins)")
    ax.set_ylabel("Share confirmed by web check (95% Wilson)")
    ece = c["ece_ipw_boot"]["ci95"]
    cs = res["pair_level_test"]["calibration_primary_searched"]
    S.panel_title(ax, textwrap.fill(f"P_S on 71 test pairs: ECE raw {c['ece_raw']:.3f}, IPW {c['ece_ipw']:.3f} "
                      f"[{ece[0]:.3f}, {ece[1]:.3f}], fails the 0.10 rule. Searched 39 only: raw {cs['ece_raw']:.3f}, "
                      f"IPW {cs['ece_ipw']:.3f}, still fails", 62))
    S.small_n_note(ax, int(t.n.min()), text=f"Each bin n = {t.n.min()} to {t.n.max()}: read the intervals")
    rows = [(f"P_L >= 0.7\n(n = {hi_n})", hi_k, hi_n), (f"P_L < 0.7\n(n = {lo_n})", lo_k, lo_n)]
    for i, (lab, k, n) in enumerate(rows):
        p, lo, hi = S.wilson(k, n)
        bars = bx.bar(i, p * 100, width=0.55, color=S.SEMANTIC["verified"] if i == 0 else S.OTHER, **S.bar_style())
        S.add_interval(bx, [i], [lo * 100], [hi * 100])
        bx.annotate(f"{k} of {n}\n[{lo:.2f}, {hi:.2f}]", (i, hi * 100), xytext=(0, 5), textcoords="offset points",
                    ha="center", va="bottom", fontsize=10.5, color=S.INK)
    bx.set_xticks([0, 1], [r[0] for r in rows])
    bx.set_ylim(0, 128)
    bx.set_yticks([0, 25, 50, 75, 100])
    bx.set_ylabel("Location confirmed by web check (%, 95% Wilson)")
    bx.grid(axis="x", visible=False)
    S.panel_title(bx, textwrap.fill(f"Location head P_L on the {loc['n']} test pairs with a yes/no location label "
                      f"({71 - loc['n']} 'unclear' excluded): AUROC {loc['auroc_raw']:.3f}, no interval "
                      f"({loc['n'] - loc['n_yes']} negatives)", 48))
    S.small_n_note(bx, lo_n, where=(0.98, 0.9), text=f"Small samples: n = {hi_n} and {lo_n}")
    S.fig_title(fig, f"P_S runs high: mean {c['mean_p']:.2f} predicted against {c['obs']:.2f} confirmed on the "
                     f"sealed test. Location scores of 0.7 or more were confirmed {hi_k} of {hi_n} times")
    S.source_note(fig, textwrap.fill(I.source("results", "test_metrics") + " (published sealed-test results; "
                  "P_L < 0.7 counts are the published totals minus the P_L >= 0.7 counts). Acceptance rule A3 "
                  "(IPW ECE <= 0.10) fails.", 190))
    alt = (f"Left: reliability diagram for the service score P_S on 71 test pairs in 5 bins. Mean P_S per bin "
           + ", ".join(f"{r.mean_p:.2f}" for r in t.itertuples()) + " against confirmed shares "
           + ", ".join(f"{r.observed:.2f}" for r in t.itertuples()) +
           f". The ranking is monotone but every bin sits below the diagonal; ECE IPW {c['ece_ipw']:.3f}. "
           f"Right: location head. {hi_k} of {hi_n} pairs with P_L at least 0.7 had their location confirmed "
           f"(Wilson 0.76 to 0.97); {lo_k} of {lo_n} below 0.7. Only the {loc['n']} pairs with a yes or no location "
           f"label count; {71 - loc['n']} unclear pairs are excluded.")
    pd.concat([t.assign(panel="P_S reliability"),
               pd.DataFrame([dict(panel="P_L location", bin=lab.split()[0] + " " + lab.split()[1], n=n, k_confirmed=k)
                             for lab, k, n in rows])]).to_csv(out / "s3_calibration_location.csv", index=False)
    S.save(fig, out / "s3_calibration_location", alt)


def build(load=I.local_load, out=I.OUT):
    res = load("results")
    tm = load("test_metrics")
    t = auroc_table(res, tm)
    forest(t, res, out)
    calibration_location(res, tm, out)
    return t


if __name__ == "__main__":
    print(build()[["system", "auroc_all71", "lo", "hi", "wl_minus"]].round(3).to_string())

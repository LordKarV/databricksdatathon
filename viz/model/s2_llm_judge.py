"""Story 2: the LLM judge said yes 239 of 243 times; the ledger did not.

Reads the B3 LLM-judge answers on the 243 benchmark candidates (top-10 keyword candidates of 40 queries,
no labels involved) and joins the ledger's stored P_S, own-text level T and flags. Quotes the published
test AUROCs from results.json. Writes s2_llm_vs_ledger.* (png, svg, txt, csv).
Run: .venv-viz/bin/python viz/model/s2_llm_judge.py
"""
import textwrap

import numpy as np
import pandas as pd

import _inputs as I
import style as S

ROWS = [  # (row label, selector)
    ("T = 5: own text, several fields, plus a unit or quantity", lambda d: d["T"] == 5),
    ("T = 4: own sentences in 2+ fields", lambda d: d["T"] == 4),
    ("T = 3: 2+ own sentences, one field", lambda d: d["T"] == 3),
    ("T = 2: one own sentence", lambda d: d["T"] == 2),
    ("T = 1: tag or list item only", lambda d: d["T"] == 1),
    ("Flag: sentence about another hospital (C = 1)", lambda d: d["C"] >= 1),
    ("Flag: eye or dental facility (S = 1)", lambda d: d["S"] >= 1),  # 3 rows, 2 facilities
]
YES, NO = S.CATEGORICAL[0], S.CATEGORICAL[1]


def table(load):
    llm = load("llm_b3_pairs")
    ps = load("pair_scores")[["unique_id", "service", "name", "p_s", "T", "C", "S", "band"]]
    d = llm.merge(ps, on=["unique_id", "service"], how="left", validate="many_to_one")
    assert d.p_s.notna().all() and len(d) == 243, len(d)
    return d[["query_id", "rank", "unique_id", "name", "service", "offers", "confidence", "quote",
              "p_s", "T", "C", "S", "band"]]


def chart(d, res, load_tm, out):
    fig, ax = S.new_figure(size=(13, 7.4))
    rng = np.random.default_rng(7)  # jitter only
    ylab = []
    for i, (lab, sel) in enumerate(ROWS):
        r = d[sel(d)]
        y = -i + rng.uniform(-0.22, 0.22, len(r))
        yes = r.offers == "yes"
        ax.scatter(r.p_s[yes], y[yes.values], s=46, color=YES, alpha=0.75, edgecolors=S.SURFACE, lw=0.8)
        ax.scatter(r.p_s[~yes], y[~yes.values], s=80, color=NO, marker="D", edgecolors=S.SURFACE, lw=1)
        k, n = int(yes.sum()), len(r)
        ylab.append(f"{lab}\nLLM yes {k} of {n}" + (" (small n)" if n < S.SMALL_N else ""))
    ax.set_yticks(-np.arange(len(ROWS)), ylab, fontsize=10)
    ax.axhline(-4.5, color=S.AXIS, lw=0.8)
    ax.axvspan(0, 0.20, color=S.NEUTRAL, zorder=0)
    ax.text(0.10, -len(ROWS) + 0.45, "Ledger badge\nUnlikely\n(P_S <= 0.20)", ha="center", va="bottom",
            fontsize=9.5, color=S.INK_2)
    ax.set_xlim(0, 0.8)
    ax.set_ylim(-len(ROWS) + 0.4, 0.5)
    ax.set_xlabel("Ledger P_S: chance a public web check confirms the service (stored score)")
    ax.grid(axis="y", visible=False)
    ex = d[(d.name == "Deshmukh Eye Hospital") & (d.service == "cardiac_surgery")].iloc[0]
    ax.annotate(textwrap.fill(f"{ex['name']}, cardiac surgery: LLM yes, confidence {ex.confidence:.0f}, "
                              f"quoting \"{ex.quote}\". Ledger P_S {ex.p_s:.2f}.", 52),
                (ex.p_s, -6), xytext=(0.43, -6.05), textcoords="data", fontsize=9.5, color=S.INK_2,
                va="center", arrowprops=dict(arrowstyle="-", color=S.MUTED, lw=0.8))
    ax.scatter([], [], s=46, color=YES, label="LLM judge: yes")
    ax.scatter([], [], s=80, color=NO, marker="D", label="LLM judge: no")
    ax.legend(loc="upper right", ncols=1, frameon=True, facecolor=S.SURFACE, edgecolor="none")
    a = res["pair_level_test"]["primary_target_all"]["auroc"]
    n_yes, n = int((d.offers == "yes").sum()), len(d)
    conf1 = int(((d.confidence == 1) & (d.offers == "yes")).sum())  # yes answers at confidence 1
    n_q = d.query_id.nunique()
    p_yes, lo, hi = S.wilson(n_yes, n)
    S.fig_title(fig, f"The LLM judge said yes to {n_yes} of {n} benchmark candidates, {conf1} of them at confidence 1; "
                        f"the ledger spread the same candidates from P_S {d.p_s.min():.2f} to {d.p_s.max():.2f}")
    ipw39 = load_tm["headline_checked"]["auroc_ipw_shipped_minus_system"]["B3_llm_judge"]
    S.panel_title(ax, textwrap.fill(f"{n} candidates: up to 10 keyword matches per query, {n_q} of 40 benchmark queries, "
                              f"{d.unique_id.nunique()} facilities. Yes rate {p_yes:.1%} (Wilson 95% "
                              f"{lo:.1%} to {hi:.1%}). Published test AUROC, 71 pairs: LLM judge "
                              f"{a['B3_llm_judge']['raw']:.3f} [{a['B3_llm_judge']['raw_boot']['ci95'][0]:.3f}, "
                              f"{a['B3_llm_judge']['raw_boot']['ci95'][1]:.3f}], ledger "
                              f"{a['WL_shipped']['raw']:.3f} [{a['WL_shipped']['raw_boot']['ci95'][0]:.3f}, "
                              f"{a['WL_shipped']['raw_boot']['ci95'][1]:.3f}]; on the 39 searched pairs reweighted "
                              f"(IPW), ledger minus LLM is {ipw39['mean']:+.3f} "
                              f"[{ipw39['ci95'][0]:+.2f}, {ipw39['ci95'][1]:+.2f}])", 118))
    S.source_note(fig, textwrap.fill(I.source("llm_b3_pairs", "pair_scores", "results", "test_metrics") +
                  ". Flag rows repeat candidates already shown in the T rows. Vertical jitter only.", 190))
    flags = d[(d.C >= 1) | (d.S >= 1) | (d.band == "Unlikely")]
    alt = (f"Dot strip chart. Each dot is one of {n} benchmark candidates, placed by the ledger's P_S and "
           f"grouped by own-text level and flags. The LLM judge (llama-3.3-70b) said yes on {n_yes} of {n} "
           f"({p_yes:.1%}, Wilson 95% {lo:.1%} to {hi:.1%}), confidence 1 on {conf1}. Ledger P_S ranged "
           f"from {d.p_s.min():.2f} to {d.p_s.max():.2f}. The LLM also said yes on all {int((d.C >= 1).sum())} "
           f"candidates with a sentence about another hospital, all {int((d.S >= 1).sum())} eye or dental "
           f"candidates ({d[d.S >= 1].unique_id.nunique()} facilities), and all {int((d.band == 'Unlikely').sum())} the ledger badged Unlikely "
           f"({len(flags)} distinct flagged rows). Published test AUROC on 71 pairs: LLM judge 0.585, ledger 0.776; "
           f"on the 39 searched pairs reweighted to the population the difference is {ipw39['mean']:+.3f} "
           f"[{ipw39['ci95'][0]:+.2f}, {ipw39['ci95'][1]:+.2f}].")
    d.to_csv(out / "s2_llm_vs_ledger.csv", index=False)
    S.save(fig, out / "s2_llm_vs_ledger", alt)
    return dict(n=n, n_queries=n_q, n_yes=n_yes, wilson=(lo, hi), conf1_yes=conf1, unlikely_yes=int(((d.band == "Unlikely") &
                (d.offers == "yes")).sum()), p_s_min=d.p_s.min(), p_s_max=d.p_s.max())


def build(load=I.local_load, out=I.OUT):
    d = table(load)
    stats = load("llm_b3_stats")
    assert stats["offers"]["yes"] == int((d.offers == "yes").sum()), "stats file and pairs disagree"
    return chart(d, load("results"), load("test_metrics"), out)


if __name__ == "__main__":
    print(build())

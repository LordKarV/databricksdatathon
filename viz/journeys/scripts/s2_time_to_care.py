"""Story 2: how long until definitive care, by pathway and state sample, with the estimate's range.

Input: data/plans_best.csv. Output: charts/s2_time_to_care.*, data/s2_ecdf.csv, data/s2_within_window.csv.
Each origin's best plan gives an ETA at the definitive facility plus low/high (geo.travel 10th/90th
percentile ratios, summed over legs). An abstaining origin never reaches care (counted in the denominator).
"""
import numpy as np
import pandas as pd

from common import CHARTS, DATA, PATHWAY_LABEL, STATE_COLOR, STATE_SETS, STUB_NOTE, S, note

PANELS = ["major_trauma", "obstetric_emergency", "stemi", "burns", "sick_newborn"]
GRID = np.arange(0, 301, 2)
WINDOW = 60


def ecdf(x, n):
    x = np.asarray(x, float)
    return np.array([(x <= g).sum() / n for g in GRID])


def tables(df):
    curves, within = [], []
    for pid in PANELS:
        for st in STATE_SETS:
            d = df[(df.pathway == pid) & (df.origin_set == st)]
            n = len(d)
            for col, what in [("def_eta", "definitive"), ("def_low", "definitive_low"), ("def_high", "definitive_high"),
                              ("first_eta", "first_care")]:
                y = ecdf(d[col].dropna(), n)
                curves += [{"pathway": pid, "origin_set": st, "series": what, "minutes": g, "share": v, "n": n}
                           for g, v in zip(GRID, y)]
                k = int((d[col] <= WINDOW).sum())
                p, lo, hi = S.wilson(k, n)
                within.append({"pathway": pid, "origin_set": st, "series": what, "within_minutes": WINDOW,
                               "count": k, "n": n, "share": p, "lo95": lo, "hi95": hi,
                               "median_minutes_reached": float(d[col].median()), "abstain": int((d.best_type == "abstain").sum())})
    return pd.DataFrame(curves), pd.DataFrame(within)


def best_direct_within(df, pid, st, window=WINDOW):
    """Share of a state's origins whose best DIRECT plan (vs_direct in the planner output) reaches a definitive
    facility within the window. For stop plans this is the alternative the planner passed over."""
    d = df[(df.pathway == pid) & (df.origin_set == st)]
    m = d.direct_minutes.where(d.best_type == "one_stop", d.def_eta)
    return S.wilson(int((m <= window).sum()), len(d))


def chart(c, w, df_all):
    fig, axes = S.new_figure(size=(13, 8.6), nrows=2, ncols=3, sharex=True, sharey=True)
    axes = axes.ravel()
    for ax, pid in zip(axes, PANELS):
        for st in STATE_SETS:
            col = STATE_COLOR[st]
            g = c[(c.pathway == pid) & (c.origin_set == st)]
            lo = g[g.series == "definitive_high"].share.values  # slower estimate -> lower curve
            hi = g[g.series == "definitive_low"].share.values
            ax.fill_between(GRID, lo * 100, hi * 100, color=col, alpha=0.13, lw=0)
            ax.plot(GRID, g[g.series == "definitive"].share.values * 100, color=col, lw=2)
            if pid in ("major_trauma", "obstetric_emergency"):
                ax.plot(GRID, g[g.series == "first_care"].share.values * 100, color=col, lw=1.4, ls=(0, (3, 2)))
        ax.axvline(WINDOW, color=S.INK_2, lw=1, ls="--")
        if pid == "stemi":
            ax.axvline(120, color=S.MUTED, lw=1, ls=":")
            ax.text(124, 50, "PCI\n120 min", fontsize=9.5, color=S.INK_2)
        rows = w[(w.pathway == pid) & (w.series == "definitive")].set_index("origin_set")
        txt = "Definitive care within 60 min\n" + "\n".join(
            f"{st}: {rows.loc[st, 'share']*100:.0f}% ({rows.loc[st, 'lo95']*100:.0f} to {rows.loc[st, 'hi95']*100:.0f})"
            for st in STATE_SETS)
        if pid in ("major_trauma", "obstetric_emergency"):
            fr = w[(w.pathway == pid) & (w.series == "first_care")].set_index("origin_set")
            txt += "\nFirst care within 60 min\n" + "\n".join(
                f"{st}: {fr.loc[st, 'share']*100:.0f}% ({fr.loc[st, 'lo95']*100:.0f} to {fr.loc[st, 'hi95']*100:.0f})"
                for st in STATE_SETS)
        ax.text(0.98, 0.03, txt, transform=ax.transAxes, ha="right", va="bottom", fontsize=9.2, color=S.INK,
                linespacing=1.3, bbox=dict(fc=S.SURFACE, ec=S.GRID, boxstyle="round,pad=0.4"))
        S.panel_title(ax, f"{PATHWAY_LABEL[pid]} (n = 150 per state)")
        ax.set_xlim(0, 300)
        ax.set_ylim(0, 100)
        ax.set_xticks([0, 60, 120, 180, 240, 300])
    # legend panel
    lg = axes[5]
    lg.axis("off")
    for i, st in enumerate(STATE_SETS):
        lg.plot([0.05, 0.2], [0.85 - i * 0.11] * 2, color=STATE_COLOR[st], lw=2.5, transform=lg.transAxes)
        lg.text(0.24, 0.85 - i * 0.11, st, transform=lg.transAxes, va="center", fontsize=11.5)
    lg.plot([0.05, 0.2], [0.45, 0.45], color=S.INK_2, lw=2, transform=lg.transAxes)
    lg.text(0.24, 0.45, "Definitive care, best plan", transform=lg.transAxes, va="center", fontsize=10.5)
    lg.fill_between([0.05, 0.2], 0.31, 0.39, color=S.INK_2, alpha=0.15, transform=lg.transAxes, lw=0)
    lg.text(0.24, 0.35, "Range: 10th to 90th percentile\nroad-time ratio, summed over legs", transform=lg.transAxes,
            va="center", fontsize=10.5)
    lg.plot([0.05, 0.2], [0.21, 0.21], color=S.INK_2, lw=1.4, ls=(0, (3, 2)), transform=lg.transAxes)
    lg.text(0.24, 0.21, "First care (stabilising stop)", transform=lg.transAxes, va="center", fontsize=10.5)
    lg.text(0.05, 0.06, "Curves stop below 100% where the planner\nabstains or care takes over 300 min.",
            transform=lg.transAxes, fontsize=10, color=S.INK_2)
    axes[2].tick_params(labelbottom=True)
    for ax in (axes[2], axes[3], axes[4]):
        ax.set_xlabel("Minutes from now")
    for ax in (axes[0], axes[3]):
        ax.set_ylabel("Origins reaching care by then (%)")
    tr = w[(w.pathway == "major_trauma") & (w.origin_set == "Bihar")].set_index("series")
    bd = best_direct_within(df_all, "major_trauma", "Bihar")
    S.fig_title(fig, f"In Bihar, the planner's best trauma plan reaches first care within the hour for "
                     f"{tr.loc['first_care', 'share']*100:.0f}% of sampled origins but definitive care for only "
                     f"{tr.loc['definitive', 'share']*100:.0f}% (95% CI {tr.loc['definitive', 'lo95']*100:.0f} to "
                     f"{tr.loc['definitive', 'hi95']*100:.0f}%), though {bd[0]*100:.0f}% ({bd[1]*100:.0f} to {bd[2]*100:.0f}%) "
                     f"have a lower-probability definitive site within 60 min")
    note(fig, "Share of 150 random PIN centroids per state (derived/v1/pin_gazetteer.parquet, seed 20261121) whose best "
              "plan reaches care by each minute. Definitive ETA includes travel, the stop's dwell (planning placeholder, "
              "kb/pathways/care_pathways.json) and the onward leg. The planner ranks plans by the chance of care in time, so it "
              "often passes over a nearer definitive site whose record is silent on one capability; curves are its choice, not "
              "the nearest site. " + STUB_NOTE, width=200)
    parts = []
    for pid in PANELS:
        r = w[(w.pathway == pid) & (w.series == "definitive")].set_index("origin_set")
        parts.append(f"{PATHWAY_LABEL[pid]}: " + ", ".join(f"{st} {r.loc[st, 'share']*100:.0f}%" for st in STATE_SETS))
    alt = ("Small multiples of cumulative curves: share of sampled origins reaching definitive care by each minute, "
           "for three state samples of 150 PIN centroids, with shaded ranges from the travel estimate's 10th to 90th "
           "percentile. Share reaching definitive care within 60 minutes: " + "; ".join(parts) + ". For major trauma "
           f"in Bihar, first care at a stabilising stop is within 60 minutes for {tr.loc['first_care', 'share']*100:.0f}% "
           f"of origins. {bd[0]*100:.0f}% of Bihar origins have a best direct trauma plan reaching some definitive site within "
           "60 minutes, which the planner passes over for a higher-probability site farther away. Probabilities are the "
           "derived/v1 stub.")
    S.save(fig, CHARTS / "s2_time_to_care", alt)


def main():
    df = pd.read_csv(DATA / "plans_best.csv")
    df = df[df.origin_set.isin(STATE_SETS)]
    c, w = tables(df)
    c.to_csv(DATA / "s2_ecdf.csv", index=False)
    w.to_csv(DATA / "s2_within_window.csv", index=False)
    chart(c, w, df)
    print(w[w.series.isin(["definitive", "first_care"])].round(3).to_string())


if __name__ == "__main__":
    main()

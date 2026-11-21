"""Story 1: direct vs one stop vs abstain, by pathway and origin set; and what a stop buys.

Input: data/plans_best.csv (scripts/run_plans.py). Output: charts/s1_plan_mix.*, charts/s1b_stop_tradeoff.*,
data/s1_plan_mix.csv, data/s1b_stop_tradeoff.csv.
"""
import numpy as np
import pandas as pd

from common import CHARTS, DATA, PATHWAY_LABEL, SETS, STUB_NOTE, S, boot_mean_ci, boot_median_ci, note

ORDER = ["major_trauma", "obstetric_emergency", "burns", "sick_newborn", "stemi", "snakebite"]
KINDS = [("direct", "Direct to definitive care", S.CATEGORICAL[0], "#ffffff"),
         ("one_stop", "Stabilising stop first", S.CATEGORICAL[1], S.INK),
         ("abstain", "Abstain (no evidence within 150 km)", S.OTHER, S.INK)]


def plan_mix(df):
    rows = []
    for pid in ORDER:
        for st in SETS:
            d = df[(df.pathway == pid) & (df.origin_set == st)]
            n = len(d)
            for k, *_ in KINDS:
                c = int((d.best_type == k).sum())
                p, lo, hi = S.wilson(c, n)
                rows.append({"pathway": pid, "origin_set": st, "plan": k, "count": c, "n": n,
                             "share": p, "lo95": lo, "hi95": hi})
    return pd.DataFrame(rows)


def chart_mix(t):
    fig, ax = S.new_figure(size=(12, 9.2))
    ypos, labels, y = [], [], 0.0
    group_mid = {}
    for pid in ORDER:
        start = y
        for st in SETS:
            ypos.append(y)
            n = int(t[(t.pathway == pid) & (t.origin_set == st)].n.iloc[0])
            labels.append(f"{st} (n = {n})")
            y += 1
        group_mid[pid] = (start, y - 1)
        y += 0.9
    ypos = np.array(ypos)
    left = np.zeros(len(ypos))
    for k, name, col, ink in KINDS:
        w = np.array([t[(t.pathway == pid) & (t.origin_set == st) & (t.plan == k)].share.iloc[0] * 100
                      for pid in ORDER for st in SETS])
        ax.barh(ypos, w, left=left, height=0.78, color=col, label=name, **S.bar_style())
        for yi, li, wi in zip(ypos, left, w):
            if wi >= 7:
                ax.text(li + wi / 2, yi, f"{wi:.0f}%", ha="center", va="center", fontsize=10, color=ink)
        left += w
    # the stop share with its 95% Wilson interval, as a text column (the stacked bar cannot carry it)
    for yi, (pid, st) in zip(ypos, [(p_, s_) for p_ in ORDER for s_ in SETS]):
        r = t[(t.pathway == pid) & (t.origin_set == st) & (t.plan == "one_stop")].iloc[0]
        ax.text(1.01, yi, f"{r.share*100:.0f}% ({r.lo95*100:.0f} to {r.hi95*100:.0f})", transform=ax.get_yaxis_transform(),
                ha="left", va="center", fontsize=10, color=S.INK_2)
    ax.text(1.01, ypos[0] - 1.1, "Stop first,\n95% CI", transform=ax.get_yaxis_transform(), ha="left", va="bottom",
            fontsize=10, color=S.INK_2)
    ax.set_yticks(ypos, labels, fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of origins by the planner's best plan (%)")
    ax.grid(axis="y", visible=False)
    for pid, (a, b) in group_mid.items():
        ax.text(-0.01, a - 0.75, PATHWAY_LABEL[pid], transform=ax.get_yaxis_transform(), ha="right",
                va="center", fontsize=12.5, fontweight="bold", color=S.INK)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=11, handlelength=1.2)
    a, b = group_mid["snakebite"]
    ax.text(50, a - 0.75, "The planner's matcher finds anti-snake venom in 5 of 9,959 records (story 4)", ha="center", va="center",
            fontsize=10.5, color=S.INK_2, style="italic")
    tr = t[(t.pathway == "major_trauma") & (t.plan == "one_stop") & (t.origin_set != SETS[0])]
    k, n = int(tr["count"].sum()), int(tr.n.sum())
    p, lo, hi = S.wilson(k, n)
    S.fig_title(fig, f"For major trauma the best plan stops to stabilise first at {p*100:.0f}% of sampled origins "
                     f"(95% CI {lo*100:.0f} to {hi*100:.0f}%); for heart attack it never does, and for snakebite "
                     f"it always abstains")
    note(fig, "Origins: 40 benchmark queries (model/gold/queries.json) and 150 random PIN centroids per state "
                       "(derived/v1/pin_gazetteer.parquet, seed 20261121). Planner: planner/core.py. " + STUB_NOTE)
    alt = ("Horizontal 100% stacked bars, one per pathway and origin set, showing the share of origins whose best "
           f"plan is direct, a stabilising stop first, or abstain. Major trauma: stop first at {k} of {n} state-sample "
           f"origins ({p*100:.0f}%, 95% CI {lo*100:.0f} to {hi*100:.0f}%). Obstetric emergency: stop first at "
           + ", ".join(f"{st} {r.share*100:.0f}%" for st, r in t[(t.pathway == 'obstetric_emergency') & (t.plan == 'one_stop')]
                       .set_index('origin_set').iterrows())
           + ". Heart attack (STEMI): no stop plans; direct for nearly all origins (19 of 487 planned origins are beyond the "
             "120 min lysis gate, but only 48 records mention thrombolysis). Snakebite: abstain for every "
             "origin because only 5 records mention anti-snake venom. Probabilities are the derived/v1 stub.")
    S.save(fig, CHARTS / "s1_plan_mix", alt)
    return p, lo, hi, k, n


def tradeoff(df):
    rows = []
    for pid in ["major_trauma", "obstetric_emergency"]:
        d = df[(df.pathway == pid) & (df.best_type == "one_stop")]
        delay = d.def_eta - d.direct_minutes
        for metric, x in [("First care, stop plan (min)", d.first_eta),
                          ("Definitive care, best direct plan (min)", d.direct_minutes),
                          ("Definitive care, stop plan (min)", d.def_eta),
                          ("Extra minutes to definitive care (stop minus direct)", delay)]:
            m, lo, hi = boot_median_ci(x)
            rows.append({"pathway": pid, "metric": metric, "stat": "median", "value": m, "lo95": lo, "hi95": hi,
                         "q25": np.nanpercentile(x, 25), "q75": np.nanpercentile(x, 75), "n": int(x.notna().sum())})
        for metric, x in [("P(first care in time), best direct plan", d.direct_p_first_care),
                          ("P(first care in time), stop plan", d.p_first_care),
                          ("P(care in time, both windows), best direct plan", d.direct_p_objective),
                          ("P(care in time, both windows), stop plan", d.p_objective)]:
            m, lo, hi = boot_mean_ci(x)
            rows.append({"pathway": pid, "metric": metric, "stat": "mean", "value": m, "lo95": lo, "hi95": hi,
                         "q25": np.nan, "q75": np.nan, "n": int(x.notna().sum())})
    return pd.DataFrame(rows)


def chart_tradeoff(t):
    fig, (ax, bx) = S.new_figure(size=(12, 6.2), ncols=2, gridspec_kw={"width_ratios": [1.35, 1]})
    mins = ["First care, stop plan (min)", "Definitive care, best direct plan (min)", "Definitive care, stop plan (min)"]
    short = ["First care at the stop", "Definitive care, going direct", "Definitive care, via the stop"]
    cols = [S.CATEGORICAL[1], S.CATEGORICAL[0], S.CATEGORICAL[1]]
    y = 0
    yt, yl = [], []
    for pid in ["major_trauma", "obstetric_emergency"]:
        for m, s_, c in zip(mins, short, cols):
            r = t[(t.pathway == pid) & (t.metric == m)].iloc[0]
            ax.plot([r.q25, r.q75], [y, y], color=c, lw=6, alpha=0.35, solid_capstyle="butt")
            ax.plot(r.value, y, "o", color=c, ms=9, mec=S.SURFACE, mew=2, zorder=4)
            ax.annotate(f"{r.value:.0f} min", (r.q75, y), xytext=(6, 0), textcoords="offset points", va="center",
                        fontsize=10.5, color=S.INK)
            yt.append(y)
            yl.append(s_)
            y += 1
        y += 0.8
    ax.set_yticks(yt, yl, fontsize=10.5)
    ax.invert_yaxis()
    ax.axvline(60, color=S.INK_2, lw=1, ls="--")
    ax.set_ylim(y - 0.2, -1.5)
    ax.text(62, y - 0.75, "60 min window", fontsize=10, color=S.INK_2, va="center")
    ax.set_xlim(0, max(t.q75.max() * 1.15, 260))
    ax.set_xlabel("Minutes from now (dot = median, band = middle 50% of origins)")
    ax.grid(axis="y", visible=False)
    n_tr = int(t[(t.pathway == "major_trauma")].n.iloc[0])
    n_ob = int(t[(t.pathway == "obstetric_emergency")].n.iloc[0])
    for yy, lab in [(-0.95, f"Major trauma (n = {n_tr})"), (2.85, f"Obstetric emergency (n = {n_ob})")]:
        ax.text(0.01, yy, lab, transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=12,
                fontweight="bold", bbox=dict(fc=S.SURFACE, ec="none", pad=1))
    S.panel_title(ax, "Time: origins whose best plan is a stop")
    # right: probabilities
    ps = [("P(first care in time), best direct plan", "Going\ndirect", S.CATEGORICAL[0]),
          ("P(first care in time), stop plan", "Via the\nstop", S.CATEGORICAL[1])]
    x = 0
    xt, xl = [], []
    for pid in ["major_trauma", "obstetric_emergency"]:
        for m, s_, c in ps:
            r = t[(t.pathway == pid) & (t.metric == m)].iloc[0]
            b = bx.bar(x, r.value, width=0.7, color=c, **S.bar_style())
            S.add_interval(bx, [x], [r.lo95], [r.hi95])
            bx.annotate(f"{r.value:.2f}", (x, r.hi95), xytext=(0, 3), textcoords="offset points", ha="center",
                        fontsize=11, color=S.INK)
            xt.append(x)
            xl.append(s_)
            x += 1
        x += 0.6
    bx.set_xticks(xt, xl, fontsize=10.5)
    bx.set_ylim(0, 1.05)
    bx.set_ylabel("Mean chance of first care within the window\n(stub probability, 95% bootstrap CI)")
    bx.text(0.5, -0.2, "Major trauma", transform=bx.get_xaxis_transform(), ha="center", fontsize=11.5, fontweight="bold")
    bx.text(3.1, -0.2, "Obstetric emergency", transform=bx.get_xaxis_transform(), ha="center", fontsize=11.5,
            fontweight="bold")
    bx.grid(axis="x", visible=False)
    S.panel_title(bx, "Chance of first care in time (60 min window)")
    tr = t[t.pathway == "major_trauma"].set_index("metric")
    pd_, ps_ = tr.loc["P(first care in time), best direct plan", "value"], tr.loc["P(first care in time), stop plan", "value"]
    dl = tr.loc["Extra minutes to definitive care (stop minus direct)"]
    S.fig_title(fig, f"A stabilising stop wins the trauma golden hour (chance of first care in time {pd_:.2f} going "
                     f"direct, {ps_:.2f} via the stop) but delays definitive care by a median {dl.value:.0f} minutes "
                     f"(95% CI {dl.lo95:.0f} to {dl.hi95:.0f})")
    note(fig, "Origins whose best plan is a stop: benchmark queries plus Bihar, Uttar Pradesh, Maharashtra "
                       "PIN samples. A stop is only considered for definitive facilities more than 60 min away (rule in "
                       "kb/pathways/care_pathways.json); the best direct plan may use a nearer one. "
                       + STUB_NOTE)
    ob = t[t.pathway == "obstetric_emergency"].set_index("metric")
    alt = (f"Left: for {n_tr} major trauma origins whose best plan is a stop, median first care at the stop is "
           f"{tr.loc['First care, stop plan (min)', 'value']:.0f} min, definitive care going direct "
           f"{tr.loc['Definitive care, best direct plan (min)', 'value']:.0f} min and via the stop "
           f"{tr.loc['Definitive care, stop plan (min)', 'value']:.0f} min; per-origin extra time median {dl.value:.0f} min. "
           f"For {n_ob} obstetric emergency origins: first care {ob.loc['First care, stop plan (min)', 'value']:.0f} min, "
           f"definitive direct {ob.loc['Definitive care, best direct plan (min)', 'value']:.0f} min, via stop "
           f"{ob.loc['Definitive care, stop plan (min)', 'value']:.0f} min. Right: mean chance of first care within 60 "
           f"min rises from {pd_:.2f} to {ps_:.2f} for trauma and from "
           f"{ob.loc['P(first care in time), best direct plan', 'value']:.2f} to "
           f"{ob.loc['P(first care in time), stop plan', 'value']:.2f} for obstetric emergencies. Stub probabilities.")
    S.save(fig, CHARTS / "s1b_stop_tradeoff", alt)


def main():
    df = pd.read_csv(DATA / "plans_best.csv")
    t = plan_mix(df)
    t.to_csv(DATA / "s1_plan_mix.csv", index=False)
    print("trauma one-stop share (state samples):", chart_mix(t))
    tt = tradeoff(df)
    tt.to_csv(DATA / "s1b_stop_tradeoff.csv", index=False)
    chart_tradeoff(tt)
    print(t[t.plan == "one_stop"].pivot(index="pathway", columns="origin_set", values="share").round(3))
    print(tt.round(2).to_string())


if __name__ == "__main__":
    main()

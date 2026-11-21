"""Story 1, the witness ledger: points waterfalls for three real cases.

Reads stored model outputs only (no labels): pair_contributions, pair_scores, facility_contributions,
facility_scores, variant_scores, atoms and the review's case file (ranks). Writes
s1_service_waterfalls.* and s1_location_waterfalls.* (png, svg, txt, csv).
Run: .venv-viz/bin/python viz/model/s1_ledger.py
"""
import math
import textwrap

import numpy as np
import pandas as pd

import _inputs as I
import style as S

CASES = [  # (review case id, label shown on the chart)
    ("S1", "Strong"),
    ("U1", "Uncertain"),
    ("C1", "Contaminated"),
]
LOC_TERMS = [("b_loc", "Base"), ("src", "Point\nsource"), ("v_coords", "Coord-\ninates"),
             ("v_pin", "PIN\ncentre"), ("v_city", "Stated\ncity"), ("v_name", "Place in\nname"),
             ("v_state", "Stated\nstate"), ("f_", "Flags")]
SVC = {"dialysis": "dialysis", "emergency_csection": "emergency C-section"}


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


def case_rows(load):
    cases = {c["case"]: c for c in load("cases")}
    ps = load("pair_scores").set_index(["unique_id", "service"])
    vs = load("variant_scores").set_index(["unique_id", "service"])
    fs = load("facility_scores").set_index("unique_id")
    out = []
    for cid, kind in CASES:
        c = cases[cid]
        key = (c["unique_id"], c["service"])
        out.append(dict(case=cid, kind=kind, name=c["name"], service=c["service"], place=c["place"],
                        rank=c["rank"], n_cand=c["n_candidates"], R=c["R_used"], U=c["U"], G=c["G"],
                        d1=c["d1"], d2=c["d2"],
                        p_s=ps.loc[key, "p_s"], p_s_lo=ps.loc[key, "p_s_lo"], p_s_hi=ps.loc[key, "p_s_hi"],
                        T=int(ps.loc[key, "T"]), band=ps.loc[key, "band"],
                        p_s_no_own_filter=vs.loc[key, "p_abl_noown"],
                        p_l=fs.loc[c["unique_id"], "p_l"], p_e=fs.loc[c["unique_id"], "p_e"]))
    return out


def service_table(load, cases):
    pc = load("pair_contributions")
    rows = []
    for c in cases:
        d = pc[(pc.unique_id == next(x for x in load("cases") if x["case"] == c["case"])["unique_id"])
               & (pc.service == c["service"])]
        pts = d.assign(fam=d.term.map(I.family)).groupby("fam").points.sum()
        run = 0.0
        for f in I.FAMILY_ORDER:
            v = float(pts.get(f, 0.0))
            rows.append(dict(case=c["case"], kind=c["kind"], name=c["name"], step=f, label=I.FAMILY_LABEL[f],
                             points=v, start=run, end=run + v))
            run += v
        rows.append(dict(case=c["case"], kind=c["kind"], name=c["name"], step="total", label="Total",
                         points=run, start=0.0, end=run))
        z = run / I.POINTS_PER_LOGIT
        assert abs(sigmoid(z) - c["p_s"]) < 1e-9, (c["case"], sigmoid(z), c["p_s"])  # additivity
    return pd.DataFrame(rows)


def ignored_sentences(load, uid, service):
    pc = load("pair_contributions")
    ids = pc[(pc.unique_id == uid) & (pc.service == service)].rejected_atom_ids.iloc[0]
    parts = str(ids).split("|") if ids else []  # "atom|service|atom|service"
    keys = [f"{a}|{b}" for a, b in zip(parts[::2], parts[1::2])]
    at = load("atoms").set_index("atom_id")
    return [(at.loc[k, "text"], at.loc[k, "named_entity"]) for k in keys if k in at.index]


def draw_waterfall(ax, d, labels, xmin, xmax, show_labels=True, notes=None):
    """Horizontal waterfall: one row per step, top to bottom, ending in the total."""
    y = -np.arange(len(d))
    for yi, r in zip(y, d.itertuples()):
        lo, hi = sorted((r.start, r.end))
        total = r.step == "total"
        col = S.INK_2 if total else (S.MUTED if r.step in ("base", "b_loc") else
                                     (S.DIVERGING[1] if r.points >= 0 else S.DIVERGING[5]))
        ax.barh(yi, max(hi - lo, 0.15), left=lo, height=0.66, color=col, **S.bar_style())
        if yi > y[-1]:
            ax.plot([r.end, r.end], [yi - 0.33, yi - 0.67], color=S.AXIS, lw=1)
        txt = f"{r.points:+.1f}" if abs(r.points) >= 0.05 else "0"
        txt += (notes or {}).get(r.step, "")
        ax.annotate(txt, (hi if r.points >= 0 else lo, yi), xytext=(4 if r.points >= 0 else -4, 0),
                    textcoords="offset points", va="center", ha="left" if r.points >= 0 else "right",
                    fontsize=10.5, color=S.INK, fontweight="bold" if total else "normal",
                    bbox=dict(boxstyle="square,pad=0.1", fc=S.SURFACE, ec="none"))
    ax.axvline(0, color=S.INK_2, lw=0.9)
    ax.set_yticks(y, labels if show_labels else [""] * len(y))
    ax.set_xlim(xmin, xmax)
    ax.grid(axis="y", visible=False)
    return y


def panel_grid(size):
    """Three waterfall axes on top, three text 'card' axes under them."""
    fig = S.plt.figure(figsize=size, constrained_layout=True)
    gs = fig.add_gridspec(2, 3, height_ratios=[3.2, 1])
    axes = [fig.add_subplot(gs[0, 0])]
    axes += [fig.add_subplot(gs[0, i], sharex=axes[0]) for i in (1, 2)]
    cards = [fig.add_subplot(gs[1, i]) for i in range(3)]
    for c in cards:
        c.axis("off")
    return fig, axes, cards


def card(ax, text):
    ax.text(0, 1, text, transform=ax.transAxes, va="top", ha="left", fontsize=9.5, color=S.INK_2,
            linespacing=1.35)


def service_chart(load, cases, tab, out):
    fig, axes, cards = panel_grid((13, 8.2))
    xmin, xmax = min(tab.start.min(), tab.end.min()) - 12, max(tab.start.max(), tab.end.max()) + 12
    for i, (ax, cx, c) in enumerate(zip(axes, cards, cases)):
        d = tab[tab.case == c["case"]]
        draw_waterfall(ax, d, [I.FAMILY_LABEL.get(s, "Total = logit x 28.9") for s in d.step],
                       xmin, xmax, show_labels=i == 0)
        S.panel_title(ax, f"{c['kind']}: {c['name']}\n{SVC[c['service']]}, own text T = {c['T']}")
        ax.set_xlabel("Points (+20 doubles the odds)")
        card(cx, f"P_S = {c['p_s']:.2f} (90% range {c['p_s_lo']:.2f} to {c['p_s_hi']:.2f})\nBadge: {c['band']}\n"
                 f"Rank {c['rank']} of {c['n_cand']} near {c['place'].split(',')[0]}\n"
                 f"U = P_E {c['p_e']:.2f} x P_S {c['p_s']:.2f} x G {c['G']:.3f} = {c['U']:.3f}")
    wock = cases[2]
    uid = next(x for x in load("cases") if x["case"] == wock["case"])["unique_id"]
    ign = ignored_sentences(load, uid, wock["service"])
    card(cards[2], cards[2].texts[0].get_text() + "\nIgnored, names another hospital (term c1, -6.4 points):\n"
         + "\n".join(textwrap.fill(f'"{t}"', 54) for t, _ in ign))
    cards[2].texts[0].remove()
    p, t = cases[0], tab[(tab.case == cases[0]["case"])].set_index("step").points
    S.fig_title(fig, f"Every score is a sum of named points: Panipat's dialysis score gets "
                     f"{t['type_size'] + t['web']:+.0f} from hospital type and web footprint, only "
                     f"{t['text']:+.0f} from its own dialysis sentences")
    S.source_note(fig, textwrap.fill(I.source("pair_contributions", "pair_scores", "cases", "atoms") +
                  ". Points = (20/ln 2) x logit contribution; base includes the Platt offset; each total "
                  "reproduces the stored P_S to 1e-9. P_S range is the stored 90% posterior range.", 190))
    alt = (f"Three horizontal waterfall charts of the points that make up the service score P_S. "
           f"{p['name']} (dialysis): base {t['base']:.1f}, own text {t['text']:+.1f}, related-service hints "
           f"{t['hints']:+.1f}, web footprint {t['web']:+.1f}, facility type and size {t['type_size']:+.1f}, "
           f"total {t['total']:+.1f} points, P_S {p['p_s']:.2f}, rank {p['rank']} of {p['n_cand']}. "
           + " ".join(_alt_case(tab, c) for c in cases[1:]) +
           f" The two ignored Wockhardt sentences both name Nair Hospital, Mumbai Central; without the "
           f"ownership filter its P_S would be {wock['p_s_no_own_filter']:.2f} instead of {wock['p_s']:.2f}. "
           f"Its rank of {wock['rank']} of {wock['n_cand']} comes mostly from location (G {wock['G']:.3f}), "
           f"not from the ignored sentences.")
    tab.to_csv(out / "s1_service_waterfalls.csv", index=False)
    S.save(fig, out / "s1_service_waterfalls", alt)


def _alt_case(tab, c):
    t = tab[tab.case == c["case"]].set_index("step").points
    parts = ", ".join(f"{I.FAMILY_LABEL[f].lower()} {t[f]:+.1f}" for f in I.FAMILY_ORDER if abs(t[f]) >= 0.05)
    return (f"{c['name']} ({SVC[c['service']]}): {parts}, total {t['total']:+.1f} points, P_S {c['p_s']:.2f}, "
            f"rank {c['rank']} of {c['n_cand']}.")


def location_table(load, cases):
    fc = load("facility_contributions")
    uid = {x["case"]: x["unique_id"] for x in load("cases")}
    rows = []
    for c in cases:
        d = fc[(fc.unique_id == uid[c["case"]]) & (fc["head"] == "location")]
        run = 0.0
        for key, lab in LOC_TERMS:
            sel = d[d.term.str.startswith(key)]
            v = float(sel.points.sum())
            vote = ",".join(f"{t}={x:+.0f}" for t, x in zip(sel.term, sel.x_value))
            rows.append(dict(case=c["case"], kind=c["kind"], name=c["name"], step=key,
                             label=lab.replace("\n", " "), votes=vote, points=v, start=run, end=run + v))
            run += v
        rows.append(dict(case=c["case"], kind=c["kind"], name=c["name"], step="total", label="Total",
                         votes="", points=run, start=0.0, end=run))
        assert abs(sigmoid(run / I.POINTS_PER_LOGIT) - c["p_l"]) < 1e-9, c["case"]
    return pd.DataFrame(rows)


def location_chart(cases, tab, out):
    fig, axes, cards = panel_grid((13, 7.6))
    xmin, xmax = min(tab.start.min(), tab.end.min()) - 14, max(tab.start.max(), tab.end.max()) + 16
    for i, (ax, cx, c) in enumerate(zip(axes, cards, cases)):
        d = tab[tab.case == c["case"]].reset_index(drop=True)
        notes = {r.step: f"  ({'agrees' if '+1' in r.votes else 'disagrees'}, weight 0)"
                 for r in d.itertuples()  # witnesses that voted but carry zero weight
                 if r.votes and abs(r.points) < 0.05 and r.step in ("v_coords", "v_name")}
        draw_waterfall(ax, d, [lab.replace("\n", " ").replace("- ", "") for _, lab in LOC_TERMS] + ["Total"],
                       xmin, xmax, show_labels=i == 0, notes=notes)
        S.panel_title(ax, f"{c['kind']}: {c['name']}")
        ax.set_xlabel("Points (+20 doubles the odds)")
        votes = "; ".join(r.votes for r in d.itertuples() if r.votes and r.step.startswith("v_"))
        far = (f"Point used is {c['d1']:.0f} km from {c['place'].split(',')[0]}"
               + (f"; fallback point {c['d2']:.0f} km" if c["d2"] else "") + f"; G = {c['G']:.3f}")
        card(cx, f"P_L = {c['p_l']:.2f} that it is within 25 km of the point we use\n" + textwrap.fill(far, 52) + "\n"
                 + textwrap.fill(f"Votes (+1 agree, -1 disagree): {votes}", 60))
    w = tab[(tab.case == "C1") & (tab.step == "v_city")].points.iloc[0]
    S.fig_title(fig, f"Wockhardt Nagpur's map point and PIN are in Mumbai, {cases[2]['d1']:.0f} km from Nagpur; its "
                     f"stated city disagrees ({w:+.0f} points), so P_L is {cases[2]['p_l']:.2f} and it ranks "
                     f"{cases[2]['rank']} of {cases[2]['n_cand']}")
    S.source_note(fig, textwrap.fill(I.source("facility_contributions", "facility_scores") +
                  ". Location head fitted on 121 rows (MODEL_SPEC 3.3); the coordinates and place-in-name "
                  "votes were fitted to weight 0, so they cannot move P_L.", 190))
    alt = ("Three horizontal waterfall charts of the location score P_L. " + " ".join(
        f"{c['name']}: " + ", ".join(f"{r.label} {r.points:+.1f}" for r in tab[tab.case == c['case']].itertuples()
                                    if abs(r.points) >= 0.05 and r.step != 'total') +
        f", P_L {c['p_l']:.2f}, point used {c['d1']:.0f} km from the query place." for c in cases) +
        " Coordinates and place-in-name votes appear but carry weight 0 in the fitted head.")
    tab.to_csv(out / "s1_location_waterfalls.csv", index=False)
    S.save(fig, out / "s1_location_waterfalls", alt)


def build(load=I.local_load, out=I.OUT):
    cases = case_rows(load)
    tab = service_table(load, cases)
    service_chart(load, cases, tab, out)
    location_chart(cases, location_table(load, cases), out)
    pd.DataFrame(cases).to_csv(out / "s1_cases.csv", index=False)
    return cases


if __name__ == "__main__":
    for c in build():
        print(c["case"], c["name"], round(c["p_s"], 3), round(c["p_l"], 3), c["rank"], c["n_cand"])

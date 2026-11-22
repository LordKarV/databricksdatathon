"""Story 4: the golden hour. Share of people within 60 minutes' drive of trauma or emergency care,
by the strength of the evidence that the facility offers it.

Travel time: least-cost motorized minutes over the MAP 2020 friction surface (common.travel_minutes),
checked against 1,398 OSRM road routes in travel_check.py. Population: WorldPop 2025, 1 km.
Tiers (each a subset of the one before, except the MAP reference):
  MAP   - MAP's own travel-time-to-healthcare raster (any hospital or clinic in OSM / Google, 2019)
  any   - any of the 9,959 usable records in this dataset
  claim - a dataset sentence claims trauma care or 24x7 emergency (common.evidence_flags)
  corr  - claimed and confirmed by a second check (own website quote, OSM emergency=yes,
          or the MoHFW trauma care facility list)
Interval on the corroborated share: thresholds 60 / 1.743 and 60 / 0.705 minutes, the 90th and 10th
percentile of OSRM / raster minutes in travel_check (real routes slower or faster than the raster).
Outputs: charts/s4_golden_hour.*, data/s4_state.csv, data/s4_numbers.json.
"""
import json

import numpy as np
import pandas as pd

import common as C
from common import S

LIMIT = 60
TIERS = [("map", "Any hospital or clinic (MAP 2020 reference)"),
         ("any", "Any record in this dataset"),
         ("claim", "Record claims trauma or 24x7 emergency"),
         ("corr", "Claim confirmed: own website, OSM or MoHFW list")]
MIN_POP = 1e6


def surfaces(d):
    G = C.build_grid()
    out = {}
    tt_map, _, nd = C._read(C.P["map_tt"])
    H, W = G["pop"].shape
    r0, c0 = C.WP_TO_FRICTION_OFFSET
    m = tt_map[r0:r0 + H, c0:c0 + W].astype(np.float32)
    out["map"] = np.where(m == nd, np.inf, m)
    sel = {"any": d.on_grid, "claim": d.on_grid & d.trauma_claimed, "corr": d.on_grid & d.trauma_corroborated}
    for k, m in sel.items():
        out[k] = C.cached_travel(f"trauma_{k}", d.row[m], d.col[m])
    return out


def shares(G, tt, states, limit):
    pop = G["pop"].ravel()
    st = states.ravel()
    within = (tt.ravel() <= limit)
    num = np.bincount(st, weights=pop * within, minlength=st.max() + 1)
    den = np.bincount(st, weights=pop, minlength=st.max() + 1)
    return num, den


def main():
    d = C.facilities()
    G = C.build_grid()
    tt = surfaces(d)
    lgd = C.lgd_table()
    names = sorted(lgd.stname.unique())
    code = {s: i + 1 for i, s in enumerate(names)}
    lut = np.zeros(lgd.grid_id.max() + 1, np.int32)
    lut[lgd.grid_id] = lgd.stname.map(code)
    states = lut[G["dist"]]
    rat = json.loads((C.DATA / "travel_check_numbers.json").read_text())
    lo_thr, hi_thr = LIMIT / rat["ratio_p90"], LIMIT / rat["ratio_p10"]
    rows = []
    tot = {}
    for key, _ in TIERS:
        num, den = shares(G, tt[key], states, LIMIT)
        tot[key] = num[1:].sum() / den[1:].sum()
        for s, i in code.items():
            rows.append(dict(stname=s, tier=key, pop=den[i], within=num[i]))
        if key == "corr":
            for tag, thr in (("lo", lo_thr), ("hi", hi_thr)):
                n2, _ = shares(G, tt[key], states, thr)
                tot[f"corr_{tag}"] = n2[1:].sum() / den[1:].sum()
                for s, i in code.items():
                    rows.append(dict(stname=s, tier=f"corr_{tag}", pop=den[i], within=n2[i]))
    long = pd.DataFrame(rows)
    long["share"] = long.within / long["pop"]
    wide = long.pivot(index="stname", columns="tier", values="share").reset_index()
    wide["pop"] = wide.stname.map(long.drop_duplicates("stname").set_index("stname")["pop"])
    wide["n_corr"] = wide.stname.map(d[d.trauma_corroborated].groupby("stname").size()).fillna(0).astype(int)
    wide["n_claim"] = wide.stname.map(d[d.trauma_claimed].groupby("stname").size()).fillna(0).astype(int)
    pw = G["pop"].ravel()
    for key in ("map", "corr"):
        med = []
        for s in wide.stname:
            m = states.ravel() == code[s]
            v = np.minimum(tt[key].ravel()[m], 10_000)
            med.append(C.weighted_quantile(v, pw[m], 0.5))
        wide[f"median_min_{key}"] = med
    wide["label"] = wide.stname.map(C.title_state)
    wide["people_outside_corr"] = (1 - wide["corr"]) * wide["pop"]
    C.save_csv(wide, "s4_state")
    chart(wide, tot, lo_thr, hi_thr, d, float(G["pop"].sum()))
    bihar = wide.set_index("stname").loc["BIHAR"]
    nums = {f"india_share_{k}": float(v) for k, v in tot.items()}
    nums.update(people_outside_corr=float((1 - tot["corr"]) * pw.sum()),
                people_outside_map=float((1 - tot["map"]) * pw.sum()),
                n_corr=int(d.trauma_corroborated.sum()), n_claim=int(d.trauma_claimed.sum()),
                corr_sources={k: int(d[d.trauma_corroborated][f"trauma_{k}"].sum()) for k in ("web", "osm", "tcf")},
                thresholds_minutes=[lo_thr, hi_thr],
                bihar=dict(bihar[["map", "any", "claim", "corr", "corr_lo", "corr_hi", "median_min_corr", "n_corr"]].astype(float)),
                lowest_corr_states=wide[wide["pop"] >= MIN_POP].nsmallest(5, "corr")[["stname", "corr", "map"]].values.tolist(),
                gap_largest=wide[wide["pop"] >= MIN_POP].assign(g=lambda x: x["map"] - x["corr"]).nlargest(5, "g")[["stname", "g", "people_outside_corr"]].values.tolist())
    C.save_numbers("s4", nums)
    print(json.dumps(nums, indent=1, default=float))


def chart(w, tot, lo_thr, hi_thr, d, pop_total):
    s = w[w["pop"] >= MIN_POP].sort_values("corr").reset_index(drop=True)
    fig, ax = S.new_figure((12, 10.5))
    y = np.arange(len(s))
    # Verification fix: step 2 failed the ordinal light-end contrast check (1.74:1); 3/6/9/12 passes.
    cols = {"map": S.SEQUENTIAL[3], "any": S.SEQUENTIAL[6], "claim": S.SEQUENTIAL[9], "corr": S.SEQUENTIAL[12]}
    ax.hlines(y, s[["map", "any", "claim", "corr"]].min(axis=1) * 100, s[["map", "any", "claim", "corr"]].max(axis=1) * 100,
              color=S.GRID, lw=2, zorder=1)
    S.add_interval(ax, y, s.corr_lo * 100, s.corr_hi * 100, horizontal=True, cap=2, lw=1, color=S.INK_2)
    for key, lab in TIERS:
        ax.scatter(s[key] * 100, y, s=70 if key == "corr" else 48, color=cols[key], zorder=4,
                   edgecolors=S.SURFACE, linewidths=1.2, label=f"{lab}: India {tot[key] * 100:.0f}%")
    ax.set_yticks(y, [f"{l}  ({n:,})" for l, n in zip(s.label, s.n_corr)])
    ax.set_xlim(0, 101)
    ax.set_xlabel(f"Share of people within {LIMIT} minutes' drive (%)")
    ax.grid(axis="y", visible=False)
    bi = s.index[s.stname == "BIHAR"][0]
    ax.get_yticklabels()[bi].set_color(S.INK)
    ax.get_yticklabels()[bi].set_fontweight("bold")
    ax.legend(loc="upper left", fontsize=10.5, frameon=True, facecolor=S.SURFACE, edgecolor="none",
              title="Nearest facility of this kind (dot)", title_fontsize=11)
    # Verification fix: rounded to 10 M (an independent re-solve on MAP's own grid gave 487 M), and "second
    # source" dropped: 1,473 of 1,525 confirmations are the facility's own website.
    S.fig_title(fig, f"About {round((1 - tot['corr']) * pop_total / 1e6, -1):,.0f} million people live more than an "
                     f"hour's drive from a facility with a confirmed trauma or emergency claim, yet "
                     f"{tot['map'] * 100:.1f}% live within an hour of some hospital or clinic", wrap=100)
    S.panel_title(ax, f"{len(s)} states and UTs over 1 M people, sorted by confirmed share; (n) = confirmed facilities, n <= 2 in {int((s.n_corr <= 2).sum())} of them.\n"
                      f"Whisker: confirmed share at {lo_thr:.0f}-{hi_thr:.0f} min (measured route error); India: "
                      f"{(1 - tot['corr_hi']) * pop_total / 1e6:,.0f}-{(1 - tot['corr_lo']) * pop_total / 1e6:,.0f} M "
                      "people outside the hour")
    C.note(fig, f"Drive time: least-cost minutes over the MAP 2020 motorized friction surface (Weiss et al., CC BY), "
                f"checked against 1,398 OSRM road routes (median ratio 1.00, 91% agree on the 60-minute cut). Whisker: "
                f"60 minutes scaled by the 10th and 90th percentile of route/raster ratios. People: WorldPop 2025. "
                f"Confirmed = a dataset sentence claims trauma care or 24x7 emergency and the facility's own website, "
                f"OSM emergency=yes or the MoHFW trauma care list agrees ({int(d.trauma_corroborated.sum()):,} records). "
                f"Government hospitals without a website or list entry cannot be confirmed here: no evidence in this "
                f"dataset is not no care.")
    alt = (f"Dot plot by state of the share of people within 60 minutes' drive of four kinds of facility. India: "
           f"{tot['map'] * 100:.0f}% within an hour of any hospital or clinic (MAP reference), {tot['any'] * 100:.0f}% "
           f"of any record in this dataset, {tot['claim'] * 100:.0f}% of a record claiming trauma or emergency care, "
           f"{tot['corr'] * 100:.0f}% of a confirmed one ({tot['corr_lo'] * 100:.0f}% to {tot['corr_hi'] * 100:.0f}% "
           f"across the travel-time error range). Lowest confirmed shares: "
           + ", ".join(f"{r.label} {r.corr * 100:.0f}%" for r in s.head(4).itertuples()) + ".")
    S.save(fig, C.CHARTS / "s4_golden_hour", alt_text=alt)


if __name__ == "__main__":
    main()

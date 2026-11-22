"""Story 1: facility records per million people, by state and district, against NFHS need.

Numerator: the 9,959 usable records (derived/v1/facility_location.parquet), placed by their cleaned
ranking point (loc_lat, loc_lon) into an LGD district polygon (internal aggregation only).
Denominator: WorldPop 2025 population summed over the same polygons.
Need: NFHS-5 district indicators (data/raw), weighted by WorldPop district population.
Outputs: charts/s1_state_density.*, charts/s1_district_dots.*, data/s1_state.csv, data/s1_district.csv.
"""
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

import common as C
from common import S

STUNT = "child_u5_who_are_stunted_height_for_age_18_pct"
INSUR = "hh_member_covered_health_insurance_pct"
MIN_POP = 1e6
LARGE_POP = 10e6  # "large state" for the stunting rank


def state_table(d, nf):
    t = C.district_population()
    st = t.groupby("stname").agg(pop=("pop", "sum"), n_districts=("grid_id", "size")).reset_index()
    st["records"] = st.stname.map(d.groupby("stname").size()).fillna(0).astype(int)
    lo, hi = C.poisson_ci(st.records)
    st["per_m"] = st.records / st["pop"] * 1e6
    st["per_m_lo"], st["per_m_hi"] = lo / st["pop"] * 1e6, hi / st["pop"] * 1e6
    w = nf.dropna(subset=[STUNT])
    lgd_state = t.dropna(subset=["nfhs_district"]).drop_duplicates(["nfhs_state", "nfhs_district"])
    w = w.merge(lgd_state[["nfhs_state", "nfhs_district", "stname"]], on=["nfhs_state", "nfhs_district"])
    for c in (STUNT, INSUR):
        ww = w.dropna(subset=[c])
        st[c] = st.stname.map(ww.groupby("stname").apply(lambda g: np.average(g[c], weights=g["pop"]),
                                                          include_groups=False))
    st["label"] = st.stname.map(C.title_state)
    return st.sort_values("per_m").reset_index(drop=True)


def spearman_boot(x, y, n=2000, seed=1):
    from scipy.stats import spearmanr
    rng = np.random.default_rng(seed)
    x, y = np.asarray(x), np.asarray(y)
    r = spearmanr(x, y).statistic
    bs = [spearmanr(x[i], y[i]).statistic for i in (rng.integers(0, len(x), len(x)) for _ in range(n))]
    return r, np.nanpercentile(bs, 2.5), np.nanpercentile(bs, 97.5)


def chart_state(st, national, bihar, rho):
    s = st[st["pop"] >= MIN_POP].reset_index(drop=True)
    fig, (a, b) = S.new_figure((12, 10), ncols=2, gridspec_kw=dict(width_ratios=[2.1, 1]), sharey=True)
    y = np.arange(len(s))
    hl = s.stname == "BIHAR"
    colors = np.where(hl, S.CATEGORICAL[1], S.CATEGORICAL[0])
    a.barh(y, s.per_m, color=colors, height=0.72, **S.bar_style())
    S.add_interval(a, y, s.per_m_lo, s.per_m_hi, horizontal=True, cap=2, lw=1)
    a.axvline(national, color=S.INK_2, lw=1)
    a.text(national, len(s) - 0.3, f" India {national:.1f}", color=S.INK_2, fontsize=11, va="bottom")
    a.set_yticks(y, s.label)
    a.set_xlabel("Facility records per million people (95% Poisson interval)")
    a.set_xlim(0, s.per_m_hi.max() * 1.18)
    xr = a.get_xlim()[1]
    for i, r in s.iterrows():
        a.text(xr, i, f"{r.records:,} / {r['pop'] / 1e6:,.1f} M", ha="right", va="center", fontsize=9.5,
               color=S.INK if r.stname == "BIHAR" else S.MUTED)
    a.text(xr, len(s) - 0.3, "records / people", ha="right", va="bottom", fontsize=9.5, color=S.MUTED)
    a.grid(axis="y", visible=False)
    S.panel_title(a, f"Records per million people\n{len(s)} states and UTs with over 1 M people")
    b.scatter(s[STUNT], y, s=46, color=colors, zorder=3, linewidths=0)
    b.set_xlabel("Children under 5 stunted (%, NFHS-5)")
    b.grid(axis="y", visible=False)
    b.set_xlim(15, 47)
    bi = s.index[hl][0]
    b.annotate(f"{s.loc[bi, STUNT]:.1f}%", (s.loc[bi, STUNT], bi), xytext=(-8, 0), textcoords="offset points",
               ha="right", va="center", fontsize=11, color=S.INK)
    S.panel_title(b, f"Need: child stunting\nrho {rho[0]:.2f} [{rho[1]:.2f}, {rho[2]:.2f}] across states")
    # Verification fix: "of any large state" hid Meghalaya (3.5 M people, higher stunting). State the
    # population cut the ranking uses instead.
    big = s[s["pop"] >= LARGE_POP]
    rank = int((big[STUNT] > bihar[STUNT]).sum()) + 1
    nth = {1: "the highest", 2: "the second-highest", 3: "the third-highest"}.get(rank, f"rank {rank} in")
    mi = s.index[s.stname == "MEGHALAYA"][0]
    b.annotate(f"Meghalaya {s.loc[mi, STUNT]:.1f}%\n({s.loc[mi, 'pop'] / 1e6:.1f} M people)", (s.loc[mi, STUNT], mi),
               xytext=(-8, 0), textcoords="offset points", ha="right", va="center", fontsize=10, color=S.INK_2)
    S.fig_title(fig, f"Bihar has {bihar.per_m:.1f} facility records per million people, under a third of the "
                     f"national {national:.1f}, and {nth} child stunting ({bihar[STUNT]:.1f}%) of the {len(big)} "
                     f"states with over {LARGE_POP / 1e6:.0f} million people")
    C.note(fig, "Records: 9,959 usable Virtue Foundation records placed by cleaned location into LGD district polygons "
                       "(aggregation only). People: WorldPop 2025 (CC BY 4.0). Stunting: NFHS-5 district fact sheets, "
                       "population-weighted to state; survey intervals not in the file. A record is a listing in this "
                       "dataset, not a count of hospitals: absence here is not absence of care. Ladakh, Lakshadweep, "
                       "Andaman & Nicobar, Sikkim (< 1 M people) omitted; values in data/s1_state.csv.")
    return fig, s


def chart_districts(dd):
    fig, ax = S.new_figure((10, 10.5))
    bins = [(0, 0, "0 records"), (0, 2, "under 2"), (2, 5, "2 to 5"), (5, 10, "5 to 10"), (10, np.inf, "10 or more")]
    ramp = [None, S.SEQUENTIAL[3], S.SEQUENTIAL[6], S.SEQUENTIAL[9], S.SEQUENTIAL[12]]
    size = np.sqrt(dd["pop"] / 1e6) * 38
    handles = []
    for (lo, hi, lab), col in zip(bins, ramp):
        m = (dd.records == 0) if hi == 0 else ((dd.per_m > lo) & (dd.per_m <= hi) & (dd.records > 0))
        if col is None:
            ax.scatter(dd.cx[m], dd.cy[m], s=size[m], facecolors="none", edgecolors=S.CATEGORICAL[1], linewidths=1.3)
            h = Line2D([], [], marker="o", ls="", mfc="none", mec=S.CATEGORICAL[1], ms=9, mew=1.3)
        else:
            ax.scatter(dd.cx[m], dd.cy[m], s=size[m], color=col, linewidths=0.6, edgecolors=S.SURFACE)
            h = Line2D([], [], marker="o", ls="", color=col, ms=9)
        handles.append((h, f"{lab} ({int(m.sum())} districts, {dd['pop'][m].sum() / 1e6:,.0f} M people)"))
    S.india_point_map(ax, [], [], scale_note=True)
    ax.legend([h for h, _ in handles], [l for _, l in handles], title="Records per million people",
              loc="lower right", fontsize=10.5, title_fontsize=11, frameon=False)
    zero = dd[dd.records == 0]
    S.finding_title(ax, f"{len(zero)} of {len(dd)} districts, home to {zero['pop'].sum() / 1e6:,.0f} million people, "
                        "have no record in the dataset at all", wrap=60,
                    subtitle="One dot per LGD district at its population-weighted centre; dot area = people")
    C.note(fig, "Records: 9,959 usable records by cleaned location. People: WorldPop 2025. District polygons "
                       "(LGD via Datameet) used only to aggregate; no boundaries drawn.")
    return fig


def main():
    d = C.facilities()
    nf = C.nfhs_districts([STUNT, INSUR])
    st = state_table(d, nf)
    national = len(d) / st["pop"].sum() * 1e6
    bihar = st.set_index("stname").loc["BIHAR"]
    s_big = st[st["pop"] >= MIN_POP].dropna(subset=[STUNT])
    rho = spearman_boot(s_big.per_m, s_big[STUNT])
    rho_ins = spearman_boot(s_big.per_m, s_big[INSUR])
    fig, s = chart_state(st, national, bihar, rho)
    S.save(fig, C.CHARTS / "s1_state_density",
           alt_text=f"Ranked bar chart of facility records per million people for {len(s)} states. Bihar has "
                    f"{bihar.records} records for {bihar['pop'] / 1e6:.1f} million people, {bihar.per_m:.2f} per million "
                    f"(95% interval {bihar.per_m_lo:.2f} to {bihar.per_m_hi:.2f}), against {national:.2f} for India. "
                    f"Chandigarh, Goa, Delhi, Punjab and Haryana lead. A second panel shows child stunting: Bihar is "
                    f"second-highest at {bihar[STUNT]:.1f}%, after Meghalaya ({s_big.set_index('stname').loc['MEGHALAYA', STUNT]:.1f}%, "
                    f"3.5 million people), and the highest of the states with over 10 million people. Across states, records per million and stunting have Spearman "
                    f"rho {rho[0]:.2f} (95% bootstrap interval {rho[1]:.2f} to {rho[2]:.2f}).")
    C.save_csv(st[["stname", "label", "pop", "n_districts", "records", "per_m", "per_m_lo", "per_m_hi", STUNT, INSUR]],
               "s1_state")
    t = C.district_population()
    dd = t.copy()
    dd["records"] = dd.grid_id.map(d.groupby("grid_id").size()).fillna(0).astype(int)
    dd["per_m"] = dd.records / dd["pop"] * 1e6
    dd = dd[dd["pop"] > 0]
    fig = chart_districts(dd)
    zero = dd[dd.records == 0]
    bd = dd[dd.stname == "BIHAR"]
    patna = int(bd.set_index("dtname").loc["Patna", "records"])
    S.save(fig, C.CHARTS / "s1_district_dots",
           alt_text=f"Dot map, one dot per district sized by population, no boundaries drawn. {len(zero)} of {len(dd)} "
                    f"districts with {zero['pop'].sum() / 1e6:.0f} million people have zero records; they cluster in "
                    f"the north-east, central India, Bihar and eastern Uttar Pradesh. In Bihar {int((bd.records == 0).sum())} "
                    f"of {len(bd)} districts have none and Patna holds {patna} of {int(bd.records.sum())} records.")
    C.save_csv(dd[["dist_lgd", "dtname", "stname", "nfhs_state", "nfhs_district", "pop", "records", "per_m", "cx", "cy"]],
               "s1_district")
    nums = dict(records=len(d), population=float(st["pop"].sum()), national_per_m=national,
                bihar_records=int(bihar.records), bihar_pop=float(bihar["pop"]), bihar_per_m=float(bihar.per_m),
                bihar_per_m_ci=[float(bihar.per_m_lo), float(bihar.per_m_hi)], bihar_stunting=float(bihar[STUNT]),
                bihar_insurance=float(bihar[INSUR]), bihar_patna=patna, bihar_districts=len(bd),
                bihar_zero_districts=int((bd.records == 0).sum()),
                bihar_patna_pop_share=float(bd.set_index("dtname").loc["Patna", "pop"] / bd["pop"].sum()),
                rho_stunting=list(rho), rho_insurance=list(rho_ins), n_states_rho=len(s_big),
                zero_districts=len(zero), districts=len(dd), zero_pop=float(zero["pop"].sum()),
                top_state=s.iloc[-1].stname, top_per_m=float(s.iloc[-1].per_m),
                ratio_delhi_bihar=float(st.set_index("stname").loc["DELHI", "per_m"] / bihar.per_m))
    C.save_numbers("s1", nums)
    for k, v in nums.items():
        print(k, v)


if __name__ == "__main__":
    main()

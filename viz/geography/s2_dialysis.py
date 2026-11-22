"""Story 2: dialysis need against confirmed dialysis supply, by NFHS-5 district.

Need proxy: mean of four NFHS-5 district prevalences in adults 15+: women and men with high blood
pressure (>= 140/90 or on medicine) and women and men with high blood sugar (> 140 mg/dl or on
medicine). Diabetes and hypertension are the two leading causes of kidney failure; this is a proxy
for future dialysis demand, not a count of patients.
Supply: records whose dialysis claim a second check confirms (common.evidence_flags, own
website quote); share of district people within 60 minutes' drive (common.travel_minutes).
Outputs: charts/s2_dialysis_need_access.*, data/s2_district.csv, data/s2_numbers.json.
"""
import json

import numpy as np
import pandas as pd

import common as C
from common import S

NCD = ["w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
       "m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
       "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
       "m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct"]
LIMIT = 60


def district_access(d, key_mask, name):
    """Population share within LIMIT minutes and population-weighted median minutes, per NFHS district."""
    G = C.build_grid()
    m = d.on_grid & key_mask
    tt = C.cached_travel(name, d.row[m], d.col[m]).ravel()
    lgd = C.lgd_table().dropna(subset=["nfhs_district"])
    keys = lgd.nfhs_state + "|" + lgd.nfhs_district
    codes = {k: i + 1 for i, k in enumerate(sorted(keys.unique()))}
    lut = np.zeros(lgd.grid_id.max() + 2, np.int32)
    lut[lgd.grid_id] = keys.map(codes)
    cell = lut[G["dist"].ravel()]
    pop = G["pop"].ravel()
    n = len(codes) + 1
    within = np.bincount(cell, weights=pop * (tt <= LIMIT), minlength=n)
    within2 = np.bincount(cell, weights=pop * (tt <= 2 * LIMIT), minlength=n)
    den = np.bincount(cell, weights=pop, minlength=n)
    order = np.argsort(cell, kind="stable")
    cs, ts, ps = cell[order], np.minimum(tt[order], 10_000), pop[order]
    bounds = np.searchsorted(cs, np.arange(n + 1))
    med = [C.weighted_quantile(ts[bounds[i]:bounds[i + 1]], ps[bounds[i]:bounds[i + 1]], 0.5)
           if bounds[i + 1] > bounds[i] else np.nan for i in range(n)]
    out = pd.DataFrame({"key": list(codes), "share60": [within[i] / den[i] for i in codes.values()],
                        "share120": [within2[i] / den[i] for i in codes.values()],
                        "median_min": [med[i] for i in codes.values()]})
    return out, tt, pop


def main():
    d = C.facilities()
    nf = C.nfhs_districts(NCD)
    nf["key"] = nf.nfhs_state + "|" + nf.nfhs_district
    nf["ncd"] = nf[NCD].mean(axis=1, skipna=False)
    acc, tt, pop = district_access(d, d.dialysis_corroborated, "dialysis_corr")
    nf = nf.merge(acc, on="key", how="left")
    k = d[d.dialysis_corroborated].assign(key=lambda x: x.nfhs_state + "|" + x.nfhs_district).groupby("key").size()
    kc = d[d.dialysis_claimed].assign(key=lambda x: x.nfhs_state + "|" + x.nfhs_district).groupby("key").size()
    nf["n_corr"] = nf.key.map(k).fillna(0).astype(int)
    nf["n_claim"] = nf.key.map(kc).fillna(0).astype(int)
    lo, hi = C.poisson_ci(nf.n_corr)
    nf["corr_per_m"] = nf.n_corr / nf["pop"] * 1e6
    nf["corr_per_m_lo"], nf["corr_per_m_hi"] = lo / nf["pop"] * 1e6, hi / nf["pop"] * 1e6
    nf = nf.dropna(subset=["ncd"]).reset_index(drop=True)
    q75 = nf.ncd.quantile(0.75)
    nf["burden_q"] = pd.qcut(nf.ncd, 4, labels=["Q1 lowest", "Q2", "Q3", "Q4 highest"])
    nf["hot"] = (nf.ncd >= q75) & (nf.share60 < 0.5)
    C.save_csv(nf[["nfhs_state", "nfhs_district", "pop", "ncd"] + NCD + ["burden_q", "n_claim", "n_corr", "corr_per_m",
                   "corr_per_m_lo", "corr_per_m_hi", "share60", "share120", "median_min", "hot", "cx", "cy"]],
               "s2_district")
    by_q = nf.groupby("burden_q", observed=True).apply(lambda g: pd.Series(dict(
        districts=len(g), pop=g["pop"].sum(), n_corr=g.n_corr.sum(),
        share60=np.average(g.share60, weights=g["pop"]), zero=(g.n_corr == 0).sum())), include_groups=False).reset_index()
    lo, hi = C.poisson_ci(by_q.n_corr)
    by_q["per_m"], by_q["per_m_lo"], by_q["per_m_hi"] = (by_q.n_corr / by_q["pop"] * 1e6, lo / by_q["pop"] * 1e6,
                                                         hi / by_q["pop"] * 1e6)
    C.save_csv(by_q, "s2_by_quartile")
    from scipy.stats import spearmanr
    rho = spearmanr(nf.ncd, nf.share60).statistic
    hot = nf[nf.hot]
    india60 = float((pop * (tt <= LIMIT)).sum() / pop.sum())
    nums = dict(districts=len(nf), n_corr=int(d.dialysis_corroborated.sum()), n_claim=int(d.dialysis_claimed.sum()),
                ncd_q75=float(q75), ncd_range=[float(nf.ncd.min()), float(nf.ncd.max())],
                india_share60=india60, rho_ncd_share60=float(rho),
                hot_districts=len(hot), hot_pop=float(hot["pop"].sum()), hot_zero_corr=int((hot.n_corr == 0).sum()),
                hot_states=hot.groupby("nfhs_state")["pop"].sum().sort_values(ascending=False).head(6).to_dict(),
                top_hot=hot.nlargest(8, "pop")[["nfhs_district", "nfhs_state", "pop", "ncd", "share60", "median_min"]].values.tolist(),
                q4_pop=float(nf[nf.ncd >= q75]["pop"].sum()),
                by_quartile=by_q.to_dict("records"))
    pm = public_vs_dataset(d)
    lgd_with = d[d.dialysis_corroborated].grid_id.nunique()
    op = d.operatorTypeId
    nums.update(pmndp_centres=int(pm.pmndp_centres.sum()), pmndp_districts=int(pm.pmndp_districts.sum()),
                pmndp_states_fewer_centres_than_districts=int((pm.pmndp_centres < pm.pmndp_total_districts).sum()),
                public_claim=int((d.dialysis_claimed & op.isin(["public", "government"])).sum()),
                public_corr=int((d.dialysis_corroborated & op.isin(["public", "government"])).sum()),
                private_corr=int((d.dialysis_corroborated & (op == "private")).sum()),
                lgd_districts_with_corr=int(lgd_with), lgd_districts=int(C.lgd_table().shape[0]),
                bihar_pmndp=int(pm.set_index("stname").loc["BIHAR", "pmndp_centres"]),
                bihar_corr=int(pm.set_index("stname").loc["BIHAR", "corr"]),
                ap_pmndp=int(pm.set_index("stname").loc["ANDHRA PRADESH", "pmndp_centres"]))
    C.save_numbers("s2", nums)
    chart(nf, q75, nums)
    chart_public(pm, nums)
    print(json.dumps(nums, indent=1, default=str)[:3000])


def chart(nf, q75, nums):
    fig, ax = S.new_figure((12, 7.5))
    size = np.sqrt(nf["pop"] / 1e6) * 26
    base = ~nf.hot
    ax.scatter(nf.ncd[base], nf.share60[base] * 100, s=size[base], color=S.CATEGORICAL[0], alpha=0.45,
               edgecolors=S.SURFACE, linewidths=0.6, zorder=2)
    ax.scatter(nf.ncd[nf.hot], nf.share60[nf.hot] * 100, s=size[nf.hot], color=S.CATEGORICAL[1], alpha=0.85,
               edgecolors=S.SURFACE, linewidths=0.6, zorder=3)
    ax.axvline(q75, color=S.INK_2, lw=1)
    ax.axhline(50, color=S.INK_2, lw=1)
    ax.text(q75 + 0.2, 101, "Top quarter of need", fontsize=10.5, color=S.INK_2, va="bottom")
    ax.text(nf.ncd.max(), 51, "half within an hour", fontsize=10.5, color=S.INK_2, ha="right", va="bottom")
    offsets = {"East Godavari": (10, 22), "Chittoor": (12, -14), "Sangli": (8, 4), "West Godavari": (8, 4)}
    for r in nf[nf.hot & nf.nfhs_district.isin(offsets)].itertuples():
        ax.annotate(
                    f"{r.nfhs_district}, {C.title_state(r.nfhs_state)} ({r.pop / 1e6:.1f} M)",
                    (r.ncd, r.share60 * 100), xytext=offsets[r.nfhs_district], textcoords="offset points",
                    fontsize=10, color=S.INK, arrowprops=dict(arrowstyle="-", color=S.INK_2, lw=0.8))
    ax.set_xlabel("NCD burden proxy: mean % of adults with high blood pressure or high blood sugar (NFHS-5)")
    ax.set_ylabel(f"People within {LIMIT} min of confirmed dialysis (%)")
    ax.set_ylim(-3, 106)
    S.fig_title(fig, f"{nums['hot_pop'] / 1e6:,.0f} million people live in {nums['hot_districts']} high-need districts "
                        f"where most people are over an hour from a facility whose own website confirms dialysis", wrap=100)
    S.panel_title(ax, f"{nums['districts']} NFHS-5 districts; dot area = people; orange = top quarter "
                                      f"of need and under half within an hour\n({nums['hot_zero_corr']} of these "
                                      f"{nums['hot_districts']} have no confirmed dialysis facility inside the district).\nOverall access rises "
                                      f"with need: {nums['by_quartile'][3]['share60'] * 100:.0f}% of people in the top "
                                      f"quarter are within an hour, {nums['by_quartile'][0]['share60'] * 100:.0f}% in the bottom")
    C.note(fig, f"Need: mean of four NFHS-5 district prevalences (women and men 15+, BP >= 140/90 and blood sugar > 140 "
                f"mg/dl, including people on medicine); survey intervals are not in the file. Supply: "
                f"{nums['n_corr']} records whose dialysis claim the facility's own website confirms (of "
                f"{nums['n_claim']} that claim it). Drive time over the MAP 2020 friction surface; people WorldPop "
                f"2025. Spearman rho need vs access {nums['rho_ncd_share60']:.2f}. Public dialysis under the "
                f"Pradhan Mantri National Dialysis Programme is mostly absent from this dataset: no evidence here is "
                f"not no care.")
    S.save(fig, C.CHARTS / "s2_dialysis_need_access",
           alt_text=f"Scatter of {nums['districts']} districts: x is the share of adults with high blood pressure or "
                    f"sugar (NFHS-5), y is the share of people within an hour's drive of a confirmed dialysis facility. "
                    f"Need and access are barely related (Spearman {nums['rho_ncd_share60']:.2f}). "
                    f"{nums['hot_districts']} districts with {nums['hot_pop'] / 1e6:.0f} million people are in the top "
                    f"quarter of need with under half the population within an hour; largest: "
                    + ", ".join(f"{r[0]} ({C.title_state(r[1])})" for r in nums["top_hot"][:5]) + ".")


PMNDP = C.ROOT / "data/external/pmndp_counts_and_state_lists/pmndp_state_counts.csv"


def public_vs_dataset(d):
    """NHSRC PMNDP functional public dialysis centres per state (redistributable with attribution)
    against this dataset's dialysis records, claimed and confirmed."""
    pm = pd.read_csv(PMNDP)[["state_key", "nhsrc_functional_centres", "nhsrc_functional_districts", "nhsrc_total_districts"]]
    pm.columns = ["key", "pmndp_centres", "pmndp_districts", "pmndp_total_districts"]
    lgd = C.lgd_table()[["stname"]].drop_duplicates()
    alias = {"andaman and nicobar": "andaman and nicobar islands",
             "dadra nagar haveli daman and diu": "dadra and nagar haveli and daman and diu"}
    lgd["key"] = lgd.stname.map(lambda x: alias.get(C._norm(x), C._norm(x)))
    pm = pm.merge(lgd, on="key", how="left")
    assert pm.stname.notna().all(), pm[pm.stname.isna()]
    pm["claimed"] = pm.stname.map(d[d.dialysis_claimed].groupby("stname").size()).fillna(0).astype(int)
    pm["corr"] = pm.stname.map(d[d.dialysis_corroborated].groupby("stname").size()).fillna(0).astype(int)
    pm["corr_districts"] = pm.stname.map(d[d.dialysis_corroborated].groupby("stname").grid_id.nunique()).fillna(0).astype(int)
    pm["label"] = pm.stname.map(C.title_state)
    C.save_csv(pm, "s2_public_vs_dataset")
    return pm


def chart_public(pm, nums):
    s = pm[pm.pmndp_centres >= 10].sort_values("pmndp_centres").reset_index(drop=True)
    fig, ax = S.new_figure((12, 8.5))
    y = np.arange(len(s))
    ax.hlines(y, s[["corr", "pmndp_centres"]].min(axis=1), s[["corr", "pmndp_centres"]].max(axis=1), color=S.GRID, lw=2)
    ax.scatter(s.pmndp_centres, y, s=60, color=S.CATEGORICAL[0], zorder=3, label="Public dialysis centres, PMNDP (NHSRC)")
    ax.scatter(s.claimed, y, s=40, color=S.SEQUENTIAL[3], zorder=3, label="Records claiming dialysis in this dataset")
    ax.scatter(s["corr"], y, s=60, color=S.CATEGORICAL[1], zorder=4, label="Records with a confirmed dialysis claim")
    ax.set_yticks(y, s.label)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, None)
    ax.set_xlabel("Facilities (count)")
    ax.legend(loc="lower right", fontsize=11)
    bi = s.index[s.stname == "BIHAR"][0]
    ax.annotate(f"Bihar: {s.loc[bi, 'pmndp_centres']} public centres, {s.loc[bi, 'corr']} confirmed records",
                (s.loc[bi, "pmndp_centres"], bi), xytext=(10, 0), textcoords="offset points", va="center",
                fontsize=10.5, color=S.INK)
    # Verification fix: PMNDP counts a district as served when a neighbouring district's centre covers it
    # (README), so "centres in all 751 districts" overstated; the bound below needs no matching.
    S.finding_title(ax, f"The government reports {nums['pmndp_centres']:,} public dialysis centres serving all "
                        f"{nums['pmndp_districts']} districts; only {nums['public_claim']} public records in this "
                        f"dataset claim dialysis", wrap=90,
                    subtitle=f"{len(s)} states with 10 or more PMNDP centres; counts, not rates. Confirmed records: "
                             f"{nums['private_corr']} of {nums['n_corr']} private, {nums['public_corr']} public")
    C.note(fig, "Public centres: NHSRC PMNDP state table (nhsrcindia.org/pmndp-map-table, read 2026-11-21; NHSRC "
                "permits reproduction with acknowledgement). It reports functional dialysis in every district of every "
                f"state, but {nums['pmndp_states_fewer_centres_than_districts']} states have fewer centres than districts, so some "
                "districts are served from a neighbour. Records: this dataset, by cleaned location; confirmed = the facility's own website states "
                "dialysis. The two lists are different populations, mostly public vs mostly private; a referral tool "
                "built on the dataset alone would miss the public network.")
    S.save(fig, C.CHARTS / "s2_public_vs_dataset",
           alt_text=f"Dot plot by state comparing public dialysis centres under PMNDP ({nums['pmndp_centres']:,} serving "
                    f"{nums['pmndp_districts']} districts) with dataset records that claim dialysis "
                    f"({nums['n_claim']:,}) and those confirmed by a website ({nums['n_corr']}). Bihar has "
                    f"{nums['bihar_pmndp']} public centres and {nums['bihar_corr']} confirmed records. Confirmed "
                    f"records sit in {nums['lgd_districts_with_corr']} of {nums['lgd_districts']} districts.")


if __name__ == "__main__":
    main()

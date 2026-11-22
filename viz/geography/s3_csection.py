"""Story 3: caesarean access against caesarean rates, by NFHS-5 district.

Rate: NFHS-5 births in the 5 years before the survey delivered by caesarean section (district fact
sheets), and the same in public and private facilities. WHO (2015 statement on caesarean section
rates): population rates below about 10% are a sign that women who need a caesarean do not get one.
Supply, per million women aged 15-49 (WorldPop 2025, summed over LGD district polygons):
  claimed   - a dataset sentence claims emergency caesarean section (common.evidence_flags);
  confirmed - claimed and the facility's own website or a LaQshya Maternity OT certificate agrees;
  LaQshya   - public facilities whose Maternity OT was ever certified under LaQshya (NHSRC master
              list, file 08-04-2026), matched to districts by name. Independent of this dataset.
Outputs: charts/s3_csection_access.*, data/s3_district.csv, data/s3_bands.csv, data/s3_numbers.json.
"""
import json

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

import common as C
from common import S

RATE = "births_delivered_by_csection_5y_pct"
PRIV = "births_in_a_private_fac_that_were_delivered_by_csection_5y_pct"
PUB = "births_in_a_public_fac_that_were_delivered_by_csection_5y_pct"
INST = "institutional_birth_5y_pct"
BANDS = [0, 5, 10, 20, 30, 45, 100]
BAND_LABELS = ["under 5%", "5-10%", "10-20%", "20-30%", "30-45%", "45% or more"]
LQ_STATE = {"DNH, D&D": "DADRA,NAGAR HAVELI,DAMAN & DIU", "Jammu & Kashmir": "JAMMU & KASHMIR"}


def laqshya_districts():
    """LaQshya facilities with a Maternity OT certificate -> LGD district -> NFHS-5 district key."""
    lq = pd.read_parquet(C.P["lq_all"])
    lq = lq[lq["Maternity OT"].notna()].copy()
    lgd = C.lgd_table()
    lq["stname"] = lq.state.map(lambda s: LQ_STATE.get(s, s.upper()))
    out = []
    for r in lq.itertuples():
        cands = lgd[lgd.stname == r.stname]
        names = {C._norm(n): i for i, n in zip(cands.index, cands.dtname)}
        hit = process.extractOne(C._norm(r.district), list(names), scorer=fuzz.token_set_ratio) if names else None
        ok = hit is not None and hit[1] >= 85
        row = lgd.loc[names[hit[0]]] if ok else None
        out.append(dict(lq_id=r.lq_id, state=r.state, district=r.district, ftype=r.ftype,
                        valid_until=r._5, matched=ok, lgd_dtname=row.dtname if ok else None,
                        nfhs_state=row.nfhs_state if ok else None, nfhs_district=row.nfhs_district if ok else None))
    return pd.DataFrame(out)


def main():
    d = C.facilities()
    nf = C.nfhs_districts([RATE, PRIV, PUB, INST])
    nf["key"] = nf.nfhs_state + "|" + nf.nfhs_district
    dk = d.assign(key=d.nfhs_state + "|" + d.nfhs_district)
    for col in ("claimed", "corroborated"):
        nf[f"n_{col}"] = nf.key.map(dk[dk[f"csection_{col}"]].groupby("key").size()).fillna(0).astype(int)
    lq = laqshya_districts()
    C.save_csv(lq, "s3_laqshya_match")
    lqk = lq[lq.matched].assign(key=lambda x: x.nfhs_state + "|" + x.nfhs_district)
    nf["n_laqshya"] = nf.key.map(lqk.groupby("key").size()).fillna(0).astype(int)
    lqv = lqk[pd.to_datetime(lqk.valid_until) >= "2026-04-08"]
    nf["n_laqshya_valid"] = nf.key.map(lqv.groupby("key").size()).fillna(0).astype(int)
    nf = nf.dropna(subset=[RATE]).reset_index(drop=True)
    nf["band"] = pd.cut(nf[RATE], BANDS, labels=BAND_LABELS, right=False)
    C.save_csv(nf[["nfhs_state", "nfhs_district", "pop", "wra", RATE, PUB, f"{PUB}_flag", PRIV, f"{PRIV}_flag", INST,
                   "band", "n_claimed", "n_corroborated", "n_laqshya", "cx", "cy"]], "s3_district")
    rows = []
    for b, g in nf.groupby("band", observed=True):
        r = dict(band=b, districts=len(g), wra=g.wra.sum(), births_cs_median=g[RATE].median())
        for col in ("claimed", "corroborated", "laqshya"):
            k = g[f"n_{col}"].sum()
            lo, hi = C.poisson_ci(k)
            r.update({f"{col}_n": int(k), f"{col}_per_m": k / r["wra"] * 1e6,
                      f"{col}_lo": float(lo) / r["wra"] * 1e6, f"{col}_hi": float(hi) / r["wra"] * 1e6})
        r["districts_zero_claimed"] = int((g.n_claimed == 0).sum())
        rows.append(r)
    bands = pd.DataFrame(rows)
    C.save_csv(bands, "s3_bands")
    low = nf[nf[RATE] < 10]
    high = nf[nf[RATE] >= 30]
    both = nf.dropna(subset=[PRIV, PUB])
    both = both[(both[f"{PRIV}_flag"] == "ok") & (both[f"{PUB}_flag"] == "ok")]
    nums = dict(districts=len(nf), n_claimed=int(d.csection_claimed.sum()), n_corr=int(d.csection_corroborated.sum()),
                corr_sources=dict(web=int((d.csection_corroborated & d.csection_web).sum()),
                                  laqshya=int((d.csection_corroborated & d.csection_laqshya).sum())),
                laqshya_mot=len(lq), laqshya_matched=int(lq.matched.sum()),
                laqshya_valid_on_file_date=int((pd.to_datetime(lq.valid_until) >= "2026-04-08").sum()),
                low_districts=len(low), low_wra=float(low.wra.sum()), low_claimed=int(low.n_claimed.sum()),
                low_corr=int(low.n_corroborated.sum()), low_laqshya=int(low.n_laqshya.sum()), low_laqshya_valid=int(low.n_laqshya_valid.sum()),
                low_states=low.groupby("nfhs_state").size().sort_values(ascending=False).head(6).to_dict(),
                high_districts=len(high), high_wra=float(high.wra.sum()), high_claimed=int(high.n_claimed.sum()),
                high_corr=int(high.n_corroborated.sum()), high_laqshya=int(high.n_laqshya.sum()),
                priv_vs_pub_districts=len(both),
                priv_minus_pub_median=float((both[PRIV] - both[PUB]).median()),
                priv_gt_pub_share=float((both[PRIV] > both[PUB]).mean()),
                priv_gt_pub_wilson=list(S.wilson(int((both[PRIV] > both[PUB]).sum()), len(both))),
                bands=bands.to_dict("records"))
    lo_r = bands.iloc[:2]
    hi_r = bands.iloc[-2:]
    nums["ratio_claimed_high_vs_low"] = float((hi_r.claimed_n.sum() / hi_r.wra.sum()) / (lo_r.claimed_n.sum() / lo_r.wra.sum()))
    nums["ratio_laqshya_low_vs_high"] = float((lo_r.laqshya_n.sum() / lo_r.wra.sum()) / (hi_r.laqshya_n.sum() / hi_r.wra.sum()))
    C.save_numbers("s3", nums)
    chart(bands, nums)
    chart_pub_priv(both, nums)
    print(json.dumps({k: v for k, v in nums.items() if k != "bands"}, indent=1, default=str))
    print(bands.to_string())


def chart(b, nums):
    fig, ax = S.new_figure((12, 7.2))
    x = np.arange(len(b))
    w = 0.26
    series = [("claimed", "Claims emergency C-section (this dataset)", S.CATEGORICAL[0], -w),
              ("corroborated", "Claim confirmed by website or LaQshya", S.SEQUENTIAL[11], 0),
              ("laqshya", "Public Maternity OT ever certified under LaQshya (not from this dataset)", S.CATEGORICAL[1], w)]
    for key, lab, col, off in series:
        bars = ax.bar(x + off, b[f"{key}_per_m"], width=w, color=col, label=lab, **S.bar_style())
        S.add_interval(ax, x + off, b[f"{key}_lo"], b[f"{key}_hi"], cap=2, lw=1)
    ax.set_xticks(x, [f"{l}\n{n} districts\n{wra / 1e6:,.0f} M women" for l, n, wra in zip(b.band, b.districts, b.wra)])
    ax.set_xlabel("Share of births by C-section in the district (NFHS-5, 2019-21)")
    ax.set_ylabel("Facilities per million women aged 15-49\n(95% Poisson interval)")
    ax.axvline(1.5, color=S.INK_2, lw=1)
    ax.set_ylim(0, max(b.laqshya_hi.max(), b.claimed_hi.max()) * 1.32)
    ax.text(1.45, 2.6, "WHO: rates under\nabout 10% suggest\nunmet need ", ha="right", va="top",
            fontsize=10.5, color=S.INK_2)
    ax.legend(loc="upper left", bbox_to_anchor=(0.36, 1.0), fontsize=10.5)
    ax.grid(axis="x", visible=False)
    S.fig_title(fig, f"Where under 10% of births are caesareans ({nums['low_districts']} districts), the dataset has "
                        f"{nums['low_claimed']} C-section claims; the public LaQshya list has {nums['low_laqshya']} maternity "
                        f"theatres ever certified there ({nums['low_laqshya_valid']} still valid)", wrap=100)
    S.panel_title(ax, f"{nums['districts']} NFHS-5 districts grouped by caesarean rate.\nDataset claims per woman "
                             f"are {nums['ratio_claimed_high_vs_low']:.0f}x higher where rates top 30% than under 10%, "
                             f"LaQshya theatres about {1 / nums['ratio_laqshya_low_vs_high']:.0f}x")
    C.note(fig, f"Claims: {nums['n_claimed']} records with a dataset sentence claiming emergency C-section; confirmed: "
                f"{nums['n_corr']} of them. LaQshya: {nums['laqshya_mot']} public facilities with a Maternity OT certificate "
                f"in the NHSRC master list (file 08-04-2026; {nums['laqshya_valid_on_file_date']} still valid on that "
                f"date), {nums['laqshya_matched']} placed in a district by name; NHSRC permits reproduction with "
                f"acknowledgement. Women 15-49: WorldPop 2025 over LGD polygons. NFHS district rates carry survey "
                f"error not in the file. No evidence in this dataset is not no care.")
    S.save(fig, C.CHARTS / "s3_csection_access",
           alt_text="Grouped bars of facilities per million women aged 15-49 across six bands of district C-section "
                    "rate. Dataset C-section claims rise steeply with the rate: "
                    + ", ".join(f"{r.band} {r.claimed_per_m:.2f}" for r in b.itertuples())
                    + ". Public LaQshya-certified maternity theatres per million women: "
                    + ", ".join(f"{r.band} {r.laqshya_per_m:.2f}" for r in b.itertuples())
                    + f". In {nums['low_districts']} districts with rates under 10% the dataset has "
                      f"{nums['low_claimed']} C-section claims and LaQshya lists {nums['low_laqshya']} certified theatres.")


def chart_pub_priv(b, nums):
    fig, ax = S.new_figure((9, 8))
    size = np.sqrt(b.wra / 1e6) * 40
    ax.scatter(b[PUB], b[PRIV], s=size, color=S.CATEGORICAL[0], alpha=0.5, edgecolors=S.SURFACE, linewidths=0.6)
    ax.plot([0, 100], [0, 100], color=S.INK_2, lw=1)
    ax.text(62, 58, "same rate", rotation=45, rotation_mode="anchor", fontsize=10.5, color=S.INK_2, ha="left")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_aspect("equal")
    ax.set_xlabel("C-section share of births in public facilities (%)")
    ax.set_ylabel("C-section share of births in private facilities (%)")
    S.finding_title(ax, f"In {nums['priv_gt_pub_share'] * 100:.0f}% of districts private facilities deliver more babies "
                        f"by C-section than public ones; the median gap is {nums['priv_minus_pub_median']:.0f} points",
                    wrap=62, subtitle=f"{nums['priv_vs_pub_districts']} NFHS-5 districts where both rates rest on 50+ "
                                      f"births (95% Wilson {nums['priv_gt_pub_wilson'][1] * 100:.1f}-"
                                      f"{nums['priv_gt_pub_wilson'][2] * 100:.1f}%); dot area = women 15-49")
    C.note(fig, "Source: NFHS-5 district fact sheets (2019-21), births in the 5 years before the survey. Districts "
                "with a suppressed (*) or 25-49 case (bracketed) value for either sector are left out. This dataset "
                "is 88% private records (8,805 of 9,959), so its C-section evidence comes from the high-rate sector.",
           width=120)
    S.save(fig, C.CHARTS / "s3_public_private",
           alt_text=f"Scatter of {nums['priv_vs_pub_districts']} districts, public-facility C-section rate on x and "
                    f"private-facility rate on y. {nums['priv_gt_pub_share'] * 100:.1f}% of dots sit above the "
                    f"equal-rate line; the median private minus public gap is {nums['priv_minus_pub_median']:.1f} "
                    "percentage points.")


if __name__ == "__main__":
    main()

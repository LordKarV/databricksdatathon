"""Pattern 5: public vs private hospitals: claims, evidence, empanelment, hours, web, geography and data quality.

Population: records typed hospital with a stated operator (public or private); operator "not stated" is excluded.
For each binary metric: rates with Wilson intervals, the difference (Newcombe interval, Fisher/chi-square p), and
an adjusted odds ratio (logistic, HC1) holding stated beds, URL count and region fixed. Geography: people within
25 km (WorldPop 2025) compared by medians with a bootstrap interval and a Mann-Whitney p.
Fitted on discovery, re-measured on holdout.
Outputs: data/p5_public_private.csv, data/tests_p5.csv, charts/p5_public_private.*
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from common import CHARTS, DATA, SEED, S, facility, newcombe, read_input, register, two_prop_p, wilson
from p3_quality import design

METRICS = {
    "any_acute": "Claims any of 20 acute services",
    "any_strong": "Has a strong grade for a service",
    "any_web_service": "Own website confirms a service",
    "site_alive": "Website answers",
    "pmjay": "Text says PM-JAY empanelled",
    "cghs": "Text says CGHS empanelled",
    "private_insurance": "Text says private insurance accepted",
    "h24_any": "Text says open 24x7",
    "nabh_listed": "Matched to the NABH list",
    "contaminated": "Has another facility's text",
    "drift50": "Pin over 50 km from PIN",
}


def frame() -> pd.DataFrame:
    from p1_cooccurrence import ACUTE
    from common import services
    d = design(facility())
    sm = services()
    d["any_acute"] = (sm[sorted(ACUTE)].sum(axis=1).reindex(d.unique_id).to_numpy() > 0).astype(int)
    d["any_strong"] = (d.n_strong > 0).astype(int)
    d["any_web_service"] = (d.n_web_services > 0).astype(int)
    d["site_alive"] = d.site_alive.fillna(0)
    wp = read_input("data/external/worldpop_r2025a/derived/facility_population.parquet").drop_duplicates("unique_id")
    d["pop_25km"] = d.unique_id.map(wp.set_index("unique_id").pop_25km)
    d = d[(d.ftype == "hospital") & d.operator.isin(["public", "private"])].copy()
    d["public"] = (d.operator == "public").astype(int)
    return d


def adj_or(d: pd.DataFrame, m: str) -> tuple[float, float, float, float]:
    x = d.dropna(subset=[m])
    r = smf.logit(f"{m} ~ public + log2_beds + beds_missing + log2_urls + C(region)", x).fit(disp=0, cov_type="HC1")
    lo, hi = r.conf_int().loc["public"]
    return float(np.exp(r.params["public"])), float(np.exp(lo)), float(np.exp(hi)), float(r.pvalues["public"])


def median_diff(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float, float]:
    rng = np.random.default_rng(SEED)
    boots = [np.median(rng.choice(a, len(a))) - np.median(rng.choice(b, len(b))) for _ in range(2000)]
    return float(np.median(a) - np.median(b)), *np.percentile(boots, [2.5, 97.5]), float(stats.mannwhitneyu(a, b).pvalue)


def main() -> None:
    d = frame()
    rows, tests = [], []
    for m, lab in METRICS.items():
        res = {}
        for sp in ["discovery", "holdout"]:
            x = d[(d.split == sp) & d[m].notna()]
            k1, n1 = int(x[x.public == 1][m].sum()), int((x.public == 1).sum())
            k0, n0 = int(x[x.public == 0][m].sum()), int((x.public == 0).sum())
            res[sp] = dict(k1=k1, n1=n1, k0=k0, n0=n0, diff=newcombe(k1, n1, k0, n0), p=two_prop_p(k1, n1, k0, n0),
                           adj=adj_or(x, m), r1=wilson(k1, n1), r0=wilson(k0, n0))
        dsc, ho = res["discovery"], res["holdout"]
        rows.append(dict(metric=m, label=lab, pub_rate=dsc["r1"][0], pub_lo=dsc["r1"][1], pub_hi=dsc["r1"][2], pub_k=dsc["k1"], pub_n=dsc["n1"],
                         pri_rate=dsc["r0"][0], pri_lo=dsc["r0"][1], pri_hi=dsc["r0"][2], pri_k=dsc["k0"], pri_n=dsc["n0"],
                         diff=dsc["diff"][0], diff_lo=dsc["diff"][1], diff_hi=dsc["diff"][2], p=dsc["p"],
                         adj_or=dsc["adj"][0], adj_lo=dsc["adj"][1], adj_hi=dsc["adj"][2], adj_p=dsc["adj"][3],
                         ho_pub_rate=ho["r1"][0], ho_pri_rate=ho["r0"][0], ho_diff=ho["diff"][0], ho_diff_lo=ho["diff"][1],
                         ho_diff_hi=ho["diff"][2], ho_p=ho["p"], ho_adj_or=ho["adj"][0], ho_adj_lo=ho["adj"][1],
                         ho_adj_hi=ho["adj"][2], ho_adj_p=ho["adj"][3]))
        n, hn = dsc["n1"] + dsc["n0"], ho["n1"] + ho["n0"]
        tests.append(dict(test_id=f"p5_{m}_diff", family="public_private", description=f"public minus private hospitals: {lab}",
                          effect_type="rate difference", effect=dsc["diff"][0], lo=dsc["diff"][1], hi=dsc["diff"][2], p=dsc["p"], n=n,
                          ho_effect=ho["diff"][0], ho_lo=ho["diff"][1], ho_hi=ho["diff"][2], ho_p=ho["p"], ho_n=hn))
        tests.append(dict(test_id=f"p5_{m}_adj", family="public_private", description=f"public vs private hospitals, adjusted: {lab}",
                          effect_type="adjusted odds ratio", effect=dsc["adj"][0], lo=dsc["adj"][1], hi=dsc["adj"][2], p=dsc["adj"][3], n=n,
                          ho_effect=ho["adj"][0], ho_lo=ho["adj"][1], ho_hi=ho["adj"][2], ho_p=ho["adj"][3], ho_n=hn))
    g = {sp: median_diff(*(d[(d.split == sp) & (d.public == v)].pop_25km.dropna().to_numpy() / 1e6 for v in (1, 0)))
         for sp in ["discovery", "holdout"]}
    tests.append(dict(test_id="p5_pop25_median", family="public_private",
                      description="public minus private hospitals: median people within 25 km (millions)",
                      effect_type="median difference", effect=g["discovery"][0], lo=g["discovery"][1], hi=g["discovery"][2],
                      p=g["discovery"][3], n=int(d[d.split == "discovery"].pop_25km.notna().sum()), ho_effect=g["holdout"][0],
                      ho_lo=g["holdout"][1], ho_hi=g["holdout"][2], ho_p=g["holdout"][3], ho_n=int(d[d.split == "holdout"].pop_25km.notna().sum())))
    out = pd.DataFrame(rows)
    out.to_csv(DATA / "p5_public_private.csv", index=False)
    register(tests, "p5")
    pd.set_option("display.width", 250)
    print(out[["label", "pub_k", "pub_n", "pub_rate", "pri_rate", "diff", "diff_lo", "diff_hi", "adj_or", "adj_lo", "adj_hi", "ho_pub_rate", "ho_pri_rate", "ho_adj_or", "ho_adj_lo", "ho_adj_hi"]].round(3).to_string())
    print("pop25 median diff (M)", {k: np.round(v, 3) for k, v in g.items()},
          "medians", d.groupby("public").pop_25km.median().round(0).to_dict())
    chart(out)


def chart(o: pd.DataFrame) -> None:
    fig, ax = S.new_figure(size=(12, 7.5))
    o = o.iloc[::-1].reset_index(drop=True)
    y = np.arange(len(o))
    for col, pre, lab in [(S.CATEGORICAL[0], "pub", f"Public hospitals (n = {o.pub_n.max():,})"),
                          (S.CATEGORICAL[1], "pri", f"Private hospitals (n = {o.pri_n.max():,})")]:
        ax.errorbar(o[f"{pre}_rate"] * 100, y, xerr=[(o[f"{pre}_rate"] - o[f"{pre}_lo"]) * 100, (o[f"{pre}_hi"] - o[f"{pre}_rate"]) * 100],
                    fmt="o", ms=8, color=col, capsize=0, elinewidth=1.6, label=lab + ", discovery")
        ax.scatter(o[f"ho_{pre}_rate"] * 100, y + 0.28, marker="|", s=90, color=col, lw=2)
    for i, r in o.iterrows():
        ax.plot([r.pub_rate * 100, r.pri_rate * 100], [i, i], color=S.GRID, lw=3, zorder=0)
        ax.text(101, i, f"adj. OR {r.adj_or:.2f} ({r.adj_lo:.2f}-{r.adj_hi:.2f})", va="center", fontsize=8.5, color=S.INK_2)
    ax.scatter([], [], marker="|", s=90, color=S.MUTED, lw=2, label="holdout rate (tick above each row)")
    ax.set_yticks(y, o.label)
    ax.set_xlim(0, 125)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xlabel("Hospitals with the attribute (%, 95% Wilson interval)")
    ax.legend(frameon=False, fontsize=9, loc="lower right", bbox_to_anchor=(1.0, -0.25), ncol=3)
    c = o.set_index("metric")
    S.finding_title(ax, f"Public hospitals say PM-JAY {c.adj_or['pmjay']:.1f} times the odds of private ones, yet only "
                        f"{c.pub_rate['site_alive']*100:.0f}% have a website that answers vs {c.pri_rate['site_alive']*100:.0f}%",
                    subtitle="Hospitals with a stated operator; adjusted odds ratios hold stated beds, URL count and region fixed")
    S.source_note(fig, "Source: viz/patterns/p5_public_private.py; kb/vf_details (PM-JAY, CGHS, 24x7 text), kb/crawl, derived/v1")
    S.save(fig, str(CHARTS / "p5_public_private"), alt_text=(
        f"Dot plot of 11 attributes for public vs private hospitals. PM-JAY text: {c.pub_rate['pmjay']*100:.0f}% vs {c.pri_rate['pmjay']*100:.0f}%. "
        f"Website answers: {c.pub_rate['site_alive']*100:.0f}% vs {c.pri_rate['site_alive']*100:.0f}%. Another facility's text: "
        f"{c.pub_rate['contaminated']*100:.0f}% vs {c.pri_rate['contaminated']*100:.0f}%."))


if __name__ == "__main__":
    main()

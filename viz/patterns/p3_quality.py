"""Pattern 3: which facility attributes go with contamination, location drift and claim inflation.

Three multivariable models, each fitted separately on the discovery and holdout splits with standard errors
clustered by NFHS district:
  contaminated (record has a sentence attributed to another facility): logistic, odds ratios;
  drift50 (raw map pin more than 50 km from the record's own PIN centroid): logistic, odds ratios;
  n_services (of 36 taxonomy services claimed in own text; claim breadth, i.e. inflation once type and size are
  held fixed): Poisson with robust errors, rate ratios.
Every coefficient is one registered test. Reference levels: hospital, private operator, year 2010+, website alive,
South region, no PM-JAY / NABH mention.
Outputs: data/p3_coefficients.csv, data/tests_p3.csv, charts/p3_forest.*
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from common import CHARTS, DATA, S, facility, register

REGION = {
    "North": ["DELHI", "HARYANA", "PUNJAB", "HIMACHAL PRADESH", "JAMMU AND KASHMIR", "LADAKH", "CHANDIGARH",
              "UTTARAKHAND", "UTTAR PRADESH", "RAJASTHAN"],
    "East": ["BIHAR", "JHARKHAND", "ODISHA", "WEST BENGAL"],
    "Northeast": ["ASSAM", "MEGHALAYA", "MANIPUR", "MIZORAM", "NAGALAND", "TRIPURA", "ARUNACHAL PRADESH", "SIKKIM"],
    "Central": ["MADHYA PRADESH", "CHHATTISGARH"],
    "West": ["MAHARASHTRA", "GUJARAT", "GOA", "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"],
}
RHS = ("C(ftype, Treatment('hospital')) + C(operator, Treatment('private')) + log2_beds + beds_missing"
       " + C(year_band, Treatment('2010+')) + log2_urls + agg10 + social10 + official10"
       " + C(web, Treatment('alive')) + pmjay + nabh_text + nabh_listed + C(region, Treatment('South'))")
LABELS = {
    "C(ftype, Treatment('hospital'))[T.clinic]": "Type: clinic (vs hospital)",
    "C(ftype, Treatment('hospital'))[T.dentist]": "Type: dentist (vs hospital)",
    "C(ftype, Treatment('hospital'))[T.other]": "Type: other (vs hospital)",
    "C(operator, Treatment('private'))[T.public]": "Operator: public (vs private)",
    "C(operator, Treatment('private'))[T.unknown]": "Operator: not stated (vs private)",
    "log2_beds": "Beds stated, per doubling",
    "beds_missing": "Beds not stated",
    "C(year_band, Treatment('2010+'))[T.before 1990]": "Established before 1990 (vs 2010+)",
    "C(year_band, Treatment('2010+'))[T.1990-2009]": "Established 1990-2009 (vs 2010+)",
    "C(year_band, Treatment('2010+'))[T.unknown]": "Year not stated (vs 2010+)",
    "log2_urls": "Source URLs, per doubling",
    "agg10": "Aggregator share of URLs, per 10 points",
    "social10": "Social share of URLs, per 10 points",
    "official10": "Official-site share of URLs, per 10 points",
    "C(web, Treatment('alive'))[T.dead]": "Website does not answer (vs answers)",
    "C(web, Treatment('alive'))[T.none]": "No website (vs answers)",
    "pmjay": "Text says PM-JAY empanelled",
    "nabh_text": "Text says NABH",
    "nabh_listed": "Matched to the NABH list",
    "C(region, Treatment('South'))[T.North]": "Region North (vs South)",
    "C(region, Treatment('South'))[T.East]": "Region East (vs South)",
    "C(region, Treatment('South'))[T.Northeast]": "Region Northeast (vs South)",
    "C(region, Treatment('South'))[T.Central]": "Region Central (vs South)",
    "C(region, Treatment('South'))[T.West]": "Region West (vs South)",
}
MODELS = {"contaminated": ("logit", "odds ratio"), "drift50": ("logit", "odds ratio"), "n_services": ("poisson", "rate ratio")}


def design(f: pd.DataFrame) -> pd.DataFrame:
    d = f.copy()
    d["log2_beds"] = np.log2(d.beds.where(d.beds > 0)).fillna(np.log2(d.beds.where(d.beds > 0)).median())
    d["beds_missing"] = d.beds.isna().astype(int)
    d["year_band"] = pd.cut(d.year_est, [0, 1989, 2009, 2100], labels=["before 1990", "1990-2009", "2010+"]).astype(str)
    d.loc[d.year_est.isna(), "year_band"] = "unknown"
    d["log2_urls"] = np.log2(d.n_urls)
    d["agg10"] = d.share_aggregator.fillna(0) * 10
    d["social10"] = d.share_social.fillna(0) * 10
    d["official10"] = d.share_official.fillna(0) * 10
    d["web"] = np.where(d.has_website == 0, "none", np.where(d.site_alive == 1, "alive", "dead"))
    st2r = {s: r for r, ss in REGION.items() for s in ss}
    d["region"] = d.state.map(st2r).fillna("South")
    d["cluster"] = (d.nfhs_state.fillna("") + "|" + d.nfhs_district.fillna(d.state)).astype("category").cat.codes
    return d


def fit(d: pd.DataFrame, outcome: str) -> pd.DataFrame:
    d = d.dropna(subset=[outcome])
    kind, _ = MODELS[outcome]
    fam = sm.families.Binomial() if kind == "logit" else sm.families.Poisson()
    m = smf.glm(f"{outcome} ~ {RHS}", d, family=fam).fit(cov_type="cluster", cov_kwds={"groups": d.cluster})
    ci = m.conf_int()
    return pd.DataFrame({"term": m.params.index, "effect": np.exp(m.params.values), "lo": np.exp(ci[0].values),
                         "hi": np.exp(ci[1].values), "p": m.pvalues.values, "n": int(m.nobs)})


def main() -> None:
    d = design(facility())
    rows, tests = [], []
    for outcome, (_, etype) in MODELS.items():
        r = {sp: fit(d[d.split == sp], outcome).set_index("term") for sp in ["discovery", "holdout"]}
        t = r["discovery"].join(r["holdout"].add_prefix("ho_")).drop(index="Intercept").reset_index()
        t["outcome"] = outcome
        rows.append(t)
        for x in t.itertuples():
            tests.append(dict(test_id=f"p3_{outcome}_{x.term}", family="quality_correlates",
                              description=f"{LABELS.get(x.term, x.term)} on {outcome}", effect_type=f"adjusted {etype}",
                              effect=x.effect, lo=x.lo, hi=x.hi, p=x.p, n=x.n, ho_effect=x.ho_effect, ho_lo=x.ho_lo,
                              ho_hi=x.ho_hi, ho_p=x.ho_p, ho_n=x.ho_n))
    c = pd.concat(rows)
    c["label"] = c.term.map(LABELS)
    c.to_csv(DATA / "p3_coefficients.csv", index=False)
    register(tests, "p3")
    pd.set_option("display.width", 220)
    print(c[["outcome", "label", "effect", "lo", "hi", "p", "ho_effect", "ho_lo", "ho_hi", "ho_p"]].round(3).to_string())
    chart(c)


def chart(c: pd.DataFrame) -> None:
    fig, axes = S.new_figure(size=(14, 9), ncols=3, sharey=True)
    terms = [t for t in LABELS if t in set(c.term)]
    y = np.arange(len(terms))
    titles = {"contaminated": "Another facility's text (odds ratio)", "drift50": "Pin over 50 km from PIN (odds ratio)",
              "n_services": "Services claimed (rate ratio)"}
    for ax, outcome in zip(axes, MODELS):
        x = c[c.outcome == outcome].set_index("term").reindex(terms)
        for off, pre, col, lab in [(-0.17, "", S.CATEGORICAL[0], "discovery"), (0.17, "ho_", S.CATEGORICAL[2], "holdout")]:
            ax.errorbar(x[pre + "effect"], y + off, xerr=[x[pre + "effect"] - x[pre + "lo"], x[pre + "hi"] - x[pre + "effect"]],
                        fmt="o", ms=5, color=col, ecolor=col, elinewidth=1.4, capsize=0,
                        label=f"{lab} (n = {int(x[pre + 'n'].iloc[0]):,})")
        ax.axvline(1, color=S.MUTED, lw=1)
        ax.set_xscale("log")
        ax.set_xticks([0.05, 0.1, 0.25, 0.5, 1, 2, 4], ["0.05", "0.1", "0.25", "0.5", "1", "2", "4"])
        ax.minorticks_off()
        ax.set_xlabel(titles[outcome].split("(")[1].rstrip(")") + " (log scale, 95% CI)")
        S.panel_title(ax, titles[outcome].split(" (")[0])
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, ["discovery (70% of facilities)", "holdout (30%)"], loc="upper right", ncol=2, frameon=False, fontsize=10)
    axes[0].set_yticks(y, [LABELS[t] for t in terms], fontsize=9.5)
    axes[0].invert_yaxis()
    con = c[c.outcome == "contaminated"].set_index("term")
    u = con.loc["log2_urls"]
    pu, nw = con.loc["C(operator, Treatment('private'))[T.public]"], con.loc["C(web, Treatment('alive'))[T.none]"]
    S.fig_title(fig, f"With record breadth held fixed, public operators (odds ratio {pu.effect:.2f}, {pu.lo:.2f} to {pu.hi:.2f}) and "
                     f"records with no website ({nw.effect:.2f}, {nw.lo:.2f} to {nw.hi:.2f}) still carry more of another facility's text; "
                     f"breadth is the largest effect ({u.effect:.2f} per doubling of URLs)")
    S.source_note(fig, "Multivariable GLMs, errors clustered by district, fitted separately on the discovery (70%) and holdout (30%) facilities. "
                       "Source: viz/patterns/p3_quality.py; data/p3_coefficients.csv")
    S.save(fig, str(CHARTS / "p3_forest"), alt_text=(
        f"Forest plot of adjusted odds and rate ratios for contamination, location drift and claim breadth. Source URLs per doubling: "
        f"contamination odds ratio {u.effect:.2f} ({u.lo:.2f} to {u.hi:.2f}) in discovery and {u.ho_effect:.2f} in holdout."))


if __name__ == "__main__":
    main()

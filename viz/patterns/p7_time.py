"""Pattern 7: does the stated year of establishment relate to claims, web presence or trust?

yearEstablished is stated for 4,754 of 9,959 records (valid 1800 to 2026); an audit found it is usually read from
the record's own description (383 of 416), so it is a claim, not an independent fact.
Per decade of establishment: website present, website answers (among records with a website), services claimed,
contamination and location drift, with Wilson / t intervals. Models: one coefficient per decade of age
(year - 2000) / 10, adjusted for facility type, URL count and stated beds, fitted separately on each split.
Heaping: share of years ending in 0 or 5 vs the 20% expected without rounding (binomial test).
Outputs: data/p7_decades.csv, data/tests_p7.csv, charts/p7_time.*
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from common import CHARTS, DATA, S, facility, register, wilson
from p3_quality import design

DECADES = [1800, 1970, 1990, 2000, 2010, 2020, 2027]
DLAB = ["before 1970", "1970-89", "1990-99", "2000-09", "2010-19", "2020-26"]
OUTCOMES = {"has_website": ("logit", "Has a website"), "site_alive": ("logit", "Website answers (among with a website)"),
            "contaminated": ("logit", "Has another facility's text"), "drift50": ("logit", "Pin over 50 km from PIN"),
            "n_services": ("poisson", "Services claimed")}


def main() -> None:
    d = design(facility())
    y = d[d.year_est.notna()].copy()
    y["decade"] = pd.cut(y.year_est, DECADES, right=False, labels=DLAB)
    y["age10"] = (2000 - y.year_est) / 10
    y.loc[y.has_website == 0, "site_alive"] = np.nan
    tests, rows = [], []
    for o, (kind, lab) in OUTCOMES.items():
        res = {}
        for sp in ["discovery", "holdout"]:
            x = y[(y.split == sp)].dropna(subset=[o])
            fam = sm.families.Binomial() if kind == "logit" else sm.families.Poisson()
            m = smf.glm(f"{o} ~ age10 + C(ftype) + log2_urls + log2_beds + beds_missing", x, family=fam).fit(cov_type="HC1")
            lo, hi = m.conf_int().loc["age10"]
            res[sp] = (np.exp(m.params["age10"]), np.exp(lo), np.exp(hi), m.pvalues["age10"], int(m.nobs))
        (e, lo, hi, p, n), (he, hlo, hhi, hp, hn) = res["discovery"], res["holdout"]
        tests.append(dict(test_id=f"p7_age_{o}", family="time", description=f"10 years older: {lab}",
                          effect_type="adjusted " + ("odds ratio" if kind == "logit" else "rate ratio") + " per decade older",
                          effect=e, lo=lo, hi=hi, p=p, n=n, ho_effect=he, ho_lo=hlo, ho_hi=hhi, ho_p=hp, ho_n=hn))
        for dec, g in y[y.split == "discovery"].groupby("decade", observed=True):
            v = g[o].dropna()
            if kind == "logit":
                r, l_, h_ = wilson(int(v.sum()), len(v))
            else:
                r = v.mean(); se = v.std(ddof=1) / np.sqrt(len(v)); l_, h_ = r - 1.96 * se, r + 1.96 * se
            rows.append(dict(outcome=o, decade=dec, n=len(v), value=r, lo=l_, hi=h_))
    for dec_, g in y[y.split == "discovery"].groupby("decade", observed=True):
        v = g.n_urls
        se = v.std(ddof=1) / np.sqrt(len(v))
        rows.append(dict(outcome="n_urls", decade=dec_, n=len(v), value=v.mean(), lo=v.mean() - 1.96 * se, hi=v.mean() + 1.96 * se))
    res = {}
    for sp in ["discovery", "holdout"]:
        x = y[y.split == sp]
        m = smf.logit("contaminated ~ age10", x).fit(disp=0, cov_type="HC1")
        lo, hi = m.conf_int().loc["age10"]
        res[sp] = (np.exp(m.params["age10"]), np.exp(lo), np.exp(hi), m.pvalues["age10"], int(m.nobs))
    (e, lo, hi, p, n), (he, hlo, hhi, hp, hn) = res["discovery"], res["holdout"]
    tests.append(dict(test_id="p7_age_contaminated_unadjusted", family="time", description="10 years older: contamination, unadjusted",
                      effect_type="odds ratio per decade older", effect=e, lo=lo, hi=hi, p=p, n=n, ho_effect=he, ho_lo=hlo,
                      ho_hi=hhi, ho_p=hp, ho_n=hn))
    # heaping on 0 and 5
    res = {}
    for sp in ["discovery", "holdout"]:
        x = y[y.split == sp]
        k, n = int((x.year_est % 5 == 0).sum()), len(x)
        bt = stats.binomtest(k, n, 0.2)
        ci = bt.proportion_ci()
        res[sp] = (k / n - 0.2, ci.low - 0.2, ci.high - 0.2, bt.pvalue, n)
    (e, lo, hi, p, n), (he, hlo, hhi, hp, hn) = res["discovery"], res["holdout"]
    tests.append(dict(test_id="p7_heaping", family="time", description="share of years ending in 0 or 5 minus 20%",
                      effect_type="proportion difference", effect=e, lo=lo, hi=hi, p=p, n=n, ho_effect=he, ho_lo=hlo,
                      ho_hi=hhi, ho_p=hp, ho_n=hn))
    register(tests, "p7")
    dec = pd.DataFrame(rows)
    dec.to_csv(DATA / "p7_decades.csv", index=False)
    print(pd.DataFrame(tests)[["test_id", "effect", "lo", "hi", "p", "n", "ho_effect", "ho_lo", "ho_hi", "ho_p"]].round(3).to_string())
    print(dec.round(3).to_string())
    print("year known", len(y), "of", len(d), "median", y.year_est.median())
    chart(dec, pd.DataFrame(tests))


def chart(dec: pd.DataFrame, t: pd.DataFrame) -> None:
    fig, axes = S.new_figure(size=(14, 5.5), ncols=3)
    labels = {**{k: v[1] for k, v in OUTCOMES.items()}, "n_urls": "Source URLs in the record"}
    for ax, o, unit in zip(axes, ["contaminated", "n_urls", "n_services"], ["%", "mean", "mean"]):
        x = dec[dec.outcome == o]
        k = 100 if unit == "%" else 1
        b = ax.bar(range(len(x)), x.value * k, color=S.CATEGORICAL[0], **S.bar_style())
        S.add_interval(ax, range(len(x)), x.lo * k, x.hi * k)
        ax.set_xticks(range(len(x)), [f"{a}\n(n = {n:,})" for a, n in zip(x.decade, x.n)], fontsize=8)
        ax.set_ylabel(labels[o] + (" (%, 95% CI)" if unit == "%" else " (mean, 95% CI)"), fontsize=10)
        if f"p7_age_{o}" in set(t.test_id):
            r = t.set_index("test_id").loc[f"p7_age_{o}"]
            S.panel_title(ax, f"Adjusted, per decade older: {r.effect:.2f} ({r.lo:.2f} to {r.hi:.2f})")
        else:
            S.panel_title(ax, "The confounder: older records cite more URLs")
    s = t.set_index("test_id")
    a = s.loc["p7_age_site_alive"]
    c = s.loc["p7_age_contaminated"]
    raw = dec[dec.outcome == "contaminated"].set_index("decade").value
    S.fig_title(fig, f"Records of pre-1970 facilities carry another facility's text {raw.iloc[0]*100:.0f}% of the time vs "
                     f"{raw.iloc[-1]*100:.0f}% for 2020s ones, but the gap is URL count: adjusted, age changes the odds by "
                     f"{c.effect:.2f} per decade ({c.lo:.2f} to {c.hi:.2f})")
    S.source_note(fig, "Discovery records stating a year (data/p7_decades.csv). Ratios adjusted for type, URL count and stated beds. "
                       "Source: viz/patterns/p7_time.py")
    S.save(fig, str(CHARTS / "p7_time"), alt_text=(
        f"Three bar panels by decade of establishment: contamination, source URLs and services claimed. Raw contamination falls "
        f"from {raw.iloc[0]*100:.0f}% to {raw.iloc[-1]*100:.0f}% but the adjusted odds ratio per decade older is {c.effect:.2f} "
        f"({c.lo:.2f} to {c.hi:.2f})."))


if __name__ == "__main__":
    main()

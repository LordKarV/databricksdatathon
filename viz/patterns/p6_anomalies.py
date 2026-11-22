"""Pattern 6: isolation-forest anomalies over record features, with the top 20 classified by hand.

Features (log1p where counts): sentences, URLs, services claimed, specialties, stated beds, stated doctors,
doctors per bed, year established, raw pin-to-PIN km, social profiles, followers, strong grades, web-confirmed
services. Missing values become -1 plus a missing flag, so "nothing stated" is itself a pattern the forest sees.
Trust outcomes (contamination, drift) are not inputs except that pin-to-PIN km is the raw distance itself.
The forest is fitted on discovery only (seed fixed) and scores everyone; the top 20 discovery records are written
to data/p6_top20.csv for hand classification (data/p6_top20_classified.csv, written by hand after reading them).
Tests: top 5% anomaly score vs the rest on contamination, discovery and holdout.
Outputs: data/p6_scores.csv, data/p6_top20.csv, data/tests_p6.csv, charts/p6_anomalies.*
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from common import CHARTS, DATA, SEED, S, facility, newcombe, register, two_prop_p, wilson

COLS = ["n_sentences", "n_urls", "n_services", "n_specialties", "beds", "doctors", "year_est", "coord_pin_km",
        "social_count", "followers", "n_strong", "n_web_services"]


def features(f: pd.DataFrame) -> pd.DataFrame:
    x = pd.DataFrame(index=f.index)
    for c in COLS:
        v = f[c].astype(float)
        x[c] = (v if c == "year_est" else np.log1p(v.clip(lower=0))).fillna(-1)
        if v.isna().any():
            x[c + "_missing"] = v.isna().astype(int)
    x["doctors_per_bed"] = np.log1p((f.doctors / f.beds.where(f.beds > 0)).fillna(-0.5) + 0.5)
    return x


def main() -> None:
    f = facility()
    x = features(f)
    disc = f.split.eq("discovery").to_numpy()
    iso = IsolationForest(n_estimators=500, random_state=SEED, contamination="auto").fit(x[disc])
    f["anomaly"] = -iso.score_samples(x)
    thr = np.quantile(f.anomaly[disc], 0.95)
    f["top5"] = (f.anomaly >= thr).astype(int)
    f[["unique_id", "split", "anomaly", "top5"]].to_csv(DATA / "p6_scores.csv", index=False)
    show = ["unique_id", "name", "city", "state", "ftype", "operator", "beds", "doctors", "year_est", "n_sentences",
            "n_urls", "n_services", "n_specialties", "coord_pin_km", "social_count", "followers", "n_other_facility", "anomaly"]
    top = f[disc].sort_values("anomaly", ascending=False).head(20)[show]
    top.to_csv(DATA / "p6_top20.csv", index=False)
    tests, rates = [], []
    for outcome in ["contaminated", "drift50"]:
        res = {}
        for sp in ["discovery", "holdout"]:
            g = f[(f.split == sp) & f[outcome].notna()]
            k1, n1 = int(g[g.top5 == 1][outcome].sum()), int((g.top5 == 1).sum())
            k0, n0 = int(g[g.top5 == 0][outcome].sum()), int((g.top5 == 0).sum())
            res[sp] = (newcombe(k1, n1, k0, n0), two_prop_p(k1, n1, k0, n0), n1 + n0)
            for lv, k, n in [(1, k1, n1), (0, k0, n0)]:
                r, lo, hi = wilson(k, n)
                rates.append(dict(outcome=outcome, split=sp, top5=lv, k=k, n=n, rate=r, lo=lo, hi=hi))
        (d, lo, hi), p, n = res["discovery"]
        (hd, hlo, hhi), hp, hn = res["holdout"]
        tests.append(dict(test_id=f"p6_top5_{outcome}", family="anomalies", description=f"top 5% anomaly score vs rest: {outcome}",
                          effect_type="rate difference", effect=d, lo=lo, hi=hi, p=p, n=n, ho_effect=hd, ho_lo=hlo, ho_hi=hhi, ho_p=hp, ho_n=hn))
    register(tests, "p6")
    pd.DataFrame(rates).to_csv(DATA / "p6_rates.csv", index=False)
    pd.set_option("display.width", 250, "display.max_colwidth", 40)
    print(top.drop(columns="unique_id").round(2).to_string())
    print(pd.DataFrame(rates).round(3).to_string())




def chart() -> None:
    """Top 20 anomalies with the hand verdicts (run after data/p6_top20_classified.csv exists)."""
    t = pd.read_csv(DATA / "p6_top20.csv")
    c = pd.read_csv(DATA / "p6_top20_classified.csv")
    assert (t.name.str[:10].to_numpy() == c.name.str[:10].to_numpy()).all(), "hand verdicts no longer match the top 20"
    t = pd.concat([t.drop(columns="name").reset_index(drop=True), c[["name", "verdict", "reason"]]], axis=1).iloc[::-1].reset_index(drop=True)
    r = pd.read_csv(DATA / "p6_rates.csv")
    fig, ax = S.new_figure(size=(12, 8))
    col = np.where(t.verdict == "data error", S.SEMANTIC["flagged"], S.CATEGORICAL[0])
    ax.barh(np.arange(len(t)), t.anomaly, color=col, **S.bar_style())
    for i, row in t.iterrows():
        ax.text(0.005, i, f"{row['name']}: {row.reason}", va="center", fontsize=8.2, color=S.INK)
    ax.set_yticks([])
    ax.set_xlim(0, 0.9)
    ax.set_xlabel("Isolation-forest anomaly score (higher = more isolated)")
    n_err = int((t.verdict == "data error").sum())
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=S.SEMANTIC["flagged"], label=f"Data error ({n_err})"),
                       Patch(color=S.CATEGORICAL[0], label=f"Genuinely unusual facility ({len(t) - n_err})")],
              frameon=False, loc="lower right", fontsize=9)
    d = r[(r.outcome == "contaminated") & (r.split == "discovery")].set_index("top5")
    S.finding_title(ax, f"{n_err} of the 20 most anomalous records are data errors, mostly doctors exceeding beds or a pin "
                        f"in another town; the rest are large hospitals with unusually complete records",
                    subtitle=f"Top 20 of {int(d.n.sum()):,} discovery records, classified by hand. Top 5% by score: another facility's text "
                             f"{d.rate[1]*100:.0f}% vs {d.rate[0]*100:.0f}% for the rest")
    S.source_note(fig, "Source: viz/patterns/p6_anomalies.py; data/p6_top20_classified.csv (hand verdicts from the record text)")
    S.save(fig, str(CHARTS / "p6_anomalies"), alt_text=(
        f"Bar chart of the 20 highest isolation-forest scores. {n_err} are data errors (for example 2860 doctors for 200 beds, "
        f"a pin 242 km from its PIN) and {len(t) - n_err} are genuinely large hospitals with complete records."))


if __name__ == "__main__":
    main()
    chart()

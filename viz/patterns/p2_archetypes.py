"""Pattern 2: facility archetypes from k-means on standardised claim, size, type, operator, web and evidence features.

Trust outcomes (contamination, location drift) are NOT clustering inputs; they describe the clusters afterwards.
k is chosen on the discovery split from k = 3..10 by mean silhouette (3,000-row sample) and bootstrap stability
(adjusted Rand index of 20 bootstrap refits against the full fit). The holdout is assigned to the discovery
centroids (discovery scaler) and also clustered on its own; ARI between the two measures replication, and the
archetype trust rates are recomputed on the holdout.
Outputs: data/p2_k_selection.csv, data/p2_profiles.csv, data/p2_assignments.csv, data/tests_p2.csv, charts/p2_*.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler
from scipy import stats

from common import CHARTS, DATA, SEED, S, facility, register, services, wilson, newcombe, two_prop_p
from p1_cooccurrence import CATEGORY

K_RANGE = range(3, 11)


def features(f: pd.DataFrame) -> pd.DataFrame:
    sm = services()[list(CATEGORY)]
    cat = pd.DataFrame({c: sm[[s for s, k in CATEGORY.items() if k == c]].max(axis=1)
                        for c in sorted(set(CATEGORY.values()))}).add_prefix("cat_").reindex(f.index)
    x = pd.DataFrame(index=f.index)
    x["log_services"] = np.log1p(f.n_services)
    x["log_beds"] = np.log10(f.beds.where(f.beds > 0)).fillna(np.log10(f.beds.where(f.beds > 0)).median())
    x["beds_missing"] = f.beds.isna().astype(int)
    x["log_doctors"] = np.log10(f.doctors.where(f.doctors > 0)).fillna(0)
    x["log_specialties"] = np.log1p(f.n_specialties.fillna(0))
    for t in ["hospital", "clinic", "dentist"]:
        x[f"type_{t}"] = (f.ftype == t).astype(int)
    x["public"] = (f.operator == "public").astype(int)
    x["log_urls"] = np.log(f.n_urls)
    x["share_official"] = f.share_official.fillna(0)
    x["share_aggregator"] = f.share_aggregator.fillna(0)
    x["site_alive"] = f.site_alive.fillna(0)
    x["log_social"] = np.log1p(f.social_count.fillna(0))
    x["log_strong"] = np.log1p(f.n_strong)
    x["log_web_services"] = np.log1p(f.n_web_services)
    x["nabh_listed"] = f.nabh_listed
    x["osm_match"] = f.osm_match
    x["pmjay"] = f.pmjay
    return x.join(cat)


def select_k(X: np.ndarray) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    samp = rng.choice(len(X), 3000, replace=False)
    rows = []
    for k in K_RANGE:
        ref = KMeans(k, n_init=10, random_state=SEED).fit(X)
        sil = silhouette_score(X[samp], ref.labels_[samp])
        aris = []
        for b in range(20):
            i = rng.integers(0, len(X), len(X))
            m = KMeans(k, n_init=4, random_state=SEED + b).fit(X[i])
            aris.append(adjusted_rand_score(ref.labels_, m.predict(X)))
        rows.append(dict(k=k, silhouette=sil, stability_ari=np.mean(aris), stability_lo=np.percentile(aris, 2.5),
                         inertia=ref.inertia_))
    return pd.DataFrame(rows)


def main(k_fixed: int | None = None) -> None:
    f = facility().set_index("unique_id")
    x = features(f)
    disc, hold = f.split.eq("discovery"), f.split.eq("holdout")
    sc = StandardScaler().fit(x[disc])
    Xd, Xh = sc.transform(x[disc]), sc.transform(x[hold])
    ks = select_k(Xd)
    ks.to_csv(DATA / "p2_k_selection.csv", index=False)
    print(ks.round(3).to_string())
    # ponytail: k = 4 and 6 tie on silhouette (0.143 vs 0.142); k = 6 is kept because it is the only k that
    # separates public hospitals. k = 3 is the most stable (bootstrap ARI 0.97). Both are reported.
    k = k_fixed or 6
    km = KMeans(k, n_init=20, random_state=SEED).fit(Xd)
    lab = pd.Series(-1, index=f.index)
    lab[disc] = km.labels_
    lab[hold] = km.predict(Xh)
    own = KMeans(k, n_init=20, random_state=SEED).fit(Xh).labels_
    ari_hold = adjusted_rand_score(lab[hold], own)
    f["cluster"] = lab
    prof = x.join(f[["cluster", "split", "contaminated", "drift50", "disputed", "n_services", "beds", "doctors"]])
    means = prof[prof.split == "discovery"].groupby("cluster").mean(numeric_only=True)
    means["n_disc"] = prof[prof.split == "discovery"].groupby("cluster").size()
    means["n_hold"] = prof[prof.split == "holdout"].groupby("cluster").size()
    means["median_beds"] = prof[prof.split == "discovery"].groupby("cluster").beds.median()
    means.round(3).to_csv(DATA / "p2_profiles.csv")
    f[["cluster", "split"]].to_csv(DATA / "p2_assignments.csv")
    names = name_clusters(means)
    f["archetype"] = f.cluster.map(names)
    f[["cluster", "archetype", "split"]].to_csv(DATA / "p2_assignments.csv")
    tests, rates = [], []
    for a in names.values():
        for outcome in ["contaminated", "drift50"]:
            res = {}
            for sp in ["discovery", "holdout"]:
                g = f[(f.split == sp) & f[outcome].notna()]
                i, o = g[g.archetype == a][outcome], g[g.archetype != a][outcome]
                k1, n1, k2, n2 = int(i.sum()), len(i), int(o.sum()), len(o)
                res[sp] = (newcombe(k1, n1, k2, n2), two_prop_p(k1, n1, k2, n2), n1 + n2)
                r_, lo_, hi_ = wilson(k1, n1)
                rates.append(dict(archetype=a, outcome=outcome, split=sp, k=k1, n=n1, rate=r_, lo=lo_, hi=hi_))
            (d, dlo, dhi), p_, n_ = res["discovery"]
            (hd, hlo, hhi), hp, hn = res["holdout"]
            tests.append(dict(test_id=f"p2_{a.split()[0].lower()}_{outcome}", family="archetypes",
                              description=f"{a} vs all others: {outcome}", effect_type="rate difference",
                              effect=d, lo=dlo, hi=dhi, p=p_, n=n_, ho_effect=hd, ho_lo=hlo, ho_hi=hhi, ho_p=hp, ho_n=hn))
    register(tests, "p2")
    rates = pd.DataFrame(rates)
    rates.to_csv(DATA / "p2_rates.csv", index=False)
    pd.Series(dict(k=k, holdout_ari=ari_hold, names=names)).to_json(DATA / "p2_summary.json", indent=1)
    chart(means, names, rates, ks, k, ari_hold)
    print(f"k = {k}, holdout ARI {ari_hold:.3f}", names)
    print(rates.round(3).to_string())


def name_clusters(m: pd.DataFrame) -> dict[int, str]:
    """Name clusters from their discovery means (rules, so the names survive a re-run with new labels)."""
    names = {}
    hosp = []
    for c, r in m.iterrows():
        if r.public > 0.5:
            names[c] = "Public hospitals"
        elif r.type_dentist > 0.5:
            names[c] = "Dental clinics"
        elif r.type_clinic > 0.5:
            names[c] = "Clinics with thin records"
        else:
            hosp.append(c)
    hosp = sorted(hosp, key=lambda c: m.loc[c, "n_services"], reverse=True)
    labels = ["Flagship tertiary hospitals", "Mid-size multispecialty hospitals", "Small hospitals with thin records"]
    for c, lab in zip(hosp, labels + [f"Hospital group {i}" for i in range(len(hosp))]):
        names[c] = lab
    return names


SHOW = [("n_services", "Services claimed (mean)", "{:.1f}"), ("median_beds", "Median beds stated", "{:.0f}"),
        ("beds_missing", "Beds not stated", "{:.0%}"), ("public", "Public operator", "{:.0%}"),
        ("site_alive", "Website answers", "{:.0%}"), ("nabh_listed", "On NABH list", "{:.0%}"),
        ("pmjay", "Says PM-JAY", "{:.0%}"), ("cat_critical", "Claims ICU-type care", "{:.0%}")]


def chart(means: pd.DataFrame, names: dict, rates: pd.DataFrame, ks: pd.DataFrame, k: int, ari: float) -> None:
    order = means.sort_values("n_services", ascending=False).index.tolist()
    fig = plt.figure(figsize=(13, 8), facecolor=S.SURFACE, constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1])
    ax = fig.add_subplot(gs[0]); ax2 = fig.add_subplot(gs[1])
    z = np.array([[(means.loc[c, col] - means[col].min()) / (means[col].max() - means[col].min() + 1e-9) for col, _, _ in SHOW] for c in order])
    ax.imshow(z, cmap=plt.matplotlib.colors.LinearSegmentedColormap.from_list("s", S.SEQUENTIAL[:9]), aspect="auto", vmin=0, vmax=1.3)
    for i, c in enumerate(order):
        for j, (col, _, fmt) in enumerate(SHOW):
            ax.text(j, i, fmt.format(means.loc[c, col]), ha="center", va="center", fontsize=9,
                    color="#ffffff" if z[i, j] > 0.75 else S.INK)
    ax.set_xticks(range(len(SHOW)), [s[1] for s in SHOW], rotation=35, ha="right", fontsize=9)
    ax.set_yticks(range(len(order)), [f"{names[c]}\n(n = {int(means.loc[c, 'n_disc']):,})" for c in order], fontsize=9)
    ax.tick_params(length=0)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    S.panel_title(ax, "Profile (discovery); shade = rank among archetypes")
    y = np.arange(len(order))
    for off, (sp, col) in zip([-0.18, 0.18], [("discovery", S.CATEGORICAL[0]), ("holdout", S.CATEGORICAL[2])]):
        r = rates[(rates.outcome == "contaminated") & (rates.split == sp)].set_index("archetype").reindex([names[c] for c in order])
        ax2.barh(y + off, r.rate * 100, height=0.34, color=col, label=f"{sp} (n = {int(r.n.sum()):,})", **S.bar_style())
        S.add_interval(ax2, y + off, r.lo * 100, r.hi * 100, horizontal=True)
    ax2.set_yticks(y, [""] * len(y)); ax2.invert_yaxis(); ax.set_ylim(len(order) - 0.5, -0.5)
    ax2.set_ylim(len(order) - 0.5, -0.5)
    ax2.set_xlabel("Has another facility's text (%, 95% Wilson CI)")
    ax2.legend(frameon=False, fontsize=9, loc="lower right")
    S.panel_title(ax2, "Contamination by archetype")
    pub = rates[(rates.archetype == "Public hospitals") & (rates.outcome == "contaminated")].set_index("split")
    den = rates[(rates.archetype == "Dental clinics") & (rates.outcome == "contaminated")].set_index("split")
    sel = ks.set_index("k").loc[k]
    S.fig_title(fig, f"Six facility archetypes: public hospitals carry another facility's text in {pub.rate['discovery']*100:.0f}% of records, "
                     f"dental clinics in {den.rate['discovery']*100:.0f}%")
    S.source_note(fig, f"k-means on 30 standardised features, k = {k} (silhouette {sel.silhouette:.2f}, bootstrap ARI {sel.stability_ari:.2f}; "
                       f"holdout re-clustering ARI {ari:.2f}).\nWeak structure: silhouette is below 0.15 for every k from 3 to 10. Source: viz/patterns/p2_archetypes.py")
    S.save(fig, str(CHARTS / "p2_archetypes"), alt_text=(
        f"Heatmap of six facility archetypes with a bar chart of contamination. Public hospitals: {pub.rate['discovery']*100:.0f}% "
        f"of discovery records ({pub.rate['holdout']*100:.0f}% holdout) contain another facility's text; dental clinics "
        f"{den.rate['discovery']*100:.0f}%. Silhouette {sel.silhouette:.2f} means the archetypes are a segmentation, not natural clusters."))


if __name__ == "__main__":
    main()

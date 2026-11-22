"""Charts for the feature study, all through viz/style.py. Inputs: out/*.parquet|json from
build_features.py, univariate.py, glassbox.py and recommend.py. Outputs: charts/<name>.png|svg|txt.

Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python viz/features/charts.py
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/viz")
import style as S  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, ListedColormap  # noqa: E402

import catalogue_meta as M  # noqa: E402
import labels as L  # noqa: E402

HERE = Path(__file__).parent
OUT, CH = HERE / "out", HERE / "charts"
CH.mkdir(exist_ok=True)
SVC_LABEL = {"dialysis": "Dialysis", "emergency_csection": "Emergency C-section", "nicu": "NICU",
             "cardiac_surgery": "Cardiac surgery", "mri": "MRI", "burn_care": "Burn care",
             "trauma_emergency": "Trauma"}
SVC_ORDER = ["trauma_emergency", "emergency_csection", "dialysis", "mri", "cardiac_surgery", "nicu", "burn_care"]
FAM_ORDER = list(M.FAMILIES)
SRC_FEAT = "Source: viz/features/out/features_pairs.parquet (69,713 facility x service pairs; inputs in features_catalogue.csv)"


def short(f: str, n: int = 46) -> str:
    """Card-style label for a feature: the phrase with placeholders filled generically."""
    p = M.META[f][3].replace("the {svc}", "the service").replace("{svc}", "the service")
    for k, v in {"{n}": "N", "{pct}": "X%", "{status}": "any programme", "{code}": "matching",
                 "{course}": "a matching course", "{date}": "date", "{level}": "higher public level",
                 "{grade}": "higher", "{conf}": "high, medium, low or disputed"}.items():
        p = p.replace(k, v)
    return textwrap.shorten(p[0].upper() + p[1:], n, placeholder="...")


def title(fig, ax, text, subtitle=None, wrap=None):
    """Figure-level headline (never clipped by the axes) plus an optional gray subtitle on the panel."""
    S.fig_title(fig, text, wrap=int(fig.get_figwidth() * 8.2))
    if subtitle:
        S.panel_title(ax, textwrap.fill(subtitle, int(fig.get_figwidth() * 6.5)))


def fam(f: str) -> str:
    return M.FAMILIES[f[0]]


def load():
    u = pd.read_parquet(OUT / "univariate.parquet")
    feat = pd.read_parquet(OUT / "features_pairs.parquet")
    meta = json.loads((OUT / "univariate_meta.json").read_text())
    return u, feat, meta


# ------------------------------------------------------------------ 1. coverage
def note(fig, text):
    S.source_note(fig, textwrap.fill(text, 200))


def service_sources(feat: pd.DataFrame) -> pd.DataFrame:
    """Per service: share of pairs where each kind of source says something about THIS service."""
    lists = ((feat.d_nabh_service_code == 1) | (feat.d_nmc_course_strong == 1) |
             (feat.d_laqshya_ot_ever == 1) | (feat.d_mohfw_trauma_centre == 1))
    web = feat.e_web_service == 1
    osm = (feat.f_osm_speciality_service == 1) | ((feat.service == "trauma_emergency") & (feat.f_osm_emergency_yes == 1))
    txt = feat.a_T >= 1
    ind = lists | web | osm
    d = pd.DataFrame(dict(service=feat.service, text=txt, own_text=feat.a_T >= 2, website=web, lists=lists, osm=osm,
                          both=txt & ind, text_only=txt & ~ind, indep_only=ind & ~txt, none=~(txt | ind),
                          indep_only_nabh=(feat.d_nabh_service_code == 1) & ~txt & ~web & ~osm
                          & ~(feat.d_nmc_course_strong == 1) & ~(feat.d_laqshya_ot_ever == 1) & ~(feat.d_mohfw_trauma_centre == 1)))
    g = d.groupby("service").agg(["sum", "count"])
    out = pd.DataFrame({c: g[(c, "sum")] for c in d.columns if c != "service"})
    out["n"] = g[("text", "count")]
    return out.loc[SVC_ORDER]


def chart_coverage(feat):
    a = service_sources(feat)
    a.to_csv(OUT / "service_source_coverage.csv")
    fig, axes = S.new_figure(size=(14, 7.4), ncols=2, gridspec_kw=dict(width_ratios=[1.25, 1]))
    ax = axes[0]
    y = np.arange(len(a))[::-1]
    left = np.zeros(len(a))
    parts = [("both", "Text and an independent source", S.CATEGORICAL[0]),
             ("text_only", "Dataset text only", S.CATEGORICAL[1]),
             ("indep_only", "Independent source only (website, list, OSM)", S.CATEGORICAL[2])]
    for col, lab, c in parts:
        v = (a[col] / a.n * 100).values
        ax.barh(y, v, left=left, color=c, height=0.62, label=lab, **S.bar_style())
        for yi, l, w in zip(y, left, v):
            if w >= 3:
                ax.text(l + w / 2, yi, f"{w:.1f}", ha="center", va="center", fontsize=10, color="#ffffff")
        left = left + v
    for yi, l, r in zip(y, left, a.itertuples()):
        ax.text(l + 0.8, yi, f"no source: {100 * r.none / r.n:.0f}%", va="center", fontsize=10.5, color=S.INK_2)
    ax.set_yticks(y, [SVC_LABEL[s] for s in a.index])
    ax.set_xlim(0, 60)
    ax.set_xlabel("% of the service's 9,959 pairs where some source speaks about this service")
    ax.legend(loc="lower right", fontsize=10.5)
    ax.grid(axis="y", visible=False)
    S.panel_title(ax, "Who speaks for the pair (Wilson 95% half-widths below 1 point)")
    ax = axes[1]
    cols = [("text", "Dataset text\n(any mention)"), ("own_text", "Dataset text\n(own offer unit)"),
            ("website", "Own website"), ("lists", "Official list"), ("osm", "OpenStreetMap")]
    m = np.column_stack([a[c] / a.n * 100 for c, _ in cols])
    cmap = LinearSegmentedColormap.from_list("seq", ["#f4f3ef"] + S.SEQUENTIAL[2:])
    im = ax.imshow(m, cmap=cmap, vmin=0, vmax=40, aspect="auto")
    ax.set_xticks(range(len(cols)), [l for _, l in cols], fontsize=10, rotation=30, ha="right")
    ax.set_yticks(range(len(a)), [SVC_LABEL[s] for s in a.index])
    ax.grid(False)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m[i, j]
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=10.5, color="#ffffff" if v > 22 else S.INK)
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.colorbar(im, ax=ax, label="% of pairs", shrink=0.8)
    S.panel_title(ax, "Each source separately (% of 9,959 pairs)")
    tot_none = a.none.sum() / a.n.sum() * 100
    cs = a.loc["emergency_csection"]
    S.fig_title(fig, f"For {tot_none:.0f}% of facility-service pairs no source says anything about the service; "
                     f"for emergency C-section, independent sources speak for {int(cs.indep_only):,} facilities the text never mentions "
                     f"against {int(cs.text_only):,} the other way round, but {int(cs.indep_only_nabh):,} of them only via a NABH "
                     "obstetrics (OBG) code, which names a department, not emergency C-section")
    note(fig, "Independent = the facility's own website (attributable pages), an official list (NABH code, NMC course, LaQshya, "
              "MoHFW trauma) or an OSM speciality/emergency tag. Source: viz/features/out/service_source_coverage.csv")
    alt = (f"For {tot_none:.1f}% of 69,713 pairs no source mentions the service. By service, share with text only / both / "
           "independent only / none: " + "; ".join(
               f"{SVC_LABEL[s]} {100 * r.text_only / r.n:.1f} / {100 * r.both / r.n:.1f} / {100 * r.indep_only / r.n:.1f} / {100 * r.none / r.n:.1f}%"
               for s, r in a.iterrows()))
    S.save(fig, CH / "01_who_speaks_for_each_service", alt)


def chart_coverage_features(u):
    d = u.copy()
    d["fam"] = d.feature.map(fam)
    d["fk"] = d.feature.str[0].map({k: i for i, k in enumerate(FAM_ORDER)})
    d = d.sort_values(["fk", "nonzero_share"], ascending=[False, True]).reset_index(drop=True)
    fig, ax = S.new_figure(size=(12, 26))
    y = np.arange(len(d))
    nz = np.clip(d.nonzero_share * 100, 0.005, 100)
    cv = np.clip(d.coverage * 100, 0.005, 100)
    ax.hlines(y, nz, cv, color=S.GRID, lw=2, zorder=1)
    ax.scatter(cv, y, s=46, facecolor=S.SURFACE, edgecolor=S.CATEGORICAL[0], lw=1.6, zorder=3, label="Has a value (not missing)")
    ax.scatter(nz, y, s=46, color=S.CATEGORICAL[0], edgecolor=S.SURFACE, lw=1.2, zorder=4, label="Value is non-zero")
    ax.set_xscale("log")
    ax.set_xlim(0.004, 250)
    ax.set_xticks([0.01, 0.1, 1, 10, 100], ["0.01", "0.1", "1", "10", "100"])
    ax.set_yticks(y, [f"{f}  " for f in d.feature], fontsize=9.5, family="monospace")
    ax.set_ylim(-0.8, len(d) - 0.2)
    for f, g in d.groupby("fam", sort=False):
        top = g.index.max()
        ax.axhline(top + 0.5, color=S.AXIS, lw=0.8)
        ax.text(0.0045, top + 0.15, f.upper(), fontsize=10, color=S.INK_2, va="top", fontweight="bold")
    for i, r in d.iterrows():
        ax.text(min(cv[i], 100) * 1.25, i, f"{r.n_nonzero:,}", va="center", fontsize=8.5, color=S.INK_2)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Share of the 69,713 pairs (%, log scale); number = pairs with a non-zero value")
    ax.legend(loc="lower left", frameon=False, bbox_to_anchor=(0.02, 0.0))
    n01 = int((d.nonzero_share < 0.001).sum())
    title(fig, ax, f"{n01} of {len(d)} candidate features fire on fewer than 1 in 1,000 pairs; "
                        "list and website facts are rare, record forensics are common", wrap=80)
    note(fig, SRC_FEAT)
    alt = (f"Coverage of all {len(d)} candidate features. {n01} are non-zero on fewer than 0.1% of pairs. "
           + "; ".join(f"{r.feature} {100 * r.nonzero_share:.2f}% non-zero" for r in d.sort_values('nonzero_share').head(12).itertuples()))
    S.save(fig, CH / "02_coverage_by_feature", alt)


# ------------------------------------------------------------------ 2. univariate
def forest(ax, d, col, lo, hi, label_col="label", n_text=None):
    y = np.arange(len(d))[::-1]
    sig = (d[lo] > 0.5) | (d[hi] < 0.5)
    ax.axvline(0.5, color=S.INK_2, lw=1)
    for yi, (_, r), s in zip(y, d.iterrows(), sig):
        c = S.CATEGORICAL[0] if s else S.MUTED
        ax.plot([r[lo], r[hi]], [yi, yi], color=c, lw=2, solid_capstyle="round")
        ax.scatter([r[col]], [yi], s=60, color=c, edgecolor=S.SURFACE, lw=1.5, zorder=3)
        if n_text is not None:
            ax.text(1.005, yi, n_text(r), transform=ax.get_yaxis_transform(), va="center", fontsize=9.5, color=S.INK_2)
    ax.set_yticks(y, d[label_col], fontsize=10.5)
    ax.set_ylim(-1.4, len(d) - 0.4)  # empty bottom row keeps the small-n note off the data
    ax.set_xlim(0, 1)
    ax.grid(axis="y", visible=False)
    return sig


def chart_dev(u, meta):
    d = u[(u.dev_minority >= 5) & u.dev_auc.notna()].copy()
    d["eff"] = (d.dev_auc - 0.5).abs()
    d = d.sort_values("eff", ascending=False).head(26).sort_values("dev_auc", ascending=False)
    d["label"] = [f"{short(f, 44)}  [{fam(f)}]" for f in d.feature]
    fig, ax = S.new_figure(size=(13, 10.5))
    sig = forest(ax, d, "dev_auc", "dev_auc_lo", "dev_auc_hi",
                 n_text=lambda r: f"n={r.dev_n}, {r.dev_minority} minority" + ("  (fitted on gold)" if r.leak_gold_web_check == "fitted" else ""))
    ax.set_xlabel("AUROC on gold DEV: chance a confirmed pair has the higher value (0.5 = no signal), 95% cluster bootstrap")
    top = d.iloc[0]
    title(fig, ax, f"On {meta['dev_searched']} searched DEV pairs the strongest signals are how often the listing names the "
                        f"service, a NABH claim and specialty breadth; only {int(sig.sum())} of {len(d)} intervals clear 0.5",
                    subtitle=f"Gold DEV split only: {meta['dev_searched']} searched pairs, {meta['dev_confirmed']} confirmed. "
                             f"Features with at least 5 labelled pairs in the minority value. Blue: interval excludes 0.5.",
                    wrap=85)
    S.small_n_note(ax, meta["dev_searched"], threshold=100,
                   text=f"Small sample: {meta['dev_searched']} labelled pairs; read the interval, not the point")
    note(fig, "Labels: model/gold/splits.json (split = dev), labels_p*.json, audit/ground_truth/web_*.json. "
                       "Never-searched pairs dropped. Script: viz/features/univariate.py")
    alt = (f"Univariate AUROC of {len(d)} features on {meta['dev_searched']} gold DEV pairs ({meta['dev_confirmed']} confirmed). "
           + "; ".join(f"{r.feature} {r.dev_auc:.2f} [{r.dev_auc_lo:.2f}, {r.dev_auc_hi:.2f}]" for r in d.itertuples()))
    S.save(fig, CH / "03_univariate_dev", alt)


def chart_pu(u, meta):
    d = u[u.nabh_auc.notna() & (u.nabh_n >= 200)].copy()
    d["eff"] = (d.nabh_auc - 0.5).abs()
    d = d.sort_values("eff", ascending=False).head(26).sort_values("nabh_auc", ascending=False)
    d["label"] = [f"{short(f, 44)}  [{fam(f)}]" for f in d.feature]
    fig, ax = S.new_figure(size=(13, 10.5))
    forest(ax, d, "nabh_auc", "nabh_auc_lo", "nabh_auc_hi",
           n_text=lambda r: f"held-out states {r.nabh_fold_min:.2f} to {r.nabh_fold_max:.2f}")
    ax.set_xlabel("AUROC within service: NABH lists the code vs NABH-known facility without it (95% bootstrap over states)")
    pos = meta["pu_nabh_pos"]
    title(fig, ax, "Among NABH-listed facilities, size and a written list of prerequisites predict which "
                        "specialties they declare to NABH; the service sentence itself adds less",
                    subtitle=f"{meta['pu_nabh_pairs']:,} pairs ({pos:,} with the code) from 1,054 facilities in "
                             f"{meta['n_states_nabh']} states; 4 services with a NABH code. NABH-derived features excluded.",
                    wrap=85)
    note(fig, "Labels: data/external/nabh_accredited (self-declared specialty codes, positive-unlabeled). "
                       "Right column: AUROC range across 5 folds of held-out states. Script: viz/features/univariate.py")
    alt = (f"Univariate AUROC against NABH specialty codes on {meta['pu_nabh_pairs']} pairs. "
           + "; ".join(f"{r.feature} {r.nabh_auc:.2f} [{r.nabh_auc_lo:.2f}, {r.nabh_auc_hi:.2f}]" for r in d.itertuples()))
    S.save(fig, CH / "04_univariate_nabh_pu", alt)


def chart_dev_vs_pu(u, meta):
    d = u[u.dev_auc.notna() & u.nabh_auc.notna() & (u.dev_minority >= 5)].copy()
    fig, ax = S.new_figure(size=(11, 8.5))
    ax.axhline(0.5, color=S.AXIS, lw=1)
    ax.axvline(0.5, color=S.AXIS, lw=1)
    ax.plot([0.2, 0.9], [0.2, 0.9], color=S.GRID, lw=1)
    agree = np.sign(d.dev_auc - 0.5) == np.sign(d.nabh_auc - 0.5)
    for ok, c in [(True, S.CATEGORICAL[0]), (False, S.CATEGORICAL[1])]:
        m = agree == ok
        ax.errorbar(d.nabh_auc[m], d.dev_auc[m], yerr=[d.dev_auc[m] - d.dev_auc_lo[m], d.dev_auc_hi[m] - d.dev_auc[m]],
                    fmt="o", color=c, ecolor=S.GRID, elinewidth=1, ms=7, mec=S.SURFACE, mew=1.5,
                    label=("same direction" if ok else "opposite direction") + f" ({int(m.sum())})")
    lab = d.assign(e=(d.dev_auc - 0.5).abs() + (d.nabh_auc - 0.5).abs()).sort_values("e", ascending=False).head(9)
    # labels in a column on the right, leader lines to their dots (no overlaps by construction)
    lab = lab.sort_values("dev_auc", ascending=False)
    for i, r in enumerate(lab.itertuples()):
        ty = 0.88 - i * 0.045
        ax.annotate(short(r.feature, 36), (r.nabh_auc, r.dev_auc), xytext=(0.715, ty), textcoords="data",
                    fontsize=9.5, color=S.INK_2, va="center",
                    arrowprops=dict(arrowstyle="-", color=S.AXIS, lw=0.6, shrinkA=0, shrinkB=4))
    ax.set_xlim(0.25, 0.95)
    ax.set_ylim(0.15, 0.95)
    ax.set_xlabel("AUROC against NABH specialty codes (PU, 4,216 pairs)")
    ax.set_ylabel("AUROC against gold web check (DEV, 61 pairs)")
    ax.legend(loc="lower right")
    rho = np.corrcoef(d.nabh_auc, d.dev_auc)[0, 1]
    title(fig, ax, f"The two label sources agree on direction for {int(agree.sum())} of {len(d)} features "
                        f"(Pearson r = {rho:.2f} between their AUROCs)",
                    subtitle="Each dot is a feature with at least 5 DEV pairs in its minority value; vertical whiskers: 95% DEV interval",
                    wrap=80)
    note(fig, "Source: viz/features/out/univariate.parquet. Gold DEV only; NABH labels are self-declared and positive-unlabeled.")
    alt = (f"Feature AUROC on gold DEV versus NABH codes for {len(d)} features: same direction for {int(agree.sum())}, "
           f"correlation {rho:.2f}. Labelled: " + "; ".join(f"{r.feature} dev {r.dev_auc:.2f}, NABH {r.nabh_auc:.2f}" for r in lab.itertuples()))
    S.save(fig, CH / "05_dev_vs_nabh_agreement", alt)


def chart_location(u, meta):
    d = u[u.loc_auc.notna() & u.feature.str[0].isin(list("bcdef")) & (u.loc_no >= 5)].copy()
    d["eff"] = (d.loc_auc - 0.5).abs()
    d = d.sort_values("eff", ascending=False).head(14).sort_values("loc_auc", ascending=False)
    d["label"] = [f"{short(f, 44)}  [{fam(f)}]" for f in d.feature]
    fig, ax = S.new_figure(size=(12.5, 7.5))
    forest(ax, d, "loc_auc", "loc_auc_lo", "loc_auc_hi",
           n_text=lambda r: (f"vs service {r.dev_auc:.2f}" if pd.notna(r.dev_auc) else "")
           + ("  FITTED ON GOLD" if r.leak_gold_web_check == "fitted" else ""))
    ax.set_xlabel("AUROC for 'location checks out' on gold DEV facilities (95% cluster bootstrap)")
    n, no = meta["dev_location_facilities"], meta["dev_location_no"]
    nu = u.set_index("feature").loc["c_n_urls"]
    title(fig, ax, f"Location and service need different features: a record built from many web pages is more often "
                   f"confirmed for the service (AUROC {nu.dev_auc:.2f}) and more often in the wrong place ({nu.loc_auc:.2f})",
                    subtitle=f"Gold DEV facilities with a yes/no location verdict: {n} ({no} wrong); features with at least 5 wrong locations among their labelled rows. Right column: same feature's AUROC for the service label. Values near 0 mean the feature flags wrong locations.",
                    wrap=85)
    S.small_n_note(ax, no, threshold=30, text=f"Small sample: only {no} wrong locations; intervals are wide")
    note(fig, "Labels: location_ok in model/gold/labels_p*.json and location_matches in audit/ground_truth (DEV split only).")
    alt = ("AUROC of forensics, source, list, website and open-data features for the gold DEV location label "
           f"({n} facilities, {no} wrong): " + "; ".join(f"{r.feature} {r.loc_auc:.2f} [{r.loc_auc_lo:.2f}, {r.loc_auc_hi:.2f}]" for r in d.itertuples()))
    S.save(fig, CH / "06_location_label", alt)


# ------------------------------------------------------------------ 3. redundancy
def chart_clusters(u):
    rho = pd.read_parquet(OUT / "spearman.parquet")
    cl = u.set_index("feature").cluster
    multi = cl[cl.map(cl.value_counts()) >= 2].index
    order = [f for f in rho.index if f in set(multi)]
    r = rho.loc[order, order].abs()
    fig, ax = S.new_figure(size=(13, 12))
    cmap = LinearSegmentedColormap.from_list("seq", ["#f4f3ef"] + S.SEQUENTIAL[2:])
    im = ax.imshow(r.values, cmap=cmap, vmin=0, vmax=1)
    ax.set_xticks(range(len(order)), order, rotation=90, fontsize=8.5, family="monospace")
    ax.set_yticks(range(len(order)), order, fontsize=8.5, family="monospace")
    ax.grid(False)
    # outline each redundancy cluster
    import matplotlib.patches as mp
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and cl[order[j + 1]] == cl[order[i]]:
            j += 1
        ax.add_patch(mp.Rectangle((i - 0.5, i - 0.5), j - i + 1, j - i + 1, fill=False, ec=S.INK, lw=1.4))
        i = j + 1
    fig.colorbar(im, ax=ax, label="|Spearman rho| over 69,713 pairs", shrink=0.7)
    n_cl = cl[multi].nunique()
    title(fig, ax, f"{len(order)} of {len(cl)} features fall into {n_cl} redundancy clusters (|rho| >= 0.7); "
                        "keep one per cluster", wrap=80)
    note(fig, "Average-linkage clustering on 1 - |rho|, cut at 0.3. Boxes: clusters. Singletons omitted. Script: viz/features/univariate.py")
    groups = {}
    for f in order:
        groups.setdefault(int(cl[f]), []).append(f)
    alt = f"{n_cl} redundancy clusters: " + "; ".join(", ".join(v) for v in groups.values())
    S.save(fig, CH / "07_correlation_clusters", alt)


# ------------------------------------------------------------------ 4. leakage
LEAK_LEVELS = ["none", "design", "selection", "shared", "fitted", "direct"]
LEAK_TEXT = {"none": "", "design": "design", "selection": "select", "shared": "shared", "fitted": "fitted", "direct": "DIRECT"}


def chart_leakage(u, meta):
    d = u.copy()
    d["fk"] = d.feature.str[0].map({k: i for i, k in enumerate(FAM_ORDER)})
    d = d.sort_values(["fk", "feature"]).reset_index(drop=True)
    cols = ["leak_gold_web_check", "leak_nabh_codes", "leak_official_lists"]
    m = d[cols].apply(lambda s: s.map({k: i for i, k in enumerate(LEAK_LEVELS)})).values
    fig, axes = S.new_figure(size=(13, 26), ncols=2, gridspec_kw=dict(width_ratios=[1.1, 1]))
    ax = axes[0]
    ramp = ["#f4f3ef"] + S.SEQUENTIAL_2[:5]
    ax.imshow(m, cmap=ListedColormap(ramp), vmin=-0.5, vmax=5.5, aspect="auto")
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            ax.text(j, i, LEAK_TEXT[LEAK_LEVELS[m[i, j]]], ha="center", va="center", fontsize=8,
                    color="#ffffff" if m[i, j] >= 4 else S.INK)
    ax.set_yticks(range(len(d)), d.feature, fontsize=8.5, family="monospace")
    ax.set_xticks(range(3), ["Gold web\ncheck", "NABH\ncodes (PU)", "All official\nlists (PU)"])
    ax.xaxis.tick_top()
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    prev = None
    for i, f in enumerate(d.feature):
        if prev is not None and f[0] != prev:
            ax.axhline(i - 0.5, color=S.INK_2, lw=0.8)
        prev = f[0]
    S.panel_title(ax, "Leakage of each feature against each label source")
    # right panel: legend + measured overlap
    ax = axes[1]
    ax.axis("off")
    y0 = 0.98
    ax.text(0, y0, "Levels (worst last)", fontsize=12, fontweight="bold", transform=ax.transAxes, va="top")
    desc = {"none": "independent of the label's source",
            "design": "gold sample was stratified on this feature's rule grade",
            "selection": "the list matcher's gates or the list's scope depend on it (PIN, coordinates, public operator)",
            "shared": "feature and label read the same pages or claim",
            "fitted": "weights or rules were fitted or tuned on gold labels (DEV, or the v1 verdicts read during design)",
            "direct": "the label is read off the same list: never use it for that label"}
    for i, k in enumerate(LEAK_LEVELS):
        yy = y0 - 0.03 - i * 0.03
        ax.add_patch(__import__("matplotlib").patches.Rectangle((0, yy - 0.012), 0.05, 0.022, transform=ax.transAxes,
                                                                color=ramp[i], ec=S.AXIS, lw=0.5))
        ax.text(0.07, yy, f"{k}: {desc[k]}", fontsize=10, transform=ax.transAxes, va="center", wrap=True)
    ov = meta["evidence_overlap"]
    n = ov["dev_pairs_with_evidence_urls"]
    rows = [("Evidence domain is one of the record's own cited sources", ov["pairs_hit"]["record_source_domain"]),
            ("Evidence domain is the facility's own website", ov["pairs_hit"]["own_website"]),
            ("Evidence is a NABH portal page", ov["pairs_hit"]["nabh_portal"]),
            ("Any of the three", ov["pairs_hit"]["any_of_these"])]
    inset = ax.inset_axes([0.12, 0.55, 0.85, 0.18])
    ps = [S.wilson(k, n) for _, k in rows]
    yy = np.arange(len(rows))[::-1]
    bars = inset.barh(yy, [p[0] * 100 for p in ps], color=S.SEQUENTIAL_2[3], height=0.6, **S.bar_style())
    S.add_interval(inset, yy, [p[1] * 100 for p in ps], [p[2] * 100 for p in ps], horizontal=True)
    for yi, p_, (_, k) in zip(yy, ps, rows):
        inset.text(p_[2] * 100 + 2, yi, f"{k} of {n} ({100 * k / n:.0f}%)", va="center", fontsize=9.5, color=S.INK)
    inset.set_yticks(yy, [textwrap.fill(t, 30) for t, _ in rows], fontsize=9.5)
    inset.set_xlim(0, 115)
    inset.set_xticks([0, 25, 50, 75, 100])
    inset.set_xlabel("% of gold DEV pairs with an evidence URL (95% Wilson)", fontsize=10)
    inset.grid(axis="y", visible=False)
    inset.set_title("Measured: where the gold labeller found the evidence", loc="left", fontsize=11.5, fontweight="bold")
    S.fig_title(fig, f"The gold web check is not independent of the features: in {ov['pairs_hit']['any_of_these']} of {n} "
                     "DEV pairs the labeller's evidence came from a web domain the record already cites or its own website", wrap=90)
    note(fig, "Leakage levels: viz/features/catalogue_meta.py leakage(). Overlap: viz/features/labels.py evidence_overlap() over DEV labels only.")
    alt = (f"Leakage matrix for {len(d)} features against gold, NABH and all-list labels. "
           f"Gold evidence overlap on {n} DEV pairs with URLs: record source domain {rows[0][1]}, own website {rows[1][1]}, "
           f"NABH portal {rows[2][1]}, any {rows[3][1]}. Direct leakage for NABH labels: "
           + ", ".join(d[d.leak_nabh_codes == "direct"].feature) + ".")
    S.save(fig, CH / "08_leakage_map", alt)


# ------------------------------------------------------------------ 5. glass box
def shape_panel(ax, f, sh, color):
    e, sc, sd = sh["edges"], np.array(sh["scores"]), np.array(sh["sd"])
    pts = 20 / np.log(2)
    if sh["categorical"] or len(sc) <= 3:
        if sh["categorical"]:
            labels = list(e)
        elif all(abs(v - round(v) - 0.5) < 1e-9 or abs(v - round(v) + 0.5) < 1e-9 for v in e):
            # integer-valued feature cut at x.5: bin i holds one integer value (0/1 flags read no/yes)
            lo = int(np.floor(e[0]))
            labels = ["no", "yes"] if len(sc) == 2 and lo == 0 else [str(lo + i) for i in range(len(sc))]
        else:
            labels = [f"< {e[0]:g}"] + [f"{a:g}-{b:g}" for a, b in zip(e[:-1], e[1:])] + [f">= {e[-1]:g}"]
        x = np.arange(len(sc))
        ax.bar(x, sc * pts, color=color, width=0.55, **S.bar_style())
        S.add_interval(ax, x, (sc - 1.96 * sd) * pts, (sc + 1.96 * sd) * pts)
        ax.set_xticks(x, [textwrap.shorten(str(v), 16) for v in labels], fontsize=9.5, rotation=20 if len(sc) > 3 else 0)
    else:
        xs = np.array([e[0] - (e[1] - e[0]) if len(e) > 1 else e[0] - 1] + list(e))
        mids = xs
        ax.step(mids, sc * pts, where="post", color=color, lw=2)
        ax.fill_between(mids, (sc - 1.96 * sd) * pts, (sc + 1.96 * sd) * pts, step="post", color=color, alpha=0.18, lw=0)
        ax.set_xlabel("log10 of the stated value (1 = 10, 2 = 100)" if "_log_" in f else f"value of {f}", fontsize=9.5)
    ax.axhline(0, color=S.INK_2, lw=0.9)
    ax.set_ylabel("Points (20 = odds x2)", fontsize=10)
    S.panel_title(ax, f"{f}\n{short(f, 40)}")


def chart_ebm(name, shapes, n_text, title, path, color):
    top = sorted(shapes.items(), key=lambda kv: -kv[1]["importance"])
    top = [kv for kv in top if kv[0] != "service"][:8]
    fig, axes = S.new_figure(size=(14, 8.6), nrows=2, ncols=4)
    for ax, (f, sh) in zip(axes.flat, top):
        shape_panel(ax, f, sh, color)
    S.fig_title(fig, title)
    note(fig, n_text)
    alt = f"{name} EBM shape functions, top 8 by importance: " + "; ".join(
        f"{f} importance {sh['importance']:.3f}, scores " + ", ".join(f"{v * 20 / np.log(2):+.1f}" for v in sh["scores"][:6]) + " points"
        for f, sh in top)
    S.save(fig, path, alt)


def chart_scorecard(gb):
    sc = pd.read_csv(OUT / "scorecard.csv")
    sc = sc[sc.feature != "intercept"].copy()
    pts = 20 / np.log(2)
    sc = sc.sort_values("weight")
    fig, ax = S.new_figure(size=(12.5, 7.8))
    y = np.arange(len(sc))
    ax.axvline(0, color=S.INK_2, lw=1)
    clear = sc.lo > 1e-6
    for yi, (_, r), c in zip(y, sc.iterrows(), clear):
        col = S.CATEGORICAL[0] if c else S.MUTED
        ax.plot([r.lo * pts, r.hi * pts], [yi, yi], color=col, lw=2, solid_capstyle="round")
        ax.scatter([r.weight * pts], [yi], s=60, color=col, edgecolor=S.SURFACE, lw=1.5, zorder=3)
        ax.text(1.005, yi, f"sign {r.sign}; zero in {100 * r.share_boot_zero:.0f}% of refits", transform=ax.get_yaxis_transform(),
                va="center", fontsize=9.5, color=S.INK_2)
    ax.set_yticks(y, [f"{short(f, 42)}  [{fam(f)}]" for f in sc.feature], fontsize=10.5)
    ax.set_ylim(-1.4, len(sc) - 0.4)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Points at full scale (feature at its cap; 20 points doubles the odds), 95% cluster bootstrap over 500 refits")
    dv = gb["dev"]
    a, lo, hi = dv["scorecard_oof_auc"]
    t, tlo, thi = dv["text_level_alone_auc"]
    title(fig, ax, f"A 15-term monotone scorecard fitted on 61 DEV pairs reaches out-of-fold AUROC {a:.2f} "
                        f"[{lo:.2f}, {hi:.2f}] against {t:.2f} for the text level alone; only {int(clear.sum())} terms are clearly above zero",
                    subtitle="Weights sign-constrained by expected direction; L2 penalty 1.0; features scaled to [0, 1] (counts capped). Gold DEV only.",
                    wrap=85)
    S.small_n_note(ax, dv["n"], threshold=100, text=f"Small sample: {dv['n']} pairs, {dv['n_pos']} confirmed")
    note(fig, "Source: viz/features/out/scorecard.csv, glassbox.json. Script: viz/features/glassbox.py")
    alt = (f"Monotone logistic scorecard on {dv['n']} DEV pairs, out-of-fold AUROC {a:.2f} [{lo:.2f}, {hi:.2f}], text level alone {t:.2f}. "
           + "; ".join(f"{r.feature} {r.weight * pts:+.1f} points [{r.lo * pts:+.1f}, {r.hi * pts:+.1f}]" for r in sc.iloc[::-1].itertuples()))
    S.save(fig, CH / "11_scorecard_dev", alt)


# ------------------------------------------------------------------ 6. stories and card table
def chart_nabh_text(feat):
    pu = feat.join(L.pu_labels(feat)[["pu_nabh"]])
    d = pu[pu.pu_nabh.notna()]
    rows = []
    for s in ["dialysis", "emergency_csection", "trauma_emergency", "cardiac_surgery"]:
        g = d[d.service == s]
        for lab, m in [("NABH lists the code", g.pu_nabh == 1), ("NABH lists other codes only", g.pu_nabh == 0)]:
            k, n = int((g[m].a_any_mention == 1).sum()), int(m.sum())
            rows.append(dict(service=s, group=lab, k=k, n=n))
    r = pd.DataFrame(rows)
    r.to_csv(OUT / "nabh_vs_text.csv", index=False)
    fig, ax = S.new_figure(size=(12, 6.5))
    svcs = r.service.unique()
    x = np.arange(len(svcs))
    w = 0.36
    for i, (lab, c) in enumerate([("NABH lists the code", S.CATEGORICAL[0]), ("NABH lists other codes only", S.CATEGORICAL[1])]):
        g = r[r.group == lab].set_index("service").loc[svcs]
        ps = [S.wilson(k, n) for k, n in zip(g.k, g.n)]
        bars = ax.bar(x + (i - 0.5) * w, [p[0] * 100 for p in ps], width=w, color=c, label=lab, **S.bar_style())
        S.add_interval(ax, x + (i - 0.5) * w, [p[1] * 100 for p in ps], [p[2] * 100 for p in ps])
        for xi, p_, k, n in zip(x + (i - 0.5) * w, ps, g.k, g.n):
            ax.text(xi, p_[2] * 100 + 1.5, f"{k}/{n}", ha="center", va="bottom", fontsize=9.5, color=S.INK)
    ax.set_xticks(x, [SVC_LABEL[s] + (" (code CAR = cardiology)" if s == "cardiac_surgery" else "") for s in svcs])
    ax.set_ylim(0, 105)
    ax.set_ylabel("Dataset text mentions the service (%, 95% Wilson)")
    ax.legend(loc="upper right")
    dia = r[(r.service == "dialysis") & (r.group == "NABH lists the code")].iloc[0]
    title(fig, ax, f"When NABH lists dialysis or nephrology (DIA or NPH), the dataset text mentions dialysis for only "
                        f"{dia.k} of {dia.n} facilities ({100 * dia.k / dia.n:.0f}%); NABH codes name departments, so read "
                        "this as text silence, not as proof the service exists",
                    subtitle="1,054 NABH-matched facilities with at least one fetched specialty code", wrap=80)
    note(fig, "Sources: data/external/nabh_accredited (codes DIA or NPH, OBG, EMD, CAR); model/proto/evidence/claim_atoms.parquet")
    alt = "Share of NABH-matched facilities whose dataset text mentions the service, split by whether NABH lists the code: " + "; ".join(
        f"{r_.service} {r_.group} {r_.k} of {r_.n}" for r_ in r.itertuples())
    S.save(fig, CH / "12_nabh_codes_vs_text", alt)


def chart_card_table(cat):
    head_order = {"S": 0, "X": 1, "R": 2, "L": 3, "E": 4}
    head_name = {"S": "Service", "X": "Official list", "R": "Guard", "L": "Location", "E": "Exists"}
    keep = cat[cat.recommendation.str.startswith("keep")].copy()
    keep["ho"] = keep["head"].map(head_order)
    keep = keep.sort_values(["ho", "family", "feature"])
    fig, ax = S.new_figure(size=(18, 1.6 + 0.36 * len(keep)))
    ax.axis("off")
    cols = ["Head", "What the card would say (example: dialysis)", "Feature", "DEV service", "DEV location",
            "NABH codes (PU)", "Fires on"]
    xs = [0.0, 0.07, 0.43, 0.595, 0.715, 0.835, 0.95]
    ax.text(0, 1.0, "", transform=ax.transAxes)
    for x, c in zip(xs, cols):
        ax.text(x, 0.995, c, fontsize=11, fontweight="bold", transform=ax.transAxes, va="bottom")
    ax.plot([0, 1], [0.99, 0.99], color=S.AXIS, lw=1, transform=ax.transAxes)
    step = 0.985 / len(keep)

    def fmt(a, lo, hi, small=False):
        if pd.isna(a):
            return "-"
        return f"{a:.2f} [{lo:.2f}, {hi:.2f}]" + (" *" if small else "")

    def pct(v):
        v = 100 * v
        return f"{v:.0f}%" if v >= 10 else f"{v:.1f}%" if v >= 0.1 else f"{v:.2f}%"
    import matplotlib.patches as mp
    for i, r in enumerate(keep.itertuples()):
        yy = 0.985 - (i + 0.5) * step
        if i % 2 == 0:
            ax.add_patch(mp.Rectangle((0, yy - step / 2), 1, step, transform=ax.transAxes, color=S.NEUTRAL, lw=0))
        vals = [head_name[r.head], '"' + textwrap.shorten(r.card_phrase_example, 62) + '"', r.feature,
                fmt(r.dev_auc, r.dev_auc_lo, r.dev_auc_hi, r.dev_too_small),
                fmt(r.loc_auc, r.loc_auc_lo, r.loc_auc_hi, r.loc_no < 5) if r.loc_no >= 1 else "-",
                fmt(r.nabh_auc, r.nabh_auc_lo, r.nabh_auc_hi), pct(r.nonzero_share)]
        for x, v in zip(xs, vals):
            ax.text(x, yy, str(v), fontsize=10, transform=ax.transAxes, va="center", color=S.INK,
                    family="monospace" if x == 0.43 else None)
    S.fig_title(fig, f"What the card would say: the {len(keep)} kept features in plain words, with how strongly each "
                     "separated confirmed from unconfirmed pairs", wrap=130)
    note(fig, "Example values (dialysis, 3, 40%, district hospital) are illustrative, not a real record. * fewer than 5 DEV pairs "
              "in the minority value: too small to read. '-' not computable (direct leakage, or no DEV pair has the value). "
              "AUROC columns with 95% intervals; 0.5 = no signal. DEV service: 61 pairs; DEV location: 52 facilities (12 wrong), AUROC for 'location right'. Source: viz/features/features_catalogue.csv")
    alt = "Card phrases for kept features: " + "; ".join(f"{r.feature}: {r.card_phrase_example}" for r in keep.itertuples())
    S.save(fig, CH / "13_card_phrases", alt)


def main():
    u, feat, meta = load()
    gb = json.loads((OUT / "glassbox.json").read_text())
    chart_coverage(feat)
    chart_coverage_features(u)
    chart_dev(u, meta)
    chart_pu(u, meta)
    chart_dev_vs_pu(u, meta)
    chart_location(u, meta)
    chart_clusters(u)
    chart_leakage(u, meta)
    ds = json.loads((OUT / "ebm_dev_shapes.json").read_text())
    ps = json.loads((OUT / "ebm_pu_shapes.json").read_text())
    a, lo, hi = gb["dev"]["ebm_oof_auc"]
    chart_ebm("Gold DEV", ds, f"EBM, interactions off, 50 outer bags, fitted on {gb['dev']['n']} gold DEV pairs ({gb['dev']['n_pos']} confirmed). "
              "Bands: +-1.96 bagging SD. Script: viz/features/glassbox.py",
              f"On 61 DEV pairs the EBM learns mostly web footprint (own-site mention, cited pages, hospital type); "
              f"out-of-fold AUROC {a:.2f} [{lo:.2f}, {hi:.2f}], so read these as hypotheses",
              CH / "09_ebm_shapes_dev", S.CATEGORICAL[0])
    p = gb["pu_nabh"]
    chart_ebm("NABH PU", ps, f"EBM, interactions off, fitted on {p['n']:,} NABH-coded pairs ({p['n_pos']:,} positive), service as a term, "
              "NABH features excluded. Bands: +-1.96 bagging SD. Script: viz/features/glassbox.py",
              f"With 4,216 NABH-coded pairs the shapes are stable: written prerequisites, beds and an own-site mention "
              f"raise the odds; held-out-state AUROC {p['oof_auc_within_service']:.2f} vs {p['text_level_alone_auc']:.2f} for text alone",
              CH / "10_ebm_shapes_nabh_pu", S.CATEGORICAL[2])
    chart_scorecard(gb)
    chart_nabh_text(feat)
    cat = pd.read_csv(HERE / "features_catalogue.csv")
    chart_card_table(cat)
    print("charts written to", CH)


if __name__ == "__main__":
    main()

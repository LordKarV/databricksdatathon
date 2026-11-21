"""Pattern 1: which services are claimed together, and does an incoherent claim profile predict trust problems.

Universe: facilities with at least one of the 36 taxonomy services in own, positive dataset text
(data/services_matrix.parquet). Pairs are tested on the discovery split; lift is re-measured on the holdout.
- association rules: support, confidence (both directions), lift with a 1,000-draw bootstrap 95% interval,
  Fisher exact p for every pair where both services have at least 30 discovery facilities;
- clinical review: CLINICAL_LINK lists pairs on one care pathway (written from clinical knowledge, not from
  the data); we report how many of the top 25 lift pairs are on it;
- suspicious profile: a single-focus name (eye, dental, IVF, skin, ENT, physiotherapy, AYUSH, diagnostic centre)
  claiming an acute service outside that focus. Logistic models (HC1 errors) for contamination and
  location drift, adjusted for claim breadth, URL count and facility type, fitted on each split separately.
Outputs: data/p1_pairs.csv, data/p1_suspicious.csv, data/tests_p1.csv, charts/p1_network.*, charts/p1_suspicious.*
"""
from __future__ import annotations

import itertools
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from common import CHARTS, DATA, SEED, S, facility, register, services, wilson, newcombe, two_prop_p

CATEGORY = {
    "emergency_24x7": "emergency", "trauma_care": "emergency", "burn_care": "emergency",
    "orthopaedic_trauma_surgery": "emergency", "snakebite_antivenom": "emergency",
    "icu": "critical", "picu": "critical", "ventilator_support": "critical",
    "emergency_csection": "maternal", "institutional_delivery": "maternal", "high_risk_pregnancy": "maternal",
    "nicu": "maternal", "safe_abortion_mtp": "maternal",
    "cardiac_surgery": "heart_brain", "cath_lab_angioplasty": "heart_brain", "stemi_thrombolysis": "heart_brain",
    "stroke_care": "heart_brain", "neurosurgery": "heart_brain",
    "dialysis": "kidney", "kidney_transplant": "kidney",
    "chemotherapy": "cancer", "radiotherapy": "cancer", "surgical_oncology": "cancer",
    "mri": "diagnostics", "ct_scan": "diagnostics", "ultrasound": "diagnostics", "blood_bank": "diagnostics",
    "psychiatric_care": "mental", "de_addiction": "mental", "cataract_surgery": "eye", "eye_emergency": "eye",
    "tb_care": "infectious", "hiv_art": "infectious", "anti_rabies": "infectious",
    "paediatric_inpatient": "child", "nutrition_rehabilitation": "child",
}
SERVICES = list(CATEGORY)
# One care pathway: the second service is a prerequisite, step-up or routine companion of the first.
CLINICAL_LINK = {frozenset(p) for p in [
    ("dialysis", "kidney_transplant"), ("cardiac_surgery", "cath_lab_angioplasty"),
    ("cath_lab_angioplasty", "stemi_thrombolysis"), ("cardiac_surgery", "stemi_thrombolysis"),
    ("stroke_care", "neurosurgery"), ("stroke_care", "ct_scan"), ("stroke_care", "stemi_thrombolysis"),
    ("chemotherapy", "radiotherapy"), ("chemotherapy", "surgical_oncology"), ("radiotherapy", "surgical_oncology"),
    ("icu", "ventilator_support"), ("icu", "picu"), ("picu", "nicu"), ("picu", "paediatric_inpatient"),
    ("nicu", "paediatric_inpatient"), ("nicu", "emergency_csection"), ("nicu", "high_risk_pregnancy"),
    ("emergency_csection", "institutional_delivery"), ("emergency_csection", "high_risk_pregnancy"),
    ("institutional_delivery", "high_risk_pregnancy"), ("institutional_delivery", "safe_abortion_mtp"),
    ("trauma_care", "orthopaedic_trauma_surgery"), ("trauma_care", "emergency_24x7"), ("trauma_care", "neurosurgery"),
    ("trauma_care", "burn_care"), ("trauma_care", "ct_scan"), ("emergency_24x7", "icu"), ("mri", "ct_scan"),
    ("ct_scan", "ultrasound"), ("cataract_surgery", "eye_emergency"), ("psychiatric_care", "de_addiction"),
    ("tb_care", "hiv_art"), ("anti_rabies", "snakebite_antivenom"), ("nutrition_rehabilitation", "paediatric_inpatient"),
    ("icu", "dialysis"), ("kidney_transplant", "icu"), ("neurosurgery", "icu"), ("cardiac_surgery", "icu"),
    ("picu", "ventilator_support"), ("nicu", "ventilator_support"), ("emergency_csection", "blood_bank"),
    ("trauma_care", "blood_bank"), ("orthopaedic_trauma_surgery", "emergency_24x7"), ("neurosurgery", "ct_scan"),
]}
# Single-focus names and the services that focus legitimately covers.
FOCUS = {
    "eye": (r"\b(eye|netra|nethra|ophthalm\w*|lasik|retina|vision)\b", {"cataract_surgery", "eye_emergency"}),
    "dental": (r"\b(dental|dentist\w*|teeth|tooth|orthodont\w*|dentistry)\b", set()),
    "ivf": (r"\b(ivf|fertility|test tube)\b", {"high_risk_pregnancy", "institutional_delivery", "safe_abortion_mtp"}),
    "skin": (r"\b(skin|derma\w*|hair|cosmetic|aesthetic\w*)\b", set()),
    "ent": (r"\bENT\b|ear,? nose", set()),
    "physio": (r"physiotherap\w*|\bphysio\b|rehabilitation cent", set()),
    "ayush": (r"ayurved\w*|homoeo\w*|homeo\w*|unani|siddha|naturopath\w*|panchakarma", set()),
    "diagnostic": (r"diagnostic\w*|\bscans?\b|imaging|path\w* lab|laborator\w*", {"mri", "ct_scan", "ultrasound"}),
}
GENERIC = r"multi|general hospital|super ?speciality|medical college|institute of medical|medical sciences|\bAIIMS\b"
ACUTE = {"icu", "nicu", "picu", "dialysis", "cardiac_surgery", "cath_lab_angioplasty", "emergency_csection",
         "neurosurgery", "trauma_care", "burn_care", "kidney_transplant", "ventilator_support", "stroke_care",
         "stemi_thrombolysis", "radiotherapy", "chemotherapy", "surgical_oncology", "orthopaedic_trauma_surgery",
         "institutional_delivery", "high_risk_pregnancy"}
MIN_FAC = 30


def name_focus(name: str, ftype: str) -> str:
    n = str(name or "")
    if re.search(GENERIC, n, re.I):
        return "none"
    hits = [k for k, (rx, _) in FOCUS.items()
            if re.search(rx, n) if k == "ent"] + [k for k, (rx, _) in FOCUS.items() if k != "ent" and re.search(rx, n, re.I)]
    if ftype == "dentist" and "dental" not in hits:
        hits.append("dental")
    return hits[0] if len(hits) == 1 else "none"


def pair_table(M: np.ndarray, names: list[str], boot: int = 1000) -> pd.DataFrame:
    n = M.shape[0]
    co = M.T @ M
    cnt = np.diag(co)
    rng = np.random.default_rng(SEED)
    blift = []
    for _ in range(boot):
        X = M[rng.integers(0, n, n)]
        c = X.T @ X
        d = np.diag(c)
        with np.errstate(divide="ignore", invalid="ignore"):
            blift.append(c * n / np.outer(d, d))
    blift = np.array(blift)
    rows = []
    for i, j in itertools.combinations(range(len(names)), 2):
        if cnt[i] < MIN_FAC or cnt[j] < MIN_FAC:
            continue
        ab = co[i, j]
        tab = [[ab, cnt[i] - ab], [cnt[j] - ab, n - cnt[i] - cnt[j] + ab]]
        orr, p = stats.fisher_exact(tab)
        lo, hi = np.nanpercentile(blift[:, i, j], [2.5, 97.5])
        rows.append(dict(a=names[i], b=names[j], n=n, n_a=cnt[i], n_b=cnt[j], n_ab=ab, support=ab / n,
                         conf_ab=ab / cnt[i], conf_ba=ab / cnt[j], lift=ab * n / (cnt[i] * cnt[j]),
                         lift_lo=lo, lift_hi=hi, odds_ratio=orr, p=p))
    return pd.DataFrame(rows)


def logit(d: pd.DataFrame, outcome: str, term: str) -> tuple[float, float, float, float, int]:
    d = d.dropna(subset=[outcome]).copy()
    m = smf.logit(f"{outcome} ~ {term} + np.log1p(n_services) + np.log(n_urls) + C(ftype)", d).fit(disp=0, cov_type="HC1")
    b, (lo, hi) = m.params[term], m.conf_int().loc[term]
    return float(np.exp(b)), float(np.exp(lo)), float(np.exp(hi)), float(m.pvalues[term]), int(m.nobs)


def main() -> None:
    f = facility().set_index("unique_id")
    sm = services()[SERVICES]
    tests = []
    out = {}
    for sp in ["discovery", "holdout"]:
        ids = f.index[(f.split == sp) & (sm.sum(axis=1) > 0)]
        out[sp] = pair_table(sm.loc[ids].to_numpy(float), SERVICES, boot=1000 if sp == "discovery" else 300)
    d, h = out["discovery"], out["holdout"].set_index(["a", "b"])
    d = d.join(h[["lift", "lift_lo", "lift_hi", "p", "n_ab", "n"]].add_prefix("ho_"), on=["a", "b"])
    d["linked"] = [frozenset((a, b)) in CLINICAL_LINK for a, b in zip(d.a, d.b)]
    d["same_category"] = [CATEGORY[a] == CATEGORY[b] for a, b in zip(d.a, d.b)]
    d.to_csv(DATA / "p1_pairs.csv", index=False)
    for r in d.itertuples():
        tests.append(dict(test_id=f"p1_pair_{r.a}__{r.b}", family="cooccurrence", description=f"{r.a} with {r.b}",
                          effect_type="lift", effect=r.lift, lo=r.lift_lo, hi=r.lift_hi, p=r.p, n=r.n,
                          ho_effect=r.ho_lift, ho_lo=r.ho_lift_lo, ho_hi=r.ho_lift_hi, ho_p=r.ho_p, ho_n=r.ho_n))

    top = d[d.n_ab >= MIN_FAC].sort_values("lift", ascending=False).head(25)
    neg = d[(d.lift < 1)].sort_values("p").head(10)
    summary = dict(n_pairs=len(d), n_disc_facilities=int(d.n.iloc[0]), top25_linked=int(top.linked.sum()),
                   top25_same_cat=int(top.same_category.sum()),
                   all_linked_share=float(d.linked.mean()),
                   top_pairs=top[["a", "b", "n_ab", "lift", "lift_lo", "lift_hi", "ho_lift", "linked"]].round(2).to_dict("records"),
                   anti_pairs=neg[["a", "b", "n_ab", "lift", "lift_lo", "lift_hi", "ho_lift", "p"]].round(3).to_dict("records"))

    # suspicious profile
    f["focus"] = [name_focus(n, t) for n, t in zip(f.name, f.ftype)]
    allowed = {k: v[1] for k, v in FOCUS.items()}
    claimed = sm.apply(lambda r: set(r.index[r.values > 0]), axis=1)
    f["off_focus_acute"] = [len((c & ACUTE) - allowed.get(fc, set())) if fc != "none" else 0
                            for c, fc in zip(claimed, f.focus)]
    f["suspicious"] = (f.off_focus_acute > 0).astype(int)
    f["incoherent_pairs"] = 0
    anti = d[(d.lift_hi < 1) & (d.p < 0.001)]
    anti_set = [(a, b) for a, b in zip(anti.a, anti.b)]
    f["incoherent_pairs"] = sum((sm[a] * sm[b]).reindex(f.index) for a, b in anti_set) if anti_set else 0
    f["any_incoherent"] = (f.incoherent_pairs > 0).astype(int)
    f[["focus", "off_focus_acute", "suspicious", "incoherent_pairs", "any_incoherent"]].to_csv(DATA / "p1_suspicious.csv")
    summary["focus_counts"] = f.focus.value_counts().to_dict()
    summary["suspicious_n"] = int(f.suspicious.sum())
    summary["suspicious_overlap_scope_conflict"] = int(((f.suspicious == 1) & (f.n_scope_conflict > 0)).sum())
    summary["anti_pairs_used"] = len(anti_set)

    rates = []
    for term in ["suspicious", "any_incoherent"]:
        for outcome in ["contaminated", "drift50"]:
            base = f[f.focus != "none"] if term == "suspicious" else f
            res = {sp: logit(base[base.split == sp], outcome, term) for sp in ["discovery", "holdout"]}
            (e, lo, hi, p, n), (he, hlo, hhi, hp, hn) = res["discovery"], res["holdout"]
            tests.append(dict(test_id=f"p1_{term}_{outcome}", family="cooccurrence",
                              description=f"{term} to {outcome} (adjusted for breadth; URLs; type)",
                              effect_type="adjusted odds ratio", effect=e, lo=lo, hi=hi, p=p, n=n,
                              ho_effect=he, ho_lo=hlo, ho_hi=hhi, ho_p=hp, ho_n=hn))
            for sp in ["discovery", "holdout"]:
                g = f[(f.split == sp) & f[outcome].notna() & (f.focus != "none")]
                for lv in [0, 1]:
                    x = g[g[term] == lv]
                    k, nn = int(x[outcome].sum()), len(x)
                    p_, l_, h_ = wilson(k, nn)
                    rates.append(dict(term=term, outcome=outcome, split=sp, level=lv, k=k, n=nn, rate=p_, lo=l_, hi=h_))
            rr = pd.DataFrame(rates[-4:]).set_index(["split", "level"])
            dd = {sp: (newcombe(rr.k[sp, 1], rr.n[sp, 1], rr.k[sp, 0], rr.n[sp, 0]),
                       two_prop_p(rr.k[sp, 1], rr.n[sp, 1], rr.k[sp, 0], rr.n[sp, 0])) for sp in ["discovery", "holdout"]}
            tests.append(dict(test_id=f"p1_{term}_{outcome}_raw", family="cooccurrence",
                              description=f"{term}: unadjusted rate difference in {outcome}, single-focus names",
                              effect_type="rate difference", effect=dd["discovery"][0][0], lo=dd["discovery"][0][1],
                              hi=dd["discovery"][0][2], p=dd["discovery"][1], n=int(rr.n.loc["discovery"].sum()),
                              ho_effect=dd["holdout"][0][0], ho_lo=dd["holdout"][0][1], ho_hi=dd["holdout"][0][2],
                              ho_p=dd["holdout"][1], ho_n=int(rr.n.loc["holdout"].sum())))
    rates = pd.DataFrame(rates)
    rates.to_csv(DATA / "p1_rates.csv", index=False)
    summary["rates_focus_named"] = rates.round(4).to_dict("records")
    register(tests, "p1")
    pd.Series(summary).to_json(DATA / "p1_summary.json", indent=1, default_handler=str)
    chart_network(d)
    chart_suspicious(rates, pd.DataFrame(tests).set_index("test_id"))
    print({k: v for k, v in summary.items() if k not in ("rates_focus_named",)})


def chart_network(d: pd.DataFrame) -> None:
    e = d[(d.n_ab >= MIN_FAC) & (d.lift_lo > 1.5)].sort_values("lift", ascending=False).head(40)
    nodes = [s for s in SERVICES if s in set(e.a) | set(e.b)]
    ang = np.linspace(0, 2 * np.pi, len(nodes), endpoint=False)
    pos = {s: (np.cos(a), np.sin(a)) for s, a in zip(nodes, ang)}
    fig, ax = S.new_figure(size=(12, 9))
    for r in e.sort_values("lift").itertuples():
        (x1, y1), (x2, y2) = pos[r.a], pos[r.b]
        col = S.CATEGORICAL[0] if r.linked else S.CATEGORICAL[1]
        ax.plot([x1, x2], [y1, y2], color=col, lw=0.6 + 0.35 * min(r.lift, 12), alpha=0.75, zorder=1,
                solid_capstyle="round")
    nfac = dict(zip(d.a, d.n_a)) | dict(zip(d.b, d.n_b))
    for s, (x, y) in pos.items():
        ax.scatter([x], [y], s=40 + nfac[s] / 6, color=S.SURFACE, edgecolor=S.INK, lw=1.2, zorder=3)
        ha = "left" if x > 0.05 else ("right" if x < -0.05 else "center")
        ax.text(x * 1.1, y * 1.1, f"{s.replace('_', ' ')} ({int(nfac[s]):,})", ha=ha, va="center", fontsize=9, color=S.INK)
    ax.plot([], [], color=S.CATEGORICAL[0], lw=3, label=f"Same care pathway ({int(e.linked.sum())} of {len(e)})")
    ax.plot([], [], color=S.CATEGORICAL[1], lw=3, label=f"Not on a listed pathway ({int((~e.linked).sum())})")
    ax.legend(loc="lower left", frameon=False, fontsize=10, bbox_to_anchor=(0.0, 0.0))
    ax.set_xlim(-1.75, 1.75); ax.set_ylim(-1.25, 1.2); ax.set_aspect("equal"); ax.axis("off")
    k = int(e.linked.sum())
    S.fig_title(fig, f"Two kinds of service pairing: {k} of the {len(e)} strongest sit on one care pathway (blue); "
                        f"most of the rest tie cardiac, transplant, cancer and imaging services into one tertiary bundle (orange)")
    S.panel_title(ax, f"Lift lower bound above 1.5, at least {MIN_FAC} facilities per pair; discovery split, n = {int(d.n.iloc[0]):,} facilities\n"
                             f"with a service claim. Line width = lift; circle size and number = facilities claiming the service.")
    S.source_note(fig, "Source: kb/taxonomy/out/lexicon_matches.parquet (own positive text); viz/patterns/p1_cooccurrence.py")
    S.save(fig, str(CHARTS / "p1_network"), alt_text=(
        f"Network of the 40 most over-represented service pairs among {int(d.n.iloc[0]):,} discovery facilities. "
        f"{k} of 40 are on one clinical pathway, such as chemotherapy with radiotherapy (lift "
        f"{d.set_index(['a','b']).lift.get(('chemotherapy','radiotherapy'), float('nan')):.1f}) and cataract surgery with eye emergency."))


def chart_suspicious(r: pd.DataFrame, t: pd.DataFrame) -> None:
    fig, axes = S.new_figure(ncols=2)
    for ax, outcome, lab in zip(axes, ["contaminated", "drift50"],
                                ["Has another facility's text (%)", "Pin over 50 km from own PIN (%)"]):
        x = r[(r.term == "suspicious") & (r.outcome == outcome)]
        pos = 0
        ticks, tl = [], []
        for sp in ["discovery", "holdout"]:
            for lv, col in [(0, S.OTHER), (1, S.SEMANTIC["flagged"])]:
                row = x[(x.split == sp) & (x.level == lv)].iloc[0]
                b = ax.bar([pos], [row.rate * 100], color=col, **S.bar_style())
                S.add_interval(ax, [pos], [row.lo * 100], [row.hi * 100])
                ax.text(pos, row.hi * 100 + 1.5, f"{row.rate*100:.0f}%\n{row.k}/{row.n}", ha="center", fontsize=8, color=S.INK)
                ticks.append(pos); tl.append(f"{sp}\n{'claims off-focus acute' if lv else 'stays in focus'}")
                pos += 1
            pos += 0.6
        ax.set_xticks(ticks, tl, fontsize=8)
        ax.set_ylabel(lab[:-4] + " (%, 95% Wilson CI)")
        ax.set_ylim(0, max(x.hi) * 100 + 12)
        S.panel_title(ax, f"Single-focus names, n = {int(x[x.split=='discovery'].n.sum()):,} discovery")
    d1 = r[(r.term == "suspicious") & (r.outcome == "contaminated") & (r.split == "discovery")].set_index("level").rate
    a = t.loc["p1_suspicious_contaminated"]
    S.fig_title(fig, f"Eye, dental and AYUSH-named facilities that claim acute care carry another facility's text "
                     f"{d1[1]*100:.0f}% of the time vs {d1[0]*100:.0f}%, but the gap is claim breadth: adjusted odds ratio "
                     f"{a.effect:.2f} ({a.lo:.2f} to {a.hi:.2f})")
    S.source_note(fig, "Source: viz/patterns/data/p1_rates.csv; derived/v1/claims.parquet; derived/v1/facility_location.parquet")
    S.save(fig, str(CHARTS / "p1_suspicious"), alt_text=(
        f"Bars compare single-focus facilities that claim an acute service outside their focus with those that do not. "
        f"Contamination {d1[1]*100:.0f}% vs {d1[0]*100:.0f}% in discovery; the holdout bars repeat the comparison."))


if __name__ == "__main__":
    main()

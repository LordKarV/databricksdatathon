"""Pattern 4: district supply (records per million, by service and evidence level) vs NFHS-5 need indicators.

Unit: NFHS-5 district (population from WorldPop 2025 via the LGD crosswalk, built by viz/geography/common.py and
read from its cache). Supply = records per million people:
  all records; dialysis corroborated (own text plus an independent source); C-section claimed (own positive text;
  only 115 records are corroborated, too sparse); trauma corroborated.
Need: NFHS-5 district fact-sheet values; "*" (suppressed) cells are missing, "(x)" cells kept.
Statistic: Spearman rho with bootstrap 95% CI and permutation p, plus a partial rho controlling for the share of
the district's people living in an urban centre (both variables rank-regressed on that share).
Hold-out: districts (not facilities) are split 70/30 with the project seed; pairs are tested on the 70%.
ECOLOGICAL FALLACY: these are district aggregates. A district where more births are by C-section and more
facilities claim C-section says nothing about whether any one facility performs them, or about any one mother.
Outputs: data/p4_districts.csv, data/p4_correlations.csv, data/tests_p4.csv, charts/p4_district.*
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from common import CHARTS, DATA, ROOT, SEED, S, facility, register, spearman_ci

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("geo_common", ROOT / "viz" / "geography" / "common.py")
G = importlib.util.module_from_spec(_spec)  # viz/geography/common.py, read-only reuse of its population cache
_spec.loader.exec_module(G)

NEED = {
    "hh_member_covered_health_insurance_pct": "Households with health insurance (%)",
    "institutional_birth_5y_pct": "Institutional births (%)",
    "births_delivered_by_csection_5y_pct": "C-section births, all (%)",
    "births_in_a_private_fac_that_were_delivered_by_csection_5y_pct": "C-section share of private-facility births (%)",
    "births_in_a_public_fac_that_were_delivered_by_csection_5y_pct": "C-section share of public-facility births (%)",
    "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct": "Women with high blood sugar (%)",
    "m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct": "Men with high blood sugar (%)",
    "w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct": "Women with high blood pressure (%)",
    "m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct": "Men with high blood pressure (%)",
}
SUPPLY = {"all_pm": "All records per million", "dialysis_corr_pm": "Corroborated dialysis per million",
          "csection_claim_pm": "C-section claims per million", "trauma_corr_pm": "Corroborated trauma per million"}
PAIRS = [("all_pm", "hh_member_covered_health_insurance_pct"), ("all_pm", "institutional_birth_5y_pct"),
         ("all_pm", "births_delivered_by_csection_5y_pct"),
         ("csection_claim_pm", "births_delivered_by_csection_5y_pct"),
         ("csection_claim_pm", "births_in_a_private_fac_that_were_delivered_by_csection_5y_pct"),
         ("csection_claim_pm", "births_in_a_public_fac_that_were_delivered_by_csection_5y_pct"),
         ("csection_claim_pm", "institutional_birth_5y_pct"),
         ("dialysis_corr_pm", "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct"),
         ("dialysis_corr_pm", "m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct"),
         ("dialysis_corr_pm", "w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct"),
         ("dialysis_corr_pm", "m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct"),
         ("trauma_corr_pm", "hh_member_covered_health_insurance_pct")]


def districts() -> pd.DataFrame:
    d = G.nfhs_districts(list(NEED))
    d = d[d["pop"] > 0].copy()
    d["urban_share"] = d.pop_3 / d["pop"]
    f = facility()
    e = G.evidence_flags()
    key = ["nfhs_state", "nfhs_district"]
    counts = {"all": f.groupby(key).size()}
    for grp, col, name in [("dialysis", "corroborated", "dialysis_corr"), ("csection", "claimed", "csection_claim"),
                           ("trauma", "corroborated", "trauma_corr")]:
        ids = set(e[(e.group == grp) & e[col]].unique_id)
        counts[name] = f[f.unique_id.isin(ids)].groupby(key).size()
    for name, s in counts.items():
        d[name] = d.set_index(key).index.map(s).fillna(0).to_numpy()
        d[f"{name}_pm"] = d[name] / d["pop"] * 1e6
    rng = np.random.default_rng(SEED)
    d["split"] = np.where(rng.random(len(d)) < 0.7, "discovery", "holdout")
    return d


def partial_spearman(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple[float, float, float, float, int]:
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    rx, ry, rz = (stats.rankdata(v[m]) for v in (x, y, z))
    res = [a - np.polyval(np.polyfit(rz, a, 1), rz) for a in (rx, ry)]
    return spearman_ci(res[0], res[1])  # ponytail: rank residuals re-ranked; fine as an approximate partial rho


def main() -> None:
    d = districts()
    d.to_csv(DATA / "p4_districts.csv", index=False)
    rows, tests = [], []
    for s, n in PAIRS:
        for kind in ["raw", "partial_urban"]:
            r = {}
            for sp in ["discovery", "holdout"]:
                x = d[d.split == sp]
                r[sp] = (spearman_ci(x[s].to_numpy(), x[n].to_numpy()) if kind == "raw"
                         else partial_spearman(x[s].to_numpy(), x[n].to_numpy(), x.urban_share.to_numpy()))
            (e, lo, hi, p, nn), (he, hlo, hhi, hp, hn) = r["discovery"], r["holdout"]
            rows.append(dict(supply=s, need=n, kind=kind, rho=e, lo=lo, hi=hi, p=p, n=nn, ho_rho=he, ho_lo=hlo, ho_hi=hhi, ho_p=hp, ho_n=hn))
            tests.append(dict(test_id=f"p4_{kind}_{s}_{n[:40]}", family="district",
                              description=f"{SUPPLY[s]} vs {NEED[n]} ({kind})", effect_type="Spearman rho",
                              effect=e, lo=lo, hi=hi, p=p, n=nn, ho_effect=he, ho_lo=hlo, ho_hi=hhi, ho_p=hp, ho_n=hn))
    c = pd.DataFrame(rows)
    c.to_csv(DATA / "p4_correlations.csv", index=False)
    register(tests, "p4")
    print(c.round(3).to_string())
    print("districts", len(d), d.split.value_counts().to_dict(), "zero dialysis corr", int((d.dialysis_corr == 0).sum()))
    chart(d, c)


def chart(d: pd.DataFrame, c: pd.DataFrame) -> None:
    fig, (ax, ax2) = S.new_figure(size=(14, 7.5), ncols=2, gridspec_kw={"width_ratios": [1.25, 1]})
    y = np.arange(len(PAIRS))
    for off, kind, col, lab in [(-0.17, "raw", S.CATEGORICAL[0], "raw"), (0.17, "partial_urban", S.CATEGORICAL[1], "urban share held fixed")]:
        x = c[c.kind == kind]
        ax.errorbar(x.rho, y + off, xerr=[x.rho - x.lo, x.hi - x.rho], fmt="o", ms=5, color=col, capsize=0, elinewidth=1.4,
                    label=f"{lab}, discovery districts (n = {int(x.n.max())})")
        ax.scatter(x.ho_rho, y + off, marker="x", s=30, color=S.INK, zorder=3, label="holdout point estimate" if kind == "raw" else None)
    ax.axvline(0, color=S.MUTED, lw=1)
    ax.set_yticks(y, [f"{SUPPLY[s].replace(' per million', '/M')} vs\n{NEED[n]}" for s, n in PAIRS], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlabel("Spearman rho across districts (95% bootstrap CI)")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", bbox_to_anchor=(-0.35, -0.09), ncol=3)
    S.panel_title(ax, "Supply vs need, district level")
    x = d[d.split == "discovery"]
    k = "institutional_birth_5y_pct"
    ax2.scatter(x[k], x.all_pm + 0.5, s=np.clip(x["pop"] / 1e5, 4, 80), color=S.CATEGORICAL[0], alpha=0.55, lw=0)
    ax2.set_yscale("log")
    ax2.set_yticks([0.5, 1, 2, 5, 10, 20, 50, 100], ["0", "0.5", "1.5", "4.5", "9.5", "19.5", "49.5", "99.5"])
    ax2.minorticks_off()
    ax2.set_xlabel("Institutional births (% of births in the 5 years before NFHS-5)")
    ax2.set_ylabel("Dataset records per million people (log scale; 0 at bottom)")
    r = c[(c.supply == "all_pm") & (c.need == k)].set_index("kind")
    ins = c[(c.supply == "all_pm") & (c.need == "hh_member_covered_health_insurance_pct")].set_index("kind")
    dia = c[(c.supply == "dialysis_corr_pm") & (c.need.str.startswith("w15_plus_with_high_bp"))].set_index("kind")
    S.panel_title(ax2, f"Discovery districts, n = {int(r.n['raw'])}; dot size = population")
    S.fig_title(fig, f"Records follow institutional births (rho {r.rho['raw']:.2f}, {r.lo['raw']:.2f} to {r.hi['raw']:.2f}), "
                     f"not insurance cover ({ins.rho['raw']:.2f}); corroborated dialysis tracks women's high blood pressure "
                     f"even with urban share fixed ({dia.rho['partial_urban']:.2f}, {dia.lo['partial_urban']:.2f} to {dia.hi['partial_urban']:.2f}). "
                     f"District aggregates only")
    S.source_note(fig, "Ecological data: NFHS-5 district fact sheets, WorldPop 2025 population, dataset records by NFHS district. "
                       "Districts split 70/30 for replication. Source: viz/patterns/p4_district.py")
    S.save(fig, str(CHARTS / "p4_district"), alt_text=(
        f"Forest plot of 12 district-level Spearman correlations between facility supply and NFHS-5 need, raw and with urban share held fixed, "
        f"plus a scatter of institutional births against records per million (rho {r.rho['raw']:.2f}). "
        f"These are ecological correlations and do not describe individual facilities."))


if __name__ == "__main__":
    main()

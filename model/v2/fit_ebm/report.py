"""Print the markdown tables FIT.md quotes, straight from out/. Run after fit_ps.py and fit_pl.py."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "out"


def md(df: pd.DataFrame, index: bool = True) -> str:
    """Markdown table without the tabulate dependency."""
    d = df.reset_index() if index else df
    head = "| " + " | ".join(map(str, d.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in d.columns) + " |"
    body = ["| " + " | ".join(map(str, r)) + " |" for r in d.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def ci(r: pd.Series, col: str = "value", lo: str = "lo", hi: str = "hi") -> str:
    return f"{r[col]:.3f} [{r[lo]:.3f}, {r[hi]:.3f}]"


def metric_table(m: pd.DataFrame) -> str:
    rows = ["| model | n (pos) | log loss | AUROC | Brier | ECE | log loss delta vs base rate |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for model, d in m.groupby("model", sort=False):
        d = d.set_index("metric")
        ll = d.loc["log_loss"]
        delta = ("ref" if pd.isna(ll.get("delta_vs_ref")) else
                 f"{ll.delta_vs_ref:+.3f} [{ll.delta_lo:+.3f}, {ll.delta_hi:+.3f}] se {ll.delta_se:.3f}")
        rows.append(f"| {model} | {int(ll.n)} ({int(ll.k)}) | {ci(ll)} | {ci(d.loc['auroc'])} | "
                    f"{ci(d.loc['brier'])} | {ci(d.loc['ece'])} | {delta} |")
    return "\n".join(rows)


def likely_with_pl() -> dict:
    """Likely rule with the P_L >= 0.7 gate added (P_E is prior-only and not applied here).

    P_L per gold facility: the fold5 out-of-fold P_L when the facility has a location label,
    otherwise the final-fit P_L, which never saw that facility's label (it has none).
    """
    import numpy as np
    from scipy.special import expit
    import metrics as M
    oof = pd.read_parquet(OUT / "ps_oof_predictions.parquet")
    plo = pd.read_parquet(OUT / "pl_oof_predictions.parquet")
    plo = plo[(plo.cv == "fold5") & (plo.variant == "L_ebm")].set_index("unique_id").p
    pla = pd.read_parquet(OUT / "pl_scores_all.parquet").set_index("unique_id").p
    feats = pd.read_parquet("/Users/karthikvattem/projects/datathon/derived/v2/facility_features.parquet",
                            columns=["unique_id", "service", "a_T"])
    out = {}
    for (cv, v), d in oof.groupby(["cv", "variant"]):
        d = d.merge(feats, on=["unique_id", "service"], how="left")
        p_l = d.unique_id.map(plo).fillna(d.unique_id.map(pla)).to_numpy()
        gate = ((d.a_T >= 2) & (p_l >= 0.7)).to_numpy()
        out[f"{cv}|{v}"] = M.thresholds(d.y_S.to_numpy(), expit(d.z.to_numpy()), gate)
    (OUT / "ps_thresholds_with_pl_gate.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def thr_table(title: str, thr: dict) -> None:
    print(f"\n### P_S thresholds, {title}\n")
    print("| cv / variant | t_L | fallback | Likely n | precision [Wilson] | best precision, 20+ beyond "
          "| t_U | fallback | Unlikely n | NPV [Wilson] |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for k, t in thr.items():
        lw, uw = t["likely_wilson"], t["unlikely_wilson"]
        print(f"| {k} | {t['t_L']:.3f} | {t['t_L_fallback']} | {t['likely_n']} | "
              f"{t['likely_precision']:.3f} [{lw[0]:.3f}, {lw[1]:.3f}] | {t['max_precision_20']:.3f} | "
              f"{t['t_U']:.3f} | {t['t_U_fallback']} | {t['unlikely_n']} | "
              f"{t['unlikely_npv']:.3f} [{uw[0]:.3f}, {uw[1]:.3f}] |")


def main() -> None:
    ps = pd.read_csv(OUT / "ps_metrics.csv")
    for (cv, subset, wt), d in ps.groupby(["cv", "subset", "weighting"], sort=False):
        print(f"\n### P_S cv={cv} subset={subset} weighting={wt}\n")
        print(metric_table(d))
    for title, thr in (("T >= 2 gate", json.loads((OUT / "ps_thresholds.json").read_text())),
                       ("T >= 2 and P_L >= 0.7 gate", likely_with_pl())):
        thr_table(title, thr)
    fam =pd.read_csv(OUT / "ps_family_contributions.csv")
    print("\n### P_S family contributions (fold5 OOF)\n")
    f5 = fam[fam.cv == "fold5"].round(3)
    print(md(f5.pivot_table(index="family", columns="variant", values="mean_abs").round(3)))
    print()
    print(md(f5[f5.variant.isin(["C1_platt", "C3_resid", "C0_gold"])][
        ["variant", "family", "mean_pos", "mean_neg", "share_nonzero"]], index=False))
    svc = pd.read_csv(OUT / "ps_metrics_by_service.csv")
    print("\n### P_S by service (fold5 OOF)\n")
    s = svc[svc.metric.isin(["log_loss", "auroc"])].assign(
        cell=lambda d: d.apply(lambda r: f"{r.value:.3f} [{r.lo:.3f}, {r.hi:.3f}]", axis=1))
    print(md(s.pivot_table(index=["service", "metric"], columns="model", values="cell",
                        aggfunc="first")))
    pl = pd.read_csv(OUT / "pl_metrics.csv")
    for (cv, subset), d in pl.groupby(["cv", "subset"], sort=False):
        print(f"\n### P_L cv={cv} subset={subset}\n")
        print(metric_table(d) if "log_loss" in set(d.metric.dropna()) else md(d, index=False))
    meta = json.loads((OUT / "ps_fit_meta.json").read_text())
    print("\nclamp edits (final):", meta["clamp_edits_final"])
    print("platt:", json.dumps(meta["platt"]))
    sh = pd.read_parquet(OUT / "ps_shape_functions.parquet")
    for v in ("C1_platt", "C3_resid", "C0_gold"):
        d = sh[(sh.variant == v) & ~sh.bin_label.isin(["unseen"])]
        rng = d.groupby(["stage", "term"]).contribution_logit.agg(["min", "max"]).round(3)
        print(f"\n### shape ranges {v}\n")
        print(md(rng))


if __name__ == "__main__":
    main()

"""Candidate C for P_S: EBM (interactions off) on PU list labels plus gold DEV, cross-fitted.

Variants (all additive ledgers, see glassbox.py):
- base_rate: training-fold confirmation rate, no features (reference for paired deltas).
- C1_shift: PU-stage EBM score + one gold-fitted intercept shift (slope fixed at 1).
- C1_platt: PU-stage EBM score with a gold-fitted Platt slope and intercept.
- C0_gold: EBM fitted on gold DEV pairs only (terms plus a service term).
- C3_resid: C1_platt as init_score plus a gold residual EBM (terms plus service).
Each EBM variant is also run without the website and cited-source columns (suffix _noweb).

CV: fold5 (grouped by leakage group, shared with the PU tables) and held-out states
(GroupKFold on state; train rows sharing a leakage group with the test fold are dropped too).
In every fold the PU stage is refitted without the test fold's facilities.

Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python fit_ps.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

import features as F
import glassbox as G
import metrics as M

OUT = Path(__file__).parent / "out"
PU_EXCLUDE_FAMILIES = ("mohfw_tcf", "pmndp_goa")    # c = 0.056, and 1 positive (LABELS.md)
PU_EXCLUDE_PAIRS = (("nmc", "blood_bank"),)          # c = 0.000 [0, 0.176]
LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ff = F.load_features()
    gold = pd.read_parquet(f"{F.LABEL_DIR}/gold_dev_pairs.parquet")
    gold = gold[gold.y_S.notna()].merge(ff, on=["unique_id", "service"], how="left",
                                        suffixes=("", "_ff"), validate="one_to_one")
    assert gold.a_T.notna().all() and (gold.leakage_group_id == gold.leakage_group_id_ff).all()
    pu = pd.read_parquet(f"{F.LABEL_DIR}/pu_labels.parquet")
    keep = pu.label.isin(["positive", "unlabeled"]) & ~pu.label_family.isin(PU_EXCLUDE_FAMILIES)
    for fam, svc in PU_EXCLUDE_PAIRS:
        keep &= ~((pu.label_family == fam) & (pu.service == svc))
    pu = pu[keep].merge(ff, on=["unique_id", "service"], how="left", suffixes=("", "_ff"),
                        validate="many_to_one").reset_index(drop=True)
    assert pu.a_T.notna().all()
    plan = pd.read_parquet(f"{F.LABEL_DIR}/crossfit_plan.parquet")
    return ff, gold.reset_index(drop=True), pu, plan


def pu_matrix(pu: pd.DataFrame, terms: tuple[F.Term, ...],
              masks: dict[str, list[str]]) -> pd.DataFrame:
    """PU design matrix with each label family's own list columns set to NaN in its rows.

    A list used as the label is then never a feature for those rows (cross-fitting by label
    family); its column learns only from rows another list labelled.
    """
    X = F.matrix(pu, terms)
    for fam, cols in masks.items():
        rows = (pu.label_family == fam).to_numpy()
        cols = [c for c in cols if c in X]
        if rows.any() and cols:
            X.loc[rows, cols] = np.nan
            assert X.loc[rows, cols].isna().all().all()
    return X


def fit_pu(pu: pd.DataFrame, terms: tuple[F.Term, ...], masks: dict[str, list[str]]):
    """PU-stage EBM: list positive vs unlabeled inside each list's scope.

    init_score is the logit of the weighted positive rate per (label family, service), a
    training-only nuisance offset. The terms then learn within-(list, service) discrimination
    instead of list and service base rates, and NaN masks cannot act as a family indicator.
    The offset is not part of the published ledger; the gold Platt step sets the level.
    """
    y = (pu.label == "positive").to_numpy(int)
    w = np.where(y == 1, pu.weight.to_numpy(), 1.0)
    cell = (pu.label_family + "|" + pu.service).to_numpy()   # positional, not index-aligned
    rate = pd.Series(y * w).groupby(cell).sum() / pd.Series(w).groupby(cell).sum()
    init = logit(pd.Series(cell).map(rate.clip(0.01, 0.99)).to_numpy(float))
    assert np.isfinite(init).all()
    ebm = G.fit_ebm(pu_matrix(pu, terms, masks), y, terms, weight=w, init=init)
    edits = G.clamp_list_terms(ebm, terms)
    return ebm, edits


def platt(s: np.ndarray, y: np.ndarray, slope: bool) -> tuple[float, float]:
    if slope:
        lr = LogisticRegression(C=1e6, max_iter=1000).fit(s.reshape(-1, 1), y)
        a, b = float(lr.coef_[0, 0]), float(lr.intercept_[0])
        assert a > 0, "Platt slope must be positive"
        return a, b
    # intercept-only shift with slope 1: Newton on b
    b = 0.0
    for _ in range(50):
        p = expit(s + b)
        b += float((y - p).sum() / max((p * (1 - p)).sum(), 1e-12))
    return 1.0, b


def fold_ledgers(gtr: pd.DataFrame, pu_tr: pd.DataFrame, terms: tuple[F.Term, ...],
                 masks: dict[str, list[str]]) -> tuple[dict[str, G.Ledger], list[dict]]:
    """Fit every EBM variant on one training fold. Returns ledgers and the clamp edits."""
    terms_s = terms + (F.SERVICE_TERM,)
    y = gtr.y_S.to_numpy(int)
    ebm_pu, edits = fit_pu(pu_tr, terms, masks)
    s_tr = ebm_pu.decision_function(F.matrix(gtr, terms))
    led: dict[str, G.Ledger] = {}
    for name, slope in (("C1_shift", False), ("C1_platt", True)):
        a, b = platt(s_tr, y, slope)
        led[name] = G.Ledger((G.Stage("pu", ebm_pu, terms, a),), b)
    ebm0 = G.fit_ebm(F.matrix(gtr, terms_s), y, terms_s)
    edits += G.clamp_list_terms(ebm0, terms_s)
    led["C0_gold"] = G.Ledger((G.Stage("gold", ebm0, terms_s, 1.0),), 0.0)
    init = G.score(led["C1_platt"], gtr)
    ebm3 = G.fit_ebm(F.matrix(gtr, terms_s), y, terms_s, init=init)
    edits += G.clamp_list_terms(ebm3, terms_s)
    p1 = led["C1_platt"]
    led["C3_resid"] = G.Ledger(p1.stages + (G.Stage("gold", ebm3, terms_s, 1.0),), p1.offset)
    return led, edits


def splits(gold: pd.DataFrame, scheme: str) -> list[np.ndarray]:
    if scheme == "fold5":
        return [np.flatnonzero(gold.fold5 == k) for k in range(5)]
    gkf = GroupKFold(n_splits=5)
    return [te for _, te in gkf.split(gold, groups=gold.state)]


def run_cv(gold: pd.DataFrame, pu: pd.DataFrame, terms: tuple[F.Term, ...],
           masks: dict[str, list[str]], scheme: str, suffix: str) -> pd.DataFrame:
    parts = []
    for k, te in enumerate(splits(gold, scheme)):
        t0 = time.time()
        gte = gold.iloc[te]
        test_groups = set(gte.leakage_group_id)
        tr_mask = ~gold.index.isin(te) & ~gold.leakage_group_id.isin(test_groups)
        pu_mask = ~pu.leakage_group_id.isin(test_groups)
        if scheme == "fold5":
            pu_mask &= pu.fold5 != k
        else:
            test_states = set(gte.state)
            tr_mask &= ~gold.state.isin(test_states)
            pu_mask &= ~pu.state.isin(test_states)
        gtr = gold[tr_mask]
        led, edits = fold_ledgers(gtr, pu[pu_mask], terms, masks)
        base_p = gtr.y_S.mean()
        part = [pd.DataFrame(dict(row=te, variant="base_rate" + suffix, z=logit(base_p),
                                  base=logit(base_p)))]
        for name, ledger in led.items():
            base, contrib = G.contributions(ledger, gte)
            z = G.score(ledger, gte)
            df = pd.DataFrame(dict(row=te, variant=name + suffix, z=z, base=base))
            part.append(pd.concat([df, contrib.add_prefix("c__").reset_index(drop=True)], axis=1))
        out = pd.concat(part, ignore_index=True).assign(cv=scheme, fold=k)
        parts.append(out)
        log(f"{scheme}{suffix} fold {k}: train gold {len(gtr)}, PU {int(pu_mask.sum())}, "
            f"test {len(te)}, clamp edits {len(edits)}, {time.time() - t0:.0f}s")
    return pd.concat(parts, ignore_index=True)


def family_summary(oof: pd.DataFrame, gold: pd.DataFrame,
                   fam_of: dict[str, str]) -> pd.DataFrame:
    rows = []
    for (cv, var), d in oof.groupby(["cv", "variant"]):
        cols = [c for c in d.columns if c.startswith("c__") and d[c].notna().any()]
        if not cols:
            continue
        y = gold.y_S.to_numpy()[d.row.to_numpy()]
        fam = pd.DataFrame({c: d[c].to_numpy() for c in cols}).T.groupby(
            lambda c: fam_of[c.split(":")[1]]).sum().T
        for f in fam.columns:
            v = fam[f].to_numpy()
            rows.append(dict(cv=cv, variant=var, family=f, mean_abs=float(np.abs(v).mean()),
                             mean_pos=float(v[y == 1].mean()), mean_neg=float(v[y == 0].mean()),
                             share_nonzero=float((np.abs(v) > 1e-12).mean())))
    return pd.DataFrame(rows)


def evaluate(oof: pd.DataFrame, gold: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    res, thr = [], {}
    subsets = {
        "all": np.ones(len(gold), bool),
        "public": (gold.operator_public == 1).to_numpy(),
        "private": (gold.operator_public == 0).to_numpy(),
        "no_gold_cites_list": ~gold.gold_cites_list.to_numpy(),
    }
    for cv, d in oof.groupby("cv"):
        P = {v: expit(g.set_index("row").z.sort_index().to_numpy()) for v, g in d.groupby("variant")}
        y = gold.y_S.to_numpy()
        for sname, m in subsets.items():
            for suffix in ("", "_noweb"):
                preds = {v: p[m] for v, p in P.items() if v.endswith(suffix) and
                         (suffix or not v.endswith("_noweb"))}
                if not preds or m.sum() < 5:
                    continue
                ref = "base_rate" + suffix
                s = M.summarize(y[m], preds, gold.leakage_group_id.to_numpy()[m], ref=ref)
                res.append(s.assign(cv=cv, subset=sname, weighting="none"))
        # IPW on the stratified v1 and v2 pairs (e2e pairs have no inclusion probability).
        m = gold.ipw.notna().to_numpy()
        preds = {v: p[m] for v, p in P.items() if not v.endswith("_noweb")}
        s = M.summarize(y[m], preds, gold.leakage_group_id.to_numpy()[m],
                        w=gold.ipw.to_numpy()[m], ref="base_rate")
        res.append(s.assign(cv=cv, subset="v1v2_strata", weighting="ipw"))
        gate = (gold.a_T >= 2).to_numpy()
        for v, p in P.items():
            thr[f"{cv}|{v}"] = M.thresholds(y, p, gate)
    return pd.concat(res, ignore_index=True), thr


def per_service(oof: pd.DataFrame, gold: pd.DataFrame, variants: tuple[str, ...]) -> pd.DataFrame:
    d = oof[(oof.cv == "fold5") & oof.variant.isin(variants)]
    P = {v: expit(g.set_index("row").z.sort_index().to_numpy()) for v, g in d.groupby("variant")}
    out = []
    for svc in sorted(gold.service.unique()):
        m = (gold.service == svc).to_numpy()
        s = M.summarize(gold.y_S.to_numpy()[m], {v: p[m] for v, p in P.items()},
                        gold.leakage_group_id.to_numpy()[m], ref="base_rate")
        out.append(s.assign(service=svc))
    return pd.concat(out, ignore_index=True)


def final_fit(ff: pd.DataFrame, gold: pd.DataFrame, pu: pd.DataFrame, terms, masks,
              suffix: str) -> tuple[dict[str, G.Ledger], list[dict]]:
    led, edits = fold_ledgers(gold, pu, terms, masks)
    return {k + suffix: v for k, v in led.items()}, edits


def main(final_only: bool = False) -> None:
    """Full run. final_only=True skips the CV (its outputs in out/ must already exist)."""
    OUT.mkdir(exist_ok=True)
    ff, gold, pu, plan = load()
    terms = F.active_terms(F.PS_TERMS, ff)
    terms_nw = F.active_terms(F.PS_TERMS, ff, drop=F.WEB_ABLATE)
    masks = F.family_mask_columns(plan, terms)
    fam_of = {t.name: t.family for t in terms + (F.SERVICE_TERM,)}
    log(f"gold labelled pairs {len(gold)} (pos {int(gold.y_S.sum())}); PU rows {len(pu)} "
        f"(pos {int((pu.label == 'positive').sum())}); terms {len(terms)}; masks {masks}")
    if not final_only:
        cv_stage(gold, pu, terms, terms_nw, masks, fam_of)
    final_stage(ff, gold, pu, terms, terms_nw, masks)


def cv_stage(gold, pu, terms, terms_nw, masks, fam_of) -> None:
    oof = pd.concat([run_cv(gold, pu, terms, masks, "fold5", ""),
                     run_cv(gold, pu, terms_nw, masks, "fold5", "_noweb"),
                     run_cv(gold, pu, terms, masks, "state", "")], ignore_index=True)
    oof = oof.assign(p=expit(oof.z))
    keys = gold[["pair_id", "unique_id", "service", "y_S", "version", "operator_public",
                 "gold_cites_list", "leakage_group_id", "state", "fold5"]]
    oof_out = keys.iloc[oof.row.to_numpy()].reset_index(drop=True).join(oof.drop(columns="row"))
    oof_out.to_parquet(OUT / "ps_oof_predictions.parquet", index=False)
    res, thr = evaluate(oof, gold)
    res.to_csv(OUT / "ps_metrics.csv", index=False)
    per_service(oof, gold, ("base_rate", "C1_shift", "C1_platt", "C0_gold", "C3_resid")).to_csv(
        OUT / "ps_metrics_by_service.csv", index=False)
    family_summary(oof, gold, fam_of).to_csv(OUT / "ps_family_contributions.csv", index=False)
    (OUT / "ps_thresholds.json").write_text(json.dumps(thr, indent=1, default=float))


def final_stage(ff, gold, pu, terms, terms_nw, masks) -> None:
    ledgers, edits = final_fit(ff, gold, pu, terms, masks, "")
    led_nw, edits_nw = final_fit(ff, gold, pu, terms_nw, masks, "_noweb")
    ledgers.update(led_nw)
    tables = pd.concat([G.shape_table(l, "P_S", v) for v, l in ledgers.items()], ignore_index=True)
    tables.to_parquet(OUT / "ps_shape_functions.parquet", index=False)
    viol = G.sign_violations(tables)
    final_pu = ledgers["C1_platt"].stages[0]
    meta = dict(
        terms=[t.__dict__ | {"anchor": str(t.anchor)} for t in terms],
        terms_noweb=[t.name for t in terms_nw], masks=masks, ebm_params=G.EBM_PARAMS,
        platt={v: dict(scale=[s.scale for s in l.stages], offset=l.offset)
               for v, l in ledgers.items()},
        clamp_edits_final=edits + edits_nw, sign_violations=len(viol),
        pu_family_counts={f"{a}|{b}": int(n) for (a, b), n in
                          pu.groupby(["label_family", "label"]).size().items()},
        reader_slot_active=any(t.name == "r_reader_p_offers" for t in terms), log=LOG)
    (OUT / "ps_fit_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    for v, l in ledgers.items():
        for st in l.stages:
            (OUT / f"ps_ebm_{v}_{st.prefix}.json").write_text(json.dumps(st.ebm.to_jsonable()))
    assert len(viol) == 0, viol
    score_all(ff, ledgers, ("C1_platt", "C3_resid", "C0_gold"))
    log(f"pu stage intercept {float(final_pu.ebm.intercept_[0]):.4f}; done")
    (OUT / "ps_fit_meta.json").write_text(json.dumps(meta | {"log": LOG}, indent=1, default=str))


def score_all(ff: pd.DataFrame, ledgers: dict[str, G.Ledger], names: tuple[str, ...]) -> None:
    """Final-fit scores and per-term contributions for every (facility, service) pair."""
    for name in names:
        base, contrib = G.contributions(ledgers[name], ff)   # asserts additivity to 1e-9
        z = G.score(ledgers[name], ff)
        out = ff[["unique_id", "service"]].assign(variant=name, z=z, p=expit(z), base=base)
        out = pd.concat([out, contrib.add_prefix("c__")], axis=1)
        out.to_parquet(OUT / f"ps_scores_all_{name}.parquet", index=False)
        log(f"scored {len(out)} pairs with {name}; max additivity gap <= {G.TOL}")


if __name__ == "__main__":
    import sys
    main(final_only="final" in sys.argv[1:])

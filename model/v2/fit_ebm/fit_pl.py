"""Candidate C for P_L (EBM, interactions off) on the facility location labels.

P_E is not fitted: gold y_E has 10 negatives, under the 15 MODEL_SPEC 3.3 requires, so it stays
prior-only. The counts are written to pl_fit_meta.json.

Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python fit_pl.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.model_selection import GroupKFold

import features as F
import glassbox as G
import metrics as M

OUT = Path(__file__).parent / "out"
MIN_NEG_PE = 15


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    ff = F.load_features().drop_duplicates("unique_id").reset_index(drop=True)
    lab = pd.read_parquet(f"{F.LABEL_DIR}/gold_dev_facility.parquet")
    # One facility has a gold row with y_L missing plus a hand-check row with y_L; keep the
    # labelled row so each facility enters once.
    lab = lab.sort_values("y_L", na_position="last").drop_duplicates("unique_id")
    assert not lab.unique_id.duplicated().any()
    lab = lab.sort_index()
    lab = lab.merge(ff, on="unique_id", how="left", suffixes=("", "_ff"), validate="one_to_one")
    return ff, lab


def run_cv(lab: pd.DataFrame, terms: tuple[F.Term, ...], scheme: str, name: str) -> pd.DataFrame:
    folds = ([np.flatnonzero(lab.fold5 == k) for k in range(5)] if scheme == "fold5" else
             [te for _, te in GroupKFold(n_splits=5).split(lab, groups=lab.state)])
    parts = []
    for k, te in enumerate(folds):
        test = lab.iloc[te]
        tr = ~lab.index.isin(te) & ~lab.leakage_group_id.isin(set(test.leakage_group_id))
        if scheme == "state":
            tr &= ~lab.state.isin(set(test.state))
        trn = lab[tr]
        ebm = G.fit_ebm(F.matrix(trn, terms), trn.y_L.to_numpy(int), terms)
        led = G.Ledger((G.Stage("loc", ebm, terms, 1.0),), 0.0)
        base, contrib = G.contributions(led, test)
        df = pd.DataFrame(dict(row=te, variant=name, z=G.score(led, test), base=base))
        parts.append(pd.concat([df, contrib.add_prefix("c__").reset_index(drop=True)], axis=1)
                     .assign(cv=scheme, fold=k))
        if name == "L_ebm":
            parts.append(pd.DataFrame(dict(row=te, variant="base_rate", z=logit(trn.y_L.mean()),
                                           base=logit(trn.y_L.mean()), cv=scheme, fold=k)))
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    ff, lab_all = load()
    lab = lab_all[lab_all.y_L.notna()].reset_index(drop=True)
    terms = F.active_terms(F.PL_TERMS, ff)
    terms_ns = F.active_terms(F.PL_TERMS, ff, drop=F.PL_ABLATE)
    oof = pd.concat([run_cv(lab, terms, cv, "L_ebm") for cv in ("fold5", "state")]
                    + [run_cv(lab, terms_ns, cv, "L_ebm_noselection") for cv in ("fold5", "state")],
                    ignore_index=True)
    oof = oof.assign(p=expit(oof.z))
    keys = lab[["unique_id", "y_L", "src", "operator_public", "leakage_group_id", "state", "fold5"]]
    keys.iloc[oof.row.to_numpy()].reset_index(drop=True).join(oof.drop(columns="row")).to_parquet(
        OUT / "pl_oof_predictions.parquet", index=False)
    subsets = {"all": np.ones(len(lab), bool), "public": (lab.operator_public == 1).to_numpy(),
               "private": (lab.operator_public == 0).to_numpy(),
               "gold_only": (lab.src == "gold_dev").to_numpy()}
    res = []
    y, grp = lab.y_L.to_numpy(), lab.leakage_group_id.to_numpy()
    for cv, d in oof.groupby("cv"):
        P = {v: expit(g.set_index("row").z.sort_index().to_numpy()) for v, g in d.groupby("variant")}
        for s, m in subsets.items():
            if m.sum() >= 5 and 0 < y[m].sum() < m.sum():
                res.append(M.summarize(y[m], {v: p[m] for v, p in P.items()}, grp[m],
                                       ref="base_rate").assign(cv=cv, subset=s))
            else:
                res.append(pd.DataFrame([dict(cv=cv, subset=s, n=int(m.sum()), k=int(y[m].sum()),
                                              model="not_run_one_class")]))
    pd.concat(res, ignore_index=True).to_csv(OUT / "pl_metrics.csv", index=False)

    ledgers = {}
    for name, ts in (("L_ebm", terms), ("L_ebm_noselection", terms_ns)):
        ebm = G.fit_ebm(F.matrix(lab, ts), y.astype(int), ts)
        ledgers[name] = G.Ledger((G.Stage("loc", ebm, ts, 1.0),), 0.0)
        (OUT / f"pl_ebm_{name}.json").write_text(json.dumps(ebm.to_jsonable()))
    tables = pd.concat([G.shape_table(l, "P_L", v) for v, l in ledgers.items()], ignore_index=True)
    tables.to_parquet(OUT / "pl_shape_functions.parquet", index=False)
    viol = G.sign_violations(tables)
    base, contrib = G.contributions(ledgers["L_ebm"], ff)      # asserts additivity to 1e-9
    z = G.score(ledgers["L_ebm"], ff)
    pd.concat([ff[["unique_id"]].assign(variant="L_ebm", z=z, p=expit(z), base=base),
               contrib.add_prefix("c__")], axis=1).to_parquet(OUT / "pl_scores_all.parquet",
                                                             index=False)
    ye = lab_all.y_E
    meta = dict(n_labelled=len(lab), n_neg=int((y == 0).sum()), by_src=lab.groupby("src").y_L
                .agg(["size", "sum"]).astype(int).to_dict(), terms=[t.name for t in terms],
                terms_noselection=[t.name for t in terms_ns], sign_violations=len(viol),
                p_e=dict(fitted=False, n_labelled=int(ye.notna().sum()), n_neg=int((ye == 0).sum()),
                         rule=f"fit only with >= {MIN_NEG_PE} negatives (MODEL_SPEC 3.3)"))
    (OUT / "pl_fit_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    assert len(viol) == 0, viol
    print(json.dumps(meta, indent=1, default=str))


if __name__ == "__main__":
    main()

"""Candidate B fitting core: data assembly, cross-fit masking, PU EM with the c correction, MAP under constraints.

PU likelihood (Elkan and Noto, known c): inside a list's scope P(list positive | x) = c f(x), f = P(offered | x).
EM: an unlabeled row gets the soft target q = (1 - c) f / (1 - c f); a positive keeps y = 1 with its case weight
(match precision x witness value). The M-step is a MAP logistic fit with Gaussian priors (candidate A centres) and the
sign / monotone constraints, solved by the active-set Newton of model/proto/fusion/glm.py (reused unchanged).
Identical PU design rows are merged (soft targets are linear in the log likelihood, so the merge is exact).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

import design as D

sys.path.insert(0, str(D.ROOT / "model/proto/fusion"))
import glm  # noqa: E402  (proto MAP fitter: null_space, _newton)
from fcommon import sigmoid  # noqa: E402

EM_ITERS = 60
EM_TOL = 1e-4
MAX_ROUNDS = 10


@dataclass(frozen=True)
class Data:
    X: np.ndarray          # design, offsets 0 (gold) or 1 (PU family)
    y: np.ndarray          # gold y_S; PU positive share of the merged row (weight of positives / total)
    w: np.ndarray          # gold 1; PU merged weight (positive weights + unlabeled count)
    wpos: np.ndarray       # PU merged positive weight (0 for gold)
    nunl: np.ndarray       # PU merged unlabeled count (0 for gold)
    c: np.ndarray          # label frequency per row (nan for gold)
    is_pu: np.ndarray


def c_table() -> tuple[pd.DataFrame, list]:
    """Chosen c per (family, service), raised to the observed positive rate where SCAR would be violated."""
    c = pd.read_parquet(D.LAB / "c_estimates.parquet")
    c = c[c.used & c.service.ne("ALL")][["label_family", "service", "c", "c_lo", "c_hi", "anchor", "k", "n"]]
    pu = pd.read_parquet(D.LAB / "pu_labels.parquet")
    pu = pu[pu.label.isin(["positive", "unlabeled"])]
    rate = pu.groupby(["label_family", "service"]).label.apply(lambda s: (s == "positive").mean()).rename("pos_rate").reset_index()
    c = c.merge(rate, on=["label_family", "service"], how="left")
    c["c_eff"] = np.maximum(c.c, c.pos_rate)
    raised = c[c.c_eff > c.c][["label_family", "service", "c", "pos_rate"]].to_dict("records")
    return c, raised


def pu_rows(pairs: pd.DataFrame, c: pd.DataFrame) -> pd.DataFrame:
    """PU training rows: families nabh, nmc (not blood_bank), laqshya, eraktkosh; positive or unlabeled only.

    Skipped, as LABELS.md says: MoHFW trauma (c 1/18) and NMC blood_bank (c 0/18) would claim almost every facility
    offers the service; PMNDP has one positive; expired LaQshya rows are neither positive nor unlabeled.
    """
    pu = pd.read_parquet(D.LAB / "pu_labels.parquet")
    pu = pu[pu.label_family.isin(D.PU_FAMILIES) & pu.label.isin(["positive", "unlabeled"])]
    pu = pu[~((pu.label_family == "nmc") & (pu.service == "blood_bank"))]
    pu = pu.merge(c[["label_family", "service", "c_eff"]], on=["label_family", "service"], how="left")
    assert pu.c_eff.notna().all()
    pu = pu[["unique_id", "service", "label_family", "label", "weight", "c_eff", "leakage_group_id", "state", "fold5"]]
    m = pu.merge(pairs, on=["unique_id", "service"], how="left", suffixes=("", "_ff"))
    assert len(m) == len(pu) and m.a_T.notna().all()
    return m


def pu_design(m: pd.DataFrame, terms: list, drop: frozenset) -> np.ndarray:
    """Design for PU rows with cross-fit masking: a list's own columns are zeroed on rows it labels."""
    X = D.service_X(m, terms)
    idx = {t.name: i for i, t in enumerate(terms)}
    fam = m.label_family.to_numpy()
    for f in D.PU_FAMILIES:
        rows = fam == f
        X[rows, idx[f"off@{f}"]] = 1.0
        for t in terms:
            if t.family == "X" and t.source == f:
                X[rows, idx[t.name]] = 0.0
        if f == "nabh":
            for nm in D.NABH_SCOPE_COLS:
                X[rows, idx[nm]] = 0.0
    return zero_cols(X, terms, drop)


def zero_cols(X: np.ndarray, terms: list, drop: frozenset) -> np.ndarray:
    for i, t in enumerate(terms):
        if t.name in drop:
            X[:, i] = 0.0
    return X


def assemble(Xg: np.ndarray, yg: np.ndarray, Xp: np.ndarray, m: pd.DataFrame, pu_scale: float = 1.0) -> Data:
    """Stack gold rows and merged PU rows; pu_scale multiplies every PU case weight."""
    pos = (m.label == "positive").to_numpy()
    wpos = np.where(pos, m.weight.to_numpy(), 0.0) * pu_scale
    nunl = (~pos).astype(float) * pu_scale
    if len(Xp):
        key = pd.DataFrame(Xp).astype(np.int8)
        key["c"] = m.c_eff.to_numpy()
        codes = key.groupby(list(key.columns), sort=False).ngroup().to_numpy()
        ng = codes.max() + 1
        first = np.unique(codes, return_index=True)[1]
        Xu, cu = Xp[first], m.c_eff.to_numpy()[first]
        wp, nu = np.bincount(codes, wpos, ng), np.bincount(codes, nunl, ng)
    else:
        Xu, cu, wp, nu = Xp, np.zeros(0), np.zeros(0), np.zeros(0)
    ng_ = len(yg)
    X = np.vstack([Xg, Xu])
    return Data(X=X, y=np.concatenate([yg, wp / np.maximum(wp + nu, 1e-300)]), w=np.concatenate([np.ones(ng_), wp + nu]),
                wpos=np.concatenate([np.zeros(ng_), wp]), nunl=np.concatenate([np.zeros(ng_), nu]),
                c=np.concatenate([np.full(ng_, np.nan), cu]), is_pu=np.concatenate([np.zeros(ng_, bool), np.ones(len(Xu), bool)]))


def map_fit(X: np.ndarray, y: np.ndarray, w: np.ndarray, mu: np.ndarray, sd: np.ndarray, A: np.ndarray,
            beta0: np.ndarray) -> tuple[np.ndarray, tuple, bool, np.ndarray, np.ndarray]:
    """Active-set MAP (glm.fit with a warm start). Returns beta, active rows, converged, basis N, Hessian H."""
    prec = 1.0 / sd ** 2
    active: list = []
    converged = False
    beta = beta0.copy()
    for rnd in range(1, MAX_ROUNDS + 2):
        N = glm.null_space(A[active]) if active else np.eye(X.shape[1])
        _, beta, H = glm._newton(X, y, w, mu, prec, N, N.T @ beta)
        viol = [i for i in range(A.shape[0]) if i not in active and A[i] @ beta < -1e-9]
        if not viol:
            converged = True
            break
        if rnd > MAX_ROUNDS:
            break
        active += viol
    return beta, tuple(active), converged, N, H


def fit(data: Data, mu: np.ndarray, sd: np.ndarray, A: np.ndarray) -> dict:
    """PU-EM MAP fit. Returns beta and diagnostics."""
    beta = mu.copy()
    hist = []
    for it in range(EM_ITERS):
        y = data.y.copy()
        if data.is_pu.any():
            f = sigmoid(data.X[data.is_pu] @ beta)
            c = data.c[data.is_pu]
            q = (1 - c) * f / (1 - c * f)
            wp, nu = data.wpos[data.is_pu], data.nunl[data.is_pu]
            y[data.is_pu] = (wp + nu * q) / np.maximum(wp + nu, 1e-300)
        new, active, conv, N, H = map_fit(data.X, y, data.w, mu, sd, A, beta)
        step = float(np.max(np.abs(new - beta)))
        beta = new
        hist.append(step)
        if not data.is_pu.any() or step < EM_TOL:
            break
    return dict(beta=beta, active=active, converged=conv, em_iters=it + 1, em_last_step=hist[-1], N=N, H=H)


def laplace_sd(res: dict) -> np.ndarray:
    """Posterior sd over the free directions (active constraints held as equalities)."""
    N, H = res["N"], res["H"]
    cov = N @ np.linalg.inv(N.T @ H @ N) @ N.T
    return np.sqrt(np.clip(np.diag(cov), 0, None))


def contributions(X: np.ndarray, beta: np.ndarray, terms: list) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """base (intercept terms), per-term contributions (non-base, offsets excluded) and z; asserts the identity."""
    is_base = np.array([t.family == "base" for t in terms])
    is_off = np.array([t.family == "offset" for t in terms])
    assert not X[:, is_off].any(), "published rows must carry no PU offset"
    C = X * beta[None, :]
    base = C[:, is_base].sum(axis=1)
    z = X @ beta
    contrib = C[:, ~is_base & ~is_off]
    assert np.max(np.abs(base + contrib.sum(axis=1) - z)) < 1e-9, "additivity broken"
    return base, contrib, z

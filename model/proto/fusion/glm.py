"""Bayesian logistic regression with Gaussian priors and linear sign constraints (numpy only).

MAP by Newton on the penalised, case-weighted log likelihood. Constraints are rows of A with A @ beta >= 0: simple
sign constraints (beta_j >= 0 or <= 0) and composite monotonicity constraints (for example t2 + tb_high >= 0, so a
bucket discount can never make more own evidence lower the score). Active set: fit, add every violated constraint as
an equality (beta then lives in the null space of the active rows; a violated simple sign constraint is exactly
"fixed at 0"), refit, at most 10 rounds. Laplace covariance = N (N' H N)^-1 N' over the free directions.
Posterior draws are Gaussian draws rejected when they break any constraint (a truncated Laplace posterior).
"""
from dataclasses import dataclass

import numpy as np

from fcommon import sigmoid


@dataclass(frozen=True)
class Fit:
    beta: np.ndarray
    cov: np.ndarray
    active: tuple
    basis: np.ndarray       # N: columns span the free directions
    chol: np.ndarray        # Cholesky factor of (N' H N)^-1
    rounds: int
    converged: bool


def null_space(C, tol=1e-10):
    if C.shape[0] == 0:
        return np.eye(C.shape[1])
    _, s, vt = np.linalg.svd(C)
    rank = int((s > tol).sum())
    return vt[rank:].T


def _newton(X, y, w, mu, prec, N, theta, iters=200):
    def obj(b):
        z = X @ b
        ll = np.sum(w * (y * z - np.logaddexp(0, z)))
        return -ll + 0.5 * np.sum(prec * (b - mu) ** 2)

    b = N @ theta
    f = obj(b)
    for _ in range(iters):
        p = sigmoid(X @ b)
        g = X.T @ (w * (p - y)) + prec * (b - mu)
        H = (X * (w * p * (1 - p))[:, None]).T @ X + np.diag(prec)
        gt, Ht = N.T @ g, N.T @ H @ N
        step = np.linalg.solve(Ht, gt)
        t = 1.0
        while True:
            th2 = theta - t * step
            f2 = obj(N @ th2)
            if f2 <= f + 1e-12 or t < 1e-8:
                break
            t /= 2
        theta, b, df = th2, N @ th2, f - f2
        f = f2
        if np.max(np.abs(t * step)) < 1e-10 or abs(df) < 1e-13:
            break
    p = sigmoid(X @ b)
    H = (X * (w * p * (1 - p))[:, None]).T @ X + np.diag(prec)
    return theta, b, H


def fit(X, y, w, mu, sd, A=None, max_rounds=10):
    k = X.shape[1]
    A = np.zeros((0, k)) if A is None else A
    prec = 1.0 / np.asarray(sd, float) ** 2
    mu = np.asarray(mu, float)
    active = []
    converged = False
    for rnd in range(1, max_rounds + 2):
        N = null_space(A[active]) if active else np.eye(k)
        theta, b, H = _newton(X, y, w, mu, prec, N, N.T @ mu)
        viol = [i for i in range(A.shape[0]) if i not in active and A[i] @ b < -1e-9]
        if not viol:
            converged = True
            break
        if rnd > max_rounds:
            break
        active += viol
    Ht = N.T @ H @ N
    Hinv = np.linalg.inv(Ht)
    cov = N @ Hinv @ N.T
    return Fit(beta=b, cov=cov, active=tuple(active), basis=N, chol=np.linalg.cholesky((Hinv + Hinv.T) / 2),
               rounds=rnd, converged=converged)


def draws(f: Fit, A, n=200, seed=20261122, max_tries=200000):
    """n posterior draws that satisfy every constraint (rejection from the Laplace Gaussian). Returns (draws, rate)."""
    rng = np.random.default_rng(seed)
    out, tries, acc = [], 0, 0
    A = np.zeros((0, len(f.beta))) if A is None else A
    while len(out) < n and tries < max_tries:
        z = rng.standard_normal((2000, f.chol.shape[0]))
        b = f.beta[None, :] + (f.basis @ (f.chol @ z.T)).T
        ok = (b @ A.T >= -1e-9).all(axis=1) if A.shape[0] else np.ones(len(b), bool)
        out.extend(b[ok][: n - len(out)])
        tries += 2000
        acc += int(ok.sum())
    return np.array(out), acc / max(tries, 1)


def fit_platt(z, y, w):
    """Affine recalibration z* = a z + c with a >= 0 and a weak prior a ~ N(1, 2^2), c ~ N(0, 2^2)."""
    X = np.column_stack([z, np.ones_like(z)])
    f = fit(X, y, w, mu=[1.0, 0.0], sd=[2.0, 2.0], A=np.array([[1.0, 0.0]]))
    return float(f.beta[0]), float(f.beta[1])


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    X = np.column_stack([np.ones(400), rng.standard_normal(400), rng.standard_normal(400)])
    true = np.array([-0.5, 1.0, -0.8])
    y = (rng.random(400) < sigmoid(X @ true)).astype(float)
    w = np.ones(400)
    f0 = fit(X, y, w, mu=np.zeros(3), sd=np.full(3, 10.0))
    assert np.allclose(f0.beta, true, atol=0.35), f0.beta
    # constraint beta_2 >= 0 must bind (true value is negative): fixed at 0
    A = np.array([[0.0, 0.0, 1.0]])
    f1 = fit(X, y, w, mu=np.zeros(3), sd=np.full(3, 10.0), A=A)
    assert abs(f1.beta[2]) < 1e-9 and f1.active == (0,), f1
    # composite constraint beta_1 + beta_2 >= 0.0 with prior pulling the sum negative
    A2 = np.array([[0.0, 1.0, 1.0]])
    f2 = fit(X, y, w, mu=[0, 0, -5], sd=[10, 10, 0.1], A=A2)
    assert f2.beta[1] + f2.beta[2] >= -1e-9
    d, rate = draws(f1, A, n=200)
    assert d.shape == (200, 3) and (d[:, 2] >= -1e-9).all()
    a, c = fit_platt(X @ f0.beta, y, w)
    assert 0.6 < a < 1.6, a
    print("glm ok", np.round(f0.beta, 3), "draw acceptance", round(rate, 3))

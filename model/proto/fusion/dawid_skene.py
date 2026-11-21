"""M2: semi-supervised hierarchical Dawid-Skene over all 69,713 pairs (spec 5.3.1), numpy only.

P(Y=1) = sigmoid(eta_s); P(v_k = v | Y=c, bucket g, service s) = theta[k,s,g,c](v) for families T, C, N, S, P.
E-step: posterior q_i, clamped to the label for checked dev gold pairs (test pairs are never clamped).
M-step: theta = (counts + 20 m) / (total + 20), m = the same estimate pooled over services (Laplace +1).
PAVA (count weighted) makes the reported weight of evidence w(v) = log theta1(v) - log theta0(v) monotone; it is
applied to the outputs (prior means and reliability rows), not inside EM.
Stop at max |delta theta| < 1e-4 or 200 iterations; 10 restarts, keep the highest log likelihood.
"""
import numpy as np
import pandas as pd

from fcommon import BUCKETS, SERVICES, sigmoid

FAMILIES = {"T": 6, "C": 3, "N": 2, "S": 2, "P": 3}
DIRECTION = {"T": +1, "C": -1, "N": -1, "S": -1, "P": +1}
PSEUDO = 20.0


def pava(y, w, increasing=True):
    y, w = list(map(float, y)), list(map(float, w))
    if not increasing:
        return [-v for v in pava([-v for v in y], w, True)]
    blocks = [[y[i], w[i], 1] for i in range(len(y))]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0] + 1e-12:
            a, b = blocks[i], blocks[i + 1]
            tw = a[1] + b[1]
            blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / tw if tw > 0 else (a[0] + b[0]) / 2, tw, a[2] + b[2]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for v, _, n in blocks:
        out += [v] * n
    return out


def _arrays(pf):
    s = pf.service.map({k: i for i, k in enumerate(SERVICES)}).to_numpy()
    g = pf.bucket.map({k: i for i, k in enumerate(BUCKETS)}).to_numpy()
    V = {k: np.clip(pf[k].to_numpy().astype(int), 0, n - 1) for k, n in FAMILIES.items()}
    return s, g, V


def _mstep(q, s, g, V):
    th = {}
    for k, nv in FAMILIES.items():
        cnt = np.zeros((len(SERVICES), len(BUCKETS), 2, nv))
        for c, r in ((1, q), (0, 1 - q)):
            np.add.at(cnt, (s, g, np.full(len(q), c), V[k]), r)
        pooled = cnt.sum(axis=0) + 1.0
        m = pooled / pooled.sum(axis=-1, keepdims=True)
        th[k] = (cnt + PSEUDO * m[None]) / (cnt.sum(axis=-1, keepdims=True) + PSEUDO)
        th[k + "_cnt"] = cnt
    eta = np.array([np.log((q[s == i].sum() + 0.5) / ((1 - q[s == i]).sum() + 0.5)) for i in range(len(SERVICES))])
    return th, eta


def _loglik_terms(th, eta, s, g, V):
    l1 = np.log(sigmoid(eta[s]))
    l0 = np.log(sigmoid(-eta[s]))
    for k in FAMILIES:
        l1 = l1 + np.log(th[k][s, g, 1, V[k]])
        l0 = l0 + np.log(th[k][s, g, 0, V[k]])
    return l1, l0


def run(pf: pd.DataFrame, clamp: dict, restarts=10, seed=20261122):
    """clamp: {row index in pf: 0/1}. Returns dict with theta, eta, q, loglik, iterations."""
    s, g, V = _arrays(pf)
    ci = np.array(list(clamp.keys()), int)
    cy = np.array(list(clamp.values()), float)
    rng = np.random.default_rng(seed)
    best = None
    for r in range(restarts):
        q = np.clip(0.15 + 0.6 * (V["T"] >= 2) + 0.2 * rng.standard_normal(len(pf)), 0.01, 0.99)
        q[ci] = cy
        th, eta = _mstep(q, s, g, V)
        for it in range(200):
            l1, l0 = _loglik_terms(th, eta, s, g, V)
            q = sigmoid(l1 - l0)
            q[ci] = cy
            th2, eta = _mstep(q, s, g, V)
            delta = max(np.abs(th2[k] - th[k]).max() for k in FAMILIES)
            th = th2
            if delta < 1e-4:
                break
        l1, l0 = _loglik_terms(th, eta, s, g, V)
        free = np.ones(len(pf), bool)
        free[ci] = False
        ll = np.logaddexp(l1, l0)[free].sum() + (cy * l1[ci] + (1 - cy) * l0[ci]).sum()
        if best is None or ll > best["loglik"]:
            best = dict(theta=th, eta=eta, q=q, loglik=float(ll), iterations=it + 1, restart=r)
    return best


def woe_tables(res, pf):
    """Pooled-over-services weight of evidence per (family, bucket or '*', value) with PAVA and an approximate sd."""
    out = {}
    for k, nv in FAMILIES.items():
        cnt = res["theta"][k + "_cnt"]  # (s, g, c, v) posterior counts
        for gi, gname in list(enumerate(BUCKETS)) + [(None, "*")]:
            c = cnt.sum(axis=0) if gi is None else cnt[:, gi]
            c = c.sum(axis=0) if gi is None else c.sum(axis=0)  # -> (c, v)
            n1, n0 = c[1] + 0.5, c[0] + 0.5
            w = np.log(n1 / n1.sum()) - np.log(n0 / n0.sum())
            sd = np.sqrt(1 / n1 + 1 / n0)
            wm = pava(w, n1 + n0, increasing=DIRECTION[k] > 0)
            out[(k, gname)] = dict(w_raw=w, w=np.array(wm), sd=sd, n1=c[1], n0=c[0])
    return out


def m2_priors(res, pf):
    """Prior means for the service head's evidence terms (others fall back to M0)."""
    W = woe_tables(res, pf)
    pri = {}

    def step(k, g, v):
        a = W[(k, g)]
        return float(a["w"][v] - a["w"][v - 1]), float(max(0.5, 2 * np.sqrt(a["sd"][v] ** 2 + a["sd"][v - 1] ** 2)))

    for v in range(1, 6):
        pri[f"t{v}"] = step("T", "low", v)
    lowT = W[("T", "low")]
    for g in ("mid", "high"):
        a = W[("T", g)]
        n1, n0 = a["n1"], a["n0"]
        # WOE of T >= 2 relative to T = 0 inside bucket g, minus the same in the low bucket
        def rel(t):
            m1, m0 = t["n1"] + 0.5, t["n0"] + 0.5
            return np.log(m1[2:].sum() / m1[0]) - np.log(m0[2:].sum() / m0[0])
        d = float(rel(a) - rel(lowT))
        sd = float(max(0.5, 2 * np.sqrt(1 / (n1[2:].sum() + 0.5) + 1 / (n0[2:].sum() + 0.5) + 1 / (lowT["n1"][2:].sum() + 0.5)
                                       + 1 / (lowT["n0"][2:].sum() + 0.5))))
        pri[f"tb_{g}"] = (d, sd)
    pri["c1"], pri["c2"] = step("C", "*", 1), step("C", "*", 2)
    pri["n1"], pri["s1"] = step("N", "*", 1), step("S", "*", 1)
    pri["p1"], pri["p2"] = step("P", "*", 1), step("P", "*", 2)
    q, T = res["q"], pf["T"].to_numpy()
    for i, s in enumerate(SERVICES):
        m = (pf.service.to_numpy() == s) & (T == 0) & (pf.bucket.to_numpy() == "low")
        r = (q[m].sum() + 0.5) / (m.sum() + 1)
        pri[f"b_{s}"] = (float(np.log(r / (1 - r))), 1.5)
    return pri, W


def reliability_rows(res, pf):
    """Agreement columns of reliability.parquet: family x value x bucket x service."""
    rows = []
    for k, nv in FAMILIES.items():
        th, cnt = res["theta"][k], res["theta"][k + "_cnt"]
        for si, s in enumerate(SERVICES):
            for gi, g in enumerate(BUCKETS):
                for v in range(nv):
                    rows.append(dict(family=k, value=v, bucket=g, service=s, n_all=float(cnt[si, gi, :, v].sum()),
                                     agree_p_v_offers=float(th[si, gi, 1, v]), agree_p_v_not=float(th[si, gi, 0, v]),
                                     agree_woe=float(np.log(th[si, gi, 1, v] / th[si, gi, 0, v]))))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    assert pava([1, 3, 2, 4], [1, 1, 1, 1]) == [1, 2.5, 2.5, 4]
    assert pava([3, 1], [1, 1], increasing=False) == [3, 1]
    print("pava ok")

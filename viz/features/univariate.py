"""Coverage, univariate association, redundancy for every candidate feature.

Gold: DEV split only (labels.gold_dev). AUROC = P(feature higher on a confirmed pair than on a
not-confirmed pair), ties count half, pooled over services (the dev set is too small to stratify).
95% intervals: cluster bootstrap over gold split groups (2,000 resamples). IPW AUROC reweights by
inverse inclusion probability (point estimate and the same bootstrap).
PU: AUROC within service (only pairs of the same service are compared, because list base rates
differ by service), 95% interval from a bootstrap over states (1,000 resamples for nabh_codes,
300 for official_lists), plus AUROC in each of 5 held-out state folds (GroupKFold by state).
Redundancy: Spearman correlation on all 69,713 pairs (ranks of each column, pairwise-complete),
average-linkage clusters on 1 - |rho| cut at 0.3 (|rho| >= 0.7 joins a cluster).

Writes out/univariate.parquet, out/spearman.parquet, out/univariate_meta.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata
from sklearn.model_selection import GroupKFold

import catalogue_meta as M
import labels as L

OUT = Path(__file__).parent / "out"
RNG = np.random.default_rng(20261121)
B_DEV, B_NABH, B_LISTS = 2000, 1000, 300
MIN_MINORITY = 5  # fewer feature-positive (or distinct-value) labelled pairs than this -> "too small"


def auc(x, y, w=None):
    """Mann-Whitney AUROC with ties = 1/2; optional case weights (O(n^2), small n only)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    pos, neg = x[y == 1], x[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    if w is None:
        r = rankdata(np.concatenate([pos, neg]))
        return (r[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))
    w = np.asarray(w, float)
    wp, wn = w[y == 1], w[y == 0]
    cmp = (pos[:, None] > neg[None, :]) + 0.5 * (pos[:, None] == neg[None, :])
    return float((wp[:, None] * wn[None, :] * cmp).sum() / (wp.sum() * wn.sum()))


def auc_strat(x, y, s):
    """AUROC comparing only pairs within the same stratum s (pooled concordance)."""
    num = den = 0.0
    for v in np.unique(s):
        m = s == v
        pos, neg = y[m] == 1, y[m] == 0
        n1, n0 = pos.sum(), neg.sum()
        if n1 == 0 or n0 == 0:
            continue
        r = rankdata(x[m])
        num += r[pos].sum() - n1 * (n1 + 1) / 2
        den += n1 * n0
    return num / den if den else np.nan


def minority(xs) -> int:
    """Labelled pairs NOT at the feature's most common value (for a binary flag: the rarer value)."""
    xs = np.asarray(xs, float)
    xs = xs[~np.isnan(xs)]
    if len(xs) == 0:
        return 0
    _, c = np.unique(xs, return_counts=True)
    return int(len(xs) - c.max())


def cluster_boot(groups, b):
    """Yield row-index arrays for a cluster bootstrap over the unique values of groups."""
    g = pd.Series(np.arange(len(groups))).groupby(np.asarray(groups)).apply(np.array).tolist()
    for _ in range(b):
        pick = RNG.integers(0, len(g), len(g))
        yield np.concatenate([g[i] for i in pick])


def dev_stats(dev: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    d = dev[dev.y.notna()].reset_index(drop=True)
    boots = list(cluster_boot(d.group.values, B_DEV))
    rows = []
    for f in feats:
        x, y, w = d[f].values.astype(float), d.y.values, d.ipw.values
        ok = ~np.isnan(x)
        r = dict(feature=f, dev_n=int(ok.sum()), dev_pos=int(y[ok].sum()))
        xs, ys = x[ok], y[ok]
        vals = np.unique(xs)
        r["dev_minority"] = minority(xs)
        if len(vals) < 2 or ys.min() == ys.max():
            r.update(dev_auc=np.nan, dev_auc_lo=np.nan, dev_auc_hi=np.nan, dev_auc_ipw=np.nan)
        else:
            r["dev_auc"] = auc(xs, ys)
            r["dev_auc_ipw"] = auc(xs, ys, w[ok])
            bs = []
            for idx in boots:
                xi, yi = x[idx], y[idx]
                k = ~np.isnan(xi)
                bs.append(auc(xi[k], yi[k]))
            r["dev_auc_lo"], r["dev_auc_hi"] = np.nanpercentile(bs, [2.5, 97.5])
        if set(vals) <= {0.0, 1.0} and len(vals) == 2:
            k1, n1 = int(ys[xs == 1].sum()), int((xs == 1).sum())
            k0, n0 = int(ys[xs == 0].sum()), int((xs == 0).sum())
            r.update(dev_k1=k1, dev_n1=n1, dev_k0=k0, dev_n0=n0, dev_rate_diff=k1 / n1 - k0 / n0)
            bs = []
            for idx in boots:
                xi, yi = x[idx], y[idx]
                a, b = yi[xi == 1], yi[xi == 0]
                if len(a) and len(b):
                    bs.append(a.mean() - b.mean())
            r["dev_rd_lo"], r["dev_rd_hi"] = np.percentile(bs, [2.5, 97.5])
        r["dev_too_small"] = bool(r["dev_minority"] < MIN_MINORITY or ys.sum() < MIN_MINORITY)
        rows.append(r)
    return pd.DataFrame(rows)


def dev_location_stats(dev: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    d = dev[dev.label_location.isin(["yes", "no"])].drop_duplicates("unique_id").reset_index(drop=True)
    d["yl"] = (d.label_location == "yes").astype(float)
    boots = list(cluster_boot(d.group.values, B_DEV))
    rows = []
    for f in feats:
        x, y = d[f].values.astype(float), d.yl.values
        ok = ~np.isnan(x)
        r = dict(feature=f, loc_n=int(ok.sum()), loc_no=int((y[ok] == 0).sum()))
        if len(np.unique(x[ok])) < 2:
            r.update(loc_auc=np.nan, loc_auc_lo=np.nan, loc_auc_hi=np.nan)
        else:
            r["loc_auc"] = auc(x[ok], y[ok])
            bs = []
            for idx in boots:
                xi, yi = x[idx], y[idx]
                k = ~np.isnan(xi)
                bs.append(auc(xi[k], yi[k]))
            r["loc_auc_lo"], r["loc_auc_hi"] = np.nanpercentile(bs, [2.5, 97.5])
        rows.append(r)
    return pd.DataFrame(rows)


def pu_stats(d: pd.DataFrame, ycol: str, feats: list[str], b: int, prefix: str) -> pd.DataFrame:
    d = d[d[ycol].notna()].reset_index(drop=True)
    y, s, st = d[ycol].values, d.service.values, d.state.fillna("unknown").values
    boots = list(cluster_boot(st, b))
    folds = list(GroupKFold(n_splits=5).split(d, groups=st))
    rows = []
    for f in feats:
        x = d[f].values.astype(float)
        ok = ~np.isnan(x)
        r = {"feature": f, f"{prefix}_n": int(ok.sum()), f"{prefix}_pos": int(y[ok].sum())}
        if len(np.unique(x[ok])) < 2 or leak_of(f, prefix) == "direct":
            r.update({f"{prefix}_auc": np.nan, f"{prefix}_auc_lo": np.nan, f"{prefix}_auc_hi": np.nan,
                      f"{prefix}_fold_min": np.nan, f"{prefix}_fold_max": np.nan})
            rows.append(r)
            continue
        r[f"{prefix}_auc"] = auc_strat(x[ok], y[ok], s[ok])
        bs = []
        for idx in boots:
            xi = x[idx]
            k = ~np.isnan(xi)
            bs.append(auc_strat(xi[k], y[idx][k], s[idx][k]))
        r[f"{prefix}_auc_lo"], r[f"{prefix}_auc_hi"] = np.nanpercentile(bs, [2.5, 97.5])
        fa = [auc_strat(x[te][ok[te]], y[te][ok[te]], s[te][ok[te]]) for _, te in folds]
        r[f"{prefix}_fold_min"], r[f"{prefix}_fold_max"] = np.nanmin(fa), np.nanmax(fa)
        rows.append(r)
    return pd.DataFrame(rows)


def leak_of(f: str, prefix: str) -> str:
    return M.leakage(f)["nabh_codes" if prefix == "nabh" else "official_lists"]


def redundancy(feat: pd.DataFrame, feats: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = feat[feats].rank()
    rho = r.corr(min_periods=500)
    a = rho.abs().fillna(0).values.copy()
    np.fill_diagonal(a, 1)
    dist = squareform(1 - a, checks=False)
    Z = linkage(dist, "average")
    cl = fcluster(Z, t=0.3, criterion="distance")
    off = rho.abs().where(~np.eye(len(feats), dtype=bool))
    out = pd.DataFrame({"feature": feats, "cluster": cl,
                        "max_abs_rho": off.max().values, "most_correlated_with": off.fillna(-1).idxmax().values})
    order = pd.Series(feats)[pd.Series(range(len(feats))).iloc[__import__("scipy").cluster.hierarchy.leaves_list(Z)]].tolist()
    rho = rho.loc[order, order]
    return out, rho


def main():
    feat = pd.read_parquet(OUT / "features_pairs.parquet")
    feats = [c for c in feat.columns if c in M.META]
    dev = L.gold_dev().merge(feat, on=["unique_id", "service"], how="left")
    assert dev[feats[0]].notna().all(), "every dev pair must join to a feature row"
    pu = feat.merge(L.pu_labels(feat).drop(columns=["unique_id", "service"]), left_index=True, right_index=True)
    cov = pd.DataFrame({"feature": feats,
                        "coverage": [feat[f].notna().mean() for f in feats],
                        "nonzero_share": [(feat[f].fillna(0) != 0).mean() for f in feats],
                        "n_nonzero": [int((feat[f].fillna(0) != 0).sum()) for f in feats]})
    for s in sorted(feat.service.unique()):
        m = feat.service == s
        cov[f"cov_{s}"] = [feat.loc[m, f].notna().mean() for f in feats]
        cov[f"nz_{s}"] = [(feat.loc[m, f].fillna(0) != 0).mean() for f in feats]
    def cached(name, fn):
        # ponytail: cache per stage so a late crash does not redo 10 min of bootstraps; delete out/cache to recompute
        p = OUT / "cache" / f"{name}.parquet"
        if p.exists():
            return pd.read_parquet(p)
        p.parent.mkdir(exist_ok=True)
        r = fn()
        r.to_parquet(p, index=False)
        return r
    ds = cached("dev", lambda: dev_stats(dev, feats))
    ls = cached("loc", lambda: dev_location_stats(dev, feats))
    dv = dev[dev.y.notna()]
    ds["dev_minority"] = [minority(dv[f]) for f in ds.feature]
    ds["dev_too_small"] = (ds.dev_minority < MIN_MINORITY) | (ds.dev_pos < MIN_MINORITY)
    pn = cached("pu_nabh", lambda: pu_stats(pu, "pu_nabh", feats, B_NABH, "nabh"))
    pl = cached("pu_lists", lambda: pu_stats(pu, "pu_lists", feats, B_LISTS, "lists"))
    print("redundancy ..."); red, rho = redundancy(feat, feats)
    u = cov.merge(ds, on="feature").merge(ls, on="feature").merge(pn, on="feature").merge(pl, on="feature").merge(red, on="feature")
    for k in ["gold_web_check", "nabh_codes", "official_lists"]:
        u[f"leak_{k}"] = [M.leakage(f)[k] for f in u.feature]
    u.to_parquet(OUT / "univariate.parquet", index=False)
    rho.to_parquet(OUT / "spearman.parquet")
    meta = dict(
        dev_pairs=int(len(dev)), dev_searched=int(dev.y.notna().sum()), dev_confirmed=int(dev.y.sum()),
        dev_location_facilities=int(dev[dev.label_location.isin(["yes", "no"])].unique_id.nunique()),
        dev_location_no=int(dev[dev.label_location.eq("no")].drop_duplicates("unique_id").shape[0]),
        pu_nabh_pairs=int(pu.pu_nabh.notna().sum()), pu_nabh_pos=int(pu.pu_nabh.sum()),
        pu_nabh_pos_by_service=pu[pu.pu_nabh.notna()].groupby("service").pu_nabh.agg(["sum", "count"]).astype(int).to_dict("index"),
        pu_lists_pos=int(pu.pu_lists.sum()),
        pu_lists_pos_by_service=pu.groupby("service").pu_lists.sum().astype(int).to_dict(),
        n_states_nabh=int(pu[pu.pu_nabh.notna()].state.nunique()), n_states_all=int(pu.state.nunique()),
        evidence_overlap=L.evidence_overlap(dev),
        bootstrap=dict(dev=B_DEV, nabh=B_NABH, lists=B_LISTS), min_minority=MIN_MINORITY)
    (OUT / "univariate_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    print(json.dumps(meta, indent=1, default=str)[:3000])
    show = u[["feature", "coverage", "dev_n", "dev_auc", "dev_auc_lo", "dev_auc_hi", "dev_too_small", "loc_auc",
              "nabh_auc", "nabh_auc_lo", "nabh_auc_hi", "lists_auc", "cluster"]]
    with pd.option_context("display.width", 250, "display.max_rows", 200):
        print(show.round(3).to_string())


if __name__ == "__main__":
    main()

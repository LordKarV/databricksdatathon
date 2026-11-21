"""Step 5: Bayesian truth discovery over sources (registrable domains) and data points.

Model (one-coin Dawid-Skene with record-level attribution):
- Each source s has reliability rho_s = P(a data point it supplied is true).
- A record's data point d came from one of the record's sources, but we do not know which. Its attribution
  weights w_sd come from the URL kind and class, per data-point profile (WEIGHTS below), summed over the
  record's URLs in that domain and normalised to 1. Where the Goal 3 page check found the claim text on a
  page, d is attributed to that page's domain only; where a fetched page did not contain it, that domain is
  dropped from d's weights.
- Source support of d: sigma_d = sum_s w_sd rho_s.
- Truth of d given evidence and sources (naive Bayes, sources and evidence assumed independent):
      logit P(d true) = logit q_ev(d) + GAMMA * (logit sigma_d - logit mean_sigma(type))
  q_ev is the evidence-only estimate from s4 (hand-check + gold dev). Average sources leave q_ev unchanged.
  Gold DEV verdicts are fixed at 0.97 / 0.03; gold TEST verdicts are ignored here (held out).
- M-step (credit and blame): for attribution group g (a record and profile) with expected true mass T_g and
  false mass F_g (sums of strength * q over its data points), every source of the record shares them by weight:
      credit_s += T_g * w_sg      blame_s += F_g * w_sg
  (Splitting by w * rho, the full EM responsibility, was tried first and is not identifiable here: a source
  present in nearly every record, such as facebook.com, absorbed all credit and went to 0.999.)
  rho_s = (alpha_c + credit_s) / (KAPPA + credit_s + blame_s), with a Beta prior per source class c:
  alpha_c = KAPPA m_c, beta_c = KAPPA (1 - m_c), m_c = (1 + class credit) / (2 + class credit + class blame).
  KAPPA = 10 pseudo data points shrinks domains seen in few records toward their class.
- Iterate until max |delta rho| < 1e-6.
Writes _work/fit_domains.parquet, _work/fit_groups.parquet, _work/dp_fit.parquet, _work/s5_stats.json.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ss_common import OUT, WORK

KAPPA = 10.0
GAMMA = 1.0
TOL = 1e-6
MAX_ITER = 500
PROFILE = {"location": "identity", "existence": "identity", "service_claim": "service",
           "claim_attribution": "attribution", "phone": "contact", "email": "contact"}
KIND_W = {"identity": {"about": 1.0, "list": 0.5, "unverified": 0.3},
          "service": {"about": 1.0, "list": 0.5, "unverified": 0.3},
          "attribution": {"about": 0.7, "list": 2.0, "unverified": 1.0},
          "contact": {"about": 1.0, "list": 0.5, "unverified": 0.3}}
WEIGHTS = {  # class multipliers per profile; unlisted classes = 1.0
    "identity": {"official": 2, "official_like": 2, "government": 2, "maps_geo": 1.5, "social": 0.7, "research": 0.5,
                 "news": 0.5, "docs_repo": 0.5, "education": 0.7, "wikipedia": 0.7, "crowdfunding_ngo": 0.7},
    "service": {"official": 1.5, "official_like": 1.5, "government": 1.5, "research": 1.2, "social": 0.7,
                "maps_geo": 0.3, "business_dir": 0.7},
    "attribution": {"research": 2, "docs_repo": 1.5, "news": 1.5, "insurance_scheme": 1.5, "wikipedia": 1.5,
                    "official": 0.7, "official_like": 0.7, "maps_geo": 0.3, "social": 0.7},
    "contact": {"health_aggregator": 2, "business_dir": 2, "maps_geo": 1.5, "official": 1.5, "official_like": 1.5,
                "research": 0.2, "news": 0.3, "docs_repo": 0.3, "wikipedia": 0.2, "education": 0.5},
}
GOLD_TRUE, GOLD_FALSE = 0.97, 0.03
EPS = 1e-4


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def expit(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def record_edges(u: pd.DataFrame) -> pd.DataFrame:
    """(profile, unique_id, domain, w): attribution weight of each domain in each record, per profile."""
    out = []
    for prof in KIND_W:
        w = u.url_kind.map(KIND_W[prof]) * u.source_class.map(lambda c, p=prof: WEIGHTS[p].get(c, 1.0))
        e = u.assign(w=w).groupby(["unique_id", "domain"], as_index=False).w.sum()
        out.append(e.assign(profile=prof, group="rec:" + prof + ":" + e.unique_id))
    return pd.concat(out, ignore_index=True)


def page_overrides(dp: pd.DataFrame, edges: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Per-claim attribution from the Goal 3 page check. Returns extra edges and dp_id -> group."""
    pc_path = OUT / "source_page_checks.parquet"
    if not pc_path.exists():
        return edges.iloc[:0], {}
    pc = pd.read_parquet(pc_path)
    pc = pc[pc.claim_id.notna() & pc.fetch_status.str.startswith("ok")]
    sup = pc[pc.supported].groupby("claim_id").domain.agg(set).to_dict()
    nos = pc[~pc.supported & ~pc.token_supported].groupby("claim_id").domain.agg(set).to_dict()
    rec_att = {k: g for k, g in edges[edges.profile == "attribution"].groupby("unique_id")}
    extra, assign = [], {}
    sent = dp[dp.dp_type == "claim_attribution"].set_index("claim_id")
    for cid in set(sup) | set(nos):
        if cid not in sent.index:
            continue
        r = sent.loc[cid]
        grp = "pc:" + cid
        if cid in sup:
            e = pd.DataFrame({"domain": sorted(sup[cid]), "w": 1.0})
        else:
            e = rec_att[r.unique_id][["domain", "w"]]
            e = e[~e.domain.isin(nos[cid])]
            if e.empty:
                continue
        extra.append(e.assign(unique_id=r.unique_id, profile="attribution", group=grp))
        assign[r.dp_id] = grp
    # service claims whose cited sentence was found on a page are attributed to that page's domain
    svc = dp[(dp.dp_type == "service_claim") & dp.cited_claim_ids.notna()]
    for dpid, uid, cids in zip(svc.dp_id, svc.unique_id, svc.cited_claim_ids):
        doms = set().union(*[sup.get(c, set()) for c in cids.split("|") if c])
        if doms:
            extra.append(pd.DataFrame({"domain": sorted(doms), "w": 1.0, "unique_id": uid, "profile": "service", "group": "pcs:" + dpid}))
            assign[dpid] = "pcs:" + dpid
    return (pd.concat(extra, ignore_index=True) if extra else edges.iloc[:0]), assign


def fit(dp: pd.DataFrame, edges: pd.DataFrame, dom_class: pd.Series) -> dict:
    groups = pd.Index(edges.group.unique())
    domains = pd.Index(dom_class.index)
    eg = groups.get_indexer(edges.group)
    es = domains.get_indexer(edges.domain)
    ew = edges.w.to_numpy(float)
    ew = ew / np.bincount(eg, weights=ew, minlength=len(groups))[eg]  # normalise per group
    classes = pd.Index(sorted(dom_class.unique()))
    sc = classes.get_indexer(dom_class.to_numpy())

    dg = groups.get_indexer(dp.group)
    assert (dg >= 0).all(), "every record has at least one source URL"
    has_src = dg >= 0
    fixed = dp.fit_fixed_q.to_numpy(float)
    is_fixed = ~np.isnan(fixed)
    lq = logit(dp.q_ev.to_numpy(float))
    stren = dp.fit_strength.to_numpy(float)
    types = pd.Index(sorted(dp.dp_type.unique()))
    dt = types.get_indexer(dp.dp_type)

    rho = np.full(len(domains), 0.7)
    hist = []
    for it in range(MAX_ITER):
        sigma = np.bincount(eg, weights=ew * rho[es], minlength=len(groups))
        sig_d = np.where(has_src, sigma[np.clip(dg, 0, None)], np.nan)
        lsig = logit(sig_d)
        mean_l = np.array([np.nanmean(lsig[(dt == t) & has_src]) if ((dt == t) & has_src).any() else 0.0 for t in range(len(types))])
        q = np.where(is_fixed, fixed, expit(lq + GAMMA * np.where(has_src, lsig - mean_l[dt], 0.0)))
        use = has_src & (stren > 0)
        T = np.bincount(dg[use], weights=stren[use] * q[use], minlength=len(groups))
        F = np.bincount(dg[use], weights=stren[use] * (1 - q[use]), minlength=len(groups))
        credit = np.bincount(es, weights=T[eg] * ew, minlength=len(domains))
        blame = np.bincount(es, weights=F[eg] * ew, minlength=len(domains))
        cc = np.bincount(sc, weights=credit, minlength=len(classes))
        cb = np.bincount(sc, weights=blame, minlength=len(classes))
        m_c = (1 + cc) / (2 + cc + cb)
        new = (KAPPA * m_c[sc] + credit) / (KAPPA + credit + blame)
        delta = float(np.abs(new - rho).max())
        rho = new
        hist.append(delta)
        if delta < TOL:
            break
    return dict(rho=rho, credit=credit, blame=blame, m_c=m_c, classes=classes, domains=domains, sc=sc, groups=groups,
                sigma=sigma, eg=eg, es=es, ew=ew, q=q, sig_d=sig_d, mean_l=mean_l, types=types, iters=it + 1, hist=hist)


def blame_by_type(dp: pd.DataFrame, res: dict) -> pd.DataFrame:
    """Final credit/blame per (domain, dp_type), for the plain-English reason string."""
    dg = res["groups"].get_indexer(dp.group)
    rows = []
    for t in res["types"]:
        m = (dp.dp_type.to_numpy() == t) & (dg >= 0) & (dp.fit_strength.to_numpy() > 0)
        T = np.bincount(dg[m], weights=dp.fit_strength.to_numpy()[m] * res["q"][m], minlength=len(res["groups"]))
        F = np.bincount(dg[m], weights=dp.fit_strength.to_numpy()[m] * (1 - res["q"][m]), minlength=len(res["groups"]))
        eg, es, ew = res["eg"], res["es"], res["ew"]
        cr = np.bincount(es, weights=T[eg] * ew, minlength=len(res["domains"]))
        bl = np.bincount(es, weights=F[eg] * ew, minlength=len(res["domains"]))
        rows.append(pd.DataFrame({"domain": res["domains"], "dp_type": t, "credit": cr, "blame": bl}))
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    u = pd.read_parquet(WORK / "record_urls.parquet")
    dp = pd.read_parquet(WORK / "datapoints.parquet")
    dom_class = u.groupby("domain").source_class.agg(lambda s: s.value_counts().index[0])
    edges = record_edges(u)
    extra, assign = page_overrides(dp, edges)
    edges = pd.concat([edges, extra], ignore_index=True)
    dp["group"] = "rec:" + dp.dp_type.map(PROFILE) + ":" + dp.unique_id
    dp["group"] = dp.dp_id.map(assign).fillna(dp.group)
    # fitting labels: gold DEV fixed; TEST gold hidden (falls back to q_ev); deterministic placeholder email fixed
    dev = (dp.gold_split == "dev") & dp.gold_true.notna()
    dp["fit_fixed_q"] = np.where(dev, np.where(dp.gold_true.fillna(False).astype(bool), GOLD_TRUE, GOLD_FALSE), np.nan)
    dp.loc[dp.rule == "EMAIL_PLACEHOLDER", "fit_fixed_q"] = 0.01
    dp["fit_strength"] = np.where(dev, 1.0, dp.strength)
    res = fit(dp, edges, dom_class)

    # domain posterior and 90% interval (Monte Carlo from the Beta posterior; seed fixed)
    a = KAPPA * res["m_c"][res["sc"]] + res["credit"]
    b = KAPPA * (1 - res["m_c"][res["sc"]]) + res["blame"]
    rng = np.random.default_rng(20261121)
    lo, hi = np.empty(len(a)), np.empty(len(a))
    for i in range(0, len(a), 500):
        draws = rng.beta(a[i:i + 500, None], b[i:i + 500, None], size=(len(a[i:i + 500]), 4000))
        lo[i:i + 500], hi[i:i + 500] = np.quantile(draws, [0.05, 0.95], axis=1)
    fd = pd.DataFrame({"domain": res["domains"], "source_class": dom_class.to_numpy(), "alpha": a, "beta": b,
                       "reliability": a / (a + b), "ci05": lo, "ci95": hi, "credit": res["credit"], "blame": res["blame"],
                       "class_prior_mean": res["m_c"][res["sc"]]})
    fd.to_parquet(WORK / "fit_domains.parquet", index=False)
    blame_by_type(dp, res).to_parquet(WORK / "fit_blame_by_type.parquet", index=False)
    # per data point: source support, its logit variance (independent domains), and the fitted q
    var_s = 1 / a + 1 / b
    gvar = np.bincount(res["eg"], weights=res["ew"] ** 2 * var_s[res["es"]], minlength=len(res["groups"]))
    dg = res["groups"].get_indexer(dp.group)
    dp["source_support"] = res["sig_d"]
    dp["source_logit_shift"] = np.where(dg >= 0, logit(res["sig_d"]) - res["mean_l"][res["types"].get_indexer(dp.dp_type)], 0.0)
    dp["source_var"] = np.where(dg >= 0, gvar[np.clip(dg, 0, None)], 0.0)
    dp["page_attributed"] = dp.group.str.startswith("pc")
    dp.to_parquet(WORK / "dp_fit.parquet", index=False)
    edges.to_parquet(WORK / "fit_edges.parquet", index=False)
    st = {"iterations": res["iters"], "final_delta": res["hist"][-1], "domains": len(fd), "groups": len(res["groups"]),
          "page_attributed_points": len(assign), "gamma": GAMMA, "kappa": KAPPA,
          "class_prior_mean": dict(zip(res["classes"], np.round(res["m_c"], 4).tolist())),
          "mean_logit_sigma_by_type": dict(zip(res["types"], np.round(res["mean_l"], 4).tolist()))}
    (WORK / "s5_stats.json").write_text(json.dumps(st, indent=1))
    print(json.dumps(st, indent=1))


if __name__ == "__main__":
    assert np.allclose(expit(logit(np.array([0.2, 0.9]))), [0.2, 0.9])
    main()

"""Recompute the non-travel headline numbers of stories s1, s2, s3 and s6 from v_base tables.

Run after v_base.py. Writes verify/out/stories_numbers.json. Intervals: exact Poisson for counts per
population, Wilson for proportions, percentile bootstrap (2,000, seed 7) for Spearman rho.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.stats import beta, chi2, spearmanr

import v_base as B

STUNT = "child_u5_who_are_stunted_height_for_age_18_pct"
NCD = ["w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
       "m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
       "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
       "m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct"]
CS = "births_delivered_by_csection_5y_pct"
CS_PRIV = "births_in_a_private_fac_that_were_delivered_by_csection_5y_pct"
CS_PUB = "births_in_a_public_fac_that_were_delivered_by_csection_5y_pct"


def pois(k: float) -> tuple[float, float]:
    lo = chi2.ppf(0.025, 2 * k) / 2 if k > 0 else 0.0
    return lo, chi2.ppf(0.975, 2 * (k + 1)) / 2


def wilson(k: int, n: int, z: float = 1.959964) -> list[float]:
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [p, c - h, c + h]


def boot_rho(x, y, n: int = 2000, seed: int = 7) -> list[float]:
    x, y = np.asarray(x), np.asarray(y)
    rng = np.random.default_rng(seed)
    b = [spearmanr(x[i], y[i]).statistic for i in (rng.integers(0, len(x), len(x)) for _ in range(n))]
    return [float(spearmanr(x, y).statistic), float(np.nanpercentile(b, 2.5)), float(np.nanpercentile(b, 97.5))]


def nfhs_by_district(cols: list[str]) -> pd.DataFrame:
    """NFHS district rows joined to summed LGD population (child LGD districts summed into parents)."""
    link = B.nfhs_link().merge(B.district_pop()[["dist_lgd", "pop", "wra"]], on="dist_lgd")
    agg = link.dropna(subset=["nfhs_district"]).groupby(["nfhs_state", "nfhs_district"]).agg(
        pop=("pop", "sum"), wra=("wra", "sum"), stname=("stname", "first")).reset_index()
    nf = pd.read_parquet(B.ROOT / "data/raw/nfhs_5_district_health_indicators.parquet")
    nf = nf.assign(nfhs_state=nf.state_ut.str.strip(), nfhs_district=nf.district_name.str.strip())
    out = nf[["nfhs_state", "nfhs_district"]].copy()
    for c in cols:
        v = [B.nfhs_num(x) for x in nf[c]]
        out[c], out[c + "_flag"] = [a for a, _ in v], [b for _, b in v]
    return agg.merge(out, on=["nfhs_state", "nfhs_district"], how="inner"), link


def s1(d: pd.DataFrame) -> dict:
    t = B.district_pop()
    st = t.groupby("stname")["pop"].sum().to_frame()
    st["records"] = d.groupby("stname").size().reindex(st.index).fillna(0)
    st["per_m"] = st.records / st["pop"] * 1e6
    nf, _ = nfhs_by_district([STUNT])
    w = nf.dropna(subset=[STUNT])
    st["stunt_popw"] = w.groupby("stname").apply(lambda g: np.average(g[STUNT], weights=g["pop"]), include_groups=False)
    st["stunt_mean"] = w.groupby("stname")[STUNT].mean()
    big = st[st["pop"] >= 1e6].dropna(subset=["stunt_popw"])
    b = st.loc["BIHAR"]
    lo, hi = pois(b.records)
    dd = t.assign(records=t.dist_lgd.map(d.groupby("dist_lgd").size()).fillna(0))
    dd = dd[dd["pop"] > 0]
    bd = dd[dd.stname == "BIHAR"]
    zero = dd[dd.records == 0]
    over10 = st[st["pop"] >= 10e6].sort_values("stunt_popw", ascending=False)
    return dict(
        national_per_m=len(d) / t["pop"].sum() * 1e6, bihar_records=int(b.records), bihar_pop_m=b["pop"] / 1e6,
        bihar_per_m=[b.per_m, lo / b["pop"] * 1e6, hi / b["pop"] * 1e6],
        bihar_by_stated_state=int((d.state_final.str.upper() == "BIHAR").sum()),
        delhi_over_bihar=st.loc["DELHI", "per_m"] / b.per_m, top=st.per_m.idxmax(), top_per_m=st.per_m.max(),
        lowest_big=st[st["pop"] >= 1e6].per_m.nsmallest(3).to_dict(),
        bihar_stunt_popw=b.stunt_popw, bihar_stunt_mean=b.stunt_mean,
        stunt_rank_among_over1m=big.stunt_popw.rank(ascending=False)["BIHAR"],
        stunt_top3_over1m=big.stunt_popw.nlargest(3).to_dict(),
        stunt_rank_among_over10m=over10.stunt_popw.rank(ascending=False)["BIHAR"], n_over10m=len(over10),
        n_states_rho=len(big), rho=boot_rho(big.per_m, big.stunt_popw),
        patna=int(bd.set_index("dtname").loc["Patna", "records"]), bihar_total_in_districts=int(bd.records.sum()),
        patna_pop_share=float(bd.set_index("dtname").loc["Patna", "pop"] / bd["pop"].sum()),
        bihar_districts=len(bd), bihar_zero=int((bd.records == 0).sum()),
        zero_districts=len(zero), districts=len(dd), zero_pop_m=zero["pop"].sum() / 1e6)


def s2(d: pd.DataFrame) -> dict:
    nf, link = nfhs_by_district(NCD)
    nf["ncd"] = nf[NCD].mean(axis=1, skipna=False)
    nf = nf.dropna(subset=["ncd"])
    k = d.merge(link[["dist_lgd", "nfhs_state", "nfhs_district"]], on="dist_lgd")
    nf["n_conf"] = nf.set_index(["nfhs_state", "nfhs_district"]).index.map(
        k[k.dialysis_conf].groupby(["nfhs_state", "nfhs_district"]).size()).fillna(0).to_numpy()
    nf["q"] = pd.qcut(nf.ncd, 4, labels=False)
    q = nf.groupby("q").agg(pop=("pop", "sum"), n=("n_conf", "sum"), districts=("ncd", "size"))
    q["per_m"] = q.n / q["pop"] * 1e6
    q["ci"] = [[pois(n)[0] / p * 1e6, pois(n)[1] / p * 1e6] for n, p in zip(q.n, q["pop"])]
    pm = pd.read_csv(B.ROOT / "data/external/pmndp_counts_and_state_lists/pmndp_state_counts.csv")
    conf = d[d.dialysis_conf]
    claim = d[d.dialysis_claim]
    op = lambda x: x.operatorTypeId.where(x.operatorTypeId.isin(["private", "public", "government"]), "not stated")
    return dict(
        districts=len(nf), ncd_range=[nf.ncd.min(), nf.ncd.max()], ncd_q75=nf.ncd.quantile(0.75),
        by_quartile=q.reset_index().to_dict("records"),
        n_claim=len(claim), n_conf=len(conf), conf_operator=op(conf).value_counts().to_dict(),
        claim_operator=op(claim).value_counts().to_dict(),
        conf_private_share=wilson(int((op(conf) == "private").sum()), len(conf)),
        lgd_districts_with_conf=int(conf.dist_lgd.nunique()),
        pmndp_centres=int(pm.nhsrc_functional_centres.sum()), pmndp_func_districts=int(pm.nhsrc_functional_districts.sum()),
        pmndp_total_districts=int(pm.nhsrc_total_districts.sum()),
        pmndp_states_fewer_centres_than_districts=pm.loc[pm.nhsrc_functional_centres < pm.nhsrc_total_districts,
                                                        "state_key"].tolist(),
        pmndp_bihar=int(pm.set_index("state_key").loc["bihar", "nhsrc_functional_centres"]),
        bihar_conf=int((conf.stname == "BIHAR").sum()),
        pmndp_ap=pm.set_index("state_key").loc["andhra pradesh", ["nhsrc_functional_centres", "nhsrc_total_districts"]].tolist(),
        public_records_claiming_dialysis=int((op(claim).isin(["public", "government"])).sum()))


def s3(d: pd.DataFrame) -> dict:
    nf, link = nfhs_by_district([CS, CS_PRIV, CS_PUB])
    nf = nf.dropna(subset=[CS])
    k = d.merge(link[["dist_lgd", "nfhs_state", "nfhs_district"]], on="dist_lgd")
    idx = nf.set_index(["nfhs_state", "nfhs_district"]).index
    for c in ("csection_claim", "csection_conf"):
        nf[c] = idx.map(k[k[c]].groupby(["nfhs_state", "nfhs_district"]).size()).fillna(0).to_numpy()
    lq = laqshya_by_district(link)
    nf["lq"] = idx.map(lq).fillna(0).to_numpy()
    low, hi = nf[nf[CS] < 10], nf[nf[CS] >= 30]
    rate = lambda g, c: g[c].sum() / g.wra.sum()
    both = nf[(nf[CS_PRIV + "_flag"] == "ok") & (nf[CS_PUB + "_flag"] == "ok")]
    gt = int((both[CS_PRIV] > both[CS_PUB]).sum())
    op = d.operatorTypeId
    return dict(
        districts=len(nf), low_districts=len(low), low_wra_m=low.wra.sum() / 1e6,
        low_claim=int(low.csection_claim.sum()), low_conf=int(low.csection_conf.sum()), low_lq=int(low.lq.sum()),
        low_states=low.nfhs_state.value_counts().head(5).to_dict(),
        ratio_claim_hi_vs_low=rate(hi, "csection_claim") / rate(low, "csection_claim"),
        ratio_lq_hi_vs_low=rate(hi, "lq") / rate(low, "lq"),
        claims_per_m_women={str(b): float(rate(g, "csection_claim") * 1e6) for b, g in
                            nf.groupby(pd.cut(nf[CS], [0, 5, 10, 20, 30, 45, 100], right=False), observed=True)},
        priv_gt_pub=[gt, len(both), *wilson(gt, len(both))], gap_median=float((both[CS_PRIV] - both[CS_PUB]).median()),
        private_records=int((op == "private").sum()), records=len(d),
        lq_mot=int(lq.attrs["n_mot"]), lq_placed=int(lq.sum()), lq_valid_on_file=int(lq.attrs["valid"]))


def laqshya_by_district(link: pd.DataFrame) -> pd.Series:
    """LaQshya Maternity OT facilities per NFHS district, by exact loose-key district name within state.

    Simpler than the analyst's fuzzy match on purpose (a lower bound on placement)."""
    lq = pd.read_parquet(B.ROOT / "data/external/laqshya_master/laqshya_facilities.parquet")
    lq = lq[lq["Maternity OT"].notna()]
    st_alias = {"dnh d d": "dadra nagar haveli daman diu", "jammu kashmir": "jammu kashmir"}
    lq_sk = lq.state.map(B.key).replace(st_alias)
    l2 = link.assign(sk=link.stname.map(B.key), dk=link.dtname.map(B.key)).dropna(subset=["nfhs_district"])
    m = dict(zip(zip(l2.sk, l2.dk), zip(l2.nfhs_state, l2.nfhs_district)))
    # Also allow the NFHS district name itself as a target.
    m.update({(sk, B.key(nd)): (ns, nd) for sk, ns, nd in zip(l2.sk, l2.nfhs_state, l2.nfhs_district)})
    hits = [m.get((s, B.key(x))) for s, x in zip(lq_sk, lq.district)]
    s = pd.Series([h for h in hits if h]).value_counts()
    s.index = pd.MultiIndex.from_tuples(s.index)
    s.attrs.update(n_mot=len(lq), valid=int((lq["Maternity OT"] >= "2026-04-08").sum()))
    return s


def s6(d: pd.DataFrame) -> dict:
    out = {}
    for s in B.SERVICE:
        for site in (True, False):
            g = d[d[f"{s}_claim"] & (d.own_site == site)]
            out[f"{s}_site{int(site)}"] = [int(g[f"{s}_conf"].sum()), len(g)]
    anyc = d[[f"{s}_claim" for s in B.SERVICE]].any(axis=1)
    anyk = d[[f"{s}_conf" for s in B.SERVICE]].any(axis=1)
    for site in (True, False):
        g = d[anyc & (d.own_site == site)]
        k = int(anyk[g.index].sum())
        out[f"any_site{int(site)}"] = [k, len(g), *wilson(k, len(g))]
    op = d.operatorTypeId
    grp = {"private": op == "private", "public": op.isin(["public", "government"]),
           "not_stated": ~op.isin(["private", "public", "government"])}
    out["coverage"] = {k: [int(d.own_site[m].sum()), int(m.sum()), *wilson(int(d.own_site[m].sum()), int(m.sum()))]
                       for k, m in grp.items()}
    tr = d[d.trauma_conf]
    out["trauma_conf_sources"] = {c: int(tr[f"trauma_{c}"].sum()) for c in ("web", "osm", "tcf")}
    out["trauma_conf_web_only"] = int((tr.trauma_web & ~tr.trauma_osm & ~tr.trauma_tcf).sum())
    out["site_in_vf_sources"] = site_overlap(d)
    return out


def site_overlap(d: pd.DataFrame) -> dict:
    """Of web-confirmed claims, how many come from a website the dataset already lists among its sources."""
    raw = pd.read_parquet(B.ROOT / "data/raw/facilities.parquet", columns=["unique_id", "source_urls"]).drop_duplicates("unique_id")
    host = lambda u: re.sub(r"^(www|m)\.", "", re.sub(r"^https?://", "", u.strip().lower()).split("/")[0])
    hosts = {}
    for u, s in zip(raw.unique_id, raw.source_urls):
        try:
            hosts[u] = {host(x) for x in json.loads(s) if isinstance(x, str)}
        except (TypeError, ValueError):
            hosts[u] = set()
    si = pd.read_parquet(B.ROOT / "kb/web_evidence/out/site_identity.parquet", columns=["unique_id", "site", "kind", "attributable"])
    si = si[si.attributable & si.kind.isin(["site", "branch"])]
    same = {u for u, s in zip(si.unique_id, si.site) if isinstance(s, str) and host(s) in hosts.get(u, set())}
    res = {}
    for s in B.SERVICE:
        g = d[d[f"{s}_conf"] & d[f"{s}_web"]]
        res[s] = [int(g.unique_id.isin(same).sum()), len(g)]
    return res


import re  # noqa: E402  (used by site_overlap)

if __name__ == "__main__":
    d = B.records()
    res = {"s1": s1(d), "s2": s2(d), "s3": s3(d), "s6": s6(d)}
    txt = json.dumps(res, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    (B.OUT / "stories_numbers.json").write_text(txt)
    print(txt)

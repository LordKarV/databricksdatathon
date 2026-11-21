"""Independent recomputation of story 3 (confirmation funnel)."""
import pandas as pd
from vcommon import R, OK, wil

E = R + "data/external/"
W = R + "kb/web_evidence/out/"
SV = ["dialysis", "trauma_emergency", "emergency_csection", "nicu", "cardiac_surgery", "mri", "burn_care"]
pf = pd.read_parquet(R + "model/proto/evidence/pair_features.parquet", columns=["unique_id", "service", "T", "P"])
pf = pf[pf.service.isin(SV) & pf.unique_id.isin(OK)]
si = pd.read_parquet(W + "site_identity.parquet")
sites = set(si.unique_id[si.attributable & si.kind.isin(["site", "branch"])])
ss = pd.read_parquet(W + "web_service_summary.parquet")
ws = pd.read_parquet(W + "web_services.parquet", columns=["unique_id", "service_id", "quote", "final_url", "field", "line_kind"])
ws = ws.drop_duplicates(["unique_id", "service_id", "quote", "final_url", "field"])
ss = ss[ss.web_positive & (ss.scope != "chain_home")].merge(
    ws.rename(columns={"quote": "best_quote", "final_url": "best_url", "field": "best_field"}),
    on=["unique_id", "service_id", "best_quote", "best_url", "best_field"], how="left")
print("summary rows after merge", len(ss), "dupes", ss.duplicated(["unique_id", "service_id"]).sum())
hp = ss[ss.web_positive_strong & ((ss.n_pages_positive >= 2) | (ss.line_kind == "item"))]
web = set(zip(hp.unique_id, hp.service_id))
print("strict web pairs", len(web), "of which unique_id not in attributable sites:", sum(u not in sites for u, _ in web))
# lists
L = set()
nabh = pd.read_parquet(E + "nabh_accredited/nabh_vf_match.parquet")
print("nabh accept all?", nabh.accept.all(), "geo_conflict", nabh.geo_conflict.sum())
for code, svc in [("DIA", "dialysis"), ("EMD", "trauma_emergency")]:
    L |= {(u, svc) for u, s in zip(nabh.unique_id, nabh.nabh_specs) if s is not None and code in set(s)}
lq = pd.read_parquet(E + "laqshya_master/laqshya_vf_matches.parquet")
lqf = pd.read_parquet(E + "laqshya_master/laqshya_facilities.parquet")
mot = set(lqf.lq_id[lqf["Maternity OT"].notna()])
L |= {(u, "emergency_csection") for u, i in zip(lq.unique_id, lq.lq_id) if i in mot}
tcf = pd.read_csv(E + "mohfw_trauma_196/tcf_vf_matches.csv")
L |= {(u, "trauma_emergency") for u in tcf.vf_id}
nm = pd.read_parquet(E + "nmc_colleges/nmc_vf_matches.parquet").merge(pd.read_parquet(E + "nmc_colleges/nmc_service_labels.parquet"), on="college_id")
nm = nm[nm.tier == "strong"]
mp = {"dialysis": "dialysis", "trauma": "trauma_emergency", "csection": "emergency_csection", "nicu": "nicu",
      "cardiac_surgery": "cardiac_surgery", "burns": "burn_care"}
L |= {(u, mp[s]) for u, s in zip(nm.unique_id, nm.service) if s in mp}
tot = dict(m=0, o=0, o_site=0, pr=0)
for s in SV:
    g = pf[pf.service == s]
    m = g[g["T"] >= 1]
    k = list(zip(m.unique_id, [s] * len(m)))
    wkeys = [[(u, w) for w in (["trauma_care", "emergency_24x7"] if s == "trauma_emergency" else [s])] for u in m.unique_id]
    wv = pd.Series([any(x in web for x in ks) for ks in wkeys], index=m.index)
    hs = m.unique_id.isin(sites)
    lv = pd.Series([x in L for x in k], index=m.index)
    f2 = m["T"] >= 4
    pr = f2 & (m.P >= 1)
    o = (pr & (wv | lv)).sum(); o_site = (pr & ((wv & hs) | lv)).sum()
    tot["m"] += len(m); tot["o"] += o; tot["o_site"] += o_site; tot["pr"] += pr.sum()
    # reverse: outside evidence, not mentioned
    nm_ = g[g["T"] < 1]
    wk2 = [any((u, w) in web for w in (["trauma_care", "emergency_24x7"] if s == "trauma_emergency" else [s])) for u in nm_.unique_id]
    rev = sum((a and u in sites) or ((u, s) in L) for a, u in zip(wk2, nm_.unique_id))
    print(f"{s}: mentioned {len(m)} f2 {f2.sum()} prereq {pr.sum()} web {(wv & hs).sum()}/{hs.sum()} {wil((wv&hs).sum(), hs.sum())} "
          f"listed {lv.sum()} {wil(lv.sum(), len(m))} prereq&outside {o} (site-restricted {o_site}) reverse {rev}")
print(tot, wil(tot["o"], tot["m"]), "outside among prereq-passing", wil(tot["o"], tot["pr"]))

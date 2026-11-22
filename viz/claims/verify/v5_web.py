"""Independent recomputation of story 5 (websites vs dataset)."""
import json, re
import pandas as pd
from vcommon import R, OK, wil, claims, raw

W = R + "kb/web_evidence/out/"
si = pd.read_parquet(W + "site_identity.parquet")
own = si[si.attributable & si.kind.isin(["site", "branch"]) & si.unique_id.isin(OK)]
pop = set(own.unique_id)
print("population", len(pop), "with services page", own[own.has_services_page].unique_id.nunique())
ss = pd.read_parquet(W + "web_service_summary.parquet")
ss = ss[ss.web_positive & (ss.scope != "chain_home")]
pos = set(zip(ss.unique_id, ss.service_id))
ws = pd.read_parquet(W + "web_services.parquet")
best = ws.drop_duplicates(["unique_id", "service_id", "quote", "final_url", "field"])[["unique_id", "service_id", "quote", "final_url", "field", "line_kind"]]
m = ss.merge(best, left_on=["unique_id", "service_id", "best_quote", "best_url", "best_field"],
             right_on=["unique_id", "service_id", "quote", "final_url", "field"], how="left")
strict = set(zip(m.unique_id[m.web_positive_strong & ((m.n_pages_positive >= 2) | (m.line_kind == "item"))],
                 m.service_id[m.web_positive_strong & ((m.n_pages_positive >= 2) | (m.line_kind == "item"))]))
c = claims()
c = c[c.unique_id.isin(pop)]
cl = c[c.text_pos | c.spec].copy()
cl["conf"] = [(u, s) in pos for u, s in zip(cl.unique_id, cl.service)]
cl["strict"] = [(u, s) in strict for u, s in zip(cl.unique_id, cl.service)]
print("claims", len(cl), "confirm", cl.conf.sum(), wil(cl.conf.sum(), len(cl)), "strict", cl.strict.sum(), wil(cl.strict.sum(), len(cl)))
mention = set(zip(c.unique_id, c.service))
wp = {x for x in pos if x[0] in pop}; wst = {x for x in strict if x[0] in pop}
print("web-only", len(wp - mention), len(wp), wil(len(wp - mention), len(wp)), "strict", len(wst - mention), len(wst))
# source overlap
def host(u):
    return re.sub(r"^(www|m)\.", "", re.sub(r"^https?://", "", u.strip().lower()).split("/")[0])
rw = raw()
hs = {}
for u, s in zip(rw.unique_id, rw.source_urls):
    try:
        v = json.loads(s) if isinstance(s, str) else []
    except ValueError:
        v = []
    hs[u] = {host(x) for x in v if isinstance(x, str)}
same = {u for u, st in zip(own.unique_id, own.site) if st in hs.get(u, set())}
cl["same"] = cl.unique_id.isin(same)
cl["kind"] = cl.text_pos.map({True: "text", False: "spec_only"})
for (k, sm), g in cl.groupby(["kind", "same"]):
    print(k, "site in sources" if sm else "independent", g.conf.sum(), len(g), wil(g.conf.sum(), len(g)), "strict", g.strict.sum())
# per-service extremes among services with 100+ claims
bs = cl.groupby("service").agg(n=("conf", "size"), k=("conf", "sum"))
bs = bs[bs.n >= 100].assign(r=lambda d: d.k / d.n).sort_values("r")
print(bs.head(3).to_string(), bs.tail(3).to_string())
# confounding check: is the specialty-only vs sentence gap present within services? (independent sites only and all)
for lab, g in [("all", cl), ("independent", cl[~cl.same])]:
    t = g.groupby(["service", "kind"]).conf.agg(["sum", "size"]).unstack()
    t = t.dropna()
    t = t[(t[("size", "spec_only")] >= 20) & (t[("size", "text")] >= 20)]
    diff = (t[("sum", "text")] / t[("size", "text")] - t[("sum", "spec_only")] / t[("size", "spec_only")])
    print(lab, "services with >=20 of each kind:", len(t), "text higher in", (diff > 0).sum(), "median gap", round(diff.median(), 3))
    # service-standardised: reweight spec_only to text's service mix
# silent
hasp = set(own.unique_id[own.has_services_page])
anyrow = set(zip(ws.unique_id[ws.attributable & ws.scope.isin(["own_site", "branch_page"])], ws.service_id[ws.attributable & ws.scope.isin(["own_site", "branch_page"])]))
sil = cl[cl.unique_id.isin(hasp)]
k = sum((u, s) not in anyrow for u, s in zip(sil.unique_id, sil.service))
print("silent", k, len(sil), wil(k, len(sil)))

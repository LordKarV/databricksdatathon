"""Independent re-implementation of P2 (off-state directory URL), P3-like foreign-institution claims, P3s-like
near-miss names, research URLs, and the any_proxy gradient (PROV-02..05, 07)."""
import duckdb, json, re, pandas as pd
from rapidfuzz import fuzz, process
from urllib.parse import urlparse
R = "/Users/karthikvattem/projects/datathon/data/raw"
f = duckdb.sql(f"""select distinct * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""").df()
p = pd.read_parquet(f"{R}/india_post_pincode_directory.parquet"); p = p[p.statename != "NA"]
def jl(s):
    try: v = json.loads(s) if isinstance(s, str) and s.startswith("[") else []
    except ValueError: v = []
    return [x.strip() for x in v if isinstance(x, str) and x.strip()]
k = lambda s: re.sub(r"[^a-z]", "", str(s).lower())
canon = sorted(p.statename.unique())
def ns(s):
    if not isinstance(s, str) or s.strip().lower() in ("", "null"): return None
    t = re.sub(r"\s+", " ", s.upper().replace(" STATE", "")).strip().split(",")[-1].strip()
    t = {"ORISSA": "ODISHA", "PONDICHERRY": "PUDUCHERRY", "UP": "UTTAR PRADESH", "MP": "MADHYA PRADESH", "NCT OF DELHI": "DELHI", "NEW DELHI": "DELHI"}.get(t, t)
    b = process.extractOne(t, canon, scorer=fuzz.ratio); return b[0] if b and b[1] >= 88 else None
f["st"] = f.address_stateOrRegion.map(ns)
# district-name -> states (district names only: stricter than finder, which also uses office names)
dist_states = p.groupby(p.district.map(k)).statename.agg(set).to_dict()
ALIAS = {"bangalore": "bengaluruurban", "bengaluru": "bengaluruurban", "gurgaon": "gurugram", "delhi": "newdelhi", "newdelhi": "newdelhi", "kochi": "ernakulam", "cochin": "ernakulam",
         "mysore": "mysuru", "trivandrum": "thiruvananthapuram", "calicut": "kozhikode", "baroda": "vadodara", "vizag": "visakhapatnam", "allahabad": "prayagraj", "navimumbai": "thane",
         "noida": "gautambuddhanagar", "mangalore": "dakshinakannada", "hubli": "dharwad", "belgaum": "belagavi", "gulbarga": "kalaburagi", "secunderabad": "hyderabad", "pondicherry": "pondicherry"}
def url_state(u):
    m = re.match(r"https?://(?:www\.|m\.)?(justdial\.com|practo\.com|lybrate\.com)/([^/?#]+)", u, re.I)
    if not m: return None
    key = ALIAS.get(k(m.group(2)), k(m.group(2)))
    s = dist_states.get(key)
    return next(iter(s)) if s and len(s) == 1 else None
RES = re.compile(r"(ncbi\.nlm\.nih\.gov|pubmed|europepmc|researchgate|sciencedirect|springer|wiley|doi\.org|journals?\.|journal|tandfonline|frontiersin|bmj\.com|thelancet|cureus|plos|mdpi|sagepub|medknow|jamanetwork|nejm|semanticscholar)", re.I)
HEAD = r"(?:Hospitals?|Medical College|Nursing Home|Medical Cent(?:re|er)|Institute of Medical Sciences)"
MENT = re.compile(r"((?:[A-Z][A-Za-z\.'&-]+\s+){1,5}" + HEAD + r")")
GEN = set("hospital hospitals medical college nursing home centre center institute sciences of the and multispeciality multi speciality super specialty general government govt district civil city new care health sri shri shree st".split())
AFF = re.compile(r"(?i)\b(MBBS|MD|MS|DNB|degree|trained|alumn|former|previously|consultant|professor|affiliat|attached|partner|tie-?up|associated|near|opposite|behind|refer|network|empanel|insurance|listed|top|best)\w*")
rows = []
for r in f.itertuples(index=False):
    urls = jl(r.source_urls)
    offst = [u for u in urls if (s := url_state(u)) and r.st and s != r.st]
    claims = [x for c in ("procedure", "equipment", "capability") for x in jl(getattr(r, c))]
    own = [t for t in re.findall(r"[a-z]+", (r.name or "").lower()) if t not in GEN and len(t) >= 3]
    foreign, near = [], []
    for x in claims:
        for m in MENT.findall(x):
            mt = [t for t in re.findall(r"[a-z]+", m.lower()) if t not in GEN and len(t) >= 3]
            if not mt or not own: continue
            if any(t in own for t in mt) or any(fuzz.ratio(t, o) >= 90 for t in mt for o in own): continue
            if AFF.search(x): continue
            foreign.append((m, x))
            # near-miss: first distinctive token close to own first token but different (Kamal vs Kamat)
            if 75 <= fuzz.ratio(mt[0], own[0]) < 100 and len(mt) <= 2: near.append((m, x))
    rows.append({"unique_id": r.unique_id, "name": r.name, "city": r.address_city, "nu": len(urls), "p2": bool(offst) if r.st else None,
                 "p2_ex": offst[:2], "n_res": sum(bool(RES.search(urlparse(u if "://" in u else "http://" + u).netloc)) for u in urls),
                 "p3x": bool(foreign), "p3x_ex": foreign[:2], "p3n": bool(near), "p3n_ex": near[:2], "nclaims": len(claims), "nforeign": len({x for _, x in foreign})})
d = pd.DataFrame(rows)
km = pd.read_parquet("v3_fac_pin_km.parquet")[["unique_id", "d"]]
d = d.merge(km, on="unique_id", how="left"); d["p4"] = (d.d > 50).where(d.d.notna())
st = json.load(open("v5_state.json"))
o = {"n": len(d), "p2": [int(d.p2.fillna(False).sum()), int(d.p2.notna().sum())], "research_records": int((d.n_res > 0).sum()), "research_urls": int(d.n_res.sum()),
     "research_median_urls": float(d[d.n_res > 0].nu.median()), "p3x": int(d.p3x.sum()), "p3n_near_miss": int(d.p3n.sum())}
d["any"] = d[["p2", "p3x", "p4"]].fillna(False).astype(bool).any(axis=1)
ub = pd.cut(d.nu, [-1, 5, 10, 20, 1000], labels=["0-5", "6-10", "11-20", "21+"])
o["any_by_bucket(p2|p3x|p4)"] = {str(b): [int(g.sum()), len(g), round(100 * g.mean(), 1)] for b, g in d.groupby(ub, observed=True)["any"]}
o["p2_by_bucket"] = {str(b): round(100 * g.fillna(False).astype(bool).mean(), 2) for b, g in d.groupby(ub, observed=True)["p2"]}
o["any_total"] = int(d["any"].sum())
w = d[d.nu > 20]
for nm, m in (("research", w.n_res > 0), ("no_research", w.n_res == 0)):
    o["21plus_" + nm] = {"records": int(m.sum()), "foreign_claims": int(w[m].nforeign.sum()), "claims": int(w[m].nclaims.sum()),
                         "rate_pct": round(100 * w[m].nforeign.sum() / w[m].nclaims.sum(), 2), "p4_pct": round(100 * w[m].p4.dropna().astype(bool).mean(), 1)}
d["p4b"] = d.p4.fillna(False).astype(bool)
o["p4_given_near_miss"] = [int(d[d.p3n].p4b.sum()), int(d[d.p3n].p4.notna().sum())]
o["p4_given_not_near_miss"] = [int(d[~d.p3n].p4b.sum()), int(d[~d.p3n].p4.notna().sum())]
d.to_parquet("v10_records.parquet")
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v10_proxies.json", "w"), indent=1, default=str)

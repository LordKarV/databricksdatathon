"""Missed-issue probe: is officialWebsite itself about the facility? Name-vs-host similarity, aggregator hosts, shared official sites."""
import duckdb, re, json, random
from urllib.parse import urlparse
from rapidfuzz import fuzz
R = "/Users/karthikvattem/projects/datathon/data/raw"
rows = duckdb.sql(f"""select distinct unique_id, name, address_city, officialWebsite from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""").fetchall()
GEN = set("hospital hospitals clinic clinics dental medical care health healthcare centre center multispeciality multi speciality super specialty superspeciality nursing home research institute diagnostic diagnostics eye children child women city general the and of dr pvt ltd".split())
def host(u):
    u = u if "://" in u else "http://" + u
    try: x = urlparse(u).netloc.lower()
    except ValueError: return ""
    return x[4:] if x.startswith("www.") else x
o = dict(records=len(rows), has_official=0, aggregator_or_social=0, low_sim=0)
low, hosts = [], {}
for uid, n, c, w in rows:
    if not w or w.strip().lower() in ("null", ""): continue
    o["has_official"] += 1; hh = host(w); hosts.setdefault(hh, set()).add(n)
    if re.search(r"practo|justdial|facebook|instagram|lybrate|google|business\.site|placestars|wix|blogspot", hh): o["aggregator_or_social"] += 1; continue
    nk = "".join(t for t in re.findall(r"[a-z0-9]+", (n or "").lower()) if t not in GEN)
    lab = re.sub(r"[^a-z0-9]", "", hh.split(".")[0] if not hh.startswith("m.") else hh.split(".")[1])
    if len(nk) >= 4 and fuzz.partial_ratio(nk, lab) < 60 and fuzz.partial_ratio(lab, nk) < 60:
        o["low_sim"] += 1; low.append((n, c, w))
o["hosts_shared_by_gt1_distinct_names"] = sum(len(v) > 1 for v in hosts.values())
o["records_on_shared_hosts"] = sum(len(v) for v in hosts.values() if len(v) > 1)
random.seed(5); o["low_sim_sample"] = random.sample(low, 15)
print(json.dumps(o, indent=1, ensure_ascii=False)); json.dump(o, open("v14_official.json", "w"), indent=1)

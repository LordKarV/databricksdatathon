"""PROV-01: independent crude URL classes: own-site host, facebook numeric id, aggregator, name-token-in-path."""
import duckdb, json, re
from urllib.parse import urlparse
R = "/Users/karthikvattem/projects/datathon/data/raw"
rows = duckdb.sql(f"""select distinct unique_id, name, officialWebsite, websites, source_urls from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie' and source_urls like '[%'""").fetchall()
def h(u):
    u = u if "://" in u else "http://" + u
    try: x = urlparse(u).netloc.lower()
    except ValueError: return ""
    return x[4:] if x.startswith("www.") else x
GEN = set("hospital hospitals clinic clinics dental medical care health healthcare centre center multispeciality multi speciality super nursing home research institute diagnostic diagnostics eye children child women city general india the and sri shri shree new life".split())
c = dict(total=0, own_host=0, fb_numeric=0, name_in_path=0, agg=0, research=0, about_est=0, recs_no_about=0)
for uid, name, ow, ws, su in rows:
    own = {h(ow)} if ow and ow != "null" else set()
    # ponytail: 'websites' is not used: it mirrors source_urls hosts (aggregators included), see websites_overlap
    own.discard("")
    toks = {t for t in re.findall(r"[a-z]{4,}", (name or "").lower()) if t not in GEN}
    anyabout = False
    for u in json.loads(su):
        if not isinstance(u, str) or not u.strip(): continue
        c["total"] += 1; hu = h(u)
        a = False
        if hu in own: c["own_host"] += 1; a = True
        elif re.search(r"facebook\.com/(profile\.php\?id=)?\d{6,}/?$", u): c["fb_numeric"] += 1
        elif toks and toks & set(re.findall(r"[a-z]+", urlparse(u if "://" in u else "http://" + u).path.lower())): c["name_in_path"] += 1; a = True
        if re.search(r"practo|justdial|lybrate|medindia|credihealth|onefivenine|hexahealth|bajajfinservhealth|healthfrog|drlogy", hu): c["agg"] += 1
        c["about_est"] += a; anyabout |= a
    c["recs_no_about"] += not anyabout
c["recs"] = len(rows)
c["about_pct"] = round(100 * c["about_est"] / c["total"], 1); c["fb_numeric_pct"] = round(100 * c["fb_numeric"] / c["total"], 1); c["agg_pct"] = round(100 * c["agg"] / c["total"], 1)
print(json.dumps(c, indent=1)); json.dump(c, open("v13_url_classes.json", "w"), indent=1)

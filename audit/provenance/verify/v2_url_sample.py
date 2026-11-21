"""Independent random sample of 50 non-empty source URLs (seed 2026) for manual labelling."""
import duckdb, random, json
F = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
rows = duckdb.sql(f"""select distinct unique_id, name, address_city, officialWebsite, source_urls from '{F}'
 where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie' and source_urls like '[%'""").fetchall()
pairs = [(u, n, c, w, x) for u, n, c, w, s in rows for x in json.loads(s) if isinstance(x, str) and x.strip()]
print(len(pairs))
random.seed(2026)
for i, (u, n, c, w, x) in enumerate(random.sample(pairs, 50)):
    print(i, "|", n, "|", c, "|", w, "|", x[:150])

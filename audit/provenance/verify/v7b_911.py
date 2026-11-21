"""Read claim sentences containing 911 / patient portal / board certified to see whether they are template text."""
import duckdb, json, re, collections
R = "/Users/karthikvattem/projects/datathon/data/raw"
rows = duckdb.sql(f"""select distinct unique_id, name, procedure, equipment, capability from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""").fetchall()
c = collections.Counter(); recs = collections.defaultdict(set)
for u, n, *cols in rows:
    for s in cols:
        try: v = json.loads(s) if s and s.startswith("[") else []
        except ValueError: v = []
        for x in v:
            if isinstance(x, str):
                for lab, rx in (("911", r"\b911\b"), ("portal", r"(?i)patient portal"), ("board", r"(?i)board[- ]certified")):
                    if re.search(rx, x): c[(lab, x[:110])] += 1; recs[lab].add(u)
for lab in ("911", "portal", "board"):
    print(lab, "records", len(recs[lab]))
    for (l, x), k in c.most_common(200):
        if l == lab: print("  ", k, x)
    print()

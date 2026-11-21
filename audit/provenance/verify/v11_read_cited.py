"""Read raw rows for cited examples: print the claim sentences / URLs that support each cited detail."""
import duckdb, json, re, sys
R = "/Users/karthikvattem/projects/datathon/data/raw"
con = duckdb.connect()
con.sql(f"""create view b as select distinct * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""")
CHECK = {  # id -> regex to grep in claims/urls/description
 "8211380c-2349-4969-b60c-7cf10335c20b": "umaa", "13964de0-54a7-4fc2-94b5-95454187017d": "fortis", "deb837c2-e6b5-490e-90a2-e5adf36ee69e": "chaitanya",
 "356efa40-be81-4a3e-a99b-3ed4e15e32db": "kamal|kolhapur", "f6a7f172-824b-49bd-b5ea-dbced9e4b350": "naik|bhusawal",
 "1fecf8f2-3de2-4a25-bfda-bc868419c78f": "anand hospital", "3b3f7422-f1ed-48df-9dd3-54f8f17a7e5e": "jaya hospital", "8a3bf8a0-fdf6-4481-bc4b-7040060cd5de": "lathi",
 "81f69525-b792-4246-a25f-a98cb67348e9": "santhi", "723a6e17-fdf9-4af8-ae80-b16ea3b98244": "visakhapatnam|vizag",
 "33f3fa89-8e8d-460e-a147-47fabb4d8902": "kerala institute|kims", "4616c935-ae1b-4d40-ae5a-3d6c31a90206": "j\\.? ?j\\.?|exercise",
 "788a47ec-36ae-43ba-afb0-ae07df9b1579": "gauhati medical", "1a62801f-4ddb-43e0-81cc-182cb1311171": "ppgl|single-center",
 "0f8375e1-a47c-4959-94c5-313e0e2512a1": "ranchi|bokaro", "58f1d117-1043-4761-abc2-254274e11cd7": "justdial|practo|lybrate",
 "21aff767-36c4-4454-b0e6-a74dfd136f94": "reva|indore", "182f39ec-8648-4ec8-8b57-216719778ff1": "cardiac", "160970c9-3aaf-474c-9b95-287957844262": "cardiac",
}
for uid, rx in CHECK.items():
    r = con.sql(f"select name, address_city, address_stateOrRegion, address_zipOrPostcode, latitude, longitude, description, procedure, equipment, capability, source_urls from b where unique_id='{uid}'").fetchall()
    if not r: print(uid, "NOT FOUND"); continue
    r = r[0]
    print(f"== {uid} | {r[0]} | {r[1]}, {r[2]} {r[3]} | {r[4]},{r[5]}")
    items = [("desc", r[6] or "")]
    for lab, s in zip(("proc", "equip", "cap", "url"), r[7:]):
        try: items += [(lab, x) for x in json.loads(s) if isinstance(x, str)] if s and s.startswith("[") else []
        except ValueError: pass
    hits = [(l, x) for l, x in items if re.search(rx, x, re.I)]
    for l, x in hits[:3]: print("   ", l, ":", x[:230])
    if not hits: print("    NO HIT for", rx)

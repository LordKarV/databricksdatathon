"""Independent sentence table: list items of procedure/equipment/capability plus description split at
sentence ends. Writes verify/out/sent.parquet."""
import json, os, re
import pandas as pd
from v_base import con
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)
df = con.execute("select distinct * from wf").df()
NULLS = {None, "", "null", "NULL"}
def items(v):
    if v in NULLS or (isinstance(v, float)):
        return []
    try:
        x = json.loads(v)
    except Exception:
        return []
    return [s.strip() for s in x if isinstance(s, str) and s.strip()] if isinstance(x, list) else []
rows = []
for r in df.itertuples():
    for f in ("procedure", "equipment", "capability"):
        for i, s in enumerate(items(getattr(r, f))):
            rows.append((r.unique_id, f, i, s))
    d = r.description if isinstance(r.description, str) and r.description not in NULLS else ""
    for i, s in enumerate([x.strip() for x in re.split(r"(?<=[.!?])\s+", d) if x.strip()]):
        rows.append((r.unique_id, "description", i, s))
s = pd.DataFrame(rows, columns=["unique_id", "field", "idx", "text"])
s.to_parquet(f"{OUT}/sent.parquet")
df[["unique_id", "name", "address_city", "address_stateOrRegion", "address_zipOrPostcode", "latitude", "longitude",
    "facilityTypeId", "source_urls", "source_ids", "source_content_id", "description"]].to_parquet(f"{OUT}/rec.parquet")
print("records", len(df), "sentences", len(s), s.field.value_counts().to_dict())
print("records with zero sentences", len(set(df.unique_id) - set(s.unique_id)))
# description splitting artefacts: fragments ending in a title abbreviation
frag = s[(s.field == "description") & s.text.str.contains(r"\b(?:Dr|St|Mr|Mrs|Ms|No|Pvt|Ltd|Sr|Jr)\.$", regex=True)]
print("description fragments ending in an abbreviation (Dr./St./Pvt. ...):", len(frag), "of", int((s.field == 'description').sum()))

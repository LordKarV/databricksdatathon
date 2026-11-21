"""Extractor hedge phrases across all procedure/equipment/capability items. Writes out/hedges.json."""
import json, random
from common import load, TEXT_FIELDS
from services import CUES
df = load()
H = CUES["hedge"]
tot, hits, fac = 0, [], set()
for r in df.itertuples():
    for f in TEXT_FIELDS:
        for s in getattr(r, f + "_l"):
            tot += 1
            if H.search(s):
                hits.append((r.unique_id, f, s))
                fac.add(r.unique_id)
random.seed(2)
res = dict(items=tot, hedged_items=len(hits), facilities=len(fac), examples=random.sample(hits, 8))
json.dump(res, open("out/hedges.json", "w"), indent=1)
print({k: v for k, v in res.items() if k != "examples"})

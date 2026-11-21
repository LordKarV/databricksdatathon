"""P4 sensitivity (naive centroid) and hand-check sample: cited ids + 6 random >50 km rows."""
import pandas as pd, numpy as np
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
d = pd.read_parquet("v3_fac_pin_km.parquet")
p = pd.read_parquet("/Users/karthikvattem/projects/datathon/data/raw/india_post_pincode_directory.parquet")
dist = p[p.district != "NA"].groupby("pincode").district.agg(lambda s: "|".join(sorted(set(s)))[:40])
d["pin_districts"] = d.pin.map(dist)
cited = ["b8a5401f-42f1-422a-8cd9-686a15b4cb76", "5bd3bbd4-3590-4bf8-9a5c-4a856a14f1de", "e31d34f8-578c-41d6-9723-0c137438ceb2",
         "356efa40-be81-4a3e-a99b-3ed4e15e32db", "f6a7f172-824b-49bd-b5ea-dbced9e4b350", "1fecf8f2-3de2-4a25-bfda-bc868419c78f", "3b3f7422-f1ed-48df-9dd3-54f8f17a7e5e"]
cols = ["name", "address_city", "address_stateOrRegion", "pin", "pin_districts", "latitude", "longitude", "a", "b", "d"]
print(d[d.unique_id.isin(cited)][cols].round(2).to_string())
print(d[d.d > 50].sample(8, random_state=99)[cols].round(2).to_string())
# rate of >50 km among facilities whose PIN has a single office used vs many: is PIN coarseness driving it?

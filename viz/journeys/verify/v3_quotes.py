"""Story 3: every claim id quoted on the itinerary chart exists in derived/v1/claims.parquet with that text,
and belongs to the facility it is attached to."""
from pathlib import Path

import pandas as pd

R = Path("/Users/karthikvattem/projects/datathon")
ids = ["2dccd2d1:capa:0", "2dccd2d1:capa:5", "acb49d43:capa:43", "acb49d43:capa:16", "925fb5c8:capa:3", "925fb5c8:desc:0",
       "1a7c035e:capa:11", "1a7c035e:proc:5", "e22f6de9:capa:29", "e22f6de9:equi:5", "e22f6de9:proc:11",
       "9f46eab1:equi:2", "9f46eab1:proc:9"]
c = pd.read_parquet(R / "derived/v1/claims.parquet", columns=["claim_id", "unique_id", "text", "attribution", "nonoffer"])
f = pd.read_parquet(R / "derived/v1/facility_location.parquet", columns=["unique_id", "name", "loc_conf", "district"])
x = c[c.claim_id.isin(ids)].merge(f, on="unique_id", how="left")
pd.set_option("display.max_colwidth", 90)
print(x[["claim_id", "name", "district", "loc_conf", "attribution", "nonoffer", "text"]].to_string())
print("missing:", set(ids) - set(x.claim_id))

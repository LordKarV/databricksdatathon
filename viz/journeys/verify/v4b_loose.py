"""Story 4: which records mention snakes outside the planner's matcher, and in which states."""
from pathlib import Path

import pandas as pd

R = Path("/Users/karthikvattem/projects/datathon")
c = pd.read_parquet(R / "derived/v1/claims.parquet", columns=["claim_id", "unique_id", "text", "attribution", "nonoffer"])
f = pd.read_parquet(R / "derived/v1/facility_location.parquet", columns=["unique_id", "name", "state_final"])
x = c[c.text.str.contains(r"snake|antivenom|anti-venom|anti venom|\bASV\b", case=False, na=False)].merge(f, on="unique_id")
pd.set_option("display.max_colwidth", 140)
print(x[["state_final", "name", "attribution", "nonoffer", "text"]].sort_values("state_final").to_string())

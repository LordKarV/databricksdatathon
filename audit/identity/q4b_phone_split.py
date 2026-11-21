"""Q4b: records whose officialPhone is held by records in >= 3 cities, split by chain membership."""
import pandas as pd
from common import OUT
E = pd.read_csv(OUT + "existence_signals.csv", dtype={"officialPhone": str})
C = pd.read_csv(OUT + "chain_membership.csv")
m = E.merge(C[["unique_id", "chain"]], on="unique_id")
s = m[m.phone == "shared_3plus_cities"]
print("officialPhone shared across >= 3 cities:", len(s), "| chain members:", int(s.chain.notna().sum()),
      "| non-chain (directory number likely):", int(s.chain.isna().sum()))
print("officialPhone = 9693969347 (proptiger.com pages):", int((m.officialPhone == "+919693969347").sum()))
print(s[s.chain.isna()].officialPhone.value_counts().head(8).to_dict())

"""Q1b: duplicate candidates the strong keys miss: phone/domain-linked pairs in the same city
or within 5 km with similar names (token_set_ratio >= 90). Prints a sample for hand check."""
import pandas as pd
from common import OUT
P = pd.read_csv(OUT + "dup_pairs.csv")
strong = P["keys"].str.contains("name_city|name_pin|geo_name")
c = P[~strong & (P.name_sim >= 90) & ((P.city_a.str.lower() == P.city_b.str.lower()) | (P.km < 5))]
print("phone/domain-only pairs, similar name, same city or <5 km:", len(c),
      "records", len(set(c.uid_a) | set(c.uid_b)))
print(c.sample(min(15, len(c)), random_state=0)[["uid_a", "name_a", "name_b", "city_a", "city_b", "km", "keys"]].to_string())

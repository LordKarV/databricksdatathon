"""Q3b: for the most-shared phone numbers, which directory domain the holders have in common
(lift = share of holders listing the domain / share of all records listing it)."""
import collections
import pandas as pd
from common import load, OUT, norm_phone, domain

df = load().drop_duplicates("unique_id").reset_index(drop=True)
S = pd.read_csv(OUT + "shared_phones.csv", dtype={"phone": str})
doms = df.websites_l.map(lambda l: {domain(u) for u in l} - {None})
base = collections.Counter(d for s in doms for d in s)
N = len(df)
for p in S.phone.head(12):
    holders = [i for i, r in df.iterrows()
               if p in {norm_phone(x)[0] for x in r.phone_numbers_l + ([r.officialPhone] if r.officialPhone else [])}]
    c = collections.Counter(d for i in holders for d in doms[i])
    best = sorted(((c[d] / len(holders)) / (base[d] / N), d, c[d]) for d in c if c[d] >= 0.3 * len(holders))[-2:]
    print(p, "holders", len(holders), "| most over-represented directory domains (lift, domain, holders):",
          [(round(l, 1), d, n) for l, d, n in best[::-1]])

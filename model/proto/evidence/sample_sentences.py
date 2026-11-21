"""Draw the sentence-level hand-check set (spec 4.2: 50 unanchored atoms on high-bucket records, 50 on low,
plus every other ownership and role class). Writes sentence_sample.csv with the strata and rule outputs and
sentence_blind.txt with only what a labeller may see (name, type, city, state, service, field, text).
Split: sha256('vf-sent-v1:' + unique_id) even -> dev, odd -> test, so all sentences of a record share a split.
"""
import hashlib

import pandas as pd

from common import HERE, INPUTS

SEED = 20261122
STRATA = [  # name, query on atoms (+ bucket), n
    ("unanch_high", "ownership == 'unanchored' and counts_as_own and bucket == 'high'", 50),
    ("unanch_low", "ownership == 'unanchored' and counts_as_own and bucket == 'low'", 50),
    ("unanch_mid", "ownership == 'unanchored' and counts_as_own and bucket == 'mid'", 20),
    ("own_anchored", "ownership == 'own_anchored' and counts_as_own", 15),
    ("other_facility", "ownership == 'other_facility'", 20),
    ("other_place", "ownership in ('other_place', 'quarantined')", 14),
    ("sibling", "ownership == 'sibling'", 10),
    ("ambiguous", "ownership == 'ambiguous'", 15),
    ("nonoffer", "role == 'nonoffer'", 15),
    ("list_dir_staff", "role in ('list', 'directory', 'staff', 'hedge', 'research_or_template') and field != 'specialties'", 15),
]


def split_of(uid: str) -> str:
    return "dev" if int(hashlib.sha256(f"vf-sent-v1:{uid}".encode()).hexdigest(), 16) % 2 == 0 else "test"


def main():
    a = pd.read_parquet(HERE / "claim_atoms.parquet")
    pf = pd.read_parquet(HERE / "pair_features.parquet", columns=["unique_id", "bucket"]).drop_duplicates("unique_id")
    rs = pd.read_parquet(INPUTS["record_scores"], columns=["unique_id", "name", "facilityTypeId", "address_city",
                                                           "address_stateOrRegion"])
    a = a.merge(pf, on="unique_id").merge(rs, on="unique_id")
    a = a.drop_duplicates("claim_id")          # one label per sentence; the service is the first tagged one
    taken, rows = set(), []
    for name, q, n in STRATA:
        pool = a.query(q)
        pool = pool[~pool.claim_id.isin(taken)]
        s = pool.sample(min(n, len(pool)), random_state=SEED)
        taken |= set(s.claim_id)
        rows.append(s.assign(stratum=name))
    s = pd.concat(rows).sample(frac=1, random_state=SEED).reset_index(drop=True)
    s["sid"] = [f"s{i:03d}" for i in range(len(s))]
    s["split"] = s.unique_id.map(split_of)
    s.to_csv(HERE / "sentence_sample.csv", index=False)
    with open(HERE / "sentence_blind.txt", "w") as f:
        for r in s.itertuples():
            f.write(f"{r.sid} | {r.name} | {r.facilityTypeId} | {r.address_city}, {r.address_stateOrRegion} | "
                    f"{r.service} | {r.field} | {r.text}\n")
    print(s.groupby(["stratum", "split"]).size().unstack(fill_value=0), len(s))


if __name__ == "__main__":
    main()

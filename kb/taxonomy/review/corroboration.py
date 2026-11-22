"""How often a specialties value is corroborated by positive text for the service it maps to (or names as prereq_for).
Tests whether the service vs too_general split in specialty_map.csv is consistent: a value labelled with a service
should be corroborated about as often as, or more than, a value labelled too_general.
Writes review/corroboration.csv. Run: /Users/karthikvattem/projects/datathon/.venv/bin/python review/corroboration.py
"""
from __future__ import annotations

import os

import duckdb
import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
T = os.path.dirname(D)
RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
LOC = "/Users/karthikvattem/projects/datathon/cleaning/geo_identity/facility_location.parquet"
MIN_FAC = 100


def main() -> None:
    usable = set(pd.read_parquet(LOC, columns=["unique_id"]).unique_id)
    smap = pd.read_csv(os.path.join(T, "specialty_map.csv"))
    m = pd.read_parquet(os.path.join(T, "out", "lexicon_matches.parquet"))
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility")]
    pos_pairs = set(zip(pos.unique_id, pos.service))
    sp = duckdb.sql(f"""select distinct unique_id, s as specialty from
        (select unique_id, unnest(from_json(specialties, '["VARCHAR"]')) s from read_parquet('{RAW}') where json_valid(specialties))""").df()
    sp = sp[sp.unique_id.isin(usable)]
    rows = []
    big = smap[smap.n_facilities >= MIN_FAC]
    for r in big.itertuples():
        targets = [r.service_id] if r.service_id not in ("too_general", "out_of_scope", "not_a_service") else \
            [t for t in str(r.prereq_for).split(";") if t and t != "nan"]
        fac = set(sp[sp.specialty == r.specialty].unique_id)
        for t in targets:
            k = sum((u, t) in pos_pairs for u in fac)
            rows.append(dict(specialty=r.specialty, label=r.service_id, service=t, n=len(fac), text_positive=k,
                             rate=round(k / len(fac), 3)))
    out = pd.DataFrame(rows).sort_values(["service", "rate"], ascending=[True, False])
    out.to_csv(os.path.join(D, "corroboration.csv"), index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()

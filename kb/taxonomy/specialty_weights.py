"""specialty_evidence_weights.csv: how strongly a specialties value supports a service, measured instead of a 0/1 label
(review issue 4: psychiatry, labelled a service, is confirmed by text less often than nephrology, labelled too_general).

For every (value, service) pair where the service is the value's label or is in its prereq_for, the rate is the share
of usable facilities carrying the value that also have positive text evidence for the service (out/lexicon_matches.parquet,
same 'positive' rule as build_lexicon.py). Rates are shrunk toward the pooled rate of their group (label kind x service)
with a Beta prior of strength M, so singletons do not get 0 or 1.

Held-out check: facilities are split in two by md5(unique_id). Rates are fitted on half A and scored on half B by
log loss over (facility, value, service) rows, against the binary interface (one pooled rate per label kind x service,
which is what a 0/1 service vs too_general label can express). The final weights are refitted on all facilities.
Caveat: the rate is a lower bound on support, because text evidence depends on lexicon recall and on what the
facility's pages say. It is corroboration, not proof of an offer.

Run: /Users/karthikvattem/projects/datathon/.venv/bin/python specialty_weights.py
"""
from __future__ import annotations

import hashlib
import json
import math
import os

import duckdb
import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
LOC = "/Users/karthikvattem/projects/datathon/cleaning/geo_identity/facility_location.parquet"
M = 20  # prior strength in pseudo-facilities
NON_SERVICE = {"too_general", "out_of_scope", "not_a_service"}


def split_ids(x: str) -> list[str]:
    return [t for t in str(x).split(";") if t]


def pairs(smap: pd.DataFrame) -> pd.DataFrame:
    """(specialty, service, kind): kind = 'label' when the value is labelled with the service, else 'prereq'."""
    rows = []
    for r in smap.itertuples():
        for s in split_ids(r.service_id):
            if s not in NON_SERVICE:
                rows.append((r.specialty, s, "label"))
        for s in split_ids(r.prereq_for):
            rows.append((r.specialty, s, "prereq"))
    return pd.DataFrame(rows, columns=["specialty", "service", "kind"]).drop_duplicates(["specialty", "service"])


def facility_rows(smap: pd.DataFrame) -> pd.DataFrame:
    usable = set(pd.read_parquet(LOC, columns=["unique_id"]).unique_id)
    sp = duckdb.sql(f"""select distinct unique_id, s as specialty from
        (select unique_id, unnest(from_json(specialties, '["VARCHAR"]')) s from read_parquet('{RAW}') where json_valid(specialties))""").df()
    sp = sp[sp.unique_id.isin(usable)].merge(pairs(smap), on="specialty")
    m = pd.read_parquet(os.path.join(D, "out", "lexicon_matches.parquet"))
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility") & ~m.kind.isin(["staff", "directory"])]
    hit = set(zip(pos.unique_id, pos.service))
    sp["y"] = [(u, s) in hit for u, s in zip(sp.unique_id, sp.service)]
    sp["half"] = sp.unique_id.map(lambda u: int(hashlib.md5(u.encode()).hexdigest(), 16) % 2)
    return sp


def fit(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    grp = rows.groupby(["kind", "service"]).y.agg(k="sum", n="size").reset_index()
    grp["pooled_rate"] = grp.k / grp.n
    per = rows.groupby(["specialty", "service", "kind"]).y.agg(k="sum", n="size").reset_index().merge(
        grp[["kind", "service", "pooled_rate"]], on=["kind", "service"])
    per["weight"] = (per.k + M * per.pooled_rate) / (per.n + M)
    return per, grp


def logloss(p: pd.Series, y: pd.Series) -> float:
    p = p.clip(1e-4, 1 - 1e-4)
    return float(-(y * p.map(math.log) + (1 - y) * (1 - p).map(math.log)).mean())


def main() -> None:
    smap = pd.read_csv(os.path.join(D, "specialty_map.csv"), keep_default_na=False)
    rows = facility_rows(smap)
    a, b = rows[rows.half == 0], rows[rows.half == 1]
    per_a, grp_a = fit(a)
    test = b.merge(per_a[["specialty", "service", "weight"]], on=["specialty", "service"], how="left").merge(
        grp_a[["kind", "service", "pooled_rate"]], on=["kind", "service"], how="left")
    test["pooled_rate"] = test.pooled_rate.fillna(a.y.mean())
    test["weight"] = test.weight.fillna(test.pooled_rate)
    res = {"rows_fit_half": len(a), "rows_test_half": len(b), "test_base_rate": round(float(b.y.mean()), 4),
           "logloss_per_value_weights": round(logloss(test.weight, test.y), 4),
           "logloss_binary_label_interface": round(logloss(test.pooled_rate, test.y), 4),
           "logloss_constant_rate": round(logloss(pd.Series(a.y.mean(), index=test.index), test.y), 4), "prior_strength_M": M}
    per, grp = fit(rows)
    hold = per_a.rename(columns={"k": "k_fit_half", "n": "n_fit_half", "weight": "weight_fit_half"})[
        ["specialty", "service", "k_fit_half", "n_fit_half", "weight_fit_half"]]
    tb = b.groupby(["specialty", "service"]).y.agg(k_test_half="sum", n_test_half="size").reset_index()
    out = per.merge(hold, on=["specialty", "service"], how="left").merge(tb, on=["specialty", "service"], how="left")
    out = out.rename(columns={"k": "k_text_positive", "n": "n_facilities"}).sort_values(["service", "n_facilities"], ascending=[True, False])
    out["weight"] = out.weight.round(4)
    out["pooled_rate"] = out.pooled_rate.round(4)
    out["weight_fit_half"] = out.weight_fit_half.round(4)
    out.to_csv(os.path.join(D, "specialty_evidence_weights.csv"), index=False)
    res["pairs"] = len(out)
    res["group_rates"] = {f"{r.kind}:{r.service}": [int(r.k), int(r.n)] for r in grp.itertuples()}
    json.dump(res, open(os.path.join(D, "out", "specialty_weights_eval.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "group_rates"}, indent=1))
    big = out[out.n_facilities >= 1000][["specialty", "service", "kind", "n_facilities", "k_text_positive", "weight"]]
    print(big.sort_values("weight", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()

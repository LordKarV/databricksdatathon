"""Fresh hand-read samples for validation/claims (fixed seeds; items checked by earlier hand checks are excluded).

python samples.py dump <name>   prints items with context for reading
python samples.py init          writes empty label CSVs under labels/ (never overwrites a file that exists)
Names: attribution, lexicon_precision, lexicon_recall, specialty_map, nonoffer.
"""
from __future__ import annotations

import functools
import glob
import os
import sys

import pandas as pd

import checks as C

SEED_ATTR, SEED_LEXP, SEED_LEXR, SEED_SPEC, SEED_NEG = 9101, 9102, 9103, 9104, 9105
N_PER_LABEL, N_LEXP, N_LEXR, N_SPEC, N_NEG = 20, 40, 40, 40, 30


@functools.lru_cache(None)
def prior_claim_ids() -> frozenset:
    ids = set()
    for p in glob.glob(f"{C.ROOT}/kb/taxonomy/out/handcheck_*.csv") + glob.glob(f"{C.ROOT}/kb/taxonomy/review/*.csv"):
        d = pd.read_csv(p, keep_default_na=False)
        if "claim_id" in d:
            ids |= set(d.claim_id)
    return frozenset(ids)


@functools.lru_cache(None)
def prior_specialties() -> frozenset:
    vals = set()
    for p in glob.glob(f"{C.ROOT}/kb/taxonomy/out/handcheck_specialty*.csv") + glob.glob(f"{C.ROOT}/kb/taxonomy/review/specialty_*.csv"):
        vals |= set(pd.read_csv(p, keep_default_na=False).specialty)
    return frozenset(vals)


def attribution_sample() -> pd.DataFrame:
    c = C.claims()
    c = c[~c.claim_id.isin(prior_claim_ids())]
    return (c.groupby("attribution", group_keys=False).sample(N_PER_LABEL, random_state=SEED_ATTR)
            [["claim_id", "attribution"]].reset_index(drop=True))


def lexicon_precision_sample() -> pd.DataFrame:
    m = C.lex_matches()
    m = m[~m.claim_id.isin(prior_claim_ids())]
    return m.sample(N_LEXP, random_state=SEED_LEXP)[["claim_id", "service"]].reset_index(drop=True)


def lexicon_recall_sample() -> pd.DataFrame:
    c = C.claims()
    un = c[~c.claim_id.isin(set(C.lex_matches().claim_id)) & ~c.claim_id.isin(prior_claim_ids())]
    return un.sample(N_LEXR, random_state=SEED_LEXR)[["claim_id"]].reset_index(drop=True)


def specialty_sample() -> pd.DataFrame:
    """(record, value) rows over usable records: precision weighted by how often a value is attached to a facility."""
    loc = set(pd.read_parquet(f"{C.V1}/facility_location.parquet", columns=["unique_id"]).unique_id)
    sp = C.raw_specialties()
    sp = sp[sp.unique_id.isin(loc)].drop_duplicates()
    sp = sp[~sp.specialty.isin(prior_specialties())]
    return sp.sample(N_SPEC, random_state=SEED_SPEC).reset_index(drop=True)


def nonoffer_sample() -> pd.DataFrame:
    m = C.lex_matches()
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility") & ~m.kind.isin(["staff", "directory"])]
    pos = pos[~pos.claim_id.isin(prior_claim_ids()) & ~pos.claim_id.isin(set(lexicon_precision_sample().claim_id))]
    return pos.sample(N_NEG, random_state=SEED_NEG)[["claim_id", "service"]].reset_index(drop=True)


def _ctx(df: pd.DataFrame) -> pd.DataFrame:
    c = C.claims().set_index("claim_id")
    f = pd.read_parquet(f"{C.V1}/facility_location.parquet", columns=["unique_id", "name", "address_city", "state_final"]).set_index("unique_id")
    out = df.join(c.drop(columns=[x for x in ("attribution",) if x in df]), on="claim_id")
    return out.join(f, on="unique_id")


def dump(name: str) -> None:
    pd.set_option("display.width", 250)
    if name == "attribution":
        d = _ctx(attribution_sample())
        for i, r in enumerate(d.itertuples(), 1):
            print(f"{i}. {r.claim_id} [{r.attribution}] FAC={r.name} ({r.address_city}, {r.state_final}) kind={r.kind}\n   TEXT: {r.text[:400]}\n"
                  f"   self={r.self_names} foreign={r.foreign_names} sib={r.sibling_names} os={r.places_other_state} od={r.places_other_district} ctx={r.context}")
    elif name in ("lexicon_precision", "nonoffer"):
        d = _ctx(lexicon_precision_sample() if name == "lexicon_precision" else nonoffer_sample())
        for i, r in enumerate(d.itertuples(), 1):
            print(f"{i}. {r.claim_id} [{r.service}] FAC={r.name} kind={r.kind} attr={r.attribution}\n   TEXT: {r.text[:400]}")
    elif name == "lexicon_recall":
        d = _ctx(lexicon_recall_sample())
        for i, r in enumerate(d.itertuples(), 1):
            print(f"{i}. {r.claim_id} FAC={r.name} {r.field}: {r.text[:300]}")
    elif name == "specialty_map":
        sm = pd.read_csv(f"{C.TAX}/specialty_map.csv", keep_default_na=False).set_index("specialty")
        d = specialty_sample().join(sm, on="specialty")
        f = pd.read_parquet(f"{C.V1}/facility_location.parquet", columns=["unique_id", "name"]).set_index("unique_id")
        for i, r in enumerate(d.join(f, on="unique_id").itertuples(), 1):
            print(f"{i}. {r.specialty!r} -> {r.service_id} prereq={r.prereq_for} ({r.method}, n={r.n_facilities}) FAC={r.name}")


def init() -> None:
    os.makedirs(C.LAB, exist_ok=True)
    specs = {
        "attribution_80.csv": attribution_sample(),
        "lexicon_precision.csv": lexicon_precision_sample(),
        "lexicon_recall.csv": lexicon_recall_sample().assign(service=""),
        "specialty_map.csv": specialty_sample(),
        "nonoffer_30.csv": nonoffer_sample(),
    }
    for fn, d in specs.items():
        p = os.path.join(C.LAB, fn)
        if not os.path.exists(p):
            d.assign(verdict="", note="").to_csv(p, index=False)


if __name__ == "__main__":
    {"dump": lambda: dump(sys.argv[2]), "init": init}[sys.argv[1]]()

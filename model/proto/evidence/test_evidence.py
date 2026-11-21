"""Evidence tests (spec 4.10) plus contract checks. Run: .venv/bin/python -m pytest -q test_evidence.py
(or plain python: the __main__ block runs every test and prints a summary)."""
import json
import re

import duckdb
import pandas as pd

from atoms import echo_units, pair_families
from common import HERE, RAW

WOCK, ARAV = "3ac5ae50-9ce2-4de3-a13c-d95a4ef218ee", "b8a5401f-42f1-422a-8cd9-686a15b4cb76"
A = pd.read_parquet(HERE / "claim_atoms.parquet")
PF = pd.read_parquet(HERE / "pair_features.parquet")
FF = pd.read_parquet(HERE / "facility_features.parquet")
WS = r"[\t\n\f\r ]"   # RE2 \s, which the DuckDB explode used


def _pair(u, s):
    return PF[(PF.unique_id == u) & (PF.service == s)].iloc[0]


def test_wockhardt():
    a = A[(A.unique_id == WOCK) & (A.service == "dialysis")].set_index("claim_id")
    for c in ["3ac5ae50:proc:17", "3ac5ae50:equi:7"]:
        assert a.at[c, "rejected_reason"] == "names_other_facility" and not a.at[c, "counts_as_own"]
        assert "Nair Hospital" in a.at[c, "named_entity"]
    assert a.at["3ac5ae50:capa:24", "counts_as_own"] and a.at["3ac5ae50:equi:43", "counts_as_own"]
    p = _pair(WOCK, "dialysis")
    assert (p["T"], p["C"], p["bucket"]) == (5, 1, "high")
    f = FF[FF.unique_id == WOCK].iloc[0]
    assert f.vote_name_place == -1 and f.vote_city == -1 and f.vote_pin == 1 and f.vote_coords == 1
    assert f.vote_name_place_p2 == 1 and f.vote_city_p2 == 1


def test_aravind():
    a = A[(A.unique_id == ARAV) & (A.service == "dialysis") & (A.field != "specialties")]
    assert len(a) == 8 and (a.ownership == "unanchored").all() and a.counts_as_own.all()
    p = _pair(ARAV, "dialysis")
    assert p["T"] == 5 and p["S"] == 1 and p["C"] == 0 and p["bucket"] == "high"   # documents the gap: no ownership signal
    assert (PF[PF.unique_id == ARAV].S == 1).all()


def _raw_items() -> dict:
    r = duckdb.sql(f"""select unique_id, procedure, equipment, capability, description, specialties from read_parquet('{RAW}')
        where source='kie' and regexp_matches(unique_id, '^[0-9a-f]{{8}}-')
        qualify row_number() over (partition by unique_id order by unique_id) = 1""").df()
    out = {}
    for row in r.itertuples(index=False):
        for f in ["procedure", "equipment", "capability"]:
            try:
                items = json.loads(getattr(row, f)) if isinstance(getattr(row, f), str) else []
            except ValueError:
                items = []
            items = [re.sub(f"^{WS}+|{WS}+$", "", str(x)) for x in (items if isinstance(items, list) else []) if x is not None]
            out.update({(row.unique_id, f, i): t for i, t in enumerate(x for x in items if x)})
        d = row.description
        if isinstance(d, str) and d != "null":
            parts = [re.sub(f"^{WS}+|{WS}+$", "", x) for x in re.sub(r"([.!?])" + WS + "+", "\\1\x1f", d).split("\x1f")]
            out.update({(row.unique_id, "description", i): t for i, t in enumerate(x for x in parts if x)})
        try:
            sp = json.loads(row.specialties) if isinstance(row.specialties, str) else []
        except ValueError:
            sp = []
        out.update({(row.unique_id, "specialties", i): t for i, t in enumerate(sp if isinstance(sp, list) else [])})
    return out


def test_every_quote_matches_raw():
    raw = _raw_items()
    bad = [r.atom_id for r in A.itertuples() if raw.get((r.unique_id, r.field, r.idx)) != r.text]
    assert not bad, f"{len(bad)} atoms differ from raw, e.g. {bad[:3]}"


def test_echo_collapse():
    base = dict(unique_id="u1", service="dialysis", ownership="unanchored", role="offer", specificity="generic",
                counts_as_own=True, rejected_reason=None, quarantined=False, qty_value=None, support_score=None)
    t = pd.DataFrame([dict(base, atom_id="u1:proc:0|dialysis", claim_id="u1:proc:0", field="procedure", idx=0,
                           text="Provides dialysis treatment"),
                      dict(base, atom_id="u1:capa:3|dialysis", claim_id="u1:capa:3", field="capability", idx=3,
                           text="Provides dialysis treatment.")])
    e = echo_units(t)
    assert e.unit_id.nunique() == 1 and e.is_unit_rep.sum() == 1
    p = pair_families(e, pd.Series(["u1"])).query("service == 'dialysis'").iloc[0]
    assert p["n_units_own"] == 1 and p["n_fields_own"] == 1 and p["T"] == 2
    p0 = pair_families(e, pd.Series(["u1"]), echo=False).query("service == 'dialysis'").iloc[0]
    assert p0["T"] == 4   # without echo collapse the same sentence looks like two-field corroboration


def test_contract_shapes():
    assert len(PF) == 69713 and not PF.duplicated(["unique_id", "service"]).any()
    assert len(FF) == 9959 and FF.unique_id.is_unique
    assert A.atom_id.is_unique and set(A.service) <= set(PF.service.unique())
    assert PF["T"].between(0, 5).all() and PF.C.between(0, 2).all() and PF.P.between(0, 2).all()
    assert PF.X.isna().all()
    cited = {x for s in PF.cited_atom_ids for x in s.split(";") if x}
    assert cited <= set(A[A.is_unit_rep].atom_id)
    rej = {x for s in PF.rejected_atom_ids for x in s.split(";") if x}
    assert rej <= set(A[A.rejected_reason.notna()].atom_id)
    assert (A.counts_as_own == A.rejected_reason.isna()).all()
    assert (PF.t_without_cited <= PF["T"]).all()


if __name__ == "__main__":
    res = {}
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                res[name] = "pass"
            except AssertionError as e:
                res[name] = f"FAIL: {e}"
    print(json.dumps(res, indent=1))
    (HERE / "test_results.json").write_text(json.dumps(res, indent=1))

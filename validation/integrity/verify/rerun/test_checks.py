"""Mutation tests: each check must fail when its defect is planted in an in-memory copy of a table.

Nothing on disk is touched. Run: .venv-viz/bin/python validation/integrity/test_checks.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402
from common import is_null_like, table, wilson  # noqa: E402


def with_table(name: str, mutate):
    """Run with checks.table returning mutate(copy) for one file."""
    real = checks.table

    def fake(f):
        return mutate(real(f).copy()) if f == name else real(f)
    checks.table = fake
    return real


def test_helpers():
    assert is_null_like("null") == "null_string" and is_null_like(" ") == "empty"
    assert is_null_like("[]") == "empty_container" and is_null_like("none") is None and is_null_like("x") is None
    lo, hi = wilson(46, 50)
    assert 0.80 < lo < 0.82 and 0.96 < hi < 0.98
    assert checks._in_india([28.6, 0.0], [77.2, 0.0]).tolist() == [True, False]


def test_primary_key_duplicate_detected():
    real = with_table("derived/v1/facility_location.parquet", lambda d: pd.concat([d, d.head(1)]))
    try:
        assert checks.check_primary_keys()["status"] == "fail"
    finally:
        checks.table = real


def test_unresolved_claim_detected():
    def mut(d):
        d.loc[d.index[0], "claim_id"] = "deadbeef:proc:999"
        return d
    real = with_table("kb/taxonomy/out/lexicon_matches.parquet", mut)
    try:
        assert checks.check_claim_id_fk()["status"] == "fail"
    finally:
        checks.table = real


def test_probability_out_of_range_detected():
    def mut(d):
        d.loc[d.index[0], "score"] = 1.5
        return d
    real = with_table("derived/v1/data_point_scores.parquet", mut)
    try:
        assert checks.check_probabilities()["status"] == "fail"
    finally:
        checks.table = real


def test_ranking_point_outside_india_detected():
    def mut(d):
        d.loc[d.index[0], "loc_lat"] = np.float64(51.5)
        return d
    real = with_table("derived/v1/facility_location.parquet", mut)
    try:
        assert checks.check_lat_lon_bounds()["status"] == "fail"
    finally:
        checks.table = real


def test_unknown_enum_detected():
    def mut(d):
        d.loc[d.index[0], "status"] = "verified_maybe"
        return d
    real = with_table("derived/v1/data_point_scores.parquet", mut)
    try:
        assert checks.check_enums()["status"] == "fail"
    finally:
        checks.table = real


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} tests passed")

"""Tests for the evidence reader's data and rule code. No model weights and no network needed.
Run: .venv/bin/python -m pytest model/reader/test_reader.py -q
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402
import evaluate  # noqa: E402


@pytest.fixture(scope="module")
def lex():
    return common.Lexicon()


def test_lexicon_loads_all_services_with_labels(lex):
    assert len(lex.services) == 37 and "dialysis" in lex.services
    assert all(lex.label[s] for s in lex.services)
    assert lex.canon("trauma_emergency") == "trauma_care" and lex.canon("csection") == "emergency_csection"
    assert lex.canon("dialysis") == "dialysis"


def test_rule_offers_follows_the_lexicon(lex):
    assert lex.rule_offers("The hospital has a 10 bed dialysis unit", "dialysis", "specific") == 1
    assert lex.rule_offers("Dialysis is not available at this centre", "dialysis", "specific") == 0     # negation cue
    assert lex.rule_offers("Patients needing dialysis are referred to the district hospital", "dialysis", "specific") == 0
    assert lex.rule_offers("A dialysis unit is planned and under construction", "dialysis", "specific") == 0
    assert lex.rule_offers("Dialysis profile test available in the lab", "dialysis", "specific") == 0   # exclude pattern
    assert lex.rule_offers("The hospital has a 10 bed dialysis unit", "dialysis", "staff") == 0         # sentence kind
    assert lex.rule_offers("The hospital has an eye clinic", "dialysis", "specific") == 0
    assert lex.match("Dialysis is not available", "dialysis") == (True, True)


def test_context_string():
    assert common.context("City Hospital", "Pune", "dialysis") == "City Hospital, Pune | dialysis"
    assert common.context("City Hospital", "Pune", "") == "City Hospital, Pune | any service"


def test_wilson_and_prf():
    assert evaluate.wilson(0, 0) == [None, None]
    lo, hi = evaluate.wilson(8, 10)
    assert 0.44 < lo < 0.5 and 0.94 < hi < 0.98
    y = np.array([0, 0, 0, 1, 1, 1, 1, 1])
    pred = np.array([0, 0, 1, 1, 1, 1, 1, 0])
    r = evaluate.prf(y, pred, 0)
    assert (r["tp"], r["fp"], r["fn"]) == (2, 1, 1) and r["precision"] == pytest.approx(0.667, abs=1e-3)
    assert evaluate.summarise(y, pred)["accuracy"] == 0.75
    same = evaluate.paired_bootstrap(y, pred, pred, 0, n=50)
    assert same["f1_reader_minus_rules"] == 0 and same["ci95"] == [0.0, 0.0]


def test_calibration_bins_sum_to_n():
    y = np.array([0, 1, 1, 0, 1, 1.0])
    p = np.array([0.1, 0.9, 0.8, 0.3, 0.6, 1.0])
    c = evaluate.calibration(y, p)
    assert sum(b["n"] for b in c["bins"]) == 6 and 0 <= c["ece"] <= 1


def test_eval_set_is_well_formed_and_documented():
    e = pd.read_csv(HERE / "eval" / "eval_set.csv")
    assert set(e.target) == {"about_this", "offers"} and set(e.label) <= {-1, 0, 1}
    assert e.in_claims.all() and e.source_file.notna().all() and e.label_rule.notna().all()
    use = e[e.label >= 0]
    assert len(use) == json.loads((HERE / "eval" / "eval_set_stats.json").read_text())["usable"]
    assert not use.duplicated(["claim_id", "target", "service_canonical"]).any()
    assert (use[use.target == "offers"].service_canonical.notna()).mean() > 0.95
    assert not set(use.service_canonical.dropna()) & {"trauma_emergency", "trauma", "csection", "burns"}
    # the inverted sets: a vetoed sentence judged 'correct' is a non-offer
    veto = e[e.label_rule.str.startswith("clause_veto")]
    assert len(veto) > 0 and set(veto[veto.original_label == "True"].label) == {0}


def test_training_data_excludes_held_out_facilities():
    path = HERE / "data" / "train.parquet"
    if not path.exists():
        pytest.skip("training data not built (run make_data.py)")
    d = pd.read_parquet(path, columns=["unique_id", "split", "y_about", "y_offers", "tag"])
    splits = json.loads((common.ROOT / "model/gold/splits.json").read_text())
    test = {p["unique_id"] for p in splits["pairs"] if p.get("split") == "test"}
    ev = set(pd.read_csv(HERE / "eval" / "eval_set.csv").unique_id.dropna())
    assert len(test) == 88 and not set(d.unique_id) & test and not set(d.unique_id) & ev
    assert not set(d[d.split == "train"].unique_id) & set(d[d.split == "val"].unique_id)   # grouped by facility
    assert set(d.y_about) <= {-1, 0, 1} and set(d.y_offers) <= {-1, 0, 1}
    assert ((d.y_about >= 0) | (d.y_offers >= 0)).all()


def test_reader_scores_schema():
    path = common.ROOT / "derived" / "v2" / "reader_scores.parquet"
    if not path.exists():
        pytest.skip("scores not written yet (run score.py)")
    s = pd.read_parquet(path)
    assert list(s.columns) == ["claim_id", "service_id", "p_about_this", "p_offers", "top_tokens_about", "top_tokens_offers", "model_version"]
    assert s.p_about_this.between(0, 1).all() and s.p_offers.dropna().between(0, 1).all()
    assert s[s.service_id == ""].p_offers.isna().all() and s[s.service_id != ""].p_offers.notna().all()
    assert not s.duplicated(["claim_id", "service_id"]).any()
    assert path.stat().st_size < 50e6 and s.model_version.nunique() == 1

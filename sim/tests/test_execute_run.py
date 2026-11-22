"""The temporary executor follows the interface; the runner writes the #92 tables; reports are observations only."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from sim import _stub_execute as X
from sim.assumptions import DEFAULT
from sim.interface import EVENT_COLUMNS, EVENT_KINDS, N_OPTIONS, Case, Step, Truth
from sim.reports import Beliefs, aggregate, district_summary, reports_from_events
from sim.run import simulate

CASE = Case("s0w1c00000", 0, 25.6, 85.1, "BIHAR", "PATNA", "dialysis", "planned", 120, 600, True, True)


def truth(**rows: dict) -> Truth:
    base = {"exists": True, "offers": True, "phone_ok": True, "open_now_p": 1.0, "accept_p": 1.0,
            "true_lat": 25.61, "true_lon": 85.12}
    df = pd.DataFrame([{"unique_id": k, "service": "dialysis", **base, **v} for k, v in rows.items()])
    return Truth(df, "S1", 0)


def test_treated_at_first_good_facility() -> None:
    ev = X.run_case(CASE, [Step("a", True), Step("b", True)], truth(a={}, b={}), DEFAULT)
    assert [e["kind"] for e in ev] == ["call", "travel", "arrive", "treated"]
    assert ev[0]["outcome"] == "yes" and ev[-1]["facility_id"] == "a"
    assert all(e["kind"] in EVENT_KINDS for e in ev)


def test_turned_away_then_next() -> None:
    a = replace(DEFAULT, wrong_yes_p=1.0)  # every "no" becomes a wrong "yes"
    ev = X.run_case(CASE, [Step("a", True), Step("b", False)], truth(a={"offers": False}, b={}), a)
    kinds = [(e["kind"], e["outcome"]) for e in ev]
    assert ("turned_away", "no_service") in kinds and kinds[-1] == ("treated", "ok")
    assert sum(k == "travel" for k, _ in kinds) == 2


def test_not_found_and_caps() -> None:
    steps = [Step(f"f{i}", False) for i in range(5)]
    ev = X.run_case(CASE, steps, truth(**{f"f{i}": {"exists": False} for i in range(5)}), DEFAULT)
    assert sum(e["kind"] == "travel" for e in ev) == N_OPTIONS
    assert ev[-1]["kind"] == "gave_up" and ev[-1]["outcome"] == "list_exhausted"


def test_no_options_and_outages() -> None:
    c = replace(CASE, has_data=False, has_phone_signal=False)
    assert [(e["kind"], e["outcome"]) for e in X.run_case(c, [], truth(a={}), DEFAULT)] == [
        ("outage", "no_data"), ("gave_up", "no_options")]
    ev = X.run_case(c, [Step("a", True)], truth(a={}), DEFAULT)
    assert ("outage", "no_signal") in [(e["kind"], e["outcome"]) for e in ev]


def test_common_random_numbers() -> None:
    assert X.draw("c1", "f1", "open") == X.draw("c1", "f1", "open")
    assert X.draw("c1", "f1", "open") != X.draw("c1", "f2", "open")
    a = X.generate_cases(4, 20, ["BIHAR"], ["dialysis", "trauma_emergency"])
    assert a == X.generate_cases(4, 20, ["BIHAR"], ["dialysis", "trauma_emergency"])
    assert all(c.urgency in ("emergency", "planned") and c.state == "BIHAR" for c in a)


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("simout")
    return simulate(["S0", "S2"], [0, 1], 20, ["BIHAR"], ["dialysis", "trauma_emergency"], out, n_boot=50,
                    sweep=True, with_reports=True, verbose=False) | {"out": out}


def test_runner_tables(run: dict) -> None:
    out: Path = run["out"]
    ev = pd.read_parquet(out / "events" / f"{run['run_id']}.parquet")
    assert list(ev.columns) == list(EVENT_COLUMNS)
    assert set(ev.kind) <= set(EVENT_KINDS)
    assert (out / "truth" / "S0_1.parquet").is_file()
    m = pd.read_parquet(out / "metrics.parquet")
    assert set(m.policy) == {"app", "app_offline", "nearest", "nearest_call_first", "best_on_paper"}
    assert set(m.state) == {"BIHAR", "ALL"} and (m.label.str.startswith("SIMULATED")).all()
    for c in ("treated_in_window", "wasted_trips_per_case", "calls_per_case", "unsafe_first_stop", "gave_up"):
        assert (m[f"{c}_lo"] <= m[c] + 1e-9).all() and (m[c] <= m[f"{c}_hi"] + 1e-9).all()
    s = pd.read_parquet(out / "sensitivity.parquet")
    assert set(s.knob) == {"all", "accept_p", "phone_ok_p", "wrong_yes_p", "open_now_p"}


def test_same_cases_for_every_policy(run: dict) -> None:
    oc = run["outcomes"]
    per = oc.groupby(["scenario", "policy"]).case_id.apply(frozenset)
    assert per.nunique() == 1


def test_reports_are_observations(run: dict) -> None:
    rep = reports_from_events(run["events"], run["cases"])
    assert set(rep.observation) <= {"phone_yes", "phone_no", "phone_no_answer", "treated", "not_found", "no_service",
                                    "closed", "refused"}
    agg = aggregate(rep)
    assert (agg.successes >= 0).all() and agg.simulated.all()
    one = agg.iloc[0]
    b = Beliefs(agg[(agg.scenario == one.scenario) & (agg.seed == one.seed)])
    assert b.posterior("nobody", "dialysis", 0.4, 4) == pytest.approx(0.4)
    expect = (0.4 * 4 + one.successes) / (4 + one.successes + one.failures)
    assert b.posterior(one.facility_id, one.service, 0.4, 4) == pytest.approx(expect)
    d = district_summary(run["events"], run["cases"])
    assert (d.treated_in_window <= d.cases).all() and (run["out"] / "network" / "facility_reports.parquet").is_file()

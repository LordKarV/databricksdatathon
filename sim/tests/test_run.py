"""The runner on the lead's world and executor writes the #92 tables; reports are observations only."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sim import world
from sim.interface import EVENT_COLUMNS, EVENT_KINDS
from sim.reports import Beliefs, aggregate, district_summary, reports_from_events
from sim.run import make_cases, simulate, sweep_configs

SCEN = ["S0-high", "S0-low", "S2"]


def test_cases_come_from_the_world_filtered() -> None:
    c = make_cases(3, 4, ["BIHAR"], ["dialysis"])
    w = world.cases(3, ("BIHAR",), 4)
    pd.testing.assert_frame_equal(c, w[w.service == "dialysis"].reset_index(drop=True))
    with pytest.raises(SystemExit):
        make_cases(3, 4, ["BIHAR"], ["mri"])


def test_sweep_uses_the_world_knobs() -> None:
    cfg = sweep_configs()
    assert cfg[0] == ("all", "mid", world.MID)
    assert {(k, lv) for k, lv, _ in cfg[1:]} == {(k, lv) for k in world.KNOBS for lv in ("low", "high")}
    for k, lv, kn in cfg[1:]:
        assert kn[k] == world.KNOBS[k][lv] and all(kn[o] == world.MID[o] for o in world.MID if o != k)


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("simout")
    return simulate(SCEN, [0, 1], 6, ["BIHAR"], ["dialysis", "trauma_emergency"], out, n_boot=50, sweep=True,
                    with_reports=True, verbose=False) | {"out": out}


def test_runner_tables(run: dict) -> None:
    out: Path = run["out"]
    ev = pd.read_parquet(out / "events" / f"{run['run_id']}.parquet")
    assert list(ev.columns) == list(EVENT_COLUMNS)
    assert set(ev.kind) <= set(EVENT_KINDS)
    assert set(ev.scenario) == set(SCEN)
    m = pd.read_parquet(out / "metrics.parquet")
    assert set(m.policy) == {"app", "app_offline", "nearest", "nearest_call_first", "best_on_paper"}
    assert set(m.state) == {"BIHAR", "ALL"} and (m.label.str.startswith("SIMULATED")).all()
    for c in ("treated_in_window", "wasted_trips_per_case", "calls_per_case", "unsafe_first_stop", "gave_up"):
        assert (m[f"{c}_lo"] <= m[c] + 1e-9).all() and (m[c] <= m[f"{c}_hi"] + 1e-9).all()
    s = pd.read_parquet(out / "sensitivity.parquet")
    assert set(s.knob) == {"all", *world.KNOBS} and set(s.scenario) == set(SCEN)


def test_truth_files_are_the_world_truth(run: dict) -> None:
    for sc in ("S0-high", "S0-low"):
        t = pd.read_parquet(run["out"] / "truth" / f"{sc}_1.parquet")
        pd.testing.assert_frame_equal(t, world.truth_table(sc, 1))


def test_same_cases_for_every_policy(run: dict) -> None:
    oc = run["outcomes"]
    per = oc.groupby(["scenario", "policy"]).case_id.apply(frozenset)
    assert per.nunique() == 1


def test_s0_bounds_order(run: dict) -> None:
    """S0-low offers less than S0-high from the same uniforms, so nearest + call first treats no more in it."""
    oc = run["outcomes"]
    ncf = oc[oc.policy == "nearest_call_first"].groupby("scenario").treated.sum()
    assert ncf["S0-low"] <= ncf["S0-high"]


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

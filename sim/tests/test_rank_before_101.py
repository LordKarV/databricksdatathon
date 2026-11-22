"""app_before_101: the app under the emergency order before PR #101, without changing the app (issue #92)."""
from __future__ import annotations

import math
import sys

import pandas as pd
import pytest

from sim import world
from sim.app_adapter import AppAdapter, ensure_built, rank_before_101
from sim.interface import N_OPTIONS, STATES
from sim.policies_app import DIAGNOSTIC, POLICIES, context
from sim.run import choose_all, policy_table

TRAUMA = "trauma_emergency"


@pytest.fixture(scope="module")
def app() -> AppAdapter:
    ensure_built(list(STATES))
    return AppAdapter()


@pytest.fixture(scope="module")
def before(app: AppAdapter) -> AppAdapter:
    return context(app)["app_before_101"]


@pytest.fixture(scope="module")
def cases() -> pd.DataFrame:
    c = world.cases(7, STATES, 12)
    return c[c.has_data].reset_index(drop=True)


def engine_module(app: AppAdapter):
    return sys.modules[type(app.engine).__module__]


def old_order(app: AppAdapter, lat: float, lon: float) -> list[str]:
    """The pre-#101 rule written out here: value = p x exp(-minutes / 45) best first, top N_OPTIONS, and a likely
    listing that missed the top slots takes the last one (Engine.plan)."""
    pool, _ = app.engine._ranked(TRAUMA, round(lat, 3), round(lon, 3))  # emergency rows carry p, not the product
    pool = sorted(pool, key=lambda r: -r[0] * math.exp(-r[1] / app.time_scale(TRAUMA)))
    chosen = pool[:N_OPTIONS]
    likely = next((r for r in pool if r[4] == "likely"), None)
    if likely and likely not in chosen:
        chosen = chosen[: N_OPTIONS - 1] + [likely]
    return [app.engine.fac["id"][r[2].fi] for r in chosen]


def ids(opts: list[dict]) -> list[str]:
    return [o["facility_id"] for o in opts]


def test_the_patch_is_scoped_and_restored(app: AppAdapter) -> None:
    mod = engine_module(app)
    assert mod.NEAREST_FIRST == {"emergency"}
    with rank_before_101(app.engine):
        assert mod.NEAREST_FIRST == set()
    assert mod.NEAREST_FIRST == {"emergency"}
    with pytest.raises(RuntimeError), rank_before_101(app.engine):
        raise RuntimeError
    assert mod.NEAREST_FIRST == {"emergency"}


def test_default_app_is_unchanged(app: AppAdapter, before: AppAdapter, cases: pd.DataFrame) -> None:
    """The default "app" policy still answers with the shipped engine's current plan, even after app_before_101 ran
    on the same engine object, and app_before_101 is not in the minimum run."""
    assert "app_before_101" not in POLICIES and "app_before_101" in DIAGNOSTIC
    assert set(policy_table(app)) == {"app", "app_offline", "nearest", "nearest_call_first", "best_on_paper"}
    for c in cases.itertuples():
        before.plan(c.service, c.lat, c.lon)
        fresh = app.engine.plan(c.service, round(c.lat, 3), round(c.lon, 3), None, "pin")
        assert ids(app.options(c.service, c.lat, c.lon)) == ids(fresh["options"])
        if c.service == TRAUMA and fresh["options"]:
            assert app.plan(c.service, c.lat, c.lon)["rank_rule"]["code"] == "nearest_plausible"


def test_before_101_reproduces_the_old_order(app: AppAdapter, before: AppAdapter, cases: pd.DataFrame) -> None:
    trauma = cases[cases.service == TRAUMA]
    differs = 0
    for c in trauma.itertuples():
        got = before.options(TRAUMA, c.lat, c.lon)
        assert ids(got) == old_order(app, c.lat, c.lon)
        if got:
            assert before.plan(TRAUMA, c.lat, c.lon)["rank_rule"]["code"] == "evidence_and_time"
        differs += ids(got) != ids(app.options(TRAUMA, c.lat, c.lon))
    assert differs > 0, "the old and new emergency orders never differ on these cases"


def test_planned_care_is_the_same_under_both(app: AppAdapter, before: AppAdapter, cases: pd.DataFrame) -> None:
    for c in cases[cases.service == "dialysis"].itertuples():
        assert ids(before.options("dialysis", c.lat, c.lon)) == ids(app.options("dialysis", c.lat, c.lon))


def test_before_101_policy_runs_only_when_named(app: AppAdapter, cases: pd.DataFrame) -> None:
    table = policy_table(app, ["app_before_101", "app", "nearest_call_first"])
    assert list(table) == ["app_before_101", "app", "nearest_call_first"]
    steps = choose_all(cases.head(6), table)
    assert all(s["call_first"] for per in steps["app_before_101"].values() for s in per)
    with pytest.raises(SystemExit):
        policy_table(app, ["no_such_policy"])

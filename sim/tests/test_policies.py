"""Policies never see the truth (#92 rule 1), no TEST labels (#51), and the engine adapter's contract with the app."""
from __future__ import annotations

import ast
import re
import subprocess
import sys

import pandas as pd
import pytest

from sim import execute, policies_baseline, world
from sim.app_adapter import AppAdapter, ensure_built
from sim.interface import N_OPTIONS, ROOT, STATES, TRUTH_COLUMNS, Case, Step
from sim.policies_app import FUTURE, POLICIES
from sim.run import app_steps, assert_no_truth, choose_all, policy_table

POLICY_MODULES = ["sim.policies_app", "sim.policies_baseline", "sim.app_adapter", "sim.reports"]
TRUTH_NAMES = {"truth_table", "write_truth", "index_truth", "run_case", "TRUTH_COLS", "TRUTH_COLUMNS", "s0_rates",
               "s2_rates"}


@pytest.mark.parametrize("module", POLICY_MODULES)
def test_policy_module_does_not_import_the_executor(module: str) -> None:
    code = f"import sys; import {module}; sys.exit(1 if 'sim.execute' in sys.modules else 0)"
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"{module} imports sim.execute: {r.stderr[-500:]}"


@pytest.mark.parametrize("module", POLICY_MODULES)
def test_policy_source_never_names_truth(module: str) -> None:
    """No import of the executor, no call into the world's truth, and no path to the truth tables (docstrings
    excepted)."""
    path = ROOT / (module.replace(".", "/") + ".py")
    tree = ast.parse(path.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [getattr(node, "module", None) or ""] + [a.name for a in node.names]
            assert not any(n == "sim.execute" or n == "execute" for n in names), (module, names)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            assert not any(w in node.value for w in ("out/truth", "truth/")), (module, node.value)
        if isinstance(node, ast.Name):
            assert node.id not in TRUTH_NAMES, (module, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in TRUTH_NAMES, (module, node.attr)


def test_never_reads_test_labels() -> None:
    """No sim module names the sealed TEST labels or the custodian's cache (#51)."""
    bad = re.compile(r"test_labels|test_sample|test_predictions|referral-saathi-gold-v3|\.cache/")
    for path in (ROOT / "sim").glob("*.py"):
        assert not bad.search(path.read_text()), path.name


def test_a_ctx_with_truth_is_refused() -> None:
    t = pd.DataFrame({c: [] for c in TRUTH_COLUMNS})
    with pytest.raises(AssertionError):
        assert_no_truth({"app": object(), "deep": {"x": t}})
    assert_no_truth(policies_baseline.context())


@pytest.fixture(scope="module")
def app() -> AppAdapter:
    ensure_built(list(STATES))
    return AppAdapter()


@pytest.fixture(scope="module")
def cases() -> pd.DataFrame:
    return world.cases(5, STATES, 10)


def test_app_policy_is_wrapped_into_step_dicts(app: AppAdapter, cases: pd.DataFrame) -> None:
    c = cases.to_dict("records")[0]
    out = app_steps(POLICIES["app"], c, {"app": app})
    direct = POLICIES["app"].choose(Case(**c), {"app": app})
    assert out == [{"facility_id": s.facility_id, "call_first": s.call_first, "note": s.note} for s in direct]
    assert all(isinstance(s, Step) for s in direct)


def test_adapter_matches_engine_plan(app: AppAdapter, cases: pd.DataFrame) -> None:
    """Contract: the adapter returns Engine.plan's options unchanged, in order, at most N_OPTIONS, and caches."""
    for c in cases.head(15).itertuples():
        plan = app.engine.plan(c.service, round(c.lat, 3), round(c.lon, 3), None, "pin")
        opts = app.options(c.service, c.lat, c.lon)
        assert [o["facility_id"] for o in opts] == [o["facility_id"] for o in plan["options"]]
        assert [o["band"] for o in opts] == [o["band"] for o in plan["options"]]
        assert len(opts) <= N_OPTIONS
        assert app.plan(c.service, c.lat, c.lon) is app.plan(c.service, c.lat + 1e-5, c.lon)  # cached


def test_pack_options_are_known_facilities(app: AppAdapter, cases: pd.DataFrame) -> None:
    ids = set(app.ids)
    for c in cases.head(15).itertuples():
        opts = app.pack_options(c.state, c.service, c.lat, c.lon)
        assert opts and all(o["facility_id"] in ids for o in opts)
        assert [o["km_straight"] for o in opts] == sorted(o["km_straight"] for o in opts)


def test_policies_follow_the_interface(app: AppAdapter, cases: pd.DataFrame) -> None:
    steps = choose_all(cases, policy_table(app))
    assert set(steps) == {"app", "app_offline", *policies_baseline.POLICIES}
    listed = execute._listed()
    tix = execute.index_truth(world.truth_table("S1", 5))
    for name, per_case in steps.items():
        for c in cases.itertuples():
            st = per_case[c.case_id]
            assert len(st) <= N_OPTIONS, name
            assert all(set(s) == {"facility_id", "call_first", "note"} for s in st), name
            assert len({s["facility_id"] for s in st}) == len(st), name
            assert all(s["facility_id"] in listed and (s["facility_id"], c.service) in tix for s in st), name
            if name.startswith("app") or name == "nearest_call_first":
                assert all(s["call_first"] for s in st), name
            if name in ("nearest", "best_on_paper"):
                assert not any(s["call_first"] for s in st), name
            if name == "app" and c.has_data:
                assert [s["facility_id"] for s in st] == [o["facility_id"]
                                                          for o in app.options(c.service, c.lat, c.lon)]
    assert "app_plus_reports" in FUTURE and "app_plus_reports" not in POLICIES

"""Policies never see the truth (#92 rule 1), and the engine adapter's contract with the shipped app."""
from __future__ import annotations

import ast
import subprocess
import sys

import pandas as pd
import pytest

from sim import _stub_baselines, _stub_execute
from sim.app_adapter import AppAdapter, ensure_built
from sim.interface import N_OPTIONS, ROOT, STATES, Truth
from sim.policies_app import FUTURE, POLICIES
from sim.run import choose_all

POLICY_MODULES = ["sim.policies_app", "sim._stub_baselines", "sim.app_adapter", "sim.reports"]
if (ROOT / "sim" / "policies_baseline.py").is_file():
    POLICY_MODULES.append("sim.policies_baseline")
TRUTH_WORDS = ("sim.truth", "sim/out/truth", "TRUTH_DIR", "Truth", "build_truth", "out/truth")


@pytest.mark.parametrize("module", POLICY_MODULES)
def test_policy_module_does_not_import_truth(module: str) -> None:
    code = (f"import sys; import {module}; "
            "bad = [m for m in sys.modules if m == 'sim.truth' or m.startswith('sim.truth.')]; "
            "sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"{module} imports sim.truth: {r.stderr[-500:]}"


@pytest.mark.parametrize("module", POLICY_MODULES)
def test_policy_source_never_names_truth(module: str) -> None:
    """No import of the truth module and no path to the truth tables, in code or strings (docstrings excepted)."""
    path = ROOT / (module.replace(".", "/") + ".py")
    tree = ast.parse(path.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [getattr(node, "module", None) or ""] + [a.name for a in node.names]
            assert not any(w in n for n in names for w in TRUTH_WORDS), (module, names)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            assert not any(w in node.value for w in ("out/truth", "truth/")), (module, node.value)
        if isinstance(node, ast.Name):
            assert node.id not in ("Truth", "TRUTH_DIR", "build_truth"), (module, node.id)


@pytest.fixture(scope="module")
def app() -> AppAdapter:
    ensure_built(list(STATES))
    return AppAdapter()


@pytest.fixture(scope="module")
def cases() -> list:
    return _stub_execute.generate_cases(5, 40, list(STATES), ["dialysis", "trauma_emergency"])


def test_choose_all_refuses_truth_in_ctx(app: AppAdapter, cases: list) -> None:
    t = Truth(pd.DataFrame({c: [] for c in ("unique_id", "service", "exists", "offers", "phone_ok", "open_now_p",
                                            "accept_p", "true_lat", "true_lon")}), "S1", 0)
    with pytest.raises(AssertionError):
        choose_all(cases[:1], {"app": POLICIES["app"]}, {"app": {"app": app, "truth": t}})


def test_adapter_matches_engine_plan(app: AppAdapter, cases: list) -> None:
    """Contract: the adapter returns Engine.plan's options unchanged, in order, at most N_OPTIONS, and caches."""
    for c in cases[:15]:
        plan = app.engine.plan(c.service, round(c.lat, 3), round(c.lon, 3), None, "pin")
        opts = app.options(c.service, c.lat, c.lon)
        assert [o["facility_id"] for o in opts] == [o["facility_id"] for o in plan["options"]]
        assert [o["band"] for o in opts] == [o["band"] for o in plan["options"]]
        assert len(opts) <= N_OPTIONS
        assert app.plan(c.service, c.lat, c.lon) is app.plan(c.service, c.lat + 1e-5, c.lon)  # cached


def test_pack_options_are_known_facilities(app: AppAdapter, cases: list) -> None:
    ids = set(app.ids)
    for c in cases[:15]:
        opts = app.pack_options(c.state, c.service, c.lat, c.lon)
        assert opts and all(o["facility_id"] in ids for o in opts)
        assert [o["km_straight"] for o in opts] == sorted(o["km_straight"] for o in opts)


def test_policies_follow_the_interface(app: AppAdapter, cases: list) -> None:
    pols = {**POLICIES, **_stub_baselines.POLICIES}
    steps = choose_all(cases, pols, {k: {"app": app} for k in pols})
    for name, per_case in steps.items():
        for c, st in zip(cases, per_case, strict=True):
            assert len(st) <= N_OPTIONS, name
            assert len({s.facility_id for s in st}) == len(st), name
            if name.startswith("app") or name == "nearest_call_first":
                assert all(s.call_first for s in st), name
            if name in ("nearest", "best_on_paper"):
                assert not any(s.call_first for s in st), name
            if name == "app" and c.has_data:
                assert [s.facility_id for s in st] == [o["facility_id"] for o in app.options(c.service, c.lat, c.lon)]
    assert "app_plus_reports" in FUTURE and "app_plus_reports" not in POLICIES

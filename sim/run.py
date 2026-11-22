"""Monte Carlo runner for the simulated referral world (issue #92). Every number it writes is SIMULATED.

    .venv-app/bin/python -m sim.run --scenarios S0,S1,S2,S3 --seeds 20 --cases-per-seed 200 \
        --states BIHAR,"UTTAR PRADESH" --services dialysis,trauma_emergency

Per seed: one case set (sim.world, else the stub) shared by every policy and scenario; each policy chooses its steps
once (choices never depend on truth); then each scenario's truth table resolves them (sim.execute, else the stub).
Writes under --out (default sim/out, git-ignored):
- truth/<scenario>_<seed>.parquet, events/<run_id>.parquet, cases/<run_id>.parquet;
- metrics.parquet: one row per policy x scenario x state (and ALL) x service x urgency, each metric with a
  seed-bootstrap 90% interval;
- sensitivity.parquet (--sweep): app minus nearest_call_first, treated within window, per swept assumption level.
Policies in the minimum run: app, app_offline, nearest, nearest_call_first, best_on_paper. app_plus_reports and the
planner route are future work (--with-reports, --include-planner).
"""
from __future__ import annotations

import argparse
import importlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sim import _stub_baselines, _stub_execute
from sim.app_adapter import AppAdapter, ensure_built
from sim.assumptions import DEFAULT, Assumptions, sweep_configs
from sim.interface import EVENT_COLUMNS, OUT, SCENARIOS, SERVICES, STATES, Case, Step, Truth
from sim.policies_app import FUTURE, POLICIES
from sim.truth import build_truth

LABEL = "SIMULATED - not field results"
METRICS = ("treated_in_window", "median_min_to_care", "wasted_trips_per_case", "calls_per_case", "unsafe_first_stop",
           "gave_up")
SHARE = ("treated_in_window", "wasted_trips", "calls", "unsafe_first_stop", "gave_up")
COMPARE = ("app", "nearest_call_first")  # the sweep's comparison (#92 review)
CI = (5, 95)


# ---------------------------------------------------------------------------------------------------------------------
# Backends: the real world / executor / baselines when they exist, else the temporary stubs
def _load(module: str, name: str, fallback: Any) -> tuple[Any, str]:
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name != module:
            raise
        print(f"note: {module} not found; using the temporary stand-in in sim/_stub_*.py")
        return fallback, "stub"
    if not hasattr(mod, name):
        raise SystemExit(f"{module} exists but has no {name}: see the contract in sim/interface.py")
    return getattr(mod, name), module


def backends(include_planner: bool = False) -> dict[str, Any]:
    gen, world = _load("sim.world", "generate_cases", _stub_execute.generate_cases)
    run_case, executor = _load("sim.execute", "run_case", _stub_execute.run_case)
    baselines, bsrc = _load("sim.policies_baseline", "POLICIES", _stub_baselines.POLICIES)
    make_ctx = None
    if bsrc != "stub":
        make_ctx = getattr(importlib.import_module("sim.policies_baseline"), "make_context", None)
    baselines = {k: v for k, v in baselines.items() if include_planner or "planner" not in k}
    return {"generate_cases": gen, "run_case": run_case, "baselines": baselines, "make_context": make_ctx,
            "sources": {"world": world, "executor": executor, "baselines": bsrc}}


# ---------------------------------------------------------------------------------------------------------------------
def choose_all(cases: list[Case], policies: dict[str, Any], ctxs: dict[str, dict]) -> dict[str, list[list[Step]]]:
    """Every policy's steps for every case. Truth is never in a policy's ctx."""
    for name, ctx in ctxs.items():
        if any(isinstance(v, Truth) for v in ctx.values()):
            raise AssertionError(f"policy {name} was handed the truth")
    return {name: [pol.choose(c, ctxs[name]) for c in cases] for name, pol in policies.items()}


def execute(cases: list[Case], steps: dict[str, list[list[Step]]], truth: Truth, run_case: Callable,
            a: Assumptions, run_id: str) -> pd.DataFrame:
    rows = []
    for policy, per_case in steps.items():
        for c, st in zip(cases, per_case, strict=True):
            for e in run_case(c, st, truth, a):
                rows.append({"run_id": run_id, "scenario": truth.scenario, "seed": c.seed, "policy": policy,
                             "case_id": c.case_id, **e})
    return pd.DataFrame(rows, columns=list(EVENT_COLUMNS))


def case_frame(cases: list[Case]) -> pd.DataFrame:
    return pd.DataFrame([c.__dict__ for c in cases])


def outcomes(events: pd.DataFrame, cases: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """One row per (scenario, seed, policy, case): treated, minutes to care, in window, wasted trips, calls,
    unsafe first stop (the first place travelled to does not exist or does not offer the service), gave up."""
    keys = ["scenario", "seed", "policy", "case_id"]
    base = events[keys].drop_duplicates()
    treated = events[events.kind == "treated"].groupby(keys).t_min.min().rename("min_to_care")
    wasted = events[events.kind == "turned_away"].groupby(keys).size().rename("wasted_trips")
    calls = events[events.kind == "call"].groupby(keys).size().rename("calls")
    gave = events[events.kind == "gave_up"].groupby(keys).size().rename("gave_up")
    first = events[events.kind == "travel"].groupby(keys).facility_id.first().rename("first_stop").reset_index()
    first = first.merge(cases[["case_id", "service"]], on="case_id").merge(
        truth[["scenario", "unique_id", "service", "exists", "offers"]].rename(columns={"unique_id": "first_stop"}),
        on=["scenario", "first_stop", "service"], how="left")
    first["unsafe_first_stop"] = ~(first.exists.fillna(False).astype(bool) & first.offers.fillna(False).astype(bool))
    out = base.join(treated, on=keys).join(wasted, on=keys).join(calls, on=keys).join(gave, on=keys)
    out = out.merge(first[[*keys, "unsafe_first_stop"]], on=keys, how="left").merge(
        cases[["case_id", "state", "district", "service", "urgency", "window_min", "has_data"]], on="case_id")
    out["treated"] = out.min_to_care.notna()
    out["treated_in_window"] = out.min_to_care.le(out.window_min)
    for c in ("wasted_trips", "calls", "gave_up"):
        out[c] = out[c].fillna(0).astype(int)
    out["gave_up"] = out.gave_up > 0
    out["unsafe_first_stop"] = out.unsafe_first_stop.fillna(False).astype(bool)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Metrics with seed-bootstrap intervals
def _boot_idx(n_seeds: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    return rng.integers(0, n_seeds, (n_boot, n_seeds))


def group_metrics(d: pd.DataFrame, n_boot: int, rng: np.random.Generator) -> dict[str, float]:
    seeds = sorted(d.seed.unique())
    per = d.groupby("seed").agg(n=("case_id", "size"), **{c: (c, "sum") for c in SHARE}).reindex(seeds)
    times = [d.loc[(d.seed == s) & d.treated, "min_to_care"].to_numpy() for s in seeds]
    idx = _boot_idx(len(seeds), n_boot, rng)
    n = per.n.to_numpy(dtype=float)
    out: dict[str, float] = {"n_cases": int(n.sum()), "n_seeds": len(seeds)}
    names = {"treated_in_window": "treated_in_window", "wasted_trips": "wasted_trips_per_case",
             "calls": "calls_per_case", "unsafe_first_stop": "unsafe_first_stop", "gave_up": "gave_up"}
    for col, name in names.items():
        s = per[col].to_numpy(dtype=float)
        boot = s[idx].sum(1) / n[idx].sum(1)
        out[name] = s.sum() / n.sum()
        out[f"{name}_lo"], out[f"{name}_hi"] = np.percentile(boot, CI)
    all_t = np.concatenate(times) if times else np.array([])
    out["median_min_to_care"] = float(np.median(all_t)) if len(all_t) else np.nan
    meds = [np.median(np.concatenate([times[i] for i in row])) if sum(len(times[i]) for i in row) else np.nan
            for row in idx[: max(1, n_boot // 2)]]
    meds = np.array(meds, dtype=float)
    out["median_min_to_care_lo"], out["median_min_to_care_hi"] = (
        np.nanpercentile(meds, CI) if np.isfinite(meds).any() else (np.nan, np.nan))
    return out


def metrics(oc: pd.DataFrame, n_boot: int = 500, seed: int = 92) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    both = pd.concat([oc, oc.assign(state="ALL")])
    for key, d in both.groupby(["policy", "scenario", "state", "service", "urgency"]):
        rows.append({**dict(zip(["policy", "scenario", "state", "service", "urgency"], key, strict=True)),
                     **group_metrics(d, n_boot, rng)})
    m = pd.DataFrame(rows)
    m["label"] = LABEL
    return m


def compare(oc: pd.DataFrame, a: str, b: str, n_boot: int = 500, seed: int = 92) -> pd.DataFrame:
    """Paired by seed: share treated within window, policy a minus policy b, per scenario and service."""
    rng = np.random.default_rng(seed)
    rows = []
    for (sc, svc), d in oc[oc.policy.isin([a, b])].groupby(["scenario", "service"]):
        per = d.pivot_table(index="seed", columns="policy", values="treated_in_window", aggfunc=["sum", "size"])
        sa, sb, n = per[("sum", a)].to_numpy(float), per[("sum", b)].to_numpy(float), per[("size", a)].to_numpy(float)
        idx = _boot_idx(len(n), n_boot, rng)
        diff = (sa[idx].sum(1) - sb[idx].sum(1)) / n[idx].sum(1)
        lo, hi = np.percentile(diff, CI)
        rows.append({"scenario": sc, "service": svc, "diff": (sa.sum() - sb.sum()) / n.sum(), "diff_lo": lo,
                     "diff_hi": hi, f"{a}": sa.sum() / n.sum(), f"{b}": sb.sum() / n.sum()})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------------------
def simulate(scenarios: list[str], seeds: list[int], n_cases: int, states: list[str], services: list[str],
             out: Path = OUT, n_boot: int = 500, sweep: bool = True, with_reports: bool = False,
             include_planner: bool = False, run_id: str | None = None, verbose: bool = True) -> dict[str, Any]:
    t_start = time.time()
    states = [s.upper() for s in states]
    ensure_built(states)
    be = backends(include_planner)
    app = AppAdapter()
    policies = {**POLICIES, **be["baselines"]}
    ctxs = {name: {"app": app} for name in POLICIES}
    extra = be["make_context"](states, services) if be["make_context"] else {}
    ctxs |= {name: {"app": app, **extra} for name in be["baselines"]}
    run_id = run_id or f"min_{len(seeds)}x{n_cases}"
    for sub in ("truth", "events", "cases"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    ev_all, oc_all, case_all, sweep_oc = [], [], [], []
    for seed in seeds:
        cases = be["generate_cases"](seed, n_cases, states, services, 1)
        cf = case_frame(cases)
        case_all.append(cf)
        steps = choose_all(cases, policies, ctxs)
        for sc in scenarios:
            tdf = build_truth(sc, seed, tuple(services), DEFAULT)
            tdf.to_parquet(out / "truth" / f"{sc}_{seed}.parquet", index=False)
            ev = execute(cases, steps, Truth(tdf, sc, seed), be["run_case"], DEFAULT, run_id)
            ev_all.append(ev)
            oc_all.append(outcomes(ev, cf, tdf.assign(scenario=sc)))
            if sweep:
                pair = {k: steps[k] for k in COMPARE if k in steps}
                for knob, level, a in sweep_configs():
                    t2 = tdf if level == "mid" else build_truth(sc, seed, tuple(services), a)
                    ev2 = execute(cases, pair, Truth(t2, sc, seed), be["run_case"], a, run_id)
                    sweep_oc.append(outcomes(ev2, cf, t2.assign(scenario=sc)).assign(knob=knob, level=level))
        if verbose:
            print(f"seed {seed} done ({time.time() - t_start:.0f} s)")

    events, oc, cases_df = pd.concat(ev_all), pd.concat(oc_all), pd.concat(case_all)
    events.to_parquet(out / "events" / f"{run_id}.parquet", index=False)
    cases_df.to_parquet(out / "cases" / f"{run_id}.parquet", index=False)
    m = metrics(oc, n_boot).assign(run_id=run_id, **{f"src_{k}": v for k, v in be["sources"].items()})
    m.to_parquet(out / "metrics.parquet", index=False)
    result: dict[str, Any] = {"metrics": m, "outcomes": oc, "events": events, "cases": cases_df,
                              "sources": be["sources"], "run_id": run_id}
    if sweep and sweep_oc:
        so = pd.concat(sweep_oc)
        sens = pd.concat([compare(d, *COMPARE, n_boot).assign(knob=k, level=lv)
                          for (k, lv), d in so.groupby(["knob", "level"])])
        sens["app_beats"] = sens.diff_lo > 0
        sens["label"] = LABEL
        sens.to_parquet(out / "sensitivity.parquet", index=False)
        result["sensitivity"] = sens
    if with_reports:  # future work: network data only, no second wave yet
        from sim.reports import write_network
        result["network"] = write_network(events, cases_df, out / "network")
    result["seconds"] = time.time() - t_start
    if verbose:
        print_summary(result)
    return result


def verdict(lo: float, hi: float) -> str:
    return "app better" if lo > 0 else "app worse" if hi < 0 else "no clear difference"


def sweep_verdicts(sens: pd.DataFrame) -> pd.DataFrame:
    """Per scenario and service: the verdict (app vs nearest_call_first, 90% CI) at the middle assumptions, and
    every swept level where the verdict changes. That is where the app starts or stops beating it."""
    rows = []
    for (sc, svc), d in sens.groupby(["scenario", "service"]):
        mid = d[d.knob == "all"].iloc[0]
        v0 = verdict(mid.diff_lo, mid.diff_hi)
        flips = [f"{r.knob} {r.level}: {verdict(r.diff_lo, r.diff_hi)}" for r in d[d.knob != "all"].itertuples()
                 if verdict(r.diff_lo, r.diff_hi) != v0]
        rows.append({"scenario": sc, "service": svc, "diff_mid_points": round(100 * mid["diff"], 1),
                     "verdict_mid": v0, "changes_at": "; ".join(flips) or "none"})
    return pd.DataFrame(rows)


def table(m: pd.DataFrame) -> pd.DataFrame:
    """The headline table: states pooled, one block per scenario and service."""
    t = m[m.state == "ALL"].copy()

    def ci(c: str, pct: bool) -> pd.Series:
        def f(x: float) -> str:
            return "-" if pd.isna(x) else f"{100 * x:.0f}" if pct else f"{x:.0f}"

        return t[c].map(f) + " [" + t[f"{c}_lo"].map(f) + "-" + t[f"{c}_hi"].map(f) + "]"

    out = pd.DataFrame({"scenario": t.scenario, "service": t.service, "policy": t.policy,
                        "treated in window %": ci("treated_in_window", True),
                        "median min": ci("median_min_to_care", False),
                        "wasted trips/case": t.wasted_trips_per_case.round(2),
                        "calls/case": t.calls_per_case.round(2),
                        "unsafe 1st stop %": (100 * t.unsafe_first_stop).round(0),
                        "gave up %": (100 * t.gave_up).round(0), "cases": t.n_cases})
    return out.sort_values(["scenario", "service", "policy"]).reset_index(drop=True)


def print_summary(r: dict[str, Any]) -> None:
    print(f"\n{LABEL}. Sources: {r['sources']}. {r['seconds']:.0f} s.")
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.max_rows", 200):
        print(table(r["metrics"]).to_string(index=False))
        if "sensitivity" in r:
            s = r["sensitivity"]
            print(f"\n{LABEL}. Sensitivity: app minus nearest_call_first, treated within window (points), 90% CI")
            s = s.assign(d=lambda x: (100 * x["diff"]).round(1).astype(str) + " [" + (100 * x.diff_lo).round(1)
                         .astype(str) + ", " + (100 * x.diff_hi).round(1).astype(str) + "]")
            print(s.pivot_table(index=["knob", "level"], columns=["scenario", "service"], values="d",
                                aggfunc="first").to_string())
            print(sweep_verdicts(r["sensitivity"]).to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=f"Run the referral simulation ({LABEL}).")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--seeds", type=int, default=3, help="number of seeds (0 .. N-1, plus --seed-start)")
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--cases-per-seed", type=int, default=200)
    ap.add_argument("--states", default=",".join(STATES))
    ap.add_argument("--services", default=",".join(SERVICES))
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--boot", type=int, default=500)
    ap.add_argument("--no-sweep", action="store_true")
    ap.add_argument("--with-reports", action="store_true", help="future work: also write network data")
    ap.add_argument("--include-planner", action="store_true", help="future work: keep a planner-route baseline")
    ap.add_argument("--run-id")
    a = ap.parse_args()
    if a.with_reports:
        print(f"note: {', '.join(FUTURE)} is future work; --with-reports writes network data only")
    simulate(a.scenarios.split(","), list(range(a.seed_start, a.seed_start + a.seeds)), a.cases_per_seed,
             a.states.split(","), a.services.split(","), a.out, a.boot, not a.no_sweep, a.with_reports,
             a.include_planner, a.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

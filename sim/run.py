"""Monte Carlo runner for the simulated referral world (issue #92). Every number it writes is SIMULATED.

    .venv-app/bin/python -m sim.run --seeds 20 --cases-per-cell 200 --states BIHAR,"UTTAR PRADESH" \
        --services dialysis,trauma_emergency --sweep

Runs on the lead's world, truth and executor (sim/world.py, sim/execute.py) and baselines (sim/policies_baseline.py),
with the app policies of sim/policies_app.py. Per seed: one case set (world.cases, filtered to the requested states
and services) shared by every policy and scenario; each policy chooses its steps once (choices never depend on
truth); then each scenario's truth table (world.truth_table) resolves them through execute.run_case.
Scenarios: world.SCENARIOS, S0-high and S0-low (the S0 base-rate bounds, always reported together), S1, S2, S3.
Writes under --out (default sim/out, git-ignored), every parquet with the SIMULATED note in its file metadata:
- truth/<scenario>_<seed>.parquet, events/<run_id>.parquet, cases/<run_id>.parquet (what sim/replay.py reads);
- metrics.parquet: one row per policy x scenario x state (and ALL) x service x urgency, each metric with a
  seed-bootstrap 90% interval;
- sensitivity.parquet (--sweep, the default): app minus nearest_call_first, treated within window, with each of
  world.KNOBS at low and high (the others at mid).
Policies in the minimum run: app, app_offline, nearest, nearest_call_first, best_on_paper. app_plus_reports is
future work (--with-reports writes network data only). app_before_101 (the emergency order before PR #101) runs only
when named in --policies.
"""
from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sim import execute, policies_baseline, world
from sim.app_adapter import AppAdapter, ensure_built
from sim.interface import EVENT_COLUMNS, OUT, SERVICES, STATES, TRUTH_COLUMNS, Case
from sim.policies_app import DIAGNOSTIC, FUTURE, context
from sim.policies_app import POLICIES as APP_POLICIES

LABEL = "SIMULATED - not field results"
SCENARIOS = world.SCENARIOS
S0_NOTE = "S0-high and S0-low are bounds (simulated, base-rate bounds): read them together, never one alone"
METRICS = ("treated_in_window", "median_min_to_care", "wasted_trips_per_case", "calls_per_case", "unsafe_first_stop",
           "gave_up")
SHARE = ("treated_in_window", "wasted_trips", "calls", "unsafe_first_stop", "gave_up")
COMPARE = ("app", "nearest_call_first")  # the sweep's comparison (#92 review)
TRUTH_KNOBS = ("accept_p", "phone_ok", "open_now_p")  # the knobs world.truth_table reads; execute reads wrong_yes
CI = (5, 95)
StepDicts = list[dict[str, Any]]
Chooser = Callable[[dict[str, Any]], StepDicts]


# ---------------------------------------------------------------------------------------------------------------------
# Cases, policies, execution
def make_cases(seed: int, n: int, states: list[str], services: list[str]) -> pd.DataFrame:
    """world.cases (n per state x service), filtered to the requested services."""
    unknown = sorted(set(services) - set(world.SERVICES))
    if unknown:
        raise SystemExit(f"services {unknown} are not in sim/world.py SERVICES {list(world.SERVICES)}")
    c = world.cases(seed, tuple(states), n)
    return c[c.service.isin(services)].reset_index(drop=True)


def app_steps(policy: Any, case: dict[str, Any], ctx: dict[str, Any]) -> StepDicts:
    """An app policy object on a world case: Case(**row) in, the executor's step dicts out."""
    return [s.as_dict() for s in policy.choose(Case(**case), ctx)]


def assert_no_truth(ctx: Any) -> None:
    """A policy's ctx must never hold a truth table (or anything with truth columns), at any depth."""
    hidden = set(TRUTH_COLUMNS) - {"unique_id", "service"}
    if isinstance(ctx, pd.DataFrame):
        if hidden & set(ctx.columns):
            raise AssertionError(f"a policy was handed truth columns {sorted(hidden & set(ctx.columns))}")
    elif isinstance(ctx, dict):
        for v in ctx.values():
            assert_no_truth(v)


def policy_table(app: AppAdapter, names: list[str] | None = None) -> dict[str, Chooser]:
    """Policies as case_dict -> step dicts: the minimum run, or `names` (which may add DIAGNOSTIC ones). App policies
    see the app; baselines the public listing."""
    app_ctx = context(app)
    base_ctx = policies_baseline.context()
    assert_no_truth(app_ctx)
    assert_no_truth(base_ctx)
    apps = APP_POLICIES | DIAGNOSTIC
    out: dict[str, Chooser] = {name: (lambda c, p=pol: app_steps(p, c, app_ctx)) for name, pol in apps.items()}
    out |= {name: (lambda c, f=fn: f(c, base_ctx)) for name, fn in policies_baseline.POLICIES.items()}
    names = names or [*APP_POLICIES, *policies_baseline.POLICIES]
    if bad := sorted(set(names) - set(out)):
        raise SystemExit(f"unknown policies {bad}; known: {sorted(out)}")
    return {n: out[n] for n in names}


def choose_all(cases: pd.DataFrame, policies: dict[str, Chooser]) -> dict[str, dict[str, StepDicts]]:
    """policy -> case_id -> steps. Computed once per seed and reused for every scenario and knob level."""
    recs = cases.to_dict("records")
    return {name: {c["case_id"]: choose(c) for c in recs} for name, choose in policies.items()}


def run_events(cases: pd.DataFrame, steps: dict[str, dict[str, StepDicts]], truth: pd.DataFrame, scenario: str,
               run_id: str, knobs: dict[str, float], listed: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """execute.run_case for every policy and case on one truth table (indexed once)."""
    tix, k = execute.index_truth(truth), {**world.MID, **knobs}
    recs = cases.to_dict("records")
    rows = [(run_id, scenario, c["seed"], pol, c["case_id"], *e)
            for pol, per in steps.items() for c in recs
            for e in execute.run_case(c, per[c["case_id"]], tix, listed, k)]
    return pd.DataFrame(rows, columns=list(EVENT_COLUMNS))


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


def sweep_configs() -> list[tuple[str, str, dict[str, float]]]:
    """(knob, level, knobs) for the sweep over world.KNOBS: mid once, then each knob low and high, others at mid."""
    out = [("all", "mid", dict(world.MID))]
    for knob, levels in world.KNOBS.items():
        out += [(knob, lv, {**world.MID, knob: levels[lv]}) for lv in ("low", "high")]
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
             run_id: str | None = None, verbose: bool = True, policies: list[str] | None = None) -> dict[str, Any]:
    """n_cases is per state x service x seed (world.cases n). policies: default the minimum run."""
    t_start = time.time()
    states = [s.upper() for s in states]
    scenarios = list(dict.fromkeys(world.S0_ALIAS.get(s, s) for s in scenarios))
    if bad := sorted(set(scenarios) - set(SCENARIOS)):
        raise SystemExit(f"unknown scenarios {bad}; sim/world.py has {list(SCENARIOS)}")
    ensure_built(states)
    if sweep and policies and not set(COMPARE) <= set(policies):
        raise SystemExit(f"the sweep compares {COMPARE}: include both in policies, or pass sweep=False")
    choosers = policy_table(AppAdapter(), policies)
    listed = execute._listed()
    run_id = run_id or f"min_{len(seeds)}x{n_cases}"
    configs = sweep_configs() if sweep else []
    mid_key = tuple(world.MID[k] for k in TRUTH_KNOBS)

    ev_all, oc_all, case_all, sweep_oc = [], [], [], []
    for seed in seeds:
        cases = make_cases(seed, n_cases, states, services)
        case_all.append(cases)
        steps = choose_all(cases, choosers)
        pair = {k: steps[k] for k in COMPARE}
        for sc in scenarios:
            tdf = world.truth_table(sc, seed, world.MID)
            world.write_parquet(tdf, out / "truth" / f"{sc}_{seed}.parquet")
            ev = run_events(cases, steps, tdf, sc, run_id, world.MID, listed)
            ev_all.append(ev)
            oc_all.append(outcomes(ev, cases, tdf.assign(scenario=sc)))
            truths = {mid_key: tdf}  # wrong_yes does not change the truth, so its levels reuse the mid table
            for knob, level, kn in configs:
                key = tuple(kn[k] for k in TRUTH_KNOBS)
                if key not in truths:
                    truths[key] = world.truth_table(sc, seed, kn)
                ev2 = run_events(cases, pair, truths[key], sc, run_id, kn, listed)
                sweep_oc.append(outcomes(ev2, cases, truths[key].assign(scenario=sc)).assign(knob=knob, level=level))
        if verbose:
            print(f"seed {seed} done ({time.time() - t_start:.0f} s)")

    events, oc, cases_df = pd.concat(ev_all), pd.concat(oc_all), pd.concat(case_all)
    world.write_parquet(events, out / "events" / f"{run_id}.parquet")
    world.write_parquet(cases_df, out / "cases" / f"{run_id}.parquet")
    m = metrics(oc, n_boot).assign(run_id=run_id)
    world.write_parquet(m, out / "metrics.parquet")
    result: dict[str, Any] = {"metrics": m, "outcomes": oc, "events": events, "cases": cases_df, "run_id": run_id}
    if sweep_oc:
        so = pd.concat(sweep_oc)
        sens = pd.concat([compare(d, *COMPARE, n_boot).assign(knob=k, level=lv)
                          for (k, lv), d in so.groupby(["knob", "level"])])
        sens["knob_value"] = [np.nan if k == "all" else world.KNOBS[k][lv]
                              for k, lv in zip(sens.knob, sens.level, strict=True)]
        sens["app_beats"] = sens.diff_lo > 0
        sens["label"] = LABEL
        world.write_parquet(sens, out / "sensitivity.parquet")
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
    print(f"\n{LABEL}. World, truth and executor: sim.world, sim.execute. {r['seconds']:.0f} s.\n{S0_NOTE}.")
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
    ap.add_argument("--cases-per-cell", "--cases-per-seed", dest="cases", type=int, default=world.CASES_PER_CELL,
                    help="cases per state x service x seed (world.cases n)")
    ap.add_argument("--states", default=",".join(STATES))
    ap.add_argument("--services", default=",".join(SERVICES))
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--boot", type=int, default=500)
    ap.add_argument("--sweep", action=argparse.BooleanOptionalAction, default=True,
                    help="knob sweep over world.KNOBS (default on)")
    ap.add_argument("--with-reports", action="store_true", help="future work: also write network data")
    ap.add_argument("--run-id")
    ap.add_argument("--policies", help="comma-separated; default the minimum run (app_before_101 only when named)")
    a = ap.parse_args()
    if a.with_reports:
        print(f"note: {', '.join(FUTURE)} is future work; --with-reports writes network data only")
    simulate(a.scenarios.split(","), list(range(a.seed_start, a.seed_start + a.seeds)), a.cases,
             a.states.split(","), a.services.split(","), a.out, a.boot, a.sweep, a.with_reports, a.run_id,
             policies=a.policies.split(",") if a.policies else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

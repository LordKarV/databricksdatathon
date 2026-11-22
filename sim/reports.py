"""Field reports and network data from simulated events (issue #92). Simulated: never field results.

A report is what a health worker could observe and send back, never the truth itself:
- phone_yes / phone_no: what the facility said on the phone (it can be wrong);
- treated, or turned away with the reason the worker saw: not_found (nothing at the map point; the executor's
  not_there), no_service (staff say they do not do it), closed, refused.
No-answer calls are reported too, but say nothing about the service.

Status (owner's decision on #92): the "app + reports" policy and these network outputs are future work, left out of
the minimum run. sim/run.py --with-reports writes them: sim/out/network/facility_reports.parquet (per facility and
service) and sim/out/network/district_summary.parquet (per district: cases, treated in window, nothing in reach).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from sim.assumptions import DEFAULT, Assumptions
from sim.interface import OUT

NETWORK = OUT / "network"
OBSERVATIONS = ("phone_yes", "phone_no", "phone_no_answer", "treated", "not_found", "no_service", "closed", "refused")


def observation(kind: str, outcome: str) -> str | None:
    if kind == "call":
        return {"yes": "phone_yes", "no": "phone_no", "no_answer": "phone_no_answer"}.get(outcome)
    if kind == "treated":
        return "treated"
    if kind == "turned_away":
        outcome = "not_found" if outcome == "not_there" else outcome
        return outcome if outcome in OBSERVATIONS else None
    return None


def reports_from_events(events: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    """One row per observation: scenario, seed, policy, case_id, step, facility_id, service, observation, t_min."""
    obs = [observation(k, o) for k, o in zip(events.kind, events.outcome, strict=True)]
    r = events.assign(observation=obs).dropna(subset=["observation"])
    r = r.merge(cases[["case_id", "service"]], on="case_id", how="left")
    return r[["run_id", "scenario", "seed", "policy", "case_id", "step", "facility_id", "service", "observation",
              "t_min"]].reset_index(drop=True)


def report_events(reports: pd.DataFrame) -> pd.DataFrame:
    """Reports in the event-log schema (kind "report", outcome = the observation)."""
    return reports.assign(kind="report", outcome=reports.observation)[
        ["run_id", "scenario", "seed", "policy", "case_id", "step", "kind", "facility_id", "t_min", "outcome"]]


def aggregate(reports: pd.DataFrame, a: Assumptions = DEFAULT) -> pd.DataFrame:
    """Per (scenario, seed, facility_id, service): a count per observation, plus Beta successes and failures."""
    keys = ["scenario", "seed", "facility_id", "service"]
    agg = reports.pivot_table(index=keys, columns="observation", values="case_id", aggfunc="count", fill_value=0)
    agg = agg.reindex(columns=list(OBSERVATIONS), fill_value=0).reset_index()
    agg["successes"] = sum(agg[o] * w[0] for o, w in a.report_weights.items() if o in agg)
    agg["failures"] = sum(agg[o] * w[1] for o, w in a.report_weights.items() if o in agg)
    agg["simulated"] = True
    return agg


def district_summary(events: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    """Per (scenario, policy, state, district, service): cases, treated in window, nothing in reach (no options)."""
    first_treated = events[events.kind == "treated"].groupby(["scenario", "seed", "policy", "case_id"]).t_min.min()
    # no_options_left at step 0: the policy had no option at all
    none = events[(events.kind == "gave_up") & (events.outcome == "no_options_left") & (events.step == 0)]
    per = events[["scenario", "seed", "policy", "case_id"]].drop_duplicates().merge(cases.drop(columns="seed"),
                                                                                    on="case_id")
    per = per.join(first_treated, on=["scenario", "seed", "policy", "case_id"])
    per["treated_in_window"] = per.t_min.le(per.window_min)
    per["nothing_in_reach"] = per.set_index(["scenario", "seed", "policy", "case_id"]).index.isin(
        none.set_index(["scenario", "seed", "policy", "case_id"]).index)
    out = per.groupby(["scenario", "policy", "state", "district", "service"]).agg(
        cases=("case_id", "size"), treated_in_window=("treated_in_window", "sum"),
        nothing_in_reach=("nothing_in_reach", "sum")).reset_index()
    out["simulated"] = True
    return out


def write_network(events: pd.DataFrame, cases: pd.DataFrame, out: Path = NETWORK,
                  a: Assumptions = DEFAULT) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = {"facility_reports": out / "facility_reports.parquet", "district_summary": out / "district_summary.parquet"}
    aggregate(reports_from_events(events, cases), a).to_parquet(paths["facility_reports"], index=False)
    district_summary(events, cases).to_parquet(paths["district_summary"], index=False)
    return paths


class Beliefs:
    """Beta posterior per (facility, service) from aggregated reports of ONE world (scenario, seed)."""

    def __init__(self, agg: pd.DataFrame) -> None:
        self._sf = {(f, s): (float(a), float(b))
                    for f, s, a, b in zip(agg.facility_id, agg.service, agg.successes, agg.failures, strict=True)}

    def posterior(self, facility_id: str, service: str, p: float, k: float = DEFAULT.report_k) -> float:
        s, f = self._sf.get((facility_id, service), (0.0, 0.0))
        return (p * k + s) / (k + s + f)

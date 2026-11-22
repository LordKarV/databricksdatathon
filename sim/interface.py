"""The #92 contract between the two halves of the simulation, as it now stands. Simulated: never field results.

World, truth and executor are the lead's (sim/world.py, sim/execute.py); the baselines are sim/policies_baseline.py.
The app policies, runner, metrics, sweep and replay are tm-AA2026's (sim/policies_app.py, sim/run.py, sim/replay.py).

- Cases: world.cases(seed, states, n) -> DataFrame, one row per patient (n per state x service), with exactly the
  fields of Case below. sim/run.py filters it to the requested services.
- Truth: world.truth_table(scenario, seed, knobs) -> DataFrame with TRUTH_COLUMNS, one row per facility x service.
  Scenarios are world.SCENARIOS (S0-high, S0-low, S1, S2, S3). Only sim/execute.py and the metrics read it;
  sim/run.py also writes it to <out>/truth/<scenario>_<seed>.parquet for the replay.
- Policies return steps as dicts {"facility_id", "call_first", "note"}, at most N_OPTIONS, tried in order:
  - baselines are functions policies_baseline.POLICIES[name](case_dict, ctx) with ctx = policies_baseline.context()
    (the public listing only);
  - app policies are objects policies_app.POLICIES[name].choose(Case(**case_dict), {"app": AppAdapter()}) returning
    Step objects; sim.run.app_steps() converts them to the dicts above.
- Execution: execute.run_case(case_dict, step_dicts, execute.index_truth(truth), listed, knobs) -> rows
  (step, kind, facility_id, t_min, outcome); sim/run.py adds run_id, scenario, seed, policy and case_id (EVENT_COLUMNS,
  the same as execute.EVENT_COLS). knobs = {**world.MID, ...}, swept over world.KNOBS.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sim" / "out"

# The minimum run (lead, #92): one planned and one emergency service, two focus states.
SERVICES = ("dialysis", "trauma_emergency")
STATES = ("BIHAR", "UTTAR PRADESH")
# Every policy tries at most this many facilities, then escalates to 108 (equal caps, #92 review). The app's
# N_OPTIONS, and execute.MAX_STEPS.
N_OPTIONS = 3

Urgency = Literal["emergency", "planned"]
EVENT_KINDS = ("call", "travel", "arrive", "turned_away", "treated", "gave_up", "outage", "report")
EVENT_FIELDS = ("step", "kind", "facility_id", "t_min", "outcome")
EVENT_COLUMNS = ("run_id", "scenario", "seed", "policy", "case_id", *EVENT_FIELDS)
TRUTH_COLUMNS = ("unique_id", "service", "exists", "offers", "phone_ok", "open_now_p", "accept_p", "true_lat",
                 "true_lon")
# Outcome vocabulary of sim/execute.py (string column `outcome`), per kind. step counts from 0.
#   call: yes | no | no_answer          travel: "" (t_min = departure)   arrive: "" (t_min = arrival)
#   turned_away: not_there | closed | no_service | refused               treated: in_window | late
#   gave_up: no_options_left | time_limit (each means "escalate to 108"; no_options_left at step 0 = no options)
#   outage: no_data (step 0, facility None) | no_signal (the call could not be placed; the worker goes anyway)
#   report: see sim/reports.py (future work)
# t_min is minutes since the case started, so window checks are t_min <= window_min.


@dataclass(frozen=True)
class Case:
    """One simulated patient: the fields of a world.cases() row."""
    case_id: str
    seed: int
    lat: float
    lon: float
    state: str
    district: str
    service: str
    urgency: Urgency
    window_min: int
    t0_min: int
    has_data: bool
    has_phone_signal: bool


@dataclass(frozen=True)
class Step:
    facility_id: str
    call_first: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        """The executor's step: {"facility_id", "call_first", "note"}."""
        return asdict(self)


class Policy(Protocol):
    """An app policy object. Baselines are plain functions (case_dict, ctx) -> list[dict] instead."""
    name: str

    def choose(self, case: Case, ctx: dict[str, Any]) -> list[Step]: ...

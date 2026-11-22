"""The #92 interface shared by both halves of the simulation: Case, Step, truth rows, the event log.

sim/world.py, sim/execute.py and sim/policies_baseline.py (tm-Art4v or the lead) and sim/truth.py, sim/policies_app.py,
sim/reports.py, sim/run.py (tm-AA2026) all build to these types. Simulated: never field results.

Module contract that sim/run.py looks for (it falls back to sim/_stub_execute.py, with a printed note, when a module
or a name is missing):
- sim.world.generate_cases(seed: int, n: int, states: list[str], services: list[str], wave: int = 1) -> list[Case]
- sim.execute.run_case(case: Case, steps: list[Step], truth: Truth, a: Assumptions) -> list[dict]
  Each dict has the EVENT_FIELDS keys; run.py adds run_id, scenario, seed, policy and case_id.
- sim.policies_baseline.POLICIES: dict[str, Policy]; optional make_context(states, services) -> dict.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sim" / "out"
TRUTH_DIR = OUT / "truth"

SCENARIOS = ("S0", "S1", "S2", "S3")
# The minimum run (lead, #92): one planned and one emergency service, two focus states.
SERVICES = ("dialysis", "trauma_emergency")
STATES = ("BIHAR", "UTTAR PRADESH")
# Case urgency per app service (#92: emergency | planned). The app's own profile is finer (urgent, scheduled).
URGENCY = {"emergency_csection": "emergency", "nicu": "emergency", "trauma_emergency": "emergency",
           "burn_care": "emergency", "dialysis": "planned", "mri": "planned", "cardiac_surgery": "planned"}
# Every policy tries at most this many facilities, then escalates to 108 (equal caps, #92 review). The app's own.
N_OPTIONS = 3

Urgency = Literal["emergency", "planned"]
EVENT_KINDS = ("call", "travel", "arrive", "turned_away", "treated", "gave_up", "outage", "report")
EVENT_FIELDS = ("step", "kind", "facility_id", "t_min", "outcome")
EVENT_COLUMNS = ("run_id", "scenario", "seed", "policy", "case_id", *EVENT_FIELDS)
TRUTH_COLUMNS = ("unique_id", "service", "exists", "offers", "phone_ok", "open_now_p", "accept_p", "true_lat",
                 "true_lon")
# Outcome vocabulary (string column `outcome`), per kind:
#   call: yes | no | no_answer          travel: minutes of this leg, as text      arrive: found | not_found
#   turned_away: not_found | no_service | closed | refused                       treated: ok
#   gave_up: no_options | list_exhausted | time_limit (each means "escalate to 108")
#   outage: no_data | no_signal | closed                                          report: see sim/reports.py
# t_min is minutes since the case started (t0_min), so window checks are t_min <= window_min.


@dataclass(frozen=True)
class Case:
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


class Policy(Protocol):
    name: str

    def choose(self, case: Case, ctx: dict[str, Any]) -> list[Step]: ...


class TruthRow(NamedTuple):
    exists: bool
    offers: bool
    phone_ok: bool
    open_now_p: float
    accept_p: float
    true_lat: float
    true_lon: float


class Truth:
    """Lookup over one truth table. Only the executor and the metrics read it; policies never do."""

    def __init__(self, df: Any, scenario: str, seed: int) -> None:
        self.scenario, self.seed = scenario, seed
        cols = [df[c].to_numpy().tolist() for c in TRUTH_COLUMNS]
        self._rows = {(u, s): TruthRow(bool(e), bool(o), bool(p), float(on), float(ac), float(la), float(lo))
                      for u, s, e, o, p, on, ac, la, lo in zip(*cols, strict=True)}

    def get(self, facility_id: str, service: str) -> TruthRow | None:
        return self._rows.get((facility_id, service))

    def __len__(self) -> int:
        return len(self._rows)

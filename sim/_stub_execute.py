"""TEMPORARY stand-in for sim/world.py and sim/execute.py (issue #92). Delete once those land.

Used by sim/run.py only when the real modules are missing, and by sim/tests. It follows sim/interface.py exactly,
so the real modules can replace it without changes elsewhere. What the real modules must replace:
- generate_cases(): here PIN centroids are drawn uniformly within the states (no NFHS population weights), the
  service uniformly from the run's services, windows from WINDOW_MIN below, outages as fixed Bernoulli rates.
- run_case(): here travel is the geo/travel.py straight-line estimate between true points (no OSRM, no planner),
  one call per step, and the worker gives up after Assumptions.give_up_minutes or N_OPTIONS steps.
Common random numbers: every draw is a hash of (case_id, facility_id, purpose), so every policy and every scenario
meets the same coin flips at the same facility for the same patient.
"""
from __future__ import annotations

import hashlib
import sys
from functools import cache

import numpy as np
import pandas as pd

from sim.assumptions import DEFAULT, Assumptions
from sim.interface import N_OPTIONS, ROOT, URGENCY, Case, Step, Truth

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from geo.travel import estimate  # noqa: E402

# Treatment windows in minutes. trauma: kb/pathways major_trauma stage "stabilise" (60, an assumption there).
# Others: app/facts/engine.py WINDOW for the service's profile (emergency 60, urgent 60, scheduled 120, planned 240).
WINDOW_MIN = {"trauma_emergency": 60, "emergency_csection": 60, "burn_care": 60, "nicu": 60, "dialysis": 120,
              "mri": 240, "cardiac_surgery": 240}


@cache
def _pins(states: tuple[str, ...]) -> pd.DataFrame:
    p = pd.read_parquet(ROOT / "derived" / "v1" / "pin_gazetteer.parquet", columns=["pin", "state", "district", "lat",
                                                                                     "lon"])
    p = p.dropna(subset=["lat", "lon", "state"])
    return p[p.state.str.upper().isin(states)].sort_values("pin").reset_index(drop=True)


def generate_cases(seed: int, n: int, states: list[str], services: list[str], wave: int = 1,
                   a: Assumptions = DEFAULT) -> list[Case]:
    pins = _pins(tuple(s.upper() for s in states))
    if pins.empty:
        raise ValueError(f"no PINs for states {states}")
    rng = np.random.default_rng([seed, wave, 7])
    idx = rng.integers(0, len(pins), n)
    svc = rng.choice(list(services), n)
    t0 = rng.integers(0, 24 * 60, n)
    data, signal = rng.random(n) < a.has_data_p, rng.random(n) < a.has_signal_p
    return [Case(case_id=f"s{seed}w{wave}c{i:05d}", seed=seed, lat=float(pins.lat[j]), lon=float(pins.lon[j]),
                 state=str(pins.state[j]), district=str(pins.district[j] or ""), service=str(svc[i]),
                 urgency=URGENCY[str(svc[i])], window_min=WINDOW_MIN[str(svc[i])], t0_min=int(t0[i]),
                 has_data=bool(data[i]), has_phone_signal=bool(signal[i]))
            for i, j in enumerate(idx)]


def draw(case_id: str, facility_id: str, purpose: str) -> float:
    """A uniform in [0, 1) fixed by (case, facility, purpose): common random numbers across policies and scenarios."""
    h = hashlib.blake2b(f"{case_id}|{facility_id}|{purpose}".encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2**64


def run_case(case: Case, steps: list[Step], truth: Truth, a: Assumptions = DEFAULT) -> list[dict]:
    """Resolve one case's steps against the truth. Returns events with EVENT_FIELDS (sim/interface.py)."""
    ev: list[dict] = []
    t = 0.0
    pos = (case.lat, case.lon)

    def add(step: int, kind: str, fid: str, outcome: str) -> None:
        ev.append({"step": step, "kind": kind, "facility_id": fid, "t_min": round(t, 1), "outcome": outcome})

    if not case.has_data:
        add(0, "outage", "", "no_data")
    if not steps:
        add(0, "gave_up", "", "no_options")
        return ev
    for k, s in enumerate(steps[:N_OPTIONS], 1):
        if t > a.give_up_minutes:
            add(k, "gave_up", "", "time_limit")
            return ev
        tr = truth.get(s.facility_id, case.service)
        if tr is None:
            raise KeyError(f"no truth row for {s.facility_id} / {case.service}")
        u = lambda what, fid=s.facility_id: draw(case.case_id, fid, what)  # noqa: E731
        is_open, accepts = u("open") < tr.open_now_p, u("accept") < tr.accept_p
        can_treat = tr.exists and tr.offers and is_open and accepts
        if s.call_first:
            if not case.has_phone_signal:
                add(k, "outage", s.facility_id, "no_signal")
            else:
                t += a.call_minutes
                if not tr.phone_ok:
                    add(k, "call", s.facility_id, "no_answer")
                else:
                    yes = u("wrong_no") >= a.wrong_no_p if can_treat else u("wrong_yes") < a.wrong_yes_p
                    add(k, "call", s.facility_id, "yes" if yes else "no")
                    if not yes:
                        continue
        dest = (tr.true_lat, tr.true_lon)
        minutes = float(estimate(pos, dest, state=case.state)["minutes"])
        t += minutes
        add(k, "travel", s.facility_id, str(round(minutes)))
        pos = dest
        if not tr.exists:
            add(k, "arrive", s.facility_id, "not_found")
            add(k, "turned_away", s.facility_id, "not_found")
            continue
        add(k, "arrive", s.facility_id, "found")
        if not tr.offers:
            add(k, "turned_away", s.facility_id, "no_service")
        elif not is_open:
            add(k, "outage", s.facility_id, "closed")
            add(k, "turned_away", s.facility_id, "closed")
        elif not accepts:
            add(k, "turned_away", s.facility_id, "refused")
        else:
            add(k, "treated", s.facility_id, "ok")
            return ev
    add(min(len(steps), N_OPTIONS), "gave_up", "", "list_exhausted")
    return ev

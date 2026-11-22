"""Assumed constants of the app side of the simulation (issue #92): field reports, future work only.

The world's and the executor's constants (knobs, call minutes, turn-away minutes, give-up limits, data and signal
shares) live where they are used: sim/world.py (KNOBS, MID, P_HAS_DATA, P_PHONE_SIGNAL) and sim/execute.py
(CALL_MIN, TURN_AWAY_MIN, NOT_THERE_KM, GIVE_UP_MIN). sim/README.md lists them all. Every value is an ASSUMPTION.
Policies may import this module: it holds no truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Assumptions:
    # ---- app + reports (future work; not in the minimum run) ----
    # Prior strength k of Beta(p k, (1 - p) k) on top of the app's p, and the weight of each report kind.
    report_k: float = 4.0
    report_weights: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        # observation -> (successes, failures) added to the Beta. ASSUMPTION.
        "phone_yes": (0.5, 0.0), "phone_no": (0.0, 0.5), "treated": (1.0, 0.0), "no_service": (0.0, 1.0),
        "not_found": (0.0, 1.0), "closed": (0.0, 0.25), "refused": (0.0, 0.25)})


DEFAULT = Assumptions()

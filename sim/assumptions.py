"""Every assumed constant of the simulation, in one place (issue #92).

Each value below is an ASSUMPTION, not a measurement, unless its note names a data source. The sensitivity sweep
(sim/run.py --sweep) varies the four marked "swept" between the LOW / MID / HIGH levels in SWEEP. sim/README.md
reproduces this table. Policies may import this module: it holds no truth, only knobs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Assumptions:
    # ---- truth (sim/truth.py) ----
    # P(the facility answers its listed phone) for a number NOT shared with other listings. ASSUMPTION; swept.
    # Shared or directory numbers (record_trust flag, or the facts phone_shared >= PHONE_SHARED_MIN) never reach it.
    phone_ok_p: float = 0.85
    # A number listed for this many records or more is a directory or switchboard number. ASSUMPTION; the app warns
    # from 3 (app/facts/engine.py _call_ahead), so the same threshold is used.
    phone_shared_min: int = 3
    # P(open now) when the listing claims 24x7 for the service (derived/v2 is_24x7), and otherwise. ASSUMPTION; swept.
    open_now_p_24x7: float = 0.95
    open_now_p_other: float = 0.60
    # P(the facility accepts the patient | it exists, offers the service and is open), by case urgency.
    # ASSUMPTION; swept. Emergencies are higher because a facility is expected to stabilise an emergency.
    accept_p: dict[str, float] = field(default_factory=lambda: {"emergency": 0.90, "planned": 0.75})
    # existence_score is missing for a few records: this P(exists) stands in. ASSUMPTION.
    exists_p_missing: float = 0.90
    # S2/S3: P(offers) for an unmentioned pair OUTSIDE the DEV no_mention frame (not public by name, under 6 services
    # claimed). No label reaches these pairs, so this is a pure ASSUMPTION.
    no_mention_outside_frame_p: float = 0.05
    # Beta shrinkage strengths (pseudo-observations, in Kish effective n) for the label-based rates. ASSUMPTION.
    # cell -> service rate with K_CELL; service -> all-service rate with K_SERVICE.
    k_cell: float = 4.0
    k_service: float = 4.0
    # ---- execution (sim/_stub_execute.py; the real executor should take the same knobs) ----
    # P(a "yes" on the phone is wrong): the facility says yes but cannot treat on arrival. ASSUMPTION; swept.
    wrong_yes_p: float = 0.10
    # P(a "no" on the phone is wrong): the facility says no but could have treated. ASSUMPTION.
    wrong_no_p: float = 0.05
    call_minutes: int = 5  # one phone call, including a retry. ASSUMPTION.
    give_up_minutes: int = 480  # the worker stops trying after this long and escalates to 108. ASSUMPTION.
    # ---- stub world (sim/_stub_execute.py only) ----
    has_data_p: float = 0.80  # P(mobile data works at the start of a case). ASSUMPTION.
    has_signal_p: float = 0.90  # P(a phone call can be placed). ASSUMPTION.
    # ---- app + reports (future work; not in the minimum run) ----
    # Prior strength k of Beta(p k, (1 - p) k) on top of the app's p, and the weight of each report kind.
    report_k: float = 4.0
    report_weights: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        # observation -> (successes, failures) added to the Beta. ASSUMPTION.
        "phone_yes": (0.5, 0.0), "phone_no": (0.0, 0.5), "treated": (1.0, 0.0), "no_service": (0.0, 1.0),
        "not_found": (0.0, 1.0), "closed": (0.0, 0.25), "refused": (0.0, 0.25)})


DEFAULT = Assumptions()

# Sensitivity sweep levels (low, mid, high). mid equals DEFAULT. Each knob is varied alone, the others at mid.
SWEEP: dict[str, tuple[Assumptions, Assumptions]] = {
    "accept_p": (replace(DEFAULT, accept_p={"emergency": 0.70, "planned": 0.50}),
                 replace(DEFAULT, accept_p={"emergency": 0.98, "planned": 0.95})),
    "phone_ok_p": (replace(DEFAULT, phone_ok_p=0.60), replace(DEFAULT, phone_ok_p=0.98)),
    "wrong_yes_p": (replace(DEFAULT, wrong_yes_p=0.0), replace(DEFAULT, wrong_yes_p=0.30)),
    "open_now_p": (replace(DEFAULT, open_now_p_24x7=0.80, open_now_p_other=0.40),
                   replace(DEFAULT, open_now_p_24x7=0.99, open_now_p_other=0.85)),
}


def sweep_configs() -> list[tuple[str, str, Assumptions]]:
    """(knob, level, assumptions) for the sweep: mid once, then low and high of each knob."""
    out = [("all", "mid", DEFAULT)]
    for knob, (lo, hi) in SWEEP.items():
        out += [(knob, "low", lo), (knob, "high", hi)]
    return out


# For the README table: name -> (value as text, basis).
TABLE: list[tuple[str, str, str]] = [
    ("phone_ok_p", "0.85 (swept 0.60 / 0.98)", "assumption: own (not shared) listed numbers that reach the facility"),
    ("phone_shared_min", "3", "assumption, matches the app's shared-number warning"),
    ("open_now_p", "0.95 with a 24x7 claim, else 0.60 (swept 0.80/0.40, 0.99/0.85)", "assumption (#92)"),
    ("accept_p", "emergency 0.90, planned 0.75 (swept 0.70/0.50, 0.98/0.95)", "assumption"),
    ("exists", "Bernoulli(derived/v1 facility_trust.existence_score); 0.90 if missing", "data; fallback assumed"),
    ("no_mention_outside_frame_p", "0.05", "assumption: no DEV label covers these pairs"),
    ("k_cell, k_service", "4, 4 (effective n)", "assumption: Beta shrinkage of thin label cells"),
    ("wrong_yes_p", "0.10 (swept 0.00 / 0.30)", "assumption"),
    ("wrong_no_p", "0.05", "assumption"),
    ("call_minutes", "5", "assumption"),
    ("give_up_minutes", "480", "assumption"),
    ("has_data_p, has_signal_p", "0.80, 0.90", "assumption (stub world only)"),
    ("report_k", "4", "assumption (app + reports, future work)"),
]

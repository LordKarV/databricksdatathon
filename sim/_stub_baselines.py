"""TEMPORARY stand-in for sim/policies_baseline.py (issue #92). Delete once that lands.

Baselines see only what a facility directory shows: every listing that names the service, its map point and state,
and, for "best on paper", the model's p. Never the truth. Each tries at most N_OPTIONS facilities (equal caps).
- nearest: the N_OPTIONS nearest listings (straight line from the worker), no call ahead.
- nearest_call_first: the same list, phoning each before travelling, like the app. Separates the value of the
  ranking from the value of calling ahead (#92 review).
- best_on_paper: the highest p in the patient's state, ignoring distance, no call ahead.
The planner-route baseline is left out until #77 (the planner is on stub scores).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from sim.interface import N_OPTIONS, Case, Step


def _km(lat: float, lon: float, la: np.ndarray, lo: np.ndarray) -> np.ndarray:
    r = np.pi / 180
    a = np.sin((la - lat) * r / 2) ** 2 + np.cos(lat * r) * np.cos(la * r) * np.sin((lo - lon) * r / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


class Nearest:
    def __init__(self, name: str, call_first: bool) -> None:
        self.name, self.call_first = name, call_first

    def choose(self, case: Case, ctx: dict[str, Any]) -> list[Step]:
        ls = ctx["app"].listings(case.service)
        d = _km(case.lat, case.lon, ls["lat"], ls["lon"])
        order = np.argsort(d, kind="stable")[:N_OPTIONS]
        return [Step(str(ls["facility_id"][i]), self.call_first, f"nearest {k}: {d[i]:.1f} km")
                for k, i in enumerate(order, 1)]


class BestOnPaper:
    name = "best_on_paper"

    def choose(self, case: Case, ctx: dict[str, Any]) -> list[Step]:
        ls = ctx["app"].listings(case.service)
        idx = np.flatnonzero(np.char.upper(ls["state"].astype(str)) == case.state.upper())
        order = idx[np.argsort(-ls["p"][idx], kind="stable")][:N_OPTIONS]
        return [Step(str(ls["facility_id"][i]), False, f"best on paper {k}: p={ls['p'][i]:.2f}")
                for k, i in enumerate(order, 1)]


POLICIES: dict[str, Any] = {"nearest": Nearest("nearest", False),
                            "nearest_call_first": Nearest("nearest_call_first", True),
                            "best_on_paper": BestOnPaper()}

"""Baseline referral policies for the simulated world (#92). SIMULATED, not field data.

choose(case, ctx) -> list of steps {facility_id, call_first, note}, at most N_STEPS, tried in order.
ctx = context() holds only the public listing (sim/world.py listing()): no truth.
- nearest: the nearest facilities whose listing names the service (geo.travel estimate, hill-road constants).
- nearest_call_first: the same places, calling each before travelling, so calling ahead is not credited to ranking.
- best_on_paper: the highest published v2 p in the case's state among the same listings, ignoring distance.
The planner route is cut from the first run (#92 update: the planner is on stub scores until #77).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from geo.travel import estimate  # noqa: E402, RUF100
from sim import world  # noqa: E402, RUF100

N_STEPS = 3  # app N_OPTIONS
PREFILTER = 15  # straight-line nearest candidates that get a travel estimate


def context() -> dict:
    return {"listing": {s: world.listing(s) for s in world.SERVICES}}


def _km(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    la1, la2 = np.radians(lat), np.radians(lats)
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(np.radians(lons - lon) / 2) ** 2
    return 12742.0 * np.arcsin(np.sqrt(h))


def nearest(case: dict, ctx: dict, call_first: bool = False) -> list[dict]:
    lst = ctx["listing"][case["service"]]
    near = np.argsort(_km(case["lat"], case["lon"], lst.lat.to_numpy(), lst.lon.to_numpy()), kind="stable")
    cand = [(estimate((case["lat"], case["lon"]), (lst.lat[i], lst.lon[i]), case["state"])["minutes"],
             lst.unique_id[i]) for i in near[:PREFILTER]]
    return [{"facility_id": fid, "call_first": call_first, "note": f"nearest #{k + 1}, about {m} min"}
            for k, (m, fid) in enumerate(sorted(cand)[:N_STEPS])]


def nearest_call_first(case: dict, ctx: dict) -> list[dict]:
    return nearest(case, ctx, call_first=True)


def best_on_paper(case: dict, ctx: dict) -> list[dict]:
    lst = ctx["listing"][case["service"]]
    top = lst[lst.state == case["state"]].sort_values(["p", "unique_id"], ascending=[False, True]).head(N_STEPS)
    return [{"facility_id": fid, "call_first": False, "note": f"best on paper #{k + 1}, p {p:.2f}"}
            for k, (fid, p) in enumerate(zip(top.unique_id, top.p, strict=True))]


POLICIES = {"nearest": nearest, "nearest_call_first": nearest_call_first, "best_on_paper": best_on_paper}

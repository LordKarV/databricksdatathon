"""Thin adapter from the simulation to the shipped app: Engine.plan online, the state pack offline (issue #92).

Nothing here reads truth. Plans do not depend on truth either, so Engine.plan is cached per (origin rounded to
1e-3 degree, about the PIN centroid scale, service). The pack query reproduces app/static/pack.js RSPack.query:
nearest PIN of the saved state pack, that PIN's stored list, sorted by straight-line km from the worker.
"""
from __future__ import annotations

import gzip
import json
import math
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

import numpy as np

from sim.interface import ROOT

APP = ROOT / "app"
FACTS = APP / "facts" / "out" / "facts.json.gz"
PACKS = APP / "packs" / "out"
ROUND = 3  # cache key precision in degrees (about 110 m, the pack's PIN centroid scale)


def _app_path() -> None:
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))


def ensure_built(states: list[str]) -> None:
    """Build app/facts/out and the state packs when missing (both git-ignored build outputs)."""
    if not FACTS.is_file():
        subprocess.run([sys.executable, "app/facts/build.py"], cwd=ROOT, check=True, capture_output=True)
    missing = [s for s in states if not (PACKS / f"{slug(s)}.json.gz").is_file()]
    if missing:
        subprocess.run([sys.executable, "app/packs/build_packs.py", "--states", ",".join(missing)], cwd=ROOT,
                       check=True, capture_output=True)


def slug(state: str) -> str:
    """app/packs/build_packs.py slug()."""
    return re.sub(r"[^a-z0-9]+", "_", state.lower()).strip("_")


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = math.pi / 180
    a = (math.sin((lat2 - lat1) * r / 2) ** 2
         + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


@contextmanager
def rank_before_101(engine: Any) -> Iterator[None]:
    """The emergency order before PR #101 (value = p x exp(-minutes / 45), best first) for calls made inside the block.

    The engine reads its module's NEAREST_FIRST at call time, so the block empties it in the engine's own module and
    restores it on exit, error or not. Nothing under app/ changes; the simulation is single-threaded.
    """
    mod = sys.modules[type(engine).__module__]
    saved = mod.NEAREST_FIRST
    mod.NEAREST_FIRST = set()
    try:
        yield
    finally:
        mod.NEAREST_FIRST = saved


class AppAdapter:
    """The deployed app's answers, as the simulation needs them.

    old_emergency_rank=True answers with the emergency order before PR #101 (see rank_before_101()), for the
    app_before_101 policy only. It may share the engine object of a normal adapter: each adapter keeps its own plan
    cache, and the old order is in force only while this adapter calls the engine.
    """

    def __init__(self, engine: Any = None, old_emergency_rank: bool = False) -> None:
        _app_path()
        from facts.engine import N_OPTIONS, Engine  # the shipped engine, unchanged

        self.engine = engine or Engine.load()
        if self.engine is None:
            raise SystemExit("app/facts/out/facts.json.gz is missing: run .venv-app/bin/python app/facts/build.py")
        self.old_emergency_rank = old_emergency_rank
        self.n_options = N_OPTIONS
        self._plans: dict[tuple[float, float, str], dict] = {}
        self._packs: dict[str, dict | None] = {}
        self._listings: dict[str, dict[str, np.ndarray]] = {}
        self.ids = self.engine.fac["id"]
        self.by_uid8: dict[str, str] = {}
        for u in self.ids:
            self.by_uid8.setdefault(u[:8], u)

    def _rule(self) -> Any:
        return rank_before_101(self.engine) if self.old_emergency_rank else nullcontext()

    # ---------- online: Engine.plan ----------
    def plan(self, service: str, lat: float, lon: float) -> dict:
        key = (round(lat, ROUND), round(lon, ROUND), service)
        if key not in self._plans:
            with self._rule():
                self._plans[key] = self.engine.plan(service, key[0], key[1], None, "pin")
        return self._plans[key]

    def options(self, service: str, lat: float, lon: float) -> list[dict]:
        """The plan's options in the app's order: facility_id, band, model_band, p, minutes, call_first."""
        return [{"facility_id": o["facility_id"], "band": o["band"], "model_band": o["model_band"], "p": o["p"],
                 "minutes": o["travel"]["minutes"], "call_first": o["call_first"]}
                for o in self.plan(service, lat, lon)["options"]]

    @staticmethod
    def time_scale(service: str) -> float:
        """The engine's utility scale in minutes for the service's profile: value = p x exp(-minutes / scale)."""
        from facts.engine import TIME_SCALE
        from services import SERVICES

        return float(TIME_SCALE[SERVICES[service]["profile"]])

    def pool(self, service: str, lat: float, lon: float) -> list[dict]:
        """Every candidate the engine ranks (not only the top N_OPTIONS), for re-ranking with field reports."""
        with self._rule():
            pool, _ = self.engine._ranked(service, round(lat, ROUND), round(lon, ROUND))
        e = self.engine
        return [{"facility_id": e.fac["id"][pr.fi], "p": e.rank_p(pr, e.score(e.fac["id"][pr.fi], service)[1]),
                 "minutes": m, "band": band} for _, m, pr, _, band in pool]

    # ---------- offline: the state pack ----------
    def pack(self, state: str) -> dict | None:
        s = slug(state)
        if s not in self._packs:
            path = PACKS / f"{s}.json.gz"
            self._packs[s] = decode(json.loads(gzip.decompress(path.read_bytes()))) if path.is_file() else None
        return self._packs[s]

    def pack_options(self, state: str, service: str, lat: float, lon: float) -> list[dict]:
        """RSPack.query: the nearest PIN's list, sorted by straight-line km (pack.js), with full facility ids."""
        p = self.pack(state)
        if p is None or service not in p["index"]:
            return []
        d = [km(lat, lon, a, b) for a, b in zip(p["pins"]["lat"], p["pins"]["lon"], strict=True)]
        i = int(np.argmin(d))
        out = []
        for e in p["lists"][p["index"][service][i]]:
            fi = p["ev"]["f"][e]
            flat, flon = p["fac"]["lat"][fi], p["fac"]["lon"][fi]
            out.append({"facility_id": self.by_uid8.get(p["fac"]["uid8"][fi], p["fac"]["uid8"][fi]),
                        "likely": bool(p["ev"]["likely"][e]), "p": p["ev"]["p"][e] / 100,
                        "km_straight": round(km(lat, lon, flat, flon) * 10) / 10, "tel": p["fac"]["tel"][fi]})
        return sorted(out, key=lambda o: o["km_straight"])  # JS sort is stable, so is this

    # ---------- listings, for the baselines (what a facility directory shows) ----------
    def listings(self, service: str) -> dict[str, np.ndarray]:
        """Every facility whose listing names the service: id, map point, state, model p (derived/v2)."""
        if service in self._listings:
            return self._listings[service]
        e = self.engine
        rows = e.pairs[service]
        self._listings[service] = {
            "facility_id": np.array([e.fac["id"][r.fi] for r in rows]),
            "lat": np.array([e.fac["lat"][r.fi] for r in rows], dtype=float),
            "lon": np.array([e.fac["lon"][r.fi] for r in rows], dtype=float),
            "state": np.array([e.fac["state"][r.fi] or "" for r in rows]),
            "p": np.array([r.model[1] if r.model else r.score for r in rows], dtype=float)}
        return self._listings[service]


def decode(pack: dict) -> dict:
    """pack.js decode(): undo the delta encoding of a v1 pack."""
    if pack.get("v") != 1:
        raise ValueError(f"unsupported pack version {pack.get('v')}")

    def undelta(a: list[int], scale: float | None = None) -> list[float]:
        acc = np.cumsum(np.asarray(a, dtype=np.int64))
        return (acc / scale).tolist() if scale else acc.tolist()

    f, fs = pack["fac"], pack["scale"]["fac"]
    return {**pack,
            "fac": {**f, "lat": undelta(f["lat"], fs), "lon": undelta(f["lon"], fs)},
            "ev": {**pack["ev"], "f": undelta(pack["ev"]["f"])},
            "pins": {"pin": undelta(pack["pins"]["pin"]), "lat": undelta(pack["pins"]["lat"], pack["scale"]["pin"]),
                     "lon": undelta(pack["pins"]["lon"], pack["scale"]["pin"]), "d": pack["pins"]["d"]}}


def pack_path(state: str) -> Path:
    return PACKS / f"{slug(state)}.json.gz"

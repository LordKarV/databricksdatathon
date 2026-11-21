"""Planner inputs at run time, standard library only.

    store = Store.load()                     # planner/out/planner_v1.json.gz, or None if not built
    store.facilities()                       -> list of facility dicts for planner.plan
    store.capability_p(facility_id, cap)     -> (p, evidence_ids)
    store.state_near((lat, lon))             -> state of the nearest facility (for hill-road constants)

capability_p is the swap point for the model (#11): give planner.service a different function and
nothing else changes. The file is written by planner/export_v1.py.
"""
import gzip
import json
from pathlib import Path

from .core import hav_km

OUT = Path(__file__).resolve().parent / "out" / "planner_v1.json.gz"


class Store:
    def __init__(self, doc):
        f = doc["facilities"]
        self.meta = {"built_utc": doc["built_utc"], "probabilities": doc["probabilities"]}
        self.no_mention_p = doc["no_mention_p"]
        self._fac = [{"id": i, "name": n, "lat": la, "lon": lo, "town": t, "district": d, "state": s, "flags": fl}
                     for i, n, la, lo, t, d, s, fl in zip(f["id"], f["name"], f["lat"], f["lon"], f["town"],
                                                          f["district"], f["state"], f["flags"])]
        self._caps = {cap: {f["id"][i]: (p, e) for i, p, e in zip(c["i"], c["p"], c["e"])}
                      for cap, c in doc["capabilities"].items()}

    @classmethod
    def load(cls, path=OUT):
        path = Path(path)
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return cls(json.load(fh))

    def facilities(self):
        return self._fac

    def capability_p(self, facility_id, capability):
        if capability not in self._caps:
            raise KeyError(f"unknown capability {capability!r}")
        p, ids = self._caps[capability].get(facility_id, (self.no_mention_p, []))
        return p, list(ids)

    def state_near(self, origin):
        best = min(self._fac, key=lambda f: hav_km(origin, (f["lat"], f["lon"])), default=None)
        return best["state"] if best else None

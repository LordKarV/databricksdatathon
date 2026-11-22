"""Planner inputs at run time, standard library only.

    store = Store.load()                     # planner/out/planner_v2.json.gz, or None if not built
    store.facilities()                       -> list of facility dicts for planner.plan
    store.capability_p(facility_id, cap)     -> (p, evidence_ids)
    store.band(facility_id, cap)             -> "LIKELY" | "CALL_FIRST" | "NO_SERVICE_TEXT" (model v2
                                                tags; the last has p 0), "TEXT" (support tags v2 does not
                                                score), or None (UNLIKELY, or no mention)
    store.state_near((lat, lon))             -> state of the nearest PIN centroid (for hill-road
                                                constants); nearest facility if the file has no PINs

Probabilities come from model v2 (derived/v2) for the tags that map to a v2 service. A v2 pair that
is not in the file (NO_SERVICE_TEXT or UNLIKELY) has p 0, so it is never a stop. The file is written by
planner/export_v2.py.
"""
import gzip
import json
import os
from pathlib import Path

from .core import hav_km

BANDS = {"L": "LIKELY", "C": "CALL_FIRST", "T": "TEXT"}
OUT = Path(os.environ.get("PLANNER_OUT") or Path(__file__).resolve().parent / "out") / "planner_v2.json.gz"


class Store:
    def __init__(self, doc):
        f = doc["facilities"]
        self.meta = {"built_utc": doc["built_utc"], "probabilities": doc["probabilities"]}
        self.no_mention_p = doc["no_mention_p"]
        self._fac = [{"id": i, "name": n, "lat": la, "lon": lo, "town": t, "district": d, "state": s, "flags": fl}
                     for i, n, la, lo, t, d, s, fl in zip(f["id"], f["name"], f["lat"], f["lon"], f["town"],
                                                          f["district"], f["state"], f["flags"])]
        pins = doc.get("pins") or {}
        self._pins = [(la, lo, pins["states"][s]) for la, lo, s in zip(pins.get("lat", []), pins.get("lon", []), pins.get("s", []))]
        self._blood = doc.get("blood")
        self._caps = {cap: {f["id"][i]: (p, e, b) for i, p, e, b in zip(c["i"], c["p"], c["e"], c["b"])}
                      for cap, c in doc["capabilities"].items()}
        # tags scored by model v2: an absent pair was judged NO_SERVICE_TEXT or UNLIKELY, so it is not offered
        self.v2_caps = {cap for cap, c in doc["capabilities"].items() if c["source"].startswith("derived/v2")}
        self._silent = {cap: {f["id"][i] for i in c.get("n", [])} for cap, c in doc["capabilities"].items()}

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
        row = self._caps[capability].get(facility_id)
        if row is None:
            return (0.0 if capability in self.v2_caps else self.no_mention_p), []
        return row[0], list(row[1])

    def band(self, facility_id, capability):
        row = self._caps.get(capability, {}).get(facility_id)
        if row is None:
            return "NO_SERVICE_TEXT" if facility_id in self._silent.get(capability, ()) else None
        return BANDS[row[2]]

    def blood_facts(self):
        """List facts for blood (planner/implied.py), or None when the export has none."""
        b = self._blood
        if not b:
            return None
        by_id = {f["id"]: f for f in self._fac}
        centres = list(zip(b["centres"]["lat"], b["centres"]["lon"], b["centres"]["name"]))

        def nearest(fid):
            f = by_id.get(fid)
            if f is None or not centres:
                return None
            km, name = min((hav_km((f["lat"], f["lon"]), (la, lo)), n) for la, lo, n in centres)
            return km, name
        return {"matched": b["matched"], "nearest": nearest}

    def state_near(self, origin):
        """State of the nearest PIN centroid. Near a state border this can be the neighbouring state."""
        if self._pins:
            return min(self._pins, key=lambda p: hav_km(origin, (p[0], p[1])))[2]
        return state_of_nearest(origin, self._fac)


def state_of_nearest(origin, facilities):
    best = min(facilities, key=lambda f: hav_km(origin, (f["lat"], f["lon"])), default=None)
    return best.get("state") if best else None

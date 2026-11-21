"""Query resolution for the decision layer (spec 6.2), built on audit/geo/resolve_input.py.

resolve_place(text) -> dict(status, lat, lon, note, matches)
  status "ok"         one point; note is the echo shown to the user ("Using PIN 843317 (Singwahini BO), Sitamarhi, Bihar")
  status "ambiguous"  the name matches places in more than one state; matches lists them and the App asks the user to
                      pick. It never guesses.
  status "not_found"  nothing matched
Accepted forms: "lat, lon"; a 6-digit PIN; "<village> village, <district> district, <state>"; "<district> district,
<state>"; a district or city name (layers in resolve_input order: district, city, office).
"""
import re
import sys

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True  # audit/geo is read-only for this layer
sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from geo_common import CITY_ALIAS, PIN_DIR, norm, office_base  # noqa: E402
from resolve_input import build, resolve  # noqa: E402

COORD = re.compile(r"^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{2,3}\.\d+)\s*$")
PIN = re.compile(r"^\s*([1-9]\d{5})\s*$")


class Resolver:
    def __init__(self):
        self.layers, cen = build()
        self.cen = cen.set_index("pincode")
        d = pd.read_parquet(PIN_DIR)[["officename", "pincode", "district", "statename", "latitude", "longitude"]]
        d["office"] = d.officename.map(office_base)
        d["dn"], d["sn"] = d.district.map(norm), d.statename.map(norm)
        d["olat"] = pd.to_numeric(d.latitude, errors="coerce")
        d["olon"] = pd.to_numeric(d.longitude, errors="coerce")
        self.dir = d

    def _pin(self, pin):
        if pin not in self.cen.index:
            return dict(status="not_found", note=f"PIN {pin} is not in the India Post directory", matches=[])
        c = self.cen.loc[pin]
        o = self.dir[self.dir.pincode == pin].officename.iloc[0]
        return dict(status="ok", lat=float(c.best_lat), lon=float(c.best_lon), matches=[],
                    note=f"Using PIN {pin} ({o}), {str(c.district).title()}, {str(c.state).title()}")

    def _village(self, village, district, state):
        d = self.dir[(self.dir.office == norm(village)) & (self.dir.dn == norm(district))]
        if state:
            d = d[d.sn == norm(state)]
        if d.empty:
            return None
        if d.pincode.nunique() > 1:
            return dict(status="ambiguous", note=f"'{village}' matches {d.pincode.nunique()} post offices", matches=[
                f"{r.officename}, PIN {r.pincode}, {r.district.title()}" for r in d.itertuples()])
        r = d.iloc[0]
        lat, lon, src = (r.olat, r.olon, "office coordinates") if np.isfinite(r.olat) and np.isfinite(r.olon) else (
            float(self.cen.loc[r.pincode].best_lat), float(self.cen.loc[r.pincode].best_lon), "PIN centre")
        return dict(status="ok", lat=float(lat), lon=float(lon), matches=[],
                    note=f"Using PIN {r.pincode} ({r.officename}), {r.district.title()}, {r.statename.title()} ({src})")

    def _name(self, name, state=None):
        n = CITY_ALIAS.get(norm(name), norm(name))
        layer, npts, spread, states = resolve(n, self.layers)
        if layer is None:
            return dict(status="not_found", note=f"no place called '{name}' in the gazetteer", matches=[])
        pts, _ = self.layers[layer][n]
        if layer == "district" and (state or len(states) > 1):
            # the district layer stores PIN points; filter them by the PIN directory's state
            dd = self.dir[self.dir.dn == n].drop_duplicates("pincode").merge(
                self.cen[["best_lat", "best_lon", "state"]], left_on="pincode", right_index=True)
            if state:
                dd = dd[dd.sn == norm(state)]
                states = sorted(set(dd.state))
            if len(states) > 1:
                return dict(status="ambiguous", note=f"'{name}' is a district name in {len(states)} states; pick one",
                            matches=[f"{name.title()}, {s.title()}" for s in states])
            pts = dd[["best_lat", "best_lon"]].dropna().to_numpy()
        elif len(states) > 1:
            return dict(status="ambiguous", note=f"'{name}' matches places in {len(states)} states; pick one",
                        matches=[f"{name.title()}, {s.title()}" for s in states])
        if len(pts) == 0:
            return dict(status="not_found", note=f"no point for '{name}'", matches=[])
        lat, lon = float(np.median(pts[:, 0])), float(np.median(pts[:, 1]))
        st = states[0].title() if states else "?"
        return dict(status="ok", lat=lat, lon=lon, matches=[],
                    note=f"Using {name.title()} ({layer} layer, median of {len(pts)} PIN points), {st}")

    def resolve_place(self, text):
        m = COORD.match(text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            return dict(status="ok", lat=lat, lon=lon, matches=[], note=f"Using coordinates {lat:.4f}, {lon:.4f}")
        m = PIN.match(text)
        if m:
            return self._pin(int(m.group(1)))
        parts = [p.strip() for p in text.split(",")]
        village = next((re.sub(r"\s+village$", "", p, flags=re.I) for p in parts if re.search(r"\svillage$", p, re.I)), None)
        district = next((re.sub(r"\s+district$", "", p, flags=re.I) for p in parts if re.search(r"\sdistrict$", p, re.I)), None)
        state = parts[-1] if len(parts) > 1 and not re.search(r"(village|district)$", parts[-1], re.I) else None
        if village and district:
            r = self._village(village, district, state)
            if r:
                return r
        return self._name(district or parts[0], state)


if __name__ == "__main__":
    R = Resolver()
    a = R.resolve_place("Singwahini village, Sitamarhi district, Bihar")
    assert a["status"] == "ok" and "843317" in a["note"], a
    assert R.resolve_place("18.8193, 73.2852")["status"] == "ok"
    assert R.resolve_place("Aurangabad")["status"] == "ambiguous"  # Bihar and Maharashtra: must ask, never guess
    assert R.resolve_place("Aurangabad district, Bihar")["status"] == "ok"
    print("resolve ok:", a["note"], "|", R.resolve_place("Aurangabad")["matches"])

"""A typed place to a point (#121 bug 5): PIN, district, town or post office name, from data the server already has.

PINs and districts come from the PIN table in facts.json.gz, the same centroids the offline pack uses, so a district
centre online equals the one offline (offline.js districtCentre). Towns and post offices come from places.json.gz,
which facts/build.py writes from derived/v1 place_gazetteer. No external geocoder is called.
"""
from __future__ import annotations

import gzip
import json
import math
import re
from pathlib import Path
from typing import TypedDict

MAX_MATCHES = 6
NEAR_KM = 15  # "Near <place>" only when that place is this close; past it the line names only the district and PIN
TOWN_KM = 5  # a town centre this close is named before a nearer post office
_SUFFIX = re.compile(r"\s+(district|dist|zila|zilla|jila)$")
_KIND_ORDER = {"town": 0, "district": 1, "post_office": 2}  # a town centre is more precise than a district centre
_GAZ_KIND = {"city": "town", "office": "post_office"}
PIN_GRID = 1000  # the offline packs keep PIN points to 0.001 degree (packs/build_packs.py PIN_SCALE)
# A PIN as people copy it: "848 125" (India Post prints it so), "848-125", "PIN 848125", "pin: 848125", "848125.".
# Same rule as pinOf() in static/app.js, which the offline path uses.
_PIN = re.compile(r"(?:(?:pin|पिन)(?:\s*code|\s*कोड)?\s*[:#.\-]?\s*)?"
                  r"([0-9](?:[0-9\s\-]*[0-9])?)[.,;:!]*", re.IGNORECASE)


class Match(TypedDict, total=False):
    lat: float
    lon: float
    label: str
    kind: str  # pin | district | town | post_office
    state: str
    district: str  # only with district_from
    district_from: str  # a PIN the gazetteer files under no district: "nearest_pin" or "gazetteer_list"


class Near(TypedDict, total=False):
    district: str
    state: str
    pin: str
    place: str  # only when a town or post office is within NEAR_KM
    kind: str  # town | post_office
    km: float


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def norm(s: str) -> str:
    """Lower case, punctuation to spaces, single spaces, no trailing 'district'."""
    s = " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())
    return _SUFFIX.sub("", s)


def centre_pin(pts: list[tuple[int, int, int]]) -> int:
    """The district's own PIN nearest the mean of its PIN points, from (pin, lat, lon) in 0.001 degree integers.

    A plain mean can lie nearer another district's PINs (Anakapalli's is nearest a Visakhapatnam PIN, matrix cluster
    district_centre_in_other_district), and the area view, which names the district of the nearest PIN, then names
    the other one. A PIN point of the district itself cannot. Same rule as offline.js districtCentre, on the same
    integers the packs store, longitude scaled by cos(lat), lowest PIN on a tie (two PINs are always equally far
    from their mean), so online and offline pick the same PIN.
    """
    n, sa, so = len(pts), sum(x[1] for x in pts), sum(x[2] for x in pts)
    k = math.cos(math.radians(sa / n / PIN_GRID))
    return min(pts, key=lambda x: ((n * x[1] - sa) ** 2 + ((n * x[2] - so) * k) ** 2, x[0]))[0]


def pin_of(q: str) -> str | None:
    """The six digits of a typed PIN, or None when the text is not a PIN in one of the forms _PIN accepts."""
    m = _PIN.fullmatch(q.strip())
    d = re.sub(r"[\s\-]", "", m.group(1)) if m else ""
    return d if len(d) == 6 else None


def title(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in str(s).lower().split())


def load_places(path: Path) -> dict | None:
    return json.loads(gzip.decompress(path.read_bytes())) if path.is_file() else None


class Places:
    def __init__(self, pins: dict[str, list], places: dict | None) -> None:
        self.pins = pins
        self.pin_at = {p: i for i, p in enumerate(pins["pin"])}
        # facts/build.py marks each district's centre PIN, chosen from the raw gazetteer points on the packs' grid
        # (the 5 decimal points here can round to another 0.001 degree); tables without the column choose here
        marked = pins.get("centre") or [0] * len(pins["pin"])
        # facts/build.py fill_districts: "" when the gazetteer files the PIN under its district, else how we chose one
        self.district_from = pins.get("district_from") or [""] * len(pins["pin"])
        acc: dict[tuple[str, str], list] = {}
        for i, (d, s, how) in enumerate(zip(pins["district"], pins["state"], self.district_from, strict=True)):
            if not how:  # a district centre is one of the PINs filed there, as offline.js districtCentre
                acc.setdefault((norm(d), s), [d, []])[1].append(i)
        self.districts: dict[str, list[tuple[str, str, float, float]]] = {}
        for (key, s), (d, idx) in acc.items():
            c = [i for i in idx if marked[i]]
            i = c[0] if len(c) == 1 else self.pin_at[centre_pin(
                [(pins["pin"][i], round(pins["lat"][i] * PIN_GRID), round(pins["lon"][i] * PIN_GRID)) for i in idx])]
            self.districts.setdefault(key, []).append((d, s, pins["lat"][i], pins["lon"][i]))
        self.gaz = places
        self.names: dict[str, list[int]] = {}
        if places:
            for i, n in enumerate(places["name"]):
                self.names.setdefault(norm(n), []).append(i)

    def _district_of(self, lat: float, lon: float) -> str:
        """District of the nearest PIN centroid, only to tell same-named places apart in a label."""
        p, k = self.pins, math.cos(math.radians(lat))
        i = min((j for j, how in enumerate(self.district_from) if not how),
                key=lambda j: (p["lat"][j] - lat) ** 2 + ((p["lon"][j] - lon) * k) ** 2)
        return title(p["district"][i])

    def near(self, lat: float, lon: float) -> Near:
        """The phone's point in words (#140 3f): the nearest town or post office, and the district and PIN of the
        nearest PIN centroid filed under a district. The place is left out when it is over NEAR_KM away."""
        p, k = self.pins, math.cos(math.radians(lat))
        i = min((j for j, how in enumerate(self.district_from) if not how),
                key=lambda j: (p["lat"][j] - lat) ** 2 + ((p["lon"][j] - lon) * k) ** 2)
        out: Near = {"district": title(p["district"][i]), "state": title(p["state"][i]), "pin": str(p["pin"][i])}
        g = self.gaz
        if not g or not g["name"]:
            return out
        d2 = [(g["lat"][j] - lat) ** 2 + ((g["lon"][j] - lon) * k) ** 2 for j in range(len(g["name"]))]
        town = g["kinds"].index("city") if "city" in g["kinds"] else -1
        # a town the point is in reads better than the post office next door; else the nearest of either kind
        j = min((j for j in range(len(d2)) if g["k"][j] == town), key=d2.__getitem__, default=None)
        if j is None or _km(lat, lon, g["lat"][j], g["lon"][j]) > TOWN_KM:
            j = min(range(len(d2)), key=d2.__getitem__)
        km = _km(lat, lon, g["lat"][j], g["lon"][j])
        if km <= NEAR_KM:
            out.update(place=title(g["name"][j]), kind=_GAZ_KIND[g["kinds"][g["k"][j]]], km=round(km, 1))
        return out

    def lookup(self, q: str) -> list[Match]:
        """Every place the text names, best first (at most MAX_MATCHES); [] when nothing matches.

        'Name, State' keeps only matches in that state.
        """
        q = q.strip()
        pin = pin_of(q)
        if pin:
            i = self.pin_at.get(int(pin))
            if i is None:
                return []
            p, how = self.pins, self.district_from[i]
            if how:  # the gazetteer files no district here: the label names only the state, the district is a guess
                return [{"lat": p["lat"][i], "lon": p["lon"][i], "kind": "pin", "state": title(p["state"][i]),
                         "label": f"PIN {q}, {title(p['state'][i])}", "district": title(p["district"][i]),
                         "district_from": how}]
            return [{"lat": p["lat"][i], "lon": p["lon"][i], "kind": "pin", "state": title(p["state"][i]),
                     "label": f"PIN {pin}, {title(p['district'][i])}, {title(p['state'][i])}"}]
        name, _, state_q = q.rpartition(",") if "," in q else (q, "", "")
        key, sq = norm(name), norm(state_q)
        if not key:
            return []
        found = [("district", d, s, la, lo) for d, s, la, lo in self.districts.get(key, [])]
        g = self.gaz
        found += [(_GAZ_KIND[g["kinds"][g["k"][i]]], g["name"][i], g["states"][g["s"][i]], g["lat"][i], g["lon"][i])
                  for i in (self.names.get(key, []) if g else [])]
        found.sort(key=lambda m: (_KIND_ORDER[m[0]], m[2]))
        out: list[Match] = []
        seen: set[str] = set()
        for kind, name, s, la, lo in found:
            if s in seen or (sq and not norm(s).startswith(sq)):
                continue  # one match per state: the town, else the district centre, else the post office
            seen.add(s)
            where = {"town": f"{title(name)} town", "district": f"{title(name)} district centre",
                     "post_office": f"{title(name)} post office area, {self._district_of(la, lo)}"}[kind]
            out.append({"lat": la, "lon": lo, "kind": kind, "state": title(s), "label": f"{where}, {title(s)}"})
            if len(out) == MAX_MATCHES:
                break
        return out

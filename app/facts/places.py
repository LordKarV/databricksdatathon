"""A typed place to a point (#121 bug 5): PIN, district, town or post office name, from data the server already has.

PINs and districts come from the PIN table in facts.json.gz, the same centroids the offline pack uses, so a district
centre online equals the one offline (offline.js districtCentre). Towns and post offices come from places.json.gz,
which facts/build.py writes from derived/v1 place_gazetteer. No external geocoder is called.
"""
from __future__ import annotations

import difflib
import gzip
import json
import math
import re
from itertools import zip_longest
from pathlib import Path
from typing import TypedDict

MAX_MATCHES = 6
# Official renames, old to new. When the typed name is in none of our tables, the other name of its pair is tried
# (either way: our tables may carry the old name or the new one). When the old name is itself a place in our tables
# (Simla is a post office in Assam), the new one's matches in other states come first and the old ones stay, so
# neither is picked for the user. Source for every pair: "List of renamed places in India",
# https://en.wikipedia.org/wiki/List_of_renamed_places_in_India (with the year where that list gives one).
RENAMES: tuple[tuple[str, str], ...] = (
    ("bombay", "mumbai"),  # 1995
    ("madras", "chennai"),  # 1996
    ("calcutta", "kolkata"),  # 2001
    ("gurgaon", "gurugram"),  # 2016
    ("allahabad", "prayagraj"),
    ("alleppey", "alappuzha"),
    ("poona", "pune"),  # 1978
    ("cawnpore", "kanpur"),
    ("banaras", "varanasi"),
    ("benares", "varanasi"),  # the older spelling of Banaras
    ("gauhati", "guwahati"),
    ("cannanore", "kannur"),
    ("palghat", "palakkad"),
    ("quilon", "kollam"),
    ("trichur", "thrissur"),
    ("tanjore", "thanjavur"),
    ("trivandrum", "thiruvananthapuram"),
    ("calicut", "kozhikode"),
    ("cochin", "kochi"),  # 1996
    ("baroda", "vadodara"),  # 1974
    ("pondicherry", "puducherry"),  # 2006
    ("simla", "shimla"),
    ("jubbulpore", "jabalpur"),
    ("bangalore", "bengaluru"),  # 1 November 2014, with the eleven below
    ("mysore", "mysuru"),
    ("mangalore", "mangaluru"),
    ("belgaum", "belagavi"),
    ("gulbarga", "kalaburagi"),
    ("bellary", "ballari"),
    ("shimoga", "shivamogga"),
    ("tumkur", "tumakuru"),
    # not ("bijapur", "vijayapura"): Bijapur is also the current name of a district in Chhattisgarh
    ("hubli", "hubballi"),
    ("chikmagalur", "chikkamagaluru"),
    ("hoshangabad", "narmadapuram"),
    ("faizabad", "ayodhya"),
    ("aurangabad", "chhatrapati sambhaji nagar"),
    ("osmanabad", "dharashiv"),
    ("ahmednagar", "ahilyanagar"),
    # not a rename: the common short name of Visakhapatnam, used for no other place (served as how "rename")
    ("vizag", "visakhapatnam"),
)
# A spelling match (difflib ratio, same first letter) only when the name and its rename find nothing. 'Baharaich'
# to 'bahraich' scores 0.94.
SPELLING_CUTOFF = 0.9
SPELLING_TIE = 0.05  # every name scoring this close to the best is offered: a near miss never picks one for the user
SPELLING_MIN_LEN = 5  # shorter names are one letter away from too many others
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
    matched_as: dict  # only from Places.resolve's fallbacks: {"query", "name", "how": "rename" | "spelling"}
    district: str  # only with district_from
    district_from: str  # a PIN the gazetteer files under no district: "nearest_pin" or "gazetteer_list"


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
        self.renames: dict[str, list[str]] = {}  # either way, for a name our tables do not have
        self.renamed_to: dict[str, list[str]] = {}  # old to new only, for an old name that is also a place
        for a, b in RENAMES:
            self.renames.setdefault(a, []).append(b)
            self.renames.setdefault(b, []).append(a)
            self.renamed_to.setdefault(a, []).append(b)
        self.by_letter: dict[str, list[str]] = {}
        for k in sorted(set(self.districts) | set(self.names)):
            self.by_letter.setdefault(k[:1], []).append(k)

    def _district_of(self, lat: float, lon: float) -> str:
        """District of the nearest PIN centroid, only to tell same-named places apart in a label."""
        p, k = self.pins, math.cos(math.radians(lat))
        i = min((j for j, how in enumerate(self.district_from) if not how),
                key=lambda j: (p["lat"][j] - lat) ** 2 + ((p["lon"][j] - lon) * k) ** 2)
        return title(p["district"][i])

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

    def resolve(self, q: str) -> tuple[list[Match], dict | None]:
        """lookup(q), else what an official rename (RENAMES) or a close spelling of the name finds. An old name that
        is also a place keeps its own matches after those of its new name in other states (Simla: Shimla first).

        Returns (matches, matched_as). Every match a fallback finds carries matched_as = {"query", "name", "how"}
        ("rename" or "spelling"), so the page can say which name it shows. "query" is the name as norm() read it,
        never the raw text (/api/place does not echo input). The second value is that dict when all
        matches come from one name, else None. Every name within SPELLING_TIE of the best spelling score is offered,
        each with at least one match, so a near miss is never quietly read as one of two real places.
        """
        found = self.lookup(q)
        if pin_of(q):
            return found, None
        name, _, state_q = q.strip().rpartition(",") if "," in q else (q, "", "")
        key, tail = norm(name), (f", {state_q}" if state_q.strip() else "")
        if found:  # an old name that is also a place: add the renamed place where it is in another state
            have = {m["state"] for m in found}
            new = [(n, ms) for n in self.renamed_to.get(key, [])
                   if (ms := [m for m in self.lookup(n + tail) if m["state"] not in have])]
            return ((self._tagged(new, key, "rename")[0] + found)[:MAX_MATCHES], None) if new else (found, None)
        if not key:
            return [], None
        for other in self.renames.get(key, []):
            if found := self.lookup(other + tail):
                return self._tagged([(other, found)], key, "rename")
        if len(key) < SPELLING_MIN_LEN or not key[0].isalpha():
            return [], None
        scored = self._spellings(key)
        if not scored:
            return [], None
        best = scored[0][0]
        hits = [(k, ms) for r, k in scored if r >= best - SPELLING_TIE and (ms := self.lookup(k + tail))]
        return self._tagged(hits, key, "spelling") if hits else ([], None)

    def _spellings(self, key: str) -> list[tuple[float, str]]:
        """(difflib ratio, name) of every known name with key's first letter scoring SPELLING_CUTOFF or more, best
        first (then by name, so the order never depends on the tables' order)."""
        sm = difflib.SequenceMatcher(autojunk=False)
        sm.set_seq2(key)
        out = []
        for k in self.by_letter.get(key[0], []):
            sm.set_seq1(k)
            if sm.real_quick_ratio() >= SPELLING_CUTOFF and sm.quick_ratio() >= SPELLING_CUTOFF \
                    and (r := sm.ratio()) >= SPELLING_CUTOFF:
                out.append((r, k))
        return sorted(out, key=lambda t: (-t[0], t[1]))

    @staticmethod
    def _tagged(hits: list[tuple[str, list[Match]]], key: str, how: str) -> tuple[list[Match], dict | None]:
        """Each name's matches tagged with matched_as, interleaved (every name's first match before any second)."""
        tagged = [[{**m, "matched_as": {"query": key, "name": title(n), "how": how}} for m in ms]
                  for n, ms in hits]
        out = [m for row in zip_longest(*tagged) for m in row if m][:MAX_MATCHES]
        return out, (out[0]["matched_as"] if len(tagged) == 1 else None)

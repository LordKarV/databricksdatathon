"""Real facilities behind the plan contract (issue #42): /api/plan, /api/area and the slip read from here.

Loads app/facts/out/facts.json.gz (built by facts/build.py from derived/v1) once at start-up. Everything model-like
is behind score(); the rest only assembles stored rows into the contract in app/README.md.
"""
from __future__ import annotations

import gzip
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from services import BAND_WORDS, SERVICES, emergency_numbers, haversine_km, travel

OUT = Path(__file__).resolve().parent / "out"
RADIUS_KM = 150  # straight-line search radius
N_OPTIONS = 3
N_TRAVEL = 40  # travel estimates for the nearest candidates only
# value = p x exp(-minutes / scale): the scale by urgency; the area window in minutes
TIME_SCALE = {"emergency": 45, "urgent": 60, "scheduled": 120, "planned": 240}
WINDOW = {"emergency": 60, "urgent": 60, "scheduled": 120, "planned": 240}
OWN_EVIDENCE = {"strong", "moderate"}
UNLIKELY_GRADES = {"attributed_elsewhere", "counter_evidence"}

RULE_PLAIN = {
    "G_strong": "own specific sentences about it", "G_mod": "an own sentence about it",
    "G_weak": "only a general sentence", "G_tag": "only a specialty or tag list",
    "G_scope": "its name suggests a different specialty", "G_else": "its sentence names another facility",
    "G_no": "a sentence says it is not offered",
}
WHY_NOT = {
    "G_else": "Its {label} sentence names another facility", "G_no": "A sentence says it does not offer {label}",
    "G_tag": "{label} appears only in a specialty or tag list", "G_weak": "Its sentence about {label} is not specific",
    "G_scope": "Its name suggests a different specialty",
}
WHERE = {
    "LOC_HIGH": "Map point, PIN and city agree", "LOC_MEDIUM": "Map point roughly agrees with the PIN",
    "LOC_COORDS_FAR": "Map point is far from its PIN; check the address",
    "LOC_CITY_ELSEWHERE": "City and map point disagree; check the address",
    "LOC_DISPUTED_OR_LOW": "Location is approximate or disputed",
}
RISK_PLAIN = {
    "location": "Its location is uncertain.",
    "name_collision": "Another listing has a similar name; make sure you have the right one.",
    "service_elsewhere": "A sentence may describe this service at another branch.",
    "counter": "Another sentence says it does not offer this.",
    "unit_gt_capacity": "The unit it claims is larger than its recorded size.",
    "outpatient_type": "Listed as a clinic or outpatient place.",
    "scope": "Its name suggests a different specialty.",
}


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _pts(x: float) -> int:
    return round(10 * x)


@dataclass
class Pair:
    fi: int
    grade: str
    rule: str
    status: str
    score: float
    lo: float
    hi: float
    q_ev: float
    score_model: float
    evidence: list[str]
    missing: list[str]
    risks: list[str]
    qty: str | None
    n_own: int
    model: list | None
    listings: int = 1  # duplicate listings of this site merged into it (#78); the score is the best member's


class Engine:
    def __init__(self, facts: dict, sha: str) -> None:
        self.meta, self.rules, self.fac, self.claims, self.pins = (
            facts["meta"], facts["rules"], facts["fac"], facts["claims"], facts["pins"])
        self.sha = sha
        self.pairs = {s: [Pair(*row) for row in rows] for s, rows in facts["pairs"].items()}
        self.index = {s: {p.fi: p for p in rows} for s, rows in self.pairs.items()}
        self.fid = {u: i for i, u in enumerate(self.fac["id"])}

    @classmethod
    def load(cls, out: Path = OUT) -> Engine | None:
        path = out / "facts.json.gz"
        if not path.is_file():
            return None
        sha = (out / "facts.sha").read_text().strip() if (out / "facts.sha").is_file() else "unknown"
        return cls(json.loads(gzip.decompress(path.read_bytes())), sha)

    # ---------- the one scoring function (#11's model drops in here) ----------
    def score(self, facility_id: str, service_id: str) -> tuple[str, float, float, float, list[dict], list[str]]:
        """(band, p, lo, hi, contributions, evidence_ids) for one facility and service."""
        pr = self.index[service_id][self.fid[facility_id]]
        ev = [c for c in pr.evidence if c in self.claims and not self.claims[c][2]
              and self.claims[c][3] != "other_facility"][:3]
        if pr.model:  # derived/v2 published: its band and interval, one contribution row
            band, p, lo, hi = pr.model
            return band, p, lo, hi, [{"label": "model score (derived/v2)", "points": _pts(_logit(p))},
                                     *self._listings(pr)], ev
        # Interim, conservative: Likely only for pairs verified true by a second source.
        # A second-source check outranks the text grade: it is the stronger evidence (#85: two confirmed pairs were
        # banded Unlikely because the grade was tested first).
        if pr.status == "verified_false":
            band = "unlikely"
        elif pr.status == "verified_true":
            band = "likely"
        elif pr.grade in UNLIKELY_GRADES:
            band = "unlikely"
        else:
            band = "not_verified"
        # Points are the stored score split in log-odds x 10: evidence rule, then sources, then the gold check.
        contrib = [{"label": f"evidence: {RULE_PLAIN.get(pr.rule, pr.rule)}", "points": _pts(_logit(pr.q_ev))}]
        src = _pts(_logit(pr.score_model) - _logit(pr.q_ev))
        if src:
            contrib.append({"label": "sources it is listed on", "points": src})
        gold = _pts(_logit(pr.score) - _logit(pr.score_model))
        if gold:
            contrib.append({"label": "checked against a second source: " +
                            ("confirmed" if pr.status == "verified_true" else "contradicted"), "points": gold})
        return band, pr.score, pr.lo, pr.hi, contrib + self._listings(pr), ev

    @staticmethod
    def _listings(pr: Pair) -> list[dict]:
        """A site listed more than once is scored by its best evidenced listing; say so, with no points of its own."""
        if pr.listings <= 1:
            return []
        return [{"label": f"best evidenced record of {pr.listings} duplicate listings", "points": 0}]

    # ---------- helpers ----------
    def _f(self, k: str, i: int):
        return self.fac[k][i]

    def _travel(self, lat: float, lon: float, i: int, state: str | None = None) -> dict:
        return travel(lat, lon, self._f("lat", i), self._f("lon", i), state)

    def origin_state(self, lat: float, lon: float) -> str | None:
        """State of the nearest facility: the planner's rule when no state is given, so the cards and the route use
        the same terrain constants (#85: one hospital showed 31-52 min on its card and 37-112 min on the route)."""
        # equirectangular distance is enough to pick the nearest point; computed once per request
        k = math.cos(math.radians(lat))
        la, lo = self.fac["lat"], self.fac["lon"]
        best = min(range(len(la)), default=None, key=lambda i: (la[i] - lat) ** 2 + ((lo[i] - lon) * k) ** 2)
        return None if best is None else self._f("state", best)

    def _near(self, service: str, lat: float, lon: float) -> list[tuple[float, Pair]]:
        out = []
        for pr in self.pairs[service]:
            km = haversine_km(lat, lon, self._f("lat", pr.fi), self._f("lon", pr.fi))
            if km <= RADIUS_KM:
                out.append((km, pr))
        out.sort(key=lambda t: t[0])
        return out[:N_TRAVEL]

    def _phone(self, i: int) -> dict:
        raw = self._f("phone_raw", i)
        return {"e164": self._f("phone_e164", i), "display": raw or None, "shared_listings": self._f("phone_shared", i)}

    def _address(self, i: int) -> str:
        parts = [self._f("city", i), self._f("district", i), self._f("state", i)]
        txt = ", ".join(dict.fromkeys(p.title() if p and p.isupper() else p for p in parts if p))
        pin = self._f("pin", i)
        return f"{txt} {pin}" if pin else txt

    def _call_ahead(self, pr: Pair, band: str, label: str, i: int) -> list[dict]:
        qs = []
        if band != "likely":
            q = (f"Do you do {label} here yourselves, or send patients elsewhere?" if pr.grade == "tag_only"
                 else f"Can you do {label} today?")
            qs.append({"question": q, "asked_because": "listing not confirmed by a second source"})
        if pr.missing:
            need = pr.missing[0].replace("_or_", " or ").replace("_", " ")
            qs.append({"question": f"Do you have {need} on site?", "asked_because": "our data does not mention it"})
        if "claims_6plus_of_8_services" in self._f("flags", i) or "copies_far_apart" in self._f("flags", i):
            qs.append({"question": "Is this the branch in this town, or another branch?",
                       "asked_because": "record may merge several branches"})
        if self._f("phone_shared", i) >= 3:
            qs.append({"question": "Is this number the hospital itself?",
                       "asked_because": "the same number is listed for other places"})
        qs.append({"question": "What does it cost? Is PM-JAY accepted?",
                   "asked_because": "our data does not say if it is public or private"})
        return qs[:3]

    def _flags(self, pr: Pair, i: int) -> list[str]:
        out = list(self._f("reasons", i))
        out += [RISK_PLAIN[r] for r in pr.risks if r in RISK_PLAIN and RISK_PLAIN[r] not in out]
        ignored = [c for c in pr.evidence if c in self.claims and self.claims[c][3] == "other_facility"][:1]
        out += [f'Ignored: "{self.claims[c][1]}" names another facility' for c in ignored]
        return out

    def _is_real(self, i: int) -> list[str]:
        out = []
        if self._f("website_own", i):
            out.append("own website")
        if self._f("phone_e164", i):
            out.append("phone not shared with other listings" if self._f("phone_shared", i) <= 1
                       else "phone also listed for other places")
        if not self._f("reasons", i):
            out.append("no concerns found in its record")
        return out or ["no own website or phone in our data"]

    def option(self, rank: int, pr: Pair, service: str, lat: float, lon: float, trav: dict) -> dict:
        i, label = pr.fi, SERVICES[service]["label_en"]
        fid = self._f("id", i)
        band, p, lo, hi, contrib, ev = self.score(fid, service)
        rule = self.rules.get(pr.rule, {"n": 0, "k_confirmed": 0, "k_contradicted": 0})
        url = self._f("url", i)
        say = (f"This hospital's listing says it offers {label}. It is about {round(trav['km'])} kilometres away. "
               "We will phone before going.") if band == "likely" else (
               f"This hospital's listing mentions {label}, but we have not confirmed it. It is about "
               f"{round(trav['km'])} kilometres away. We will phone before going.")
        return {
            "rank": rank, "facility_id": fid, "name": self._f("name", i), "town": self._f("city", i) or "",
            "district": self._f("district", i) or "", "state": self._f("state", i) or "",
            "address": self._address(i), "operator": "unknown",
            "lat": self._f("lat", i), "lon": self._f("lon", i), "travel": trav,
            "band": band, "band_word": BAND_WORDS[band],
            "band_reason": None if band == "likely" else (
                "listing evidence not yet confirmed by a second source" if band == "not_verified"
                else RULE_PLAIN.get(pr.rule, "contradicted by a second source")),
            "p": round(p, 2), "p_lo": round(lo, 2), "p_hi": round(hi, 2),
            "p_e": self._f("p_e", i), "p_l": self._f("p_l", i),
            "evidence": [{"claim_id": c, "field": self.claims[c][0], "quote": self.claims[c][1],
                          "source_url": url or ""} for c in ev],
            "contributions": contrib, "flags": self._flags(pr, i),
            "call_ahead": self._call_ahead(pr, band, label, i), "call_first": rank == 1,
            "track_record": {"n": rule["n"], "k_confirmed": rule["k_confirmed"],
                             "k_contradicted": rule["k_contradicted"],
                             "k_no_info": 0, "split": "dev"},
            "phone": self._phone(i), "is_real": self._is_real(i),
            "where_check": WHERE.get(self._f("loc_rule", i), "Location not checked"),
            "why_first_text": None, "say_to_family": {"en": say, "hi": None},
        }

    def _ranked(self, service: str, lat: float, lon: float, state: str | None = None) -> tuple[list, list]:
        """(pool, unlikely): [(utility, minutes, pair, travel, band)] sorted best first / nearest first."""
        scale = TIME_SCALE[SERVICES[service]["profile"]]
        pool, unlikely = [], []
        state = state or self.origin_state(lat, lon)
        for _, pr in self._near(service, lat, lon):
            band, p, *_, ev = self.score(self._f("id", pr.fi), service)
            if not ev and band != "unlikely":
                continue  # every recommendation cites facility text (#85): a pair with no usable quote is not offered
            tr = self._travel(lat, lon, pr.fi, state)
            row = (p * math.exp(-tr["minutes"] / scale), tr["minutes"], pr, tr, band)
            (unlikely if band == "unlikely" else pool).append(row)
        # Distance counts for every band: a confirmed listing three hours away should not outrank one an hour away
        # by default. Likely options still carry a higher p, and the abstention depends on the band, not the order.
        pool.sort(key=lambda r: -r[0])
        unlikely.sort(key=lambda r: r[1])
        return pool, unlikely

    def _outside(self, service: str, lat: float, lon: float) -> dict | None:
        best = None
        for i, ok in enumerate(self.fac["public_standard"]):
            if ok:
                km = haversine_km(lat, lon, self._f("lat", i), self._f("lon", i))
                if km <= RADIUS_KM and (best is None or km < best[0]):
                    best = (km, i)
        if best is None:
            return None
        i = best[1]
        return {"facility_id": self._f("id", i), "name": self._f("name", i), "operator": "unknown",
                "text": "By the public standard a hospital at this level should offer it; not verified in our data.",
                "travel": self._travel(lat, lon, i, self.origin_state(lat, lon))}

    # ---------- /api/plan ----------
    def plan(self, service: str, lat: float, lon: float, accuracy_m: float | None, source: str) -> dict:
        info, label = SERVICES[service], SERVICES[service]["label_en"]
        pool, unlikely = self._ranked(service, lat, lon)
        chosen = pool[:N_OPTIONS]
        # Never hide a confirmed listing in reach: if none made the top slots, it takes the last one.
        best_likely = next((r for r in pool if r[4] == "likely"), None)
        if best_likely and best_likely not in chosen:
            chosen = chosen[: N_OPTIONS - 1] + [best_likely]
        options = [self.option(k + 1, r[2], service, lat, lon, r[3]) for k, r in enumerate(chosen)]
        if len(options) > 1:
            nearest = min(range(len(chosen)), key=lambda k: chosen[k][1])
            if nearest != 0:
                n, o = options[nearest], options[0]
                options[0]["why_first_text"] = (
                    f"{n['name']} is nearer (about {n['travel']['minutes']} min), but this listing's evidence is "
                    f"stronger ({o['p']:.2f} against {n['p']:.2f}), so it ranks first.")
        first_min = chosen[0][1] if chosen else float("inf")
        picked = {r[2].fi for r in chosen}
        why_rows = sorted([r for r in pool if r[2].fi not in picked and r[1] < first_min] + unlikely,
                          key=lambda r: r[1])[:3]
        why_not = [{"facility_id": self._f("id", r[2].fi), "name": self._f("name", r[2].fi), "travel": r[3],
                    "reason": WHY_NOT.get(r[2].rule, "Less evidence about {label} than the options above")
                    .format(label=label)} for r in why_rows if r[1] < first_min]
        abstain = None
        if not any(o["band"] == "likely" for o in options):
            abstain = {"text": (f"No facility within {RADIUS_KM} km is confirmed for {label}. The listings below say "
                                "they offer it; call to confirm before going.") if options else
                       f"No facility in our data within {RADIUS_KM} km lists {label}.",
                       "outside_option": self._outside(service, lat, lon)}
        return {
            "query": {"service": service, "service_label": {"en": label, "hi": info["label_hi"]}},
            "location": {"lat": lat, "lon": lon, "accuracy_m": accuracy_m, "source": source, "rounded_to_deg": 0.01},
            "as_of": self.meta["as_of"], "profile": info["profile"], "emergency_numbers": emergency_numbers(service),
            "abstain": abstain, "options": options, "why_not": why_not, "meta": self._meta(),
        }

    def _meta(self) -> dict:
        return {"stub": False, "model_hash": f"interim-{self.sha}" if "interim" in self.meta["scores"] else self.sha,
                "data_snapshot": f"{self.meta['source']} {self.meta['as_of']}", "scores": self.meta["scores"],
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds")}

    # ---------- /api/area ----------
    def area(self, service: str, lat: float, lon: float, max_pins: int = 40) -> dict:
        info, label = SERVICES[service], SERVICES[service]["label_en"]
        pins = self.pins
        k = min(range(len(pins["pin"])), key=lambda j: (pins["lat"][j] - lat) ** 2 + (pins["lon"][j] - lon) ** 2)
        district, state = pins["district"][k], pins["state"][k]
        idx = sorted((j for j in range(len(pins["pin"])) if pins["district"][j] == district
                      and pins["state"][j] == state), key=lambda j: pins["pin"][j])[:max_pins]
        window = WINDOW[info["profile"]]
        rows, gains, n_now, n_conf = [], {}, 0, 0
        for j in idx:
            plat, plon = pins["lat"][j], pins["lon"][j]
            pool, _ = self._ranked(service, plat, plon, state)
            within = [r for r in pool if r[1] <= window and r[2].grade in OWN_EVIDENCE | {"tag_only", "weak"}
                      and (r[4] == "likely" or r[2].grade in OWN_EVIDENCE)]
            likely = [r for r in within if r[4] == "likely"]
            n_now += bool(likely)
            n_conf += bool(within)
            if not likely:
                for r in within:
                    gains.setdefault(r[2].fi, set()).add(pins["pin"][j])
            first, backup = (within + [None, None])[:2]
            near = min((r for r in pool if r[2].grade in OWN_EVIDENCE), key=lambda r: r[1], default=None)
            rows.append({
                "pin": pins["pin"][j], "lat": plat, "lon": plon,
                "first": {"facility_id": self._f("id", first[2].fi), "name": self._f("name", first[2].fi)}
                if first else None,
                "backup": {"facility_id": self._f("id", backup[2].fi), "name": self._f("name", backup[2].fi)}
                if backup else None,
                "travel": {"low": first[3]["low"], "high": first[3]["high"]} if first else None,
                "call_first": self._f("name", first[2].fi) if first else None,
                "nearest_km": None if first else (round(near[3]["km"], 1) if near else None),
            })
        n = len(rows) or 1
        calls = sorted(gains.items(), key=lambda t: (-len(t[1]), self._f("name", t[0])))[:10]
        return {
            "query": {"service": service, "service_label": {"en": label, "hi": info["label_hi"]}},
            "area": {"district": district.title(), "state": state.title(), "window_min": window},
            "as_of": self.meta["as_of"],
            "summary": {"n_pins": len(rows), "n_without_option": sum(r["first"] is None for r in rows),
                        "access_now": round(n_now / n, 2), "access_if_confirmed": round(n_conf / n, 2),
                        "calls_could_close": round((n_conf - n_now) / n, 2),
                        "no_public_evidence": round(1 - n_conf / n, 2)},
            "caveat": "Low web presence looks like a gap. Verify before deciding.",
            "pins": rows,
            "ten_calls": [{"rank": r + 1, "facility_id": self._f("id", fi), "name": self._f("name", fi),
                           "phone_kind": self._phone_kind(fi), "areas": len(p), "access_gain": round(len(p) / n, 3)}
                          for r, (fi, p) in enumerate(calls)],
            "meta": self._meta(),
        }

    def _phone_kind(self, i: int) -> str:
        e = self._f("phone_e164", i)
        if not e:
            return "no number"
        if self._f("phone_shared", i) >= 2:
            return f"shared x{self._f('phone_shared', i)}"
        return "own mobile" if e[3] in "6789" else "landline"


def timed_load() -> tuple[Engine | None, float]:
    t = time.perf_counter()
    e = Engine.load()
    return e, time.perf_counter() - t

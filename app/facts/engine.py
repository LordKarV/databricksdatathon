"""Real facilities behind the plan contract (issue #42): /api/plan, /api/area and the slip read from here.

Loads app/facts/out/facts.json.gz (built by facts/build.py from derived/v1) once at start-up. Everything model-like
is behind score(); the rest only assembles stored rows into the contract in app/README.md.
"""
from __future__ import annotations

import gzip
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from services import BAND_WORDS, SERVICES, emergency_numbers, haversine_km, travel

from facts.ledger_terms import nabh_text
from facts.redact import redact_names

# New user-facing strings (#121), en and hi, ready to move into the strings files of the app-wide language setting.
# The payload carries "en"; the Hindi question is also in static/speech_templates.json for read-aloud.
STRINGS = {
    "need_today": {"en": "Is {need} available today for this patient?",
                   "hi": "क्या आज इस मरीज़ के लिए {need} की सुविधा मिल पाएगी?"},
    "need_named": {"en": "its listing names it, but not whether it is free today",
                   "hi": "इसकी लिस्टिंग में यह लिखा है, पर यह नहीं कि आज खाली है या नहीं"},
    # Route guard (#140 WS2 2c, app/itinerary.py). hi: None until WS2 2e adds the engine table rows to hi.json.
    "route_dropped": {"en": "Go straight to {name}; it is nearer than any other place with evidence for every stage.",
                      "hi": None},
    "stop_no_line": {"en": "No line in its listing names {need}; ask on the phone.", "hi": None},
    "stop_1_unlisted": {"en": "The route starts at {name}, which is not in the options list: no listing near here "
                              "names this service itself, so each stop is chosen on the evidence for its own stage.",
                        "hi": None},
    "private_cost": {"en": "private hospital, may charge", "hi": "प्राइवेट अस्पताल, पैसे लग सकते हैं"},
}
OUT = Path(__file__).resolve().parent / "out"
# Area district brief (WS4 4b): where each number comes from, for the payload and the page's Sources line.
NEED_SOURCE = {"people": "WorldPop 2025 (CC BY 4.0), summed over the LGD district polygon",
               "listings": "the provided facility dataset", "nfhs": "NFHS-5 district fact sheets (2019-21)"}
LAQSHYA_SOURCE = "NHSRC LaQshya master data, 08-04-2026"
PMNDP_SOURCE = "NHSRC, PMNDP data (nhsrcindia.org/pmndp-map-table)"
N_GOV = 5  # government-list rows on the Area brief
RADIUS_KM = 150  # straight-line search radius
N_OPTIONS = 3
N_TRAVEL = 40  # travel estimates for the nearest candidates only
# Non-emergency order: value = p x exp(-minutes / scale), the scale by urgency; the area window in minutes.
TIME_SCALE = {"emergency": 45, "urgent": 60, "scheduled": 120, "planned": 240}
# Emergency order (#92): nearest plausible place first, call it, and if it says no call the next. A "no" on the
# phone costs minutes, a wasted trip costs the window, so distance leads; p only chooses among the places within
# TIE_MIN of the nearest one left.
# The simulation showed the p x exp(-minutes / 45) order losing to "nearest + call first" in every scenario.
NEAREST_FIRST = {"emergency"}
TIE_MIN = 5
CALL_MIN = 5  # assumed minutes per phone call, used only for expected_in_window (sim/assumptions.py has the range)
RANK_RULE = {
    "nearest_plausible": "Nearest place that plausibly offers it first; call first, and if they say no, call the next.",
    "evidence_and_time": "Ordered by how sure we are, discounted by travel time.",
}
WINDOW = {"emergency": 60, "urgent": 60, "scheduled": 120, "planned": 240}
OWN_EVIDENCE = {"strong", "moderate"}
UNLIKELY_GRADES = {"attributed_elsewhere", "counter_evidence"}
# Listed website the crawl could not check or flags unreliable (#117 A, BE-001; facts/build.py site_flags and
# SITE_STATUS), en and hi like STRINGS above. "unchecked" is neutral and has no reason line; "unreliable" names its
# reason (no_identity, other_org) in one short line. Neither site is ever cited as a source.
SITE_STRINGS = {
    "unchecked": {"en": "Listed website could not be checked", "hi": "लिस्टिंग की वेबसाइट जाँची नहीं जा सकी"},
    "unreliable": {"en": "Listed website unreliable", "hi": "लिस्टिंग में दी गई वेबसाइट भरोसे लायक नहीं"},
    "no_identity": {"en": "it opens, but no page on it names this facility",
                    "hi": "वेबसाइट खुलती है, पर किसी पेज पर इस अस्पताल का नाम नहीं है"},
    "other_org": {"en": "it may belong to another organisation", "hi": "यह किसी दूसरी संस्था की वेबसाइट हो सकती है"},
    "not_cited": {"en": "We do not cite it as a source.", "hi": "हम इसे सबूत के तौर पर नहीं दिखाते।"},
}
# Tie-break from health-worker reports (#86, lead's rule): leading options in the same band whose shown p differ by
# at most TIE_P and whose travel differs by at most TIE_TRAVEL_MIN are tied; only those are reordered, and only for
# TIE_BREAK_PROFILES: scheduled and planned care. Emergency (#101) and urgent care (NICU: a sick newborn is
# time-critical) never move on report counts (lead's decision on #116).
TIE_P, TIE_TRAVEL_MIN = 0.05, 10
TIE_BREAK_PROFILES = {"scheduled", "planned"}


def tied_prefix(rows: list[tuple[float, float, str]]) -> int:
    """How many leading rows (p, minutes, band), in rank order, tie with each other; 0 when fewer than two do.
    Every pair in the group must tie, so the group never chains across a gap larger than the rule allows."""
    n = 1
    while n < len(rows):
        grp = rows[: n + 1]
        ps, ms = [round(r[0], 2) for r in grp], [r[1] for r in grp]
        if (len({r[2] for r in grp}) > 1 or max(ps) - min(ps) > TIE_P + 1e-9
                or max(ms) - min(ms) > TIE_TRAVEL_MIN):
            break
        n += 1
    return n if n > 1 else 0

def nearest_plausible(rows: list, window: float = math.inf) -> list:
    """Rows (p, minutes, ...) in emergency order: repeatedly the highest p among the rows within TIE_MIN of the
    nearest row left (no fixed buckets, so 102 and 103 minutes are always a tie), nearer first on equal p. A tie
    never crosses the window: while the nearest row left is inside it, only rows inside it compete.
    Engine pool rows carry the uncapped p sixth: two rows capped at the same rank_p (NO_SERVICE_TEXT) are told
    apart by it before distance (#140 2a: a children's clinic at p 0.56 led a hospital at 0.98, both capped)."""
    rest, out = sorted(rows, key=lambda r: r[1]), []
    while rest:
        reach = rest[0][1] + TIE_MIN
        if rest[0][1] <= window:
            reach = min(reach, window)
        near = [r for r in rest if r[1] <= reach]
        best = max(near, key=lambda r: (r[0], r[5] if len(r) > 5 else r[0], -r[1]))
        out.append(best)
        rest.remove(best)
    return out


def expected_in_window(rows: list[tuple[float, float]], window: float, call_min: float = CALL_MIN) -> float:
    """Chance of care within the window when the options are called in order and the first "yes" is visited:
    rows are (p, minutes); the k-th call ends at k x call_min. p is the model's chance that a decisive web check
    confirms the service, not the chance of a "yes" on the phone, so this treats one as a stand-in for the other."""
    e, miss = 0.0, 1.0
    for k, (p, minutes) in enumerate(rows, 1):
        if k * call_min + minutes <= window:
            e += miss * p
        miss *= 1 - p
    return round(e, 3)


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
# Data-quality warnings shown next to a quote (#86): (text, weak). Weak quotes are listed after clean ones.
# Source codes come from the record's cited page (url_kind, place_gazetteer); the rest from claims.parquet columns.
QUOTE_FLAGS = {
    "src_list": ("Weak: the source is a list of many places, not a page about this facility", True),
    "src_unverified": ("Weak: the source page does not name this facility", True),
    "src_other_place": ("Weak: the source is a page about another place", True),
    "ambiguous": ("Weak: this sentence may be about another facility", True),
    "foreign": ("Weak: this sentence also names another facility", True),
    "other_district": ("Weak: this sentence names a place in another district", True),
    "other_state": ("Weak: this sentence names a place in another state", True),
    "third_party": ("Weak: an outside or partner facility may do this", True),
    "hedge": ("Weak: the wording is unsure", True),
    "camp": ("Weak: this reads like a one-off camp", True),
    "future": ("Weak: this reads like a plan, not a service today", True),
    "past": ("Weak: this may describe the past", True),
    "parttime": ("Note: this may be part-time or on some days only", False),
}
# Prerequisites the grader looks for (grades.parquet pre_* columns), in words for the why-not line.
NEED_PLAIN = {
    "emergency_24x7": "24x7 emergency care", "ct": "a CT scanner", "surgery_or_ortho": "surgery or orthopaedics",
    "operating_theatre": "an operating theatre", "anaesthesia": "anaesthesia", "obstetrics": "obstetrics",
    "incubator_warmer_ventilator": "incubators, warmers or ventilators", "paeds_or_neonatology": "a children's doctor",
    "dialysis_unit_or_machine": "a dialysis unit or machines", "nephrology": "a kidney specialist",
    "mri_scanner": "an MRI scanner", "cathlab_or_heart_lung": "a cath lab or heart-lung machine",
    "cardiothoracic_surgeon_or_dept": "a heart surgeon",
    "burn_unit_or_plastic_surgery": "a burn unit or plastic surgery",
}
# Why the call asks about cost, by the operator the card shows; None leaves the question out.
COST_REASON = {"private": STRINGS["private_cost"]["en"], "public": None,
               "unknown": "our data does not say if it is public or private"}
# Words that name each prerequisite in a quote. A call-ahead question never says "our data does not mention it"
# when a quote on the card names it (#121: "Do you have a dialysis unit?" next to "Advanced Kidney Dialysis").
NEED_WORDS = {k: re.compile(v, re.I) for k, v in {
    "emergency_24x7": r"24\s*[x/×*]\s*7|24[- ]hours?|round[- ]the[- ]clock", "ct": r"\bct\b|computed tomography",
    "surgery_or_ortho": r"surg|orthop", "operating_theatre": r"operation theat|operating theat|\bOT\b",
    "anaesthesia": r"an(a)?esthe", "obstetrics": r"obstet|gyn(a)?ec|maternity",
    "incubator_warmer_ventilator": r"incubat|warmer|ventilat", "paeds_or_neonatology": r"p(a)?ediat|neonat|\bnicu\b",
    "dialysis_unit_or_machine": r"dialys", "nephrology": r"nephro", "mri_scanner": r"\bmri\b|magnetic resonance",
    "cathlab_or_heart_lung": r"cath ?lab|catheteri[sz]ation lab|heart[- ]lung",
    "cardiothoracic_surgeon_or_dept": r"cardiothoracic|\bctvs\b|cardiac surg|heart surg|bypass|\bcabg\b",
    "burn_unit_or_plastic_surgery": r"\bburns?\b|plastic surg",
}.items()}
LOC_DOUBT = {"LOC_COORDS_FAR", "LOC_CITY_ELSEWHERE", "LOC_DISPUTED_OR_LOW"}
N_WHY_NOT = 3
# "Say this to the family" by the model's band (#140 2d). A NO_SERVICE_TEXT listing never "says it offers" the care,
# whatever band field reports give it. New English strings for the hi.json engine table (2e).
SAY = {
    "likely": "This hospital's listing says it offers {label}. It is {dist}. We will phone before going.",
    "mentions": "This hospital's listing mentions {label}, but we have not confirmed it. It is {dist}. "
                "We will phone before going.",
    "NO_SERVICE_TEXT": "Its listing has no line of its own about {label} (it names it only in a list). "
                       "We will phone to ask before going.",
}
LIKELY_FARTHER = ("It is rated Likely, but it is {n} min farther. In an emergency we phone the nearest plausible "
                  "place first and go on if they say no")


def km_words(km: float) -> str:
    """'less than 1 km away' under 1 km (never '0 km'), else 'about N km away' in whole km."""
    return "less than 1 km away" if km < 1 else f"about {round(km)} km away"
PUBLIC_LABEL = "by public standard, not verified"
PUBLIC_LEVEL = {"phc": "primary health centre", "chc": "community health centre", "sdh": "sub-divisional hospital",
                "dh": "district hospital", "mc": "medical college hospital"}
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
    ledger: list | None = None  # derived/v2 terms: [[term, tenths of a point, [claim ids]], ...], base first
    not_observed: str = ""  # families derived/v2 cannot see for this pair, e.g. "WO" (facts/ledger_terms.py)
    lists: list | None = None  # derived/v2 ON_A_PUBLIC_LIST overlays: [[list, date], ...] (WS4 4a)


class Engine:
    def __init__(self, facts: dict, sha: str, moved: dict[str, list[str]] | None = None) -> None:
        self.meta, self.rules, self.fac, self.pins = facts["meta"], facts["rules"], facts["fac"], facts["pins"]
        # (district, state) where each PIN point lies (facts/build.py pin_districts, validation C4); its own otherwise
        self.pin_where = [tuple((moved or {}).get(str(pin), (d, st))) for pin, d, st in
                          zip(self.pins["pin"], self.pins["district"], self.pins["state"], strict=True)]
        # Every quote leaves the server with doctors' names redacted (#86): options, route stops and flags alike.
        self.claims = {k: [f, redact_names(t), *rest] for k, (f, t, *rest) in facts["claims"].items()}
        self.claim_flags = facts.get("claim_flags", {})
        for k in ("url_kind", "url_place", "url_site", "site_flag", "site_status"):  # older exports: no source or site checks
            self.fac.setdefault(k, [None] * len(self.fac["id"]))
        self.site_check = facts.get("site_check") or {}
        self.sha = sha
        self.track_bins = facts.get("track_bins", [])
        self.likely_threshold = facts.get("likely_threshold")
        self.test_record = facts.get("test_record")  # sealed gold v3 TEST record of LIKELY (#86); None if absent
        self.pairs = {s: [Pair(*row) for row in rows] for s, rows in facts["pairs"].items()}
        words = facts.get("ledger", {})  # older exports: no ledger, one "model score" row
        self.terms, self.not_observed = words.get("terms", {}), words.get("not_observed", {})
        self.cites, self.list_names = words.get("cites", {}), words.get("lists", {})
        self.fac.setdefault("nabh", [None] * len(self.fac["id"]))
        self.index = {s: {p.fi: p for p in rows} for s, rows in self.pairs.items()}
        self.brief = facts.get("district_brief")  # older exports: no district brief, the Area page leaves it out
        self.fid = {u: i for i, u in enumerate(self.fac["id"])}
        # The score a pair gets once a second source confirms it (the gold override): used for "what would change".
        self.p_confirmed = min((p.score for rows in self.pairs.values() for p in rows if p.status == "verified_true"),
                               default=0.95)

    @classmethod
    def load(cls, out: Path = OUT) -> Engine | None:
        path = out / "facts.json.gz"
        if not path.is_file():
            return None
        sha = (out / "facts.sha").read_text().strip() if (out / "facts.sha").is_file() else "unknown"
        moved = out / "pin_districts.json"
        return cls(json.loads(gzip.decompress(path.read_bytes())), sha,
                   json.loads(moved.read_text()) if moved.is_file() else None)

    # ---------- the one scoring function (#11's model drops in here) ----------
    def score(self, facility_id: str, service_id: str) -> tuple[str, float, float, float, list[dict], list[str]]:
        """(band, p, lo, hi, contributions, evidence_ids) for one facility and service."""
        pr = self.index[service_id][self.fid[facility_id]]
        ev = self._evidence(pr)
        if pr.model:  # derived/v2 published: its band and interval, and its ledger rows
            band, p, lo, hi, *_ = pr.model
            rows = self._ledger(pr) if pr.ledger else [{"label": "Model score", "points": _pts(_logit(p))}]
            return band, p, lo, hi, [*rows, *self._listings(pr)], ev
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

    def _ledger(self, pr: Pair) -> list[dict]:
        """The model's named terms on the app's scale (10 points per logit unit), base first. The build spreads the
        rounding so the points sum to round(10 x logit(p), 1). A row's quotes are the app claims its term cites."""
        rows = []
        for term, tenths, cids, *rest in pr.ledger:
            family, en, hi = self.terms[term]
            rows.append({"label": en, "label_hi": hi, "family": family, "points": tenths / 10,
                         "quotes": [{"claim_id": c, "field": self.claims[c][0], "quote": self.claims[c][1]}
                                    for c in cids if c in self.claims],
                         "cites": [self._cite(c) for c in (rest[0] if rest else []) if c in self.cites]})
        return rows

    def _cite(self, cid: str) -> dict:
        """One official-list or OpenStreetMap row a ledger term rests on (facts/build.py cites()), with its link."""
        text, url, source, fetched, tier, k, n = self.cites[cid]
        return {"id": cid, "text": text, "url": url, "source": source, "fetched_date": fetched, "tier": tier,
                "precision_k": k, "precision_n": n}

    def _public_lists(self, pr: Pair, i: int) -> list[dict]:
        """The official lists derived/v2 found this facility on, for one "Official lists" line. A NABH entry says
        which kind it is (facts/ledger_terms.py NABH_TIER): a CGHS/ECHS empanelment is not accreditation."""
        out = []
        for key, date in pr.lists or []:
            row = {"list": key, "name": self.list_names.get(key, key), "fetched_date": date}
            nabh = self._f("nabh", i)
            if key == "nabh" and nabh:
                tier, acc, url = nabh
                row |= {"tier": tier, "id": acc, "url": url, "text": nabh_text(tier, acc)}
            out.append(row)
        return out

    def _not_observed(self, pr: Pair) -> list[dict]:
        """Families the model cannot see for this pair: they add no points, so they are named, not scored."""
        return [{"family": f, "label": self.not_observed[f][0], "label_hi": self.not_observed[f][1]}
                for f in pr.not_observed if f in self.not_observed]

    def _track(self, p: float, rule: dict) -> dict:
        """Of the checked listings at this level, how many were confirmed, contradicted or left without information.

        From the model card's score bin when published (#82 H2). Before that, the evidence rule's hand checks, which
        recorded only confirmed and contradicted: k_no_info is None (not recorded), never a made-up 0.
        """
        if self.track_bins:
            # Equal-count bins have data-dependent edges and need not tile [0, 1] (#84 review): a p below the lowest
            # edge, above the highest or in a gap takes the nearest bin, and the basis says which bin it was.
            b = min(self.track_bins, key=lambda b: 0 if b["lo"] <= p <= b["hi"] else min(abs(p - b["lo"]),
                                                                                          abs(p - b["hi"])))
            return {**{k: b[k] for k in ("n", "k_confirmed", "k_contradicted", "k_no_info", "split")},
                    "basis": f"score {b['lo']:.2f} to {b['hi']:.2f}"}
        return {"n": rule["n"], "k_confirmed": rule["k_confirmed"], "k_contradicted": rule["k_contradicted"],
                "k_no_info": None, "split": "dev", "basis": "evidence rule"}

    def _evidence(self, pr: Pair) -> list[str]:
        """The claim ids a card quotes for this pair: its own sentences, at most three."""
        ev = [c for c in pr.evidence if c in self.claims and not self.claims[c][2]
              and self.claims[c][3] != "other_facility"]
        return sorted(ev, key=self._n_weak)[:3]  # demoted, not hidden: flagged sentences come after clean ones

    def _n_weak(self, cid: str) -> int:
        return sum(QUOTE_FLAGS[c][1] for c, _ in self.claim_flags.get(cid, []) if c in QUOTE_FLAGS)

    def quote_flags(self, cid: str, i: int | None = None) -> list[dict]:
        """Warnings for one quoted sentence; with a facility index, also for the source page it links to."""
        raw: list[tuple[str, str | None, int | None]] = []
        if i is not None:
            place, kind = self._f("url_place", i), self._f("url_kind", i)
            if place:
                raw.append(("src_other_place", place[0], place[1]))
            elif kind in ("list", "unverified"):
                raw.append(("src_" + kind, None, None))
        raw += [(c, d, None) for c, d in self.claim_flags.get(cid, []) if c in QUOTE_FLAGS]
        return [{"code": c, "text": QUOTE_FLAGS[c][0], "weak": QUOTE_FLAGS[c][1], "place": d, "km": km}
                for c, d, km in raw]

    @staticmethod
    def _listings(pr: Pair) -> list[dict]:
        """A site listed more than once is scored by its best evidenced listing; say so, with no points of its own."""
        if pr.listings <= 1:
            return []
        return [{"label": f"best evidenced record of {pr.listings} duplicate listings", "points": 0}]

    # ---------- helpers ----------
    def _f(self, k: str, i: int):
        return self.fac[k][i]

    def rank_p(self, pr: Pair, p: float) -> float:
        """p for ranking. A NO_SERVICE_TEXT pair has no sentence about the service as its own unit, so its p rests on
        context alone (derived/v2/README: "show the band, not p"). It ranks as if at most at the LIKELY threshold, so a
        district hospital with p 0.95 from its level never outranks a listing that describes the service."""
        if pr.model and pr.model[4] == "NO_SERVICE_TEXT" and self.likely_threshold is not None:
            return min(p, self.likely_threshold)
        return p

    def _exists_where(self, pr: Pair, i: int) -> dict[str, float | None]:
        """p_e, p_l: the model's P_E and P_L for this pair (derived/v2 p_exists, p_location), the values its band rule
        tests (#121: the derived/v1 facility trust scores showed 0.34 on a Likely card). Interim pairs keep v1's."""
        if pr.model and len(pr.model) > 6:
            return {"p_e": pr.model[6], "p_l": pr.model[5]}
        return {"p_e": self._f("p_e", i), "p_l": self._f("p_l", i)}

    @staticmethod
    def model_band(pr: Pair) -> str | None:
        return pr.model[4] if pr.model and len(pr.model) > 4 else None

    def _operator(self, i: int) -> str:
        ops = self.fac.get("operator")  # older facts files have no operator column
        return ops[i] if ops else "unknown"

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
            qs.append({"question": q, "asked_because": "listing not rated Likely"})
        if pr.missing:
            need = pr.missing[0].replace("_or_", " or ").replace("_", " ")
            words = NEED_WORDS.get(pr.missing[0])
            if words and any(words.search(self.claims[c][1]) for c in self._evidence(pr)):
                # a quote on the card names it: what is unknown is whether it can take this patient today
                qs.append({"question": STRINGS["need_today"]["en"].format(need=need),
                           "asked_because": STRINGS["need_named"]["en"]})
            else:
                qs.append({"question": f"Do you have {need} on site?", "asked_because": "our data does not mention it"})
        if "claims_6plus_of_8_services" in self._f("flags", i) or "copies_far_apart" in self._f("flags", i):
            qs.append({"question": "Is this the branch in this town, or another branch?",
                       "asked_because": "record may merge several branches"})
        if self._f("phone_shared", i) >= 3:
            qs.append({"question": "Is this number the hospital itself?",
                       "asked_because": "the same number is listed for other places"})
        # The reason matches the card's operator label (#121: "does not say if it is public or private" sat on a card
        # labelled Government); a government hospital is not asked about cost.
        why = COST_REASON.get(self._operator(i), COST_REASON["unknown"])
        if why:
            qs.append({"question": "What does it cost? Is PM-JAY accepted?", "asked_because": why})
        return qs[:3]

    def _flags(self, pr: Pair, i: int) -> list[str]:
        out = list(self._f("reasons", i))
        out += [RISK_PLAIN[r] for r in pr.risks if r in RISK_PLAIN and RISK_PLAIN[r] not in out]
        ignored = [c for c in pr.evidence if c in self.claims and self.claims[c][3] == "other_facility"][:1]
        out += [f'Ignored: "{self.claims[c][1]}" names another facility' for c in ignored]
        return out

    def cited_url(self, i: int) -> str:
        """The source page a quote links to; "" when that page is the listed website and the crawl flags it (#117 A)."""
        if self._f("site_status", i) and self._f("url_site", i):
            return ""
        return self._f("url", i) or ""

    def website(self, i: int) -> dict | None:
        """{site_status, reason, label, reason_line, text} in en and hi when the listed website is not cited (#117 A,
        BE-001); None otherwise. reason_line is None for "unchecked", which states no reason against the site."""
        status, code = self._f("site_status", i), self._f("site_flag", i)
        if not status:
            return None
        s, stop = SITE_STRINGS, {"en": ".", "hi": "।"}
        label = dict(s[status])
        if status == "unchecked":
            return {"site_status": status, "reason": code, "label": label, "reason_line": None,
                    "text": {k: f"{label[k]}{stop[k]} {s['not_cited'][k]}" for k in stop}}
        line = {"en": s[code]["en"][:1].upper() + s[code]["en"][1:] + stop["en"], "hi": s[code]["hi"] + stop["hi"]}
        return {"site_status": status, "reason": code, "label": label, "reason_line": line,
                "text": {k: f"{label[k]}: {s[code][k]}{stop[k]} {s['not_cited'][k]}" for k in stop}}

    def _is_real(self, i: int) -> list[str]:
        out = []
        if status := self._f("site_status", i):  # an unchecked or unreliable site is no sign it is real (#117 A)
            out.append(SITE_STRINGS[status]["en"])
        elif self._f("website_own", i):
            out.append("own website")
        if self._f("phone_e164", i):
            out.append("phone not shared with other listings" if self._f("phone_shared", i) <= 1
                       else "phone also listed for other places")
        if not self._f("reasons", i):
            out.append("no concerns found in its record")
        return out or ["no own website or phone in our data"]

    def _scored(self, fid: str, service: str, scores: dict | None) -> tuple:
        """score(), or the caller's replacement for this facility (community/field.py's field-adjusted score)."""
        return (scores or {}).get(fid) or self.score(fid, service)

    def say_to_family(self, pr: Pair, band: str, label: str, km: float) -> str:
        """The family sentence by model_band, then by the shown band (field reports can lower a Likely card)."""
        if self.model_band(pr) == "NO_SERVICE_TEXT":
            return SAY["NO_SERVICE_TEXT"].format(label=label)
        return SAY["likely" if band == "likely" else "mentions"].format(label=label, dist=km_words(km))

    def option(self, rank: int, pr: Pair, service: str, lat: float, lon: float, trav: dict,
               scores: dict | None = None) -> dict:
        i, label = pr.fi, SERVICES[service]["label_en"]
        fid = self._f("id", i)
        band, p, lo, hi, contrib, ev = self._scored(fid, service, scores)
        rule = self.rules.get(pr.rule, {"n": 0, "k_confirmed": 0, "k_contradicted": 0})
        url = self.cited_url(i)
        evidence = [{"claim_id": c, "field": self.claims[c][0], "quote": self.claims[c][1], "source_url": url,
                     "flags": self.quote_flags(c, i)} for c in ev]
        say = self.say_to_family(pr, band, label, trav["km"])
        return {
            "rank": rank, "facility_id": fid, "name": self._f("name", i), "town": self._f("city", i) or "",
            "district": self._f("district", i) or "", "state": self._f("state", i) or "",
            "address": self._address(i), "operator": self._operator(i),
            "lat": self._f("lat", i), "lon": self._f("lon", i), "travel": trav,
            "band": band, "band_word": BAND_WORDS[band],
            "band_reason": None if band == "likely" else (
                "listing evidence not strong enough to rate it Likely" if band == "not_verified"
                else RULE_PLAIN.get(pr.rule, "contradicted by a second source")),
            "p": round(p, 2), "p_lo": round(lo, 2), "p_hi": round(hi, 2),
            # v2's lo / hi are the confirmed rate of checked DEV pairs at a similar score, not an interval around p
            "range_kind": "similar_scores" if pr.model else "interval", "model_band": self.model_band(pr),
            **self._exists_where(pr, i),
            "evidence": evidence,
            "contributions": contrib + ([{"label": "quoted sentences with a warning are listed last", "points": 0}]
                                        if any(f["weak"] for e in evidence for f in e["flags"]) else []),
            "not_observed": self._not_observed(pr),
            "public_lists": self._public_lists(pr, i),
            "flags": self._flags(pr, i),
            "call_ahead": self._call_ahead(pr, band, label, i), "call_first": rank == 1,
            "track_record": self._track(p, rule),
            "phone": self._phone(i), "is_real": self._is_real(i), "website": self.website(i),
            "where_check": WHERE.get(self._f("loc_rule", i), "Location not checked"),
            "why_first_text": None, "say_to_family": {"en": say, "hi": None},
        }

    def _ranked(self, service: str, lat: float, lon: float, state: str | None = None,
                scores: dict | None = None) -> tuple[list, list]:
        """(pool, unlikely): [(utility, minutes, pair, travel, band, p)] sorted best first / nearest first; p is the
        uncapped score, which breaks ties between equal capped rank_p in the emergency order."""
        profile = SERVICES[service]["profile"]
        scale = TIME_SCALE[profile]
        pool, unlikely = [], []
        state = state or self.origin_state(lat, lon)
        for _, pr in self._near(service, lat, lon):
            band, p, *_, ev = self._scored(self._f("id", pr.fi), service, scores)
            if not ev and band != "unlikely":
                continue  # every recommendation cites facility text (#85): a pair with no usable quote is not offered
            tr = self._travel(lat, lon, pr.fi, state)
            rp = self.rank_p(pr, p)
            row = (rp if profile in NEAREST_FIRST else rp * math.exp(-tr["minutes"] / scale), tr["minutes"], pr, tr,
                   band, p)
            (unlikely if band == "unlikely" else pool).append(row)
        # Distance counts for every band: a confirmed listing three hours away should not outrank one an hour away
        # by default. Likely options still carry a higher p, and the abstention depends on the band, not the order.
        pool = (nearest_plausible(pool, WINDOW[profile]) if profile in NEAREST_FIRST
                else sorted(pool, key=lambda r: -r[0]))
        unlikely.sort(key=lambda r: r[1])
        return pool, unlikely

    def _public_near(self, service: str, lat: float, lon: float, exclude: frozenset = frozenset()) -> tuple[float, int] | None:
        """(km, index) of the nearest facility the public standard (IPHS 2022) expects to offer this service at its
        level, within RADIUS_KM. Skips `exclude` ids and listings our data rates Unlikely for the service (#85 H2)."""
        best = None
        for i, svcs in enumerate(self.fac["public_standard"]):
            if service in svcs and self._f("id", i) not in exclude and not self._unlikely(i, service):
                km = haversine_km(lat, lon, self._f("lat", i), self._f("lon", i))
                if km <= RADIUS_KM and (best is None or km < best[0]):
                    best = (km, i)
        return best

    def _unlikely(self, i: int, service: str) -> bool:
        return i in self.index[service] and self.score(self._f("id", i), service)[0] == "unlikely"

    def _outside(self, service: str, lat: float, lon: float, exclude: frozenset = frozenset()) -> dict | None:
        """The public-standard option: never one already listed or explained under "why not" (#85 H2)."""
        best = self._public_near(service, lat, lon, exclude)
        if best is None:
            return None
        i = best[1]
        level = PUBLIC_LEVEL.get(self.fac["public_level"][i], "public hospital")
        return {"facility_id": self._f("id", i), "name": self._f("name", i), "operator": self._operator(i),
                "label": PUBLIC_LABEL,
                "text": f"By the public standard (IPHS 2022) a {level} should offer it; not verified in our data.",
                "travel": self._travel(lat, lon, i, self.origin_state(lat, lon))}

    # ---------- /api/plan ----------
    def plan(self, service: str, lat: float, lon: float, accuracy_m: float | None, source: str,
             scores: dict | None = None, tiebreak: dict[str, float] | None = None,
             lead: dict[str, str] | None = None) -> dict:
        """scores: {facility_id: score() tuple} replacing score() for those facilities, so the ranking, the
        abstention and every sentence below are built from the same p and band the card shows.
        tiebreak: {facility_id: value}, higher first, used only among tied leading options (tied_prefix); missing
        facilities count 0. The payload then gains tie_break when the values told the tied options apart.
        lead: {facility_id: reason line}, set by itinerary.attach after the route is built (#121): the first key
        becomes option 1 when it is in the ranked pool, the other options keep their order, and each listed option
        gets its line as route_reason and why_first_text. The ranking itself is unchanged."""
        info, label = SERVICES[service], SERVICES[service]["label_en"]
        pool, unlikely = self._ranked(service, lat, lon, scores=scores)
        tie = None
        if tiebreak and info["profile"] in TIE_BREAK_PROFILES:
            pool, tie = self._break_tie(service, pool, scores, tiebreak)
        chosen = pool[:N_OPTIONS]
        head = next((r for r in pool if lead and self._f("id", r[2].fi) == next(iter(lead))), None)
        if head:  # ponytail: a route stop outside the pool (no quote, beyond N_TRAVEL) leaves the order as ranked
            chosen = ([head] + [r for r in chosen if r is not head])[:N_OPTIONS]
        # Never hide a confirmed listing in reach: if none made the top slots, it takes the last one.
        best_likely = next((r for r in pool if r[4] == "likely"), None)
        if best_likely and best_likely not in chosen:
            chosen = chosen[: N_OPTIONS - 1] + [best_likely]
        options = [self.option(k + 1, r[2], service, lat, lon, r[3], scores) for k, r in enumerate(chosen)]
        nearest_first = info["profile"] in NEAREST_FIRST
        if nearest_first and options:
            options[0]["why_first_text"] = RANK_RULE["nearest_plausible"]
        elif len(options) > 1:
            nearest = min(range(len(chosen)), key=lambda k: chosen[k][1])
            # After a tie-break the first need not have the stronger evidence; the sentence is then left out.
            if nearest != 0 and options[0]["p"] > options[nearest]["p"]:
                n, o = options[nearest], options[0]
                options[0]["why_first_text"] = (
                    f"{n['name']} is nearer (about {n['travel']['minutes']} min), but this listing's evidence is "
                    f"stronger ({o['p']:.2f} against {n['p']:.2f}), so it ranks first.")
        for o in options if head else []:
            if o["facility_id"] in lead:
                o["route_reason"] = o["why_first_text"] = lead[o["facility_id"]]
        why_not, change = self._why_not(service, chosen, pool + unlikely, options)
        window = WINDOW[info["profile"]]
        abstain = None
        shown = frozenset(o["facility_id"] for o in options) | {w["facility_id"] for w in why_not}
        public = self._outside(service, lat, lon, shown)
        if not any(o["band"] == "likely" for o in options):
            abstain = {"text": (f"No facility within {RADIUS_KM} km is confirmed for {label}. The listings below say "
                                "they offer it; call to confirm before going.") if options else
                       f"No facility in our data within {RADIUS_KM} km lists {label}.",
                       "outside_option": public}
        first_outside = bool(options) and options[0]["travel"]["minutes"] > window
        return {
            "query": {"service": service, "service_label": {"en": label, "hi": info["label_hi"]}},
            "location": {"lat": lat, "lon": lon, "accuracy_m": accuracy_m, "source": source, "rounded_to_deg": 0.01},
            "as_of": self.meta["as_of"], "profile": info["profile"], "emergency_numbers": emergency_numbers(service),
            "abstain": abstain, "options": options, "why_not": why_not, "what_would_change": change,
            # No listing in reach that names the service is nearer than option 1 (#121: the section then says so
            # instead of reading as a list of nearer alternatives).
            "first_is_nearest": bool(chosen) and all(r[1] >= chosen[0][1] for r in pool + unlikely),
            # The first choice beyond the urgency window (60 min for emergencies) is the answer's first line, with
            # 108/102 and the nearest hospital the public standard expects to offer the care (#86, lead's decision).
            "time_window": {"window_min": window, "first_outside": first_outside},
            "rank_rule": {"code": "nearest_plausible" if nearest_first else "evidence_and_time",
                          "text": RANK_RULE["nearest_plausible" if nearest_first else "evidence_and_time"],
                          # model p (web-check confirm chance) stands in for a "yes" per call; CALL_MIN per call is assumed
                          "expected_in_window": expected_in_window([(o["p"], o["travel"]["minutes"]) for o in options],
                                                                   window) if nearest_first else None},
            "public_option": public if first_outside else None,
            "meta": self._meta(),
            **({"tie_break": tie} if tie else {}),
        }

    def _break_tie(self, service: str, pool: list, scores: dict | None, tiebreak: dict[str, float]) -> tuple:
        """(pool with its tied leading options reordered by tiebreak, {facility_ids, moved, rule} or None).
        Stable: equal values keep the evidence-and-time order. Nothing outside the tied group moves."""
        head = pool[:N_OPTIONS]
        fids = [self._f("id", r[2].fi) for r in head]
        k = tied_prefix([(self._scored(f, service, scores)[1], r[1], r[4]) for f, r in zip(fids, head, strict=True)])
        if len({tiebreak.get(f, 0.0) for f in fids[:k]}) < 2:  # no tie, or the values cannot tell them apart
            return pool, None
        order = sorted(range(k), key=lambda j: -tiebreak.get(fids[j], 0.0))
        return [pool[j] for j in order] + pool[k:], {
            "facility_ids": [fids[j] for j in order], "moved": order != list(range(k)),
            "p_within": TIE_P, "minutes_within": TIE_TRAVEL_MIN}

    # ---------- "Why not the nearest?" (#86) ----------
    def _why_not_clauses(self, service: str, r: tuple, top: tuple) -> list[tuple[str, str, dict]]:
        """Every reason that applies, most decisive first: (code, plain clause, basis). The basis names the payload
        or engine field the clause rests on, so tests can check each sentence against data."""
        label = SERVICES[service]["label_en"]
        _, minutes, pr, _, band, _ = r
        i = pr.fi
        _, p, *_, ev = self.score(self._f("id", i), service)
        window = WINDOW[SERVICES[service]["profile"]]
        top_pr = top[2]
        out: list[tuple[str, str, dict]] = []
        if band == "unlikely":
            text = (f"A second source says it does not offer {label}" if pr.status == "verified_false"
                    else WHY_NOT.get(pr.rule, "Its listing contradicts the claim about {label}").format(label=label))
            out.append(("contradicted", text, {"field": "band", "value": band}))
        if not ev:
            out.append(("no_quote", f"Its listing has no sentence of its own about {label}",
                        {"field": "n_quotes", "value": 0}))
        elif all(any(f["weak"] for f in self.quote_flags(c, i)) for c in ev):
            out.append(("weak_quotes", f"Every sentence we have about {label} carries a data-quality warning",
                        {"field": "n_clean_quotes", "value": 0}))
        if minutes > window >= top[1]:  # the first choice is inside the window and this one is not
            out.append(("outside_window", "It is beyond the time window for this care",
                        {"field": "travel.minutes", "value": minutes, "window_min": window}))
        elif (minutes > top[1] and band == "likely" and top[4] != "likely"
              and SERVICES[service]["profile"] in NEAREST_FIRST):
            # #140 2d: say why a Likely place is not first under the nearest-plausible rule, before anything else
            out.insert(0, ("farther", LIKELY_FARTHER.format(n=minutes - top[1]),
                           {"field": "minutes_vs_first", "value": minutes - top[1]}))
        elif minutes > top[1]:
            out.append(("farther", "It is farther away than the first choice",
                        {"field": "minutes_vs_first", "value": minutes - top[1]}))
        gaps = [m for m in pr.missing if m not in top_pr.missing]
        if gaps:  # a prerequisite the first choice's listing mentions and this one's does not
            need = NEED_PLAIN.get(gaps[0], gaps[0].replace("_or_", " or ").replace("_", " "))
            out.append(("missing", f"Its listing does not mention {need}", {"field": "missing", "value": gaps[0]}))
        if pr.rule in WHY_NOT and band != "unlikely":
            out.append(("evidence_kind", WHY_NOT[pr.rule].format(label=label), {"field": "rule", "value": pr.rule}))
        if self._f("loc_rule", i) in LOC_DOUBT:
            out.append(("location", "Its map point may be wrong, so the travel time is unsure",
                        {"field": "loc_rule", "value": self._f("loc_rule", i)}))
        if self._f("phone_shared", i) >= 3:
            out.append(("shared_phone", "Its phone number is also listed for other places",
                        {"field": "phone_shared", "value": self._f("phone_shared", i)}))
        if top[4] == "likely" and band == "not_verified":
            out.append(("not_confirmed", "It is not rated Likely; the first choice is",
                        {"field": "band", "value": band}))
        top_p = self.score(self._f("id", top_pr.fi), service)[1]
        if not out or (minutes <= top[1] and p < top_p):
            out.append(("weaker", "Its listing evidence is weaker than the first choice's",
                        {"field": "p", "value": round(p, 2)}))
        return out

    def _why_not_reason(self, service: str, r: tuple, top: tuple) -> tuple[str, str, list[dict]]:
        """(code, one plain sentence of at most two clauses, basis per clause)."""
        cl = self._why_not_clauses(service, r, top)[:2]
        # A lead of two sentences takes the next clause as a third sentence, not after a semicolon
        join = (lambda t: f". {t}") if ". " in cl[0][1] else (lambda t: f"; {t[0].lower()}{t[1:]}")
        text = cl[0][1] + "".join(join(c[1]) for c in cl[1:])
        return cl[0][0], text, [{"code": c[0], **c[2]} for c in cl]

    def _why_not(self, service: str, chosen: list, cands: list, options: list) -> tuple[list[dict], dict | None]:
        """The nearest facilities by travel time other than the first choice, each with why it is not first, and
        the one change (a phone call) that would change the answer."""
        if not chosen:
            return [], None
        top = chosen[0]
        rank = {r[2].fi: k + 1 for k, r in enumerate(chosen)}
        near = sorted((r for r in cands if r[2].fi != top[2].fi), key=lambda r: r[1])[:N_WHY_NOT]
        rows = []
        for r in near:
            code, text, basis = self._why_not_reason(service, r, top)
            rows.append({"facility_id": self._f("id", r[2].fi), "name": self._f("name", r[2].fi), "travel": r[3],
                         "option_rank": rank.get(r[2].fi), "minutes_vs_first": r[1] - top[1], "band": r[4],
                         "reason_code": code, "reason": text, "basis": basis})
        # A nearer listing that a "yes" on the phone would move to first place (confirmed pairs score p_confirmed).
        profile = SERVICES[service]["profile"]
        scale = TIME_SCALE[profile]
        def first_if_confirmed(r: tuple) -> bool:
            if profile in NEAREST_FIRST:
                conf = (self.p_confirmed, *r[1:5], self.p_confirmed)
                return nearest_plausible([top, conf], WINDOW[profile])[0] is conf
            return self.p_confirmed * math.exp(-r[1] / scale) > top[0]

        flip = next((r for r in near if r[1] < top[1] and r[4] == "not_verified" and first_if_confirmed(r)), None)
        if flip:
            change = {"kind": "confirm_nearer", "facility_id": self._f("id", flip[2].fi),
                      "name": self._f("name", flip[2].fi), "minutes_vs_first": flip[1] - top[1]}
        elif len(options) > 1:
            nxt = options[1]
            change = {"kind": "first_says_no", "facility_id": nxt["facility_id"], "name": nxt["name"],
                      "first_name": options[0]["name"],
                      "minutes_vs_first": nxt["travel"]["minutes"] - options[0]["travel"]["minutes"]}
        else:
            change = None
        return rows, change

    def _meta(self) -> dict:
        return {"stub": False, "model_hash": f"interim-{self.sha}" if "interim" in self.meta["scores"] else self.sha,
                "data_snapshot": f"{self.meta['source']} {self.meta['as_of']}", "scores": self.meta["scores"],
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                **({"test_record": self.test_record} if self.test_record else {})}

    # ---------- /api/area ----------
    def area(self, service: str, lat: float, lon: float, max_pins: int = 40) -> dict:
        info, label = SERVICES[service], SERVICES[service]["label_en"]
        pins = self.pins
        k = min(range(len(pins["pin"])), key=lambda j: (pins["lat"][j] - lat) ** 2 + (pins["lon"][j] - lon) ** 2)
        district, state = self.pin_where[k]  # the district the nearest PIN point lies in, not the one it is filed under
        # PINs the gazetteer files under no district (facts/build.py fill_districts) are not counted as the district's
        guessed = pins.get("district_from") or [""] * len(pins["pin"])
        all_idx = sorted((j for j in range(len(pins["pin"]))
                          if self.pin_where[j] == (district, state) and not guessed[j]), key=lambda j: pins["pin"][j])
        idx = all_idx[:max_pins]
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
            # Data gap vs care gap (#86): no listing claims it at all, or listings claim it but none is confirmed
            # in the window, or all of them are farther than the window.
            gap = ("covered" if likely else "not_confirmed" if any(r[1] <= window for r in pool)
                   else "far" if pool else "no_claim")
            rows.append({
                "pin": pins["pin"][j], "lat": plat, "lon": plon,
                "first": {"facility_id": self._f("id", first[2].fi), "name": self._f("name", first[2].fi)}
                if first else None,
                "backup": {"facility_id": self._f("id", backup[2].fi), "name": self._f("name", backup[2].fi)}
                if backup else None,
                "travel": {"low": first[3]["low"], "high": first[3]["high"]} if first else None,
                "call_first": self._f("name", first[2].fi) if first else None,
                "nearest_km": None if first else (round(near[3]["km"], 1) if near else None),
                "gap": gap,
                "public": self._public_pin(service, plat, plon) if first is None else None,
            })
        n = len(rows) or 1
        calls = sorted(gains.items(), key=lambda t: (-len(t[1]), self._f("name", t[0])))[:10]
        return {
            "query": {"service": service, "service_label": {"en": label, "hi": info["label_hi"]}},
            "area": {"district": district.title(), "state": state.title(), "window_min": window,
                     "need": self._need(district, state), "gov_list": self._gov_list(service, district, state)},
            "as_of": self.meta["as_of"],
            "summary": {"n_pins": len(rows), "n_without_option": sum(r["first"] is None for r in rows),
                        "access_now": round(n_now / n, 2), "access_if_confirmed": round(n_conf / n, 2),
                        "calls_could_close": round((n_conf - n_now) / n, 2),
                        "no_public_evidence": round(1 - n_conf / n, 2)},
            "caveat": "Low web presence looks like a gap. Verify before deciding.",
            "gap": self._gap(service, district, state, rows, len(all_idx)),
            "pins": rows,
            "ten_calls": [{"rank": r + 1, "facility_id": self._f("id", fi), "name": self._f("name", fi),
                           "phone_kind": self._phone_kind(fi), "areas": len(p), "access_gain": round(len(p) / n, 3)}
                          for r, (fi, p) in enumerate(calls)],
            "headline": self._headline(calls, len(rows), n_now, window),
            "meta": self._meta(),
        }

    def _lgd(self, district: str, state: str) -> str | None:
        return (self.brief or {}).get("key", {}).get(f"{state}|{district}".upper())

    def _need(self, district: str, state: str) -> dict | None:
        """People, listings per million (against India's) and NFHS-5 birth rates for the area's LGD district. The
        NFHS-5 numbers are a district survey estimate, not facility data; None where a value is suppressed."""
        row = (self.brief or {}).get("need", {}).get(self._lgd(district, state) or "")
        if not row:
            return None
        name, people, listings, per_m, nfhs_district, cs, pub, priv, inst = row
        return {"lgd_district": name, "population": people, "listings": listings, "listings_per_million": per_m,
                "india_per_million": self.brief["india_per_million"], "nfhs_district": nfhs_district,
                "csection_pct": cs, "public_csection_pct": pub, "private_csection_pct": priv,
                "institutional_pct": inst, "source": NEED_SOURCE}

    def _gov_list(self, service: str, district: str, state: str) -> list[dict]:
        """Government lists for this care in the area: LaQshya Maternity OT certificates in the district for a
        C-section (valid ones first, latest expiry first), PMNDP's state count for dialysis; [] otherwise."""
        b = self.brief or {}
        if service == "emergency_csection":
            today = datetime.now(UTC).date().isoformat()
            rows = b.get("laqshya", {}).get(self._lgd(district, state) or "", [])
            rows = sorted(rows, key=lambda r: r[3], reverse=True)
            rows = sorted(rows, key=lambda r: r[3] < today)  # stable: valid ones first, each part latest expiry first
            return [{"list": "laqshya", "name": name, "what": f"LaQshya certificate, {dept}", "department": dept,
                     "certified": cert, "valid_to": valid, "expired": valid < today, "status": status,
                     "source": LAQSHYA_SOURCE} for name, dept, cert, valid, status in rows[:N_GOV]]
        key = re.sub(r"^the ", "", state.lower()).replace("&", "and")
        if service == "dialysis" and key in b.get("pmndp", {}):
            centres, working, total, fetched = b["pmndp"][key]
            return [{"list": "pmndp", "name": f"PMNDP, {state.title()}",
                     "what": f"{centres} government dialysis centres working in {working} of {total} districts",
                     "centres": centres, "districts_working": working, "districts_total": total, "fetched": fetched,
                     "valid_to": None, "expired": False, "source": PMNDP_SOURCE}]
        return []

    @staticmethod
    def _headline(calls: list, n: int, now: int, window: int) -> dict:
        """The Area headline from ten_calls[0]: if it confirms, k of n sampled PIN areas (now `now`) have care in the
        window; or why there is no such call: every area is covered already, or nothing is claimed in the window."""
        if calls:
            _, gained = calls[0]
            return {"kind": "if_confirms", "rank": 1, "k": now + len(gained), "n": n, "now": now, "window_min": window}
        return {"kind": "all_covered" if n and now == n else "none_in_window", "n": n, "now": now,
                "window_min": window}

    def _public_pin(self, service: str, lat: float, lon: float) -> dict | None:
        best = self._public_near(service, lat, lon)
        return None if best is None else {"facility_id": self._f("id", best[1]), "name": self._f("name", best[1]),
                                          "km": round(best[0], 1), "label": PUBLIC_LABEL}

    def _gap(self, service: str, district: str, state: str, rows: list[dict], n_total: int) -> dict:
        """Per district: listings in the district that claim the service (and how many are confirmed), and the
        sampled PIN areas split into covered / care gap (not confirmed, or all far) / data gap (no claim)."""
        mine = [p for p in self.pairs[service] if self._f("district", p.fi) == district
                and self._f("state", p.fi) == state]
        bands = [self.score(self._f("id", p.fi), service)[0] for p in mine]
        count = {k: sum(r["gap"] == k for r in rows) for k in ("covered", "not_confirmed", "far", "no_claim")}
        public = sorted((self._f("name", i), self._f("id", i)) for i, svcs in enumerate(self.fac["public_standard"])
                        if service in svcs and not self._unlikely(i, service) and self._f("district", i) == district and self._f("state", i) == state)[:5]
        # A district with almost no listings is first a gap in our data (#86 item 3): say how many there are, and
        # when none is a public-standard hospital, name the nearest one we have (or none within the radius).
        listings = sum(self._f("district", i) == district and self._f("state", i) == state
                       for i in range(len(self.fac["id"])))
        nearest = None
        if not public and rows:
            nearest = self._public_pin(service, sum(r["lat"] for r in rows) / len(rows), sum(r["lon"] for r in rows) / len(rows))
        return {"pins_sampled": len(rows), "pins_in_district": n_total, "radius_km": RADIUS_KM,
                "district_listings": listings, "public_nearest": nearest,
                "district_claiming": sum(b != "unlikely" for b in bands),
                "district_confirmed": sum(b == "likely" for b in bands), **count,
                # named where the district shows a gap: hospitals the public standard expects to offer acute care
                "public_standard": [{"facility_id": f, "name": n, "label": PUBLIC_LABEL} for n, f in public]}

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

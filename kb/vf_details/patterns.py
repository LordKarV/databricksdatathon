"""Deterministic extractors for operational details in one claim sentence.

Each extractor takes a sentence and yields Hit(fact_type, attribute, value_num, value_text, start, end).
start/end index the span that carries the fact; extract.py widens it to a clause and stores that
clause as the quote (always an exact substring of the sentence).

Reused, read-only: total-bed rules from audit/scale/beds_text.py (BED_RX, UNIT_RX, SCOPE_RX, HIST_RX,
_clause) and sentence cues from cleaning/claims/lexicon.py (CUES).
Run `python patterns.py` for the self-check.
"""
from __future__ import annotations

import re
import sys
from typing import Iterator, NamedTuple

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/scale")
import beds_text as BT  # noqa: E402

sys.modules.pop("common", None)  # audit/scale/common must not shadow another step's common module
sys.path.insert(0, "/Users/karthikvattem/projects/datathon/cleaning/claims")
import lexicon as L  # noqa: E402

I = re.I


class Hit(NamedTuple):
    fact_type: str
    attribute: str
    value_num: float | None
    value_text: str | None
    start: int
    end: int


NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "single": 1, "double": 2}
NUM = r"(?<![\w.,/])(\d{1,3}(?:,\d{3})+|\d{1,5}|" + "|".join(sorted(NUMW, key=len, reverse=True)) + r")\b"
APPROX = r"(?:(?:about|around|over|more than|nearly|approximately|approx\.?|upto|up to|at least|a total of|total of)\s+)?"


def num(s: str) -> float:
    s = s.lower().replace(",", "")
    return float(NUMW[s]) if s in NUMW else float(s)


# ---------------------------------------------------------------- 24x7 statements
H24_STRONG = re.compile(r"24\s*[x×*]\s*7|24\s*/\s*7|24\s*-\s*7\b|round[- ]the[- ]clock|around[- ]the[- ]clock|24\s*x\s*365|365\s*days", I)
H24_HOURS = re.compile(r"\b24\s*-?\s*(?:hours?|hrs?)\b|twenty[- ]four[- ]hours?", I)
# "reports within 24 hours", "24-hour Holter monitoring": a duration, not an opening statement
H24_BEFORE_BAD = re.compile(r"\b(within|in|after|before|of|for|upto|up to|than|next|every|last|over|per|about|least|takes?|post|ago|first|under)\s*$", I)
H24_AFTER_BAD = re.compile(r"^\W{0,3}(of|after|before|post|prior|ago|later|period|urine|urinary|holter|ambulatory|abp|abpm|bp\b|blood pressure"
                           r"|monitor\w*|ph\b|eeg|ecg|recording|record|fast\w*|stay|admission|delivery of|turnaround|report)", I)
SCOPES = [  # first listed wins when two keywords sit at the same distance
    ("helpline", r"help ?line|helpdesk|help desk|call ?cent\w*|phone|telephon\w*|tele-?consult\w*|whats ?app|appointment|booking|chat|online|contact"),
    ("ambulance", r"ambulances?"),
    ("blood_bank", r"blood (?:bank|centre|center|storage)"),
    ("pharmacy", r"pharmac\w*|chemist|medical stores?|drug stores?|medicines?"),
    ("dialysis", r"dialysis|ha?emodialysis"),
    ("icu", r"\bn?icus?\b|\bpicu\b|\biccu\b|\bccu\b|intensive care|critical care|\bhdu\b"),
    ("emergency", r"emergenc\w*|casualty|trauma|accident\w*|\bA\s?&\s?E\b|\bER\b"),
    ("doctor_on_duty", r"doctors?|physicians?|medical officers?|\bRMOs?\b|consultants?|specialists?|intensivists?|ana?esthe\w*|pa?ediatrician|gyn\w*cologist|surgeons?|duty"),
    ("nursing", r"nurs\w*"),
    ("lab_imaging", r"lab\w*|diagnos\w*|patholog\w*|radiolog\w*|imaging|x-?rays?|\bCT\b|\bMRI\b|scans?|sonograph\w*|ultrasound|USG|sample collection|blood tests?"),
    ("labour_room", r"labou?r room|deliver\w*|obstetric\w*|matern\w*"),
    ("operation_theatre", r"operation theat\w*|operating theat\w*|\bOTs?\b"),
    ("home_care", r"home (?:care|nursing|visits?|health)|in-home"),
    ("facility", r"\bopen\b|operat\w*|function\w*|services?|care|facility|hospital|clinic|available|availability"),
]
SCOPE_RX = [(k, re.compile(r"\b(?:" + p + ")", I)) for k, p in SCOPES]


def _scope(s: str, a: int, b: int) -> str:
    """Nearest scope keyword to the 24x7 token span [a, b) within its comma clause; 'facility' if none."""
    before = s[max(0, a - 45):a]
    cut = list(re.finditer(r"[,;.:|(]", before))
    before = before[cut[-1].end():] if cut else before
    after = s[b:b + 50]
    m = re.search(r"[,;.|)]|\band\b", after, I)
    after = after[: m.start()] if m else after
    best, best_d = "facility", 10 ** 6
    for k, rx in SCOPE_RX[:-1]:  # 'facility' words ("open", "services") only when no specific scope is in the clause
        for m in rx.finditer(after):
            d = m.start()
            if d < best_d:
                best, best_d = k, d
        for m in rx.finditer(before):
            d = len(before) - m.end() + 1
            if d < best_d:
                best, best_d = k, d
    return best


def hits_24x7(s: str) -> Iterator[Hit]:
    spans = [(m.start(), m.end()) for m in H24_STRONG.finditer(s)]
    for m in H24_HOURS.finditer(s):
        if any(a <= m.start() < b for a, b in spans):
            continue
        if H24_BEFORE_BAD.search(s[max(0, m.start() - 15):m.start()]) or H24_AFTER_BAD.search(s[m.end():m.end() + 25]):
            continue
        spans.append((m.start(), m.end()))
    seen = set()
    for a, b in sorted(spans):
        sc = _scope(s, a, b)
        if sc in seen:
            continue
        seen.add(sc)
        ft = "staffing" if sc == "doctor_on_duty" else "hours_24x7"
        yield Hit(ft, "doctor_24x7" if ft == "staffing" else sc, None, "24x7", a, b)


# ---------------------------------------------------------------- timed schedules (OPD, lab, dialysis)
MER = r"(a\.\s?m\.?|p\.\s?m\.?|am|pm|noon)(?![a-z])"
TIME = r"(\d{1,2})(?:\s?[:.]\s?(\d{2}))?\s*(?:" + MER + r")?(?:\s*hrs\b\.?)?"
RANGE = re.compile(TIME + r"\s*(?:-|–|—|to|till|until|upto|up to)\s*" + TIME, I)
SINGLE = re.compile(r"\b(?:opens?|opening|starts?|from)\s+(?:at\s+)?" + r"(\d{1,2})(?:[:.](\d{2}))?\s*" + MER, I)
DAYN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY = r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)s?\.?"
DAY_RANGE = re.compile(r"\b" + DAY + r"\s*(?:-|–|—|to|through|till|until)\s*" + DAY + r"(?![a-z])", I)
DAY_ONE = re.compile(r"\b" + DAY + r"(?![a-z])", I)
ALL_DAYS = re.compile(r"\ball (?:7 |seven )?days|\bdaily\b|7 days a week|seven days a week|every ?day|all week|365 days|throughout the week", I)
CLOSED = re.compile(r"\b" + DAY + r"\s*[:-]?\s*(?:closed|holiday|off)\b|\bclosed on\s+" + DAY + r"|(?:except|excluding)\s+" + DAY, I)
DATE = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
                  r"|\b\d{1,2}[/-]\d{1,2}[/-](?:19|20)?\d\d\b|\b(?:19|20)\d\d\b", I)
HOURS_WORD = re.compile(r"timing|hours|\bopen|working|\bOPD\b|schedule|session|shift|visiting|consult|clinic|available|daily|weekday", I)
SCHED_SCOPE = [("dialysis", r"dialysis"), ("visiting", r"visiting hours|visitors?|visit timings"),
               ("lab", r"\blab\w*|collection|patholog|blood tests?|diagnostic|radiolog|scan"),
               ("pharmacy", r"pharmac|chemist|medical store"), ("emergency", r"emergenc|casualty"),
               ("doctor_session", r"\bDr\b\.?\s*[A-Z]|\bfor Dr|\bDr\.\s"), ("opd", r"\bOPD\b|out-?patient|consult")]


def _mins(h: str, mm: str | None, mer: str | None, other_mer: str | None, is_start: bool, other_h: int | None) -> tuple[int, bool]:
    """Minutes after midnight and whether the meridiem was guessed."""
    hh, m = int(h), int(mm or 0)
    mer = (mer or "").lower().replace(".", "").replace(" ", "")
    guessed = False
    if mer == "":
        if mm is not None and (hh >= 13 or hh == 0):  # 24-hour clock
            return hh * 60 + m, False
        om = (other_mer or "").lower().replace(".", "").replace(" ", "")
        if om in ("am", "pm"):
            mer, guessed = om, True
            if is_start and other_h is not None and om == "pm" and (hh % 12) > (other_h % 12):
                mer = "am"  # "10 - 2 pm" -> 10 am
        else:
            return -1, True
    if mer == "noon":
        return 12 * 60 + m, False
    if mer == "am":
        return (0 if hh == 12 else hh) * 60 + m, guessed
    return (12 if hh == 12 else hh + 12) * 60 + m, guessed


def _days(seg: str) -> list[str]:
    out: list[str] = []
    if ALL_DAYS.search(seg):
        return DAYN[:]
    used = []
    for m in DAY_RANGE.finditer(seg):
        a, b = DAYN.index(m.group(1)[:3].lower()), DAYN.index(m.group(2)[:3].lower())
        rng = [DAYN[(a + i) % 7] for i in range((b - a) % 7 + 1)]
        out += [d for d in rng if d not in out]
        used.append((m.start(), m.end()))
    for m in DAY_ONE.finditer(seg):
        if not any(a <= m.start() < b for a, b in used):
            d = m.group(1)[:3].lower()
            if d not in out:
                out.append(d)
    return out


def _fmt(t: int) -> str:
    return f"{t // 60:02d}:{t % 60:02d}"


def parse_schedule(s: str) -> dict | None:
    """Deterministic parse of a timed schedule. None when the sentence has no clock range.
    Returns {scope, entries:[{days, open, close}], closed, guessed, problems}."""
    ranges = list(RANGE.finditer(s))
    ranges = [r for r in ranges if r.group(3) or r.group(6) or (r.group(2) and r.group(5))]
    singles = [] if ranges else list(SINGLE.finditer(s))
    if not ranges and not singles:
        return None
    problems: list[str] = []
    if DATE.search(s) and not re.search(r"timing|hours|\bopen|working|\bOPD\b|schedule|daily|weekday", s, I):
        problems.append("dated_event")
    closed = []
    for m in CLOSED.finditer(s):
        d = next(g for g in m.groups() if g)[:3].lower()
        if d not in closed:
            closed.append(d)
    entries, guessed = [], False
    style = None
    prev_end, prev_days = 0, None
    for i, r in enumerate(ranges):
        h1, m1, mer1, h2, m2, mer2 = r.groups()
        if not mer1 and not mer2 and m1 and m2:  # "10:00-17:00": 24-hour clock
            o, c, g1, g2 = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2), False, False
        else:
            o, g1 = _mins(h1, m1, mer1, mer2, True, int(h2))
            c, g2 = _mins(h2, m2, mer2, mer1, False, int(h1))
        guessed |= g1 or g2
        nxt = ranges[i + 1].start() if i + 1 < len(ranges) else len(s)
        before = _days(s[prev_end:r.start()])
        after = _days(s[r.end():min(nxt, r.end() + 45)])
        if style is None:
            style = "before" if before else ("after" if after else None)
        days = (after if style == "after" else before) or prev_days or []
        days = [d for d in days if d not in closed] if days else days
        if o < 0 or c < 0:
            problems.append("no_meridiem")
        elif c <= o and not (o >= 18 * 60 and c <= 10 * 60):
            problems.append("close_before_open")
        elif o < 5 * 60 and (c - o) < 20 * 60:
            problems.append("odd_open_time")
        entries.append({"days": days, "open": _fmt(o) if o >= 0 else None, "close": _fmt(c) if c >= 0 else None})
        prev_end, prev_days = r.end(), days or prev_days
    for r in singles:
        o, g = _mins(r.group(1), r.group(2), r.group(3), None, True, None)
        entries.append({"days": _days(s), "open": _fmt(o) if o >= 0 else None, "close": None})
    if guessed:
        problems.append("meridiem_guessed")
    if re.search(r"\b(sun|mon|tue|wed|thu|fri|sat)", s, I) and not any(e["days"] for e in entries) and not closed:
        problems.append("days_unparsed")
    scope = next((k for k, p in SCHED_SCOPE if re.search(p, s, 0 if k == "doctor_session" else I)), "general")
    span = (min(r.start() for r in ranges + singles), max(r.end() for r in ranges + singles))
    return {"scope": scope, "entries": entries, "closed": closed, "problems": problems, "span": span}


def sched_text(p: dict) -> str:
    parts = []
    for e in p["entries"]:
        d = e["days"]
        ds = "days?" if not d else (f"{d[0]}-{d[-1]}" if len(d) > 2 and d == DAYN[DAYN.index(d[0]):DAYN.index(d[0]) + len(d)] else ",".join(d))
        parts.append(f"{ds} {e['open'] or '?'}-{e['close'] or '?'}")
    if p["closed"]:
        parts.append("closed " + ",".join(p["closed"]))
    return "; ".join(parts)


TIME_ANY = re.compile(r"\d{1,2}(?:[:.]\d{2})?\s*" + MER + r"|\b\d{1,2}[:.]\d{2}\b", I)


def is_hour_candidate(s: str) -> bool:
    """A sentence that mentions clock times with an hours word: the LLM pool when the parse fails."""
    return bool(TIME_ANY.search(s) and HOURS_WORD.search(s))


def hits_schedule(s: str) -> Iterator[Hit]:
    p = parse_schedule(s)
    if p is None or "dated_event" in p["problems"]:
        return
    yield Hit("opd_hours", p["scope"], None, sched_text(p), *p["span"])


SHIFT = re.compile(NUM + r"\s+(?:dialysis\s+)?shifts?\b|\b(multiple|several)\s+shifts\b|\((\d)\s+shifts?\)", I)


def hits_shifts(s: str) -> Iterator[Hit]:
    if not re.search(r"dialy|renal", s, I):
        return
    m = SHIFT.search(s)
    if m:
        v = m.group(1) or m.group(3)
        yield Hit("hours_dialysis_shifts", "dialysis_shifts", num(v) if v else None, m.group(0), m.start(), m.end())


# ---------------------------------------------------------------- beds by unit and total
UNIT = (r"(neonatal (?:intensive care(?: units?)?|ICUs?|care units?)|newborn (?:intensive care|care units?)|\bNICUs?\b|\bSNCUs?\b"
        r"|pa?ediatric (?:ICUs?|intensive care(?: units?)?)|\bPICUs?\b"
        r"|\bICCUs?\b|\bCCUs?\b|\bCICUs?\b|coronary care(?: units?)?|cardiac (?:care|intensive care) units?|cardiac ICUs?"
        r"|\bHDUs?\b|high[- ]dependency(?: units?)?"
        r"|(?:ha?emo)?dialysis(?: units?| centres?| centers?| wards?| facilit\w+)?"
        r"|emergency(?: departments?| rooms?| wards?| units?)?|casualty(?: wards?)?|trauma (?:care|centres?|centers?|units?|wards?|bays?)"
        r"|\b[MS]ICUs?\b|\bCTICUs?\b|\bCTVS ICUs?\b|\bICUs?\b|intensive care(?: units?)?|critical care(?: units?)?|\bITUs?\b)")
UNIT_CLASS = [("nicu", r"neonat|newborn|nicu|sncu"), ("picu", r"pa?ediatric|picu"), ("ccu", r"iccu|\bccu|cicu|coronary|cardiac"),
              ("hdu", r"hdu|high"), ("dialysis", r"dialysis"), ("emergency", r"emergenc|casualty|trauma"), ("icu", r".")]
BED_W = r"(?:beds?|bedded|cots?)"
UB_A = re.compile(APPROX + NUM + r"\+?\s*[- ]?\s*" + BED_W + r"\s+(?:[A-Za-z(][\w/&()-]*\s+){0,3}?" + UNIT, I)
UB_B = re.compile(UNIT + r"(?:\s+[\w/&-]+){0,3}?\s*(?:with|of|having|has|:|\(|-|–)\s*" + APPROX + NUM + r"\+?\s*(?:-\s*)?" + BED_W, I)
UB_C = re.compile(APPROX + NUM + r"\+?\s+" + UNIT + r"\s+" + BED_W, I)


def _unit_class(u: str) -> str:
    return next(k for k, p in UNIT_CLASS if re.search(p, u, I))


def hits_beds(s: str) -> Iterator[Hit]:
    got = []
    for rx, ni, ui in ((UB_C, 1, 2), (UB_A, 1, 2), (UB_B, 2, 1)):
        for m in rx.finditer(s):
            if any(not (m.end() <= a or m.start() >= b) for a, b in got):
                continue
            v = num(m.group(ni))
            got.append((m.start(), m.end()))
            yield Hit("unit_beds", _unit_class(m.group(ui)), v, m.group(ui), m.start(), m.end())
    scoped = bool(BT.SCOPE_RX.search(s) or BT.HIST_RX.search(s))
    for m in BT.BED_RX.finditer(s):
        if any(a <= m.start() < b for a, b in got):
            continue
        if not scoped and not BT.UNIT_RX.search(BT._clause(s, m)):
            yield Hit("unit_beds", "total", float(m.group(1).replace(",", "")), None, m.start(), m.end())


# ---------------------------------------------------------------- equipment counts
EQUIP = [
    ("dialysis_machines", re.compile(APPROX + NUM + r"\+?\s*(?:[A-Za-z][\w-]*\s+){0,2}?(?:ha?emo)?dialysis\s+(machines?|stations?|chairs?)", I), 1),
    ("dialysis_machines", re.compile(r"(?:ha?emo)?dialysis(?:\s+[\w-]+){0,3}?\s*(?:with|of|having|has|:|\()\s*" + APPROX + NUM + r"\+?\s*(?:[A-Za-z][\w-]*\s+)?(machines?|stations?|chairs?)", I), 1),
    ("ventilators", re.compile(APPROX + NUM + r"\+?\s*(?:[A-Za-z][\w-]*\s+){0,2}?ventilators?\b(?![- ]days)", I), 1),
    ("ventilators", re.compile(r"ventilators?\s*(?:[:=]|-\s)\s*" + NUM, I), 1),
    ("cath_labs", re.compile(NUM + r"\s*(?:[A-Za-z][\w-]*\s+){0,2}?cath(?:eteri[sz]ation)?\s*-?\s*labs?\b", I), 1),
    ("operation_theatres", re.compile(NUM + r"\s*(?:[A-Za-z][\w-]*\s+){0,2}?(?:operation theat\w*|operating theat\w*|operating rooms?|OTs\b|OT\b(?! technician))", I), 1),
]
CT_RX = re.compile(r"(\d{1,3})\s*[- ]?\s*slices?\b", I)
MRI_RX = re.compile(r"(\d(?:\.\d)?)\s*[- ]?\s*(?:T|Tesla)\b", I)


def hits_equipment(s: str) -> Iterator[Hit]:
    seen = set()
    for attr, rx, g in EQUIP:
        if attr in seen:
            continue
        m = rx.search(s)
        if m and not re.search(r"\b(class|iso|level|grade|no\.?|number|phase|ward)\s*$", s[max(0, m.start() - 8):m.start()], I):
            seen.add(attr)
            yield Hit("equipment_count", attr, num(m.group(g)), None, m.start(), m.end())
    if re.search(r"\bCT\b|computed tomograph|\bMDCT\b|\bCAT scan", s, I):
        m = CT_RX.search(s)
        if m:
            yield Hit("equipment_count", "ct_slices", float(m.group(1)), None, m.start(), m.end())
    if re.search(r"\bMRI\b|magnetic resonance", s, I):
        m = MRI_RX.search(s)
        if m and not re.match(r"[- ]?\d", s[m.end():m.end() + 2]):
            yield Hit("equipment_count", "mri_tesla", float(m.group(1)), None, m.start(), m.end())


# ---------------------------------------------------------------- staffing counts and statements
STAFF_RX = re.compile(APPROX + NUM + r"(?!\s*(?:-\s*)?(?:hours?|hrs?|x\s*7|/\s*7|×))\+?\s*(?:[A-Za-z][\w-]*\s+){0,2}?(doctors|consultants|specialists|physicians|surgeons|faculty(?: members)?|dentists|\w+ologists|\w+iatrists|\w*paediatricians|\w*pediatricians|ana?esthetists|optometrists|physiotherapists|therapists"
                      r"|nurses|nursing staff|paramedic\w*|staff(?: members)?|employees|medical professionals|healthcare professionals)\b", I)
GENERIC_ADJ = {"highly", "qualified", "experienced", "well", "trained", "skilled", "full", "time", "fulltime", "expert", "dedicated", "eminent", "renowned",
               "senior", "junior", "in", "house", "resident", "permanent", "more", "other", "total", "qualified", "specialist", "expert", "top", "leading"}
TEACHING = re.compile(r"\btrain(ed|s|ing)\b|graduat|alumni|course|seats|students|batch|intake|produced|have passed", I)
DOCTOR_WORD = re.compile(r"doctor|consultant|specialist|surgeon|physician|ana?esthe|intensivist|gyn\w*colog", I)


def hits_staffing(s: str) -> Iterator[Hit]:
    seen = set()
    for m in STAFF_RX.finditer(s):
        w = m.group(2).lower()
        attr = "nurses" if w.startswith("nurs") else ("staff_total" if re.match(r"staff|employ|paramed|medical prof|healthcare prof|\w*therap|optomet", w) else "doctors")
        gap = [x for x in re.split(r"[\s-]+", s[m.end(1):m.start(2)].strip(" +").lower()) if x and x not in GENERIC_ADJ]
        if attr == "doctors" and (gap or w not in ("doctors", "consultants", "specialists", "physicians", "faculty", "faculty members")):
            attr = "specialty_doctors"  # hand check: "7 ENT doctors", "2 dermatologists" are department counts, not the facility's
        if attr in seen or TEACHING.search(s) or re.search(r"\d\s*-\s*$", s[max(0, m.start() - 4):m.start() + 0]) or re.match(r"\d+\s*-\s*\d", s[m.start(1):]):  # LinkedIn headcount bands "11-50 employees"
            continue
        seen.add(attr)
        yield Hit("staffing", attr, num(m.group(1)), w, m.start(), m.end())
    m = L.CUES["parttime"].search(s)
    if m and DOCTOR_WORD.search(s):
        yield Hit("staffing", "visiting_or_on_call", None, m.group(0).lower(), m.start(), m.end())


# ---------------------------------------------------------------- accreditation
ACC = [("NABH", re.compile(r"\bNABH\b|National Accreditation Board for Hospitals", I)),
       ("NABL", re.compile(r"\bNABL\b|National Accreditation Board for Testing", I)),
       ("JCI", re.compile(r"\bJCI\b|Joint Commission International", I)),
       ("NQAS", re.compile(r"\bNQAS\b|National Quality Assurance Standard", I)),
       ("LaQshya", re.compile(r"\bLaQshya\b", I)),
       ("Kayakalp", re.compile(r"\bKayakalp\b", I))]
ACC_STATUS = [
    ("non", re.compile(r"\bnon[- ]?(NABH|NABL|JCI|accredited)|\bnot (yet )?(NABH|NABL|JCI|accredited|certified)", I)),
    ("in_process", re.compile(r"in (the )?process|applied for|applying|under process|pursu|working towards|progress\w* towards|aspir|preparing for|seeking|on the way|is going for|will be", I)),
    ("pre_accreditation", re.compile(r"pre[- ]?accredit", I)),
    ("entry_level", re.compile(r"entry[- ]?level", I)),
    ("accredited", re.compile(r"accredit|certif|approved|recogni[sz]|award|confer|received|attain|achiev|registered|accreditation", I)),
    ("norms_only", re.compile(r"norms|standards|guidelines|complian|as per|protocols|quality", I)),
]


def hits_accreditation(s: str) -> Iterator[Hit]:
    for attr, rx in ACC:
        m = rx.search(s)
        if not m:
            continue
        win = s[max(0, m.start() - 60):m.end() + 60]
        status = next((k for k, r in ACC_STATUS if r.search(win)), "mentioned")
        if attr in ("Kayakalp", "LaQshya", "NQAS") and not re.search(r"award|certif|accredit|score|winner|prize|recogni|assessment|quality", win, I):
            continue  # "Kayakalp" is also an Ayurveda rejuvenation package
        if status == "accredited" and re.search(r"norms|standards|guidelines|complian", win, I) and not re.search(r"accredit|certif", win, I):
            status = "norms_only"
        yield Hit("accreditation", attr, None, status, m.start(), m.end())


# ---------------------------------------------------------------- scheme and insurance empanelment
NOT_NAME = r"(?!\s+(?:super|multi|eye|dental|health ?care|hospital|clinic|nursing|medical|institute|diagnostic|homo?eo))"
SCHEMES = [
    ("rsby", re.compile(r"\bRSBY\b|Rashtriya Swasthya Bima", I)),
    ("pmjay", re.compile(r"\bPM-?\s?JAY\b|\bPMJAY\b|\bAB[- ]?PM-?JAY\b|Ayushman\s+(?:Bharat|card|scheme|yojana|PM|Arogya)|Pradhan Mantri Jan Arogya|\bAB-?ArK\b", I)),
    ("capf", re.compile(r"\bCAPF\b")),
    ("cghs", re.compile(r"\bCGHS\b|Central Government Health Scheme", I)),
    ("echs", re.compile(r"\bECHS\b|Ex-?Servicemen Contributory", I)),
    ("esic", re.compile(r"\bESIC\b|\bESIS\b|\bESI\b(?!\s+(?:hospital|dispensar|medical college|post graduate))|Employees'?\s*State Insurance", I)),
    ("railway", re.compile(r"\bRELHS\b|railway (?:employees?|beneficiar|empanel|panel)", I)),
    ("mjpjay_mh", re.compile(r"\bMJPJAY\b|Jyotiba Phule|Jyotirao Phule|Jeevandayee|Jivandayi|Rajiv Gandhi Jeevandayee", I)),
    ("aarogyasri_ap_ts", re.compile(r"\bA+rogya\s?sri\b" + NOT_NAME + r"|\bArogyasree\b" + NOT_NAME + r"|\bYSR\b|\bNTR Vaidya Seva|\bEHS\b", I)),
    ("cmchis_tn", re.compile(r"\bCMCHIS\b|Chief Minister'?s? Comprehensive Health Insurance", I)),
    ("kasp_kl", re.compile(r"\bKASP\b|Karunya Arogya|\bMEDISEP\b", I)),
    ("swasthya_sathi_wb", re.compile(r"Swasthya Sath[iy]", I)),
    ("bsky_od", re.compile(r"\bBSKY\b|Biju Swasthya", I)),
    ("rajasthan", re.compile(r"Chiranjeevi" + NOT_NAME + r"|\bRGHS\b|\bMAA Yojana|Bhamashah", I)),
    ("gujarat_ma", re.compile(r"\bMAA?\s*(?:Card|Yojana|Vatsalya)|Mukhyamantri Amrutum|\bPMJAY-MA\b", I)),
    ("karnataka", re.compile(r"Arogya Karnataka|Suvarna Arogya|Vajpayee Arogyashree|Yeshasvini|\bAB-?ArK\b", I)),
    ("other_state_scheme", re.compile(r"Atal Amrit|Deen Dayal Swasthya|Chirayu|\bHIMCARE\b|Mukhyamantri (?:Swasthya|Chikitsa|health)|Dr\.? Khubchand|Sehat|\bMSBY\b"
                                      r"|state government (?:health )?(?:insurance )?scheme|state health (?:insurance )?scheme|government (?:health )?schemes?", I)),
]
ESI_CONTEXT = re.compile(r"empanel|panel|cashless|tie[- ]?up|accept|approved|recogni|scheme|beneficiar|card|covered|insured|under|IP\b", I)
INSURERS = (r"Star Health|HDFC ERGO|ICICI Lombard|New India Assurance|Niva Bupa|Max Bupa|Care Health|Religare|Bajaj Allianz|United India Insurance"
            r"|Oriental Insurance|National Insurance|Medi ?Assist|Paramount|Aditya Birla Health|Tata AIG|SBI General|Reliance General|Future Generali"
            r"|Cholamandalam|IFFCO[- ]Tokio|Universal Sompo|Raksha|Vidal|MD India|Heritage Health|\bFHPL\b|Family Health Plan|Good Health|Health India"
            r"|Ericson|Safeway|Vipul|Medsave|Genins|East ?West Assist|Manipal ?Cigna|Liberty General|Kotak General|Royal Sundaram|Acko|Go Digit")
PRIVATE_INS = re.compile(r"\bcashless\b|\bTPAs?\b|\bmediclaim\b|health insurance(?! India)|insurance (?:partners?|companies|providers|accepted|tie[- ]?ups?|empanel\w*|facilit\w*|claims?|desk|help ?desk|coverage|cards?|schemes?)"
                         r"|(?:accepts?|empanel\w*|tie[- ]?ups? with|network)\b[^.;]{0,40}insurance|" + INSURERS, re.I)
PRIVATE_INS_CASE = re.compile(r"\bTPAs?\b")
INS_NEG = re.compile(r"\bnot (?:accepted|empanel\w*|available|covered)|\bno (?:cashless|insurance|TPA)|does not accept", I)


def hits_schemes(s: str, name: str) -> Iterator[Hit]:
    low_name = (name or "").lower()
    for attr, rx in SCHEMES:
        m = rx.search(s)
        if not m or (len(m.group(0)) > 3 and m.group(0).lower() in low_name):
            continue
        if attr == "esic" and not ESI_CONTEXT.search(s[max(0, m.start() - 60):m.end() + 60]):
            continue
        neg = bool(INS_NEG.search(s))
        yield Hit("empanelment", attr, None, "not_accepted" if neg else "empanelled_or_accepted", m.start(), m.end())
    m = PRIVATE_INS.search(s)
    if m and (m.group(0).upper() != "TPA" or PRIVATE_INS_CASE.search(m.group(0))) and not re.search(r"Employees'?\s*State Insurance", s, I):
        yield Hit("empanelment", "private_insurance", None, "not_accepted" if INS_NEG.search(s) else "empanelled_or_accepted", m.start(), m.end())


# ---------------------------------------------------------------- free or government care
FREE = re.compile(r"(?<![-\w])(?:free of (?:cost|charges?)|free(?:ly)?\s+(?:of cost\s+)?(?:\w+\s+){0,2}?(?:treatment|medical|surgery|surgeries|dialysis|consultations?|OPD|medicines?|drugs|care"
                  r"|services?|deliver\w*|diagnos\w*|tests?|check-?ups?|food|meals|beds?|operations?|cataract|eye|health ?care|admission|investigations?|home visits?"
                  r"|ambulance|transport|chemotherapy|vaccin\w*|immuni[sz]ation|counsell?ing|physiotherapy|X-?rays?|scans?|for (?:poor|BPL|all|patients|economically|needy|the poor)))|(?<![-\w])(?:at|is|are|provided|offered|given|done|performed)\s+free\b", I)
FREE_BAD_BEFORE = re.compile(r"\b(pain|blade|scar|stitch|suture|infection|hassle|cash|tension|stress|tobacco|drug|smoke|germ|radiation|needle|injection|knife|metal|gluten|sugar|toll|risk|side[- ]effect|cost|bacteria|dust|glass|spectacle|disease|cancer|chemical|rust)\s*$", I)
GOV_TEXT = re.compile(r"\b(?:is|as) an? (?:[\w-]+ ){0,2}government (?:[\w-]+ ){0,2}(?:hospital|facility|centre|center|dispensary|institution|medical college|health centre)"
                      r"|government[- ](?:run|owned|operated|funded|aided)|(?:run|owned|operated|managed|funded|administered) by (?:the )?(?:[\w-]+ ){0,3}government"
                      r"|under the (?:[\w-]+ ){0,4}(?:government|department of health|directorate of health|health department)", I)


def hits_free(s: str) -> Iterator[Hit]:
    m = FREE.search(s)
    if m and not FREE_BAD_BEFORE.search(s[max(0, m.start() - 20):m.start()]):
        if any(rx.search(s) for _, rx in SCHEMES[:6]) or re.search(r"\bscheme|yojana|card holders?|BPL|beneficiar", s, I):
            attr = "free_under_scheme"
        elif L.CUES["camp"].search(s):
            attr = "free_camp"
        elif re.search(r"\b(plan|package|membership|discount|coupon)s?\b", s, I):
            attr = "free_with_package"  # hand check: "Dental Health Plan includes Free Consultation" is a paid bundle
        elif re.search(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\bon (?:world|national) \w+ day", s, I):
            attr = "free_event"  # one-day offer, not a standing service
        elif re.search(r"ambulance|transport", m.group(0) + s[m.end():m.end() + 20], I):
            attr = "free_ambulance"
        else:
            attr = "free_care"
        yield Hit("free_or_government", attr, None, m.group(0).strip().lower(), m.start(), m.end())
    m = GOV_TEXT.search(s)
    if m:
        yield Hit("free_or_government", "government_run_text", None, None, m.start(), m.end())


# ---------------------------------------------------------------- ambulance and blood centre
AMB = re.compile(r"\bambulances?\b(?!\s+(?:lifts?|bays?|entr\w*|parking|access|ramps?|drivers? (?:jobs?|vacanc)))", I)
AMB_TYPES = [("air", r"air ambulance"), ("als", r"\bALS\b|advanced life support|cardiac ambulance|ICU ambulance|ventilator"), ("bls", r"\bBLS\b|basic life support"),
             ("neonatal", r"neonatal|NICU ambulance|newborn"), ("gov_108_102", r"\b10[28]\b"), ("free", r"free ambulance|ambulance\W+free")]
AMB_COUNT = re.compile(r"(?<![\d/])" + NUM + r"\s*(?:[A-Za-z][\w-]*\s+){0,2}?ambulances?\b", I)


def hits_ambulance(s: str) -> Iterator[Hit]:
    m = AMB.search(s)
    if not m:
        return
    c = AMB_COUNT.search(s)
    types = [k for k, p in AMB_TYPES if re.search(p, s, I)]
    yield Hit("ambulance", "ambulance_service", num(c.group(1)) if c else None, ",".join(types) or None,
              min(m.start(), c.start()) if c else m.start(), max(m.end(), c.end()) if c else m.end())


BLOOD = re.compile(r"\bblood (?:bank|centre|center|storage(?: units?| centres?| centers?| facilit\w+)?|transfusion (?:services?|units?|centres?|centers?|departments?))s?\b|\bBSU\b|\bblood component", I)
BLOOD_OUTSIDE = re.compile(r"tie[- ]?up|linked|nearby|near by|arrangement with|associated with|in collaboration|from (?:the )?[\w ]{0,30}blood bank|donat\w+ (?:to|at)|organi[sz]ed by", I)


def hits_blood(s: str) -> Iterator[Hit]:
    m = BLOOD.search(s)
    if m:
        w = m.group(0).lower()
        attr = "blood_storage_unit" if ("storage" in w or w == "bsu") else "blood_bank"
        yield Hit("blood_centre", attr, None, "outside_or_linked" if BLOOD_OUTSIDE.search(s) else "on_site_claim", m.start(), m.end())


def all_hits(s: str, name: str = "") -> list[Hit]:
    out: list[Hit] = []
    for f in (hits_24x7, hits_schedule, hits_shifts, hits_beds, hits_equipment, hits_staffing, hits_accreditation, hits_free, hits_ambulance, hits_blood):
        out += list(f(s))
    out += list(hits_schemes(s, name))
    return out


def clause_quote(s: str, a: int, b: int, cap: int = 220) -> str:
    """Exact substring of s: the [;|.]-delimited segment around [a, b), or a word-snapped window when that is long."""
    stop = r"(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bSt\.)(?<!\bNo\.)(?<=[.!?])"  # "Dr. Gour" is not a sentence end
    left = max([m.end() for m in re.finditer(r"[;|•]\s*|" + stop + r"\s+", s[:a])] or [0])
    m = re.search(r"\s*[;|•]|" + stop + r"\s", s[b:])
    right = b + m.start() if m else len(s)
    if right - left > cap:
        lo = max(left, a - 80)
        hi = min(right, b + 80)
        while lo > left and s[lo - 1] not in " ,(":
            lo -= 1
        while hi < right and s[hi:hi + 1] not in (" ", ",", ")", ""):
            hi += 1
        left, right = lo, hi
    q = s[left:right].strip()
    return q


if __name__ == "__main__":
    k = lambda s: [(h.fact_type, h.attribute, h.value_num, h.value_text) for h in all_hits(s)]
    assert ("hours_24x7", "ambulance", None, "24x7") in k("Provides 24/7 ambulance service")
    assert {h[1] for h in k("Provides 24/7 emergency care and has 24/7 ambulance services")} >= {"emergency", "ambulance"}
    assert ("hours_24x7", "blood_bank", None, "24x7") in k("Blood bank facility operating 24x7")
    assert not [h for h in k("Most reports delivered within 24 hours") if h[0] == "hours_24x7"]
    assert not [h for h in k("Performs 24-hour Holter monitoring") if h[0] == "hours_24x7"]
    assert ("hours_24x7", "pharmacy", None, "24x7") in k("24 Hours Pharmacy")
    assert ("staffing", "doctor_24x7", None, "24x7") in k("Doctors available 24 hours")
    assert ("hours_24x7", "helpline", None, "24x7") in k("24x7 patient care call center")
    p = parse_schedule("Opening hours: Monday–Saturday 10:00 am–8:30 pm; Sunday 10:00 am–1:30 pm.")
    assert sched_text(p) == "mon-sat 10:00-20:30; sun 10:00-13:30", sched_text(p)
    p = parse_schedule("Lab test timings: 8:00 AM–8:00 PM (Mon–Sat) and 8:00 AM–4:00 PM (Sunday)")
    assert sched_text(p) == "mon-sat 08:00-20:00; sun 08:00-16:00" and p["scope"] == "lab", sched_text(p)
    p = parse_schedule("Timings: Mon to Tue, Thu to Sat: 10:00am-1:30pm, 6:00pm-8:30pm.")
    assert sched_text(p) == "mon,tue,thu,fri,sat 10:00-13:30; mon,tue,thu,fri,sat 18:00-20:30", sched_text(p)
    p = parse_schedule("Open Monday to Saturday from 8 a.m. to 8 p.m.; Sunday closed")
    assert sched_text(p) == "mon-sat 08:00-20:00; closed sun", sched_text(p)
    p = parse_schedule("Clinic operates with Monday-Saturday sessions: 02:00 AM-04:00 PM, 04:00 PM-06:00 PM; Sunday closed.")
    assert "odd_open_time" in p["problems"]
    assert parse_schedule("Has 1 ambulance on site") is None
    assert "dated_event" in parse_schedule("Free PSA test offered on 28 June 2023 from 10:00 AM to 2:00 PM")["problems"]
    p = parse_schedule("OPD 10 - 2 pm daily")
    assert sched_text(p) == "mon-sun 10:00-14:00" and "meridiem_guessed" in p["problems"], sched_text(p)
    assert ("hours_dialysis_shifts", "dialysis_shifts", 3.0, "three shifts") in k("Eighteen haemodialysis machines operated in three shifts daily")
    assert ("equipment_count", "dialysis_machines", 18.0, None) in k("Eighteen haemodialysis machines operated in three shifts daily")
    assert ("equipment_count", "dialysis_machines", 48.0, None) in k("Renal Dialysis Unit with 48 machines")
    assert ("unit_beds", "icu", 75.0, "ICU") in k("Has 300 beds, including 75 ICU beds")
    assert ("unit_beds", "total", 300.0, None) in k("Has 300 beds, including 75 ICU beds")
    assert ("unit_beds", "ccu", 14.0, "ICCU") in k("ICCU with 14 beds")
    assert ("unit_beds", "icu", 8.0, "Intensive Care Unit") in k("24 hrs emergency, Trauma, 8 Bedded well equipped Intensive Care Unit")
    assert ("unit_beds", "dialysis", 6.0, "Dialysis Centre") in k("Dedicated Advanced Dialysis Centre (6 bedded)")
    assert ("unit_beds", "nicu", 6.0, "NICU") in k("6-bedded Level III NICU with Ventilator care")
    assert ("unit_beds", "emergency", 45.0, "emergency") in k("Emergency & Trauma Care with 45-bed emergency & trauma care area")
    assert ("equipment_count", "ventilators", 13.0, None) in k("Ventilators: 13")
    assert not [h for h in k("Baseline VAP rate of 34.81 per 1000 ventilator-days") if h[1] == "ventilators"]
    assert ("equipment_count", "ct_slices", 128.0, None) in k("128-slice CT scanner")
    assert ("equipment_count", "dialysis_machines", 10.0, None) in k("Dialysis centre started in 2018 with 10 dialysis machines")
    assert ("equipment_count", "mri_tesla", 1.5, None) in k("1.5T MRI scanner")
    assert ("staffing", "doctors", 40.0, "doctors") in k("Has 40 doctors available")
    assert ("staffing", "specialty_doctors", 40.0, "dentists") in k("Has over 40 dentists on staff")
    assert ("staffing", "specialty_doctors", 7.0, "doctors") in k("Has 7 ENT doctors")
    assert ("staffing", "doctors", 9.0, "doctors") in k("Has a staff of 9 highly qualified doctors.")
    assert not [h for h in k("24 Hours gynaecologist doctors available") if h.__getitem__(2) == 24.0]
    assert ("free_or_government", "free_with_package") in [h[:2] for h in k("Basic Dental Health Plan includes Free Consultation and X-ray")]
    assert not [h for h in k("Headcount: 11-50 employees") if h[0] == "staffing"]
    assert not [h for h in k("Class 100 Modular Liver Operating Theater") if h[1] == "operation_theatres"]
    assert parse_schedule("Open 24 Hrs") is None
    assert sched_text(parse_schedule("Dr X available Mon-Sat 10:00–13:00 and 17:00–21:00; Sun 10:00–13:00")) == "mon-sat 10:00-13:00; mon-sat 17:00-21:00; sun 10:00-13:00"
    assert sched_text(parse_schedule("Timings 10:00 hrs to 17:00 hrs")) == "days? 10:00-17:00"
    assert not [h for h in k("Provides following treatment packages: Kayakalp; Beauty Care Programme") if h[0] == "accreditation"]
    assert ("free_or_government", "free_event") in [h[:2] for h in k("Free PSA test offered on 28 June 2023 from 10:00 AM to 2:00 PM")]
    assert not [h for h in k("Has trained 500 doctors") if h[0] == "staffing"]
    assert ("accreditation", "NABH", None, "accredited") in k("Rungta Hospital is NABH accredited")
    assert ("accreditation", "NABH", None, "non") in k("NON-NABH")
    assert ("accreditation", "NABL", None, "in_process") in k("In process for NABL accreditation")
    assert ("accreditation", "NABH", None, "norms_only") in k("Modular operating theatre compliant with NABH norms")
    assert ("accreditation", "NABH", None, "entry_level") in k("NABH Certified Hospital (Entry Level)")
    assert ("empanelment", "pmjay", None, "empanelled_or_accepted") in k("Ayushman Bharat (PM-JAY) accepted")
    assert not [h for h in all_hits("Ayushman Hospital is in Delhi", "Ayushman Hospital") if h[1] == "pmjay"]
    assert not [h for h in k("Dr X worked at ESI Hospital Noida") if h[1] == "esic"]
    assert ("empanelment", "esic", None, "empanelled_or_accepted") in k("ESI empanelled hospital under Employees State Insurance, Haryana")
    assert not [h for h in k("Outpatient dental clinic") if h[1] == "private_insurance"]
    assert ("empanelment", "private_insurance", None, "empanelled_or_accepted") in k("Star Health Insurance cashless network hospital in Bhopal")
    assert ("empanelment", "mjpjay_mh", None, "empanelled_or_accepted") in k("Empanelled under MJPJAY")
    assert ("free_or_government", "free_under_scheme") in [h[:2] for h in k("Provides free treatment under Ayushman Bharat scheme")]
    assert ("free_or_government", "free_ambulance") in [h[:2] for h in k("Free ambulance service")]
    assert not [h for h in k("Performs refractive surgeries, including blade-free LASIK") if h[0] == "free_or_government"]
    assert not [h for h in k("Infection free operation theatres") if h[0] == "free_or_government"]
    assert ("ambulance", "ambulance_service", 1.0, None) in k("Has 1 ambulance on site")
    assert ("ambulance", "ambulance_service", None, "air,als") in k("Provides Air Ambulance with Portable Ventilator")
    assert not [h for h in k("Ambulance lifts for trauma patient transfer") if h[0] == "ambulance"]
    assert ("blood_centre", "blood_storage_unit", None, "on_site_claim") in k("Has a 24-hour on-site blood storage unit")
    assert ("blood_centre", "blood_bank", None, "outside_or_linked") in k("Tie-up with nearby blood bank")
    s = "Has 40-bed capacity with 8 ICU beds, 21 general ward beds; NABH accredited"
    h = [x for x in all_hits(s) if x.attribute == "icu"][0]
    q = clause_quote(s, h.start, h.end)
    assert q == "Has 40-bed capacity with 8 ICU beds, 21 general ward beds" and q in s, q
    s = "OP timings for Dr. Rajneesh Gour are Monday 05:30 pm to 07:00 pm"
    assert clause_quote(s, 40, 60) == s
    print("patterns self-check ok")

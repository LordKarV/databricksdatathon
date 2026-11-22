"""Facility-type fit (#117 B): a facility whose type cannot offer a service is never an option for it.

Shared by the planner (planner/export_v2.py) and the app lists (app/facts/build.py, app/packs/build_packs.py). It
reads the facility's type field and name only, never derived/v2 p or bands: an option is left out, not rescored.

facility_kinds(name, type_id) is decided in two steps:
1. the type field: facilityTypeId "dentist" is dental;
2. a strict name pattern: the name carries a specialty word (eye, dental, Ayurvedic, IVF, ...), names no
   institution before it (hospital, clinic, centre, nursing, medical ...) and carries no general marker anywhere
   (multi-speciality, trauma, maternity, women, heart, nursing home ...). Qualifiers touching the specialty word
   ("Multispeciality Dental", "ENT Superspeciality", "Homoeo Medical College") do not count. So "Sharma Dental
   Clinic", "Aravind Eye Hospital" and "Government Ayurvedic College and Hospital" are specialty places, while
   "City Hospital and Dental Care", "Mata Chandrakala Hospital Trauma & Dental Center", "Umang IVF and Super
   Speciality Hospital" and "District Hospital AYUSH Wing" are general and keep every service.
fits(kinds, service) then says whether a facility of those kinds can offer the service. The scope follows the
model's own scope rule (model/v2/assemble/evidence.py FOCUS_OK): dental, eye, AYUSH, skin, physiotherapy, ENT,
psychiatric and veterinary places offer none of the acute services the app and the planner serve; an IVF or
fertility centre only obstetric and newborn care; a diagnostic centre only imaging, ECG and laboratory; a children's
hospital everything except the adult heart-attack stages (thrombolysis, cath lab). A name with two kinds
("Child Care and Dental Hospital") may offer what either kind may.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping

from common.names import display_name

# Specialty words per kind, longer spellings first; each starts at a word boundary and runs to the end of its word.
# ENT stays case-sensitive so "ent" never matches. "Ayush" and "Nayan" alone are personal names ("Ayush Hospital"),
# so AYUSH places are found by their system (Ayurvedic, Homoeopathic, Unani ...) and eye places by other words.
SPECIALTY: dict[str, str] = {
    "dental": r"dental|dentists?|dentistry|\bdent\b|orthodont|root canal|teeth|tooth",
    "eye": r"eyes?\b|netralaya|nethralaya|netra|nethra|ophthalm|lasik|retina",
    "ayush": r"ayurved|homoeo|homeo|unani\b|siddha\b|naturopath|yoga\b|panchakarma",
    "ivf": r"ivf\b|infertility|fertility|test ?tube",
    "skin": r"skin\b|dermat|cosmetolog|hair\b",
    "physio": r"physiother|physio\b|chiropract",
    "ent": r"(?-i:E\.?N\.?T\b\.?)",
    "psychiatric": r"psychiatr|mental health|de-?addiction|nasha mukti",
    "veterinary": r"veterinary|vet\b|animal\b",
    "diagnostic": r"diagnostics?|imaging|scans?\b|path ?labs?|patholog|laborator(?:y|ies)",
    "child": r"children'?s?|childs?\b|child\b|kids\b|p(?:a)?ediatric|shishu",
}
# Words that qualify the specialty word they touch ("Multispeciality Dental Clinic", "ENT Superspeciality Centre",
# "Homoeo Medical College"): removed before the checks below, so they never make a specialty place general.
QUALIFIER = (r"the|super ?-? ?specialit?y|multi ?-? ?specialit?y|super ?-? ?specialty|multi ?-? ?specialty|speciality"
             r"|specialty|specialised|specialized|cosmetic|aesthetic|laser|family|advanced?|modern|smile|care|medical")
# An institution named before the first specialty word is a general one: "City Hospital and Dental Care". Not when
# it is "for" or "of" the specialty: "Centre for Sight", "College of Dental Sciences".
HEAD = re.compile(r"\b(?:hospitals?|clinics?|polyclinic|cent(?:re|er)s?|care|nursing|medical|medicare|health ?care"
                  r"|surgical)\b(?!\s+(?:for|of)\b)", re.I)
# A general marker anywhere: "Umang IVF and Super Speciality Hospital", "Shree Netralaya and Maternity Clinic".
GENERAL = re.compile(r"\bmulti|super ?-? ?spec|general|trauma|maternity|mother|wom[ae]n|cradle|heart|cardi|neuro|spine"
                     r"|ortho(?!dont)|nursing home|medical|medicare|emergency|\bicu\b|dialysis", re.I)
_WORDS = "|".join(rf"\b(?:{w})\w*" for w in SPECIALTY.values())
_FIRST = re.compile(_WORDS, re.I)
_KIND = {k: re.compile(rf"\b(?:{v})", re.I) for k, v in SPECIALTY.items()}
# Next to another specialty, a child word is a children's place of its own only when it names one ("Child Care and
# Dental Hospital", "Children and Dental Hospital"); "Pediatric Dental Clinic" and "Dental Clinic for Kids" are dental.
_CHILD_PLACE = re.compile(rf"\b(?:{SPECIALTY['child']})\w*(?:\s+(?:and|&)\s+\w+)?\s+"
                          r"(?:care|hospitals?|clinics?|health|cent(?:re|er))\b", re.I)
TYPE_KIND = {"dentist": "dental"}

# Service ids in every vocabulary that reads this rule: the app's, derived/v2 taxonomy and planner capabilities.
HEART_ATTACK = frozenset({"stemi_thrombolysis", "cath_lab_angioplasty", "thrombolysis", "pci_cath_lab"})
OBSTETRIC_NEWBORN = frozenset({"emergency_csection", "csection", "comprehensive_emoc", "basic_emoc", "nicu", "sncu",
                               "neonatal_stabilisation"})
DIAGNOSTIC_OK = frozenset({"mri", "ct_scan", "ecg", "laboratory"})
NONE: frozenset[str] = frozenset()
# kind -> the services it can offer (a frozenset), or the services it cannot ("cannot", for children's hospitals)
CAN_OFFER: dict[str, frozenset[str]] = {
    **{k: NONE for k in ("dental", "eye", "ayush", "skin", "physio", "ent", "psychiatric", "veterinary")},
    "ivf": OBSTETRIC_NEWBORN, "diagnostic": DIAGNOSTIC_OK,
}
CANNOT: dict[str, frozenset[str]] = {"child": HEART_ATTACK}
SPECIALTY_ONLY = frozenset(k for k, v in CAN_OFFER.items() if v == NONE)


def _strip_qualifiers(n: str) -> str:
    """The name without qualifiers that touch a specialty word, before or after it."""
    out, pos = [], 0
    for m in _FIRST.finditer(n):
        lead = re.search(rf"(?:\b(?:{QUALIFIER})\b[\s-]*)+$", n[pos:m.start()], re.I)
        out.append(n[pos:m.start()][: lead.start()] if lead else n[pos:m.start()])
        out.append(m.group())
        tail = re.match(rf"(?:[\s-]+(?:{QUALIFIER})\b)+", n[m.end():], re.I)
        pos = m.end() + (tail.end() if tail else 0)
    return "".join(out) + n[pos:]


def name_kinds(name: str | None) -> frozenset[str]:
    """The specialty kinds a name declares when nothing else in it makes it a general facility; else empty."""
    raw = display_name(name) if isinstance(name, str) else ""
    n = _strip_qualifiers(raw)
    first = _FIRST.search(n)
    if not first or HEAD.search(n[: first.start()]) or GENERAL.search(n):
        return NONE
    kinds = {k for k, rx in _KIND.items() if rx.search(n)}
    if "child" in kinds and len(kinds) > 1 and not _CHILD_PLACE.search(raw):
        kinds.discard("child")
    return frozenset(kinds)


def facility_kinds(name: str | None, type_id: str | None) -> frozenset[str]:
    """Type field first, then the strict name pattern; empty for a facility of no restricting kind."""
    t = TYPE_KIND.get(type_id) if isinstance(type_id, str) else None
    return frozenset({t}) if t else name_kinds(name)


def fits(kinds: Iterable[str], service: str) -> bool:
    """Whether a facility of these kinds can offer the service (any id vocabulary: app, derived/v2, planner)."""
    kinds = list(kinds)
    return not kinds or any(service in CAN_OFFER[k] if k in CAN_OFFER else service not in CANNOT.get(k, NONE)
                            for k in kinds)


def specialty_only(kinds: Iterable[str]) -> bool:
    """A facility that can offer none of the acute services (dental, eye, AYUSH, ...): every kind it has is one."""
    kinds = set(kinds)
    return bool(kinds) and kinds <= SPECIALTY_ONLY


def kinds_by_id(ids: Iterable[str], names: Iterable[str | None], types: Iterable[str | None]) -> dict[str, frozenset]:
    """{facility id: kinds} for the facilities that have a restricting kind (others are absent)."""
    out = {u: facility_kinds(n, t) for u, n, t in zip(ids, names, types, strict=True)}
    return {u: k for u, k in out.items() if k}


def fit_mask(ids: Iterable[str], services: Iterable[str],
             kinds_of: Mapping[str, frozenset]) -> tuple[list[bool], dict[str, int]]:
    """Per (facility id, service) pair, whether its type can offer the service; with the pairs left out per service."""
    services = list(services)
    mask = [fits(kinds_of.get(u, NONE), s) for u, s in zip(ids, services, strict=True)]
    out = Counter(s for s, ok in zip(services, mask, strict=True) if not ok)
    return mask, dict(sorted(out.items()))

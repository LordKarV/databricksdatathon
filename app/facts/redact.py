"""Never show a person's name (#86): a doctor named in a quoted sentence becomes "a doctor".

The claim id stays next to the quote, so the full sentence can still be looked up in derived/v1. Institution names
that start with a title ("Dr. Ram Manohar Lohia Hospital", "Dr. B.R. Ambedkar Nagar") are places, not people, and
are kept. The same function runs on the server (plan, route, website check, offline packs) and in the faithfulness
test, so a shown quote is checked against the redacted claim text.
"""
from __future__ import annotations

import re

# A title, then a run of initials and capitalised words ("Satish V. Kamat", "B. Niranjan Naik", "N N Asokan").
_NAME = re.compile(
    r"\b(?:Dr|DR|Prof|PROF)\b\.?\s*"
    r"(?:[A-Z]\.\s*|[A-Z]\s+(?=[A-Z])|[A-Z][A-Za-z\u2019'-]+\s+(?=[A-Z]))*"
    r"[A-Z][A-Za-z\u2019'-]*"
)
_INSTITUTION = re.compile(
    r"\b(?:Hospitals?|Institute|Medical|College|Memorial|Clinic|Nursing|Centre|Center|Trust|Foundation|Road|Marg|"
    r"Nagar|Chowk|Health|Cardiac|Eye|Heart|Cancer|Dental|Multispeciality|Superspeciality|Charitable|University|"
    r"Mission|Colony|Bhawan|Bhavan|Complex|Kendra|Sansthan|Sadan|Sciences|Polyclinic|Diagnostics?|Care|Labs?|"
    r"PathLabs|Laborator(?:y|ies)|Pharmacy)\b")
_NEXT_WORD = re.compile(r"\s*([A-Za-z]+)")


def _replace(m: re.Match[str]) -> str:
    name = m.group(0)
    nxt = _NEXT_WORD.match(m.string, m.end())
    if _INSTITUTION.search(name) or (nxt and _INSTITUTION.fullmatch(nxt.group(1))):
        return name  # an institution or a place named after someone, not a person on staff
    if re.search(r"[\u2019']s$", name):
        return "a doctor's"
    return "a doctor"


def redact_names(text: str) -> str:
    """The sentence with every doctor's name replaced by "a doctor" (capitalised at the start of the sentence)."""
    if not text or not _NAME.search(text):
        return text
    out = _NAME.sub(_replace, text)
    return out[0].upper() + out[1:] if out.startswith("a doctor") else out

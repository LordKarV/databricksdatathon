"""Pre-recording check for the demo (#86 decision 2): run every app service at the demo places, with routes.

    .venv-app/bin/python validation/demo_qa.py      # from the repo root, after app/facts/build.py

Prints counts and examples for: unredacted doctor names in shown quotes, citations flagged as a page about another
place, options and route stops whose facility type cannot offer the service (common/typefit.py, #117: eye, dental,
AYUSH, IVF ...), first options outside the time window, and raw internal keys in printed fields (a claim id, a
derived/ path, a snake_case or capability key, "Pawar'S"; #121). Names with a specialty word that the rule keeps as a
general facility ("City Hospital and Dental Care") are listed apart, for a human to read.
Also (#118): a shown option's first quote, the one its card shows, is never flagged as a page about another place.
Exit code 1 when a doctor name, an other-place citation, an other-place first quote, a raw key or a type that cannot
offer the service is shown; the rest are for a human to read.
"""
import collections
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]
import itinerary  # noqa: E402
from facts.engine import Engine  # noqa: E402
from facts.redact import redact_names  # noqa: E402
from services import SERVICES  # noqa: E402

from common.typefit import facility_kinds, fits, specialty_only  # noqa: E402

e = Engine.load()
PTS = {"Sitamarhi": (26.5951, 85.4808), "Mohania": (25.15, 83.68), "Pusa": (25.6, 85.95), "Patna": (25.61, 85.14),
       "Gaya": (24.78, 85.0), "Bahraich": (27.57, 81.6), "Banda": (25.48, 80.33), "Darbhanga": (26.15, 85.9)}
NAMED = re.compile(r"\b(?:Dr|DR|Prof)\b\.?\s*[A-Z][a-z]+\s+[A-Z][a-z]+")
MISMATCH = re.compile(r"\b(eye|netra|netralaya|dental|dentist|skin|derma|ayurved|homoeo|homeo|physio|vet|veterinary"
                      r"|ivf|fertility)\b", re.I)
_at = pd.read_parquet(ROOT / "derived" / "v2" / "facility_attributes.parquet", columns=["unique_id", "facilityTypeId"])
_loc = pd.read_parquet(ROOT / "derived" / "v1" / "facility_location.parquet", columns=["unique_id", "name"])
_f = _loc.merge(_at, on="unique_id", how="left")
KINDS = {u: facility_kinds(n, t) for u, n, t in zip(_f.unique_id, _f.name, _f.facilityTypeId, strict=True)}


def check_name(kind: str, row: tuple, fid: str | None, name: str, service: str | None) -> None:
    """A shown facility whose type cannot offer the service is a mismatch; a specialty word the rule keeps is listed.
    A route stop names no single service (the planner checks each stage's capability), so it is a mismatch only
    when its type offers none of them."""
    kinds = KINDS.get(fid or "", frozenset())
    if fid and (not fits(kinds, service) if service else specialty_only(kinds)):
        issues[f"mismatched specialty {kind}"].append(row)
    elif MISMATCH.search(name):
        issues[f"specialty word, kept as a general facility ({kind})"].append(row)


# #121: what a family must never read. Claim ids stay in the page as hidden marks (app.js claimHtml), not in these fields.
RAW_KEY = re.compile(r"\b[0-9a-f]{8}:[a-z]+:\d+\b|derived/|\b[a-z0-9]+(?:_[a-z0-9]+)+\b|[a-z]['\u2019]S\b")
RAW_CAPS = {k.replace("_", " ") for k, w in itinerary.CAPABILITY_WORDS.items() if k.replace("_", " ") != w}


def raw_keys(place, s, where, texts):
    for t in texts:
        if isinstance(t, str) and (RAW_KEY.search(t) or t in RAW_CAPS):
            issues["raw key on screen"].append((place, s, where, t[:80]))


issues = collections.defaultdict(list)
n_first = 0  # shown options with at least one quote: the first-quote check's denominator
for place, (la, lo) in PTS.items():
    for s in SERVICES:
        p = itinerary.attach(e.plan(s, la, lo, 40, "gps"), e)
        for k, o in enumerate(p["options"]):
            raw_keys(place, s, f"option {k + 1}", [o["name"], *(c["label"] for c in o["contributions"])])
            if o["evidence"]:
                n_first += 1
                first = o["evidence"][0]
                if any(f["code"] == "src_other_place" for f in first.get("flags", [])):
                    issues["first quote flagged other-place"].append((place, s, k + 1, o["name"], first["claim_id"]))
            check_name("option", (place, s, k + 1, o["name"], o["band"]), o["facility_id"], o["name"], s)
            for ev in o["evidence"]:
                if NAMED.search(ev["quote"]) and redact_names(e.claims[ev["claim_id"]][1]) != ev["quote"]:
                    issues["unredacted name"].append((place, s, o["name"], ev["claim_id"]))
                for f in ev.get("flags", []):
                    if f["code"] == "src_other_place":
                        row = (place, s, k + 1, o["name"], f.get("place"), f.get("km"))
                        issues["other-place source (flagged)"].append(row)
        it = p.get("itinerary") or {}
        for r in it.get("plans", []):
            for st in r["stops"]:
                raw_keys(place, s, f"route {r['rank']}", [st.get("name"), st.get("weakest_capability"),
                                                          st.get("purpose_word")])
                check_name("route stop", (place, s, r["rank"], st.get("name", "")), st.get("facility_id"),
                           st.get("name", ""), None)
                for ev in st.get("evidence", []):
                    raw = e.claims.get(ev["claim_id"], ["", ""])[1]
                    if NAMED.search(ev["quote"]) and redact_names(raw) != ev["quote"]:
                        issues["unredacted name in route"].append((place, s, st["name"]))
        tw = p.get("time_window") or {}
        if tw.get("first_outside"):
            first = p["options"][0]["travel"]["minutes"]
            row = (place, s, first, tw["window_min"], bool(p.get("public_option")))
            issues["first option outside window"].append(row)
for k in ("unredacted name", "unredacted name in route", "other-place source (flagged)",
          "first quote flagged other-place", "raw key on screen", "mismatched specialty option",
          "mismatched specialty route stop", "specialty word, kept as a general facility (option)",
          "specialty word, kept as a general facility (route stop)", "first option outside window"):
    of = f" of {n_first} shown options with a quote" if k == "first quote flagged other-place" else ""
    print(f"== {k}: {len(issues[k])}{of}")
    for x in issues[k][:12]:
        print("  ", x)
sys.exit(1 if issues["unredacted name"] or issues["unredacted name in route"]
         or issues["other-place source (flagged)"] or issues["first quote flagged other-place"]
         or issues["raw key on screen"] or issues["mismatched specialty option"]
         or issues["mismatched specialty route stop"] else 0)

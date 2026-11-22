"""Pre-recording check for the demo (#86 decision 2): run every app service at the demo places, with routes.

    .venv-app/bin/python validation/demo_qa.py      # from the repo root, after app/facts/build.py

Prints counts and examples for: unredacted doctor names in shown quotes, citations flagged as a page about another
place, option names of an unrelated specialty (eye, dental, IVF ...), and first options outside the time window.
Also (#118): a shown option's first quote, the one its card shows, is never flagged as a page about another place.
Exit code 1 when a doctor name, an other-place citation or an other-place first quote is shown; the rest are for a
human to read.
"""
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import itinerary  # noqa: E402
from facts.engine import Engine  # noqa: E402
from facts.redact import redact_names  # noqa: E402
from services import SERVICES  # noqa: E402

e = Engine.load()
PTS = {"Sitamarhi": (26.5951, 85.4808), "Mohania": (25.15, 83.68), "Pusa": (25.6, 85.95), "Patna": (25.61, 85.14),
       "Gaya": (24.78, 85.0), "Bahraich": (27.57, 81.6), "Banda": (25.48, 80.33), "Darbhanga": (26.15, 85.9)}
NAMED = re.compile(r"\b(?:Dr|DR|Prof)\b\.?\s*[A-Z][a-z]+\s+[A-Z][a-z]+")
MISMATCH = re.compile(r"\b(eye|netra|netralaya|dental|dentist|skin|derma|ayurved|homoeo|homeo|physio|vet|veterinary"
                      r"|ivf|fertility)\b", re.I)
issues = collections.defaultdict(list)
n_first = 0  # shown options with at least one quote: the first-quote check's denominator
for place, (la, lo) in PTS.items():
    for s in SERVICES:
        p = itinerary.attach(e.plan(s, la, lo, 40, "gps"), e)
        for k, o in enumerate(p["options"]):
            if o["evidence"]:
                n_first += 1
                first = o["evidence"][0]
                if any(f["code"] == "src_other_place" for f in first.get("flags", [])):
                    issues["first quote flagged other-place"].append((place, s, k + 1, o["name"], first["claim_id"]))
            if MISMATCH.search(o["name"]):
                issues["mismatched specialty option"].append((place, s, k + 1, o["name"], o["band"]))
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
                if MISMATCH.search(st.get("name", "")):
                    issues["mismatched specialty route stop"].append((place, s, r["rank"], st["name"]))
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
          "first quote flagged other-place", "mismatched specialty option", "mismatched specialty route stop",
          "first option outside window"):
    of = f" of {n_first} shown options with a quote" if k == "first quote flagged other-place" else ""
    print(f"== {k}: {len(issues[k])}{of}")
    for x in issues[k][:12]:
        print("  ", x)
sys.exit(1 if issues["unredacted name"] or issues["unredacted name in route"]
         or issues["other-place source (flagged)"] or issues["first quote flagged other-place"] else 0)

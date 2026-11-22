"""Hindi engine coverage (#140 WS2 2e): engine text in /api/plan is English; in Hindi, E() in app.js shows the row
from hi.json "engine". Every engine string the page passes through E() must resolve there, or it reaches a Hindi
reader in English.

- every template in the server's string tables (facts/engine.py STRINGS, SAY, LIKELY_FARTHER) has a hi row, with
  the same slots;
- /api/plan over the probe points x every service: every string at an E() path resolves with app.js's own engHi
  (run under node by engine_hi_harness.mjs), placeholders kept.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from facts.engine import LIKELY_FARTHER, SAY, SITE_STRINGS, STRINGS

HI = json.loads((APP / "static" / "i18n" / "hi.json").read_text())["engine"]
SLOT = re.compile(r"\{(\w+)\}")

# The 8 demo points (validation/demo_qa.py), the faithfulness and audit probes, and two more state capitals.
PROBES = {"Sitamarhi": (26.5951, 85.4808), "Mohania": (25.15, 83.68), "Pusa": (25.6, 85.95), "Patna": (25.61, 85.14),
          "Gaya": (24.78, 85.0), "Bahraich": (27.57, 81.6), "Banda": (25.48, 80.33), "Darbhanga": (26.15, 85.9),
          "Pusa SDH": (25.67, 85.844), "Gaya hero": (24.79, 85.0), "Aurangabad": (19.88, 75.34),
          "Pune": (18.52, 73.86), "Nagpur": (21.15, 79.09), "Odisha": (20.8, 85.01), "Palamu": (24.0, 84.0),
          "Kalahandi": (19.9, 83.17), "Jabalpur": (23.18, 79.95), "Lucknow": (26.85, 80.95)}

# Every payload path app.js passes through E() on the plan screens ("*" is any list index).
E_PATHS = [
    "abstain.text", "abstain.outside_option.label", "abstain.outside_option.text", "public_option.label",
    "itinerary_note", "itinerary.pathway_name", "itinerary.stop_1_note", "itinerary.abstain",
    "itinerary.fallback.ask", "itinerary.fallback.text", "why_not.*.reason",
    "itinerary.plans.*.type_word", "itinerary.plans.*.vs_direct.text", "itinerary.plans.*.vs_direct.what_would_change",
    "itinerary.plans.*.window_checks.*.check", "itinerary.plans.*.stops.*.purpose_word",
    "itinerary.plans.*.stops.*.weakest_capability", "itinerary.plans.*.stops.*.question",
    "itinerary.plans.*.stops.*.flags.*", "rank_rule.text",
    "options.*.route_reason", "options.*.why_first_text", "options.*.band_word", "options.*.travel.label",
    "options.*.say_to_family.en", "options.*.where_check", "options.*.is_real.*", "options.*.flags.*",
    "options.*.call_ahead.*.question", "options.*.call_ahead.*.asked_because", "options.*.track_record.basis",
    "options.*.evidence.*.field", "options.*.evidence.*.flags.*.text",
    "options.*.contributions.*.quotes.*.field", "options.*.contributions.*.quotes.*.flags.*.text",
    # 2c contract fields the page does not draw yet; covered so they are Hindi the day it does
    "itinerary.itinerary_note", "itinerary.plans.*.stops.*.note",
]
# A ledger row's label goes through E() only when the payload has no label_hi (rowLabel in app.js).
LABEL_PATHS = ["options.*.contributions.*", "options.*.not_observed.*"]


def walk(node: Any, parts: list[str], path: str = "") -> Iterator[tuple[str, Any]]:
    if not parts:
        yield path, node
        return
    head, rest = parts[0], parts[1:]
    if head == "*":
        for i, x in enumerate(node if isinstance(node, list) else []):
            yield from walk(x, rest, f"{path}.{i}")
    elif isinstance(node, dict) and node.get(head) is not None:
        yield from walk(node[head], rest, f"{path}.{head}" if path else head)


def engine_strings(plan: dict) -> Iterator[tuple[str, str]]:
    """(path, text) for every engine string the plan screens pass through E()."""
    for pat in E_PATHS:
        for path, v in walk(plan, pat.split(".")):
            if isinstance(v, str) and v:
                yield path, v
    for pat in LABEL_PATHS:
        for path, row in walk(plan, pat.split(".")):
            if isinstance(row, dict) and "label_hi" not in row and row.get("label"):
                yield path + ".label", row["label"]


def to_hindi(items: list[tuple[str, dict | None]]) -> list[str | None]:
    """app.js engHi on each (text, query), under node."""
    payload = json.dumps({"items": [{"text": t, "q": q} for t, q in items]})
    out = subprocess.run(["node", str(APP / "tests" / "engine_hi_harness.mjs")], input=payload, capture_output=True,
                         text=True, check=True)
    return json.loads(out.stdout)


def plans() -> Iterator[tuple[str, str, dict]]:
    from fastapi.testclient import TestClient
    from services import SERVICES

    import app as app_module

    client = TestClient(app_module.app)
    for name, (lat, lon) in PROBES.items():
        for service in sorted(SERVICES):
            yield name, service, client.post("/api/plan", json={"service": service, "lat": lat, "lon": lon}).json()


def unmapped() -> dict[str, list[str]]:
    """English text that would reach a Hindi reader: {text: [where it was seen]}."""
    seen: list[tuple[str, str, dict | None]] = []
    for name, service, plan in plans():
        q = plan.get("query")
        seen += [(f"{name}/{service}: {path}", text, q) for path, text in engine_strings(plan)]
    hi = to_hindi([(t, q) for _, t, q in seen])
    out: dict[str, list[str]] = {}
    for (where, text, _), h in zip(seen, hi, strict=True):
        if h is None:
            out.setdefault(text, []).append(where)
    return out


def server_templates() -> dict[str, str]:
    """{name: English template} from the server's string tables of engine text."""
    t = {f"STRINGS.{k}": v["en"] for k, v in STRINGS.items()}
    t |= {f"SAY.{k}": v for k, v in SAY.items()}
    t["LIKELY_FARTHER"] = LIKELY_FARTHER
    t |= {f"SITE_STRINGS.{k}": SITE_STRINGS[k]["en"] for k in ("unchecked", "unreliable")}  # is_real, through E()
    return t


def test_every_server_template_has_a_hindi_row():
    """Each template has a hi.json engine row with the same slots. {dist} is km_words(): one row per form."""
    missing, slots = [], []
    for name, en in server_templates().items():
        forms = [en.replace("{dist}", d) for d in ("about {km} km away", "less than 1 km away")] if "{dist}" in en \
            else [en]
        for form in forms:
            row = HI.get(form)
            if row is None:
                missing.append(f"{name}: {form}")
            elif sorted(SLOT.findall(form)) != sorted(SLOT.findall(row)):
                slots.append(f"{name}: {form} -> {row}")
    assert not missing, "server templates with no hi.json engine row:\n" + "\n".join(missing)
    assert not slots, "slots differ between en and hi:\n" + "\n".join(slots)


def test_server_strings_have_hindi():
    """STRINGS keeps en and hi side by side: no hi is left empty, and each en has its hi.json row."""
    bad = [k for k, v in STRINGS.items() if not v.get("hi") or v["en"] not in HI]
    assert not bad, f"STRINGS with no hi: {bad}"


def test_hindi_rows_keep_their_slots():
    """Every templated row says the same slots in Hindi; {label} and {need} are filled by the page."""
    bad = [k for k, v in HI.items() if not k.startswith("_") and isinstance(v, str)
           and sorted(set(SLOT.findall(k))) != sorted(set(SLOT.findall(v)))]
    assert not bad, f"slots differ: {bad}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_every_engine_string_on_the_plan_screens_has_hindi():
    import app as app_module

    if app_module._engine() is None:
        pytest.skip("facility data not built (app/facts/build.py)")
    left = unmapped()
    lines = [f"{t!r} ({len(w)}x, e.g. {w[0]})" for t, w in sorted(left.items(), key=lambda kv: -len(kv[1]))]
    assert not left, f"{len(left)} engine strings with no Hindi:\n" + "\n".join(lines)

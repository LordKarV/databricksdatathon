"""Release test (spec 5.4, issue #30): every value shown equals the stored row it came from.

For each plan payload, the page is rendered in Chromium with /api/plan answered from the payload, and every
screen built from it is visited: results (or abstention), why / how / call-ahead per option, and the referral
slip in English and Hindi. The page marks each value it shows from the payload with data-f="<json path>" and
data-k="<kind>". This test then checks:

- each marked value equals its source field: text verbatim; numbers within the precision shown (so "24 km" for
  24.6 fails); totals equal the sum of their parts; band words follow the fixed mapping;
- no unmarked digit is on screen, apart from fixed template text (108, 102, 112, 24x7, Hindi "24 hours",
  "in 10 listings") and device-side text (location, clock times, call outcomes) marked data-device;
- every evidence quote and every contribution of an option is shown on its why page, and every quote carries
  its claim id; when the claim id exists in derived/v1/claims.parquet, the quote equals that claim's text;
- the claim id is a hidden mark, never printed, and no derived/ path is printed (#121);
- read aloud (voice support): the Hindi and English text the Read aloud button speaks on the results and why /
  call-ahead screens (state.spoken, from static/speech.js) lists the payload path of every value it uses; each
  equals its field and is in the spoken text, and no other digit is spoken except 108 and 102.

Field reports (community/field.py): the real plans go through apply_field as /api/plan does. One extra payload
carries fixed reports, and test_field_report_lines_equal_the_aggregates recounts them here: every count and "N days
ago" on a field line equals the reports. The family journey card (journey.js) is downloaded from the slip screen
for every option in both languages: each marked name, phone and number equals the plan, and no other digit is on it.

Payloads: three real plans from derived/v1 (#42; when app/facts/out is built) plus the stub fixtures.
Set FAITH_PLANS=<dir> to run against a directory of plan JSON files (for example
the model export from #11): no test changes needed.
"""
from __future__ import annotations

import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pw = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))
from facts.redact import redact_names  # noqa: E402, RUF100
from stub_data import SERVICES, area_stub, recommend_stub  # noqa: E402

# NO_SERVICE_TEXT (derived/v2 sub-band, from options.N.model_band) names the service (#118): "No line about" is the
# band's marked part, the label after it is marked query.service_label.en, and ": call to ask" is fixed text.
BAND_WORDS = {"likely": ("Likely", "\u0938\u0902\u092d\u093e\u0935\u0928\u093e \u091c\u093c\u094d\u092f\u093e\u0926\u093e"),
              "not_verified": ("Not confirmed", "\u092a\u0915\u094d\u0915\u093e \u0928\u0939\u0940\u0902"),
              "unlikely": ("Unlikely", "\u0938\u0902\u092d\u093e\u0935\u0928\u093e \u0915\u092e"),
              "NO_SERVICE_TEXT": ("No line about", "\u0915\u0947 \u092c\u093e\u0930\u0947 \u092e\u0947\u0902 "
                                  "\u0932\u093f\u0938\u094d\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u0915\u0941\u091b \u0928\u0939\u0940\u0902")}
# UI2 shows one language at a time (design/ui2/SPEC.md); every fixed word below has its Hindi twin from app/static/i18n/hi.json.
I18N = {lang: json.loads((Path(__file__).resolve().parents[1] / "static" / "i18n" / f"{lang}.json").read_text())
        for lang in ("en", "hi")}
WORDS = {k: (I18N["en"][k], I18N["hi"][k]) for k in ("travel.road", "travel.rough", "route.met", "route.not_met",
                                                      "delta.same", "num.over99", "num.under1")}
STATIC_PHRASES = [r"\b108\b", r"\b102\b", r"\b112\b", r"\b24x7\b", r"\b24 \u0918\u0902\u091f\u0947",  # "24 ghante" (#104)
                  r"\bin 10 listings\b", r"\bNFHS-5\b"]  # NFHS-5: the survey's name on the Area brief (WS4 4b)
# Labels whose meaning must not drift: the gap split is a safety rule (spec Safety 19.1).
AREA_ROW_FIELDS = {
    "Access now: a Likely listing in reach": "area.summary.access_now",
    "If calls confirm the listings": "area.summary.access_if_confirmed",
    "Calls could close": "area.summary.calls_could_close",
    "No public evidence of care": "area.summary.no_public_evidence",
}
IST = timezone(timedelta(hours=5, minutes=30))  # the browser context runs in Asia/Kolkata


def verify_fixture(o: dict) -> dict:
    """A website-check result (#37) as /api/verify returns it; real results replace it with FAITH_PLANS runs."""
    t = int(time.time() * 1000)
    return {"facility_id": o["facility_id"], "service_id": "x", "status": "found",
            "status_text": "website lists",
            "quotes": [{"text": f"{o['name']} has a dialysis unit with 10 machines, open 24 hours.",
                        "url": "https://example.org/services/dialysis", "says": "yes"},
                       {"text": "Haemodialysis 6 days a week, 2 shifts.", "url": "https://example.org/",
                        "says": "yes"}],
            "pages_checked": ["https://example.org/"], "checked_at": "", "checked_at_ms": t, "cached": False}


def json_reply(obj: Any):
    body = json.dumps(obj)
    return lambda route: route.fulfill(status=200, content_type="application/json", body=body)


SITAMARHI = {"latitude": 26.5951, "longitude": 85.4808, "accuracy": 40}


REAL_QUERIES = {"gaya_dialysis": ("dialysis", 24.79, 85.0),
                "sitamarhi_dialysis": ("dialysis", 26.6, 85.48),  # verified option far, nearer ones not verified
                "maharashtra_csection": ("emergency_csection", 19.88, 75.34),
                "nh19_trauma_mohania": ("trauma_emergency", 25.15, 83.68),
                # #86 demo QA: the audit's trauma probe, a quote naming a doctor, quotes with source warnings
                "pusa_trauma": ("trauma_emergency", 25.6, 85.95),
                "pune_cardiac_named_doctor": ("cardiac_surgery", 18.52, 73.86),
                "nagpur_mri_flagged_sources": ("mri", 21.15, 79.09),
                # a Likely option 1 that misses the 60-min window, without abstaining; and one that abstains
                "odisha_csection_likely_far": ("emergency_csection", 20.8, 85.01),
                "palamu_nicu_out_of_window": ("nicu", 24.0, 84.0),
                # BE-001: Mohania (above) has an unchecked website on option 1; Banda an unreliable one with its reason
                "banda_trauma_unreliable_site": ("trauma_emergency", 25.48, 80.33)}


def check_website_card(payload: dict, shown: set[str]) -> list[str]:
    """BE-001: a card with a flagged listed website shows its label, and its reason line exactly when unreliable."""
    errs = []
    for i, o in enumerate(payload.get("options", [])):
        w = o.get("website")
        if not w:
            continue
        if f"options.{i}.website.label.en" not in shown:
            errs.append(f"option {i + 1}: website label not shown")
        if (f"options.{i}.website.reason_line.en" in shown) != (w["site_status"] == "unreliable"):
            errs.append(f"option {i + 1}: reason line shown for a {w['site_status']} website, or missing")
    return errs


# ---------- payloads ----------
def load_payloads() -> list[tuple[str, dict]]:
    src = os.environ.get("FAITH_PLANS")
    if src:
        files = sorted(Path(src).glob("*.json"))
        assert files, f"FAITH_PLANS={src} has no .json files"
        # A plan file may carry its area payload under "area_plan" (S11); otherwise the Area screen uses the stub.
        return [(f.stem, json.loads(f.read_text())) for f in files]
    out = []
    # Real rows (#42): the three release queries from derived/v1, with their real area plans.
    from community import field
    from facts.engine import Engine
    from itinerary import attach
    eng = Engine.load()
    if eng is not None:
        for name, (svc, lat, lon) in REAL_QUERIES.items():
            plan = attach(eng.plan(svc, lat, lon, 40, "gps"), eng)  # with the planner's route (#47) when built
            plan["area_plan"] = eng.area(svc, lat, lon)
            # As /api/plan answers when the warehouse is down: no field term, the plain note.
            plan = {**field.apply_field(plan, {}, FIELD_NOW), "field_reports": {"read": False, "note": field.NOT_READ}}
            out.append((f"real-{name}", plan))
        plan = attach(eng.plan("dialysis", 26.6, 85.48, 40, "gps"), eng)
        plan = {**field.apply_field(plan, field_aggregates(plan), FIELD_NOW), "field_reports": {"read": True, "note": None}}
        out.append(("real-sitamarhi_dialysis-field", plan))
        # Tie-break (#86): the COMMUNITY_DEMO reports break the tie at the README point; the why page row is checked.
        agg: dict = {}
        for r in field.simulated_reports(eng, FIELD_NOW):
            agg.setdefault((r["facility_id"], r["service_id"]), []).append(r)
        plan = attach(eng.plan("dialysis", *field.DEMO_POINT, 40, "gps"), eng)
        plan = {**field.apply_field(plan, agg, FIELD_NOW), "field_reports": {"read": True, "note": None}}
        assert plan.get("tie_break"), "demo reports no longer break a tie at the README point"
        out.append(("real-sitamarhi_dialysis-tie", plan))
    for svc in sorted(SERVICES):
        for name, (lat, lon) in {"sitamarhi": (26.6, 85.48), "pune": (18.52, 73.86)}.items():
            plan = recommend_stub(svc, lat, lon, 40, "gps")
            plan["area_plan"] = area_stub(svc, lat, lon)
            out.append((f"stub-{svc}-{name}", plan))
    return out


# ---------- field reports fed to apply_field (fixed; the test recounts them) ----------
FIELD_NOW = datetime.now(UTC)
# (option index, reporter key or None, kind, outcome, reason, days ago)
FIELD_REPORTS = (
    (0, "a" * 16, "visit", "accepted", None, 4), (0, "b" * 16, "visit", "accepted", None, 12),
    (0, "c" * 16, "call", "yes", None, 20), (0, "c" * 16, "call", "no", "service_not_here", 40),
    (0, None, "visit", "accepted", None, 1),  # no reporter key: never counts
    # Disagreement on the Likely option 3: it stays above the Likely line, so it stays on the plan (a lowered
    # Not verified option can drop out of the top 3 now that reports re-rank).
    (2, "d" * 16, "visit", "turned_away", "no_bed", 1), (2, "e" * 16, "visit", "turned_away", "no_bed", 3),
    (2, "a" * 16, "visit", "turned_away", "service_not_here", 5), (2, "f" * 16, "call", "no", "equipment_absent", 8),
    (1, "a" * 16, "call", "yes", None, 2),  # one reporter: a line, no score change
)


FIELD_FIDS: dict[int, str] = {}  # option index in the plan before the reports -> facility; reports can re-rank


def field_aggregates(plan: dict) -> dict:
    out: dict = {}
    for i, key, kind, outcome, reason, days in FIELD_REPORTS:
        if i < len(plan["options"]):
            fid = FIELD_FIDS.setdefault(i, plan["options"][i]["facility_id"])
            out.setdefault((fid, "dialysis"), []).append({
                "facility_id": fid, "service_id": "dialysis", "reporter_key": key, "kind": kind, "outcome": outcome,
                "reason": reason, "created_at": FIELD_NOW - timedelta(days=days, hours=2)})
    return out


PAYLOADS = load_payloads()


def claim_texts() -> dict[str, str]:
    path = ROOT / "derived" / "v1" / "claims.parquet"
    if not path.is_file():
        return {}
    try:
        import pandas as pd
    except ImportError:  # claim-text check needs pandas + pyarrow (app/requirements-dev.txt); the rest still runs
        print("pandas missing: quotes not checked against derived/v1 claims")
        return {}
    c = pd.read_parquet(path, columns=["claim_id", "text"])
    return dict(zip(c.claim_id, c.text, strict=True))


# ---------- server and browser ----------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", str(port), "--no-access-log"],
                            cwd=APP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/ping", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")
        yield url
    finally:
        proc.terminate()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def claims():
    return claim_texts()


COLLECT_JS = """() => {
  const main = document.querySelector('#main');
  const visible = el => { const c = el.cloneNode(true); c.querySelectorAll('[aria-hidden]').forEach(x => x.remove());
    return c.textContent.replace(/\\s+/g, ' ').trim(); };
  const items = [...main.querySelectorAll('[data-f]')].map(el => ({path: el.dataset.f, kind: el.dataset.k,
    text: visible(el)}));
  const rest = main.cloneNode(true);
  rest.querySelectorAll('[data-f], [data-device], [aria-hidden], script').forEach(x => x.remove());
  const rows = [...main.querySelectorAll('tr')].map(tr => ({
    label: (tr.querySelector('th[scope=row]') || {}).textContent,
    paths: [...tr.querySelectorAll('td [data-f]')].map(e => e.dataset.f)}));
  return {items, rest: rest.textContent.replace(/\\s+/g, ' '), rows};
}"""


# ---------- checks ----------
def resolve(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def decimals(shown: str) -> int:
    m = re.search(r"\.(\d+)$", shown)
    return len(m.group(1)) if m else 0


def number(shown: str) -> float:
    shown = shown.strip().replace(",", "")  # digit grouping, e.g. 9,959 or 1,58,444
    m = re.fullmatch(r"[+-]?\d+(?:\.\d+)?", shown)
    assert m, f"not a number: {shown!r}"
    return float(shown)


def within_precision(shown: str, stored: float) -> bool:
    return abs(number(shown) - float(stored)) <= 0.5 * 10 ** -decimals(shown.strip().replace(",", "")) + 1e-9


def quote_numbers(s: str) -> list[str]:
    return re.findall(r"[0-9]+", re.sub(r"(?<=[0-9]),(?=[0-9])", "", s))  # 5,000 and 5000 are one number


def capped_pct_ok(shown: str, value: float) -> bool:
    """A chance shown as a whole percent, capped so a product of model chances never reads as certain."""
    shown = shown.strip()
    if shown in WORDS["num.over99"]:
        return value > 0.99
    if shown in WORDS["num.under1"]:
        return value < 0.01
    m = re.fullmatch(r"(\d+)%", shown)
    return bool(m) and 0.01 <= value <= 0.99 and within_precision(m[1], 100 * value)


def _engine_one(part: str, q: dict | None) -> str | None:
    table = I18N["hi"]["engine"]
    if part in table:
        return table[part]
    for k, v in table.items():
        if "{" not in k or k.startswith("_"):
            continue
        names: list[str] = []
        pat = re.escape(k)
        if q:
            pat = pat.replace(re.escape("{label}"), re.escape(q["service_label"]["en"]))
        pat = re.sub(r"\\\{(\w+)\\\}", lambda m: names.append(m[1]) or "(.+?)", pat)
        m = re.fullmatch(pat, part)
        if not m:
            continue
        vals = {"label": q["service_label"]["hi"] if q else "", **dict(zip(names, m.groups(), strict=True))}
        if "need" in vals:  # the engine's fixed {need} words have glossary terms (#121 bug 8)
            vals["need"] = table.get("_needs", {}).get(vals["need"], vals["need"])
        return re.sub(r"\{(\w+)\}", lambda x: vals.get(x[1], ""), v)
    return None


def engine_hi(text: str, payload: dict) -> str | None:
    """The Hindi the page must show for an engine template, computed here independently of app.js: an exact row, a
    row with {slots} (payload words copied, {label} = the service label), or a '; '-joined reason clause by clause."""
    q = payload.get("query") or (payload.get("area") or {}).get("query")
    whole = _engine_one(text, q)
    if whole is not None or "; " not in text:
        return whole
    parts = [_engine_one(p if i == 0 else p[0].upper() + p[1:], q) for i, p in enumerate(text.split("; "))]
    return None if None in parts else "; ".join(parts)


def check_item(payload: dict, it: dict) -> str | None:
    """None if the shown value is faithful, else a message."""
    path, kind, shown = it["path"], it["kind"], it["text"]
    try:
        stored = resolve(payload, path)
    except (KeyError, IndexError, ValueError, TypeError):
        return f"{path}: path not in payload (shown {shown!r})"
    if kind == "text":
        ok = shown == re.sub(r"\s+", " ", str(stored)).strip()
    elif kind == "num":
        ok = isinstance(stored, (int, float)) and within_precision(shown, stored)
    elif kind == "sum":  # the ledger total: the shown rows' sum, to the precision shown (tenths for derived/v2)
        ok = within_precision(shown, sum(c["points"] for c in stored))
    elif kind == "clock":
        m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])?", shown.strip())
        when = datetime.fromtimestamp(stored / 1000, IST)
        h = int(m[1]) % 12 + (12 if m[3] and m[3].lower() == "pm" else 0) if m and m[3] else int(m[1]) if m else -1
        ok = bool(m) and (h, int(m[2])) == (when.hour, when.minute)
    elif kind == "pct":  # a stored fraction shown as a whole percent: '82' for 0.82
        ok = isinstance(stored, (int, float)) and within_precision(shown, 100 * stored)
    elif kind == "pct100":  # UI-SCORE-1: a model score out of 100, '47 / 100' for 0.47, so round(100 * p)
        m = re.fullmatch(r"(\d+) / 100", shown.strip())
        ok = bool(m) and isinstance(stored, (int, float)) and within_precision(m[1], 100 * stored)
    elif kind == "count":  # how many items a list holds: '3' for three options
        ok = isinstance(stored, list) and number(shown) == len(stored)
    elif kind == "likely":  # how many options in a list are in the Likely band: '2' in "2 of 3 options are Likely"
        ok = isinstance(stored, list) and number(shown) == sum(o["band"] == "likely" for o in stored)
    elif kind == "atleast":  # 1 - prod(1 - p) as a capped percent: 'over 99%', 'under 1%' or 'N%' (#121)
        ok = capped_pct_ok(shown, 1 - math.prod(1 - o["p"] for o in stored))
    elif kind == "tenths":
        ok = int(number(shown)) == round(10 * stored["k_confirmed"] / stored["n"])
    elif kind == "band":
        ok = shown in BAND_WORDS.get(stored, ())
    elif kind == "method":
        ok = shown in WORDS["travel.road" if stored == "osrm" else "travel.rough"]
    elif kind == "dur":  # minutes shown as 'N min', 'N h' or 'N day(s)' (Hindi: मिनट, घंटे, दिन), rounded to that unit
        m = re.fullmatch(r"(\d+) (min|h|days?|\u092e\u093f\u0928\u091f|\u0918\u0902\u091f\u0947|\u0926\u093f\u0928)", shown.strip())
        unit = {"min": 1, "h": 60, "day": 1440, "days": 1440, "\u092e\u093f\u0928\u091f": 1, "\u0918\u0902\u091f\u0947": 60,
                "\u0926\u093f\u0928": 1440}[m[2]] if m else 0
        ok = bool(m) and abs(int(m[1]) * unit - stored) <= unit / 2
    elif kind == "delta":  # minutes against the first choice: 'N min closer', 'N min farther', 'about the same time'
        m = re.fullmatch(r"(\d+) (?:min|\u092e\u093f\u0928\u091f) (closer|farther|\u092a\u093e\u0938|\u0926\u0942\u0930)", shown.strip())
        ok = (stored == 0 and shown.strip() in WORDS["delta.same"]) or (
            bool(m) and int(m[1]) == abs(stored) and (m[2] in ("closer", "\u092a\u093e\u0938")) == (stored < 0) and stored != 0)
    elif kind == "met":
        ok = shown in (WORDS["route.met"] if stored is True else WORDS["route.not_met"] if stored is False else ())
    elif kind == "template":  # Hindi rendering of a fixed engine template (hi.json "engine"); see engine_hi
        ok = isinstance(stored, str) and shown == engine_hi(stored, payload)
    elif kind == "part":  # a name or number restored into a translated quote: copied verbatim from the quote
        ok = re.sub(r"\s+", " ", shown).strip() in re.sub(r"\s+", " ", str(stored))
    elif kind == "term":  # a clinical term in its fixed Hindi rendering: any number in it is one of the quote's
        ok = set(quote_numbers(shown)) <= set(quote_numbers(str(stored)))
    elif kind == "mapsurl":
        m = re.search(r"destination=(-?[\d.]+),(-?[\d.]+)", shown)
        ok = bool(m) and math.isclose(float(m[1]), stored["lat"]) and math.isclose(float(m[2]), stored["lon"])
    else:
        return f"{path}: unknown kind {kind!r}"
    return None if ok else f"{path} ({kind}): shown {shown!r}, stored {repr(stored)[:120]}"


# A score next to a bracketed range reads as an interval around it; v2's lo / hi are the bin's confirmed rate (#121).
BRACKETED_RANGE = re.compile(r"\b\d\.\d{2} \(\d\.\d{2} to \d\.\d{2}\)|\(\d\.\d{2}, [a-z ]+\d\.\d{2} to \d\.\d{2}")
CERTAIN_CHANCE = re.compile(r"checks out: (?:1\.00|100%)")


def check_number_wording(text: str) -> list[str]:
    """No score with its lo / hi in brackets, and no chance shown as certain."""
    text = re.sub(r"\s+", " ", text)
    return ([f"score with a bracketed range: {m[0]!r}" for m in BRACKETED_RANGE.finditer(text)]
            + [f"chance shown as certain: {m[0]!r}" for m in CERTAIN_CHANCE.finditer(text)])


SPOKEN_JS = """() => typeof state !== 'undefined' && state.spoken"""


def num_str(v: Any) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def check_spoken(name: str, payload: dict, spoken: dict, only: int | None, report: dict) -> list[str]:
    """Read-aloud text (both languages) against the payload: the spoken twin of check_item and stray_digits."""
    errs = []
    for lang in ("hi", "en"):
        text, fields, tag = spoken[lang]["text"], spoken[lang]["fields"], f"{name}/speech-{lang}"
        if not text.strip():
            errs.append(f"{tag}: nothing to read aloud")
        rest = text
        for f in sorted(fields, key=lambda f: -len(str(f["value"]))):
            path, kind, val = f["path"], f["kind"], f["value"]
            try:
                src = resolve(payload, path)
            except (KeyError, IndexError, ValueError, TypeError):
                errs.append(f"{tag}: {path} not in payload")
                continue
            if kind == "num":
                ok = float(src) == float(val) and num_str(val) in text
            elif kind == "part":
                ok = val in src and val in text
            else:
                ok = src == val and (kind not in ("text", "template") or val in text or kind == "template")
            if kind in ("text", "part"):
                rest = rest.replace(val, " ")
            if not ok:
                errs.append(f"{tag}: {path} ({kind}) spoken {val!r}, stored {repr(src)[:120]}")
            if only is not None and not path.startswith((f"options.{only}.", "emergency_numbers.", "abstain.", "query.")):
                errs.append(f"{tag}: {path} is not about option {only}")
            report["values_checked"] += 1
        allowed = {num_str(f["value"]) for f in fields if f["kind"] == "num"} | {"108", "102"}
        errs += [f"{tag}: unmarked number {d!r} spoken" for d in re.findall(r"\d+", rest) if d not in allowed]
    return errs


def spoken_on(page) -> dict:
    assert page.locator("#speak").count() == 1, "no Read aloud button"
    # UI2: no separate read-aloud language toggle; read aloud follows the app language (#121 bug 8 superseded).
    assert page.locator("[data-say-lang]").count() == 0
    return page.wait_for_function(SPOKEN_JS).json_value()


def stray_digits(rest: str) -> list[str]:
    for pat in STATIC_PHRASES:
        rest = re.sub(pat, " ", rest)
    return re.findall(r"\S*\d\S*", rest)


def check_screen(name: str, payload: dict, got: dict, report: dict) -> list[str]:
    errs = [f"{name}: {e}" for it in got["items"] if (e := check_item(payload, it))]
    errs += [f"{name}: unmarked number {tok!r} on screen" for tok in stray_digits(got["rest"])]
    report["values_checked"] += len(got["items"])
    return errs


def check_quotes(name: str, payload: dict, items: list[dict], claims: dict[str, str], report: dict) -> list[str]:
    errs = []
    shown = {it["path"] for it in items}
    for it in items:
        if not it["path"].endswith(".quote") or it["kind"] != "text":  # "part"/"term": pieces of a translation
            continue
        base = it["path"][: -len(".quote")]
        if base + ".claim_id" not in shown:
            errs.append(f"{name}: quote {it['path']} shown without its claim id")
        cid = resolve(payload, base + ".claim_id")
        if cid in claims:
            text, q = redact_names(claims[cid]), it["text"]  # a doctor's name is never shown (#86)
            ok = q == text or (q.endswith("...") and text.startswith(q[:-3]))
            report["quotes_matched_to_claims"] += ok
            if not ok:
                errs.append(f"{name}: quote {it['path']} differs from claim {cid}: {q!r} vs {text!r}")
        else:
            report["quotes_without_claim_row"] += 1
    return errs


def raw_key_errs(name: str, payload: dict, text: str) -> list[str]:
    """#121: the visible text (inner_text skips hidden marks) shows no claim id and no derived/ path."""
    ids = {e["claim_id"] for o in payload["options"] for e in o["evidence"] if e.get("claim_id")}
    ids |= {e["claim_id"] for r in (payload.get("itinerary") or {}).get("plans") or [] for s in r["stops"]
            for e in s.get("evidence") or [] if e.get("claim_id")}
    errs = [f"{name}: claim id {c} printed" for c in sorted(ids) if c in text]
    return errs + ([f"{name}: a derived/ path printed"] if "derived/" in text else [])


CARD_TEMPLATE_NUMBERS = {"108", "102", "24", "7", "1", "16"}  # 108/102 lines, "24x7", Hindi stop list, map zoom


def check_card(name: str, payload: dict, card: str, report: dict) -> list[str]:
    """The family journey card: every marked value equals the plan, every tel: is 108, 102 or a plan phone, and no
    other digit is on it (Safety 13: no confidence numbers, no patient data)."""
    import html as htmllib
    errs = []
    marks = re.findall(r'<span data-f="([^"]+)"[^>]*>(.*?)</span>', card, flags=re.DOTALL)
    if not marks:
        errs.append(f"{name}: no marked values")
    for path, shown in marks:
        try:
            stored = resolve(payload, path)
        except (KeyError, IndexError, ValueError, TypeError):
            errs.append(f"{name}: {path} not in payload")
            continue
        if htmllib.unescape(shown) != str(stored):
            errs.append(f"{name}: {path} shown {shown!r}, stored {stored!r}")
    report["values_checked"] += len(marks)
    rows = list(payload["options"]) + [s for r in (payload.get("itinerary") or {}).get("plans") or [] for s in r["stops"]]
    phones = {r["phone"]["e164"] for r in rows if r.get("phone") and r["phone"].get("e164")}
    errs += [f"{name}: tel:{t} is not in the plan" for t in re.findall(r'href="tel:([^"]+)"', card)
             if t not in phones | {"108", "102"}]
    rest = re.sub(r"<(script|style)\b.*?</\1>", " ", card, flags=re.DOTALL)
    rest = re.sub(r"<span data-(?:f|device)\b[^>]*>.*?</span>", " ", rest, flags=re.DOTALL)
    rest = htmllib.unescape(re.sub(r"<[^>]+>", " ", rest))
    errs += [f"{name}: unmarked number {d!r} on the card" for d in set(re.findall(r"\d+", rest)) - CARD_TEMPLATE_NUMBERS]
    return errs


# ---------- #86: why not the nearest, flagged citations, data gap vs care gap ----------
PUBLIC_LABEL = "by public standard, not verified"
WINDOW_LINE = "The best-evidenced option is about"
NEAREST_LINE = "The first choice is already the nearest listing"
WHY_NOT_CODES = {"contradicted", "no_quote", "weak_quotes", "outside_window", "farther", "missing", "evidence_kind",
                 "location", "shared_phone", "not_confirmed", "weaker"}


def check_why_not(payload: dict, shown: set[str]) -> list[str]:
    """Every why-not row and the change line are shown, and each reason agrees with the fields it names."""
    errs, opts = [], payload["options"]
    first = opts[0]["travel"]["minutes"] if opts else None
    for k, w in enumerate(payload.get("why_not") or []):
        for f in ("name", "reason", "travel.km"):
            if f"why_not.{k}.{f}" not in shown:
                errs.append(f"why_not.{k}.{f} not shown")
        if "minutes_vs_first" not in w:
            continue  # an older export without the structured fields: the shown text is still checked verbatim
        if f"why_not.{k}.minutes_vs_first" not in shown:
            errs.append(f"why_not.{k}.minutes_vs_first not shown")
        if w["minutes_vs_first"] != w["travel"]["minutes"] - first:
            errs.append(f"why_not.{k}: minutes_vs_first {w['minutes_vs_first']} is not its travel minus option 1's")
        if w["facility_id"] == opts[0]["facility_id"]:
            errs.append(f"why_not.{k}: lists the first choice")
        if (w["option_rank"] is not None) != any(o["facility_id"] == w["facility_id"] for o in opts):
            errs.append(f"why_not.{k}: option_rank disagrees with the options list")
        for b in w["basis"]:
            code = b["code"]
            bad = (code not in WHY_NOT_CODES
                   or (code == "farther" and not (b["value"] == w["minutes_vs_first"] > 0))
                   or (code == "outside_window" and not (b["value"] == w["travel"]["minutes"] > b["window_min"]))
                   or (code == "contradicted" and w["band"] != "unlikely")
                   or (code == "not_confirmed" and not (w["band"] == "not_verified" and opts[0]["band"] == "likely")))
            if bad:
                errs.append(f"why_not.{k}: reason {code} does not match its fields {b} / band {w['band']}")
        if w["reason_code"] != w["basis"][0]["code"]:
            errs.append(f"why_not.{k}: reason_code is not the first basis")
        if payload.get("first_is_nearest") and w["minutes_vs_first"] < 0:
            errs.append(f"why_not.{k}: nearer than option 1, but first_is_nearest is set")
    c = payload.get("what_would_change")
    if c:
        for f in ("name", "minutes_vs_first"):
            if f"what_would_change.{f}" not in shown:
                errs.append(f"what_would_change.{f} not shown")
        if c["kind"] == "confirm_nearer" and not c["minutes_vs_first"] < 0:
            errs.append("what_would_change: confirm_nearer is not nearer than option 1")
        if c["kind"] == "first_says_no" and (len(opts) < 2 or c["facility_id"] != opts[1]["facility_id"]):
            errs.append("what_would_change: first_says_no does not point at option 2")
    tw = payload.get("time_window")
    if tw and opts and tw["first_outside"] != (first > tw["window_min"]):
        errs.append("time_window.first_outside disagrees with option 1's travel time")
    if tw and tw["first_outside"]:
        need = ["time_window.window_min", "options.0.travel.minutes"]
        po = payload.get("public_option")
        if po:
            need += ["public_option.name", "public_option.label", "public_option.travel.km"]
            if po["label"] != PUBLIC_LABEL:
                errs.append(f"public_option.label is {po['label']!r}")
        errs += [f"time_window: {x} not shown while option 1 misses the window" for x in need if x not in shown]
    return errs


def check_quote_flags(o: dict, i: int, shown: set[str]) -> list[str]:
    """Every warning on a quote is shown next to it; weak quotes come after clean ones (demoted, not hidden)."""
    errs = []
    weak = [sum(f["weak"] for f in e.get("flags", [])) for e in o["evidence"]]
    if weak != sorted(weak):
        errs.append(f"evidence of option {i} is not ordered clean first: {weak}")
    for j, e in enumerate(o["evidence"]):
        for m, f in enumerate(e.get("flags", [])):
            P = f"options.{i}.evidence.{j}.flags.{m}"
            need = [P + ".text"] + ([P + ".place"] if f.get("place") else []) + ([P + ".km"] if f.get("km") else [])
            errs += [f"{x} not shown" for x in need if x not in shown]
    return errs


def check_gap(area: dict, shown: set[str]) -> list[str]:
    g = area.get("gap")
    if not g:
        return []
    errs = [f"area.gap.{k} not shown" for k in ("district_claiming", "district_confirmed", "covered",
                                                 "not_confirmed", "far", "no_claim", "pins_sampled", "pins_in_district")
            if f"area.gap.{k}" not in shown]
    split = g["covered"] + g["not_confirmed"] + g["far"] + g["no_claim"]
    if not split == g["pins_sampled"] == len(area["pins"]):
        errs.append(f"area.gap: the split does not add up to the sampled PINs {g}")
    for k in ("covered", "not_confirmed", "far", "no_claim"):
        if g[k] != sum(r.get("gap") == k for r in area["pins"]):
            errs.append(f"area.gap.{k} is not the count of PIN rows with that gap")
    # Where the area shows no public evidence, the public-standard hospitals are named and labelled as such.
    for k, r in enumerate(area["pins"]):
        if r["first"] is None and r.get("public"):
            errs += [f"area.pins.{k}.public.{f} not shown" for f in ("name", "label", "km")
                     if f"area.pins.{k}.public.{f}" not in shown]
            if r["public"]["label"] != PUBLIC_LABEL:
                errs.append(f"area.pins.{k}.public.label is {r['public']['label']!r}")
    s = area["summary"]
    pn = g.get("public_nearest")
    if pn and not g.get("public_standard") and (s["n_without_option"] > 0 or s["no_public_evidence"] > 0):
        errs += [f"area.gap.public_nearest.{f} not shown" for f in ("name", "label", "km")
                 if f"area.gap.public_nearest.{f}" not in shown]
        if pn["label"] != PUBLIC_LABEL:
            errs.append(f"area.gap.public_nearest.label is {pn['label']!r}")
    if s["n_without_option"] > 0 or s["no_public_evidence"] > 0:
        for k, h in enumerate(g.get("public_standard") or []):
            errs += [f"area.gap.public_standard.{k}.{f} not shown" for f in ("name", "label")
                     if f"area.gap.public_standard.{k}.{f}" not in shown]
            if h["label"] != PUBLIC_LABEL:
                errs.append(f"area.gap.public_standard.{k}.label is {h['label']!r}")
    return errs


# ---------- sealed TEST record (#86, #66): the band and the How page show the committed results ----------
TEST_RECORD_SHOWN = ("k", "n", "pct", "lo_pct", "hi_pct", "public_n", "opened", "model_version", "predictions_sha256",
                     "labels_sha256", "log", "source")
GOLD_V3 = ROOT / "model" / "gold" / "v3"


def check_brief(area: dict, shown: set[str]) -> list[str]:
    """WS4 4b: the district brief shows every need value it has, each government list row, the headline's numbers
    and the source of each; check_screen has already compared each shown value with the payload."""
    need, errs = area["area"].get("need"), []
    if need:
        keys = ["population", "listings", "listings_per_million", "india_per_million", "lgd_district",
                "source.people", "source.listings"]
        if area["query"]["service"] in ("emergency_csection", "nicu") and need["csection_pct"] is not None:
            keys += ["csection_pct", "nfhs_district", "source.nfhs"] + [k for k in (
                "public_csection_pct", "private_csection_pct", "institutional_pct") if need[k] is not None]
        errs += [f"area.area.need.{k} not shown" for k in keys if f"area.area.need.{k}" not in shown]
    for j, g in enumerate(area["area"].get("gov_list", [])):
        want = ("centres", "districts_working", "districts_total") if g["list"] == "pmndp" else ("name", "valid_to")
        errs += [f"area.area.gov_list.{j}.{k} not shown" for k in want if f"area.area.gov_list.{j}.{k}" not in shown]
    h = area.get("headline")
    if h:
        errs += [f"area.headline.{k} not shown" for k in ("n", "window_min")[h["kind"] == "none_in_window":]
                 if f"area.headline.{k}" not in shown]
        if h["kind"] == "if_confirms" and not {"area.headline.k", "area.headline.now", "area.ten_calls.0.name"} <= shown:
            errs.append("area.headline: the first call's name, k or now not shown")
    return errs


def expected_test_record() -> dict:
    """Read straight from the committed files, independently of app/facts/build.py."""
    res = json.loads((GOLD_V3 / "test_eval" / "results.json").read_text())
    lk = res["headline_decided"]["LIKELY_confirmed"]
    log = next(ln for ln in (GOLD_V3 / "OPENING_LOG.md").read_text().splitlines() if ln.startswith("| opened "))
    cells = [c.strip() for c in log.strip().strip("|").split("|")]
    return {"k": lk["k"], "n": lk["n"], "pct": round(100 * lk["rate"]), "lo_pct": round(100 * lk["ci95"][0]),
            "hi_pct": round(100 * lk["ci95"][1]), "public_n": res["by_operator_decided"]["public"]["n"],
            "model_version": res["model_version"], "predictions_sha256": res["test_predictions_sha256"],
            "labels_sha256": cells[4], "opened": cells[1]}


def test_sealed_test_record_equals_the_results_file():
    from facts.engine import Engine
    eng = Engine.load()
    if eng is None or not eng.test_record:
        pytest.skip("facts export without a TEST record (interim scores or app/facts/out not built)")
    want = expected_test_record()
    meta = eng._meta()["test_record"]
    assert {k: meta[k] for k in want} == want
    assert meta["model_version"] == json.loads((ROOT / "derived/v2/model_card.json").read_text())["model_version"]
    if HOW_JSON.is_file():
        f = json.loads(HOW_JSON.read_text())["facts"]
        how = {"k": f["test_likely"]["value"], "n": f["test_likely"]["of"], "pct": f["test_likely_pct"]["value"],
               "lo_pct": f["test_likely_lo"]["value"], "hi_pct": f["test_likely_hi"]["value"],
               "public_n": f["test_public_n"]["value"], "model_version": f["test_model_version"]["value"],
               "predictions_sha256": f["test_predictions_sha"]["value"], "labels_sha256": f["test_labels_sha"]["value"],
               "opened": f["test_opened"]["value"]}
        assert how == want


def check_no_text(payload: dict, text: str, only: int | None = None) -> list[str]:
    """A NO SERVICE TEXT option (#118): its chip names the service, and a caption above its quotes says they are not
    about the service, so general emergency lines do not read as contradicting the chip. UI2 shows quotes on the
    option's own Why page, so the answer screen checks every chip (only=None, caption not required) and each Why page
    checks its option's chip and caption (only=i)."""
    label = payload["query"]["service_label"]["en"]
    errs = []
    for i, o in enumerate(payload["options"]):
        if o.get("model_band") != "NO_SERVICE_TEXT" or (only is not None and i != only):
            continue
        if f"No line about {label}: call to ask" not in text:
            errs.append(f"{o['name']}: NO SERVICE TEXT chip does not name {label!r}")
        if only is not None and o["evidence"] and not re.search(rf"\b(?:not|none) about {re.escape(label)}\b", text):
            errs.append(f"{o['name']}: quotes of a NO SERVICE TEXT option have no caption")
    return errs


def check_ledger(o: dict, i: int, shown: set[str], claims: dict[str, str]) -> list[str]:
    """The witness ledger (derived/v2): every row's label and points are shown, every quote a row cites is shown with
    its claim id, and that id is a derived/v1 claim. Not-observable families are named. check_screen has already
    compared each shown value with the payload and the total with the rows' sum."""
    errs = []
    for j, c in enumerate(o["contributions"]):
        C = f"options.{i}.contributions.{j}"
        errs += [f"{C}.label not shown"] if f"{C}.label" not in shown else []
        for k, q in enumerate(c.get("quotes", [])):
            if not {f"{C}.quotes.{k}.quote", f"{C}.quotes.{k}.claim_id"} <= shown:
                errs.append(f"{C}.quotes.{k} not shown with its claim id")
            if claims and q["claim_id"] not in claims:
                errs.append(f"{C}.quotes.{k}: claim {q['claim_id']} is not a derived/v1 claim")
        # WS4 4a: every official-list or OpenStreetMap row the term rests on is shown with its source (a NABH row
        # shows its text in English, its entry number under the Hindi tier wording)
        for k, x in enumerate(c.get("cites", [])):
            if not ({f"{C}.cites.{k}.text", f"{C}.cites.{k}.id"} & shown and f"{C}.cites.{k}.source" in shown):
                errs.append(f"{C}.cites.{k} not shown with its source")
            if x["precision_n"] and not {f"{C}.cites.{k}.precision_k", f"{C}.cites.{k}.precision_n"} <= shown:
                errs.append(f"{C}.cites.{k}: hand-check precision not shown")
    errs += [f"options.{i}.not_observed.{j} not shown" for j in range(len(o.get("not_observed", [])))
             if f"options.{i}.not_observed.{j}.label" not in shown]
    errs += [f"options.{i}.public_lists.{j} not shown" for j in range(len(o.get("public_lists", [])))
             if not {f"options.{i}.public_lists.{j}.{f}" for f in ("text", "id", "name")} & shown]
    if f"options.{i}.contributions" not in shown:
        errs.append("ledger total not shown")
    return errs


def check_tie_row(payload: dict, o: dict, rows: list[dict]) -> list[str]:
    """Tie-break (#86): a tied option's why page has the named row, with the rule and every tied option's value
    marked; an option outside the tie (or a plan without one) has no such row."""
    tb = payload.get("tie_break")
    named = [r for r in rows if (r["label"] or "").startswith("Tie broken by: health-worker reports")]
    if not tb or o["facility_id"] not in {x["facility_id"] for x in tb["options"]}:
        return ["tie row shown outside a tie"] if named else []
    if len(named) != 1 or named[0]["label"].strip() != tb["label"]:
        return [f"tie row missing or mislabelled: {[r['label'] for r in named]}"]
    if tb["simulated"] and "simulated for the demo" not in tb["label"]:
        return ["simulated tie-break not labelled"]
    need = {"tie_break.p_within", "tie_break.minutes_within"} | {
        f"tie_break.options.{j}.{k}" for j, x in enumerate(tb["options"]) if x["net"] is not None
        for k in ("net", "n_reporters")}
    ranks = {f"options.{i}.rank" for i, y in enumerate(payload["options"])
             if y["facility_id"] in {x["facility_id"] for x in tb["options"]}}
    missing = sorted((need | ranks) - set(named[0]["paths"]))
    return [f"tie row does not show {missing}"] if missing else []


def check_doubt(payload: dict, shown: set[str]) -> list[str]:
    """WS1 1d: when option 1's map point may be wrong (location_doubt, #147), the readout names its address and,
    when the engine has it, the time from the PIN centre (travel.alt)."""
    o = (payload.get("options") or [None])[0]
    if not o or not o.get("location_doubt"):
        return []
    need = ["options.0.address" if o.get("address") else "options.0.town"]
    if (o.get("travel") or {}).get("alt"):
        need += ["options.0.travel.alt.low", "options.0.travel.alt.high"]
    return [f"location doubt: {x} not shown" for x in need if x not in shown]


def test_location_doubt_line_on_the_readout(base_url, browser):
    """WS1 1d on a payload with the #147 fields set (works before #147 merges): the amber line, marked, in en and hi."""
    import copy
    base = next(p for n, p in PAYLOADS if n.startswith("stub-trauma"))
    payload = copy.deepcopy(base)
    o = payload["options"][0]
    o["location_doubt"] = True
    o["travel"]["alt"] = {"minutes": 30, "low": 25, "high": 41, "from": "pin_centre"}
    for lang in ("en", "hi"):
        ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
        page = ctx.new_page()
        page.route("**/api/plan", json_reply(payload))
        page.add_init_script("localStorage.setItem('rs.lang', " + json.dumps(json.dumps(lang)) + ");"
                             "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
                             " source: 'gps', t: Date.now(), label: null}))")
        try:
            page.goto(base_url + "/#/")
            page.locator(f"[data-svc={payload['query']['service']}]").first.click()
            page.wait_for_selector("article.card .doubt")
            got = page.evaluate(COLLECT_JS)
        finally:
            ctx.close()
        shown = {it["path"] for it in got["items"]}
        errs = check_doubt(payload, shown) + check_screen(f"doubt/{lang}", payload, got, {"values_checked": 0})
        assert not errs, errs[:10]


def test_why_page_shows_the_score_out_of_100(base_url, browser):
    """UI-SCORE-1: a score of p = 0.47 reads "47 / 100" next to its band word on the Why page, in en and hi, and the
    mark checks it as round(100 * p); no score is shown as a decimal."""
    import copy
    base = next(p for n, p in PAYLOADS if n.startswith("stub-trauma"))
    payload = copy.deepcopy(base)
    o = payload["options"][0]
    o["p"] = 0.47
    for lang in ("en", "hi"):
        ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
        page = ctx.new_page()
        page.route("**/api/plan", json_reply(payload))
        page.add_init_script("localStorage.setItem('rs.lang', " + json.dumps(json.dumps(lang)) + ");"
                             "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
                             " source: 'gps', t: Date.now(), label: null}))")
        try:
            page.goto(base_url + "/#/")
            page.locator(f"[data-svc={payload['query']['service']}]").first.click()
            page.wait_for_selector("article.card")
            page.evaluate("h => { location.hash = h; }", f"#/why/{o['rank']}")
            page.wait_for_selector(".why-head")
            got = page.evaluate(COLLECT_JS)
            text = page.inner_text("#main")
        finally:
            ctx.close()
        scores = [it for it in got["items"] if it["path"] == "options.0.p"]
        assert scores and all(it["kind"] == "pct100" and it["text"] == "47 / 100" for it in scores), scores
        assert "47 / 100" in text and not re.search(r"\b0\.47\b", text)
        errs = check_screen(f"score100/{lang}", payload, got, {"values_checked": 0})
        assert not errs, errs[:10]


NO_DIAL = ("window.addEventListener('click', e => { const a = e.target.closest && e.target.closest('a[href^=\"tel:\"]');"
           " if (a) e.preventDefault(); }, true);")
PHONE_BACK = """() => { Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'});
  document.dispatchEvent(new Event('visibilitychange')); }"""


def check_call_loop(page, payload: dict, plan_shown: set[str], report: dict) -> list[str]:
    """#140 3d: the Ask line shows options.0.call_ahead.0.question; after "Said no" on option 1, the "Call next" line
    (name, minutes, band of the next option with a number) equals its fields. The loop is reset afterwards."""
    opts = payload["options"]
    if not opts:
        return []
    errs = []
    if opts[0]["call_ahead"] and "options.0.call_ahead.0.question" not in plan_shown:
        errs.append("the Ask line (options.0.call_ahead.0.question) is not shown")
    tel = [i for i, o in enumerate(opts) if (o.get("phone") or {}).get("e164")]
    if not tel or tel[0] != 0 or len(tel) < 2:
        return errs
    page.route("**/api/outcome", json_reply({}))
    page.locator("#main .call-main").click()
    page.wait_for_function("() => state.call")  # community.js loaded on the tap
    page.evaluate(PHONE_BACK)
    page.locator("#call-loop [data-call-out=no]").click()
    page.wait_for_selector("#call-next-btn")
    got = page.evaluate(COLLECT_JS)
    errs += [f"call-next: {e}" for e in check_screen("call-next", payload, got, report)]
    shown = {it["path"] for it in got["items"]}
    band = "model_band" if opts[tel[1]].get("model_band") == "NO_SERVICE_TEXT" else "band"  # bandHtml's mark
    errs += [f"call-next: options.{tel[1]}.{f} not shown" for f in ("name", "travel.minutes", band)
             if f"options.{tel[1]}.{f}" not in shown]
    page.evaluate("() => { RSCommunity.dropPending(); state.call = null; state.outcomes = {}; render(); }")
    page.unroute("**/api/outcome")
    return errs


# ---------- the test ----------
@pytest.mark.parametrize("name, payload", PAYLOADS, ids=[n for n, _ in PAYLOADS])
def test_every_shown_value_equals_its_stored_row(name, payload, base_url, browser, claims):
    report = {"values_checked": 0, "quotes_matched_to_claims": 0, "quotes_without_claim_row": 0}
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, geolocation=SITAMARHI,
                              timezone_id="Asia/Kolkata", locale="en-IN",
                              permissions=["geolocation"], service_workers="block")
    page = ctx.new_page()
    page.add_init_script("Object.defineProperty(Navigator.prototype, 'canShare', {value: undefined})")
    page.add_init_script(NO_DIAL)  # the call loop (#140 3d): tel: links stay on the page
    page.route("**/api/plan", lambda r: r.fulfill(status=200, content_type="application/json",
                                                  body=json.dumps(payload)))
    page.add_init_script(
        "localStorage.getItem('rs.lang') || localStorage.setItem('rs.lang', '\"en\"');"
        "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
        " source: 'gps', t: Date.now(), label: null}))")
    area = payload.get("area_plan") or area_stub(payload["query"]["service"], 26.6, 85.48)
    page.route("**/api/area", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(area)))
    full = {**payload, "area": area}  # data-f paths on the Area screen start with "area."
    errs: list[str] = []
    try:
        page.goto(base_url + "/#/")
        page.locator(f"[data-svc={payload['query']['service']}]").first.click()
        page.wait_for_selector("article.card")
        if payload.get("itinerary"):  # the answer renders first; route.js re-renders it with the route
            page.wait_for_function("typeof routeHtml === 'function'")
            page.evaluate("() => new Promise(r => setTimeout(r, 50))")
        got = page.evaluate(COLLECT_JS)
        errs += check_screen("plan", payload, got, report)
        plan_shown = {it["path"] for it in got["items"]}
        errs += [f"plan: {e}" for e in check_doubt(payload, plan_shown)]
        # WS1 1c: the golden-hour sentence sits under the route strip, outside Route details, when the route has one
        it0 = payload.get("itinerary") or {}
        vd = None if it0.get("abstain") else (((it0.get("plans") or [{}])[0].get("vs_direct") or {}).get("text"))
        main_vd = page.evaluate("""() => [...document.querySelectorAll('#main [data-f="itinerary.plans.0.vs_direct.text"]')]
          .filter(e => !e.closest('details')).length""")
        if bool(vd) != (main_vd == 1):
            errs.append(f"plan: golden-hour sentence shown {main_vd} times outside Route details, vs_direct.text={bool(vd)}")
        # WS1 1b: the readout's receipt is option 1's first quote (a marked piece of it, cut at 60 characters), and
        # its "Why first" line is marked: why-not rows, ledger rows or the engine's rank rule.
        # #171 review: the receipt is the first quote with no weak flag that is not a generic description (else the
        # first, with its warning), cut at the last space at or before 60 characters.
        o0 = (payload.get("options") or [None])[0]
        if o0 and o0["evidence"]:
            j = next((k for k, e in enumerate(o0["evidence"]) if not any(f.get("weak") for f in e.get("flags", []))
                      and e.get("field") != "description"), 0)
            q = o0["evidence"][j]["quote"]
            want = q if len(q) <= 60 else (q[:q.rfind(" ", 0, 61)] if q.rfind(" ", 0, 61) > 0 else q[:60]).rstrip()
            receipt = page.evaluate("p => { const e = document.querySelector(`#main .answer [data-f=\"${p}\"]`);"
                                    " return e ? e.textContent : null; }", f"options.0.evidence.{j}.quote")
            if receipt != want:
                errs.append(f"plan: receipt {receipt!r}, expected evidence {j} cut at a word: {want!r}")
            for m, f in enumerate(o0["evidence"][j].get("flags", [])):
                if f"options.0.evidence.{j}.flags.{m}.text" not in plan_shown:
                    errs.append(f"plan: receipt quote's warning {m} not shown")
        # #140 overload review: the card keeps only a specific why-first (the farther Likely option, or planned care's
        # top ledger rows); the general rank rule moved to the Why page, so an unmarked line must not appear either.
        if page.evaluate("() => [...document.querySelectorAll('#main .answer .why-first')].some(e => !e.querySelector('[data-f]'))"):
            errs.append("plan: an unmarked 'Why first' line on the readout")
        # Safety (#140 WS1): the route line on the answer screen shows a missed window check, never a green
        # "inside the limit" while another check (for example definitive care) is not met.
        checks = (((payload.get("itinerary") or {}).get("plans") or [{}])[0]).get("window_checks") or []
        if checks:
            miss = page.evaluate("() => { const w = document.querySelector('#main .route > .window'); return w ? w.classList.contains('miss') : null; }")
            if miss != any(not c["met"] for c in checks):
                errs.append(f"plan: route line shows miss={miss}, but checks are {[c['met'] for c in checks]}")
        errs += check_spoken("plan", payload, spoken_on(page), None, report)
        opts = payload["options"]
        far = (opts and opts[0]["band"] != "likely" and any(o["band"] == "likely" for o in opts)
               and any(o["band"] != "likely" and o["travel"]["minutes"] < min(
                   x["travel"]["minutes"] for x in opts if x["band"] == "likely") for o in opts))
        errs += [f"plan: {e}" for e in check_website_card(payload, {it["path"] for it in got["items"]})]
        text = page.inner_text("#main")
        errs += [f"plan: {e}" for e in check_no_text(payload, re.sub(r"\s+", " ", text))]
        errs += raw_key_errs("plan", payload, text)
        errs += [f"plan: {e}" for e in check_call_loop(page, payload, plan_shown, report)]
        if (payload.get("time_window") or {}).get("first_outside"):  # the answer's first line (#86)
            first_row = min((text.find(x) for x in [payload["options"][0]["name"], "Suggested route",
                                                     (payload.get("abstain") or {}).get("text") or "\0"]
                             if text.find(x) >= 0), default=len(text))
            if not 0 <= text.find(WINDOW_LINE) < first_row or "Call 108" not in text:
                errs.append("plan: option 1 misses the window but that is not the first line, with 108")
        shown_note = "The nearest verified" in page.inner_text("#main")
        if bool(far) != shown_note:
            errs.append(f"plan: far-verified note shown={shown_note}, expected={bool(far)}")
        for i, o in enumerate(payload["options"]):
            page.evaluate("h => { location.hash = h; }", f"#/why/{o['rank']}")
            page.wait_for_selector("#how")
            got = page.evaluate(COLLECT_JS)
            errs += check_screen(f"why/{o['rank']}", payload, got, report)
            errs += check_quotes(f"why/{o['rank']}", payload, got["items"], claims, report)
            wtext = page.inner_text("#main")
            errs += raw_key_errs(f"why/{o['rank']}", payload, wtext)
            errs += [f"why/{o['rank']}: {e}" for e in check_no_text(payload, re.sub(r"\s+", " ", wtext), i)]
            if i == 0:  # UI2: "Why not the nearest?" sits on option 1's Why page (it explains why option 1 is first)
                # why-not rows on this page; the window line it also checks is the answer screen's first line
                errs += [f"why/{o['rank']}: {e}" for e in check_why_not(payload, plan_shown | {it["path"] for it in got["items"]})]
                # #121: it says plainly when option 1 is already the nearest listing
                said = NEAREST_LINE in wtext
                if said != bool(payload.get("first_is_nearest") and (payload.get("why_not") or payload.get("what_would_change"))):
                    errs.append(f"why/{o['rank']}: first-is-nearest line shown={said}, "
                                f"first_is_nearest={payload.get('first_is_nearest')}")
            spoken = spoken_on(page)
            errs += check_spoken(f"why/{o['rank']}", payload, spoken, i, report)
            if f"options.{i}.name" not in {f["path"] for f in spoken["en"]["fields"]}:
                errs.append(f"why/{o['rank']}: read aloud does not name this option")
            shown = {it["path"] for it in got["items"]}
            for j in range(len(o["evidence"])):
                if f"options.{i}.evidence.{j}.quote" not in shown:
                    errs.append(f"why/{o['rank']}: evidence {j} not shown")
            for j in range(len(o["contributions"])):
                if f"options.{i}.contributions.{j}.points" not in shown:
                    errs.append(f"why/{o['rank']}: contribution {j} not shown")
            errs += [f"why/{o['rank']}: {e}" for e in check_quote_flags(o, i, shown)]
            if o.get("website") and f"options.{i}.website.text.en" not in shown:
                errs.append(f"why/{o['rank']}: website line not shown")
            errs += [f"why/{o['rank']}: {e}" for e in check_ledger(o, i, shown, claims)]
            sure = re.sub(r"\s+", " ", page.inner_text("#how-sure"))
            if "()" in sure or re.search(r"(?:^|[:;.]) ?\([+-]", sure):  # a row named without its label
                errs.append(f"why/{o['rank']}: How sure has an empty label: {sure[:200]!r}")
            errs += [f"why/{o['rank']}: {e}" for e in check_tie_row(payload, o, got["rows"])]
            errs += [f"why/{o['rank']}: {e}" for e in check_number_wording(page.inner_text("#main"))]
            tr = payload.get("meta", {}).get("test_record")
            if tr and o["band"] == "likely":  # the sealed TEST record sits next to every Likely band (#86)
                errs += [f"why/{o['rank']}: meta.test_record.{k} not shown" for k in TEST_RECORD_SHOWN
                         if f"meta.test_record.{k}" not in shown]
            # Live website check (#37): the dated line and its quotes must equal the /api/verify answer.
            ver = verify_fixture(o)
            page.route("**/api/verify", json_reply(ver))
            page.locator("#verify-btn").click()
            page.wait_for_selector("#verify-out blockquote")
            got = page.evaluate(COLLECT_JS)
            errs += check_screen(f"why/{o['rank']}/website", {**payload, "verify": ver}, got, report)
            vshown = {it["path"] for it in got["items"]}
            for need in ("verify.checked_at_ms", "verify.status_text", "verify.quotes.0.text", "verify.quotes.1.url"):
                if need not in vshown:
                    errs.append(f"why/{o['rank']}/website: {need} not shown")
            page.unroute("**/api/verify")
            for lang in ("en", "hi"):
                page.evaluate("h => { location.hash = h; }", f"#/slip/{o['rank']}")
                page.wait_for_selector(".slip")
                if lang == "hi":
                    page.locator("#lang-btn").click()  # UI2: one app-wide language, switched in the top bar
                    page.wait_for_selector(".slip[lang=hi]")
                got = page.evaluate(COLLECT_JS)
                errs += check_screen(f"slip/{o['rank']}/{lang}", payload, got, report)
                errs += check_quotes(f"slip/{o['rank']}/{lang}", payload, got["items"], claims, report)
                errs += raw_key_errs(f"slip/{o['rank']}/{lang}", payload, page.inner_text("#main"))
                with page.expect_download() as dl:  # Web Share is off in this context, so the card downloads
                    page.locator("#slip-card").click()
                card = Path(dl.value.path()).read_text(encoding="utf-8")
                errs += check_card(f"card/{o['rank']}/{lang}", payload, card, report)
                if lang == "hi":
                    page.locator("#lang-btn").click()  # back to English for the next option
                    page.wait_for_selector(".slip[lang=en]")
            page.evaluate("h => { location.hash = h; }", "#/plan")
            page.wait_for_selector("article.card")
        # Compare (S10): asks "patient here?" with no default, then every option side by side.
        page.locator("[data-depth=compare]").click()
        page.locator("input[name=here][value=yes]").click()
        page.wait_for_selector(".compare-cards")
        got = page.evaluate(COLLECT_JS)
        errs += check_screen("compare", payload, got, report)
        errs += [f"compare: {e}" for e in check_number_wording(page.inner_text("#main"))]
        # #140 3e: band counts, never a "Chance ... checks out" line, on Compare
        kinds = {(it["path"], it["kind"]) for it in got["items"]}
        if payload["options"] and not {("options", "likely"), ("options", "count")} <= kinds:
            errs.append("compare: the Likely count line is not shown")
        if re.search(r"\bchance\b", page.inner_text("#main"), re.IGNORECASE):
            errs.append("compare: a 'chance' label is still shown")
        errs += check_quotes("compare", payload, got["items"], claims, report)
        shown = {it["path"] for it in got["items"]}
        for i in range(len(payload["options"])):
            # derived/v2: a NO_SERVICE_TEXT pair shows its band, not p (derived/v2/README)
            no_text = payload["options"][i].get("model_band") == "NO_SERVICE_TEXT"
            for f in (("p_e", "p_l", "travel.km") if no_text else ("p", "p_lo", "p_hi", "p_e", "p_l", "travel.km")):
                if f"options.{i}.{f}" not in shown:
                    errs.append(f"compare: options.{i}.{f} not shown")
        # Area (S11, S12): per-PIN plan, gap split and ten calls.
        page.evaluate("h => { location.hash = h; }", "#/area")  # UI2: the Area tab (no nav on the answer screen)
        page.wait_for_selector("#ten-calls")
        got = page.evaluate(COLLECT_JS)
        errs += check_screen("area", full, got, report)
        rows = {r["label"]: r["paths"] for r in got["rows"] if r["label"]}
        for label, path in AREA_ROW_FIELDS.items():
            if rows.get(label) != [path]:
                errs.append(f"area: row {label!r} shows {rows.get(label)}, expected [{path!r}]")
        shown = {it["path"] for it in got["items"]}
        for k in range(len(area["pins"])):
            if f"area.pins.{k}.pin" not in shown:
                errs.append(f"area: pin row {k} not shown")
        for k in range(len(area["ten_calls"])):
            if f"area.ten_calls.{k}.access_gain" not in shown:
                errs.append(f"area: call {k} not shown")
        errs += [f"area: {e}" for e in check_gap(area, shown)]
        errs += [f"area: {e}" for e in check_brief(area, shown)]
    finally:
        ctx.close()
    print(f"{name}: {report}")
    assert report["values_checked"] > 0
    assert not errs, "\n".join(errs[:40]) + (f"\n... {len(errs) - 40} more" if len(errs) > 40 else "")


# ---------- 'How this works' page (#45): every number comes from how.json, every source is a repo file ----------
HOW_JSON = APP / "howto" / "out" / "how.json"


@pytest.mark.skipif(not HOW_JSON.is_file(), reason="how.json not built (app/howto/build.py)")
def test_how_page_every_number_is_from_how_json(base_url, browser):
    how = json.loads(HOW_JSON.read_text())
    report = {"values_checked": 0}
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
    page = ctx.new_page()
    page.add_init_script("localStorage.setItem('rs.lang', '\"en\"')")  # UI2 asks for a language on first launch
    try:
        page.goto(base_url + "/#/how")
        page.wait_for_selector("text=Page data built")
        got = page.evaluate(COLLECT_JS)
        links = page.eval_on_selector_all("#main a[href^='http']", "as => as.map(a => a.href)")
    finally:
        ctx.close()
    errs = check_screen("how", how, got, report)
    shown = {it["path"] for it in got["items"]}
    errs += [f"how: fact {k} not shown" for k, f in how["facts"].items() if f"facts.{k}.value" not in shown]
    for k, t in how["tables"].items():
        errs += [f"how: table {k} cell {i}.{j} not shown" for i, r in enumerate(t["rows"]) for j in range(len(r))
                 if f"tables.{k}.rows.{i}.{j}" not in shown]
    for href in links:
        rel = href.removeprefix(how["repo_url"])
        if rel == href or not (ROOT / rel).exists():
            errs.append(f"how: link {href} is not a file in this repo")
    print(f"how: {report}, {len(links)} source links")
    assert not errs, "\n".join(errs[:40])


# ---------- translated quote: every number in the Hindi text is the quote's own ----------
TRANSLATABLE = [(n, p, i, j) for n, p in PAYLOADS for i, o in enumerate(p.get("options") or [])
                for j, e in enumerate(o.get("evidence") or []) if re.search(r"[0-9]", e["quote"])][:1]


@pytest.mark.skipif(not TRANSLATABLE, reason="no payload with a quote that has a number")
def test_translated_quote_shows_only_the_quotes_numbers(base_url, browser):
    """Tap "हिंदी में पढ़ें" on a quote with numbers; /api/translate is answered by the server's own protect and
    restore code with a fake model reply. Every marked piece must match the quote, every number in the Hindi text
    must be one of the quote's, and the original quote is still shown verbatim above it."""
    from inputs import translate as tr

    name, payload, i, j = TRANSLATABLE[0]
    quote = payload["options"][i]["evidence"][j]["quote"]
    _, spans = tr.protect(quote)
    fake = " ".join(f"⟦{k}⟧ हिंदी" for k in range(1, len(spans) + 1)) or "हिंदी"  # the model's words have no digits
    body = json.dumps({"available": True, "hindi": tr.restore(fake, spans),
                       "parts": tr.restore_parts(fake, spans, quote)}, ensure_ascii=False)
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
    page = ctx.new_page()
    page.route("**/api/plan", json_reply(payload))
    page.route("**/api/translate", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    page.add_init_script("localStorage.setItem('rs.lang', '\"hi\"')")  # UI2: the translate button is on Hindi screens
    page.add_init_script(
        "localStorage.getItem('rs.lang') || localStorage.setItem('rs.lang', '\"en\"');"
        "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
        " source: 'gps', t: Date.now(), label: null}))")
    P = f"options.{i}.evidence.{j}.quote"
    try:
        page.goto(base_url + "/#/")
        page.locator(f"[data-svc={payload['query']['service']}]").first.click()
        page.wait_for_selector("article.card")
        page.evaluate("h => { location.hash = h; }", f"#/why/{payload['options'][i]['rank']}")
        box = page.locator("blockquote", has=page.locator(f'[data-f="{P}"][data-k="text"]'))
        box.locator(".tr-btn").click()
        box.locator(".tr-text").wait_for()
        got = page.evaluate(COLLECT_JS)
        hindi = box.locator(".tr-text").inner_text()
        original = box.locator(f'[data-f="{P}"][data-k="text"]').inner_text()
    finally:
        ctx.close()
    errs = check_screen(f"{name}/translated", payload, got, {"values_checked": 0})
    assert not errs, "\n".join(errs[:20])
    assert quote_numbers(hindi) and set(quote_numbers(hindi)) <= set(quote_numbers(quote)), (hindi, quote)
    assert original == re.sub(r"\s+", " ", quote).strip()


# ---------- UI2: the same screens in Hindi (one language at a time) ----------
REAL = [(n, p) for n, p in PAYLOADS if n.startswith("real-")]
# English UI strings that must never show on a Hindi screen: the fixed part of each en.json string before any slot.
EN_UI = sorted({v.split("{")[0].strip() for k, v in I18N["en"].items()
                if not k.startswith(("_", "svc.", "lang.", "set.size_sample")) and isinstance(v, str)
                and len(v.split("{")[0].strip()) >= 12})


def english_leaks(text: str) -> list[str]:
    return [e for e in EN_UI if e in text]


@pytest.mark.skipif(not REAL, reason="app/facts/out not built: no real payloads")
@pytest.mark.parametrize("name, payload", REAL, ids=[n for n, _ in REAL])
def test_hindi_screens_equal_their_rows(name, payload, base_url, browser):
    """Answer and Why pages in Hindi: every marked value equals its row (engine text as its reviewed Hindi template,
    kind 'template'), no unmarked number, no raw key, and no English screen string."""
    report = {"values_checked": 0}
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, timezone_id="Asia/Kolkata", locale="hi-IN",
                              service_workers="block")
    page = ctx.new_page()
    page.route("**/api/plan", json_reply(payload))
    page.add_init_script("localStorage.setItem('rs.lang', '\"hi\"');"
                         "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
                         " source: 'gps', t: Date.now(), label: null}))")
    errs: list[str] = []
    try:
        page.goto(base_url + "/#/")
        page.locator(f"[data-svc={payload['query']['service']}]").first.click()
        page.wait_for_selector("article.card")
        screens = [("plan", page.evaluate(COLLECT_JS), page.inner_text("#main"))]
        for o in payload["options"]:
            page.evaluate("h => { location.hash = h; }", f"#/why/{o['rank']}")
            page.wait_for_selector("#how")
            screens.append((f"why/{o['rank']}", page.evaluate(COLLECT_JS), page.inner_text("#main")))
        assert page.evaluate("document.documentElement.lang") == "hi"
    finally:
        ctx.close()
    for screen, got, text in screens:
        errs += check_screen(f"hi/{screen}", payload, got, report)
        errs += raw_key_errs(f"hi/{screen}", payload, text)
        errs += [f"hi/{screen}: English on screen: {e!r}" for e in english_leaks(text)]
        errs += [f"hi/{screen}: Latin am/pm in a Hindi time: {m!r}" for m in re.findall(r"\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)\b", text)]
    templ = sum(it["kind"] == "template" for _, got, _ in screens for it in got["items"])
    print(f"{name} (hi): {report}, {templ} engine templates in Hindi")
    assert report["values_checked"] > 0
    assert not errs, "\n".join(errs[:40])


@pytest.mark.skipif(not HOW_JSON.is_file(), reason="how.json not built (app/howto/build.py)")
def test_how_page_states_the_band_rule_the_model_uses():
    """#121: the How page quotes derived/v2/model_card.json band_thresholds.rule word for word, with its thresholds."""
    how, card = json.loads(HOW_JSON.read_text()), json.loads((ROOT / "derived/v2/model_card.json").read_text())
    bt, f = card["band_thresholds"], how["facts"]
    assert f["band_rule"]["value"] == bt["rule"] and f["band_rule"]["source"] == "derived/v2/model_card.json"
    assert (f["likely_p"]["value"], f["likely_p_location"]["value"], f["likely_p_exists"]["value"]) == (
        bt["likely"]["p"], bt["likely"]["p_location"], bt["likely"]["p_exists"])


def test_displayed_transforms_are_checked_against_the_stored_value():
    """#121: kinds for a value shown in another form than stored: pct (fraction as percent), count, capped atleast."""
    opts = {"options": [{"p": 0.81, "p_lo": 0.82, "p_hi": 0.93}, {"p": 0.9}, {"p": 0.95}]}  # 1 - prod = 0.99905

    def item(path: str, kind: str, text: str) -> str | None:
        return check_item(opts, {"path": path, "kind": kind, "text": text})

    assert item("options.0.p_lo", "pct", "82") is None and item("options.0.p_hi", "pct", "93") is None
    assert item("options.0.p_lo", "pct", "0.82") is not None and item("options.0.p_lo", "pct", "80") is not None
    assert item("options", "count", "3") is None and item("options", "count", "2") is not None
    assert item("options.0.p", "pct100", "81 / 100") is None
    assert item("options.0.p", "pct100", "0.81") is not None and item("options.0.p", "pct100", "81") is not None
    assert item("options.0.p", "pct100", "79 / 100") is not None and item("options.0.p", "pct100", "81 / 10") is not None
    assert item("options", "atleast", "over 99%") is None
    assert item("options", "atleast", "1.00") is not None and item("options", "atleast", "100%") is not None
    assert capped_pct_ok("87%", 0.871) and not capped_pct_ok("over 99%", 0.95) and not capped_pct_ok("99%", 0.995)
    assert capped_pct_ok("under 1%", 0.004) and not capped_pct_ok("0%", 0.004)


def test_number_wording_flags_bracketed_ranges_and_certain_chances():
    before = [
        "Offers (range) 0.81 (0.82 to 0.93)",
        "LIKELY (0.81, listings with similar scores checked out 0.82 to 0.93 of the time).",
        "Chance at least one listing checks out: 1.00 (assumes they fail independently).",
    ]
    assert all(check_number_wording(t) for t in before)
    after = [
        "Offers score 0.81; similar listings confirmed: 82 to 93%",
        "LIKELY, score 0.81. Similar listings confirmed: 82 to 93%.",
        "Chance at least one of these 3 checks out: over 99% (assumes they fail independently).",
        "NOT VERIFIED, score 0.40. Range 0.20 to 0.60.",
    ]
    assert not any(check_number_wording(t) for t in after)


# ---------- multi-stop route (#47): every itinerary field is shown, or listed here as deliberately not shown ----------
# The vs_direct probabilities stay in the payload for the record; the page shows the plain sentence (#86).
# #140 WS2 2c adds stops[k].note and vs_direct.direct_minutes for ui2 (WS1) to render; until then they are not shown.
ROUTE_NOT_SHOWN = {"facility_id", "purpose", "type", "pathway", "urgency", "shared_listings", "direct_p_objective",
                   "plan_p_objective", "direct_p_first_care", "plan_p_first_care"}  # note, direct_minutes: shown (#152)


def route_leaves(obj: Any, path: str) -> list[str]:
    if isinstance(obj, dict):
        return [p for k, v in obj.items() if k not in ROUTE_NOT_SHOWN for p in route_leaves(v, f"{path}.{k}")]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in route_leaves(v, f"{path}.{i}")]
    return [] if obj is None else [path]


def route_expected(it: dict) -> set[str]:
    """Leaf paths the plan screen must show. A stage at the same hospital as the stop before it shares that stop's
    name, place, arrival time and phone, so those are shown once per hospital."""
    want = set()
    for k, r in enumerate(it["plans"]):
        P = f"itinerary.plans.{k}"
        for j, s in enumerate(r["stops"]):
            S, cont = f"{P}.stops.{j}", j > 0 and r["stops"][j - 1]["facility_id"] == s["facility_id"]
            for leaf in route_leaves(s, S):
                key = leaf[len(S) + 1:]
                if cont and key.split(".")[0] in ("name", "place", "eta_low", "eta_high", "phone"):
                    continue
                if key == "phone.e164" and s["phone"].get("display"):
                    continue  # the listing's own spelling of the number is shown, and dialled as e164
                if key == "place" and not s["place"]:
                    continue
                want.add(leaf)
        for key in ("rank", "type_word", "totals", "window_checks", "vs_direct"):
            want |= set(route_leaves(r.get(key), f"{P}.{key}"))
    want |= {"itinerary.pathway_name"} | ({"itinerary.abstain"} if it.get("abstain") else set())
    want |= {"itinerary.stop_1_note"} if it.get("stop_1_note") else set()
    return want


ROUTED = [(n, p) for n, p in PAYLOADS if p.get("itinerary")]
ROUTE_SCORE = re.compile(r"itinerary\.plans\.\d+\.(?:stops\.\d+\.(?:p|weakest_capability_p|fallback\.p)|totals\.p_(?:first_care|treated))")


@pytest.mark.skipif(not ROUTED, reason="no payload with a route (planner/out or app/facts/out not built)")
@pytest.mark.parametrize("name, payload", ROUTED, ids=[n for n, _ in ROUTED])
def test_every_route_field_is_shown(name, payload, base_url, browser):
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
    page = ctx.new_page()
    page.route("**/api/plan", json_reply(payload))
    page.add_init_script(
        "localStorage.getItem('rs.lang') || localStorage.setItem('rs.lang', '\"en\"');"
        "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
        " source: 'gps', t: Date.now(), label: null}))")
    try:
        page.goto(base_url + "/#/")
        page.locator(f"[data-svc={payload['query']['service']}]").first.click()
        page.wait_for_selector("text=Suggested route")
        got = page.evaluate(COLLECT_JS)
        route_text = page.evaluate("() => document.querySelector('#h-route').closest('section').textContent")
    finally:
        ctx.close()
    # #140 3e: the route says "score", never "chance"; its totals name their assumption; windows count from departure
    assert not re.search(r"\bchance\b", route_text, re.IGNORECASE), f"{name}: 'chance' on the route"
    if any(p["totals"].get("minutes_to_definitive") is not None for p in payload["itinerary"]["plans"]):
        assert "Evidence score if the listings are right" in route_text and I18N["en"]["route.totals_assume"] in route_text
    if any(p["window_checks"] for p in payload["itinerary"]["plans"]):
        assert "counted from when the patient leaves" in route_text
    shown = {it["path"] for it in got["items"]}
    missing = sorted(route_expected(payload["itinerary"]) - shown)
    assert not missing, f"{name}: route fields not shown: {missing[:20]}"
    assert not check_screen("route", payload, got, {"values_checked": 0})
    # UI-SCORE-1 (#193 review): every route score reads "N / 100" like the cards, checked as round(100 * p)
    scores = [it for it in got["items"] if ROUTE_SCORE.fullmatch(it["path"])]
    assert scores or not any(ROUTE_SCORE.fullmatch(x) for x in route_expected(payload["itinerary"])), f"{name}: no route score"
    bad = [it for it in scores if it["kind"] != "pct100" or not re.fullmatch(r"\d+ / 100", it["text"])]
    assert not bad, f"{name}: route scores not out of 100: {bad[:5]}"


# ---------- field reports: every count and "days ago" on a field line equals the reports fed in ----------
FIELD = [(n, p) for n, p in PAYLOADS if n.endswith("-field")]
NOT_OFFERED = ("service_not_here", "equipment_absent", "referred_elsewhere_for_this_service")
TEMPORARY = ("no_bed", "doctor_absent", "machine_down", "asked_to_pay", "closed_now")


def ago(days: float) -> str:
    return "today" if int(days) == 0 else f"{int(days)} day{'s' if int(days) > 1 else ''} ago"


def expected_field(fid: str) -> tuple[str | None, list[tuple[int, str]]]:
    """(summary line counts, [(n, note reason)]) recounted from FIELD_REPORTS by the rules in the README."""
    rows = [(k, kind, out, rsn, d) for i, k, kind, out, rsn, d in FIELD_REPORTS
            if k and d <= 90 and FIELD_FIDS.get(i) == fid]
    latest: dict = {}
    for k, kind, out, rsn, d in rows:
        what = ("accepted" if (kind, out) == ("visit", "accepted") else "phone_yes" if (kind, out) == ("call", "yes")
                else rsn if out in ("no", "turned_away") and rsn in NOT_OFFERED else None)
        if what and (k not in latest or d < latest[k][1]):
            latest[k] = (what, d)
    line = None
    if latest:
        n = len(latest)
        parts = []
        counts = {w: sum(1 for x, _ in latest.values() if x == w) for w in ("accepted", "phone_yes", *NOT_OFFERED)}
        if counts["accepted"]:
            parts.append(f"{counts['accepted']} accepted")
        if counts["phone_yes"]:
            parts.append(f"{counts['phone_yes']} said yes on the phone")
        parts += [f"{counts[r]} said" for r in NOT_OFFERED if counts[r]]
        who = "1 health worker" if n == 1 else f"{n} health workers"
        line = (f"Reports from {who} in the last 90 days: ", parts, f"; latest {ago(min(d for _, d in latest.values()))}.")
    notes = []
    for rsn in TEMPORARY:
        ks = {k: d for k, _, _, r, d in sorted(rows, key=lambda x: -x[4]) if r == rsn and d <= 7}
        if ks:
            notes.append((len(ks), ago(min(ks.values()))))
    return line, notes


@pytest.mark.skipif(not FIELD, reason="app/facts/out not built: no field-report payload")
def test_field_report_lines_equal_the_aggregates(base_url, browser):
    _, payload = FIELD[0]
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
    page = ctx.new_page()
    page.route("**/api/plan", json_reply(payload))
    page.add_init_script(
        "localStorage.getItem('rs.lang') || localStorage.setItem('rs.lang', '\"en\"');"
        "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
        " source: 'gps', t: Date.now(), label: null}))")
    errs, seen = [], 0
    try:
        page.goto(base_url + "/#/")
        page.locator("[data-svc=dialysis]").first.click()
        page.wait_for_selector("article.card")
        screens = []  # UI2: field reports sit on each option's Why page, not on the answer screen
        for o in payload["options"]:
            page.evaluate("h => { location.hash = h; }", f"#/why/{o['rank']}")
            page.wait_for_selector("#how")
            screens.append((f"why/{o['rank']}", page.evaluate(COLLECT_JS)))
    finally:
        ctx.close()
    for screen, got in screens:
        shown = {it["path"]: it["text"] for it in got["items"] if ".field." in it["path"]}
        for i, o in enumerate(payload["options"]):
            if screen.startswith("why/") and screen != f"why/{o['rank']}":
                continue
            line, notes = expected_field(o["facility_id"])
            f = o.get("field")
            if line is None and not notes:
                errs += [f"{screen}: option {i} has field lines without reports"] if f else []
                continue
            texts = [shown.get(f"options.{i}.field.lines.{j}.en", "") for j in range(len(f["lines"]))]
            head, parts, tail = line
            first = texts[0].removeprefix("Simulated for the demo: ")
            if not (first.startswith(head) and first.endswith(tail) and all(x in first for x in parts)):
                errs.append(f"{screen}: option {i} line {first!r}, expected {head}{parts}{tail}")
            nshown = [shown.get(f"options.{i}.field.notes.{j}.en", "") for j in range(len(f["notes"]))]
            for (n, when), text in zip(notes, nshown, strict=True):
                want = f"{n} report{'s' if n > 1 else ''} of "
                if not (text.startswith(want) and f"latest {when}." in text):
                    errs.append(f"{screen}: option {i} note {text!r}, expected {n} reports, latest {when}")
            # The Hindi line (shown on the Hindi screen) carries the same numbers as the English one shown here.
            for j in range(len(f["lines"])):
                en = shown.get(f"options.{i}.field.lines.{j}.en", "")
                hi = f["lines"][j]["hi"]
                if sorted(re.findall(r"\d+", en)) != sorted(re.findall(r"\d+", hi)):
                    errs.append(f"{screen}: option {i} line {j}: Hindi numbers differ from English")
            seen += 1
    disagree = [o for o in payload["options"] if (o.get("field") or {}).get("disagree")]
    assert disagree and all(o["call_first"] and o["band"] != "unlikely" for o in disagree)
    assert seen >= 3, f"field lines checked on only {seen} cards"
    assert not errs, "\n".join(errs[:40])

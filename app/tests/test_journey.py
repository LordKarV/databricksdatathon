"""Family journey card (journey.js): built under node from real plans (derived/v1, when app/facts/out is built)
and stub plans. The card goes to a family phone, so Safety 13 applies: no patient data, no origin point, no
confidence numbers or band codes, and every name, phone and number on it equals the payload."""
import html as htmllib
import json
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from stub_data import recommend_stub  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
NOW = 1_795_000_000_000
PROBABILITY = re.compile(r"(?<![\d.])0\.\d")
BAND_CODES = re.compile(r"not_verified|\b(un)?likely\b|not verified", re.I)
URL = re.compile(r"https?://[^\s\"'<>]+")
OSM = "https://www.openstreetmap.org/?mlat="
MAP_HREF = re.compile(r'href="(?:geo:|https://www\.openstreetmap\.org/)[^"]*"')
TEMPLATE_NUMBERS = {"108", "102", "24", "7", "1", "16"}  # 108/102 lines, "24x7", Hindi stop list, OSM zoom
REAL = {"gaya_dialysis_route": ("dialysis", 24.79, 85.0),
        "aurangabad_csection": ("emergency_csection", 19.88, 75.34),
        "mohania_trauma_route": ("trauma_emergency", 25.15, 83.68)}


def plans() -> dict:
    out = {f"stub_{s}": recommend_stub(s, 26.6, 85.48, 40, "gps") for s in ("dialysis", "emergency_csection")}
    from facts.engine import Engine
    from itinerary import attach
    eng = Engine.load()
    if eng is not None:
        out.update({n: attach(eng.plan(s, la, lo, 40, "gps"), eng) for n, (s, la, lo) in REAL.items()})
    return out


@lru_cache(maxsize=1)
def run() -> tuple[dict, dict]:
    ps = plans()
    res = subprocess.run(["node", str(APP / "tests" / "journey_harness.mjs")],
                         input=json.dumps({"plans": ps, "now": NOW}), capture_output=True, text=True, check=True)
    return ps, json.loads(res.stdout)


def get(obj, path: str):
    for k in path.split("."):
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj


def cards():
    ps, out = run()
    for name, by_lang in out["cards"].items():
        for lang, card in by_lang.items():
            yield name, lang, ps[name], card


def payload_phones(plan: dict) -> set[str]:
    rows = list(plan["options"])
    for r in (plan.get("itinerary") or {}).get("plans") or []:
        rows += r["stops"]
    return {r["phone"]["e164"] for r in rows if r.get("phone") and r["phone"].get("e164")}


def visible_unmarked(page: str) -> str:
    """Card text outside the payload-marked spans, scripts and style."""
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S)
    page = re.sub(r"<span data-(?:f|device)\b[^>]*>.*?</span>", " ", page, flags=re.S)
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", page))


def test_real_plans_are_covered():
    names = set(run()[0])
    if not any(n in names for n in REAL):
        pytest.skip("app/facts/out not built: real plans not checked")
    assert set(REAL) <= names


def test_size_and_no_external_requests():
    for name, lang, _, card in cards():
        page = card["html"]
        assert len(page.encode()) < 30_000, (name, lang, len(page.encode()))
        assert all(u.startswith(OSM) for u in URL.findall(page)), (name, URL.findall(page))
        for banned in ("src=", "<link", "url(", "@import", "fetch(", "XMLHttpRequest", "localStorage"):
            assert banned not in page, (name, banned)
        assert "default-src 'none'" in page


def test_no_patient_data_confidence_or_band_codes():
    for name, lang, plan, card in cards():
        loc = plan["location"]
        say = json.loads(re.search(r'<script type="application/json" id="say">(.*?)</script>', card["html"]).group(1))
        spoken = " ".join(say["en"] + say.get("hi", []))
        for out in (card["html"], card["text"], spoken):
            assert not PROBABILITY.search(out), (name, lang, PROBABILITY.search(out))
            assert not BAND_CODES.search(out), (name, lang, BAND_CODES.search(out))
            no_maps = URL.sub(" ", MAP_HREF.sub(" ", out))
            for v in (loc["lat"], loc["lon"]):
                assert str(v) not in no_maps, (name, lang, "origin point on the card")
            for word in ("origin", "accuracy", "gps", "%"):
                assert word not in no_maps.lower(), (name, lang, word)


def test_every_shown_value_equals_the_payload():
    for name, lang, plan, card in cards():
        page = card["html"]
        marks = re.findall(r'<span data-f="([^"]+)"[^>]*>(.*?)</span>', page, flags=re.S)
        assert marks, name
        for path, shown in marks:
            assert path in card["fields"], (name, path)
            assert htmllib.unescape(shown) == str(get(plan, path)), (name, lang, path)
        for path in card["fields"]:
            v = get(plan, path)
            assert v not in (None, ""), (name, path)
            if path.endswith((".lat", ".lon")):
                assert str(v) in page, (name, path)
        stray = set(re.findall(r"\d+", visible_unmarked(page))) - TEMPLATE_NUMBERS
        assert not stray, (name, lang, stray)


def test_phones_and_map_points_come_from_the_payload():
    for name, lang, plan, card in cards():
        page = card["html"]
        tels = set(re.findall(r'href="tel:([^"]+)"', page))
        assert "108" in tels, name
        assert ("102" in tels) == any(n["number"] == "102" for n in plan["emergency_numbers"]), name
        assert tels - {"108", "102"} <= payload_phones(plan), (name, tels)
        points = {(o["lat"], o["lon"]) for o in plan["options"]}
        for lat, lon in re.findall(r"mlat=([\d.]+)&amp;mlon=([\d.]+)", page):
            assert (float(lat), float(lon)) in points, (name, lat, lon)
        assert len(re.findall(r'href="geo:', page)) == page.count(OSM), name
        say = json.loads(re.search(r'id="say">(.*?)</script>', page).group(1))
        spoken = [d.replace(" ", "") for d in re.findall(r"\d(?: \d){4,}", " ".join(say["en"] + say.get("hi", [])))]
        digits = {re.sub(r"\D", "", p) for p in payload_phones(plan)}
        assert all(any(d.endswith(s) for d in digits) for s in spoken), (name, spoken)


def test_required_content_and_route_order():
    for name, lang, plan, card in cards():
        page, text = card["html"], card["text"]
        for needed in (plan["as_of"], "Aadhaar", "Ayushman", "MCP", 'id="read"', 'id="big"', "@media print",
                       'aria-live="polite"', f'lang="{lang}"'):
            assert needed in page, (name, lang, needed)
        if lang == "en":
            disclaimer = "This is not a medical opinion; information may be out of date."
            assert disclaimer in page and disclaimer in text
            assert "Call before you go" in page
        else:
            assert "(Hindi draft" not in page and "यात्रा" in page  # UI2: one language, no English draft line
        route = (plan.get("itinerary") or {}).get("plans")
        names = [s["name"] for s in route[0]["stops"]] if route else []
        if len(dict.fromkeys(names)) > 1:
            pos = [page.index(htmllib.escape(n, quote=False)) for n in dict.fromkeys(names)]
            assert pos == sorted(pos), (name, "stops out of order")
            for s in route[0]["stops"]:
                assert htmllib.escape(s["question"], quote=False) in page, (name, s["question"])
        else:
            o = plan["options"][0]
            assert o["name"] in text and all(q["question"] in text for q in o["call_ahead"]), name


def test_share_uses_web_share_then_falls_back_to_download():
    share = run()[1]["share"]
    assert share["shareResult"] == "shared"
    assert share["shared"]["type"] == "text/html" and share["shared"]["name"].startswith("journey-card-")
    assert share["shared"]["name"].endswith(".html") and share["shared"]["size"] > 1000
    assert share["downloadResult"] == "downloaded" and share["downloaded"]["name"].endswith(".html")


def test_a_likely_option_that_reports_disagree_with_says_call_first():
    plan = recommend_stub("dialysis", 26.6, 85.48, 40, "gps")
    first = plan["options"][0]
    assert first["band"] == "likely"
    flagged = {**plan, "itinerary": None,
               "options": [{**first, "field": {"disagree": True}}, *plan["options"][1:]]}
    plain = {**plan, "itinerary": None}
    res = subprocess.run(["node", str(APP / "tests" / "journey_harness.mjs")], capture_output=True, text=True,
                         check=True, input=json.dumps({"plans": {"plain": plain, "flagged": flagged}, "now": NOW}))
    cards = json.loads(res.stdout)["cards"]
    assert "Listed for this service" in cards["plain"]["en"]["text"]
    for c in (cards["flagged"]["en"]["text"], cards["flagged"]["en"]["html"]):
        assert "Listed for this service" not in c and "Call first to check" in c

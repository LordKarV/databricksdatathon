"""Change location by typed place (#121 bug 5): POST /api/place and the Change location screen.

The unit tests use synthetic tables. The API tests use the built facts (skip when app/facts/build.py has not run).
The browser tests run Chromium against a real server with no saved pack, so names and PINs must resolve online.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from facts.places import Places, pin_of

import app as app_module

client = TestClient(app_module.app)
built = app_module._engine() is not None and app_module.PLACES.is_file()
needs_data = pytest.mark.skipif(not built, reason="facts or places not built (app/facts/build.py)")

PINS = {"pin": [271801, 271802, 848125], "lat": [27.5, 27.7, 25.86], "lon": [81.5, 81.6, 85.78],
        "district": ["BAHRAICH", "BAHRAICH", "SAMASTIPUR"], "state": ["UTTAR PRADESH", "UTTAR PRADESH", "BIHAR"]}
GAZ = {"v": 1, "kinds": ["city", "office"], "states": ["BIHAR", "GUJARAT", "UTTAR PRADESH"],
       "name": ["patna", "pusa", "rampur", "patna", "bahraich"], "s": [0, 0, 0, 1, 2], "k": [0, 1, 1, 1, 1],
       "lat": [25.6, 25.86, 25.5, 21.9, 27.57], "lon": [85.1, 85.78, 86.0, 73.5, 81.6]}


@pytest.fixture
def places() -> Places:
    return Places(PINS, GAZ)


def test_pin_resolves_to_its_centroid(places):
    [m] = places.lookup("848125")
    assert (m["lat"], m["lon"], m["kind"]) == (25.86, 85.78, "pin")
    assert m["label"] == "PIN 848125, Samastipur, Bihar"
    assert places.lookup("999999") == []


# How a PIN gets typed or pasted (matrix cluster normalise_pin_format): India Post prints "848 125".
PIN_FORMS = ["848125", "848 125", "848-125", "  848125  ", "PIN 848125", "pin: 848125", "Pin-848125", "PIN 848 125",
             "pincode 848125", "Pin Code: 848125", "848125.", "PIN 848125,", "\u092a\u093f\u0928 848125",
             "\u092a\u093f\u0928 \u0915\u094b\u0921: 848125"]
NOT_PINS = ["84812", "8481250", "848125 848126", "PIN", "pin 848125 bihar", "848125x", "26.59 85.48", "-848125",
            "848.125", "\u096e\u096a\u096e\u0967\u0968\u096b", "spin 848125"]


@pytest.mark.parametrize("q", PIN_FORMS)
def test_typed_pin_forms_resolve_to_the_same_pin(places, q):
    assert pin_of(q) == "848125"
    [m] = places.lookup(q)
    assert m["label"] == "PIN 848125, Samastipur, Bihar" and (m["lat"], m["lon"]) == (25.86, 85.78)


@pytest.mark.parametrize("q", NOT_PINS)
def test_text_that_is_not_exactly_six_digits_is_not_a_pin(q):
    assert pin_of(q) is None


def test_district_beats_post_office_of_the_same_name_and_state(places):
    [m] = places.lookup("  bahraich DISTRICT ")
    assert m["kind"] == "district" and m["label"] == "Bahraich district centre, Uttar Pradesh"
    assert (m["lat"], m["lon"]) == (27.6, 81.55)  # mean of its PIN centroids, as offline.js districtCentre


def test_post_office_names_the_nearest_pin_district(places):
    [m] = places.lookup("Pusa")
    assert m["kind"] == "post_office" and m["label"] == "Pusa post office area, Samastipur, Bihar"


def test_same_name_in_two_states_gives_both_town_first_and_state_filter(places):
    assert [m["state"] for m in places.lookup("Patna")] == ["Bihar", "Gujarat"]
    assert places.lookup("Patna")[0]["kind"] == "town"
    assert [m["state"] for m in places.lookup("patna, gujarat")] == ["Gujarat"]


@pytest.mark.parametrize("q", ["xqzv plonk", "", ",", "   "])
def test_nonsense_finds_nothing(places, q):
    assert places.lookup(q) == []


def test_without_places_file_pins_and_districts_still_work():
    p = Places(PINS, None)
    assert p.lookup("Bahraich")[0]["kind"] == "district" and p.lookup("Pusa") == []


@needs_data
@pytest.mark.parametrize("q, kind, label", [
    ("Bahraich", "district", "Bahraich district centre, Uttar Pradesh"),
    ("Pusa", "post_office", "Pusa post office area, Samastipur, Bihar"),
    ("848125", "pin", "PIN 848125, Samastipur, Bihar"),
])
def test_api_resolves_names_and_pins_without_a_pack(q, kind, label):
    r = client.post("/api/place", json={"q": q})
    assert r.status_code == 200
    m = r.json()["matches"][0]
    assert (m["kind"], m["label"]) == (kind, label)
    assert 6 <= m["lat"] <= 37.5 and 68 <= m["lon"] <= 97.5


@needs_data
def test_api_nonsense_is_404_with_no_matches():
    r = client.post("/api/place", json={"q": "xqzv plonk"})
    assert r.status_code == 404 and r.json() == {"error": "place not found", "matches": []}


def test_api_rejects_bad_bodies_without_echoing_them():
    for body in ({"q": ""}, {"q": "x" * 81}, {"q": "Pusa", "lat": 1}):
        r = client.post("/api/place", json=body)
        assert r.status_code == 422 and "x" * 81 not in r.text


def test_plan_accepts_the_place_source():
    # 422 would mean the source was refused; without built facts the server answers 503 instead.
    r = client.post("/api/plan", json={"service": "dialysis", "lat": 25.86, "lon": 85.78, "source": "place"})
    assert r.status_code in (200, 503)


# ---------- Change location screen in Chromium ----------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    if not built:
        pytest.skip("facts or places not built (app/facts/build.py)")
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
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


LABEL = "PIN, district, town or post office, or 'lat, lon'"


def _change(browser, base_url, **ctx_args):
    ctx = browser.new_context(service_workers="block", **ctx_args)
    page = ctx.new_page()
    page.goto(base_url + "/#/change")
    page.get_by_label(LABEL).wait_for()
    return ctx, page


def _type(page, q: str) -> None:
    page.get_by_label(LABEL).fill(q)
    page.get_by_role("button", name="Use this place").click()


@pytest.mark.parametrize("q, shown", [("Bahraich", "Bahraich district centre, Uttar Pradesh"),
                                      ("Pusa", "Pusa post office area, Samastipur, Bihar"),
                                      ("848125", "PIN 848125, Samastipur, Bihar")])
def test_typed_place_works_online_with_no_saved_pack(browser, base_url, q, shown):
    ctx, page = _change(browser, base_url)
    try:
        assert page.evaluate("localStorage.getItem('rs.pack')") is None
        _type(page, q)
        page.wait_for_function("location.hash === '#/'")
        page.get_by_text(shown).wait_for()
        loc = page.evaluate("JSON.parse(localStorage.getItem('rs.loc'))")
        assert loc["label"] == shown and loc["source"] in {"pin", "district", "place"}
    finally:
        ctx.close()


def test_offline_pin_parse_matches_the_server(browser, base_url):
    """app.js pinOf() reads a PIN for the saved-pack path; it must accept and refuse exactly what pin_of() does."""
    ctx, page = _change(browser, base_url)
    try:
        got = page.evaluate("qs => qs.map(pinOf)", PIN_FORMS + NOT_PINS)
        assert got == [pin_of(q) for q in PIN_FORMS + NOT_PINS]
    finally:
        ctx.close()


@pytest.mark.parametrize("q", ["848 125", "PIN 848125"])
def test_typed_pin_with_space_or_prefix_works_online(browser, base_url, q):
    ctx, page = _change(browser, base_url)
    try:
        _type(page, q)
        page.wait_for_function("location.hash === '#/'")
        assert page.evaluate("JSON.parse(localStorage.getItem('rs.loc')).label") == "PIN 848125, Samastipur, Bihar"
    finally:
        ctx.close()


def test_nonsense_says_what_to_type(browser, base_url):
    ctx, page = _change(browser, base_url)
    try:
        _type(page, "xqzv plonk")
        err = page.locator("#place-err")
        err.get_by_text("No PIN, district, town or post office called").wait_for()
        assert page.get_by_label(LABEL).get_attribute("aria-invalid") == "true"
        assert page.evaluate("location.hash") == "#/change"
    finally:
        ctx.close()


def test_common_name_offers_a_choice(browser, base_url):
    ctx, page = _change(browser, base_url)
    try:
        _type(page, "Patna")
        page.get_by_role("button", name="Patna town, Bihar").click()
        page.wait_for_function("location.hash === '#/'")
        assert page.evaluate("JSON.parse(localStorage.getItem('rs.loc')).source") == "place"
    finally:
        ctx.close()


def test_offline_without_pack_says_what_is_needed(browser, base_url):
    ctx, page = _change(browser, base_url)
    try:
        ctx.set_offline(True)
        _type(page, "Bahraich")
        page.locator("#place-err").get_by_text("no place data is saved on this phone yet").wait_for()
        _type(page, "26.59, 85.48")  # coordinates still work offline
        page.wait_for_function("location.hash === '#/'")
    finally:
        ctx.close()


def test_gps_denied_puts_typing_first(browser, base_url):
    ctx = browser.new_context(service_workers="block")  # no geolocation permission granted
    page = ctx.new_page()
    try:
        page.add_init_script("""navigator.geolocation.getCurrentPosition = (ok, fail) =>
          setTimeout(() => fail({code: 1, message: 'denied'}), 10);""")
        page.goto(base_url + "/")
        page.get_by_role("button", name="Use my location (GPS)").click()
        page.wait_for_function("location.hash === '#/change'")
        page.get_by_text("GPS is blocked for this site").wait_for()
        # The typed-place field comes before the GPS retry.
        order = page.evaluate("""() => {
          const f = document.getElementById('place'), g = document.getElementById('back-gps');
          return !!(f.compareDocumentPosition(g) & Node.DOCUMENT_POSITION_FOLLOWING); }""")
        assert order
        # Back on home with no location: 'Type a place' is the first action, GPS the retry.
        page.get_by_role("link", name="Cancel").click()
        page.get_by_role("link", name="Type a place").wait_for()
        first = page.locator("#main .btn").first
        assert first.inner_text().strip() == "Type a place"
        page.get_by_role("button", name="Use my location (GPS)").wait_for()
    finally:
        ctx.close()

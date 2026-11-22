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

import pandas as pd
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
    # its own PIN nearest the mean of its PIN points; two PINs tie, so the lower PIN (as offline.js districtCentre)
    assert (m["lat"], m["lon"]) == (27.5, 81.5)


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


# ---------- old names and near spellings (matrix cluster spelling_variant_not_found) ----------
VARIANT_GAZ = {"v": 1, "kinds": ["city", "office"], "states": ["HARYANA", "MAHARASHTRA", "UTTAR PRADESH"],
               "name": ["mumbai", "gurgaon", "saharanpur", "saharanpir", "sitapur"], "s": [1, 0, 2, 2, 2],
               "k": [0, 0, 0, 1, 0], "lat": [19.07, 28.46, 29.96, 29.9, 27.57],
               "lon": [72.87, 77.03, 77.55, 77.5, 80.68]}


@pytest.fixture
def variants() -> Places:
    return Places(PINS, VARIANT_GAZ)


def test_exact_names_are_not_touched_by_the_fallbacks(variants):
    matches, matched_as = variants.resolve("Bahraich")
    assert matched_as is None and all("matched_as" not in m for m in matches)
    assert variants.resolve("848125")[1] is None and variants.resolve("999999") == ([], None)


@pytest.mark.parametrize("q, name", [("Bombay", "Mumbai"), ("Gurugram", "Gurgaon")])  # either name finds the other
def test_an_official_rename_finds_the_name_in_our_tables(variants, q, name):
    [m], matched_as = variants.resolve(q)
    assert matched_as == {"query": q.lower(), "name": name, "how": "rename"} == m["matched_as"]
    assert m["label"] == f"{name} town, {m['state']}"


def test_a_near_spelling_finds_the_one_close_name(variants):
    [m], matched_as = variants.resolve("Baharaich")
    assert m["label"] == "Bahraich district centre, Uttar Pradesh"
    # "query" is the name as norm() read it: /api/place never echoes the typed text itself
    assert matched_as == {"query": "baharaich", "name": "Bahraich", "how": "spelling"}
    assert variants.resolve("Baharaich, Bihar") == ([], None)  # the state filter still applies


def test_a_near_miss_between_two_real_places_offers_both_never_one(variants):
    # 'saharanpar' is one letter from Saharanpur and from Saharanpir (0.9 each): both are offered, neither picked
    matches, matched_as = variants.resolve("Saharanpar")
    assert matched_as is None
    assert sorted(m["matched_as"]["name"] for m in matches) == ["Saharanpir", "Saharanpur"]
    assert {m["matched_as"]["how"] for m in matches} == {"spelling"}


@pytest.mark.parametrize("q", ["Sitapor zz", "Ptna", "Xitapur", "Bmbay", "xqzv plonk"])
def test_far_short_or_other_first_letter_spellings_find_nothing(variants, q):
    assert variants.resolve(q) == ([], None)


# Simla is also a post office in Assam; Bijapur is a district of Chhattisgarh and the old name of Vijayapura
OLD_NAME_PINS = {"pin": [494444, 494445], "lat": [18.8, 18.9], "lon": [80.8, 80.9], "district": ["BIJAPUR"] * 2,
                 "state": ["CHHATTISGARH"] * 2}
OLD_NAME_GAZ = {"v": 1, "kinds": ["city", "office"],
                "states": ["ANDHRA PRADESH", "ASSAM", "HIMACHAL PRADESH", "KARNATAKA", "ODISHA"],
                "name": ["simla", "shimla", "vijayapura", "visakhapatnam", "bijapur"], "s": [1, 2, 3, 0, 4],
                "k": [1, 0, 0, 0, 1], "lat": [26.3, 31.1, 16.83, 17.69, 19.9], "lon": [91.0, 77.17, 75.71, 83.22, 83.2]}


@pytest.fixture
def old_names() -> Places:
    return Places(OLD_NAME_PINS, OLD_NAME_GAZ)


def test_an_old_name_that_is_also_a_place_offers_the_renamed_place_first_and_keeps_its_own(old_names):
    matches, matched_as = old_names.resolve("Simla")
    assert [m["label"] for m in matches] == ["Shimla town, Himachal Pradesh", "Simla post office area, Bijapur, Assam"]
    assert matches[0]["matched_as"] == {"query": "simla", "name": "Shimla", "how": "rename"}
    assert "matched_as" not in matches[1] and matched_as is None
    # the new name never pulls in places that only carry the old one
    assert [m["label"] for m in old_names.resolve("Shimla")[0]] == ["Shimla town, Himachal Pradesh"]


def test_vizag_is_visakhapatnam(old_names):
    [m], matched_as = old_names.resolve("Vizag")
    assert m["label"] == "Visakhapatnam town, Andhra Pradesh"
    assert matched_as == {"query": "vizag", "name": "Visakhapatnam", "how": "rename"}


def test_bijapur_is_never_sent_to_vijayapura(old_names):
    # Bijapur is today's name of a Chhattisgarh district: exact matches only, every state that has one, never one
    matches, matched_as = old_names.resolve("Bijapur")
    assert [m["label"] for m in matches] == ["Bijapur district centre, Chhattisgarh",
                                             "Bijapur post office area, Bijapur, Odisha"]
    assert matched_as is None and all("matched_as" not in m for m in matches)
    assert all(m["state"] != "Karnataka" for m in matches)


@needs_data
@pytest.mark.parametrize("q, name, how", [("Bombay", "Mumbai", "rename"), ("Alleppey", "Alappuzha", "rename"),
                                          ("Baharaich", "Bahraich", "spelling"), ("Calcutta", "Kolkata", "rename")])
def test_api_says_which_name_it_shows(q, name, how):
    r = client.post("/api/place", json={"q": q})
    assert r.status_code == 200 and r.json()["matched_as"] == {"query": q.lower(), "name": name, "how": how}
    assert q not in r.text
    assert "matched_as" not in client.post("/api/place", json={"q": name}).json()


@needs_data
def test_api_bijapur_is_the_chhattisgarh_district_and_simla_offers_shimla():
    b = client.post("/api/place", json={"q": "Bijapur"}).json()["matches"]
    assert b[0]["label"] == "Bijapur district centre, Chhattisgarh" and len(b) > 1
    assert not any("Vijayapura" in m["label"] for m in b)
    s = client.post("/api/place", json={"q": "Simla"}).json()["matches"]
    assert s[0]["label"] == "Shimla town, Himachal Pradesh" and s[0]["matched_as"]["how"] == "rename" and len(s) > 1


# ---------- PINs the gazetteer files under no district (matrix cluster pin_missing_from_facts) ----------

def test_fill_districts_takes_the_nearest_pin_of_the_same_state_and_never_invents_one():
    from facts.build import fill_districts
    g = pd.DataFrame({
        "pin": [1, 2, 3, 4, 5, 6],
        "state": ["HARYANA", "HARYANA", "DELHI", "HARYANA", "GOA", "HARYANA"],
        "district": ["FARIDABAD", "GURGAON", "SOUTH", None, None, None],
        "districts": [["FARIDABAD"], ["GURGAON"], ["SOUTH"], [], None, ["PALWAL"]],
        "lat": [28.40, 28.46, 28.39, 28.39, 15.5, 28.1], "lon": [77.30, 77.03, 77.25, 77.26, 73.8, 77.3]})
    f = fill_districts(g).set_index("pin")
    # PIN 4 is nearer the Delhi PIN, but only a Haryana district may be given to a Haryana PIN
    assert (f.loc[4, "district"], f.loc[4, "district_from"]) == ("FARIDABAD", "nearest_pin")
    assert pd.isna(f.loc[5, "district"])  # no Goa PIN has a district: it stays out rather than get a made-up one
    assert (f.loc[6, "district"], f.loc[6, "district_from"]) == ("PALWAL", "gazetteer_list")
    assert list(f.loc[[1, 2, 3], "district_from"]) == ["", "", ""]


def test_fill_districts_scales_longitude_by_cos_lat():
    from facts.build import fill_districts
    # at 60 degrees 1 degree of longitude is half a degree of latitude: B (0.8 deg east) is nearer than A (0.5 north)
    g = pd.DataFrame({"pin": [1, 2, 3], "state": ["S"] * 3, "district": ["A", "B", None], "districts": [None] * 3,
                      "lat": [60.5, 60.0, 60.0], "lon": [10.0, 10.8, 10.0]})
    assert fill_districts(g).district.iloc[2] == "B"


def test_guessed_district_pin_resolves_without_claiming_its_district():
    pins = {k: v + extra for (k, v), extra in zip(PINS.items(), ([848101], [25.9], [85.7], ["SAMASTIPUR"], ["BIHAR"]),
                                                   strict=True)}
    pins["district_from"] = ["", "", "", "nearest_pin"]
    p = Places(pins, None)
    [m] = p.lookup("848101")
    assert m["label"] == "PIN 848101, Bihar" and (m["district"], m["district_from"]) == ("Samastipur", "nearest_pin")
    # the district centre stays the mean of the PINs filed there, as the offline pack computes it
    [d] = p.lookup("Samastipur")
    assert (d["lat"], d["lon"]) == (25.86, 85.78)
    assert "district_from" not in p.lookup("848125")[0]
    # typed as India Post prints it, the label still shows the six digits, never the typed text
    assert [m["label"] for m in p.lookup("PIN 848 101")] == ["PIN 848101, Bihar"]


@needs_data
def test_api_pin_with_no_gazetteer_district_resolves():
    r = client.post("/api/place", json={"q": "121999"})
    assert r.status_code == 200
    [m] = r.json()["matches"]
    assert m["label"] == "PIN 121999, Haryana" and m["district_from"] == "nearest_pin" and m["state"] == "Haryana"


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
    assert r.status_code == 404 and r.json().items() >= {"error": "place not found", "matches": []}.items()
    assert r.json()["code"] == "place_not_found"


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
    page.add_init_script("localStorage.setItem('rs.lang', '\"en\"')")  # UI2 asks for a language on first launch
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
    page.add_init_script("localStorage.setItem('rs.lang', '\"en\"')")  # UI2 asks for a language on first launch
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
        first = page.locator("#main section[aria-labelledby=h-where] .btn").first  # UI2: the 108 row sits above it
        assert first.inner_text().strip() == "Type a place"
        page.get_by_role("button", name="Use my location (GPS)").wait_for()
    finally:
        ctx.close()

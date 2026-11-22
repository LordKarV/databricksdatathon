"""A reload on #/plan must leave the service tiles working (#140).

After a plan the hash is #/plan. A reload drops the plan and the service from memory, so the home screen shows while
the hash stays #/plan; a tile tap then set the same hash, no hashchange fired, and nothing happened. The boot now
puts a bare #/plan back to #/ and pickService routes directly when the hash is already #/plan.
Runs in Chromium against a real server with /api/plan answered from the stub; skips when Playwright is missing.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from stub_data import recommend_stub  # noqa: E402, RUF100

SERVICE, LAT, LON = "trauma_emergency", 24.79, 85.0  # Gaya
PLAN = recommend_stub(SERVICE, LAT, LON, 40, "gps")
PLAN_SHOWN = "() => location.hash === '#/plan' && document.body.classList.contains('on-plan')" \
             " && !!document.querySelector('#main article.card')"


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


def _page(browser, lang: str, viewport: dict[str, int]):
    ctx = browser.new_context(viewport=viewport, service_workers="block", is_mobile=viewport["width"] < 600)
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.route("**/api/plan", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(PLAN)))
    page.add_init_script(f"localStorage.setItem('rs.lang', '\"{lang}\"');"
                         f"localStorage.setItem('rs.loc', JSON.stringify({{lat: {LAT}, lon: {LON}, accuracy_m: 40,"
                         " source: 'gps', t: Date.now(), label: null}))")
    return ctx, page


def _tap_tile(page) -> None:
    page.locator(f"#main [data-svc={SERVICE}]").first.click()
    page.wait_for_function(PLAN_SHOWN, timeout=5000)


CASES = [("en", {"width": 1280, "height": 800}), ("en", {"width": 360, "height": 640}),
         ("hi", {"width": 360, "height": 640})]


@pytest.mark.parametrize(("lang", "viewport"), CASES, ids=["en-desktop", "en-360x640", "hi-360x640"])
def test_reload_on_plan_then_tile_shows_plan(browser, base_url, lang, viewport):
    ctx, page = _page(browser, lang, viewport)
    try:
        page.goto(base_url + "/#/")
        _tap_tile(page)
        page.reload()
        page.wait_for_selector(f"#main [data-svc={SERVICE}]")
        _tap_tile(page)  # dead before the fix: home showed on #/plan and the tap set the same hash
        page.go_back()  # back from the plan goes to home, not to a dead #/plan
        page.wait_for_function("() => location.hash === '#/' && !!document.querySelector('#main [data-svc]')")
        assert page.errors == []
    finally:
        ctx.close()


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_fresh_plan_link_is_normalised_to_home(browser, base_url, lang):
    ctx, page = _page(browser, lang, {"width": 360, "height": 640})
    try:
        page.goto(base_url + "/#/plan")
        page.wait_for_selector(f"#main [data-svc={SERVICE}]")
        assert page.evaluate("location.hash") == "#/"
        _tap_tile(page)
        assert page.errors == []
    finally:
        ctx.close()


def test_tile_on_a_bare_plan_hash_routes_directly(browser, base_url):
    """pickService itself: with the hash already #/plan (no hashchange coming), a tile tap still shows the plan."""
    ctx, page = _page(browser, "en", {"width": 360, "height": 640})
    try:
        page.goto(base_url + "/#/")
        page.wait_for_selector(f"#main [data-svc={SERVICE}]")
        page.evaluate("() => history.replaceState(null, '', '#/plan')")
        page.evaluate(f"() => pickService('{SERVICE}')")
        page.wait_for_function(PLAN_SHOWN, timeout=5000)
        assert page.errors == []
    finally:
        ctx.close()

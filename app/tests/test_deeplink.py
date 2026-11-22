"""Deep links with no plan in memory (#121 bug 6): a reload, a shared #/why/1 link, or an offline answer.

Each must show "Search again to see this option" with a working button, and never throw a page error.
Runs in Chromium against a real server; skips when Playwright is missing.
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

TITLE = "Search again to see this option"
LOC = ("localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
       " source: 'gps', t: Date.now(), label: null}))")


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
                time.sleep(0.2)
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


@pytest.fixture()
def page(browser):
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.add_init_script(LOC + ";localStorage.setItem('rs.lang', '\"en\"');")  # UI2 asks for a language on first launch
    yield pg
    ctx.close()


@pytest.mark.parametrize("link", ["#/why/1", "#/why/1#call", "#/slip/1", "#/slip/3"])
def test_fresh_deep_link_says_search_again(base_url, page, link):
    """A shared link or a reload: no plan and no service in memory, so the button goes to the service tiles."""
    page.goto(f"{base_url}/{link}")
    page.get_by_role("heading", name=TITLE).wait_for()
    assert "Option not found" not in page.inner_text("#main")
    button = page.get_by_role("link", name="Search again")
    assert button.get_attribute("href") == "#/"
    button.click()
    page.wait_for_selector("[data-svc=dialysis]")
    assert page.errors == []


def test_reload_on_why_page_says_search_again(base_url, page):
    plan = recommend_stub("dialysis", 26.6, 85.48, 40, "gps")
    page.route("**/api/plan", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(plan)))
    page.goto(base_url + "/#/")
    page.locator("[data-svc=dialysis]").first.click()
    page.wait_for_selector("article.card")
    page.evaluate("h => { location.hash = h; }", "#/why/1")
    page.wait_for_selector("#how")
    page.reload()
    page.get_by_role("heading", name=TITLE).wait_for()
    assert page.errors == []


def test_offline_answer_then_why_link_never_throws(base_url, page):
    """Offline, the plan in memory is the saved-data answer (no options list): the old code threw reading 'find'."""
    page.goto(base_url + "/#/")
    page.context.set_offline(True)
    page.locator("[data-svc=dialysis]").first.click()
    page.wait_for_function("() => state.plan && state.plan.offline")
    for link in ("#/why/1", "#/slip/1"):
        page.evaluate("h => { location.hash = h; }", link)
        page.get_by_role("heading", name=TITLE).wait_for()
        assert page.get_by_role("link", name="Search again").get_attribute("href") == "#/plan"
    page.get_by_role("link", name="Search again").click()
    page.wait_for_function("() => location.hash === '#/plan'")
    assert page.errors == []

"""#178 post-merge review: the answer never waits on /route.js, a failed /route.js is retried, and the fixed Call bar
steps aside during the call loop (#181), so it never redials an option that just failed."""
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
from stub_data import recommend_stub  # noqa: E402

LOC = ("localStorage.setItem('rs.lang', '\"en\"');"
       "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
       " source: 'gps', t: Date.now(), label: null}));")


@pytest.fixture(scope="module")
def base_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
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
        yield url
    finally:
        proc.terminate()


def plan_with_route() -> dict:
    p = recommend_stub("trauma_emergency", 26.6, 85.48, 40, "gps")
    assert p["options"], "stub plan has no options"
    p["options"][0]["phone"] = {"e164": "+910000000000", "display": "0000 000000", "shared_listings": 1}  # a Call button
    return p


def open_answer(p, base_url, viewport, route_handler=None):
    b = p.chromium.launch()
    page = b.new_context(viewport=viewport, service_workers="block").new_page()
    plan = plan_with_route()
    page.route("**/api/plan", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(plan)))
    if route_handler:
        page.route("**/route.js", route_handler)
    page.add_init_script(LOC)
    page.goto(base_url + "/#/")
    page.locator("[data-svc=trauma_emergency]").first.click()
    return b, page


def test_answer_renders_while_route_js_stalls(base_url):
    pending = []
    with pw.sync_playwright() as p:
        b, page = open_answer(p, base_url, {"width": 360, "height": 780}, lambda r: pending.append(r))  # never answers
        try:
            page.wait_for_selector("article.card .call-main", timeout=5000)
        finally:
            b.close()


def test_failed_route_js_is_retried(base_url):
    calls = []

    def handler(r):
        calls.append(1)
        r.abort() if len(calls) == 1 else r.continue_()
    with pw.sync_playwright() as p:
        b, page = open_answer(p, base_url, {"width": 360, "height": 780}, handler)
        try:
            page.wait_for_selector("article.card")
            page.wait_for_function("() => !document.querySelector('script[src=\"/route.js\"]')")  # the failed tag is gone
            page.evaluate("() => needScripts(['/route.js'])")  # a later call retries and loads it
            page.wait_for_function("typeof routeHtml === 'function'", timeout=5000)
        finally:
            b.close()
    assert len(calls) >= 2, "the failed /route.js was not requested again"


def test_call_bar_steps_aside_during_the_call_loop(base_url):
    with pw.sync_playwright() as p:
        b, page = open_answer(p, base_url, {"width": 320, "height": 568})
        try:
            page.wait_for_selector("article.card .call-main")
            assert page.locator("#call-bar").count() == 1  # a short screen gets the bar
            assert page.get_attribute("#call-bar", "role") == "region" and page.get_attribute("#call-bar", "aria-label")
            page.evaluate("() => { state.call = {plan: state.plan, rank: state.plan.options[0].rank, stage: 'outcome'}; callBar(); }")
            assert page.locator("#call-bar").count() == 0
            page.evaluate("() => { state.call = {plan: state.plan, rank: state.plan.options[0].rank, stage: 'dialing'}; callBar(); }")
            assert page.locator("#call-bar").count() == 1
        finally:
            b.close()

"""#140 cycle 4 and 7: a late /api/plan reply never draws over another screen (B1, A), call outcomes are sent when
storage is blocked (B), and the offline notice follows a language switch (C)."""
from __future__ import annotations

import json

import pytest

from test_call_bar import LOC, base_url, plan_with_route  # noqa: F401  (base_url is the module's app server fixture)

pw = pytest.importorskip("playwright.sync_api")


def named(name: str) -> str:
    p = plan_with_route()
    p["options"][0]["name"] = name
    return json.dumps(p)


def test_a_late_reply_for_another_service_is_dropped(base_url):  # noqa: F811
    held = []

    def plan(r):
        svc = json.loads(r.request.post_data)["service"]
        if svc == "trauma_emergency":
            held.append(r)  # answered only after the C-section reply has shown
        else:
            r.fulfill(status=200, content_type="application/json", body=named("CSECTION-PLACE"))
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 360, "height": 780}, service_workers="block").new_page()
        try:
            page.route("**/api/plan", plan)
            page.add_init_script(LOC)
            page.goto(base_url + "/#/")
            page.locator("[data-svc=trauma_emergency]").first.click()
            for _ in range(50):  # the trauma request is in flight before Back
                if held:
                    break
                page.wait_for_timeout(100)
            assert held, "the trauma request was never sent"
            page.go_back()
            page.wait_for_selector("[data-svc=emergency_csection]")
            page.locator("[data-svc=emergency_csection]").first.click()
            page.wait_for_selector("text=CSECTION-PLACE")
            held[0].fulfill(status=200, content_type="application/json", body=named("TRAUMA-PLACE"))
            page.wait_for_timeout(500)
            assert page.locator("text=TRAUMA-PLACE").count() == 0
            assert page.locator("text=CSECTION-PLACE").count() >= 1
        finally:
            b.close()


def test_outcomes_are_sent_when_storage_is_blocked(base_url):  # noqa: F811
    sent = []
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(service_workers="block").new_page()
        try:
            page.route("**/api/outcome", lambda r: (sent.append(json.loads(r.request.post_data)),
                                                    r.fulfill(status=200, body="{}")))
            page.add_init_script(LOC)
            page.goto(base_url + "/#/")
            page.wait_for_selector("[data-svc=trauma_emergency]")
            page.evaluate("() => { Storage.prototype.setItem = () => { throw new DOMException('full', 'QuotaExceededError'); };"
                          " queueItem({outcome_id: 'a'}); queueItem({outcome_id: 'b'}); }")
            page.wait_for_function("() => true")
            page.wait_for_timeout(500)
        finally:
            b.close()
    assert [x["outcome_id"] for x in sent] == ["a", "b"]


def test_offline_notice_follows_a_language_switch(base_url):  # noqa: F811
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
        page = ctx.new_page()
        try:
            page.add_init_script(LOC)
            page.goto(base_url + "/#/")
            page.wait_for_selector("[data-svc=trauma_emergency]")
            en = page.evaluate("() => ts('off.no_net')")
            ctx.set_offline(True)
            page.locator("[data-svc=trauma_emergency]").first.click()
            page.wait_for_selector(".offline-note")
            assert en in page.inner_text(".offline-note")
            page.click("#lang-btn")
            page.wait_for_function("() => document.documentElement.lang === 'hi'")
            assert en not in page.inner_text(".offline-note")
            assert page.evaluate("() => ts('off.no_net')") in page.inner_text(".offline-note")
        finally:
            b.close()


def test_a_reply_dropped_while_still_waiting_asks_again(base_url):  # noqa: F811
    """The place changes under an in-flight request: its reply is dropped, and the screen asks again for the new
    place instead of showing "Finding..." forever."""
    held, asked = [], []

    def plan(r):
        asked.append(json.loads(r.request.post_data)["lat"])
        if len(asked) == 1:
            held.append(r)
        else:
            r.fulfill(status=200, content_type="application/json", body=named("NEW-PLACE"))
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 360, "height": 780}, service_workers="block").new_page()
        try:
            page.route("**/api/plan", plan)
            page.add_init_script(LOC)
            page.goto(base_url + "/#/")
            page.locator("[data-svc=trauma_emergency]").first.click()
            for _ in range(50):
                if held:
                    break
                page.wait_for_timeout(100)
            page.evaluate("() => { state.loc = {...state.loc, lat: 25.6, lon: 85.1}; }")
            held[0].fulfill(status=200, content_type="application/json", body=named("OLD-PLACE"))
            page.wait_for_selector("text=NEW-PLACE", timeout=5000)
        finally:
            b.close()
    assert len(asked) == 2

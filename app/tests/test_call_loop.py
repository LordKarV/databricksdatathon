"""Call loop on the answer screen (#140 3d), in Chromium against the real server with /api/plan answered from a stub.

The Ask line sits directly under Call: nothing is added above Call, which is near the fold on a window-miss answer.
After a tel: tap, when the page is visible again, the four outcomes appear under the
readout (community.js, loaded on the tel: tap, so the loop is off the critical path). "Said no" or "No answer" shows "Call next: <name>, <minutes>, <band word>" with a focused Call button and
Why, announced in #status. After the last option: 108 (102) and the nearest public hospital. tel: links are not
followed in the browser; the dialler coming and going is a visibilitychange.
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
from stub_data import recommend_stub  # noqa: E402

PHONES = ["+916212230333", "+919470003549", "+916452239202", "+915222300025"]


def plan() -> dict:
    p = recommend_stub("emergency_csection", 26.6, 85.48, 40, "gps")
    for o, e164 in zip(p["options"], PHONES, strict=False):
        o["phone"] = {"e164": e164, "display": e164[3:], "shared_listings": 1}
    p["public_option"] = {"name": "Sadar Hospital Sitamarhi", "label": "District hospital",
                          "travel": {"km": 12.0, "low": 20, "high": 30, "minutes": 25, "method": "osrm",
                                     "label": "road route"}}
    assert len(p["options"]) >= 2 and p["options"][0]["call_ahead"]
    return p


PLAN = plan()
# tel: links stay on the page; the click still reaches app.js's listener (preventDefault does not stop propagation)
NO_DIAL = ("window.addEventListener('click', e => { const a = e.target.closest && e.target.closest('a[href^=\"tel:\"]');"
           " if (a) e.preventDefault(); }, true);")
BACK = """async () => { await new Promise(r => { const t = () => (state.call ? r() : setTimeout(t, 20)); t(); }); Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});
  document.dispatchEvent(new Event('visibilitychange'));
  Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'});
  document.dispatchEvent(new Event('visibilitychange')); }"""


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


def answer(browser, base_url, lang: str):
    ctx = browser.new_context(viewport={"width": 360, "height": 640}, service_workers="block", is_mobile=True)
    page = ctx.new_page()
    sent: list[dict] = []
    page.route("**/api/plan", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(PLAN)))
    page.route("**/api/outcome", lambda r: (sent.append(json.loads(r.request.post_data)),
                                             r.fulfill(status=200, content_type="application/json", body="{}")))
    page.add_init_script(NO_DIAL + f"localStorage.setItem('rs.lang', '\"{lang}\"');"
                         "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
                         " source: 'gps', t: Date.now(), label: null}))")
    page.goto(base_url + "/#/")
    page.locator("[data-svc=emergency_csection]").first.click()
    page.wait_for_selector("article.card .call-main")
    return ctx, page, sent


def test_ask_line_sits_under_call_and_is_marked(browser, base_url):
    ctx, page, _ = answer(browser, base_url, "en")
    try:
        q = PLAN["options"][0]["call_ahead"][0]["question"]
        ask = page.locator(".ask-line")
        assert ask.inner_text().startswith("Ask:") and q in ask.inner_text()
        assert ask.locator("[data-f='options.0.call_ahead.0.question']").inner_text() == q
        under = page.evaluate("() => document.querySelector('.ask-line').getBoundingClientRect().top"
                              " >= document.querySelector('.call-main').getBoundingClientRect().bottom")
        assert under
        assert page.locator("[data-call-out]").count() == 0  # nothing until a call was made
        assert not page.evaluate("() => performance.getEntriesByType('resource').some(r => r.name.endsWith('/community.js'))")
        page.locator(".call-main").click()  # the tap loads the loop
        page.wait_for_function("() => !!window.RSCommunity")
    finally:
        ctx.close()


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_said_no_on_option_1_focuses_call_for_option_2(browser, base_url, lang):
    ctx, page, sent = answer(browser, base_url, lang)
    o1, o2 = PLAN["options"][0], PLAN["options"][1]
    try:
        page.locator(".call-main").click()
        page.evaluate(BACK)
        page.wait_for_selector("#call-loop [data-call-out=no]")
        assert page.locator("#call-loop [data-call-out]").count() == 4
        page.locator("#call-loop [data-call-out=no]").click()
        page.wait_for_selector("#call-next-btn")
        focused = page.evaluate("() => [document.activeElement.id, document.activeElement.getAttribute('href')]")
        assert focused == ["call-next-btn", f"tel:{o2['phone']['e164']}"]
        line = page.locator(".call-next p").first
        assert line.locator("[data-f='options.1.name']").inner_text() == o2["name"]
        assert line.locator("[data-f='options.1.travel.minutes']").inner_text() == str(o2["travel"]["minutes"])
        assert line.locator("[data-f='options.1.band']").count() == 1
        assert page.locator(f".call-next a[href='#/why/{o2['rank']}']").count() == 1
        status = page.locator("#status")
        status.get_by_text(o2["name"]).wait_for()
        prefix = {"en": "Call next:", "hi": "अब यहाँ फ़ोन करें:"}[lang]  # community.js T.callNext
        assert status.inner_text().startswith(prefix) and str(o2["travel"]["minutes"]) in status.inner_text()
        page.locator("#call-reason [data-reason]").first.wait_for()  # the optional reason step, not focused
        page.locator("#call-reason [data-reason='']").click()  # Skip: the "no" goes now
        page.wait_for_function("() => true")
        deadline = time.time() + 5
        while not sent and time.time() < deadline:
            page.wait_for_timeout(100)
        assert [(x["facility_id"], x["outcome"]) for x in sent] == [(o1["facility_id"], "no")]
    finally:
        ctx.close()


def test_after_the_last_option_108_and_the_public_hospital(browser, base_url):
    ctx, page, sent = answer(browser, base_url, "en")
    try:
        page.locator(".call-main").click()
        for k in range(len(PLAN["options"])):
            page.evaluate(BACK)
            page.wait_for_selector("#call-loop [data-call-out=none]")
            page.locator("#call-loop [data-call-out=none]").click()
            if k < len(PLAN["options"]) - 1:
                page.locator("#call-next-btn").click()
        end = page.locator(".call-end")
        end.wait_for()
        assert end.locator("a[href='tel:108']").count() == 1 and end.locator("a[href='tel:102']").count() == 1
        assert end.locator("[data-f='public_option.name']").inner_text() == PLAN["public_option"]["name"]
        assert page.evaluate("() => document.activeElement.getAttribute('href')") == "tel:108"
        page.wait_for_timeout(300)
        assert [x["outcome"] for x in sent] == ["no_answer"] * len(PLAN["options"])
    finally:
        ctx.close()


# Window-miss answers (coordinator, #140): Call is near or below the fold at 360x640 there, so 3d adds nothing above
# it. Real plans from the built facts through the real /api/plan.
WINDOW_MISS = {"gaya_csection": ("emergency_csection", 24.78, 85.0),
               "mohania_csection": ("emergency_csection", 25.15, 83.68),
               "bahraich_burns": ("burn_care", 27.57, 81.6)}
CALL_FOLD_JS = """() => { const b = document.querySelector('#main .call-main'), r = b.getBoundingClientRect();
  const added = [...document.querySelectorAll('#main .ask-line, #call-loop')];
  return {visible: r.top >= 0 && r.bottom <= innerHeight, bottom: Math.round(r.bottom), viewport: innerHeight,
          nothing_above: added.every(n => n.getBoundingClientRect().top >= r.bottom)}; }"""


@pytest.mark.parametrize("case", sorted(WINDOW_MISS))
def test_window_miss_answers_get_nothing_above_call(browser, base_url, case):
    service, lat, lon = WINDOW_MISS[case]
    ctx = browser.new_context(viewport={"width": 360, "height": 640}, service_workers="block", is_mobile=True)
    page = ctx.new_page()
    page.add_init_script("localStorage.setItem('rs.lang', '\"en\"');"
                         f"localStorage.setItem('rs.loc', JSON.stringify({{lat: {lat}, lon: {lon}, accuracy_m: 40,"
                         " source: 'gps', t: Date.now(), label: null}))")
    try:
        page.goto(base_url + "/#/")
        page.locator(f"[data-svc={service}]").first.click()
        page.wait_for_selector("#main .readout, #main [role=alert], #main .offline-note")
        if not page.locator("#main .call-main").count():
            pytest.skip("no answer with a phone here (app/facts/out not built?)")
        page.evaluate("window.scrollTo(0, 0)")
        res = page.evaluate(CALL_FOLD_JS)
        print(f"\n{case}: Call visible at first open: {res['visible']} (bottom {res['bottom']} of {res['viewport']})")
        assert res["nothing_above"], res
    finally:
        ctx.close()


def test_said_yes_offers_the_slip(browser, base_url):
    ctx, page, _ = answer(browser, base_url, "en")
    try:
        page.locator(".call-main").click()
        page.evaluate(BACK)
        page.locator("#call-loop [data-call-out=yes]").click()
        page.locator(f"#call-loop a[href='#/slip/{PLAN['options'][0]['rank']}']").wait_for()
    finally:
        ctx.close()


# The fixed Call bar (#178, screens up to 600 px tall) follows the loop: after "No answer" on option 1 it dials
# option 2, not the number that just failed, and after the last option 108 (102). A later render() keeps it.
BAR_JS = """async () => { const seen = new Set();
  for (let y = 0; y <= document.documentElement.scrollHeight; y += 40) { scrollTo(0, y);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    const b = document.getElementById('call-bar');
    if (b && !b.hidden) seen.add([...b.querySelectorAll('a')].map(a => a.getAttribute('href')).join(' ')); }
  scrollTo(0, 0); return [...seen]; }"""


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_fixed_call_bar_follows_the_loop(browser, base_url, lang):
    ctx, page, _ = answer(browser, base_url, lang)
    o1, o2 = PLAN["options"][0], PLAN["options"][1]
    try:
        page.set_viewport_size({"width": 320, "height": 568})
        page.evaluate("render({keepFocus: true})")  # callBar() builds the bar for the short screen
        assert page.evaluate(BAR_JS) == [f"tel:{o1['phone']['e164']}"]
        page.locator(".call-main").click()
        page.evaluate(BACK)
        page.locator("#call-loop [data-call-out=none]").click()
        page.wait_for_selector("#call-next-btn")
        assert page.evaluate(BAR_JS) == [f"tel:{o2['phone']['e164']}"]
        page.evaluate("render({keepFocus: true})")
        assert page.evaluate(BAR_JS) == [f"tel:{o2['phone']['e164']}"]
        while page.locator("#call-next-btn").count():
            page.locator("#call-next-btn").click()
            page.evaluate(BACK)
            page.locator("#call-loop [data-call-out=none]").click()
        page.locator(".call-end").wait_for()
        assert page.evaluate(BAR_JS) == ["tel:108 tel:102"]
    finally:
        ctx.close()

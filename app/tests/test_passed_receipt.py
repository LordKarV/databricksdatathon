"""UI-PASSED-1 and UI-RECEIPT-1 (#140, lead 15:55Z): two lazy lines at the top of the Why page, by passed.js and
receipt.js. Card 1 gets neither.

- Order at the top of the Why page: the band (and score) row, then the tested-trust line, then "Passed over".
- "Passed over" is on option 1's Why page only: the engine's why_not[0] row, its name, travel km and reason, each
  marked and equal to the payload (Thane dialysis, a real plan, when app/facts/out is built; a stub plan always).
- A plan with first_is_nearest shows the "nothing nearer" line there instead, with no why_not value.
- A Likely option's Why page shows the tested-trust line: k and n equal meta.test_record, with n dots, k of them
  filled; the Why page of an option that is not Likely shows no such line.
Every marked value on the screen is also checked by test_faithfulness's check_screen (no unmarked digit).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_faithfulness as tf
from stub_data import recommend_stub

base_url, browser = tf.base_url, tf.browser  # the same module-scoped server and Chromium fixtures
I18N = tf.I18N
THANE = ("dialysis", 19.16, 72.95)
GAYA_TRAUMA = ("trauma_emergency", 24.7955, 85.0077)
ORDER_JS = """() => { const h = document.querySelector('#main .why-head');
  const kids = [...h.children], at = s => kids.findIndex(e => e.matches(s) || !!e.querySelector(s));
  return {band: at('.band'), tested: at('.tested'), passed: at('.passed')}; }"""


def results_record() -> dict:
    """k and n as the committed sealed TEST results hold them (what build.py copies into meta.test_record)."""
    lk = json.loads((ROOT / "model/gold/v3/test_eval/results.json").read_text())["headline_decided"]["LIKELY_confirmed"]
    return {"k": lk["k"], "n": lk["n"]}


def real_plan(svc: str, lat: float, lon: float) -> dict | None:
    from facts.engine import Engine
    eng = Engine.load()
    return None if eng is None else eng.plan(svc, lat, lon, 40, "gps")


def stub_plan(band: str = "likely", nearest: bool = False) -> dict:
    p = recommend_stub("dialysis", 26.6, 85.48, 40, "gps")
    p["options"][0]["band"] = band
    p["first_is_nearest"] = nearest
    # The whole record, as build.py writes it: the Why page's sealed-test section shows every field of it.
    log = "model/gold/v3/OPENING_LOG.md"
    tr = {"split": "test", **tf.expected_test_record(), "source": "model/gold/v3/test_eval/results.json", "log": log,
          "log_url": f"https://github.com/LordKarV/databricksdatathon/blob/submission/{log}"}
    p["meta"] = {**p["meta"], "test_record": tr}
    return p


def open_plan(browser, base_url, payload: dict, lang: str):
    ctx = browser.new_context(viewport={"width": 360, "height": 780}, service_workers="block")
    page = ctx.new_page()
    page.route("**/api/plan", tf.json_reply(payload))
    page.add_init_script("localStorage.setItem('rs.lang', " + json.dumps(json.dumps(lang)) + ");"
                         "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808, accuracy_m: 40,"
                         " source: 'gps', t: Date.now(), label: null}))")
    page.goto(base_url + "/#/")
    page.locator(f"[data-svc={payload['query']['service']}]").first.click()
    page.wait_for_selector("article.card")
    page.evaluate("() => new Promise(r => setTimeout(r, 100))")
    return ctx, page


def open_why(page, rank: int) -> None:
    page.evaluate("h => { location.hash = h; }", f"#/why/{rank}")
    page.wait_for_selector("#main .why-head")
    page.wait_for_function("typeof RSPassed === 'function' && typeof RSReceipt === 'function'")
    page.evaluate("() => new Promise(r => setTimeout(r, 50))")


def marked(page, sel: str) -> dict[str, str]:
    return page.evaluate("s => Object.fromEntries([...document.querySelectorAll(s + ' [data-f]')]"
                         ".map(e => [e.dataset.f, e.textContent.trim()]))", sel)


def faithful(page, name: str, payload: dict) -> list[str]:
    return tf.check_screen(name, payload, page.evaluate(tf.COLLECT_JS), {"values_checked": 0})


def card_has_neither(page) -> list[str]:
    n = page.evaluate("() => document.querySelectorAll('#main .passed, #main .tested').length")
    return [] if n == 0 else [f"the answer screen shows {n} passed-over or tested lines; card 1 gets neither"]


def check_passed_row(page, name: str, payload: dict) -> list[str]:
    errs = faithful(page, name, payload)
    got = marked(page, "#main .why-head .passed")
    errs += [f"{name}: why_not.0.{f} not on the passed-over line" for f in ("name", "travel.km", "reason")
             if f"why_not.0.{f}" not in got]
    if page.locator("#main .passed").count() != 1:
        errs.append(f"{name}: expected one passed-over line")
    return errs


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_thane_why_page_order_and_passed_over(lang, base_url, browser):
    p = real_plan(*THANE)
    if p is None:
        pytest.skip("app/facts/out not built")
    assert not p["first_is_nearest"] and p["why_not"], "Thane dialysis no longer has a nearer passed-over row"
    assert p["options"][0]["band"] == "likely"
    ctx, page = open_plan(browser, base_url, p, lang)
    try:
        errs = card_has_neither(page)
        open_why(page, p["options"][0]["rank"])
        errs += check_passed_row(page, f"thane/{lang}", p)
        text = page.locator("#main .passed").inner_text()
        order = page.evaluate(ORDER_JS)
    finally:
        ctx.close()
    assert I18N[lang]["passed.over"] in text and p["why_not"][0]["name"] in text
    assert 0 <= order["band"] < order["tested"] < order["passed"], order
    assert not errs, errs[:10]


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_stub_passed_over_line_is_why_not_0(lang, base_url, browser):
    p = stub_plan()
    ctx, page = open_plan(browser, base_url, p, lang)
    try:
        errs = card_has_neither(page)
        open_why(page, p["options"][0]["rank"])
        errs += check_passed_row(page, f"stub/{lang}", p)
        order = page.evaluate(ORDER_JS)
    finally:
        ctx.close()
    assert 0 <= order["band"] < order["tested"] < order["passed"], order
    assert not errs, errs[:10]


def test_passed_over_only_on_option_1(base_url, browser):
    p = stub_plan()
    ctx, page = open_plan(browser, base_url, p, "en")
    try:
        open_why(page, p["options"][1]["rank"])
        n = page.locator("#main .passed").count()
    finally:
        ctx.close()
    assert n == 0


@pytest.mark.parametrize("lang", ["en", "hi"])
@pytest.mark.parametrize("src", ["stub", "gaya_trauma"])
def test_first_is_nearest_shows_nothing_nearer(src, lang, base_url, browser):
    p = stub_plan(nearest=True) if src == "stub" else real_plan(*GAYA_TRAUMA)
    if p is None:
        pytest.skip("app/facts/out not built")
    assert p["first_is_nearest"], f"{src}: first_is_nearest is no longer set"
    ctx, page = open_plan(browser, base_url, p, lang)
    try:
        errs = card_has_neither(page)
        open_why(page, p["options"][0]["rank"])
        text = page.locator("#main .why-head .passed").inner_text().strip()
        got = marked(page, "#main .passed")
        errs += faithful(page, f"nearest-{src}/{lang}", p)
    finally:
        ctx.close()
    assert text == I18N[lang]["passed.none"]
    assert not any(k.startswith("why_not.") for k in got), got
    assert not errs, errs[:10]


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_likely_why_page_shows_the_test_record(lang, base_url, browser):
    p = real_plan(*THANE) or stub_plan()
    tr = p["meta"].get("test_record") or {}
    if not tr:
        pytest.skip("facts export without a TEST record")
    assert p["options"][0]["band"] == "likely"
    assert {k: tr[k] for k in ("k", "n")} == results_record()
    ctx, page = open_plan(browser, base_url, p, lang)
    try:
        errs = card_has_neither(page)
        open_why(page, p["options"][0]["rank"])
        got = marked(page, "#main .why-head .tested")
        dots = page.evaluate("() => { const s = document.querySelector('#main .why-head .tested svg');"
                             " return s && {hidden: s.getAttribute('aria-hidden'), all: s.querySelectorAll(':scope > circle,"
                             " :scope > g').length, filled: s.querySelectorAll(':scope > circle').length}; }")
        errs += faithful(page, f"tested/{lang}", p)
    finally:
        ctx.close()
    assert got == {"meta.test_record.k": str(tr["k"]), "meta.test_record.n": str(tr["n"])}
    assert dots == {"hidden": "true", "all": tr["n"], "filled": tr["k"]}
    assert not errs, errs[:10]


@pytest.mark.parametrize("band", ["not_verified", "unlikely"])
def test_why_page_not_likely_shows_no_test_record(band, base_url, browser):
    p = stub_plan(band=band)
    ctx, page = open_plan(browser, base_url, p, "en")
    try:
        errs = card_has_neither(page)
        open_why(page, p["options"][0]["rank"])
        assert page.locator("#main .tested").count() == 0
        assert page.locator("#main .why-head [data-f^='meta.test_record']").count() == 0
        assert page.locator("#main .why-head .passed").count() == 1  # the passed-over line is not band-gated
    finally:
        ctx.close()
    assert not errs, errs

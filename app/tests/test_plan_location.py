"""#134 (BE-T2): /api/plan answers 422 with a location code when the phone's point is outside India or too rough.

The page then says so in the app language (the server's text, or the strings file when the server sends none), opens
Change location with the typed box focused, and never shows the generic "could not make a plan".
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
I18N = {lang: json.loads((APP / "static" / "i18n" / f"{lang}.json").read_text()) for lang in ("en", "hi")}
KEY = {"location_outside_india": "place.outside_india", "location_too_coarse": "place.too_coarse"}


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


@pytest.mark.parametrize("lang", ["en", "hi"])
@pytest.mark.parametrize("code, server_text", [("location_outside_india", None), ("location_too_coarse", None),
                                                ("location_outside_india", {"en": "Server says outside India.",
                                                                            "hi": "सर्वर: भारत से बाहर।"})])
def test_bad_location_opens_typed_place(base_url, lang, code, server_text):
    body = {"detail": "bad location", "code": code, **({"text": server_text} if server_text else {})}
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 360, "height": 780}, service_workers="block").new_page()
        page.route("**/api/plan", lambda r: r.fulfill(status=422, content_type="application/json",
                                                      body=json.dumps(body, ensure_ascii=False)))
        page.add_init_script(f"localStorage.setItem('rs.lang', '\"{lang}\"');"
                             "localStorage.setItem('rs.loc', JSON.stringify({lat: 51.5, lon: -0.1, accuracy_m: 40,"
                             " source: 'gps', t: Date.now(), label: null}));")
        try:
            page.goto(base_url + "/#/")
            page.locator("[data-svc=dialysis]").first.click()
            page.wait_for_function("location.hash === '#/change'")
            page.wait_for_function("document.activeElement && document.activeElement.id === 'place'")
            shown = page.inner_text("#place-err")
            text = page.inner_text("#main")
        finally:
            b.close()
    want = server_text[lang] if server_text else I18N[lang][KEY[code]]
    assert shown == want
    assert I18N[lang]["err.plan"].split("(")[0].strip() not in text  # never the generic "could not make a plan"

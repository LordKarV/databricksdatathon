"""Faithfulness of the quote translation on the page (translate.js): after "हिंदी में पढ़ें", every quote is still
shown verbatim, the translation sits under it with the label, and the request carries the claim id only.
/api/plan and /api/translate are answered by the test. Needs playwright; skipped without it.
"""
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
from stub_data import recommend_stub

HINDI = "डायलिसिस यूनिट में 10 मशीनें हैं"
LABEL_HI = "मशीन अनुवाद। मूल अंग्रेज़ी ऊपर है और वही सबूत है।"


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


def test_original_quote_stays_verbatim_above_the_translation(base_url):
    plan = recommend_stub("dialysis", 26.6, 85.48, 40, "gps")
    sent = []

    def translate(route):
        sent.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"available": True, "hindi": HINDI}, ensure_ascii=False))

    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 360, "height": 780}, service_workers="block").new_page()
        page.route("**/api/plan", lambda r: r.fulfill(status=200, content_type="application/json",
                                                      body=json.dumps(plan)))
        page.route("**/api/translate", translate)
        page.add_init_script("localStorage.setItem('rs.lang', '\"hi\"');"  # UI2: translate is on Hindi screens
                             "localStorage.setItem('rs.loc', JSON.stringify({lat: 26.5951, lon: 85.4808,"
                             " accuracy_m: 40, source: 'gps', t: Date.now(), label: null}))")
        page.goto(base_url + "/#/")
        page.locator("[data-svc=dialysis]").first.click()
        page.wait_for_selector("article.card")
        page.evaluate("location.hash = '#/why/1'")
        btn = page.get_by_role("button", name="हिन्दी में पढ़ें").first
        btn.wait_for()
        btn.click()
        page.locator(".tr-text").first.wait_for()
        got = page.evaluate("""() => [...document.querySelectorAll('#main blockquote')].map(bq => {
            const q = bq.querySelector('[data-f$=".quote"]'), tr = bq.querySelector('.tr-text');
            return {path: q.dataset.f, quote: q.textContent, translated: !!tr,
                    above: !tr || !!(q.compareDocumentPosition(tr) & Node.DOCUMENT_POSITION_FOLLOWING),
                    label: bq.querySelector('.tr-out').textContent};
        })""")
        b.close()
    ev = plan["options"][0]["evidence"]
    assert [g["quote"] for g in got] == [e["quote"] for e in ev]  # every quote still verbatim
    assert sum(g["translated"] for g in got) == 1 and all(g["above"] for g in got)
    # UI2: the Hindi screen labels the machine translation in Hindi only (one language on screen)
    assert LABEL_HI in got[0]["label"] and "The original English above is the evidence." not in got[0]["label"]
    assert sent == [{"claim_id": ev[0]["claim_id"]}]  # the claim id only, never text

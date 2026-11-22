"""Eight more Indian languages, loaded on demand: each shipped file matches en.json key for key and slot for slot,
and choosing one sets <html lang> (dir=rtl for Urdu). A code whose file is not in app/static/i18n yet is skipped."""
from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
I18N = APP / "static" / "i18n"
NEW = ["ta", "te", "kn", "ml", "bn", "mr", "gu", "ur"]
EN = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
PRESENT = [c for c in NEW if (I18N / f"{c}.json").is_file()]
SLOT = re.compile(r"\{(\w+)\}")


def slots(v: object) -> list[str]:
    return sorted(SLOT.findall(v)) if isinstance(v, str) else []


@pytest.mark.parametrize("code", NEW)
def test_language_file_matches_english(code: str) -> None:
    path = I18N / f"{code}.json"
    if not path.is_file():
        pytest.skip(f"{code}.json not shipped yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) >= set(EN) - {"engine"}, f"{code}: missing {sorted(set(EN) - set(data) - {'engine'})}"
    bad = [k for k in EN if not k.startswith("_") and k != "engine" and slots(EN[k]) != slots(data[k])]
    assert not bad, f"{code}: placeholders differ for {bad}"


def test_every_language_has_a_native_name() -> None:
    names = json.loads((I18N / "hi.json").read_text(encoding="utf-8"))["langs"]
    assert set(names) == {"hi", "en", *NEW} and all(names.values())


@pytest.fixture(scope="module")
def base_url():
    pytest.importorskip("playwright.sync_api")
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


def test_unshipped_language_file_is_404(base_url: str) -> None:
    missing = [c for c in NEW if c not in PRESENT]
    if not missing:
        pytest.skip("every language file is shipped")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"{base_url}/i18n/{missing[0]}.json", timeout=5)
    assert e.value.code == 404


def test_settings_lists_every_language_and_choosing_one_sets_html_lang(base_url: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(service_workers="block").new_page()
        page.add_init_script("localStorage.setItem('rs.lang', '\"en\"');")
        page.goto(base_url + "/#/settings")
        page.wait_for_selector("#lang-ur")
        assert page.locator("input[name=lang]").count() == 10
        assert page.locator("label[lang=ta]").inner_text().startswith("தமிழ்")
        for code in PRESENT:
            page.click(f"label[lang={code}]")
            page.wait_for_function(f"document.documentElement.lang === '{code}'")
            want = "rtl" if code == "ur" else "ltr"
            assert page.evaluate("document.documentElement.dir") == want
        b.close()
    if not PRESENT:
        pytest.skip("no new language file shipped yet; listed names checked only")

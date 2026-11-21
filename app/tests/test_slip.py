"""Referral slip (S8, issue #24): slip.js run under node on stub plans."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from stub_data import recommend_stub  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
NOW = 1_795_000_000_000  # fixed clock for a stable "made" stamp
PROBABILITY = re.compile(r"(?<![\d.])0\.\d")  # confidence decimals such as 0.81 must never appear


def run(service="dialysis", rank=1, outcome=None) -> dict:
    plan = recommend_stub(service, 26.6, 85.48, 40, "gps")
    payload = {"plan": plan, "rank": rank, "outcome": outcome, "now": NOW}
    res = subprocess.run(["node", str(APP / "tests" / "slip_harness.mjs")], input=json.dumps(payload),
                         capture_output=True, text=True, check=True)
    return {"plan": plan, **json.loads(res.stdout)}


def test_english_slip_has_required_content():
    r = run()
    opt, backup = r["plan"]["options"][0], r["plan"]["options"][1]
    text = r["en"]["whatsapp"]["text"]
    for needed in ["dialysis", opt["name"], opt["address"], backup["name"], "108", "24x7 emergency",
                   f"{opt['travel']['low']}-{opt['travel']['high']} min", opt["travel"]["label"],
                   opt["evidence"][0]["quote"], opt["evidence"][0]["source_url"], r["plan"]["as_of"],
                   "more than a day old", "Not checked by phone yet"]:
        assert needed in text, needed
    html = r["en"]["html"]
    for needed in [opt["name"], backup["name"], "24x7 emergency", r["plan"]["as_of"], "write by hand"]:
        assert needed in html, needed
    assert "102" not in text, "102 only for pregnancy and newborn services"


def test_no_patient_data_or_confidence_decimals():
    r = run()
    for lang in ("en", "hi"):
        for out in (r[lang]["html"], r[lang]["whatsapp"]["text"], r[lang]["sms"]["text"]):
            assert not PROBABILITY.search(out), PROBABILITY.search(out)
            assert "26.6,85.48" not in out and "origin=" not in out, "patient location must not appear"
    assert "destination=" in r["en"]["whatsapp"]["text"]


def test_call_outcome_and_102_for_csection():
    r = run(service="emergency_csection", outcome={"said": "Said yes", "at": NOW})
    assert "Said yes on the phone" in r["en"]["whatsapp"]["text"]
    assert "102" in r["en"]["whatsapp"]["text"] and "102" in r["en"]["sms"]["text"]


def test_sms_length_and_links_encoded():
    for service in ("dialysis", "emergency_csection", "trauma_emergency"):
        r = run(service=service)
        for lang in ("en", "hi"):
            sms, wa = r[lang]["sms"], r[lang]["whatsapp"]
            assert len(sms["text"]) <= 300, (service, lang, len(sms["text"]))
            assert sms["url"].startswith("sms:?body=") and " " not in sms["url"]
            assert unquote(sms["url"][len("sms:?body="):]) == sms["text"]
            assert wa["url"].startswith("https://wa.me/?text=") and "\n" not in wa["url"] and " " not in wa["url"]
            assert unquote(wa["url"][len("https://wa.me/?text="):]) == wa["text"]


def test_hindi_is_marked_draft():
    r = run()
    assert "(Hindi draft, not reviewed)" in r["hi"]["html"]
    assert "(Hindi draft, not reviewed)" in r["hi"]["whatsapp"]["text"]
    assert 'lang="hi"' in r["hi"]["html"] and "\u092a\u0930\u094d\u091a\u0940" in r["hi"]["html"]
    assert "(Hindi draft" not in r["en"]["html"]


def test_slip_js_is_served_but_not_on_critical_path():
    from fastapi.testclient import TestClient

    from app import app
    c = TestClient(app)
    assert c.get("/slip.js").status_code == 200
    assert "slip.js" not in c.get("/").text

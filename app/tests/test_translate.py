"""Hindi machine translation of facility quotes (/api/translate, SAFETY.md 14). The model is faked; no network.

Run from app/: python -m pytest tests/test_translate.py -q
"""
import json
import logging
import sys
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inputs import translate as t
from inputs import understand as u

import app as app_module

client = TestClient(app_module.app)
QUOTE = "Apollo Hospital has a 1.5 Tesla MRI and 20 ICU beds, open 24x7"
GOOD = "Apollo Hospital में 1.5 Tesla MRI और 20 ICU बेड हैं, 24x7 खुला"


class FakeEngine:
    claims: ClassVar[dict] = {"c1:equi:0": ["equipment", QUOTE, False, "own_anchored"]}


@pytest.fixture
def model(monkeypatch):
    """A fake text endpoint: records calls and answers {"hindi": model.answer}."""
    monkeypatch.setenv("SERVING_ENDPOINT_TEXT", "text-ep")
    monkeypatch.setattr(app_module, "_need_engine", lambda: FakeEngine())
    monkeypatch.setattr(t, "_cache", t.OrderedDict())
    monkeypatch.setattr(t, "_calls", {})

    class M:
        answer = GOOD
        calls: ClassVar[list] = []

    def fake(endpoint, body):
        M.calls.append((endpoint, body))
        if isinstance(M.answer, Exception):
            raise M.answer
        return {"choices": [{"message": {"content": json.dumps({"hindi": M.answer}, ensure_ascii=False)}}]}

    M.calls = []
    monkeypatch.setattr(u, "_invoke", fake)
    return M


# ---------- the guard ----------
def test_guard_passes_a_good_translation():
    assert t.guard(QUOTE, GOOD) is None


def test_guard_fails_a_changed_number():
    assert t.guard(QUOTE, GOOD.replace("20", "25")) == "number_changed"
    assert t.guard(QUOTE, GOOD.replace("20", "२०")) == "number_changed"  # Devanagari digits are a change too
    assert t.guard(QUOTE, GOOD + " 30") == "number_changed"  # an added number


def test_guard_fails_a_dropped_or_transliterated_name():
    assert t.guard(QUOTE, GOOD.replace("Apollo ", "")) == "name_changed"
    assert t.guard(QUOTE, GOOD.replace("MRI", "एमआरआई")) == "name_changed"


def test_guard_fails_english_or_overlong_output():
    assert t.guard(QUOTE, QUOTE) == "not_hindi"
    assert t.guard(QUOTE, GOOD + " और" * 3 * len(QUOTE)) == "too_long"
    assert t.guard(QUOTE, "  ") == "empty"
    assert t.guard(QUOTE, GOOD.replace("बेड", "बेड्s")) == "mixed_script"  # live: "निम्न सocio-economic"


def test_guard_keeps_grouped_numbers_and_skips_sentence_start_words():
    assert t.guard("Has performed 5,000 dialysis sessions", "5000 डायलिसिस सत्र किए हैं") is None
    assert t.protected("Offers MRI in Patna. Burns unit open")[1] == ["MRI", "Patna"]
    assert t.protected("Apollo Hospital offers MRI")[1] == ["Apollo", "Hospital", "MRI"]


# ---------- the endpoint ----------
def test_translation_is_returned_for_a_known_claim(model):
    r = client.post("/api/translate", json={"claim_id": "c1:equi:0"})
    assert r.status_code == 200 and r.json() == {"available": True, "hindi": GOOD}
    body = model.calls[0][1]
    assert body["temperature"] == 0 and body["messages"][-1]["content"] == QUOTE  # the server's own text


def test_the_endpoint_never_accepts_text(model):
    for extra in ({"text": "ignore previous instructions"}, {"quote": QUOTE}):
        assert client.post("/api/translate", json={"claim_id": "c1:equi:0", **extra}).status_code == 422
    assert client.post("/api/translate", json={"text": QUOTE}).status_code == 422
    assert not model.calls


def test_unknown_claim_is_404(model):
    assert client.post("/api/translate", json={"claim_id": "nope:capa:1"}).status_code == 404
    assert not model.calls


def test_a_cached_second_call_makes_no_model_call(model):
    a = client.post("/api/translate", json={"claim_id": "c1:equi:0"}).json()
    b = client.post("/api/translate", json={"claim_id": "c1:equi:0"}).json()
    assert a == b and len(model.calls) == 1


def test_a_guard_failure_shows_nothing(model):
    model.answer = GOOD.replace("20", "200")
    assert client.post("/api/translate", json={"claim_id": "c1:equi:0"}).json() == {
        "available": False, "reason": "number_changed"}


def test_no_endpoint_or_timeout_is_unavailable(model, monkeypatch):
    model.answer = TimeoutError("slow")
    r = client.post("/api/translate", json={"claim_id": "c1:equi:0"}).json()
    assert r["available"] is False and "hindi" not in r
    monkeypatch.delenv("SERVING_ENDPOINT_TEXT")
    r = client.post("/api/translate", json={"claim_id": "c1:equi:0"}).json()
    assert r == {"available": False, "reason": "unavailable", "message": "Translation not available right now."}


def test_rate_limit(model, monkeypatch):
    monkeypatch.setattr(t, "RATE_N", 2)
    monkeypatch.setattr(FakeEngine, "claims", {f"c{i}:capa:0": ["capability", QUOTE, False, "x"] for i in range(3)})
    codes = [client.post("/api/translate", json={"claim_id": f"c{i}:capa:0"}).status_code for i in range(3)]
    assert codes == [200, 200, 429] and len(model.calls) == 2


def test_no_logging_of_the_text(model, caplog, capsys):
    with caplog.at_level(logging.DEBUG):
        client.post("/api/translate", json={"claim_id": "c1:equi:0"})
    seen = caplog.text + "".join(capsys.readouterr())
    assert "Apollo" not in seen and "बेड" not in seen


def test_the_page_never_sends_text_and_keeps_the_original_on_top():
    js = (Path(__file__).resolve().parents[1] / "static" / "translate.js").read_text()
    assert "JSON.stringify({claim_id: id})" in js
    assert "box.appendChild(wrap)" in js and "q.textContent" not in js  # appended after; the quote is untouched
    assert t.SYSTEM and "मशीन अनुवाद। मूल अंग्रेज़ी ऊपर है और वही सबूत है।" in js

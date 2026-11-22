"""BE-T1 (D-009): every API error has a stable `code` and `message` {en, hi}, beside its old field.

Run from the repo root: pytest app/tests/test_errors.py -q
"""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import errors
import outcomes
from community import pulse as area_pulse
from inputs import understand
from voice import transcribe as voice

import app as app_module
from app import app

client = TestClient(app)
needs_data = pytest.mark.skipif(app_module._engine() is None, reason="facility data not built (app/facts/build.py)")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# ui2 (PR #145) app/static/i18n place.outside_india and place.too_coarse: the server sends the same words.
UI2 = {"location_outside_india": ("Your phone's location looks outside India. Type a PIN, district or town.",
                                  "फ़ोन की लोकेशन भारत से बाहर दिख रही है। पिन कोड, ज़िला या कस्बे का नाम लिखें।"),
       "location_too_coarse": ("Your phone's location is too rough to use. Type a PIN, district or town.",
                               "फ़ोन की लोकेशन बहुत अंदाज़न है। पिन कोड, ज़िला या कस्बे का नाम लिखें।")}
GOOD = {"service": "dialysis", "lat": 26.6, "lon": 85.48, "accuracy_m": 40, "source": "gps"}


def coded(r, code: str, status: int) -> dict:
    """The response carries `code` and a message in both languages; returns the body for the old-field checks."""
    assert r.status_code == status, r.text
    j = r.json()
    assert j["code"] == code
    assert j["message"]["en"] and DEVANAGARI.search(j["message"]["hi"])
    return j


# The table


@pytest.mark.parametrize("code", sorted(errors.MESSAGES))
def test_every_code_has_en_and_hi(code):
    en, hi = errors.MESSAGES[code]
    assert re.fullmatch(r"[a-z][a-z0-9_]*", code)
    assert en.strip() and hi.strip()
    assert not DEVANAGARI.search(en), "English text in the en slot"
    assert DEVANAGARI.search(hi), "Hindi text must be Devanagari"
    assert PLACEHOLDER.findall(en) == PLACEHOLDER.findall(hi), "same placeholders in both languages"
    for text in (en, hi):
        assert "\u2014" not in text and "\u2013" not in text, "no dashes"
        assert text.endswith((".", "।")), "a full sentence"


def test_location_texts_match_ui2():
    for code, want in UI2.items():
        assert errors.MESSAGES[code] == want


def test_every_code_in_the_source_is_in_the_table_and_back():
    src = "\n".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py")
                    if "tests" not in p.parts and p.name != "errors.py")
    used = set(re.findall(r'(?:Coded|Invalid|_err|payload)\(\s*"(\w+)"', src))
    used |= set(re.findall(r'Rejected\(\d+, .+?, "(\w+)"\)', src))
    used |= set(re.findall(r'OutcomeError\(.+?, "(\w+)"\)', src))
    used |= {"not_found", "internal", "store_failed", "note_no_service", "note_model_unavailable"}  # in handlers
    used |= {"location_outside_india", "location_too_coarse", "location_invalid", "text_too_long",
             "request_invalid"}  # errors.validation_code
    assert used == set(errors.MESSAGES)


# Location (the ui2 LOCATION_CODES handler reads `code` and `message` {en, hi} at the top level)


def test_london_is_outside_india_and_keeps_the_pydantic_detail():
    j = coded(client.post("/api/plan", json={**GOOD, "lat": 51.5, "lon": -0.12}), "location_outside_india", 422)
    assert (j["message"]["en"], j["message"]["hi"]) == UI2["location_outside_india"]
    assert {(tuple(d["loc"]), d["type"]) for d in j["detail"]} == {(("body", "lat"), "less_than_equal"),
                                                                    (("body", "lon"), "greater_than_equal")}
    assert all(d["msg"] for d in j["detail"]) and "51.5" not in str(j["detail"])  # the point is never echoed


def test_1500_km_accuracy_is_too_coarse():
    j = coded(client.post("/api/plan", json={**GOOD, "accuracy_m": 1_500_000}), "location_too_coarse", 422)
    assert (j["message"]["en"], j["message"]["hi"]) == UI2["location_too_coarse"]
    assert [(d["loc"], d["type"]) for d in j["detail"]] == [(["body", "accuracy_m"], "less_than_equal")]


def test_outside_india_wins_over_a_rough_fix():
    coded(client.post("/api/plan", json={**GOOD, "lat": 51.5, "lon": -0.12, "accuracy_m": 2e6}),
          "location_outside_india", 422)


@pytest.mark.parametrize("change", [{"lat": None}, {"lon": "here"}, {"accuracy_m": -1}])
def test_unusable_point_is_location_invalid(change):
    coded(client.post("/api/plan", json={**GOOD, **change}), "location_invalid", 422)


def test_missing_point_is_location_invalid():
    body = {k: v for k, v in GOOD.items() if k != "lat"}
    j = coded(client.post("/api/plan", json=body), "location_invalid", 422)
    assert j["detail"][0]["type"] == "missing"


def test_nan_point_is_location_invalid():
    r = client.post("/api/plan", content=b'{"service":"dialysis","lat":NaN,"lon":85.48}',
                    headers={"Content-Type": "application/json"})
    coded(r, "location_invalid", 422)


def test_dev_alias_reads_the_query():
    coded(client.get("/api/recommend", params={**GOOD, "lat": 51.5, "lon": -0.12}), "location_outside_india", 422)


def test_other_validation_is_request_invalid():
    coded(client.post("/api/plan", json={**GOOD, "depth": "deep"}), "request_invalid", 422)
    # Only the plan endpoints say "type a place": another endpoint's bad point is a request error
    coded(client.post("/api/area", json={"service": "dialysis", "lat": 51.5, "lon": -0.12}), "request_invalid", 422)
    coded(client.post("/api/place", json={"q": ""}), "request_invalid", 422)


def test_long_text_is_text_too_long():
    j = coded(client.post("/api/parse", json={"text": "x" * (understand.MAX_TEXT + 1)}), "text_too_long", 422)
    assert j["detail"][0]["type"] == "string_too_long"


# The free-text errors: the old `detail` or `error` string is unchanged


@needs_data
def test_unknown_service_keeps_detail():
    for path, body in [("/api/plan", {**GOOD, "service": "x"}), ("/api/area", {"service": "x", "lat": 26.6,
                                                                               "lon": 85.48})]:
        j = coded(client.post(path, json=body), "unknown_service", 422)
        assert j["detail"].startswith("unknown service; expected one of [")


def test_unknown_service_on_verify():
    j = coded(client.post("/api/verify", json={"facility_id": "f1", "service_id": "x"}), "unknown_service", 422)
    assert j["detail"].startswith("unknown service; expected one of [")


def test_facts_not_built(monkeypatch):
    monkeypatch.setattr(app_module, "_engine", lambda: None)
    j = coded(client.post("/api/plan", json=GOOD), "facts_not_built", 503)
    assert j["detail"] == "facility data is not built on this server (run app/facts/build.py)"


def test_crash_is_json_with_the_old_words(monkeypatch):
    def boom(_):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(app_module, "_plan", boom)
    r = TestClient(app, raise_server_exceptions=False).post("/api/plan", json=GOOD)
    j = coded(r, "internal", 500)
    assert j["detail"] == "Internal Server Error" and "secret" not in r.text


def test_not_found_keeps_detail():
    for r in (client.get("/nope.txt"), client.get("/api/pack/atlantis"), client.get("/api/stories/chart/x.svg")):
        assert coded(r, "not_found", 404)["detail"] == "Not Found"


def test_verify_not_set_up(monkeypatch):
    monkeypatch.setattr(app_module, "_checker", lambda: None)
    j = coded(client.post("/api/verify", json={"facility_id": "f1", "service_id": "dialysis"}), "verify_not_set_up", 503)
    assert j["error"] == "website check is not set up on this server"


@needs_data
def test_translate_unknown_claim():
    j = coded(client.post("/api/translate", json={"claim_id": "zz:none:0"}), "translate_unknown_claim", 404)
    assert j["detail"] == "unknown claim id"


@pytest.mark.parametrize("note, code", [(understand.NOTE_NO_SERVICE, "note_no_service"),
                                        ("SERVING_ENDPOINT_VISION is not set on this server", "note_model_unavailable")])
def test_read_note_failures(monkeypatch, note, code):
    monkeypatch.setattr(understand, "read_note", lambda _: {"ok": False, "note": note})
    j = coded(client.post("/api/read-note", json={"image": "data:image/png;base64,AAAA"}), code, 200)
    assert j["ok"] is False and j["note"] == note


def test_read_note_success_has_no_code(monkeypatch):
    monkeypatch.setattr(understand, "read_note", lambda _: {"ok": False, "guard": "no_text", "note": None})
    assert "code" not in client.post("/api/read-note", json={"image": "data:image/png;base64,AAAA"}).json()


VOICE = [(503, "Voice input is not working on this server now. Use your keyboard's mic to speak.", "voice_failed"),
         (503, "Voice input is getting ready. Try again in a minute, or type.", "voice_loading"),
         (415, "Send the recording as webm, ogg, mp4 or wav audio.", "voice_bad_type"),
         (415, "The recording could not be read. Try again.", "voice_unreadable"),
         (413, "The recording is too big. Speak for up to 15 seconds.", "voice_too_big"),
         (413, "The recording is too long. Speak for up to 15 seconds.", "voice_too_long")]


@pytest.mark.parametrize("status, text, code", VOICE)
def test_voice_errors(monkeypatch, status, text, code):
    def reject(*_):
        raise voice.Rejected(status, text, code)
    monkeypatch.setattr(voice, "transcribe", reject)
    j = coded(client.post("/api/transcribe", json={"audio": "data:audio/webm;base64,AAAA", "lang": "hi"}), code, status)
    assert j["error"] == text


def test_voice_bad_type_from_the_real_check():
    j = coded(client.post("/api/transcribe", json={"audio": "data:audio/flac;base64,AAAA", "lang": "en"}),
              "voice_bad_type", 415)
    assert j["error"] == "Send the recording as webm, ogg, mp4 or wav audio."


def test_outcome_checks_raise_coded_value_errors():
    cases = [(("call", "accepted", None, None), "outcome_bad_kind"),
             (("call", "yes", "no_bed", None), "outcome_bad_reason"),
             (("call", "yes", None, "lt_30"), "outcome_bad_wait")]
    for args, code in cases:
        with pytest.raises(ValueError) as e:
            outcomes.check_report(*args)
        assert e.value.code == code


OUTCOME = {"outcome_id": "0b7e2c1a-1f2d-4a3b-8c4d-5e6f7a8b9c0d", "facility_id": "f1", "service_id": "dialysis",
           "outcome": "yes", "said_at_ms": 1_700_000_000_000, "lat": 26.6, "lon": 85.48}


@needs_data
@pytest.mark.parametrize("exc, code, status, old", [
    (errors.Invalid("outcome_not_listed", "this facility is not listed for this service"), "outcome_not_listed", 422,
     {"detail": "this facility is not listed for this service"}),
    (ValueError("something else"), "request_invalid", 422, {"detail": "something else"}),
    (outcomes.RateLimited("already reported for this facility and service in the last 24 hours"),
     "outcome_rate_limited", 429,
     {"ok": False, "error": "already reported for this facility and service in the last 24 hours"}),
    (outcomes.OutcomeError("DATABRICKS_WAREHOUSE_ID is not set on this server", "store_not_set_up"),
     "store_not_set_up", 503, {"ok": False, "error": "DATABRICKS_WAREHOUSE_ID is not set on this server"}),
    (outcomes.OutcomeError("the statement did not succeed (FAILED)"), "store_failed", 503,
     {"ok": False, "error": "the statement did not succeed (FAILED)"})])
def test_outcome_errors(monkeypatch, exc, code, status, old):
    def record(*_):
        raise exc
    monkeypatch.setattr(outcomes, "record", record)
    j = coded(client.post("/api/outcome", json=OUTCOME), code, status)
    assert j.items() >= old.items()


@needs_data
def test_store_not_set_up_on_summary(monkeypatch):
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    monkeypatch.setattr(outcomes, "_summary_cache", {})
    j = coded(client.get("/api/outcomes/summary"), "store_not_set_up", 503)
    assert j["error"] == "DATABRICKS_WAREHOUSE_ID is not set on this server"


@needs_data
@pytest.mark.parametrize("params, code, detail", [
    ({}, "pulse_need_where", "give a district, or lat and lon"),
    ({"district": "Atlantis"}, "pulse_unknown_district", "unknown district"),
    ({"district": "Patna", "service": "x"}, "pulse_unknown_service", "unknown service")])
def test_pulse_errors(params, code, detail):
    assert coded(client.get("/api/pulse", params=params), code, 422)["detail"] == detail


def test_pulse_point_without_district_code(monkeypatch):
    monkeypatch.setattr(outcomes, "district", lambda *_: None)
    with pytest.raises(ValueError) as e:
        area_pulse.resolve_district(None, None, 26.6, 85.48)
    assert e.value.code == "pulse_no_district_for_point"


@pytest.mark.parametrize("path, code, text", [
    ("/api/how", "how_not_built", "page data is not built on this server (run app/howto/build.py)"),
    ("/api/stories", "stories_not_built", "page data is not built on this server (run app/stories/build.py)")])
def test_page_data_not_built(monkeypatch, tmp_path, path, code, text):
    monkeypatch.setattr(app_module, "HOW", tmp_path / "how.json")
    monkeypatch.setattr(app_module, "STORIES", tmp_path)
    assert coded(client.get(path), code, 503)["error"] == text


def test_packs_not_built(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "PACKS", tmp_path)
    r = client.get("/api/pack/version")
    assert coded(r, "packs_not_built", 404)["error"] == "no packs built" and r.headers["cache-control"] == "no-cache"
    assert coded(client.post("/api/pack/locate", json={"lat": 26.6, "lon": 85.48}), "packs_not_built", 404)["error"] \
        == "no packs built"

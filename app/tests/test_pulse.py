"""Area pulse (GET /api/pulse): k-anonymity, one weekly window, complementary suppression, the Wilson interval and
parameterised SQL. The 2A-2D tests replay COMMUNITY_CHECK.md's re-identification attempts.

The warehouse is mocked and the demo reports are stubbed; no network. Run from the repo root:
pytest app/tests/test_pulse.py -q
"""
import json
import sys
import types
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import outcomes
from community import pulse

import app as app_module
from app import app

client = TestClient(app)
needs_data = pytest.mark.skipif(app_module._engine() is None, reason="facility data not built (app/facts/build.py)")
TODAY = date(2026, 11, 21)  # a Saturday; the window is 17 Aug to 15 Nov 2026
LAST_WEEK = date(2026, 11, 9)


def reports(n_reporters: int, n_reports: int, **kw) -> list[dict]:
    base = {"facility_id": "f1", "service_id": "dialysis", "kind": "visit", "outcome": "accepted", "reason": None,
            "week": LAST_WEEK}
    return [{**base, "reporter_key": f"k{i % n_reporters}" if n_reporters else None, **kw} for i in range(n_reports)]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    pulse._cache.clear()
    monkeypatch.delenv("COMMUNITY_DEMO", raising=False)


@pytest.fixture
def eng():
    e = app_module._engine()
    if e is None:
        pytest.skip("facility data not built (app/facts/build.py)")
    return e


def a_pair(eng) -> tuple[str, str]:
    for svc, rows in eng.pairs.items():
        for p in rows:
            fid = eng.fac["id"][p.fi]
            if eng.score(fid, svc)[5]:
                return fid, svc
    pytest.skip("no pair with evidence")


# ---------- k-anonymity ----------

def test_two_reporters_with_ten_reports_is_hidden():
    assert not pulse.shown(reports(2, 10))


def test_three_reporters_with_five_reports_is_shown():
    assert pulse.shown(reports(3, 5))


def test_three_reporters_with_four_reports_is_hidden():
    assert not pulse.shown(reports(3, 4))


def test_facility_and_reason_cells_need_five_reporters_and_eight_reports():
    assert pulse.detail_shown(reports(5, 8))
    assert not pulse.detail_shown(reports(4, 20)) and not pulse.detail_shown(reports(5, 7))


def test_null_and_empty_keys_never_count_as_reporters():
    rows = reports(2, 6) + reports(0, 20) + [{**reports(1, 1)[0], "reporter_key": ""}]
    assert not pulse.shown(rows)


WINDOW_KEYS = {"days", "since_week", "through", "reports", "services", "facilities", "reasons", "empty"}


@needs_data
def test_hidden_cells_are_left_out_with_no_count_of_them(eng):
    fid, sid = a_pair(eng)
    rows = reports(2, 10, facility_id=fid, service_id=sid)
    out = pulse.aggregate(eng, rows, "Patna", None, TODAY, simulated=False)
    w = out["window"]
    assert set(w) == WINDOW_KEYS and w["services"] == w["facilities"] == w["reasons"] == [] and w["reports"] == 0
    # The same answer as a district with no reports at all: nothing says that something was hidden.
    assert w == pulse.aggregate(eng, [], "Patna", None, TODAY, simulated=False)["window"]
    assert out["hidden_note"]["en"] == "Some reports are not shown so no single health worker can be identified."


@needs_data
def test_shown_cells_count_and_cite_the_listing(eng):
    fid, sid = a_pair(eng)
    rows = reports(5, 11, facility_id=fid, service_id=sid) + reports(5, 3, facility_id=fid, service_id=sid,
                                                                      outcome="turned_away", reason="no_bed")
    out = pulse.aggregate(eng, rows, "Patna", sid, TODAY, simulated=False)
    w = out["window"]
    (cell,) = w["services"]
    assert cell["referrals"] == 14 and cell["accepted"] == 11 and cell["decided"] == 14 and w["reports"] == 14
    assert cell["text"]["en"].startswith("In Patna district, health workers logged 14 ")
    assert "11 were accepted" in cell["text"]["en"] and "probably between 52% and 92%" in cell["text"]["en"]
    (fac,) = w["facilities"]
    assert fac["band"] == eng.score(fid, sid)[0] and fac["evidence"]["quote"] in json.dumps(eng.claims, ensure_ascii=False)
    # 3 turn-aways: fewer than 8 reports, so no reason cell, and no row saying one was hidden
    assert w["reasons"] == []


@needs_data
def test_phone_yes_is_never_called_confirmed(eng):
    rows = reports(3, 6, kind="call", outcome="yes")
    text = pulse.aggregate(eng, rows, "Patna", None, TODAY, False)["window"]["services"][0]["text"]["en"]
    assert "6 said yes" in text and "it is not a confirmation" in text


# ---------- weeks ----------

@pytest.mark.parametrize("d, monday", [
    (date(2026, 11, 22), date(2026, 11, 16)),               # Sunday belongs to the week before
    (date(2026, 11, 16), date(2026, 11, 16)),               # Monday is its own week
    (datetime(2026, 11, 18, 23, 59), date(2026, 11, 16)),
    ("2026-11-21T10:15:00Z", date(2026, 11, 16)),
    ("2026-01-01", date(2025, 12, 29)),                     # across a year end
])
def test_week_start_is_the_monday(d, monday):
    assert pulse.week_start(d) == monday


@needs_data
def test_one_window_of_whole_weeks_that_ends_before_this_week(eng):
    first = reports(3, 5, week=date(2026, 8, 17))
    too_old = reports(3, 5, week=date(2026, 8, 10))
    this_week = reports(3, 5, week=date(2026, 11, 16))
    rows = first + too_old + this_week
    out = pulse.aggregate(eng, rows, "Patna", None, TODAY, False)
    assert "windows" not in out and out["window"]["days"] == 90
    assert out["window"]["since_week"] == "2026-08-17" and out["window"]["through"] == "2026-11-15"
    assert out["window"]["reports"] == 5
    # The same numbers on every day of a week: a report made this week changes nothing until next Monday.
    for day in (date(2026, 11, 16), date(2026, 11, 22)):
        assert pulse.aggregate(eng, rows, "Patna", None, day, False)["window"] == out["window"]


# ---------- COMMUNITY_CHECK.md 2A-2D: nothing is recovered any more ----------

def row(fid, key, kind="visit", outcome="accepted", reason=None, week=LAST_WEEK, svc="dialysis"):
    return {"facility_id": fid, "service_id": svc, "reporter_key": key, "kind": kind, "outcome": outcome,
            "reason": reason, "week": week}


BASE = [row("F1", k) for k in "abc"] + [row("F1", "a", "call", "yes"), row("F1", "b", "call", "yes")]


@needs_data
def test_2a_one_window_so_no_older_report_can_be_isolated(eng):
    old = row("F1", "d", outcome="turned_away", reason="asked_to_pay", week=date(2026, 10, 5))  # 50 days ago
    out = pulse.aggregate(eng, BASE + [old], "Patna", None, TODAY, False)
    body = json.dumps(out)
    assert "windows" not in out and '"days": 30' not in body
    w = out["window"]
    assert w["facilities"] == [] and w["reasons"] == [] and "asked_to_pay" not in body and "F1" not in body


@needs_data
def test_2b_the_total_is_the_sum_of_the_shown_cells(eng):
    burn = row("F2", "e", outcome="turned_away", reason="no_bed", svc="burn_care")
    w = pulse.aggregate(eng, BASE + [burn], "Patna", None, TODAY, False)["window"]
    assert w["reports"] == sum(c["reports"] for c in w["services"]) == 5
    assert "burn_care" not in json.dumps(w)


@needs_data
def test_2c_a_service_cell_minus_its_shown_facilities_is_never_a_hidden_cell(eng):
    big = [row("F1", f"k{i % 5}") for i in range(8)]  # passes the facility rule on its own
    lone = [row("F2", "e", outcome="turned_away", reason="no_bed")]
    w = pulse.aggregate(eng, big + lone, "Patna", "dialysis", TODAY, False)["window"]
    (cell,) = w["services"]
    assert cell["decided"] == 9 and cell["accepted"] == 8
    assert w["facilities"] == []  # showing F1 would leave F2's single turn-away as the difference
    # With a second facility that passes the rule too, both are shown: nothing is left over to subtract.
    other = [row("F2", f"j{i % 5}", outcome="turned_away", reason="no_bed") for i in range(8)]
    w = pulse.aggregate(eng, big + other, "Patna", "dialysis", TODAY, False)["window"]
    assert sorted((f["facility_id"], f["reports"]) for f in w["facilities"]) == [("F1", 8), ("F2", 8)]
    assert "facilities_hidden" not in w


@needs_data
def test_2d_a_reason_one_person_gave_leaves_no_trace(eng):
    one = row("F1", "d", outcome="turned_away", reason="asked_to_pay")
    out = pulse.aggregate(eng, BASE + [one], "Patna", "dialysis", TODAY, False)
    assert out["window"]["reasons"] == [] and "asked_to_pay" not in json.dumps(out)


@needs_data
def test_reason_cells_show_the_two_classes_never_the_reason(eng):
    refused = [row("F1", f"k{i % 5}", outcome="turned_away", reason=("no_bed", "doctor_absent")[i % 2])
               for i in range(8)]
    out = pulse.aggregate(eng, refused, "Patna", "dialysis", TODAY, False)
    assert out["window"]["reasons"] == [{"service_id": "dialysis", "class": "temporary", "n": 8}]
    assert "no_bed" not in json.dumps(out) and "doctor_absent" not in json.dumps(out)


# ---------- Wilson interval ----------

def test_wilson_matches_reference_values():
    p, lo, hi = pulse.wilson(5, 10)
    assert p == 0.5 and lo == pytest.approx(0.2366, abs=1e-4) and hi == pytest.approx(0.7634, abs=1e-4)
    _, lo, hi = pulse.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-4)
    _, lo, hi = pulse.wilson(11, 14)
    assert lo == pytest.approx(0.5241, abs=1e-3) and hi == pytest.approx(0.9243, abs=1e-3)
    assert pulse.wilson(0, 0) is None


# ---------- the endpoint ----------

@pytest.fixture
def wh(monkeypatch):
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh-1")
    calls = []
    rows = [["f1", "dialysis", "visit", "accepted", None, f"k{i % 3}", "2026-11-16"] for i in range(5)]

    def fake(body):
        calls.append(body)
        return {"status": {"state": "SUCCEEDED"}, "result": {"data_array": rows}}

    monkeypatch.setattr(outcomes, "_sql", fake)
    return calls


@needs_data
def test_sql_is_parameterised_and_weekly(wh):
    r = client.get("/api/pulse", params={"district": "patna", "service": "dialysis"})
    assert r.status_code == 200, r.text
    (call,) = wh
    params = {p["name"]: p["value"] for p in call["parameters"]}
    assert params["district"] == "Patna" and params["service"] == "dialysis" and params["since"] < params["until"]
    assert "Patna" not in call["statement"] and "dialysis" not in call["statement"]
    assert ":district" in call["statement"] and "date_trunc('WEEK', created_at)" in call["statement"]
    body = r.json()
    assert body["district"] == "Patna" and not body["simulated"]
    assert "k0" not in r.text  # reporter keys never leave the server


@needs_data
@pytest.mark.parametrize("params", [{"district": "Patna' OR 1=1 --"}, {"district": "Patna", "service": "icu"},
                                    {}, {"lat": "1.0", "lon": "80"}])
def test_bad_input_is_422_and_runs_no_sql(wh, params):
    assert client.get("/api/pulse", params=params).status_code == 422
    assert wh == []


@needs_data
def test_point_is_resolved_to_its_district(wh):
    eng = app_module._engine()
    r = client.get("/api/pulse", params={"lat": 25.61, "lon": 85.14})
    assert r.status_code == 200 and r.json()["district"] == outcomes.district(eng, 25.61, 85.14)
    assert "25.61" not in json.dumps(wh[0]["parameters"])


@needs_data
def test_no_warehouse_is_503(monkeypatch):
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    r = client.get("/api/pulse", params={"district": "Patna"})
    assert r.status_code == 503 and "error" in r.json()


# ---------- demo ----------

@needs_data
def test_demo_sentences_all_say_simulated(monkeypatch):
    eng = app_module._engine()
    fid, sid = a_pair(eng)
    fake = types.ModuleType("community.field")
    fake.simulated_reports = lambda eng=None: [
        {"facility_id": fid, "service_id": sid, "kind": "visit", "outcome": o, "reason": None, "wait_bucket": None,
         "district": "PATNA", "reporter_key": f"sim{i % 4}", "created_at": "2026-11-17T09:00:00", "simulated": True}
        for i, o in enumerate(["accepted"] * 6 + ["turned_away"] * 2)]
    monkeypatch.setitem(sys.modules, "community.field", fake)
    monkeypatch.setenv("COMMUNITY_DEMO", "1")
    monkeypatch.setattr(outcomes, "_sql", lambda b: pytest.fail("demo mode must not touch the warehouse"))
    for district in ("Patna", "Gaya"):
        body = client.get("/api/pulse", params={"district": district}).json()
        assert body["simulated"]
        texts = [s["text"] for s in body["window"]["services"]]
        texts += [body["window"]["empty"]] if body["window"]["empty"] else []
        assert texts
        for t in texts:
            assert t["en"].startswith("Simulated for the demo: ") and t["hi"].startswith(pulse.SIM["hi"])

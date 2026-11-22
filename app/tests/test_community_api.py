"""The community features wired into the API: /api/plan reads field reports without waiting on the warehouse and
says so when it could not; /api/pulse and /api/outcome reject unbounded or non-finite input. Warehouse mocked."""
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import outcomes
from community import field

import app as app_module
from app import app

client = TestClient(app)
needs_data = pytest.mark.skipif(app_module._engine() is None, reason="facility data not built (app/facts/build.py)")
PLAN = {"service": "dialysis", "lat": 26.6, "lon": 85.48}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("COMMUNITY_DEMO", raising=False)
    field._cache.clear()
    yield
    field._cache.clear()


@needs_data
def test_plan_without_a_warehouse_is_unchanged_and_says_reports_were_not_read(monkeypatch):
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    r = client.post("/api/plan", json=PLAN)
    assert r.status_code == 200
    body = r.json()
    assert body["field_reports"] == {"read": False, "note": field.NOT_READ}
    assert not any("field" in o for o in body["options"])
    assert not any(c["label"] == field.TERM_LABEL for o in body["options"] for c in o["contributions"])


@needs_data
def test_plan_never_waits_on_a_slow_warehouse(monkeypatch):
    release, started = threading.Event(), threading.Event()

    def slow(body):
        started.set()
        release.wait(10)
        return {"status": {"state": "SUCCEEDED"}, "result": {"data_array": []}}

    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh-1")
    monkeypatch.setattr(outcomes, "_sql", slow)
    t0 = time.monotonic()
    r = client.post("/api/plan", json=PLAN)
    assert r.status_code == 200 and time.monotonic() - t0 < 5
    assert r.json()["field_reports"]["read"] is False  # nothing read yet: the plain note
    assert started.wait(5)
    release.set()
    for _ in range(50):  # the background read lands in the cache
        if field._cache.get("a"):
            break
        time.sleep(0.05)
    assert client.post("/api/plan", json=PLAN).json()["field_reports"] == {"read": True, "note": None}


@needs_data
def test_plan_carries_the_field_block_from_cached_reports(monkeypatch):
    eng = app_module._engine()
    fid = eng.plan("dialysis", 26.6, 85.48, None, "gps")["options"][0]["facility_id"]
    now = field.datetime.now(field.UTC)
    reports = [{"facility_id": fid, "service_id": "dialysis", "reporter_key": k * 16, "kind": "visit",
                "outcome": "accepted", "reason": None, "created_at": now - field.timedelta(days=2)} for k in "ab"]
    field._cache["a"] = (time.monotonic(), {(fid, "dialysis"): reports}, True)
    o = client.post("/api/plan", json=PLAN).json()["options"][0]
    assert o["field"]["n_reporters"] == 2 and o["field"]["lines"][0]["en"].startswith("Reports from 2 health workers")
    assert o["contributions"][-1]["label"] == field.TERM_LABEL


@pytest.mark.parametrize("query", [
    {"district": "Sitamarhi", "service": "x" * 41},
    {"district": "x" * 61},
    {"lat": "nan", "lon": "85.48"},
    {"lat": "26.6", "lon": "inf"},
    {"district": "Sitamarhi", "service": "not_a_service"},
])
def test_pulse_rejects_unbounded_or_non_finite_input(query, monkeypatch):
    calls = []
    monkeypatch.setattr(outcomes, "_sql", lambda b: calls.append(b))
    assert client.get("/api/pulse", params=query).status_code == 422
    assert calls == []


@pytest.mark.parametrize("bad", [
    {"said_at_ms": 10 ** 18}, {"facility_id": ""}, {"lat": float("nan")}, {"wait_bucket": "forever"},
    {"reason": "the doctor was rude"}, {"kind": "review"}, {"stars": 5},
])
def test_outcome_rejects_unbounded_or_off_list_input(bad, monkeypatch):
    calls = []
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh-1")
    monkeypatch.setattr(outcomes, "_sql", lambda b: calls.append(b))
    body = {"outcome_id": str(uuid.uuid4()), "facility_id": "F1", "service_id": "dialysis", "outcome": "no",
            "said_at_ms": 1_795_000_000_000, "lat": 26.6, "lon": 85.48, **bad}
    import json
    r = client.post("/api/outcome", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert r.status_code == 422, r.text
    assert calls == []

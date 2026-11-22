"""Call outcomes (#65). The SQL warehouse is mocked; no network. Run from app/: python -m pytest tests -q"""
import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import outcomes

import app as app_module
from app import app

client = TestClient(app)
needs_data = pytest.mark.skipif(app_module._engine() is None, reason="facility data not built (app/facts/build.py)")


@pytest.fixture
def wh(monkeypatch):
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh-1")
    outcomes._summary_cache.clear()

    class W:
        calls: list
        rows: list

    W.calls, W.rows = [], []

    def fake(body):
        W.calls.append(body)
        return {"status": {"state": "SUCCEEDED"}, "result": {"data_array": W.rows}}

    monkeypatch.setattr(outcomes, "_sql", fake)
    return W


def a_pair(band: str | None = None) -> tuple[str, str]:
    eng = app_module._engine()
    for svc, rows in eng.pairs.items():
        for p in rows:
            fid = eng.fac["id"][p.fi]
            if band is None or eng.score(fid, svc)[0] == band:
                return fid, svc
    pytest.skip(f"no pair with band {band}")


def body(**kw):
    fid, svc = a_pair()
    b = {"outcome_id": str(uuid.uuid4()), "facility_id": fid, "service_id": svc, "outcome": "yes",
         "said_at_ms": 1_700_000_000_000, "lat": 26.6, "lon": 85.48}
    return {**b, **kw}


@needs_data
def test_record_writes_one_parameterised_merge_with_no_coordinates(wh):
    b = body()
    r = client.post("/api/outcome", json=b)
    assert r.status_code == 200 and r.json()["ok"]
    (call,) = wh.calls
    assert call["warehouse_id"] == "wh-1"
    assert call["statement"].startswith("MERGE INTO workspace.referral_saathi.call_outcomes")
    params = {p["name"]: p["value"] for p in call["parameters"]}
    assert set(params) == {"outcome_id", "facility_id", "service_id", "outcome", "questions", "model_version",
                           "district", "created_at", "app_version"}
    assert params["outcome_id"] == b["outcome_id"] and params["district"]
    assert isinstance(json.loads(params["questions"]), list)
    assert "26.6" not in json.dumps(params) and "85.48" not in json.dumps(params)  # coordinates never stored
    assert params["app_version"].startswith("rs-shell-")
    # an old phone clock is replaced by the server time
    assert not params["created_at"].startswith("2023")


@needs_data
@pytest.mark.parametrize("bad", [{"outcome": "maybe"}, {"outcome_id": "not-a-uuid"}, {"lat": 1.0},
                                 {"note": "patient name"}, {"service_id": "icu"}, {"facility_id": "nope"}])
def test_record_rejects_bad_input(wh, bad):
    assert client.post("/api/outcome", json=body(**bad)).status_code == 422
    assert wh.calls == []


@needs_data
def test_no_warehouse_is_503(monkeypatch):
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    r = client.post("/api/outcome", json=body())
    assert r.status_code == 503 and "DATABRICKS_WAREHOUSE_ID" in r.json()["error"]


@needs_data
def test_failed_statement_is_503(wh, monkeypatch):
    monkeypatch.setattr(outcomes, "_sql", lambda b: {"status": {"state": "FAILED"}})
    assert client.post("/api/outcome", json=body()).status_code == 503


@needs_data
def test_summary_counts_contradictions_against_the_band_shown(wh):
    nv = a_pair("not_verified")
    wh.rows = [[nv[0], nv[1], "yes", "3"], [nv[0], nv[1], "no_answer", "2"], ["gone", "dialysis", "no", "1"]]
    likely = None
    try:
        likely = a_pair("likely")
    except pytest.skip.Exception:
        pass
    if likely:
        wh.rows += [[likely[0], likely[1], "no", "4"], [likely[0], likely[1], "yes", "5"]]
    s = client.get("/api/outcomes/summary").json()
    assert s["recorded"] == 6 + (9 if likely else 0)
    assert s["no_answer"] == 2
    assert s["contradicted"] == (4 if likely else 0) and s["agreed"] == (5 if likely else 0)
    assert s["answered"] == 3 + (9 if likely else 0)  # the unknown facility is counted but not compared
    client.get("/api/outcomes/summary")
    assert len(wh.calls) == 1  # cached for a minute

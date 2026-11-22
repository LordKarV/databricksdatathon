"""Call outcomes (#65): what the facility said on the phone, written to a Delta table, never patient data.

The page sends: a random outcome_id (so a retried offline flush writes once), facility_id, service_id, outcome
(yes / no / no_answer), the time the user tapped, and the patient's location rounded to 0.01 degree. The server keeps
only the district of the nearest PIN to that rounded point and drops the coordinates. The questions and the model
version are filled in here from the engine (the call-ahead questions the page showed), so no free text from the
page reaches the table. "Wrong number" is not sent: it says nothing about the service.

Writes go through the SQL Statement Execution API on the app's warehouse resource (DATABRICKS_WAREHOUSE_ID) with
named parameters; the table name comes from OUTCOMES_TABLE. The summary for "How this works" counts outcomes
and how many contradicted the band the app showed for that pair (Said no to a Likely, Said yes to an Unlikely).
"""
from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from facts.engine import Engine
from services import SERVICES

TABLE = os.environ.get("OUTCOMES_TABLE", "workspace.referral_saathi.call_outcomes")
OUTCOMES = ("yes", "no", "no_answer")
MAX_AGE = timedelta(days=7)
SUMMARY_TTL_S = 60
SW = Path(__file__).resolve().parent / "static" / "sw.js"
APP_VERSION = (re.search(r"const CACHE = '([^']+)'", SW.read_text()) or [None, "unknown"])[1]
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class OutcomeError(Exception):
    """The warehouse is not configured, or the statement failed."""


def _sdk_sql(body: dict[str, Any]) -> dict[str, Any]:
    """Run one statement with the app's credentials (Databricks SDK, pre-installed on Apps).

    Imported here, not at the top, so the app and its tests run where the SDK is not installed.
    """
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient().api_client.do("POST", "/api/2.0/sql/statements", body=body)


_sql: Callable[[dict[str, Any]], dict[str, Any]] = _sdk_sql  # tests replace this


def run(statement: str, params: dict[str, str | None]) -> list[list[Any]]:
    wh = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not wh:
        raise OutcomeError("DATABRICKS_WAREHOUSE_ID is not set on this server")
    body = {"warehouse_id": wh, "statement": statement, "wait_timeout": "30s", "on_wait_timeout": "CANCEL",
            "parameters": [{"name": k, "value": v, "type": "STRING"} for k, v in params.items()]}
    try:
        resp = _sql(body)
    except Exception as e:
        raise OutcomeError(f"the warehouse call failed ({type(e).__name__})") from e
    state = (resp.get("status") or {}).get("state")
    if state != "SUCCEEDED":
        raise OutcomeError(f"the statement did not succeed ({state})")
    return (resp.get("result") or {}).get("data_array") or []


def district(eng: Engine, lat: float, lon: float) -> str | None:
    """District of the nearest PIN to a point already rounded to 0.01 degree (as /api/area does)."""
    pins = eng.pins
    if not pins["pin"]:
        return None
    k = min(range(len(pins["pin"])), key=lambda j: (pins["lat"][j] - lat) ** 2 + (pins["lon"][j] - lon) ** 2)
    return str(pins["district"][k]).title() or None


def questions(eng: Engine, facility_id: str, service_id: str) -> list[str]:
    """The call-ahead questions the page showed for this pair (engine templates, no user text)."""
    i = eng.fid[facility_id]
    pr = eng.index[service_id][i]
    band = eng.score(facility_id, service_id)[0]
    return [q["question"] for q in eng._call_ahead(pr, band, SERVICES[service_id]["label_en"], i)]


def validate(eng: Engine, facility_id: str, service_id: str) -> None:
    if service_id not in SERVICES:
        raise ValueError("unknown service")
    i = eng.fid.get(facility_id)
    if i is None or i not in eng.index[service_id]:
        raise ValueError("this facility is not listed for this service")


def record(eng: Engine, outcome_id: str, facility_id: str, service_id: str, outcome: str, said_at_ms: int,
           lat: float, lon: float) -> dict[str, Any]:
    validate(eng, facility_id, service_id)
    now = datetime.now(UTC)
    said = datetime.fromtimestamp(said_at_ms / 1000, UTC)
    if not now - MAX_AGE <= said <= now + timedelta(minutes=5):
        said = now  # a phone clock far off: keep the row, use the server time
    row = {"outcome_id": outcome_id, "facility_id": facility_id, "service_id": service_id, "outcome": outcome,
           "questions": json.dumps(questions(eng, facility_id, service_id), ensure_ascii=False),
           "model_version": eng._meta()["model_hash"], "district": district(eng, round(lat, 2), round(lon, 2)),
           "created_at": said.strftime("%Y-%m-%d %H:%M:%S"), "app_version": APP_VERSION}
    # MERGE on outcome_id: a retried flush from an offline queue writes the row once.
    run(f"""MERGE INTO {TABLE} t USING (SELECT :outcome_id AS outcome_id) s ON t.outcome_id = s.outcome_id
WHEN NOT MATCHED THEN INSERT (outcome_id, facility_id, service_id, outcome, questions, model_version, district,
  created_at, app_version)
VALUES (:outcome_id, :facility_id, :service_id, :outcome, from_json(:questions, 'array<string>'), :model_version,
  :district, to_timestamp(:created_at), :app_version)""", row)
    _summary_cache.clear()
    return {"ok": True, "outcome_id": outcome_id, "district": row["district"]}


_summary_cache: dict[str, tuple[float, dict]] = {}


def summary(eng: Engine) -> dict[str, Any]:
    """Recorded outcomes and how many contradicted the band shown today; cached for a minute."""
    hit = _summary_cache.get("s")
    if hit and time.monotonic() - hit[0] < SUMMARY_TTL_S:
        return hit[1]
    rows = run(f"SELECT facility_id, service_id, outcome, count(*) FROM {TABLE} GROUP BY ALL", {})
    out = {"recorded": 0, "yes": 0, "no": 0, "no_answer": 0, "answered": 0, "contradicted": 0, "agreed": 0}
    for fid, sid, outcome, n in rows:
        n = int(n)
        out["recorded"] += n
        out[outcome] = out.get(outcome, 0) + n
        if outcome == "no_answer" or sid not in SERVICES or eng.fid.get(fid) not in eng.index.get(sid, {}):
            continue
        out["answered"] += n
        band = eng.score(fid, sid)[0]
        if (outcome == "no" and band == "likely") or (outcome == "yes" and band == "unlikely"):
            out["contradicted"] += n
        elif (outcome == "yes" and band == "likely") or (outcome == "no" and band == "unlikely"):
            out["agreed"] += n
    out["as_of"] = datetime.now(UTC).isoformat(timespec="seconds")
    _summary_cache["s"] = (time.monotonic(), out)
    return out

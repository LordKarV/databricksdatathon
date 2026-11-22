"""Call outcomes (#65): what the facility said on the phone, written to a Delta table, never patient data.

The page sends: a random outcome_id (so a retried offline flush writes once), facility_id, service_id, outcome
(yes / no / no_answer), the time the user tapped, and the patient's location rounded to 0.01 degree. The server keeps
only the district of the nearest PIN to that rounded point and drops the coordinates. The questions and the model
version are filled in here from the engine (the call-ahead questions the page showed), so no free text from the
page reaches the table. "Wrong number" is not sent: it says nothing about the service.

Writes go through the SQL Statement Execution API on the app's warehouse resource (DATABRICKS_WAREHOUSE_ID) with
named parameters; the table name comes from OUTCOMES_TABLE. The summary for "How this works" counts outcomes
and how many contradicted the band the app showed for that pair (Said no to a Likely, Said yes to an Unlikely).

Field reports (community/field.py) add four optional columns (databricks/app_plumbing/field_reports.sql): kind
(call, or visit: the patient went, accepted or turned away), reason (a fixed enum, never free text), wait_bucket and
reporter_key (a keyed hash of the signed-in user, community/reporter.py). A column is written only when it has a
value, so the old request shape writes the same statement as before and NULL kind reads as "call".
"""
from __future__ import annotations

import json
import math
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
OUTCOMES_BY_KIND = {"call": OUTCOMES, "visit": ("accepted", "turned_away")}
# Reasons for a "no" or a turn-away. Only the first class speaks to whether the facility offers the service.
REASONS_NOT_OFFERED = ("service_not_here", "equipment_absent", "referred_elsewhere_for_this_service")
REASONS_TEMPORARY = ("no_bed", "doctor_absent", "machine_down", "asked_to_pay", "closed_now")
REASONS = REASONS_NOT_OFFERED + REASONS_TEMPORARY
WAIT_BUCKETS = ("lt_30m", "30_120m", "gt_2h")
RATE_WINDOW = timedelta(hours=24)
MAX_AGE = timedelta(days=7)
SUMMARY_TTL_S = 60
SW = Path(__file__).resolve().parent / "static" / "sw.js"
APP_VERSION = (re.search(r"const CACHE = '([^']+)'", SW.read_text()) or [None, "unknown"])[1]
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class OutcomeError(Exception):
    """The warehouse is not configured, or the statement failed."""


class RateLimited(Exception):
    """This reporter already sent this kind of report for this facility and service within 24 h."""


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
    c = math.cos(math.radians(lat))  # as Engine.area
    k = min(range(len(pins["pin"])), key=lambda j: (pins["lat"][j] - lat) ** 2 + ((pins["lon"][j] - lon) * c) ** 2)
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


def check_report(kind: str, outcome: str, reason: str | None, wait_bucket: str | None) -> None:
    """Which fields go together: a reason only explains a "no" or a turn-away; a wait only follows a visit."""
    if outcome not in OUTCOMES_BY_KIND.get(kind, ()):
        raise ValueError(f"outcome {outcome!r} is not valid for a {kind} report")
    if reason is not None and (reason not in REASONS or outcome not in ("no", "turned_away")):
        raise ValueError("a reason is only accepted with a no or a turn-away, from the fixed list")
    if wait_bucket is not None and (wait_bucket not in WAIT_BUCKETS or kind != "visit"):
        raise ValueError("a wait is only accepted with a visit outcome, from the fixed list")


def _check_rate(reporter_key: str, outcome_id: str, facility_id: str, service_id: str, kind: str,
                said: datetime) -> None:
    """At most one report per reporter, pair and kind in any 24 h, checked in the table (not in this process).

    ponytail: check-then-write, so two simultaneous taps can both pass; a MERGE condition fixes that if it matters.
    Per kind, so the call-ahead and the later "they took the patient" from the same visit both go in; field.py
    counts only each reporter's latest report anyway.
    """
    fmt = "%Y-%m-%d %H:%M:%S"
    rows = run(f"""SELECT outcome_id FROM {TABLE} WHERE reporter_key = :reporter_key AND facility_id = :facility_id
  AND service_id = :service_id AND coalesce(kind, 'call') = :kind
  AND created_at > to_timestamp(:since) AND created_at < to_timestamp(:until) LIMIT 5""",
               {"reporter_key": reporter_key, "facility_id": facility_id, "service_id": service_id, "kind": kind,
                "since": (said - RATE_WINDOW).strftime(fmt), "until": (said + RATE_WINDOW).strftime(fmt)})
    if any(r[0] != outcome_id for r in rows):  # the same outcome_id is a retried flush: the MERGE writes nothing
        raise RateLimited("already reported for this facility and service in the last 24 hours")


def record(eng: Engine, outcome_id: str, facility_id: str, service_id: str, outcome: str, said_at_ms: int,
           lat: float, lon: float, kind: str = "call", reason: str | None = None, wait_bucket: str | None = None,
           reporter_key: str | None = None) -> dict[str, Any]:
    validate(eng, facility_id, service_id)
    check_report(kind, outcome, reason, wait_bucket)
    now = datetime.now(UTC)
    said = datetime.fromtimestamp(said_at_ms / 1000, UTC)
    if not now - MAX_AGE <= said <= now + timedelta(minutes=5):
        said = now  # a phone clock far off: keep the row, use the server time
    # Stored to the hour only: an exact time next to a stable reporter_key would let a reader of the table link one
    # health worker's reports to their day. The rate check below uses the same hour.
    said = said.replace(minute=0, second=0, microsecond=0)
    row = {"outcome_id": outcome_id, "facility_id": facility_id, "service_id": service_id, "outcome": outcome,
           "questions": json.dumps(questions(eng, facility_id, service_id), ensure_ascii=False),
           "model_version": eng._meta()["model_hash"], "district": district(eng, round(lat, 2), round(lon, 2)),
           "created_at": said.strftime("%Y-%m-%d %H:%M:%S"), "app_version": APP_VERSION}
    extra = {k: v for k, v in (("reason", reason), ("wait_bucket", wait_bucket), ("reporter_key", reporter_key))
             if v is not None}
    if extra or kind != "call":
        extra = {"kind": kind, **extra}
    if reporter_key:
        _check_rate(reporter_key, outcome_id, facility_id, service_id, kind, said)
    # Column names come from the fixed tuple above, never from the request; values are named parameters.
    cols = "".join(f", {k}" for k in extra)
    vals = "".join(f", :{k}" for k in extra)
    # MERGE on outcome_id: a retried flush from an offline queue writes the row once.
    run(f"""MERGE INTO {TABLE} t USING (SELECT :outcome_id AS outcome_id) s ON t.outcome_id = s.outcome_id
WHEN NOT MATCHED THEN INSERT (outcome_id, facility_id, service_id, outcome, questions, model_version, district,
  created_at, app_version{cols})
VALUES (:outcome_id, :facility_id, :service_id, :outcome, from_json(:questions, 'array<string>'), :model_version,
  :district, to_timestamp(:created_at), :app_version{vals})""", {**row, **extra})
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
        if outcome not in ("yes", "no") or sid not in SERVICES or eng.fid.get(fid) not in eng.index.get(sid, {}):
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

"""DEMO-TRAP-1 (#140): data for the How page card "One record, two answers". No hand-typed text.

The left side is copied from the raw re-run of audit/capabilities/aiq2.sql (RAW): the model, the run time, the
record's unique_id and the model's verdict. The field its quote came from and the record's own procedure sentence
about the service are looked up in derived/v1/claims.parquet, and must match the raw row exactly.
The right side is the engine's own plan at PLACE: its why-not row for that record (reason, travel time), its
location check (engine.WHERE) and the sentences it quotes for the service (Engine.score evidence ids).
The record is the raw row the engine passes over at PLACE (in why_not, not an option); with no such row, or no
raw file, there is no card.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

RAW = "audit/capabilities/aiq2_rerun_20261122.json"
QUERY_FILE = "audit/capabilities/aiq2.sql"
MODELS = {"databricks-meta-llama-3-3-70b-instruct": "Llama 3.3 70B"}  # serving endpoint id -> its model's name
PLACE = {"name": "Thane", "service": "dialysis", "lat": 19.16, "lon": 72.95}  # the demo query (#140)
VERDICT_KEY = "offers_dialysis"  # the field aiq2.sql's response schema names for this service
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def _warn(msg: str) -> None:
    print(f"trap card: {msg}; no card")


def build(root: Path, eng, claims: pd.DataFrame, services: dict) -> dict | None:
    """The card's data, or None (no card) when the raw file is absent or the engine no longer passes it over."""
    path = root / RAW
    if not path.is_file():
        return None
    raw = json.loads(path.read_text())
    svc = PLACE["service"]
    plan = eng.plan(svc, PLACE["lat"], PLACE["lon"], None, "gps")
    passed = {w["facility_id"]: w for w in plan["why_not"] if w["option_rank"] is None}
    row = next((r for r in raw["rows"] if r["unique_id"] in passed and r["verdict"][VERDICT_KEY] == "yes"), None)
    if row is None or raw["model"] not in MODELS:
        return _warn(f"no raw row the engine passes over at {PLACE['name']}, or an unnamed model")
    uid, verdict = row["unique_id"], row["verdict"]
    mine = claims[claims.unique_id == uid]
    quote_fields = sorted(set(mine[mine.text == verdict["evidence_quote"]].field))
    own = mine[(mine.field == "procedure") & mine.text.isin(row["procedure"]) & mine.services.str.contains(svc)]
    if len(quote_fields) != 1 or len(own) != 1:
        return _warn(f"{uid}: quote found in {quote_fields}, {len(own)} procedure sentences about {svc}")
    w = passed[uid]
    i = eng.fid[uid]
    ev = eng.score(uid, svc)[5]
    ran = datetime.fromisoformat(raw["ran_at_utc"])
    return {
        "source": RAW, "query_file": QUERY_FILE,
        "model": raw["model"], "model_name": MODELS[raw["model"]],
        "ran_at_utc": raw["ran_at_utc"],
        "ran_on": ran.date().isoformat(),
        "ran_on_label": {"en": f"{ran.day} {ran:%b %Y}", "hi": f"{ran.day} {MONTHS_HI[ran.month - 1]} {ran.year}"},
        "unique_id": uid, "name": row["name"], "city": row["address_city"],
        "verdict": {"key": VERDICT_KEY, "value": verdict[VERDICT_KEY], "confidence": verdict["confidence"],
                    "quote": verdict["evidence_quote"], "quote_field": quote_fields[0]},
        "own": {"field": "procedure", "text": own.text.iloc[0]},
        "saathi": {
            "place": PLACE, "label": {"en": services[svc]["label_en"], "hi": services[svc]["label_hi"]},
            "facility_id": w["facility_id"], "minutes": w["travel"]["minutes"], "option_rank": w["option_rank"],
            "band": w["band"], "reason_code": w["reason_code"], "reason": w["reason"],
            "loc_rule": eng.fac["loc_rule"][i], "where": eng_where(eng.fac["loc_rule"][i]), "city": eng.fac["city"][i],
            "quotes": [{"field": eng.claims[c][0], "text": eng.claims[c][1]} for c in ev],
        },
    }


def eng_where(rule: str) -> str:
    from facts.engine import WHERE  # noqa: PLC0415 (app/ is on sys.path once the engine is loaded)
    return WHERE.get(rule, "Location not checked")

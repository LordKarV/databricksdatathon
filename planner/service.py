"""One call for the app: plan a service at a point.

    from planner.service import plan_for_service
    out = plan_for_service("trauma_emergency", 26.45, 85.95)

Returns
    {"pathway": None}                                   service has no care pathway: keep your own ranking
    {"pathway": "<id>", "options": [...], "abstain": null | {"text"}, "thresholds": {...} | None,
     "instructions": [...], "considered": {...} | None, "assumptions": {...}, "meta": {...}}
`options` comes from planner.app_contract.to_options: the usual option keys plus `route`.

Arguments
    capability_p   optional replacement for the stub: capability_p(facility_id, capability) -> (p, ids).
                   This is the swap point for the model (#11).
    travel_fn      optional travel_fn(origin, destinations) -> geo.travel rows. Default: the
                   geo.travel estimate with no network calls, using hill constants when the
                   nearest facility is in a hill state.
Raises RuntimeError when planner/out/planner_v1.json.gz has not been built and no capability_p and
facilities are passed.
"""
import json
from pathlib import Path

from .app_contract import to_options
from .core import default_travel_fn, plan
from .store import Store

PATHWAYS_PATH = Path(__file__).resolve().parent.parent / "kb" / "pathways" / "care_pathways.json"

# app service id (app/services.py) -> pathway id (kb/pathways/care_pathways.json)
SERVICE_TO_PATHWAY = {
    "emergency_csection": "obstetric_emergency",
    "nicu": "sick_newborn",
    "trauma_emergency": "major_trauma",
    "burn_care": "burns",
    "dialysis": "dialysis_start",
    "stemi": "stemi",
    "snakebite": "snakebite",
}

_cache = {}


def pathways():
    if "pathways" not in _cache:
        doc = json.loads(PATHWAYS_PATH.read_text(encoding="utf-8"))
        _cache["pathways"] = {p["id"]: p for p in doc["pathways"]}
    return _cache["pathways"]


def store():
    if "store" not in _cache:
        _cache["store"] = Store.load()
    return _cache["store"]


def pathway_for(service):
    return SERVICE_TO_PATHWAY.get(service)


def plan_for_service(service, lat, lon, elapsed_minutes=0, capability_p=None, facilities=None, travel_fn=None):
    pid = pathway_for(service)
    if pid is None:
        return {"pathway": None}
    st = None
    if capability_p is None or facilities is None:
        st = store()
        if st is None:
            raise RuntimeError("planner data not built: run planner/export_v1.py, or pass capability_p and facilities")
    facilities = facilities if facilities is not None else st.facilities()
    stub = capability_p is None
    capability_p = capability_p or st.capability_p
    origin = (float(lat), float(lon))
    if travel_fn is None:
        travel_fn = default_travel_fn(st.state_near(origin) if st is not None else None)
    result = plan(origin, pathways()[pid], facilities, capability_p, travel_fn=travel_fn, elapsed_minutes=elapsed_minutes)
    return {"pathway": pid, "urgency": result["urgency"], "objective": result["objective"],
            "options": to_options(result, stub=stub), "abstain": result["abstain"],
            "thresholds": result.get("thresholds"), "instructions": result["instructions"],
            "considered": result.get("considered"), "assumptions": result["assumptions"],
            "meta": {"stub": stub, "planner_data": st.meta if (st is not None and stub) else None}}

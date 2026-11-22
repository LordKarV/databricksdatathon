"""One call for the app: plan a service at a point.

    from planner.service import plan_for_service
    out = plan_for_service("trauma_emergency", 26.45, 85.95)

Returns
    {"pathway": None}                                   service has no care pathway: keep your own ranking
    {"pathway": "<id>", "options": [...], "abstain": null | {"text"}, "thresholds": {...} | None,
     "instructions": [...], "considered": {...} | None, "assumptions": {...}, "meta": {...}}
`options` comes from planner.app_contract.to_options: the usual option keys plus `route`. With the
built store (model v2), a stop whose stage rests on a CALL_FIRST pair gets call_first true and a "call
first to check" flag, and each emergency plan's vs_direct gets what_would_change: the nearest facility,
nearer than the first stop, that v2 does not rule out for that stage (NO_SERVICE_TEXT or CALL_FIRST),
so a phone "yes" from it would change the answer.

Arguments
    capability_p   optional replacement for the model v2 store: capability_p(facility_id, capability)
                   -> (p, ids). Pass facilities with it.
    state          optional state or union territory of the origin (any case), e.g. from the app's
                   PIN index. It selects the hill-road travel constants in geo.travel. When it is
                   not given the state of the nearest PIN centroid is used, or of the nearest
                   facility when facilities are passed in. The state used is returned in meta.
    implications   True (default) wraps capability_p with planner.implied.with_implications: a strongly
                   evidenced capability lends a discounted probability to the ones it implies, and
                   blood comes from the blood-centre list when list facts are available. Applied
                   to a capability_p you pass in as well. Stops then carry capability_notes. With
                   the store, tags model v2 scores are never implied: v2's band is final for them.
    blood          optional list facts for blood (see planner/implied.py). Default: taken from the
                   planner export when it was built with the e-RaktKosh outputs present.
    first_stop     optional facility id the caller ranks first (the app's options list #1). In an
                   emergency it is stop 1 when it can give first care; `first_stop` in the result says
                   whether it could and which capabilities it lacks (planner.core).
    travel_fn      optional travel_fn(origin, destinations) -> geo.travel rows. Default: the
                   geo.travel estimate with no network calls, for that state. A travel_fn you pass
                   must apply the state itself.
Raises RuntimeError when planner/out/planner_v2.json.gz has not been built and no capability_p and
facilities are passed.
"""
import json
from pathlib import Path

from .app_contract import to_options
from .core import default_travel_fn, hav_km, plan
from .implied import IMPLIES, with_implications
from .store import Store, state_of_nearest

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


def _terrain(state):
    from geo import travel
    return travel.terrain_of(state)


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


def plan_for_service(service, lat, lon, elapsed_minutes=0, capability_p=None, facilities=None, travel_fn=None,
                     state=None, implications=True, blood=None, first_stop=None):
    pid = pathway_for(service)
    if pid is None:
        return {"pathway": None}
    st = None
    if capability_p is None or facilities is None:
        st = store()
        if st is None:
            raise RuntimeError("planner data not built: run planner/export_v2.py, or pass capability_p and facilities")
    facilities = facilities if facilities is not None else st.facilities()
    from_store = capability_p is None
    capability_p = capability_p or st.capability_p
    if blood is None and st is not None:
        blood = st.blood_facts()
    if implications:
        rules = {k: v for k, v in IMPLIES.items() if k not in st.v2_caps} if from_store else None
        capability_p = with_implications(capability_p, blood=blood, rules=rules)
    origin = (float(lat), float(lon))
    state_source = "caller"
    if state is None:
        if st is not None:
            state, state_source = st.state_near(origin), "nearest PIN centroid"
        else:
            state, state_source = state_of_nearest(origin, facilities), "nearest facility"
    if travel_fn is None:
        travel_fn = default_travel_fn(state)
    pw = pathways()[pid]
    result = plan(origin, pw, facilities, capability_p, travel_fn=travel_fn, elapsed_minutes=elapsed_minutes,
                  first_stop=first_stop)
    if from_store:
        _call_first(result, pw, st, capability_p)
        _what_would_change(result, pw, st, origin, facilities)
    return {"pathway": pid, "urgency": result["urgency"], "objective": result["objective"],
            "options": to_options(result), "abstain": result["abstain"],
            "thresholds": result.get("thresholds"), "instructions": result["instructions"],
            "considered": result.get("considered"), "assumptions": result["assumptions"],
            "first_stop": result.get("first_stop"),
            "meta": {"implications": capability_p.describe() if implications else None, "origin_state": state, "origin_state_source": state_source,
                     "terrain": _terrain(state), "planner_data": st.meta if from_store else None}}


def _stage_caps(stage, capability_p=None, fid=None):
    """The stage's capabilities: requires_all, plus per requires_any group the best tag for fid (every tag
    of the group when no facility is given)."""
    caps = list(stage["requires_all"])
    for group in stage["requires_any"]:
        caps += [max(group, key=lambda c: capability_p(fid, c)[0])] if fid else list(group)
    return caps


def _call_first(result, pathway, st, capability_p):
    """A stop that rests on a CALL_FIRST pair may be offered only with "call first to check" wording."""
    stages = {s["id"]: s for s in pathway["stages"]}
    for p in result["plans"]:
        for stop in p["stops"]:
            caps = [c for c in _stage_caps(stages[stop["stage"]], capability_p, stop["facility_id"])
                    if st.band(stop["facility_id"], c) == "CALL_FIRST"]
            stop["call_first"] = bool(caps)
            if caps:
                words = ", ".join(c.replace("_", " ") for c in caps)
                stop["flags"].append(f"Call first to check: {words} is not confirmed in our data.")


def _what_would_change(result, pathway, st, origin, facilities):
    """vs_direct.what_would_change: a facility nearer than the first stop that model v2 does not rule out for the
    first stop's stage (every v2 tag LIKELY, CALL_FIRST or NO_SERVICE_TEXT), so a phone "yes" from it would make
    it the first stop. The best evidenced such facility is named (fewest tags not LIKELY), then the nearest."""
    stages = {s["id"]: s for s in pathway["stages"]}
    # ponytail: one scan of every facility per plan (about 8k, a few ms); index by grid cell if that grows
    for p in result["plans"]:
        if not p.get("vs_direct") or result["objective"] != "time_critical":
            continue
        first = p["stops"][0]
        stage = stages[first["stage"]]
        need = [[c] for c in stage["requires_all"] if c in st.v2_caps]
        need += [[c for c in g if c in st.v2_caps] for g in stage["requires_any"] if any(c in st.v2_caps for c in g)]
        km = hav_km(origin, (first["lat"], first["lon"]))
        best = None
        for f in facilities if need else ():
            d = hav_km(origin, (f["lat"], f["lon"]))
            if d >= km or f["id"] == first["facility_id"]:
                continue
            bands = [[st.band(f["id"], c) for c in g] for g in need]
            if not all(any(bs) for bs in bands):
                continue  # a tag v2 rates UNLIKELY: a phone call is not what is missing
            weak = sum(all(b != "LIKELY" for b in bs) for bs in bands)
            if best is None or (weak, d) < best[:2]:
                best = (weak, d, f)
        p["vs_direct"]["what_would_change"] = (
            f"A 'yes' from {best[2]['name']} on the phone would change this." if best else None)
        p["vs_direct"]["what_would_change_facility_id"] = best[2]["id"] if best else None

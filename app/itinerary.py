"""Multi-stop itinerary for /api/plan (issue #47): the planner's route, joined with the app's facts.

The planner (planner/, owned by tm-Art4v) decides where to go and in what order for services with a care pathway.
This module only reshapes its output for the page and adds what the app already knows about each stop: phone,
place and the verbatim sentences behind each evidence id. It never changes an order, a time or a probability.
`itinerary()` returns None when the planner is not available (not shipped, not built, or no pathway for the
service), so the single-destination options keep working on their own. The swap point for the model stays
`capability_p` inside planner.service (#11); nothing here reads a probability of its own.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from facts.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
MAX_QUOTES = 2

PURPOSE = {"stabilise": "First care: stabilise", "definitive": "Definitive care", "assess": "Assessment",
           "access": "Fistula or line for dialysis", "recurring": "Regular dialysis sessions"}
TYPE = {"direct": "Go straight there", "one_stop": "Stop for first care, then go on",
        "two_stop": "Two stops, then go on", "single_site": "One hospital for every stage",
        "two_sites": "Two places, each for its stage", "three_sites": "Three places, each for its stage"}
# kb/pathways capability tags, in plain words for stop_1_note and a stop's "Least sure" line (#121: no raw keys)
CAPABILITY_WORDS = {
    "emergency_24x7": "24x7 emergency care", "general_surgery_ot": "an operating theatre",
    "blood_transfusion": "blood transfusion", "ct_scan": "a CT scanner", "icu": "an ICU",
    "trauma_centre": "a trauma centre", "neurosurgery": "neurosurgery", "orthopaedics": "orthopaedic surgery",
    "iv_fluid_resuscitation": "IV fluids for burns", "burns_dressing": "burn dressing", "burn_unit": "a burn unit",
    "plastic_surgery": "plastic surgery", "basic_emoc": "basic emergency obstetric care",
    "comprehensive_emoc": "emergency caesarean section", "neonatal_stabilisation": "newborn stabilisation",
    "sncu": "a special newborn care unit", "nicu": "a newborn intensive care unit",
    "ecg": "an ECG", "thrombolysis": "clot-dissolving drugs for a heart attack", "pci_cath_lab": "a cath lab",
    "anti_snake_venom": "anti-snake venom", "ventilator": "a ventilator", "nephrology": "a kidney specialist",
    "laboratory": "a laboratory", "vascular_access_surgery": "fistula surgery for dialysis",
    "haemodialysis_unit": "a dialysis unit",
}


def capability_words(cap: object) -> str:
    """A kb/pathways capability tag in plain words; an unknown tag with its underscores as spaces."""
    return CAPABILITY_WORDS.get(str(cap), str(cap).replace("_", " "))


ROUTE_DOWN = "The suggested route could not be built just now. The options below do not depend on it."


def _planner():
    """planner.service, or None when the planner is not shipped with this app."""
    if str(ROOT) not in sys.path:
        sys.path.append(str(ROOT))  # planner/ and geo/ live at the repo root
    try:
        from planner import service
    except ImportError:
        return None
    return service


def _quotes(eng: Engine, ids: list[str]) -> list[dict]:
    out = []
    for cid in ids:
        c = eng.claims.get(cid)
        if c and not c[2] and c[3] != "other_facility":  # own offer sentences only, as on the option cards
            out.append({"claim_id": cid, "quote": c[1]})
        if len(out) == MAX_QUOTES:
            break
    return out


def place(*parts: object) -> str:
    """Town and district for a stop; skips NaN, None and blanks from the planner export (#78)."""
    words = [x.strip() for x in parts if isinstance(x, str) and x.strip()]
    return ", ".join(dict.fromkeys(x.title() if x.isupper() else x for x in words))


def _stop(eng: Engine, s: dict, question: str | None) -> dict:
    i = eng.fid.get(s["facility_id"])
    fb = s.get("fallback_if_turned_away")
    return {
        "facility_id": s["facility_id"], "name": s["name"],
        "place": place(s.get("town"), s.get("district")),
        "purpose": s["purpose"], "purpose_word": PURPOSE.get(s["purpose"], s["purpose"]),
        "eta_low": s["eta_low"], "eta_high": s["eta_high"], "dwell_minutes": s["dwell_minutes"],
        "p": s["p"], "weakest_capability": capability_words(s["weakest_capability"]),
        "weakest_capability_p": s["weakest_capability_p"], "question": question,
        "evidence": _quotes(eng, s["evidence_ids"]), "n_evidence": len(s["evidence_ids"]),
        "phone": eng._phone(i) if i is not None else None,
        "fallback": {"facility_id": fb["facility_id"], "name": fb["name"], "eta_minutes": fb["eta_minutes"],
                     "p": fb["p"]} if fb else None,
        "flags": list(s.get("flags") or []),
    }


def _vs_direct(v: dict | None, plan_type: str) -> dict | None:
    """The planner's one plain sentence against going direct, plus what would change the answer (#86 decision 3).
    The probabilities ride along for the record but are not in the sentence."""
    if not v or v.get("direct_minutes") is None:
        return None
    if plan_type in ("direct", "single_site") and not v.get("first_care_alternative"):
        return None  # a direct plan shows its sentence only when it names a first-care stop (#92)
    return {"text": v["text"], "what_would_change": v.get("what_would_change"),
            "direct_p_objective": v["direct_p_objective"], "plan_p_objective": v["plan_p_objective"],
            "direct_p_first_care": v["direct_p_first_care"], "plan_p_first_care": v["plan_p_first_care"]}


def _plan(eng: Engine, rank: int, o: dict) -> dict:
    r = o["route"]
    qs = {q["facility_id"]: q["question"] for q in o["call_ahead"]}
    t = r["totals"]
    return {
        "rank": rank, "type": r["type"], "type_word": TYPE.get(r["type"], r["type"]),
        "stops": [_stop(eng, s, qs.get(s["facility_id"])) for s in r["stops"]],
        "totals": {k: t[k] for k in ("minutes_to_definitive", "low", "high", "p_first_care", "p_treated")
                   if t.get(k) is not None},
        "window_checks": [{k: c[k] for k in ("check", "limit_minutes", "eta_minutes", "met")}
                          for c in r["window_checks"]],
        "vs_direct": _vs_direct(r.get("vs_direct"), r["type"]),
    }


def _lacks(groups: list[list[str]]) -> str:
    words = [capability_words(c) for g in groups for c in g]
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} or {words[-1]}"


def stop_1_note(route: dict, first_option: dict | None, first_stop: dict | None = None) -> str | None:
    """One plain line when route 1's first stop is not the options list's first choice (#86 decision 2). In an
    emergency the planner takes the list's first choice as stop 1 whenever it can give first care (#92), so the line
    says which capability it lacks (first_stop: what the planner found, planner.core)."""
    if not first_option or not route.get("stops"):
        return None
    s, d = route["stops"][0], route["stops"][-1]
    if s["facility_id"] == first_option["facility_id"]:
        return None
    y = first_option["name"]
    if first_stop and first_stop["facility_id"] == first_option["facility_id"]:
        if not first_stop["in_data"]:
            return f"The route starts at {s['name']}: the best option {y} is not in the route planner's data."
        if not first_stop["first_care"] and first_stop["missing_first_care"]:
            return (f"The route starts at {s['name']}: the best option {y} has no evidence of "
                    f"{_lacks(first_stop['missing_first_care'])} in our data, which first care needs.")
        alt = (route.get("vs_direct") or {}).get("first_care_alternative") or {}
        if s is d and alt.get("facility_id") == first_option["facility_id"]:
            return (f"The route goes straight to {s['name']}, about {s['eta_minutes']} min away, for definitive care "
                    f"in time; the best option {y} ({alt['eta_minutes']} min) can give first care if it is needed sooner.")
        if s is d and first_stop["missing_definitive"]:
            return (f"The route goes straight to {s['name']}, about {s['eta_minutes']} min away, for definitive care: "
                    f"the best option {y} has no evidence of {_lacks(first_stop['missing_definitive'])} in our data.")
    if s["purpose"] == "stabilise":  # the list's choice is too far for a stop to help: the nearest first care leads
        if s["eta_minutes"] < first_option["travel"]["minutes"]:
            return f"Stop first to stabilise at {s['name']}, which is nearer than the best option {y}."
        return f"Stop first to stabilise at {s['name']}; the best option {y} is ranked on this service alone."
    if s is d:
        return f"The route goes straight to {s['name']}, which has evidence for every part of this care; the best option {y} is ranked on this service alone."
    return f"The route starts at {s['name']} for {PURPOSE.get(s['purpose'], s['purpose']).lower()}; the best option {y} is ranked on this service alone."


def _has(groups: list[list[str]]) -> str:
    """Each group is met by any one of its capabilities: "blood transfusion, a CT scanner and an ICU"."""
    words = [" or ".join(CAPABILITY_WORDS.get(c, c.replace("_", " ")) for c in g) for g in groups]
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def lead_lines(route: dict, options: list[dict], first_stop: dict | None, note: str | None) -> dict[str, str]:
    """{facility_id: line} for an emergency whose route starts elsewhere than option 1 (#121): the route's first stop
    leads the cards with the stop_1_note reason in the positive, and the former option 1 says what it lacks."""
    s, d, y = route["stops"][0], route["stops"][-1], options[0]
    fs = first_stop if first_stop and first_stop["facility_id"] == y["facility_id"] else {}
    need = (fs.get("missing_first_care") if fs.get("in_data") and not fs.get("first_care") else
            fs.get("missing_definitive") if s is d else None)
    if not need:
        return {s["facility_id"]: f"First: {note[0].lower()}{note[1:]}" if note else "First: the suggested route starts here."}
    # "Nearest" only when it is nearer than every option and the low end of the stop's own estimate
    nearest = y["travel"]["minutes"] <= min(o["travel"]["minutes"] for o in options) and y["travel"]["minutes"] < s["eta_low"]
    return {s["facility_id"]: f"First: it has evidence of {_has(need)}, which {y['name']} does not show.",
            y["facility_id"]: ("Nearest, but our" if nearest else "Our")
            + f" data shows no evidence of {_lacks(need)} here."}


def itinerary(eng: Engine, service: str, lat: float, lon: float, first_option: dict | None = None) -> dict[str, Any] | None:
    svc = _planner()
    if svc is None or svc.pathway_for(service) is None:
        return None
    try:
        out = svc.plan_for_service(service, lat, lon, first_stop=(first_option or {}).get("facility_id"))
    except RuntimeError:  # planner/out not built on this server
        return None
    pw = svc.pathways()[out["pathway"]]
    meta = out.get("meta") or {}
    note = stop_1_note(out["options"][0]["route"], first_option, out.get("first_stop")) if out["options"] else None
    return {
        "pathway": out["pathway"], "pathway_name": pw["name"].split(":")[0], "urgency": out.get("urgency"),
        "abstain": (out.get("abstain") or {}).get("text"),
        "plans": [_plan(eng, k + 1, o) for k, o in enumerate(out["options"])],
        "stop_1_note": note,
        "first_stop": out.get("first_stop"),
        "meta": {"origin_state": meta.get("origin_state"),
                 "terrain": meta.get("terrain"),
                 "plans_considered": (out.get("considered") or {}).get("plans")},
    }


def attach(plan: dict, eng: Engine) -> dict:
    """Add `itinerary` to a /api/plan payload (None when there is no route for this service or server)."""
    loc = plan["location"]
    # The options do not need the planner: a broken planner file, pathway or geo table must never fail /api/plan
    # (#85 H3). Any error here leaves the options and says plainly that the route is missing.
    try:
        first = plan["options"][0] if plan.get("options") else None
        plan["itinerary"] = itinerary(eng, plan["query"]["service"], loc["lat"], loc["lon"], first)
        plan = lead_with_route(plan, eng)
    except Exception:  # noqa: BLE001 - deliberate boundary: the route is optional
        plan["itinerary"] = None
        plan["itinerary_note"] = ROUTE_DOWN
    return plan


# What card 1 asks on the phone when the route is only the fallback (lead on #126); other services use the label.
ASK = {"trauma_emergency": "Ask: do you take accident patients now?",
       "emergency_csection": "Ask: can you do an emergency C-section now?",
       "burn_care": "Ask: do you take burn patients now?"}


def fallback(route: dict, plan: dict) -> dict[str, str]:
    """Card 1 stays first; the route is what to do if it cannot treat."""
    s, d = route["stops"][0], route["stops"][-1]
    go = (f"the suggested route goes straight to {d['name']}, about {d['eta_low']} to {d['eta_high']} min away"
          if s is d else f"the suggested route stops at {s['name']} ({s['purpose_word'].lower()}), then goes on to "
          f"{d['name']}, about {d['eta_low']} to {d['eta_high']} min in all")
    label = plan["query"]["service_label"]["en"]
    return {"ask": ASK.get(plan["query"]["service"], f"Ask: can you give {label} now?"),
            "text": f"If they cannot treat: {go}."}


def lead_with_route(plan: dict, eng: Engine) -> dict:
    """One answer above the fold (#121): in an emergency with a route, option 1 is the route's first stop when that
    stop is within the time window or no farther than option 1. The plan is rebuilt by the engine with that lead, so
    why_not, "if the first says no", read-aloud and the journey card follow; the route is not recomputed and the
    stop_1_note it no longer needs is dropped. Otherwise option 1 keeps its place with a question to ask, and the
    route is framed as the fallback (lead on #126: a far hospital never displaces a near first call)."""
    if not plan.get("itinerary"):
        return plan
    first_stop = plan["itinerary"].get("first_stop")  # the planner's view of option 1; not sent to the page
    it = {k: v for k, v in plan["itinerary"].items() if k != "first_stop"}
    plan = {**plan, "itinerary": it}
    route = it["plans"][0] if it["plans"] else None
    if plan.get("profile") != "emergency" or not route or not plan.get("options") \
            or route["stops"][0]["facility_id"] == plan["options"][0]["facility_id"]:
        return plan
    loc = plan["location"]
    lead = lead_lines(route, plan["options"], first_stop, it["stop_1_note"])
    fresh = eng.plan(plan["query"]["service"], loc["lat"], loc["lon"], loc["accuracy_m"], loc["source"], lead=lead)
    head, minutes = fresh["options"][0], fresh["options"][0]["travel"]["minutes"]
    if head["facility_id"] == route["stops"][0]["facility_id"] and (
            minutes <= plan["time_window"]["window_min"] or minutes <= plan["options"][0]["travel"]["minutes"]):
        return {**plan, **fresh, "itinerary": {**it, "stop_1_note": None}}
    return {**plan, "itinerary": {**it, "stop_1_note": None, "fallback": fallback(route, plan)}}

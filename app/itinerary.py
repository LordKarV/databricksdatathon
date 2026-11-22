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
        "two_stop": "Two stops, then go on", "single_site": "One hospital for every stage"}


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
        "p": s["p"], "weakest_capability": str(s["weakest_capability"]).replace("_", " "),
        "weakest_capability_p": s["weakest_capability_p"], "question": question,
        "evidence": _quotes(eng, s["evidence_ids"]), "n_evidence": len(s["evidence_ids"]),
        "phone": eng._phone(i) if i is not None else None,
        "fallback": {"facility_id": fb["facility_id"], "name": fb["name"], "eta_minutes": fb["eta_minutes"],
                     "p": fb["p"]} if fb else None,
        "flags": list(s.get("flags") or []),
    }


def _vs_direct(v: dict | None, eng: Engine, plan_type: str) -> dict | None:
    if not v or plan_type in ("direct", "single_site") or v.get("direct_minutes") is None:
        return None
    i = eng.fid.get(v.get("direct_facility_id"))
    return {"direct_name": eng._f("name", i) if i is not None else "the best direct option",
            "direct_minutes": v["direct_minutes"],
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
        "vs_direct": _vs_direct(r.get("vs_direct"), eng, r["type"]),
    }


def itinerary(eng: Engine, service: str, lat: float, lon: float) -> dict[str, Any] | None:
    svc = _planner()
    if svc is None or svc.pathway_for(service) is None:
        return None
    try:
        out = svc.plan_for_service(service, lat, lon)
    except RuntimeError:  # planner/out not built on this server
        return None
    pw = svc.pathways()[out["pathway"]]
    meta = out.get("meta") or {}
    return {
        "pathway": out["pathway"], "pathway_name": pw["name"].split(":")[0], "urgency": out.get("urgency"),
        "abstain": (out.get("abstain") or {}).get("text"),
        "plans": [_plan(eng, k + 1, o) for k, o in enumerate(out["options"])],
        "meta": {"stub": bool(meta.get("stub")), "origin_state": meta.get("origin_state"),
                 "terrain": meta.get("terrain"),
                 "plans_considered": (out.get("considered") or {}).get("plans")},
    }


def attach(plan: dict, eng: Engine) -> dict:
    """Add `itinerary` to a /api/plan payload (None when there is no route for this service or server)."""
    loc = plan["location"]
    plan["itinerary"] = itinerary(eng, plan["query"]["service"], loc["lat"], loc["lon"])
    return plan

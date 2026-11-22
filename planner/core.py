"""Multi-stop referral planner.

Given an origin, a pathway from kb/pathways/care_pathways.json, a list of facilities, a
probability function and a travel-time function, return the best plan and two alternatives.

    plan(origin, pathway, facilities, capability_p, travel_fn=None, state=None, elapsed_minutes=0, first_stop=None)

Inputs
- origin: (lat, lon).
- pathway: one entry of care_pathways.json.
- facilities: list of dicts with at least id, name, lat, lon. Other keys are passed through.
- capability_p(facility_id, capability) -> (p, evidence_ids): P(this facility can deliver this
  capability). This is the only place probabilities come from, so the model can replace the stub.
- travel_fn(origin, destinations) -> rows shaped like geo.travel.travel_minutes. Default: the
  geo.travel estimate with no network calls.

Method
- A stage is delivered by a facility with probability = product over requires_all of p, times,
  for each requires_any group, the largest p in the group (capabilities treated as independent).
- Emergency pathways (objective time_critical):
    direct   origin -> definitive facility D
    1 stop   origin -> stabilising facility S -> D
  A stop is only considered when the pathway's add_stop_only_if rule holds for D (travel to D is
  beyond the threshold), S is closer than D and inside a detour corridor (not for stop 1 by rule, below).
  If a facility turns the patient away, TURNAWAY_MINUTES are lost and the patient goes on: from S
  to D, from D to the best fallback definitive facility F.
  Objective, in order: (1) P(stabilised by T1 and definitive care by T2); (2) P(stabilised by T1);
  (3) expected minutes to definitive care, where an untreated outcome costs FAIL_PENALTY_MINUTES
  on top of the last arrival. T1 is the stabilising stage window, else the add-stop threshold.
  T2 is the definitive stage window. Reaching definitive care counts as stabilised. With no
  window the factor is just P(delivered).
  A stop plan is dropped unless it beats the best direct plan by MARGIN on (1), or matches it on
  (1) and beats it by MARGIN on (2), and, when going direct is within the first-care window, it gives
  first care sooner than going direct.
  Stop 1 (#92): the nearest plausible first-care stop leads, p is only a filter and a tie-break. The
  caller's first choice (first_stop, the app's options list #1) is stop 1 when it can give first care,
  that is deliver the first stage or the definitive one; otherwise the nearest place that can, by
  travel minutes. With a first stage, that place is the stop on the way to every definitive
  candidate (no gate, no corridor). Definitive care is nearest first too: the plan that reaches a
  plausible definitive facility within the window soonest, else the soonest beyond it; the objective
  only orders plans that arrive in the same minute. The best direct plan, the one the sentence
  compares with, is chosen the same way. When the rule above
  drops every plan through it, the plan with the nearest first stop leads (a direct plan's first stop
  is its definitive facility). The result's first_stop says whether the caller's choice could give
  first care and what it lacks.
- Scheduled pathways (objective fewest_trips): one facility per stage; least travel over
  PLANNING_WEEKS first (one return trip per one-off stage, per_week return trips for the recurring
  stage), then fewer distinct sites. Up to 2 stops before the recurring site. Every plan makes the
  same number of trips, so "fewest trips" comes down to the travel they cost; ranking by sites
  first sent patients past a near dialysis unit to a far hospital that had everything.

All times are minutes from now. elapsed_minutes (time already passed since the pathway's clock
started) is added when checking windows.

Constants below are planner assumptions, not guideline values; they are echoed in the output.
Standard library only.
"""
import math
from itertools import groupby, product

TURNAWAY_MINUTES = 15       # time lost at a facility that cannot deliver the stage
FAIL_PENALTY_MINUTES = 120  # extra cost of ending untreated, for ordering only
MARGIN = 0.05               # a stop must raise the objective by this much over the best direct plan
MAX_KM = 150.0              # search radius (travel constants are measured up to 150 km)
MIN_P = 0.05                # facilities below this for a stage are not candidates
N_DEFINITIVE = 6
N_STABILISE = 6
DETOUR_FACTOR = 1.6         # corridor: straight o->S->D at most this times straight o->D, plus slack
DETOUR_SLACK_KM = 10.0
SCHEDULED_MIN_P = 0.3
SCHEDULED_TOP = 5
PLANNING_WEEKS = 12

ASSUMPTIONS = {
    "turnaway_minutes": TURNAWAY_MINUTES, "fail_penalty_minutes": FAIL_PENALTY_MINUTES, "margin": MARGIN,
    "max_km": MAX_KM, "min_p": MIN_P, "detour_factor": DETOUR_FACTOR, "detour_slack_km": DETOUR_SLACK_KM,
    "scheduled_min_p": SCHEDULED_MIN_P, "planning_weeks": PLANNING_WEEKS,
    "independence": "capabilities and facilities are treated as independent",
    "fallback_depth": "one fallback definitive facility",
}


def hav_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _pt(f):
    return (f["lat"], f["lon"])


def default_travel_fn(state=None):
    from geo import travel

    def fn(origin, destinations):
        return travel.travel_minutes(origin, destinations, use_osrm=False, state=state)
    return fn


def stage_p(facility_id, stage, capability_p):
    """(p, evidence_ids, weakest capability, its p) for one facility delivering one stage."""
    p, evidence, weakest = 1.0, [], (None, 1.0)
    picks = [(cap, *capability_p(facility_id, cap)) for cap in stage["requires_all"]]
    for group in stage["requires_any"]:
        picks.append(max(((cap, *capability_p(facility_id, cap)) for cap in group), key=lambda x: x[1]))
    for cap, cp, ids in picks:
        p *= cp
        evidence += [i for i in ids if i not in evidence]
        if cp < weakest[1]:
            weakest = (cap, cp)
    return p, evidence, weakest[0], weakest[1]


def stage_notes(facility_id, stage, capability_p):
    """How each capability of the stage was reached when it was not the record's own text: implied
    by another capability, or taken from a list. Empty unless capability_p has an explain()."""
    explain = getattr(capability_p, "explain", None)
    if explain is None:
        return []
    caps = list(stage["requires_all"])
    for group in stage["requires_any"]:
        caps.append(max(group, key=lambda c: capability_p(facility_id, c)[0]))
    out = []
    for cap in caps:
        note = explain(facility_id, cap)
        if note:
            out.append({"capability": cap, **note})
    return out


def gate_minutes(pathway):
    """Threshold of the pathway's add_stop_only_if rule, or None when it has none."""
    for r in pathway["rules"]:
        if r["type"] == "add_stop_only_if" and "definitive_travel_minutes_gt" in (r.get("condition") or {}):
            return r["condition"]["definitive_travel_minutes_gt"], r
    return None, None


def _after_stabilise_max(pathway):
    for r in pathway["rules"]:
        c = r.get("condition") or {}
        if "after_stabilise_minutes_max" in c:
            return c["after_stabilise_minutes_max"], c.get("after_stabilise_minutes_min", 0), r
    return None, 0, None


def _candidates(origin, stage, facilities, capability_p, min_p):
    out = []
    for f in facilities:
        km = hav_km(origin, _pt(f))
        if km > MAX_KM:
            continue
        p, ev, weak, weak_p = stage_p(f["id"], stage, capability_p)
        if p >= min_p:
            out.append({"f": f, "km": km, "p": p, "evidence_ids": ev, "weakest": weak, "weakest_p": weak_p,
                        "notes": stage_notes(f["id"], stage, capability_p)})
    return out


def _stop(c, stage, purpose, eta, low, high, dwell, leg, fallback=None):
    f = c["f"]
    s = {"facility_id": f["id"], "name": f.get("name"), "lat": f["lat"], "lon": f["lon"],
         "town": f.get("town"), "district": f.get("district"), "state": f.get("state"),
         "stage": stage["id"], "purpose": purpose,
         "eta_minutes": round(eta), "eta_low": round(low), "eta_high": round(high),
         "dwell_minutes": dwell, "p": round(c["p"], 4),
         "weakest_capability": c["weakest"], "weakest_capability_p": round(c["weakest_p"], 4),
         "evidence_ids": c["evidence_ids"], "capability_notes": c.get("notes", []), "leg": leg,
         "flags": list(f.get("flags") or [])}
    if fallback is not None:
        s["fallback_if_turned_away"] = fallback
    return s


def _score(outcomes, t1, t2, elapsed):
    """outcomes: list of (probability, t_stabilised, t_definitive or None, t2 override or None,
    stabilised: bool). For an unstabilised, untreated outcome t_stabilised holds the last arrival."""
    p_ok = p_treated = exp = p_first = 0.0
    last = 0.0
    for p, t_stab, t_def, t2o, stabilised in outcomes:
        if stabilised and (t1 is None or t_stab + elapsed <= t1):
            p_first += p
        if t_def is None:
            last = max(last, t_stab)
            continue
        last = max(last, t_def)
        p_treated += p
        exp += p * t_def
        lim2 = t2 if t2o is None else t2o
        if (t1 is None or t_stab + elapsed <= t1) and (lim2 is None or t_def + elapsed <= lim2):
            p_ok += p
    untreated = max(0.0, 1.0 - p_treated)
    expected_all = exp + untreated * (last + FAIL_PENALTY_MINUTES)
    return {"p_objective": p_ok, "p_first_care": p_first, "p_treated": p_treated,
            "minutes_if_treated": exp / p_treated if p_treated > 0 else None, "expected_minutes": expected_all}


def _window_checks(pathway, plan_stops, t1, t1_basis, t2, t2_basis, elapsed):
    checks = []
    stab = next((s for s in plan_stops if s["purpose"] == "stabilise"), None)
    definitive = next(s for s in plan_stops if s["purpose"] == "definitive")
    first_care = stab or definitive
    if t1 is not None:
        checks.append({"check": "first care (stabilised)", "limit_minutes": t1, "basis": t1_basis,
                       "at_facility_id": first_care["facility_id"], "eta_minutes": first_care["eta_minutes"] + elapsed,
                       "met": first_care["eta_minutes"] + elapsed <= t1,
                       "met_at_high_estimate": first_care["eta_high"] + elapsed <= t1})
    if t2 is not None:
        checks.append({"check": "definitive care", "limit_minutes": t2, "basis": t2_basis,
                       "at_facility_id": definitive["facility_id"], "eta_minutes": definitive["eta_minutes"] + elapsed,
                       "met": definitive["eta_minutes"] + elapsed <= t2,
                       "met_at_high_estimate": definitive["eta_high"] + elapsed <= t2})
    return checks


def _instructions(pathway):
    keep = ("never_delay", "before_transfer", "caution", "skip_stop_if", "refer_if")
    return [{"rule": r["id"], "type": r["type"], "when": r["when"], "then": r["then"], "basis": r["basis"],
             "source": r.get("source")} for r in pathway["rules"] if r["type"] in keep]


def _missing(fid, stage, capability_p):
    """Capability groups of the stage this facility has no usable evidence for (p below MIN_P): [tag] per
    requires_all tag, the whole group per requires_any group. The weakest tag when each passes alone but the
    product does not."""
    out = [[c] for c in stage["requires_all"] if capability_p(fid, c)[0] < MIN_P]
    out += [list(g) for g in stage["requires_any"] if all(capability_p(fid, c)[0] < MIN_P for c in g)]
    p, _, weak, _ = stage_p(fid, stage, capability_p)
    return out or ([[weak]] if p < MIN_P else [])


def _anchor(origin, first_care, travel_fn, first_stop):
    """Stop 1 of an emergency route (#92): first_stop when it can give first care, else the nearest place that can
    by travel minutes, the higher p on a tie. first_care: {facility id: candidate}."""
    if first_stop in first_care:
        return first_stop
    near = sorted(first_care.values(), key=lambda c: c["km"])[:N_STABILISE]
    if not near:
        return None
    rows = travel_fn(origin, [_pt(c["f"]) for c in near])
    return min(zip(near, rows), key=lambda x: (round(x[1]["minutes"]), -x[0]["p"]))[0]["f"]["id"]


def _emergency(origin, pathway, facilities, capability_p, travel_fn, elapsed, first_stop=None):
    stages = pathway["stages"]
    definitive = stages[-1]
    stab = stages[0] if len(stages) > 1 else None
    gate, gate_rule = gate_minutes(pathway) if stab else (None, None)
    after_max, after_min, after_rule = _after_stabilise_max(pathway)

    if stab and stab.get("window"):
        t1, t1_basis = stab["window"]["minutes"], f"{stab['id']} window ({stab['window']['basis']})"
    elif gate is not None:
        t1, t1_basis = gate, f"add-stop threshold of rule {gate_rule['id']} ({gate_rule['basis']})"
    else:
        t1, t1_basis = None, None
    if definitive.get("window"):
        t2, t2_basis = definitive["window"]["minutes"], f"{definitive['id']} window ({definitive['window']['basis']})"
    else:
        t2, t2_basis = None, None

    all_d = _candidates(origin, definitive, facilities, capability_p, MIN_P)
    all_s = _candidates(origin, stab, facilities, capability_p, MIN_P) if stab else []
    first_care = {}
    for c in all_s + all_d:
        if c["p"] > first_care.get(c["f"]["id"], {"p": -1.0})["p"]:
            first_care[c["f"]["id"]] = c
    anchor = _anchor(origin, first_care, travel_fn, first_stop)
    a_def = next((c for c in all_d if c["f"]["id"] == anchor), None)
    a_stab = None if a_def else next((c for c in all_s if c["f"]["id"] == anchor), None)
    info = None
    if first_stop is not None:
        known = any(f["id"] == first_stop for f in facilities)
        info = {"facility_id": first_stop, "in_data": known, "first_care": first_stop in first_care,
                "missing_first_care": _missing(first_stop, stages[0], capability_p) if known else [],
                "missing_definitive": _missing(first_stop, definitive, capability_p) if known else []}
    cand_d = sorted(all_d, key=lambda c: (c["km"] + 5.0) / c["p"])[:N_DEFINITIVE]
    # the nearest plausible ones too: definitive care is nearest first (#92), p does not buy minutes
    cand_d += [c for c in sorted(all_d, key=lambda c: c["km"])[:N_DEFINITIVE] if c not in cand_d]
    if a_def is not None and a_def not in cand_d:
        cand_d.append(a_def)
    if not cand_d:
        return [], {"t1": t1, "t2": t2, "gate": gate, "first_stop": info}
    rows_od = travel_fn(origin, [_pt(c["f"]) for c in cand_d])
    # fallback for each D: the other definitive candidate with the least expected extra time
    fallback = {}
    for i, c in enumerate(cand_d):
        others = [o for j, o in enumerate(cand_d) if j != i]
        if not others:
            continue
        rows = travel_fn(_pt(c["f"]), [_pt(o["f"]) for o in others])
        k = min(range(len(others)), key=lambda j: (rows[j]["minutes"] + TURNAWAY_MINUTES) / others[j]["p"])
        fallback[c["f"]["id"]] = (others[k], rows[k])

    def tail(c_d, t_arrive, low, high):
        """Outcomes at D after arriving at t_arrive: delivered, or turned away and on to F."""
        out = [(c_d["p"], t_arrive, None)]
        fb = fallback.get(c_d["f"]["id"])
        fb_json = None
        if fb:
            f_c, f_row = fb
            t_f = t_arrive + TURNAWAY_MINUTES + f_row["minutes"]
            out.append(((1 - c_d["p"]) * f_c["p"], t_f, None))
            out.append(((1 - c_d["p"]) * (1 - f_c["p"]), None, t_f))
            fb_json = {"facility_id": f_c["f"]["id"], "name": f_c["f"].get("name"), "p": round(f_c["p"], 4),
                       "eta_minutes": round(t_f), "leg": f_row, "evidence_ids": f_c["evidence_ids"]}
        else:
            out.append((1 - c_d["p"], None, t_arrive))
        return out, fb_json

    plans = []
    for c_d, row in zip(cand_d, rows_od):
        t_d = row["minutes"]
        outs, fb_json = tail(c_d, t_d, row["low"], row["high"])
        outcomes = [(p, t if t is not None else t_fail, t, None, t is not None) for p, t, t_fail in outs]
        sc = _score(outcomes, t1, t2, elapsed)
        stops = [_stop(c_d, definitive, "definitive", t_d, row["low"], row["high"], None, row, fb_json)]
        plans.append({"type": "direct", "stops": stops, **sc, "_d": c_d, "_row": row, "_anchor": c_d is a_def})

    if stab and gate is not None:
        far = [(c, r) for c, r in zip(cand_d, rows_od) if r["minutes"] > gate]
        if far or a_stab is not None:
            cand_s = sorted(all_s, key=lambda c: (c["km"] + 5.0) / c["p"])[:N_STABILISE]
            if a_stab is not None and a_stab not in cand_s:
                cand_s.append(a_stab)
            rows_os = travel_fn(origin, [_pt(c["f"]) for c in cand_s]) if cand_s else []
            dwell = stab["dwell_minutes"]["typical"]
            for c_s, row_s in zip(cand_s, rows_os):
                is_a = c_s is a_stab  # stop 1 by rule: on the way or not, it is where first care is nearest
                usable = [(c, r) for c, r in (zip(cand_d, rows_od) if is_a else far) if c["f"]["id"] != c_s["f"]["id"]
                          and (is_a or (c_s["km"] < c["km"] and
                          c_s["km"] + hav_km(_pt(c_s["f"]), _pt(c["f"])) <= DETOUR_FACTOR * c["km"] + DETOUR_SLACK_KM))]
                if not usable:
                    continue
                rows_sd = travel_fn(_pt(c_s["f"]), [_pt(c["f"]) for c, _ in usable])
                for (c_d, _), row_sd in zip(usable, rows_sd):
                    t_s = row_s["minutes"]
                    wait = max(dwell, after_min - row_sd["minutes"]) if after_max is not None else dwell
                    t_ok = t_s + wait + row_sd["minutes"]            # stabilised at S, then on to D
                    t_no = t_s + TURNAWAY_MINUTES + row_sd["minutes"]  # S could not help
                    outs_ok, fb_json = tail(c_d, t_ok, 0, 0)
                    outs_no, _ = tail(c_d, t_no, 0, 0)
                    t2_ok = None if after_max is None else t_s + after_max
                    outcomes = [(c_s["p"] * p, t_s, t, t2_ok, True) for p, t, _ in outs_ok]
                    outcomes += [((1 - c_s["p"]) * p, t if t is not None else t_fail, t, None, t is not None)
                                 for p, t, t_fail in outs_no]
                    sc = _score(outcomes, t1, t2, elapsed)
                    low = row_s["low"] + wait + row_sd["low"]
                    high = row_s["high"] + wait + row_sd["high"]
                    stops = [_stop(c_s, stab, "stabilise", t_s, row_s["low"], row_s["high"], wait, row_s),
                             _stop(c_d, definitive, "definitive", t_ok, low, high, None, row_sd, fb_json)]
                    plans.append({"type": "one_stop", "stops": stops, **sc, "_d": c_d, "_anchor": is_a,
                                  "_t2_with_stop": t2_ok, "_after_rule": after_rule})
    return plans, {"t1": t1, "t1_basis": t1_basis, "t2": t2, "t2_basis": t2_basis, "gate": gate,
                   "gate_rule": gate_rule["id"] if gate_rule else None, "first_stop": info}


def _order(plans):
    """Best first. A plan leads when no other beats it by MARGIN on (1) P(care in time), then on (2) P(first care
    in time); among plans within MARGIN on both, the fewest expected minutes wins. Model probabilities a few
    hundredths apart are not a reason to send a patient 15 minutes farther (#86: the route's first stop and
    the options list disagreed on 0.01)."""
    rest, out = list(plans), []
    while rest:
        top = max(p["p_objective"] for p in rest)
        near = [p for p in rest if p["p_objective"] > top - MARGIN]
        top = max(p["p_first_care"] for p in near)
        near = [p for p in near if p["p_first_care"] > top - MARGIN]
        best = min(near, key=lambda p: (p["expected_minutes"], -p["p_objective"], -p["p_first_care"]))
        out.append(best)
        rest.remove(best)
    return out


def _beats_direct(p, best_direct, t1, elapsed):
    """A stop plan's clear advantage over the best direct plan: MARGIN on (1), or equal on (1) and MARGIN on (2);
    and when going direct is within the first-care window, first care sooner than going direct."""
    if best_direct is None:
        return True
    d = best_direct["stops"][-1]["eta_minutes"]
    if t1 is not None and d + elapsed <= t1 and p["stops"][0]["eta_minutes"] >= d:
        return False
    better = p["p_objective"] >= best_direct["p_objective"] + MARGIN
    same = p["p_objective"] >= best_direct["p_objective"] - 1e-9
    return better or (same and p["p_first_care"] >= best_direct["p_first_care"] + MARGIN)


def _def_window(p, ctx):
    """Deadline for reaching definitive care on this plan: the definitive window (moved by an after-stabilise rule),
    else for a direct plan the first-care window, since arriving there is first care. None: no deadline."""
    if p.get("_t2_with_stop") is not None:
        return p["_t2_with_stop"]
    if ctx["t2"] is not None:
        return ctx["t2"]
    return ctx["t1"] if p["type"] == "direct" else None


def _nearest_first(plans, ctx, elapsed):
    """Emergency order (#92): plans that reach definitive care within the window first, then by minutes to it; plans
    equally near (same minute) are ordered by _order, so p only breaks ties, with the same MARGIN."""
    def key(p):
        w, eta = _def_window(p, ctx), p["stops"][-1]["eta_minutes"]
        return (w is not None and eta + elapsed > w, eta)
    out = []
    for _, group in groupby(sorted(plans, key=key), key=key):
        out += _order(list(group))
    return out


def _finish_emergency(plans, ctx, pathway, elapsed):
    directs = _nearest_first([p for p in plans if p["type"] == "direct"], ctx, elapsed)
    best_direct = directs[0] if directs else None
    kept, dropped = list(directs), 0
    for p in plans:
        if p["type"] != "one_stop":
            continue
        if _beats_direct(p, best_direct, ctx["t1"], elapsed):
            kept.append(p)
        else:
            dropped += 1
    kept = _nearest_first(kept, ctx, elapsed)
    # stop 1 by rule (#92): the plan through the anchor with the nearest definitive care when it survived the rule
    # above, else the plan with the nearest first stop (a direct plan's first stop is its definitive facility)
    lead = next((p for p in kept if p.get("_anchor")), None)
    if lead is None:
        nearest = min(p["stops"][0]["eta_minutes"] for p in kept)
        lead = next(p for p in kept if p["stops"][0]["eta_minutes"] == nearest)
    kept = [lead] + [p for p in kept if p is not lead]
    by_sig = {tuple(s["facility_id"] for s in p["stops"]): p for p in plans}
    chosen, seen = [], set()
    for p in kept:
        sig = tuple(s["facility_id"] for s in p["stops"])
        d_id = p["stops"][-1]["facility_id"]
        # alternatives must differ from the best plan in the definitive facility or in having a stop
        if sig in seen or sum(1 for c in chosen if c["stops"][-1]["facility_id"] == d_id and c["type"] == p["type"]):
            continue
        seen.add(sig)
        chosen.append(p)
        if len(chosen) == 3:
            break
    out = []
    for p in chosen:
        t2 = ctx["t2"]
        t2_basis = ctx.get("t2_basis")
        if p["type"] == "one_stop" and p.get("_t2_with_stop") is not None:
            t2, t2_basis = p["_t2_with_stop"], f"rule {p['_after_rule']['id']} ({p['_after_rule']['basis']}), counted from stabilisation"
        checks = _window_checks(pathway, p["stops"], ctx["t1"], ctx.get("t1_basis"), t2, t2_basis, elapsed)
        vs = None
        if best_direct is not None:
            gain = p["p_objective"] - best_direct["p_objective"]
            same_d = by_sig.get((p["stops"][0]["facility_id"], best_direct["stops"][-1]["facility_id"]))
            text, shown = _vs_direct_text(p, best_direct, ctx["t1"], elapsed, same_d, p is chosen[0])
            vs = {"direct_facility_id": best_direct["stops"][-1]["facility_id"],
                  "direct_name": best_direct["stops"][-1]["name"],
                  "direct_minutes": best_direct["stops"][-1]["eta_minutes"],
                  "direct_p_objective": round(best_direct["p_objective"], 4),
                  "direct_p_first_care": round(best_direct["p_first_care"], 4),
                  "plan_p_objective": round(p["p_objective"], 4), "plan_p_first_care": round(p["p_first_care"], 4),
                  "gain": round(gain, 4), "text": text, "text_numbers": shown}
        out.append({"type": p["type"], "stops": p["stops"],
                    "totals": {"minutes_to_definitive": p["stops"][-1]["eta_minutes"],
                               "low": p["stops"][-1]["eta_low"], "high": p["stops"][-1]["eta_high"],
                               "p_objective": round(p["p_objective"], 4), "p_first_care": round(p["p_first_care"], 4),
                               "p_treated": round(p["p_treated"], 4),
                               "expected_minutes": round(p["expected_minutes"], 1),
                               "minutes_if_treated": None if p["minutes_if_treated"] is None else round(p["minutes_if_treated"], 1)},
                    "window_checks": checks, "vs_direct": vs})
    return out, dropped


def _vs_direct_text(p, best_direct, t1, elapsed, same_d=None, lead=True):
    """One plain sentence against going straight to the best direct facility, and every number it quotes.
    Minutes only: the probabilities stay in the vs_direct fields, not in the sentence (#86 decision 3).
    A stop plan says why it stops when going direct is within the window (first care sooner), and why its
    definitive facility is not the direct one. same_d: the plan with the same first stop and the direct one's
    definitive facility, when there is one; lead: p is the best plan."""
    d = best_direct["stops"][-1]
    shown = {"direct_minutes": d["eta_minutes"]}
    direct = f"Going straight to {d['name']} takes {d['eta_minutes']} min"
    within = False
    if t1 is not None:
        shown["window_minutes"] = t1
        within = d["eta_minutes"] + elapsed <= t1
        direct += f", within the {t1}-minute window" if within else f" and misses the {t1}-minute window"
    if p["type"] == "one_stop":
        s, e = p["stops"]
        shown["first_care_minutes"] = s["eta_minutes"]
        text = f"{direct}; stopping first at {s['name']} gives first care"
        if within:  # _beats_direct keeps such a stop only when first care comes sooner
            shown["minutes_sooner"] = d["eta_minutes"] - s["eta_minutes"]
            text += f" {shown['minutes_sooner']} min sooner,"
        text += f" in about {s['eta_minutes']} min"
        if e["facility_id"] != d["facility_id"]:
            shown["plan_minutes"] = e["eta_minutes"]
            why = _why_other(p, d, same_d, lead)
            text += f", and the route then goes on to {e['name']} (about {e['eta_minutes']} min), {why}"
        return f"{text}.", shown
    if p is best_direct:
        return f"{direct}.", shown
    shown["plan_minutes"] = p["stops"][-1]["eta_minutes"]
    return f"{direct}; this route goes straight to {p['stops'][-1]['name']} instead, in about {shown['plan_minutes']} min.", shown


def _why_other(p, d, same_d, lead):
    """Why a stop plan's definitive facility is not the direct one (d), in words that hold for this plan. Only the
    lead plan was ranked above same_d; an alternative just names the other hospital."""
    if same_d is not None and same_d["stops"][-1]["eta_minutes"] > p["stops"][-1]["eta_minutes"]:
        return f"which is quicker to reach from {p['stops'][0]['name']} than {d['name']}"
    if p["stops"][-1]["p"] > d["p"]:
        return f"which has stronger evidence than {d['name']} for definitive care"
    if lead and same_d is not None:
        return f"which the route rates higher than {d['name']} for definitive care"
    return f"rather than {d['name']}"


def _scheduled(origin, pathway, facilities, capability_p, travel_fn):
    stages = pathway["stages"]
    per_stage = []
    for st in stages:
        c = _candidates(origin, st, facilities, capability_p, SCHEDULED_MIN_P)
        c.sort(key=lambda x: (x["km"] + 5.0) / x["p"])
        per_stage.append(c[:SCHEDULED_TOP])
    if any(not c for c in per_stage):
        return [], [st["id"] for st, c in zip(stages, per_stage) if not c]
    # a facility that can deliver every stage joins every stage's list, so one-site plans are found
    all_stage = {}
    for st in stages:
        for c in _candidates(origin, st, facilities, capability_p, SCHEDULED_MIN_P):
            all_stage.setdefault(c["f"]["id"], {})[st["id"]] = c
    whole = sorted((v for v in all_stage.values() if len(v) == len(stages)),
                   key=lambda v: next(iter(v.values()))["km"])[:SCHEDULED_TOP]
    for v in whole:
        for st, cs in zip(stages, per_stage):
            if all(c["f"]["id"] != v[st["id"]]["f"]["id"] for c in cs):
                cs.append(v[st["id"]])
    uniq = {c["f"]["id"]: c for cs in per_stage for c in cs}
    ids = list(uniq)
    rows = dict(zip(ids, travel_fn(origin, [_pt(uniq[i]["f"]) for i in ids])))
    plans = []
    for combo in product(*per_stage):
        sites = len({c["f"]["id"] for c in combo})
        burden = 0.0
        p = 1.0
        for st, c in zip(stages, combo):
            trips = (st.get("repeat") or {}).get("per_week", 0) * PLANNING_WEEKS or 1
            burden += 2 * rows[c["f"]["id"]]["minutes"] * trips
            p *= c["p"]
        plans.append((sites, burden, -p, combo))
    # least travel over the planning weeks first (the session trips dominate), then fewer sites
    plans.sort(key=lambda x: (x[1], x[0], x[2]))
    def build(sites, burden, neg_p, combo):
        stops = []
        for st, c in zip(stages, combo):
            r = rows[c["f"]["id"]]
            s = _stop(c, st, st["purpose"], r["minutes"], r["low"], r["high"],
                      (st.get("dwell_minutes") or st.get("session_minutes") or {}).get("typical"), r)
            if st.get("repeat"):
                s["per_week"] = st["repeat"]["per_week"]
            if st.get("window"):
                s["wait_before_next_stage_minutes"] = st["window"]["minutes"]
            stops.append(s)
        return {"type": {1: "single_site", 2: "two_sites"}.get(sites, "three_sites"), "stops": stops,
                "totals": {"distinct_sites": sites, "stops_before_recurring": sites - 1,
                           "travel_minutes_over_planning_weeks": round(burden), "planning_weeks": PLANNING_WEEKS,
                           "one_way_minutes_to_recurring_site": stops[-1]["eta_minutes"], "p_all_stages": round(-neg_p, 4)},
                "window_checks": [], "vs_direct": None, "_last": combo[-1]["f"]["id"], "_sites": sites}

    out, seen = [], set()
    for sites, burden, neg_p, combo in plans:
        sig = tuple(c["f"]["id"] for c in combo)
        if sig in seen or any(o["_last"] == sig[-1] and o["_sites"] == sites for o in out):
            continue
        seen.add(sig)
        out.append(build(sites, burden, neg_p, combo))
        if len(out) == 3:
            break
    # the best one-site plan is always shown, as the thing a multi-site plan is compared with
    if not any(o["_sites"] == 1 for o in out):
        one = next((x for x in plans if x[0] == 1), None)
        if one is not None:
            out = out[:2] + [build(*one)]
    single = next((o for o in out if o["totals"]["distinct_sites"] == 1), None)
    for o in out:
        if single is not None and o is not single:
            shown = {"plan_sites": o["totals"]["distinct_sites"], "planning_weeks": PLANNING_WEEKS,
                     "plan_travel_minutes": o["totals"]["travel_minutes_over_planning_weeks"],
                     "single_site_travel_minutes": single["totals"]["travel_minutes_over_planning_weeks"]}
            o["vs_direct"] = {"direct_facility_id": single["stops"][-1]["facility_id"], "direct_name": single["stops"][-1]["name"],
                              "text": f"Uses {shown['plan_sites']} sites against one site at {single['stops'][-1]['name']}; "
                                      f"travel over {shown['planning_weeks']} weeks {shown['plan_travel_minutes']} min "
                                      f"against {shown['single_site_travel_minutes']} min.",
                              "text_numbers": shown}
        elif o is single:
            o["vs_direct"] = {"direct_facility_id": o["stops"][-1]["facility_id"], "direct_name": o["stops"][-1]["name"],
                              "text": "One site for every stage.", "text_numbers": {}}
        o.pop("_last"), o.pop("_sites")
    return out, []


def plan(origin, pathway, facilities, capability_p, travel_fn=None, state=None, elapsed_minutes=0, first_stop=None):
    """Best plan and up to two alternatives. See the module docstring. first_stop: facility id the caller ranks
    first (time-critical pathways only)."""
    origin = (float(origin[0]), float(origin[1]))
    travel_fn = travel_fn or default_travel_fn(state)
    result = {"pathway": pathway["id"], "service": pathway["service"], "urgency": pathway["urgency"],
              "objective": pathway["objective"], "origin": {"lat": origin[0], "lon": origin[1]},
              "elapsed_minutes": elapsed_minutes, "plans": [], "abstain": None,
              "instructions": _instructions(pathway), "assumptions": dict(ASSUMPTIONS)}
    if pathway["objective"] == "time_critical":
        plans, ctx = _emergency(origin, pathway, facilities, capability_p, travel_fn, elapsed_minutes, first_stop)
        result["first_stop"] = ctx.get("first_stop")
        if not plans:
            result["abstain"] = {"text": f"No facility within {MAX_KM:.0f} km has evidence of the definitive stage "
                                         f"({pathway['stages'][-1]['id']}). Call the emergency number."}
            return result
        result["plans"], dropped = _finish_emergency(plans, ctx, pathway, elapsed_minutes)
        result["thresholds"] = {"first_care_minutes": ctx["t1"], "first_care_basis": ctx.get("t1_basis"),
                                "definitive_minutes": ctx["t2"], "definitive_basis": ctx.get("t2_basis"),
                                "add_stop_only_if_definitive_beyond_minutes": ctx["gate"], "rule": ctx.get("gate_rule")}
        result["considered"] = {"plans": len(plans), "stop_plans_dropped_below_margin": dropped}
    else:
        result["plans"], missing = _scheduled(origin, pathway, facilities, capability_p, travel_fn)
        if not result["plans"]:
            result["abstain"] = {"text": f"No facility within {MAX_KM:.0f} km has evidence for: {', '.join(missing)}."}
    return result

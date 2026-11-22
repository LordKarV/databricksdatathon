"""Shape a planner result for the app's plan screen and slip (POST /api/plan, app/README.md).

    options = to_options(result)

One option per plan, describing the plan's definitive facility with the contract's keys, plus a
`route` object that carries the multi-stop plan. Keys the planner cannot fill are left out on
purpose: band, band_word, p_lo, p_hi, p_e, p_l, contributions, track_record, phone, is_real,
where_check, say_to_family come from the model and the facts tables (#11, app/facts).

Filled here
- rank, facility_id, name, town, district, state, lat, lon
- travel: the geo.travel row of the last leg into the definitive facility
- p: the planner's objective for the whole plan (see route.totals), not a facility score
- evidence: [{claim_id}] for the definitive stage (quotes are joined by the app from its facts)
- flags: plain-English warnings (location confidence, windows not met, call first to check)
- call_ahead: one question per stop, asked about its weakest capability
- call_first: true whenever any stop's probability is below CALL_FIRST_BELOW
- route: {type, stops, totals, window_checks, vs_direct}
"""
CALL_FIRST_BELOW = 0.9

CAPABILITY_QUESTION = {
    "emergency_24x7": "Is your emergency department open now, with a doctor on duty?",
    "thrombolysis": "Can you give clot-dissolving treatment for a heart attack right now?",
    "ecg": "Is an ECG available in emergency right now?",
    "pci_cath_lab": "Is the cath lab open now for emergency angioplasty?",
    "general_surgery_ot": "Is a surgeon and an operating theatre available now?",
    "blood_transfusion": "Do you have blood available now?",
    "ct_scan": "Is the CT scanner working now?",
    "icu": "Do you have an ICU bed free now?",
    "anti_snake_venom": "Do you have anti-snake venom in stock right now?",
    "ventilator": "Do you have a ventilator free now?",
    "iv_fluid_resuscitation": "Can a doctor start IV fluids for a burn patient now?",
    "burn_unit": "Do you admit burn patients, and is a bed free?",
    "basic_emoc": "Is the labour room open now with a doctor or nurse who can give emergency treatment?",
    "comprehensive_emoc": "Can you do an emergency caesarean now: is the theatre, anaesthetist and obstetrician available?",
    "neonatal_stabilisation": "Do you have a warmer and oxygen for a sick newborn now?",
    "sncu": "Does your special newborn care unit have a bed free now?",
    "nicu": "Does your NICU have a bed and a ventilator free now?",
    "nephrology": "On which days does the kidney specialist see patients?",
    "vascular_access_surgery": "Do you create AV fistulas for dialysis here?",
    "haemodialysis_unit": "Do you have a dialysis slot for a new patient, and on which days?",
}


def _question(stop):
    cap = stop["weakest_capability"]
    q = CAPABILITY_QUESTION.get(cap, f"Can you confirm you offer this now: {str(cap).replace('_', ' ')}?")
    return {"question": q, "facility_id": stop["facility_id"],
            "asked_because": f"weakest evidence at {stop['name']}: {str(cap).replace('_', ' ')} "
                             f"(probability {stop['weakest_capability_p']:.2f})"}


def to_options(result):
    options = []
    for rank, p in enumerate(result["plans"], start=1):
        d = p["stops"][-1]
        totals = p["totals"]
        flags = []
        for s in p["stops"]:
            flags += [f"{s['name']}: {f}" for f in s["flags"]]
        flags += [f"{c['check']} within {c['limit_minutes']} min is not met (arrival at {c['eta_minutes']} min)."
                  for c in p["window_checks"] if not c["met"]]
        flags += [f"{c['check']} within {c['limit_minutes']} min is met at the estimate but not at the high end of the range."
                  for c in p["window_checks"] if c["met"] and not c["met_at_high_estimate"]]
        options.append({
            "rank": rank, "facility_id": d["facility_id"], "name": d["name"], "town": d["town"],
            "district": d["district"], "state": d["state"], "lat": d["lat"], "lon": d["lon"],
            "travel": d["leg"],
            "p": totals.get("p_objective", totals.get("p_all_stages")),
            "evidence": [{"claim_id": i} for i in d["evidence_ids"]],
            "flags": flags,
            "call_ahead": [_question(s) for s in p["stops"]],
            "call_first": any(s["p"] < CALL_FIRST_BELOW or s.get("call_first") for s in p["stops"]),
            "route": {"type": p["type"], "stops": p["stops"], "totals": totals,
                      "window_checks": p["window_checks"], "vs_direct": p["vs_direct"]},
        })
    return options

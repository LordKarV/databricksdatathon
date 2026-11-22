"""Implied capabilities and list evidence, as a wrapper around any capability_p.

    cap_p = with_implications(base_capability_p, blood=blood_facts)
    p, evidence_ids = cap_p(facility_id, capability)
    cap_p.explain(facility_id, capability)   -> None, or how the probability was reached

Why: the planner scores each capability from the record's text alone. A dialysis unit that never
writes "nephrology" was dropped from the dialysis pathway, and the gold DEV check (EVAL_GOLD_DEV.md)
found 13 of 15 skipped confirmed facilities were lost this way.

Implications
  A capability takes max(own p, STRENGTH x p of a source capability) when the source is strongly
  evidenced (p >= STRONG). The rules are in IMPLIES, each with its reason. An implied probability
  never carries evidence ids: no quote is attached to something the record does not say. explain()
  returns {"basis": "implied", "implied_by", "text", ...} so the card can show it as a named, weaker
  contribution.

Blood from the list
  When blood facts are supplied, blood_transfusion ignores the record text:
    the facility is matched to a listed blood centre           -> P_LIST_MATCH
    a listed centre lies within SHORT_TRANSFER_KM              -> P_LIST_NEAR ("within a short transfer")
    neither                                                    -> P_LIST_NONE
  Blood facts: {"matched": {facility_id: {"name", "type"}}, "nearest": callable(facility_id) -> (km, name) or None}.
  Without blood facts the base capability_p is used unchanged for blood, and implications still apply.

Constants
  P_LIST_MATCH is the strict precision of the matcher's hand check (16 of 20 correct,
  external/eraktkosh_blood_centres/README.md). STRONG, the strengths, P_LIST_NEAR, P_LIST_NONE and
  SHORT_TRANSFER_KM are assumptions, echoed by describe().

Standard library only.
"""
STRONG = 0.75
SHORT_TRANSFER_KM = 5.0
P_LIST_MATCH = 0.80
P_LIST_NEAR = 0.50
P_LIST_NONE = 0.02

# implied capability -> [(source capability, strength, reason)]
IMPLIES = {
    "nephrology": [("haemodialysis_unit", 0.8, "a running haemodialysis unit needs a nephrologist or trained physician to prescribe sessions")],
    "laboratory": [("haemodialysis_unit", 0.8, "dialysis needs kidney function, electrolyte and viral marker tests before and after sessions"),
                   ("comprehensive_emoc", 0.7, "a unit doing caesareans needs blood grouping and basic tests"),
                   ("icu", 0.7, "an intensive care unit needs laboratory support")],
    "general_surgery_ot": [("comprehensive_emoc", 0.8, "a caesarean service has an operating theatre and anaesthesia"),
                           ("trauma_centre", 0.8, "a trauma centre has operating theatres")],
    "basic_emoc": [("comprehensive_emoc", 0.9, "comprehensive emergency obstetric care includes the basic functions")],
    "blood_transfusion": [("comprehensive_emoc", 0.6, "a First Referral Unit must have blood on site or a blood storage unit; "
                                                      "it may be within a short transfer, so the implication is weaker")],
    "neonatal_stabilisation": [("sncu", 0.9, "a special newborn care unit can stabilise a sick newborn"),
                               ("nicu", 0.9, "a NICU can stabilise a sick newborn")],
    "sncu": [("nicu", 0.8, "a NICU provides the care of a special newborn care unit and more")],
    "burns_dressing": [("burn_unit", 0.9, "a burn unit does burn dressings")],
    "iv_fluid_resuscitation": [("burn_unit", 0.9, "a burn unit gives IV fluid resuscitation"),
                               ("icu", 0.8, "an intensive care unit gives IV fluids"),
                               ("emergency_24x7", 0.7, "a round-the-clock emergency department can start IV fluids")],
    "emergency_24x7": [("trauma_centre", 0.9, "a trauma centre runs a round-the-clock emergency department")],
    "ecg": [("pci_cath_lab", 0.9, "a cath lab cannot work without ECG"), ("icu", 0.7, "an intensive care unit has ECG monitoring")],
}


def describe(blood):
    return {"strong_source_at_least": STRONG, "rules": sum(len(v) for v in IMPLIES.values()),
            "blood_from_list": blood is not None, "p_list_match": P_LIST_MATCH, "p_list_near": P_LIST_NEAR,
            "p_list_none": P_LIST_NONE, "short_transfer_km": SHORT_TRANSFER_KM,
            "note": "p_list_match is the matcher's hand-checked precision (16 of 20); the other constants are assumptions"}


def with_implications(base, blood=None, rules=None):
    """Wrap base(facility_id, capability) -> (p, evidence_ids). See the module docstring."""
    rules = IMPLIES if rules is None else rules

    def own(fid, cap):
        if cap == "blood_transfusion" and blood is not None:
            m = blood["matched"].get(fid)
            if m:
                return P_LIST_MATCH, [], {"basis": "list", "list": "e-RaktKosh blood centres", "p": P_LIST_MATCH,
                                          "text": f"listed blood centre: {m.get('name')} ({m.get('type')})"}
            near = blood["nearest"](fid) if blood.get("nearest") else None
            if near and near[0] <= SHORT_TRANSFER_KM:
                return P_LIST_NEAR, [], {"basis": "list_nearby", "list": "e-RaktKosh blood centres", "p": P_LIST_NEAR,
                                         "km": round(near[0], 1),
                                         "text": f"a listed blood centre is {near[0]:.1f} km away: {near[1]}"}
            return P_LIST_NONE, [], {"basis": "list_none", "list": "e-RaktKosh blood centres", "p": P_LIST_NONE,
                                     "text": f"no listed blood centre within {SHORT_TRANSFER_KM:.0f} km"}
        p, ids = base(fid, cap)
        return p, ids, None

    def resolve(fid, cap):
        p, ids, note = own(fid, cap)
        best = None
        for src, strength, reason in rules.get(cap, []):
            sp, _, _ = own(fid, src)          # one level only: an implied capability does not imply further
            if sp >= STRONG and strength * sp > p and (best is None or strength * sp > best[0]):
                best = (strength * sp, src, strength, sp, reason)
        if best is None:
            return p, ids, note
        ip, src, strength, sp, reason = best
        return ip, [], {"basis": "implied", "implied_by": src, "p": round(ip, 4), "source_p": round(sp, 4),
                        "strength": strength, "own_p": round(p, 4), "reason": reason,
                        "text": f"implied by a strongly evidenced {src.replace('_', ' ')}"}

    def capability_p(fid, cap):
        p, ids, _ = resolve(fid, cap)
        return p, list(ids)

    def explain(fid, cap):
        return resolve(fid, cap)[2]

    capability_p.explain = explain
    capability_p.describe = lambda: describe(blood)
    return capability_p

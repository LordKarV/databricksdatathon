"""Multi-stop itinerary for /api/plan (issue #47): the planner's route, joined with the app's facts.

The planner (planner/, owned by tm-Art4v) decides where to go and in what order for services with a care pathway.
This module only reshapes its output for the page and adds what the app already knows about each stop: phone,
place and the verbatim sentences behind each evidence id. It never changes an order, a time or a probability.
`itinerary()` returns None when the planner is not available (not shipped, not built, or no pathway for the
service), so the single-destination options keep working on their own. The swap point for the model stays
`capability_p` inside planner.service (#11); nothing here reads a probability of its own.
"""
from __future__ import annotations

import json
import re
import sys
from functools import cache
from pathlib import Path
from typing import Any

from facts.engine import STRINGS, Engine

ROOT = Path(__file__).resolve().parents[1]
MAX_QUOTES = 2
CAPABILITIES_PATH = ROOT / "kb" / "pathways" / "capabilities.json"  # shipped with the app (tools/deploy/deploy.sh)
# Route guard (#140 WS2 2c, rule 1): a route whose definitive stop is this much past a Likely card 1 is dropped.
GUARD_MIN = 15

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

# ---------- route guard (#140 WS2 2c, rule 2): a stop's quote must name what the stop is for ----------
# Word stems per kb/pathways capability tag. A stop's quote is shown only when it matches one of its stage's tags
# (or a tag that implies one, planner.implied.IMPLIES: a haemodialysis line is evidence for nephrology). The kb's own
# evidence_words (capabilities.json) are added as whole phrases; they are too narrow alone ("24x7 emergency" misses
# "24/7 emergency care"), so the stems below are the main list. Stems match at a word start; a stem ending in \b
# must be the whole word ("ortho" would otherwise take "orthodontics").
CAPABILITY_STEMS = {
    "emergency_24x7": r"emergenc|casualty|24\s*[x/×]\s*7|round[\s-]the[\s-]clock",
    "ecg": r"ecg|ekg|electrocardio|12[\s-]lead|cardiac\s+monitor",
    "thrombolysis": r"thromboly|fibrinoly|streptokinase|tenecteplase|reteplase|alteplase|stemi|heart\s+attack"
                    r"|myocardial\s+infarct",
    "pci_cath_lab": r"cath(?:eteri[sz]ation)?\s*lab|angioplast|ptca\b|pci\b|stent|interventional\s+cardio|angiogra",
    "general_surgery_ot": r"surg|ot\b|operat(?:ion|ing)\s+theat|theat(?:re|er)|anaesth|anesth|laparotom",
    "blood_transfusion": r"blood\s*(?:bank|transfus|storage|cent|component)|transfus|component\s+separation"
                         r"|\w*apheres|platelet",  # leukapheresis, plateletpheresis
    "ct_scan": r"ct\b|ncct\b|mdct\b|computed\s+tomograph|tomograph",
    "icu": r"(?:icu|micu|sicu|ccu|iccu|hdu)\b|intensive\s+care|(?:neuro\s*-?\s*)?critical\s+care|high\s+dependency",
    "trauma_centre": r"trauma|polytrauma|accident",
    "neurosurgery": r"neuro\s*-?\s*(?:surg|trauma|endoscop)|craniotom|head\s+injur|(?:vp\s+)?shunt|aneurysm",
    "orthopaedics": r"orthop|ortho\b|fractur|bone\s+and\s+joint|joint\s+replacement",
    "anti_snake_venom": r"snake|venom|asv\b|anti-?venom",
    "ventilator": r"ventilat|intubat",
    "iv_fluid_resuscitation": r"iv\b|intraven|fluid|in-?patient|indoor|admission",
    "burns_dressing": r"burn|dressing",
    "burn_unit": r"burn",
    "plastic_surgery": r"plastic|reconstruct|skin\s*graft",
    "nephrology": r"nephro|kidney|renal",
    "laboratory": r"laborator|labs?\b|patholog|biochem|creatinin|hbsag|viral\s+marker",
    "vascular_access_surgery": r"fistula|vascular|permcath|dialysis\s+catheter",
    "haemodialysis_unit": r"dialys|pmndp\b|ro\s+plant|renal\s+replacement|crrt\b",
    "basic_emoc": r"obstet|matern|deliver|labou?r\b|gyn|pregnan",
    "comprehensive_emoc": r"caesar|cesar|c[\s-]*section|lscs\b|cemonc\b|fru\b|first\s+referral",
    "neonatal_stabilisation": r"new[\s-]?born|neonat|nbsu\b|radiant\s+warmer|phototherap",
    "sncu": r"sncu\b|special\s+new[\s-]?born|sick\s+new[\s-]?born|level\s*(?:ii|2)\s+neonat",
    "nicu": r"nicu\b|neonatal\s+(?:intensive|icu|critical|ventilat)|neonatolog|level\s*(?:iii|3)\s+neonat",
}


def _phrase(word: str) -> str:
    """A kb evidence_words phrase as a whole-phrase pattern; spaces and hyphens match each other."""
    return r"(?<!\w)" + r"[\s-]+".join(re.escape(w) for w in re.split(r"[\s-]+", word.strip())) + r"(?!\w)"


@cache
def capability_patterns() -> dict[str, re.Pattern[str]]:
    """{capability tag: case-insensitive pattern}: CAPABILITY_STEMS plus the kb's evidence_words when shipped."""
    shipped = CAPABILITIES_PATH.is_file()
    kb = json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))["capabilities"] if shipped else []
    words = {c["id"]: c.get("evidence_words") or [] for c in kb}
    out = {}
    for cap in CAPABILITY_STEMS.keys() | words.keys():
        parts = [rf"\b(?:{CAPABILITY_STEMS[cap]})"] if cap in CAPABILITY_STEMS else []
        out[cap] = re.compile("|".join(parts + [_phrase(w) for w in words.get(cap, [])]) or r"(?!)", re.IGNORECASE)
    return out


@cache
def stage_pattern(caps: tuple[str, ...]) -> re.Pattern[str]:
    """One pattern for a stage: any of its tags, or a tag that implies one of them (planner.implied.IMPLIES)."""
    from planner.implied import IMPLIES  # the planner is on sys.path once _planner() has run
    pats = capability_patterns()
    tags = dict.fromkeys([*caps, *(src for c in caps for src, *_ in IMPLIES.get(c, []))])
    return re.compile("|".join(f"(?:{pats[t].pattern})" for t in tags if t in pats) or r"(?!)", re.IGNORECASE)


_TOKEN = re.compile(r"[a-z0-9]+")
_JOINERS = {"and", "of", "the"}


def _norm(tok: str) -> str:
    return "centre" if tok == "center" else tok


def without_name(quote: str, name: str) -> str:
    """The quote with the facility's own name taken out: a run of two or more of the name's words (joined by "and",
    "of", "the" or punctuation) is blanked, so "Vardaan Hospital and Maternity Centre" never reads as maternity
    evidence. A single name word stays ("Maternity ward" at a maternity home is still evidence)."""
    own = {_norm(t) for t in _TOKEN.findall((name or "").lower())} - _JOINERS
    low = quote.lower()
    toks = [(m.start(), m.end(), _norm(m.group())) for m in _TOKEN.finditer(low)]
    out, run = low, []
    for k, t in enumerate([*toks, (len(low), len(low), "")]):
        if k < len(toks) and (t[2] in own or (run and t[2] in _JOINERS)):
            run.append(t)
            continue
        while run and run[-1][2] in _JOINERS:
            run.pop()
        if sum(x[2] in own for x in run) >= 2:
            out = out[:run[0][0]] + " " * (run[-1][1] - run[0][0]) + out[run[-1][1]:]
        run = []
    return out


def stage_caps(pathway: dict, stage_id: str | None) -> tuple[str, ...]:
    """Every capability tag a pathway stage can rest on: requires_all and each requires_any group."""
    st = next((x for x in pathway.get("stages", []) if x["id"] == stage_id), None)
    return tuple(dict.fromkeys([*st["requires_all"], *(c for g in st["requires_any"] for c in g)])) if st else ()


def _planner():
    """planner.service, or None when the planner is not shipped with this app."""
    if str(ROOT) not in sys.path:
        sys.path.append(str(ROOT))  # planner/ and geo/ live at the repo root
    try:
        from planner import service
    except ImportError:
        return None
    return service


def _own(eng: Engine, ids: list[str], words: re.Pattern[str] | None = None, name: str = "") -> list[str]:
    """Own offer sentences only, as on the option cards; with words, only those that name the stage (rule 2)."""
    out = []
    for cid in ids:
        c = eng.claims.get(cid)
        if c and not c[2] and c[3] != "other_facility" and (words is None or words.search(without_name(c[1], name))):
            out.append(cid)
    return out


def _quotes(eng: Engine, ids: list[str]) -> list[dict]:
    return [{"claim_id": cid, "quote": eng.claims[cid][1]} for cid in ids[:MAX_QUOTES]]


def stop_evidence(eng: Engine, s: dict, service: str, caps: tuple[str, ...]) -> tuple[list[str], str | None]:
    """(claim ids, note) for one route stop (#140 WS2 2c, rules 2 and 3). The planner's lines count only when they
    name the stop's stage; otherwise the engine's own quotes for this facility and the asked service stand in; with
    neither, a note says to ask on the phone."""
    ids = _own(eng, s["evidence_ids"], stage_pattern(caps) if caps else None, s.get("name") or "")
    if not ids:
        i = eng.fid.get(s["facility_id"])
        pr = eng.index.get(service, {}).get(i) if i is not None else None
        ids = _own(eng, eng._evidence(pr)) if pr else []
    if ids:
        return ids, None
    return [], STRINGS["stop_no_line"]["en"].format(need=capability_words(s["weakest_capability"]))


def place(*parts: object) -> str:
    """Town and district for a stop; skips NaN, None and blanks from the planner export (#78)."""
    words = [x.strip() for x in parts if isinstance(x, str) and x.strip()]
    return ", ".join(dict.fromkeys(x.title() if x.isupper() else x for x in words))


def _stop(eng: Engine, s: dict, question: str | None, service: str, caps: tuple[str, ...]) -> dict:
    i = eng.fid.get(s["facility_id"])
    fb = s.get("fallback_if_turned_away")
    ids, note = stop_evidence(eng, s, service, caps)
    return {
        "facility_id": s["facility_id"], "name": s["name"],
        "place": place(s.get("town"), s.get("district")),
        "purpose": s["purpose"], "purpose_word": PURPOSE.get(s["purpose"], s["purpose"]),
        "eta_low": s["eta_low"], "eta_high": s["eta_high"], "dwell_minutes": s["dwell_minutes"],
        "p": s["p"], "weakest_capability": capability_words(s["weakest_capability"]),
        "weakest_capability_p": s["weakest_capability_p"], "question": question,
        "evidence": _quotes(eng, ids), "n_evidence": len(ids), "note": note,
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
    return {"text": v["text"], "what_would_change": v.get("what_would_change"), "direct_minutes": v["direct_minutes"],
            "direct_p_objective": v["direct_p_objective"], "plan_p_objective": v["plan_p_objective"],
            "direct_p_first_care": v["direct_p_first_care"], "plan_p_first_care": v["plan_p_first_care"]}


def _plan(eng: Engine, rank: int, o: dict, service: str, pathway: dict) -> dict:
    r = o["route"]
    qs = {q["facility_id"]: q["question"] for q in o["call_ahead"]}
    t = r["totals"]
    return {
        "rank": rank, "type": r["type"], "type_word": TYPE.get(r["type"], r["type"]),
        "stops": [_stop(eng, s, qs.get(s["facility_id"]), service, stage_caps(pathway, s.get("stage")))
                  for s in r["stops"]],
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


def lead_lines(route: dict, options: list[dict], first_stop: dict | None, note: str | None,
               window_min: int | None = None) -> dict[str, str]:
    """{facility_id: line} for an emergency whose route starts elsewhere than option 1 (#121): the route's first stop
    leads the cards with the stop_1_note reason in the positive, and the former option 1 says what it lacks. When the
    route goes straight to definitive care inside the window and the former option 1 can give first care, that one
    is framed as the nearer first-care place, never as the best option (lead on #126, item 4)."""
    s, d, y = route["stops"][0], route["stops"][-1], options[0]
    fs = first_stop if first_stop and first_stop["facility_id"] == y["facility_id"] else {}
    need = (fs.get("missing_first_care") if fs.get("in_data") and not fs.get("first_care") else
            fs.get("missing_definitive") if s is d else None)
    if s is d and fs.get("in_data") and fs.get("first_care") and window_min and d["eta_high"] <= window_min \
            and y["travel"]["minutes"] < s["eta_low"]:  # "Nearer" only when it is
        has = f"; it has evidence of {_has(need)}, which {y['name']} does not show" if need else ""
        lacks = f"; our data shows no evidence of {_lacks(need)} here" if need else ""
        return {s["facility_id"]: f"Go here directly: definitive care within the {window_min}-minute window{has}.",
                y["facility_id"]: f"Nearer: can give first care in about {y['travel']['minutes']} min if the patient "
                                  f"needs it sooner{lacks}."}
    if not need:
        return {s["facility_id"]: f"First: {note[0].lower()}{note[1:]}" if note else "First: the suggested route starts here."}
    # "Nearest" only when it is nearer than every option and the low end of the stop's own estimate
    nearest = y["travel"]["minutes"] <= min(o["travel"]["minutes"] for o in options) and y["travel"]["minutes"] < s["eta_low"]
    return {s["facility_id"]: f"First: it has evidence of {_has(need)}, which {y['name']} does not show.",
            y["facility_id"]: ("Nearest, but our" if nearest else "Our")
            + f" data shows no evidence of {_lacks(need)} here."}


def covers_every_stage(first_option: dict | None, first_stop: dict | None) -> bool:
    """True when the planner found option 1 able to give first care and definitive care itself (planner.core
    first_stop: in_data, first_care, nothing in missing_definitive)."""
    fs = first_stop or {}
    return bool(first_option and fs.get("facility_id") == first_option["facility_id"] and fs.get("in_data")
                and fs.get("first_care") and not fs.get("missing_definitive"))


def past_card_1(route: dict, first_option: dict) -> bool:
    """The route's definitive stop is more than GUARD_MIN past card 1's high travel estimate."""
    d = [s for s in route["stops"] if s["purpose"] == "definitive"]
    return bool(d) and d[-1]["eta_low"] > first_option["travel"]["high"] + GUARD_MIN


def guard(options: list[dict], first_option: dict | None, first_stop: dict | None) -> tuple[list[dict], str | None]:
    """(planner options kept, itinerary_note) (#140 WS2 2c, rule 1). When card 1 is Likely and has evidence for every
    stage itself, a route whose definitive stop is far past it is dropped: going straight to card 1 is the answer. A
    Likely card 1 that lacks a definitive capability (blood, CT or an ICU for trauma) keeps the route (lead, D1: the
    Gaya hero stabilises at card 1, then goes on)."""
    if not (first_option and first_option.get("band") == "likely" and covers_every_stage(first_option, first_stop)):
        return options, None
    kept = [o for o in options if not past_card_1(o["route"], first_option)]
    # The note says "go straight to card 1": only when a route went and no route left leads anywhere else.
    goes = len(kept) < len(options) and (not kept or only_at(kept[0]["route"], first_option["facility_id"]))
    return kept, dropped_note(first_option) if goes else None


def only_at(route: dict, facility_id: str) -> bool:
    return {s["facility_id"] for s in route["stops"]} == {facility_id}


def dropped_note(first_option: dict) -> str:
    return STRINGS["route_dropped"]["en"].format(name=first_option["name"])


def guard_led(plan: dict) -> dict:
    """Rule 1 again after lead_with_route: when card 1 is now route 1's only place (a direct route to it, so it has
    evidence for every stage) and Likely, the other routes whose definitive stop is far past it are dropped."""
    it, opts = plan.get("itinerary"), plan.get("options")
    if not it or not it["plans"] or not opts or opts[0].get("band") != "likely" \
            or not only_at(it["plans"][0], opts[0]["facility_id"]):
        return plan
    kept = [it["plans"][0], *(r for r in it["plans"][1:] if not past_card_1(r, opts[0]))]
    if len(kept) == len(it["plans"]):
        return plan
    return {**plan, "itinerary": {**it, "plans": [{**r, "rank": k + 1} for k, r in enumerate(kept)],
                                  "itinerary_note": dropped_note(opts[0])}}


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
    options, dropped = guard(out["options"], first_option, out.get("first_stop"))
    note = stop_1_note(options[0]["route"], first_option, out.get("first_stop")) if options else None
    if options and first_option is None:  # no option card at all: stop 1 is not among the options (rule 4)
        note = STRINGS["stop_1_unlisted"]["en"].format(name=options[0]["route"]["stops"][0]["name"])
    return {
        "pathway": out["pathway"], "pathway_name": pw["name"].split(":")[0], "urgency": out.get("urgency"),
        "abstain": (out.get("abstain") or {}).get("text"),
        "plans": [_plan(eng, k + 1, o, service, pw) for k, o in enumerate(options)],
        "itinerary_note": dropped,
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
        plan = guard_led(lead_with_route(plan, eng))
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
    window = (plan.get("time_window") or {}).get("window_min")
    lead = lead_lines(route, plan["options"], first_stop, it["stop_1_note"], window)
    fresh = eng.plan(plan["query"]["service"], loc["lat"], loc["lon"], loc["accuracy_m"], loc["source"], lead=lead)
    head, minutes = fresh["options"][0], fresh["options"][0]["travel"]["minutes"]
    if head["facility_id"] == route["stops"][0]["facility_id"] and (
            minutes <= plan["time_window"]["window_min"] or minutes <= plan["options"][0]["travel"]["minutes"]):
        return {**plan, **fresh, "itinerary": {**it, "stop_1_note": None}}
    # Card 1 stays first. The note stays whenever stop 1 is not on the list at all (#140 WS2 2c, rule 4).
    listed = route["stops"][0]["facility_id"] in {o["facility_id"] for o in plan["options"]}
    return {**plan, "itinerary": {**it, "stop_1_note": None if listed else it["stop_1_note"],
                                  "fallback": fallback(route, plan)}}

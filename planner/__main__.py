"""Print a plan for a coordinate.

    .venv/bin/python -m planner --pathway major_trauma --lat 26.45 --lon 85.95 --state Bihar
    .venv/bin/python -m planner --pathway dialysis_start --lat 26.6 --lon 85.48 --json
    .venv/bin/python -m planner --list

Probabilities come from the derived/v1 stub in planner/data_v1.py (not the fitted model). Travel
times are geo.travel estimates with no network calls; add --osrm to route the legs of the printed
plans on the OSRM demo server (a handful of requests).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.core import plan  # noqa: E402


def load_pathways():
    doc = json.loads((ROOT / "kb" / "pathways" / "care_pathways.json").read_text())
    return {p["id"]: p for p in doc["pathways"]}


def text(result):
    out = [f"Pathway: {result['pathway']} ({result['urgency']}). Probabilities: derived/v1 stub, not the fitted model."]
    if result["abstain"]:
        return "\n".join(out + [result["abstain"]["text"]])
    th = result.get("thresholds")
    if th:
        if th["first_care_minutes"] is not None:
            out.append(f"First care within {th['first_care_minutes']} min [{th['first_care_basis']}].")
        if th["definitive_minutes"] is not None:
            out.append(f"Definitive care within {th['definitive_minutes']} min [{th['definitive_basis']}].")
        if th["add_stop_only_if_definitive_beyond_minutes"] is not None:
            out.append(f"A stop is considered only if the definitive facility is beyond "
                       f"{th['add_stop_only_if_definitive_beyond_minutes']} min [rule {th['rule']}].")
    for i, p in enumerate(result["plans"]):
        t = p["totals"]
        out.append("")
        if "p_objective" in t:
            out.append(f"{'BEST' if i == 0 else 'ALTERNATIVE ' + str(i)}: {p['type']}, {t['minutes_to_definitive']} min "
                       f"({t['low']} to {t['high']}) to definitive care, chance of care in time {t['p_objective']:.2f}, "
                       f"chance of first care in time {t['p_first_care']:.2f}, "
                       f"chance treated at all {t['p_treated']:.2f}")
        else:
            out.append(f"{'BEST' if i == 0 else 'ALTERNATIVE ' + str(i)}: {p['type']}, {t['distinct_sites']} site(s), "
                       f"{t['travel_minutes_over_planning_weeks']} min of travel over {t['planning_weeks']} weeks, "
                       f"chance every stage is available {t['p_all_stages']:.2f}")
        for s in p["stops"]:
            dwell = f", stay {s['dwell_minutes']} min" if s["dwell_minutes"] else ""
            rep = f", {s['per_week']} times a week" if s.get("per_week") else ""
            out.append(f"  {s['purpose']:10s} {s['name']} ({s['town']}, {s['state']}): arrive {s['eta_minutes']} min "
                       f"({s['eta_low']} to {s['eta_high']}), {s['leg']['km']} km by {s['leg']['method']}{dwell}{rep}; "
                       f"P {s['p']:.2f}, weakest: {s['weakest_capability']} {s['weakest_capability_p']:.2f}; "
                       f"evidence {', '.join(s['evidence_ids'][:3]) or 'none'}")
            for fl in s["flags"]:
                out.append(f"             note: {fl}")
            fb = s.get("fallback_if_turned_away")
            if fb:
                out.append(f"             if turned away: {fb['name']} at {fb['eta_minutes']} min, P {fb['p']:.2f}")
        for c in p["window_checks"]:
            out.append(f"  check: {c['check']} within {c['limit_minutes']} min: {'met' if c['met'] else 'NOT met'} "
                       f"at {c['eta_minutes']} min{'' if c['met_at_high_estimate'] == c['met'] else ' (not met at the high estimate)'}")
        if p["vs_direct"]:
            out.append(f"  against direct: {p['vs_direct']['text']}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m planner", description="Multi-stop referral plan for a coordinate.")
    ap.add_argument("--pathway")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--state", help="origin state, for hill-road travel constants")
    ap.add_argument("--elapsed", type=float, default=0, help="minutes already passed since the pathway clock started")
    ap.add_argument("--osrm", action="store_true", help="use live OSRM routes instead of estimates")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="list pathway ids")
    a = ap.parse_args(argv)
    pathways = load_pathways()
    if a.list:
        print("\n".join(f"{k}: {v['name']}" for k, v in pathways.items()))
        return 0
    if a.pathway not in pathways or a.lat is None or a.lon is None:
        ap.error("need --pathway (see --list), --lat and --lon")
    from geo import travel
    from planner.data_v1 import V1Store
    store = V1Store()

    def travel_fn(origin, destinations):
        return travel.travel_minutes(origin, destinations, use_osrm=a.osrm, state=a.state)
    result = plan((a.lat, a.lon), pathways[a.pathway], store.facilities(), store.capability_p, travel_fn=travel_fn,
                  elapsed_minutes=a.elapsed)
    result["meta"] = {"stub": True, "probabilities": store.describe(),
                      "travel": "live OSRM" if a.osrm else "geo.travel estimate, no network"}
    print(json.dumps(result, indent=1) if a.json else text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

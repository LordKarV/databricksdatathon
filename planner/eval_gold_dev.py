"""Planner against the gold DEV labels: is the definitive facility it picks one the labels confirm?

For every gold DEV pair (facility, service) whose service has a care pathway, the query is placed at
the gold facility's own location and the planner is run with its stub probabilities and estimated
travel times (no network). Recorded per query:
  - the definitive facility of the best plan (or abstain)
  - whether that is the gold facility itself
  - the gold verdict of the picked facility for that service: confirmed, contradicted, no_info, or
    unknown when the picked facility has no DEV label for the service
The planner is run twice: without and with implied capabilities (planner/implied.py), so the
effect of that layer is visible. Baseline "nearest mention": the nearest facility (the gold facility included, at distance 0) that
has a graded mention of the service in derived/v1/grades.parquet.

TEST pairs are never read: gold_pairs.parquet is filtered to split == "dev" on load, and a picked
facility that only has a TEST label counts as unknown.

Reading the result: the query sits on the gold facility, so "picks the gold facility" measures
whether the planner trusts that facility's own claim. A planner that separates good claims from bad
picks the gold facility more often when the label says confirmed than when it says contradicted.

Writes planner/out_eval/gold_dev.json and prints a summary. Needs pandas (for the two parquet reads).
Run: .venv/bin/python planner/eval_gold_dev.py      (after planner/export_v1.py)
"""
import json
import math
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.core import MIN_P, SCHEDULED_MIN_P, hav_km, stage_p  # noqa: E402
from planner.implied import with_implications  # noqa: E402
from planner.service import pathways, plan_for_service, store  # noqa: E402

DATA_ROOT = Path(os.environ.get("DATATHON_ROOT") or ROOT)       # where derived/v1 lives
OUT = Path(os.environ.get("PLANNER_EVAL_OUT") or Path(__file__).resolve().parent / "out_eval")
# service names in gold_pairs.parquet -> app service ids with a pathway
GOLD_TO_APP = {"dialysis": "dialysis", "csection": "emergency_csection", "nicu": "nicu", "trauma": "trauma_emergency",
               "burns": "burn_care"}
VERDICTS = ("confirmed", "contradicted", "no_info", "unknown")


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 3), round(c + h, 3)]


def rate(k, n):
    return {"k": int(k), "n": int(n), "share": None if n == 0 else round(k / n, 3), "ci95": wilson(k, n)}


def missed_summary(rows):
    """Gold-confirmed facilities the planner did not pick, by the capability that kept them out."""
    missed = [r for r in rows if r["gold_verdict"] == "confirmed" and not r["planner_is_gold"]]
    not_cand = [r for r in missed if not r["why_not_gold"]["was_candidate"]]
    by_cap = {}
    for r in not_cand:
        k = f"{r['pathway']}: {r['why_not_gold']['weakest_capability']}"
        by_cap[k] = by_cap.get(k, 0) + 1
    return {"n": len(missed), "not_a_candidate": len(not_cand), "candidate_but_outranked": len(missed) - len(not_cand),
            "not_a_candidate_by_missing_capability": dict(sorted(by_cap.items(), key=lambda x: -x[1]))}


def summarise(rows, who):
    picked = [r for r in rows if r[f"{who}_pick"] is not None]
    out = {"queries": len(rows), "abstained": len(rows) - len(picked),
           "picked_verdict": {v: rate(sum(r[f"{who}_verdict"] == v for r in picked), len(picked)) for v in VERDICTS},
           "picks_gold_facility": rate(sum(r[f"{who}_is_gold"] for r in rows), len(rows)),
           "picks_gold_facility_by_gold_verdict": {}}
    for v in ("confirmed", "contradicted", "no_info"):
        g = [r for r in rows if r["gold_verdict"] == v]
        out["picks_gold_facility_by_gold_verdict"][v] = rate(sum(r[f"{who}_is_gold"] for r in g), len(g))
    known = [r for r in picked if r[f"{who}_verdict"] in ("confirmed", "contradicted")]
    out["confirmed_among_picks_with_a_clear_label"] = rate(sum(r[f"{who}_verdict"] == "confirmed" for r in known), len(known))
    return out


def why_not_gold(uid, pathway, capability_p):
    """Why the planner did not send the patient to this facility for the definitive (or recurring)
    stage: that stage's probability and its weakest capability."""
    stages = [pathway["stages"][-1]]
    worst = min((stage_p(uid, stg, capability_p) + (stg["id"],) for stg in stages), key=lambda x: x[0])
    cut = MIN_P if pathway["objective"] == "time_critical" else SCHEDULED_MIN_P
    return {"stage": worst[4], "stage_p": round(worst[0], 3), "weakest_capability": worst[2],
            "weakest_capability_p": round(worst[3], 3), "was_candidate": worst[0] >= cut}


def main():
    st = store()
    if st is None:
        sys.exit("planner data not built: run planner/export_v1.py")
    gold = pd.read_parquet(DATA_ROOT / "derived/v1/gold_pairs.parquet",
                           columns=["pair_id", "unique_id", "service", "stratum", "split", "service_verdict"])
    gold = gold[(gold.split == "dev") & gold.service.isin(GOLD_TO_APP)].reset_index(drop=True)   # TEST never used
    verdict = {(r.unique_id, r.service): r.service_verdict for r in gold.itertuples()}
    fac = {f["id"]: f for f in st.facilities()}
    grades = pd.read_parquet(DATA_ROOT / "derived/v1/grades.parquet", columns=["unique_id", "service"])
    mention = {s: [fac[u] for u in g.unique_id.unique() if u in fac] for s, g in grades.groupby("service")}

    def run(implications):
        cap_p = with_implications(st.capability_p, blood=st.blood_facts()) if implications else st.capability_p
        rows, skipped = [], 0
        for r in gold.itertuples():
            f = fac.get(r.unique_id)
            if f is None:
                skipped += 1
                continue
            origin = (f["lat"], f["lon"])
            res = plan_for_service(GOLD_TO_APP[r.service], *origin, implications=implications)
            pick = res["options"][0] if res["options"] else None
            pid = pick["facility_id"] if pick else None
            near = min(mention.get(r.service, []), key=lambda x: hav_km(origin, (x["lat"], x["lon"])), default=None)
            nid = near["id"] if near else None
            implied = [n["capability"] for s_ in (pick["route"]["stops"] if pick else []) for n in s_.get("capability_notes", [])
                       if n["basis"] == "implied"]
            rows.append({"pair_id": r.pair_id, "service": r.service, "pathway": res["pathway"], "stratum": r.stratum,
                         "gold_verdict": r.service_verdict,
                         "planner_pick": pid, "planner_is_gold": pid == r.unique_id,
                         "planner_verdict": None if pid is None else verdict.get((pid, r.service), "unknown"),
                         "planner_plan_type": pick["route"]["type"] if pick else None,
                         "planner_minutes": pick["travel"]["minutes"] if pick else None,
                         "planner_implied_capabilities": implied,
                         "why_not_gold": None if pid == r.unique_id else why_not_gold(r.unique_id, pathways()[res["pathway"]], cap_p),
                         "baseline_pick": nid, "baseline_is_gold": nid == r.unique_id,
                         "baseline_verdict": None if nid is None else verdict.get((nid, r.service), "unknown")})
        return rows, skipped

    before, _ = run(False)
    rows, skipped = run(True)
    result = {"split": "dev", "pairs_used": len(rows), "pairs_without_location": skipped,
              "gold_verdicts": {v: int(n) for v, n in gold.service_verdict.value_counts().items()},
              "probabilities": "derived/v1 stub (planner/data_v1.py), not the fitted model",
              "travel": "geo.travel estimate, no network",
              "blood_from_list": st.blood_facts() is not None,
              "overall": {"planner": summarise(rows, "planner"), "planner_without_implications": summarise(before, "planner"),
                          "nearest_mention": summarise(rows, "baseline")},
              "picks_changed_by_implications": sum(a["planner_pick"] != b["planner_pick"] for a, b in zip(before, rows)),
              "plans_using_an_implied_capability": sum(bool(r["planner_implied_capabilities"]) for r in rows),
              "confirmed_but_not_picked_without_implications": missed_summary(before),
              "by_pathway": {p: {"planner": summarise(g, "planner"), "nearest_mention": summarise(g, "baseline")}
                             for p in sorted({r["pathway"] for r in rows})
                             for g in [[r for r in rows if r["pathway"] == p]]},
              "confirmed_but_not_picked": missed_summary(rows),
              "rows": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gold_dev.json").write_text(json.dumps(result, indent=1))

    def line(name, s):
        v = s["picked_verdict"]
        bg = s["picks_gold_facility_by_gold_verdict"]
        return (f"{name:16s} n {s['queries']:3d} abstain {s['abstained']:2d} | picked: confirmed {v['confirmed']['k']:2d} "
                f"contradicted {v['contradicted']['k']:2d} no_info {v['no_info']['k']:2d} unknown {v['unknown']['k']:2d} | "
                f"picks gold facility when confirmed {bg['confirmed']['k']}/{bg['confirmed']['n']}, contradicted "
                f"{bg['contradicted']['k']}/{bg['contradicted']['n']}, no_info {bg['no_info']['k']}/{bg['no_info']['n']}")
    print(f"gold DEV pairs with a pathway: {len(rows)} ({result['gold_verdicts']})")
    m = result["confirmed_but_not_picked"]
    print(f"confirmed but not picked: {m['n']} ({m['not_a_candidate']} not a candidate, {m['candidate_but_outranked']} outranked); "
          f"missing capability: {m['not_a_candidate_by_missing_capability']}")
    print(f"blood from list: {result['blood_from_list']}; picks changed by implications: "
          f"{result['picks_changed_by_implications']}; plans using an implied capability: {result['plans_using_an_implied_capability']}")
    for scope, block in [("ALL", result["overall"])] + list(result["by_pathway"].items()):
        print(scope)
        if "planner_without_implications" in block:
            print("  " + line("planner BEFORE", block["planner_without_implications"]))
        print("  " + line("planner", block["planner"]))
        print("  " + line("nearest mention", block["nearest_mention"]))
    return result


if __name__ == "__main__":
    main()

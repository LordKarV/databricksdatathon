"""Step loop for the simulated referral world (#92). SIMULATED, not field data. The only module that reads the truth.

    steps = {c["case_id"]: policy(c, ctx) for c in cases.to_dict("records")}   # policies never see the truth
    events = execute(cases, steps, truth, scenario="S2", policy="nearest", run_id="s2_seed1")

The health worker tries the policy's steps in order, at most MAX_STEPS:
- call_first: no signal -> an outage, then go anyway. The call costs CALL_MIN. A number that does not reach the
  facility -> "no_answer", go anyway. Answered: "yes" if the facility would treat now, else a wrong "yes" at rate
  wrong_yes; "no" -> next step without travelling.
- travel to the listed point (geo.travel estimate, hill-road constants for the origin state).
- arrive: not there (does not exist, or the true point is more than NOT_THERE_KM from the listed one), closed
  (open_now_p), does not offer, or refused (accept_p) -> turned away, TURN_AWAY_MIN lost, next step from here.
  Otherwise treated.
- gives up when the steps run out or before a step once GIVE_UP_MIN[urgency] has passed.
Every per-visit draw is a hash of (seed, case, facility, purpose), so two policies that send the same patient to the
same facility get the same answer (common random numbers).
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from geo.travel import estimate, hav_km  # noqa: E402, RUF100
from sim import world  # noqa: E402, RUF100

MAX_STEPS = 3  # app N_OPTIONS (app/facts/engine.py)
CALL_MIN = 5  # assumption
TURN_AWAY_MIN = 15  # planner/core.py: a facility that cannot deliver costs 15 minutes
NOT_THERE_KM = 2.0  # assumption: farther than this from the listed point, the patient does not find it
GIVE_UP_MIN = {"emergency": 240, "planned": 480}  # assumption
EVENT_COLS = ["run_id", "scenario", "seed", "policy", "case_id", "step", "kind", "facility_id", "t_min", "outcome"]


def draw(seed: int, case_id: str, facility_id: str, what: str) -> float:
    """A uniform in [0, 1) fixed by its key."""
    h = hashlib.blake2b(f"{seed}|{case_id}|{facility_id}|{what}".encode(), digest_size=8).digest()
    return int.from_bytes(h, "little") / 2.0**64


def index_truth(truth: pd.DataFrame) -> dict[tuple[str, str], tuple]:
    return {(r.unique_id, r.service): r for r in truth.itertuples(index=False)}


def _listed() -> dict[str, tuple[float, float]]:
    f = world.facilities().dropna(subset=["lat", "lon"])
    return dict(zip(f.unique_id, zip(f.lat, f.lon, strict=True), strict=True))


def run_case(case: dict, steps: list[dict], truth: dict, listed: dict, knobs: dict) -> list[tuple]:
    """(step, kind, facility_id, t_min, outcome) rows for one case."""
    seed, cid, svc = case["seed"], case["case_id"], case["service"]
    t, pos, ev = 0.0, (case["lat"], case["lon"]), []

    def log(k, kind, fid, outcome):
        ev.append((k, kind, fid, round(t, 1), outcome))

    if not case["has_data"]:
        log(0, "outage", None, "no_data")
    for k, s in enumerate(steps[:MAX_STEPS]):
        if t > GIVE_UP_MIN[case["urgency"]]:
            log(k, "gave_up", None, "time_limit")
            return ev
        fid = s["facility_id"]
        tr, dest = truth.get((fid, svc)), listed.get(fid)
        if tr is None or dest is None:
            raise KeyError(f"no truth or listed point for facility {fid!r}, service {svc!r}")
        is_open = draw(seed, cid, fid, "open") < tr.open_now_p
        accepts = draw(seed, cid, fid, "accept") < tr.accept_p
        would_treat = tr.exists and tr.offers and is_open and accepts
        if s["call_first"]:
            if not case["has_phone_signal"]:
                log(k, "outage", fid, "no_signal")
            else:
                t += CALL_MIN
                if not (tr.phone_ok and tr.exists):
                    log(k, "call", fid, "no_answer")
                else:
                    yes = would_treat or draw(seed, cid, fid, "wrong_yes") < knobs["wrong_yes"]
                    log(k, "call", fid, "yes" if yes else "no")
                    if not yes:
                        continue
        log(k, "travel", fid, "")
        t += estimate(pos, dest, case["state"])["minutes"]
        pos = dest
        log(k, "arrive", fid, "")
        there = tr.exists and not math.isnan(tr.true_lat) and hav_km(dest, (tr.true_lat, tr.true_lon)) <= NOT_THERE_KM
        reason = ("not_there" if not there else "closed" if not is_open else "no_service" if not tr.offers
                  else "refused" if not accepts else None)
        if reason is None:
            log(k, "treated", fid, "in_window" if t <= case["window_min"] else "late")
            return ev
        log(k, "turned_away", fid, reason)
        t += TURN_AWAY_MIN
    log(min(len(steps), MAX_STEPS), "gave_up", None, "no_options_left")
    return ev


def execute(cases: pd.DataFrame, steps: dict[str, list[dict]], truth: pd.DataFrame, *, scenario: str, policy: str,
            run_id: str, knobs: dict | None = None) -> pd.DataFrame:
    """Event log (EVENT_COLS) for every case. steps maps case_id -> the policy's list of steps."""
    k = {**world.MID, **(knobs or {})}
    tix, listed = index_truth(truth), _listed()
    rows = []
    for c in cases.to_dict("records"):
        for e in run_case(c, steps[c["case_id"]], tix, listed, k):
            rows.append((run_id, scenario, c["seed"], policy, c["case_id"], *e))
    return pd.DataFrame(rows, columns=EVENT_COLS)


def summary(events: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    """Smoke-run numbers per policy x scenario x service (the real metrics with intervals are sim/run.py's)."""
    n = cases.groupby("service").size()
    e = events.merge(cases[["case_id", "service"]], on="case_id")
    g = ["policy", "scenario", "service"]
    tr = e[e.kind == "treated"]
    first = e[e.kind == "arrive"].drop_duplicates(["policy", "scenario", "case_id"])
    first = first.merge(e[e.kind == "turned_away"], on=["policy", "scenario", "case_id", "step", "service"],
                        how="left", suffixes=("", "_ta"))
    per = pd.DataFrame({
        "treated_in_window": tr[tr.outcome == "in_window"].groupby(g).size(),
        "median_min_to_care": tr.groupby(g).t_min.median(),
        "wasted_trips": e[e.kind == "turned_away"].groupby(g).size(),
        "calls": e[e.kind == "call"].groupby(g).size(),
        "unsafe_first_stop": first[first.outcome_ta.isin(["no_service", "not_there"])].groupby(g).size(),
        "gave_up": e[e.kind == "gave_up"].groupby(g).size(),
    }).fillna(0).reset_index()
    for col in ["treated_in_window", "wasted_trips", "calls", "unsafe_first_stop", "gave_up"]:
        per[col] = per[col] / per.service.map(n)  # per case
    return per.round(3)


def main(seeds: list[int]) -> None:
    from sim import policies_baseline as pb
    ctx = pb.context()
    out = []
    for seed in seeds:
        cases = world.cases(seed)
        recs = cases.to_dict("records")
        for name, choose in pb.POLICIES.items():
            steps = {c["case_id"]: choose(c, ctx) for c in recs}
            for sc in world.SCENARIOS:
                run_id = f"{name}_{sc}_{seed}"
                ev = execute(cases, steps, world.truth_table(sc, seed), scenario=sc, policy=name, run_id=run_id)
                world.write_parquet(ev, world.OUT / "events" / f"{run_id}.parquet")
                out.append((ev, cases))
    events = pd.concat([e for e, _ in out], ignore_index=True)
    allcases = pd.concat([c for _, c in out]).drop_duplicates("case_id")
    print(world.SIMULATED)
    print(summary(events, allcases).to_string(index=False))


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]] or [1, 2])

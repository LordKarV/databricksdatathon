"""Real-data policy comparison at the demo places (#92, the cheaper companion to the simulation).

    .venv-app/bin/python validation/policy_compare.py      # from the repo root, after app/facts/build.py

For every app service at the places in validation/demo_qa.py, three ways to pick the first facility:
- app:             the app's first option (Engine.plan, model v2, as shipped);
- nearest:         the nearest facility whose listing names the service (any band), within the app's search radius;
- best_on_paper:   the highest model p in the origin's state, ignoring distance.
Each pick gets the app's travel estimate, whether it is inside the service's time window, and a published gold label
where one exists (gold v3 DEV web labels and derived/v1 gold pairs; never the sealed TEST). Writes
validation/out/policy_compare.csv and prints a summary table. This is real data, not simulated; gold coverage is
small, and the table says so.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import pandas as pd  # noqa: E402
from facts.engine import WINDOW, Engine  # noqa: E402
from services import SERVICES  # noqa: E402

PLACES = {"Sitamarhi": (26.5951, 85.4808), "Mohania": (25.15, 83.68), "Pusa": (25.6, 85.95), "Patna": (25.61, 85.14),
          "Gaya": (24.78, 85.0), "Bahraich": (27.57, 81.6), "Banda": (25.48, 80.33), "Darbhanga": (26.15, 85.9)}
TAXONOMY = {"trauma_emergency": "trauma_care"}  # app service id -> gold v3 service id where they differ
OUT = ROOT / "validation" / "out" / "policy_compare.csv"


def gold() -> dict[tuple[str, str], str]:
    """(unique_id, app service) -> confirmed / contradicted / no_info, from published DEV gold only."""
    back = {v: k for k, v in TAXONOMY.items()}
    out: dict[tuple[str, str], str] = {}
    for r in pd.read_parquet(ROOT / "derived/v1/gold_pairs.parquet").itertuples():
        out[(r.unique_id, back.get(r.service, r.service))] = r.service_verdict
    for r in json.loads((ROOT / "model/gold/v3/dev_labels.json").read_text())["results"]:
        out[(r["unique_id"], back.get(r["service_id"], r["service_id"]))] = r["service"]  # v3 wins over v1
    return out


def pick(e: Engine, policy: str, service: str, lat: float, lon: float) -> int | None:
    """Facility index chosen by a policy, or None."""
    if policy == "app":
        opts = e.plan(service, lat, lon, 40, "gps")["options"]
        return e.fid[opts[0]["facility_id"]] if opts else None
    if policy == "nearest":
        near = e._near(service, lat, lon)
        return near[0][1].fi if near else None
    state = e.origin_state(lat, lon)
    cands = [pr for pr in e.pairs[service] if pr.model and e._f("state", pr.fi) == state]
    return max(cands, key=lambda pr: pr.model[1]).fi if cands else None


def rows(e: Engine, labels: dict) -> list[dict]:
    by_fi = {s: {pr.fi: pr for pr in e.pairs[s]} for s in SERVICES}
    out = []
    for place, (lat, lon) in PLACES.items():
        state = e.origin_state(lat, lon)
        for s in SERVICES:
            window = WINDOW[SERVICES[s]["profile"]]
            for policy in ("app", "nearest", "best_on_paper"):
                i = pick(e, policy, s, lat, lon)
                if i is None:
                    out.append({"place": place, "service": s, "policy": policy, "facility": "", "minutes": None,
                                "window_min": window, "in_window": False, "band": "", "gold": ""})
                    continue
                pr = by_fi[s][i]
                minutes = e._travel(lat, lon, i, state)["minutes"]
                out.append({"place": place, "service": s, "policy": policy, "facility": e._f("name", i),
                            "minutes": minutes, "window_min": window, "in_window": minutes <= window,
                            "band": Engine.model_band(pr) or "", "gold": labels.get((e._f("id", i), s), "")})
    return out


def summary(rs: list[dict]) -> None:
    print("REAL DATA, demo places; gold = published DEV labels only (coverage is small)")
    print(f"{'policy':<14} {'answers':>7} {'median min':>10} {'in window':>9} {'LIKELY':>6} {'gold n':>6} "
          f"{'confirmed':>9} {'contradicted':>12}")
    for policy in ("app", "nearest", "best_on_paper"):
        r = [x for x in rs if x["policy"] == policy and x["facility"]]
        g = [x["gold"] for x in r if x["gold"] in ("confirmed", "contradicted")]
        print(f"{policy:<14} {len(r):>7} {statistics.median(x['minutes'] for x in r):>10.0f} "
              f"{sum(x['in_window'] for x in r):>4}/{len(r):<4} {sum(x['band'] == 'LIKELY' for x in r):>6} "
              f"{len(g):>6} {g.count('confirmed'):>9} {g.count('contradicted'):>12}")


def main() -> None:
    e = Engine.load()
    if e is None:
        raise SystemExit("run app/facts/build.py first")
    rs = rows(e, gold())
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rs[0]))
        w.writeheader()
        w.writerows(rs)
    summary(rs)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(rs)} rows)")


if __name__ == "__main__":
    main()

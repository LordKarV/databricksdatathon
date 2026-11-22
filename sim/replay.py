"""Live replay of the referral simulation (#92): one patient, the same world, several referral policies side by side.

    .venv-app/bin/python -m sim.replay                       # newest run in sim/out, 30 cases per scenario
    .venv-app/bin/python -m sim.replay --sim-out <dir> --cases 60 --out sim/out/replay.html

Reads what sim/run.py writes (cases/<run>.parquet, events/<run>.parquet, truth/<scenario>_<seed>.parquet) and writes
one self-contained HTML file: no server, no network, no external script. Open it in a browser. It stays local
(sim/out/ is git-ignored) because it names facilities. Every number in it is simulated.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ["app", "nearest_call_first", "best_on_paper", "nearest", "app_offline"]
SHOWN = ["app", "nearest_call_first", "best_on_paper"]  # the default three panels
LABEL = {"app": "Referral Saathi (as shipped)", "app_offline": "Referral Saathi, offline pack",
         "nearest": "Nearest listing", "nearest_call_first": "Nearest + call first",
         "best_on_paper": "Best on paper (highest score in state)"}
SCENARIO = {"S0-high": "S0-high: listing text says nothing, high base rate (a bound; read with S0-low)",
            "S0-low": "S0-low: listing text says nothing, low base rate (a bound; read with S0-high)",
            "S0": "S0: listing text says nothing (offers at base rate)",
            "S1": "S1: the model is right (best case for the app)",
            "S2": "S2: from DEV web labels",
            "S3": "S3: data as bad as the audit says"}


def newest_run(sim_out: Path) -> str:
    runs = sorted((sim_out / "events").glob("*.parquet"), key=lambda p: p.stat().st_mtime)
    if not runs:
        raise SystemExit(f"no runs in {sim_out}/events: run `python -m sim.run` first")
    return runs[-1].stem


def pick_cases(cases: pd.DataFrame, events: pd.DataFrame, n: int) -> pd.DataFrame:
    """n cases per scenario from the first seed, spread across services and urgencies, preferring cases where the
    policies end differently (the interesting ones), then the rest in case order."""
    first_seed = cases.seed.min()
    ev = events[events.seed == first_seed]
    end = (ev[ev.kind.isin(["treated", "gave_up"])].sort_values("t_min")
           .groupby(["scenario", "case_id", "policy"]).kind.first().unstack("policy"))
    differs = end.nunique(axis=1).gt(1).rename("differs").reset_index()
    c = cases[cases.seed == first_seed].merge(differs, on=["scenario", "case_id"], how="inner")
    out = []
    for _, g in c.groupby("scenario"):
        g = g.sort_values(["differs", "case_id"], ascending=[False, True])
        per = -(-n // max(1, g.groupby(["service", "urgency"]).ngroups))  # ceil: n spread over the groups
        out.append(g.groupby(["service", "urgency"], group_keys=False).head(per).head(n))
    return pd.concat(out)


def payload(sim_out: Path, run: str, n: int) -> dict:
    cases = pd.read_parquet(sim_out / "cases" / f"{run}.parquet")
    events = pd.read_parquet(sim_out / "events" / f"{run}.parquet")
    if "scenario" not in cases.columns:  # cases are per seed; the scenario comes from the events
        sc = events[["case_id", "scenario"]].drop_duplicates()
        cases = cases.merge(sc, on="case_id")
    chosen = pick_cases(cases, events, n)
    ev = events.merge(chosen[["case_id", "scenario"]], on=["case_id", "scenario"])
    fids = set(ev.facility_id.dropna())
    loc = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet",
                          columns=["unique_id", "name", "loc_lat", "loc_lon"])
    loc = loc[loc.unique_id.isin(fids)].set_index("unique_id")
    truth = {}
    for (scen, seed), _ in chosen.groupby(["scenario", "seed"]):
        path = sim_out / "truth" / f"{scen}_{seed}.parquet"
        if path.is_file():
            t = pd.read_parquet(path)
            t = t[t.unique_id.isin(fids)]
            truth[scen] = {f"{r.unique_id}|{r.service}": [bool(r.offers), bool(r.phone_ok), bool(r.exists),
                                                           _coord(r.true_lat), _coord(r.true_lon)]
                           for r in t.itertuples()}
    states = sorted(chosen.state.unique())
    pins = pd.read_parquet(ROOT / "derived/v1/pin_gazetteer.parquet", columns=["state", "lat", "lon"]).dropna()
    pins = pins[pins.state.isin(states)]
    steps = {}
    for (scen, cid, pol), g in ev.groupby(["scenario", "case_id", "policy"], sort=False):  # keeps the log order
        steps.setdefault(f"{scen}|{cid}", {})[pol] = [[int(r.step), r.kind, r.facility_id or "", float(r.t_min),
                                                       str(r.outcome)] for r in g.itertuples()]
    return {
        "run": run, "policies": [p for p in POLICIES if p in set(events.policy)], "shown": SHOWN, "label": LABEL,
        "scenarios": {s: SCENARIO.get(s, s) for s in sorted(chosen.scenario.unique())},
        "cases": [{"id": r.case_id, "scenario": r.scenario, "lat": round(r.lat, 4), "lon": round(r.lon, 4),
                   "state": r.state.title(), "district": str(r.district).title(), "service": r.service,
                   "urgency": r.urgency, "window": int(r.window_min), "data": bool(r.has_data),
                   "signal": bool(r.has_phone_signal)} for r in chosen.itertuples()],
        "steps": steps,
        "fac": {f: [str(r["name"]), round(float(r["loc_lat"]), 4), round(float(r["loc_lon"]), 4)]
                for f, r in loc.iterrows()},
        "truth": truth,
        "pins": [[round(a, 3), round(b, 3)] for a, b in zip(pins.lat, pins.lon, strict=True)],
        "summary": summary(events, cases),
    }


def _coord(x: float) -> float | None:
    """A true point, or None when the facility has no findable point."""
    return None if pd.isna(x) else round(float(x), 4)


def summary(events: pd.DataFrame, cases: pd.DataFrame) -> dict:
    """Per scenario and policy, over every case and seed in the run: treated within the window, median minutes to
    care when treated, wasted trips per case."""
    keys = ["scenario", "seed", "policy", "case_id"]
    w = cases[["case_id", "window_min"]].drop_duplicates("case_id").set_index("case_id").window_min
    treated = events[events.kind == "treated"].groupby(keys).t_min.min()
    wasted = events[events.kind == "turned_away"].groupby(keys).size()
    base = events[keys].drop_duplicates().set_index(keys)
    base["t"] = treated
    base["wasted"] = wasted
    base = base.fillna({"wasted": 0}).reset_index()
    base["in_window"] = base.t.le(base.case_id.map(w))
    out: dict = {}
    for (scen, pol), g in base.groupby(["scenario", "policy"]):
        out.setdefault(scen, {})[pol] = {"n": len(g), "in_window": round(float(g.in_window.mean()), 3),
                                         "median_min": None if g.t.isna().all() else round(float(g.t.median())),
                                         "wasted": round(float(g.wasted.mean()), 2)}
    return out


TEMPLATE = Path(__file__).resolve().parent / "replay_template.html"  # the page; __DATA__ is replaced


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim-out", type=Path, default=ROOT / "sim" / "out")
    ap.add_argument("--run", help="run id (default: the newest in sim-out/events)")
    ap.add_argument("--cases", type=int, default=30, help="patients per scenario")
    ap.add_argument("--out", type=Path, help="output file (default: <sim-out>/replay.html)")
    a = ap.parse_args()
    run = a.run or newest_run(a.sim_out)
    data = payload(a.sim_out, run, a.cases)
    out = a.out or a.sim_out / "replay.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.read_text().replace("__DATA__", json.dumps(data, separators=(",", ":"), ensure_ascii=False)
                                .replace("</", "<\\/")))
    n = sum(1 for _ in data["cases"])
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB): {n} patients, run {run}, "
          f"policies {', '.join(data['policies'])}. Simulated; local only (names facilities).")


if __name__ == "__main__":
    main()

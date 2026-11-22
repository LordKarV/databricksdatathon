"""What each outside source adds to the frozen model v2 scores and to the app's first answer (WS5 5d, issue #140).

    python validation/source_impact.py      # from the repo root, after app/facts/build.py

For every outside source that feeds a scorecard term, it removes that source's points from each pair's stored
additive contributions (derived/v2/facility_service_scores.parquet; 20 points = one doubling of the odds) and asks:
- pairs fired, and LIKELY pairs it fires on, over the 7 app services;
- likely_lost: LIKELY pairs whose service score p would fall below t_L without it;
- likely_lost_gates: LIKELY pairs whose existence (P_E) or location (P_L) score would fall below the 0.7 LIKELY gate
  without it. NABH and OSM also feed those heads (e_nabh_listed, e_osm_high/medium, l_d_nabh_listed,
  l_osm_conflict; weights in model/v2/fit_prior/out/params_A.json), removed here from the stored logits;
- reach_t_u: pairs not UNLIKELY whose p would fall to t_U or below without it;
- per service, how often the app's first option changes without it, over 300 seeded PIN centres
  (Engine._ranked with the source-free p). Bands are held as shipped in this count: a pair that would turn UNLIKELY
  (reach_t_u) stays in the pool.
The frozen model is not touched: this is a counterfactual on the published points, never a refit. Writes
validation/out/source_impact.csv and prints it.
"""
from __future__ import annotations

import csv
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import pandas as pd  # noqa: E402
from facts.engine import SERVICES, Engine  # noqa: E402

OUT = ROOT / "validation" / "out" / "source_impact.csv"
TAXONOMY = {"trauma_emergency": "trauma_care"}  # app service id -> score service id where they differ
POINTS_PER_LOGIT = 20 / math.log(2)
N_ORIGINS, SEED, TOP_N = 300, 7, 30
LISTS_LINE = "'Official lists' line (WS4 4a, #150)"
# term label prefix -> (source, where it shows in the app)
SOURCES = {
    "x_nabh": ("NABH accreditation list", f"Why page ledger row; {LISTS_LINE}"),
    "x_nmc": ("NMC medical colleges", f"Why page ledger row; {LISTS_LINE}"),
    "x_erk_prereq": ("e-RaktKosh blood centres", "Why page ledger row (a blood centre, a prerequisite for C-section, "
                     f"trauma, burns and cardiac surgery); {LISTS_LINE}"),
    "x_laqshya": ("NHSRC LaQshya certification", f"Why page ledger row; {LISTS_LINE}"),
    "x_mohfw_tcf": ("MoHFW trauma care facilities", f"Why page ledger row; {LISTS_LINE}"),
    "x_pmndp": ("PMNDP dialysis lists", f"Why page ledger row; {LISTS_LINE}"),
    "o_": ("OpenStreetMap (HOT export)", "Why page ledger row"),
    "k_iphs": ("IPHS 2022 public standard", "Why page ledger row; public-standard option"),
}
ALL_LISTS = "all lists and OSM (X and O families)"
# existence and location head terms fed by a source (prior_a.existence_terms, location_terms)
GATE_TERMS = {"x_nabh": ("e_nabh_listed", "l_d_nabh_listed"), "o_": ("e_osm_high", "e_osm_medium", "l_osm_conflict")}
GATE_TERMS[ALL_LISTS] = GATE_TERMS["x_nabh"] + GATE_TERMS["o_"]


def source_of(label: str) -> str | None:
    return next((k for k in SOURCES if label.startswith(k)), None)


def load_points() -> tuple[pd.DataFrame, dict]:
    """One row per app pair: p, band, and points per source key (plus ALL_LISTS)."""
    s = pd.read_parquet(ROOT / "derived/v2/facility_service_scores.parquet",
                        columns=["unique_id", "service_id", "p", "band", "p_exists", "p_location", "contributions"])
    s = s[s.service_id.isin({TAXONOMY.get(k, k) for k in SERVICES})]
    pts: dict = {}
    for r in s.itertuples(index=False):
        d: dict[str, float] = {}
        for t in json.loads(r.contributions):
            k = source_of(t["label"])
            if k:
                d[k] = d.get(k, 0.0) + t["points"]
            if t["family"] in ("X", "O"):
                d[ALL_LISTS] = d.get(ALL_LISTS, 0.0) + t["points"]
        if d:
            pts[(r.unique_id, r.service_id)] = d
    return s, pts


def gate_logits() -> dict[str, dict[str, float]]:
    """{unique_id: {gate term: logit it adds to P_E or P_L}} for the list and OSM terms that fire on the facility."""
    w = {t["name"]: t["weight"] for h in ("existence", "location")
         for t in json.loads((ROOT / "model/v2/fit_prior/out/params_A.json").read_text())[h]}
    ff = pd.read_parquet(ROOT / "derived/v2/facility_features.parquet",
                         columns=["unique_id", "d_nabh_listed", "f_osm_conflict"]).drop_duplicates("unique_id")
    o = pd.read_parquet(ROOT / "derived/v2/witnesses.parquet",
                        columns=["unique_id", "service", "family", "witness", "observability"])
    o = o[(o.family == "O") & (o.observability == "present") & (o.service == "*") & o.witness.str.contains("_match_")]
    tier = o.assign(t=o.witness.str.split("_").str[-1]).sort_values("t").groupby("unique_id").t.first().to_dict()
    out: dict[str, dict[str, float]] = {}
    for r in ff.itertuples(index=False):  # same indicators as prior_a.existence_design and location_design
        d = {}
        if r.d_nabh_listed == 1:
            d |= {"e_nabh_listed": w["e_nabh_listed"], "l_d_nabh_listed": w["l_d_nabh_listed"]}
        if r.f_osm_conflict == 1:
            d["l_osm_conflict"] = w["l_osm_conflict"]
        if tier.get(r.unique_id) in ("high", "medium"):
            d[f"e_osm_{tier[r.unique_id]}"] = w[f"e_osm_{tier[r.unique_id]}"]
        if d:
            out[r.unique_id] = d
    return out


def drop_logit(p: float, logit: float) -> float:
    return 1 / (1 + math.exp(-(math.log(p / (1 - p)) - logit)))


def without(p: float, points: float) -> float:
    return 1 / (1 + math.exp(-(math.log(p / (1 - p)) - points / POINTS_PER_LOGIT)))


def top1_changes(e: Engine, key: str, pts: dict, origins: list) -> dict[str, str]:
    """Per app service: 'changed of answered' when this source's points are removed."""
    out = {}
    for svc in SERVICES:
        sid = TAXONOMY.get(svc, svc)
        changed = n = 0
        for lat, lon in origins:
            pool, _ = e._ranked(svc, lat, lon)
            if not pool:
                continue
            n += 1
            ov = {}
            for row in pool[:TOP_N]:
                fid = e._f("id", row[2].fi)
                v = pts.get((fid, sid), {}).get(key)
                if v:
                    b, p, lo, hi, c, ev = e.score(fid, svc)
                    ov[fid] = (b, without(p, v), lo, hi, c, ev)
            if ov:
                pool2, _ = e._ranked(svc, lat, lon, scores=ov)
                changed += pool2[0][2].fi != pool[0][2].fi
        out[svc] = f"{changed} of {n}"
    return out


def main() -> None:
    bt = json.loads((ROOT / "derived/v2/model_card.json").read_text())["band_thresholds"]
    t_l, t_u = bt["likely"]["p"], bt["unlikely"]["p"]
    gate_e, gate_l = bt["likely"]["p_exists"], bt["likely"]["p_location"]
    s, pts = load_points()
    band = {(r.unique_id, r.service_id): (r.band, r.p) for r in s.itertuples(index=False)}
    gates = gate_logits()
    all_likely = list(s[s.band == "LIKELY"][["unique_id", "p_exists", "p_location"]].itertuples(index=False))

    def gate_lost(key: str) -> int:
        """LIKELY pairs whose P_E or P_L falls below its gate when this source's head terms are removed."""
        n = 0
        for r in all_likely:
            g = {t: v for t, v in gates.get(r.unique_id, {}).items() if t in GATE_TERMS.get(key, ())}
            pe = drop_logit(r.p_exists, sum(v for t, v in g.items() if t.startswith("e_")))
            pl = drop_logit(r.p_location, sum(v for t, v in g.items() if t.startswith("l_")))
            n += pe < gate_e or pl < gate_l
        return n
    e = Engine.load()
    assert e is not None, "app/facts/out is missing: run app/facts/build.py first"
    rng = random.Random(SEED)
    origins = [(e.pins["lat"][j], e.pins["lon"][j]) for j in rng.sample(range(len(e.pins["pin"])), N_ORIGINS)]
    rows = []
    for key in [*SOURCES, ALL_LISTS]:
        fired = [k for k, d in pts.items() if d.get(key)]
        likely = [k for k in fired if band[k][0] == "LIKELY"]
        name, where = SOURCES.get(key, (ALL_LISTS, "as above"))
        rows.append({"source": name, "term_prefix": key if key in SOURCES else "X,O",
                     "family": {"o_": "O", "k_iphs": "K", ALL_LISTS: "X+O"}.get(key, "X"),
                     "pairs_fired": len(fired), "likely_pairs": len(likely),
                     "likely_lost": sum(without(band[k][1], pts[k][key]) < t_l for k in likely),
                     "likely_lost_gates": gate_lost(key),
                     "reach_t_u": sum(band[k][0] != "UNLIKELY" and without(band[k][1], pts[k][key]) <= t_u
                                      for k in fired),
                     **{f"top1_changes_{svc}": v for svc, v in top1_changes(e, key, pts, origins).items()},
                     "where_it_shows": where})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(pd.DataFrame(rows).drop(columns=["where_it_shows"]).to_string(index=False))


if __name__ == "__main__":
    main()

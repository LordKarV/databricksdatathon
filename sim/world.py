"""Simulated referral world for #92: cases, the hidden truth per scenario, and outages. SIMULATED, not field data.

    from sim import world
    cases = world.cases(seed=1)                  # one row per simulated patient
    truth = world.truth_table("S2", seed=1)      # read only by sim/execute.py
    lst = world.listing("dialysis")              # what a policy may see

Only sim/execute.py may call truth_table(). Policies get listing() rows, which hold no truth column.
Gold labels: only the v3 DEV file is read (for S0 and S2). The sealed TEST labels (#51) are never opened.
Seeded: the same seed gives the same cases and the same truth. Truth uniforms are drawn once per seed and
shared by every scenario and knob level, so scenarios differ only by their rates (common random numbers).
"""
from __future__ import annotations

import json
import re
from functools import cache, lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
V1, V2 = ROOT / "derived" / "v1", ROOT / "derived" / "v2"
DEV_LABELS = ROOT / "model" / "gold" / "v3" / "dev_labels.json"  # DEV only
PATHWAYS = ROOT / "kb" / "pathways" / "care_pathways.json"
OUT = ROOT / "sim" / "out"
SIMULATED = "SIMULATED: synthetic referral world (#92), not field data"

STATES = ("BIHAR", "UTTAR PRADESH")  # minimum scope (#92 lead comment)
# app service id -> derived/v1 grade name, derived/v2 and gold v3 id, urgency, pathway and the stage whose window
# counts. dialysis_start has no deadline (its 60480 min is a wait before first fistula use), so dialysis takes the
# app's own window for its profile (app/facts/engine.py WINDOW["scheduled"] = 120).
SERVICES = {
    "dialysis": {"v1": "dialysis", "v2": "dialysis", "urgency": "planned", "pathway": "dialysis_start",
                 "stage": None, "window_min": 120},
    "trauma_emergency": {"v1": "trauma", "v2": "trauma_care", "urgency": "emergency", "pathway": "major_trauma",
                         "stage": "stabilise", "window_min": None},
}
SCENARIOS = ("S0", "S1", "S2", "S3")
CASES_PER_CELL = 200  # per state x service x seed
P_HAS_DATA = 0.8  # assumption: share of cases with mobile data
P_PHONE_SIGNAL = 0.9  # assumption: share of cases where a call can be placed
# Sensitivity knobs (#92 update). mid is the default; every value is an assumption, swept low/mid/high.
KNOBS = {
    "accept_p": {"low": 0.6, "mid": 0.8, "high": 0.95},     # a facility that offers it takes this patient now
    "phone_ok": {"low": 0.3, "mid": 0.5, "high": 0.8},      # the listed number reaches the facility (PHONE_UNCHECKED
                                                            # q_ev 0.5 in derived/v1/evidence_rules)
    "wrong_yes": {"low": 0.05, "mid": 0.15, "high": 0.3},   # a "yes" on the phone that is wrong
    "open_now_p": {"low": 0.7, "mid": 0.9, "high": 0.98},   # open and staffed when the patient arrives
}
MID = {k: v["mid"] for k, v in KNOBS.items()}
SMOOTH = 2  # pseudo-count pulling a small DEV cell towards its pooled rate
RISKS = re.compile(r"location|collision|elsewhere")  # model/gold/v3/build_sample_v3.py "suspect" rule
FAR_KM = 50
TRUTH_COLS = ["unique_id", "service", "exists", "offers", "phone_ok", "open_now_p", "accept_p", "true_lat",
              "true_lon"]


def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    """Parquet with the SIMULATED note in the file metadata, so no copy of the table loses the label."""
    path.parent.mkdir(parents=True, exist_ok=True)
    t = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(t.replace_schema_metadata({**(t.schema.metadata or {}), b"simulated": SIMULATED.encode()}), path)
    return path


def window_min(service: str) -> int:
    meta = SERVICES[service]
    if meta["window_min"] is not None:
        return meta["window_min"]
    pw = next(p for p in json.loads(PATHWAYS.read_text())["pathways"] if p["id"] == meta["pathway"])
    return int(next(s for s in pw["stages"] if s["id"] == meta["stage"])["window"]["minutes"])


@lru_cache(maxsize=1)
def facilities() -> pd.DataFrame:
    """One row per facility scored by derived/v2 (the app's eligible set): listed point, alternative point, state,
    operator, whether a phone is listed, its location rule, and whether the map point is far from its PIN."""
    ids = pd.read_parquet(V2 / "facility_service_scores.parquet", columns=["unique_id"]).drop_duplicates()
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=[
        "unique_id", "state_final", "loc_lat", "loc_lon", "alt_lat", "alt_lon", "raw_coords_to_pin_km"])
    ph = pd.read_parquet(V1 / "record_trust.parquet", columns=["unique_id", "display_phones"])
    ft = pd.read_parquet(V1 / "facility_trust.parquet", columns=["unique_id", "location_reason_codes"])
    op = pd.read_parquet(V2 / "facility_attributes.parquet", columns=["unique_id", "operator"])
    f = ids.merge(loc, on="unique_id", how="left").merge(ph, on="unique_id", how="left")
    f = f.merge(ft, on="unique_id", how="left").merge(op, on="unique_id", how="left")
    f["has_phone"] = [x is not None and len(x) > 0 for x in f.display_phones]
    f["loc_rule"] = f.location_reason_codes.fillna("").str.extract(r"(LOC_[A-Z_]+)", expand=False).fillna("LOC_HIGH")
    f["far"] = f.raw_coords_to_pin_km.fillna(0) > FAR_KM
    f["operator"] = f.operator.fillna("unknown")
    f = f.rename(columns={"state_final": "state", "loc_lat": "lat", "loc_lon": "lon"})
    return f[["unique_id", "state", "lat", "lon", "alt_lat", "alt_lon", "operator", "has_phone", "loc_rule", "far"]]


@cache
def _pairs(service: str) -> pd.DataFrame:
    """Every facility x this service: v2 p and p_exists, the v1 grade (None when the listing never names the
    service) and the DEV stratum the same pair would fall in."""
    meta = SERVICES[service]
    v2 = pd.read_parquet(V2 / "facility_service_scores.parquet", columns=["unique_id", "service_id", "p", "p_exists"],
                         filters=[("service_id", "==", meta["v2"])]).drop(columns="service_id")
    g = pd.read_parquet(V1 / "grades.parquet", columns=["unique_id", "service", "grade", "risks"],
                        filters=[("service", "==", meta["v1"])]).drop(columns="service")
    d = facilities().merge(v2, on="unique_id", how="left").merge(g, on="unique_id", how="left")
    risky = d.risks.fillna("").str.contains(RISKS) | d.far | d.grade.isin(["attributed_elsewhere", "counter_evidence"])
    d["stratum"] = np.select([d.grade.isna(), risky, d.grade.eq("strong")], ["no_mention", "suspect", "strong"],
                             "weak")
    d["service"] = service
    return d


def listing(service: str) -> pd.DataFrame:
    """What a policy may see for one service: facilities whose listing names it (a derived/v1 service claim, the
    app's own candidate pool), with the listed point, state, operator and the published v2 p. No truth column."""
    d = _pairs(service)
    d = d[d.grade.notna() & d.lat.notna() & d.lon.notna()]
    return d[["unique_id", "service", "state", "lat", "lon", "operator", "p"]].reset_index(drop=True)


@lru_cache(maxsize=1)
def _dev() -> pd.DataFrame:
    """Decided gold v3 DEV pairs (confirmed or contradicted) for the services in scope, with operator."""
    lab = pd.DataFrame(json.loads(DEV_LABELS.read_text())["results"])
    lab = lab[lab.service.isin(["confirmed", "contradicted"])].copy()
    lab["yes"] = lab.service.eq("confirmed").astype(float)
    lab["w"] = 1.0 / lab.inclusion_prob
    op = facilities().set_index("unique_id").operator
    lab["operator"] = lab.unique_id.map(op).fillna("unknown")
    return lab


def _shrunk(rate: pd.Series, n: pd.Series, prior: pd.Series | float) -> pd.Series:
    return (rate * n + SMOOTH * prior) / (n + SMOOTH)


@lru_cache(maxsize=1)
def s2_rates() -> pd.Series:
    """S2: P(offers) by (gold service id, stratum) from the DEV labels, pulled towards the stratum's rate over all
    services. Unweighted within a cell (one inclusion probability per cell, up to the focus / rest split)."""
    lab = _dev()
    pooled = lab.groupby("stratum").yes.mean()
    cell = lab.groupby(["service_id", "stratum"]).yes.agg(["mean", "size"])
    return _shrunk(cell["mean"], cell["size"], pooled.reindex(cell.index.get_level_values(1)).to_numpy())


@lru_cache(maxsize=1)
def s0_rates() -> pd.Series:
    """S0 "text says nothing": P(offers) by (gold service id, operator), the DEV frame rate weighted by
    1 / inclusion_prob, so the same for every facility of that operator whatever its text says."""
    lab = _dev()
    lab = lab.assign(wy=lab.w * lab.yes)
    svc = lab.groupby("service_id").wy.sum() / lab.groupby("service_id").w.sum()
    g = lab.groupby(["service_id", "operator"])
    cell = (g.wy.sum() / g.w.sum()).to_frame("mean").assign(size=g.size())
    return _shrunk(cell["mean"], cell["size"], svc.reindex(cell.index.get_level_values(0)).to_numpy())


@lru_cache(maxsize=1)
def audit_q() -> dict[str, float]:
    """q_ev per evidence rule from derived/v1/evidence_rules: LOC_* = P(map point right), EXISTS_DEFAULT."""
    e = pd.read_parquet(V1 / "evidence_rules.parquet", columns=["rule", "q_ev"])
    return dict(zip(e.rule, e.q_ev, strict=True))


def _rate(table: pd.Series, keys: pd.MultiIndex, fallback: float) -> np.ndarray:
    return table.reindex(keys).fillna(fallback).to_numpy()


def truth_table(scenario: str, seed: int, knobs: dict | None = None) -> pd.DataFrame:
    """The hidden truth: one row per facility x service in scope (TRUTH_COLS). Read only by sim/execute.py."""
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}, got {scenario!r}")
    k = {**MID, **(knobs or {})}
    q = audit_q()
    out = []
    for i, service in enumerate(SERVICES):
        d = _pairs(service)
        u = np.random.default_rng([seed, i]).random((4, len(d)))  # offers, exists, phone, map; shared by scenarios
        gid = SERVICES[service]["v2"]
        if scenario == "S0":
            p_off = _rate(s0_rates(), pd.MultiIndex.from_arrays([[gid] * len(d), d.operator]), s0_rates().mean())
        elif scenario == "S1":
            p_off = d.p.fillna(0).to_numpy()
        else:
            p_off = _rate(s2_rates(), pd.MultiIndex.from_arrays([[gid] * len(d), d.stratum]), s2_rates().mean())
        offers = u[0] < p_off
        if scenario == "S3":  # a sentence attributed to another facility is false
            offers &= ~d.grade.eq("attributed_elsewhere").to_numpy()
        p_exist = d.p_exists.fillna(q["EXISTS_DEFAULT"]).to_numpy() if scenario == "S1" else q["EXISTS_DEFAULT"]
        lat, lon = d.lat.to_numpy(float), d.lon.to_numpy(float)
        if scenario == "S3":  # map point wrong at the audit's rate for its rule; the truth is the alternative point
            wrong = u[3] >= d.loc_rule.map(q).fillna(q["LOC_HIGH"]).to_numpy()
            lat = np.where(wrong, d.alt_lat.to_numpy(float), lat)  # NaN when there is no alternative: not findable
            lon = np.where(wrong, d.alt_lon.to_numpy(float), lon)
        out.append(pd.DataFrame({
            "unique_id": d.unique_id, "service": service, "exists": u[1] < p_exist, "offers": offers,
            "phone_ok": d.has_phone.to_numpy() & (u[2] < k["phone_ok"]), "open_now_p": float(k["open_now_p"]),
            "accept_p": float(k["accept_p"]), "true_lat": lat, "true_lon": lon}))
    return pd.concat(out, ignore_index=True)[TRUTH_COLS]


def write_truth(scenario: str, seed: int, knobs: dict | None = None, out: Path = OUT) -> Path:
    return write_parquet(truth_table(scenario, seed, knobs), out / "truth" / f"{scenario}_{seed}.parquet")


@lru_cache(maxsize=1)
def _pins() -> pd.DataFrame:
    p = pd.read_parquet(V1 / "pin_gazetteer.parquet", columns=["pin", "state", "district", "lat", "lon"])
    return p.dropna(subset=["lat", "lon", "district"]).sort_values("pin").reset_index(drop=True)


def cases(seed: int, states: tuple[str, ...] = STATES, n: int = CASES_PER_CELL) -> pd.DataFrame:
    """n simulated patients per state x service. Origins are PIN centroids drawn uniformly within the state (no
    population table is in the repo, so PIN density stands in for population). t0_min is the minute of the day."""
    rng = np.random.default_rng([seed, 99])
    pins = _pins()
    rows = []
    for state in states:
        sp = pins[pins.state == state]
        if sp.empty:
            raise ValueError(f"no PIN centroids for state {state!r}")
        for service, meta in SERVICES.items():
            pick = sp.iloc[rng.integers(len(sp), size=n)]
            rows.append(pd.DataFrame({
                "case_id": [f"{seed}-{state[:2]}-{service}-{j}" for j in range(n)], "seed": seed,
                "lat": pick.lat.to_numpy(), "lon": pick.lon.to_numpy(), "state": state,
                "district": pick.district.to_numpy(), "service": service, "urgency": meta["urgency"],
                "window_min": window_min(service), "t0_min": rng.integers(0, 1440, size=n),
                "has_data": rng.random(n) < P_HAS_DATA, "has_phone_signal": rng.random(n) < P_PHONE_SIGNAL}))
    return pd.concat(rows, ignore_index=True)

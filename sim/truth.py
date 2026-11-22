"""Hidden truth for the simulated referral world (issue #92). Simulated: never field results.

Writes sim/out/truth/<scenario>_<seed>.parquet with TRUTH_COLUMNS (sim/interface.py), one row per facility and app
service. Four scenarios, every result is reported for each one (S1 never alone):

- S0 "text says nothing": P(offers) is a base rate by service x operator group (public by derived/v2 operator or by
  name, else private or unknown), from the DEV labels. No text feature and no model p is used. The app can lose here.
- S1 "model is right": offers ~ Bernoulli(derived/v2 p). Circular, the best case for the app.
- S2 "from labels": P(offers) by service x evidence grade (derived/v1/grades) x attribution (a sentence about the
  service attributed to another facility, derived/v1/claims attribution == "other_facility"), from the gold v3 DEV
  labels, independent of p.
- S3 "data as bad as the audit says": S2, plus other-facility sentences are false (a pair whose only sentences are
  attributed elsewhere does not offer; one with its own sentences takes the rate of the same grade without the
  attribution), plus records flagged coords_pin_conflict_gt50km really sit at their alternative point.

Rates from labels (S0, S2): decided DEV labels only (confirmed vs contradicted; no_info is missing, as the headline in
model/gold/v3/merge_labels.py), weighted 1 / inclusion_prob. A cell's weighted rate r_c with Kish effective n n_c is
shrunk toward its service rate r_s with a Beta prior of strength k_cell: (n_c r_c + k_cell r_s) / (n_c + k_cell).
r_s is itself shrunk toward the all-service rate with k_service. A cell with no label takes r_s.

Every scenario uses the same uniform draws per seed (common random numbers), so scenarios differ only in rates.
Only the DEV labels file is read: never the sealed TEST labels or the custodian's copy of them (#51).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from dataclasses import replace
from functools import cache
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd

from sim.assumptions import DEFAULT, Assumptions
from sim.interface import ROOT, SCENARIOS, SERVICES, TRUTH_COLUMNS, TRUTH_DIR, URGENCY

V1 = ROOT / "derived" / "v1"
V2 = ROOT / "derived" / "v2"
DEV_LABELS = ROOT / "model" / "gold" / "v3" / "dev_labels.json"
APP_SERVICES = tuple(URGENCY)
GRADE_NONE = "none"  # no grades.parquet row: the listing does not mention the service
LARGE_N_SERVICES = 6  # the DEV no_mention frame: public by name, or 6+ services claimed (build_sample_v3.py)
LOC_CONFLICT = "coords_pin_conflict_gt50km"


@cache
def _facts_build() -> ModuleType:
    """app/facts/build.py loaded by path, for its service maps and public-standard rule (one source of truth)."""
    spec = importlib.util.spec_from_file_location("_rs_facts_build", ROOT / "app" / "facts" / "build.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _maps() -> tuple[dict[str, str], dict[str, str]]:
    """app id -> taxonomy id (derived/v2, DEV labels), app id -> derived/v1 service name."""
    b = _facts_build()
    return {a: b.APP_TO_TAXONOMY.get(a, a) for a in APP_SERVICES}, dict(b.SERVICE_MAP)


def _phones() -> pd.DataFrame:
    rt = pd.read_parquet(V1 / "record_trust.parquet",
                         columns=["unique_id", "display_phones", "trust_flags", "n_services_claimed"])
    first = [str(p[0]) if isinstance(p, (list, tuple, np.ndarray)) and len(p) else "" for p in rt.display_phones]
    shared = pd.Series([str(x) for p in rt.display_phones if p is not None for x in set(p)]).value_counts()
    rt["phone_listed"] = [bool(p) for p in first]
    rt["phone_shared"] = [int(shared.get(p, 0)) if p else 0 for p in first]
    rt["phone_directory"] = [isinstance(f, (list, tuple, np.ndarray)) and "official_phone_is_directory" in list(f)
                             for f in rt.trust_flags]
    return rt[["unique_id", "phone_listed", "phone_shared", "phone_directory", "n_services_claimed"]]


def _facilities() -> pd.DataFrame:
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=[
        "unique_id", "name", "state_final", "loc_lat", "loc_lon", "loc_flags", "alt_lat", "alt_lon", "pin"])
    pins = pd.read_parquet(V1 / "pin_gazetteer.parquet", columns=["pin", "lat", "lon"]).rename(
        columns={"lat": "pin_lat", "lon": "pin_lon"}).astype({"pin": float})
    loc = loc.merge(pins, on="pin", how="left")
    loc["loc_conflict"] = [isinstance(f, (list, tuple, np.ndarray)) and LOC_CONFLICT in list(f) for f in loc.loc_flags]
    ft = pd.read_parquet(V1 / "facility_trust.parquet", columns=["unique_id", "existence_score"])
    op = pd.read_parquet(V2 / "facility_attributes.parquet", columns=["unique_id", "operator"]).drop_duplicates(
        "unique_id")
    f = loc.merge(ft, on="unique_id", how="left").merge(op, on="unique_id", how="left").merge(
        _phones(), on="unique_id", how="left")
    f["public_name"] = f.name.fillna("").str.contains(_facts_build().PUBLIC_STANDARD)
    f["group"] = np.where((f.operator == "public") | f.public_name, "public", "private_or_unknown")
    f["in_no_mention_frame"] = f.public_name | (f.n_services_claimed.fillna(0) >= LARGE_N_SERVICES)
    return f.drop(columns=["loc_flags", "name"])


def _attributed_elsewhere(v1_names: dict[str, str]) -> set[tuple[str, str]]:
    """(unique_id, app service) pairs with a sentence naming the service that is attributed to another facility."""
    c = pd.read_parquet(V1 / "claims.parquet", columns=["unique_id", "services", "attribution"])
    c = c[(c.attribution == "other_facility") & (c.services.fillna("") != "")]
    to_app = {v: k for k, v in v1_names.items()}
    out = set()
    for u, s in zip(c.unique_id, c.services, strict=True):
        for name in s.split("|"):
            if name in to_app:
                out.add((u, to_app[name]))
    return out


@cache
def base_frame() -> pd.DataFrame:
    """One row per (facility, app service) for every facility derived/v2 scores, all 7 app services, sorted.

    Columns used by the scenarios: p (v2), is_24x7, grade, n_own_distinct, attr_other, group, in_no_mention_frame,
    existence_score, phone fields, map point, alternative point, PIN centroid.
    """
    to_tax, to_v1 = _maps()
    tax_to_app = {t: a for a, t in to_tax.items()}
    v2 = pd.read_parquet(V2 / "facility_service_scores.parquet", columns=["unique_id", "service_id", "p", "is_24x7"])
    v2 = v2[v2.service_id.isin(tax_to_app)]
    v2 = v2.assign(service=v2.service_id.map(tax_to_app)).drop(columns="service_id")
    g = pd.read_parquet(V1 / "grades.parquet", columns=["unique_id", "service", "grade", "n_own_distinct"])
    v1_to_app = {v: k for k, v in to_v1.items()}
    g = g[g.service.isin(v1_to_app)].assign(service=lambda d: d.service.map(v1_to_app))
    df = v2.merge(g, on=["unique_id", "service"], how="left").merge(_facilities(), on="unique_id", how="left")
    df["grade"] = df.grade.fillna(GRADE_NONE)
    df["n_own_distinct"] = df.n_own_distinct.fillna(0).astype(int)
    attr = _attributed_elsewhere(to_v1)
    df["attr_other"] = [(u, s) in attr for u, s in zip(df.unique_id, df.service, strict=True)]
    df["is_24x7"] = df.is_24x7.fillna(False).astype(bool)
    return df.sort_values(["unique_id", "service"]).reset_index(drop=True)


# ---------------------------------------------------------------------------------------------------------------------
# Rates from the DEV labels
def dev_labels() -> pd.DataFrame:
    """Decided DEV labels for the 7 app services: unique_id, service (app id), y (1 confirmed), w (1/inclusion_prob)."""
    assert DEV_LABELS.name == "dev_labels.json"  # TEST labels are never read (#51)
    rows = json.loads(DEV_LABELS.read_text())["results"]
    to_tax, _ = _maps()
    tax_to_app = {t: a for a, t in to_tax.items()}
    d = pd.DataFrame(rows)
    d = d[d.service_id.isin(tax_to_app) & d.service.isin(["confirmed", "contradicted"]) & d.inclusion_prob.gt(0)]
    return pd.DataFrame({"unique_id": d.unique_id, "service": d.service_id.map(tax_to_app),
                         "y": (d.service == "confirmed").astype(float), "w": 1 / d.inclusion_prob}).reset_index(
        drop=True)


def _wrate(d: pd.DataFrame) -> tuple[float, float]:
    """(weighted rate, Kish effective n)."""
    if d.empty:
        return float("nan"), 0.0
    w = d.w.to_numpy()
    return float((w * d.y.to_numpy()).sum() / w.sum()), float(w.sum() ** 2 / (w**2).sum())


def labelled(features: list[str]) -> pd.DataFrame:
    """DEV decided labels joined to the base frame's features."""
    lab = dev_labels()
    return lab.merge(base_frame()[["unique_id", "service", *features]], on=["unique_id", "service"], how="inner")


def rate_table(features: list[str], a: Assumptions = DEFAULT) -> pd.DataFrame:
    """Shrunk P(offers) per (service, *features) cell seen in the labels, with raw rate, n, n_eff and the service rate.

    Cells not listed take the service rate (column r_service of any row of that service, see rate_of()).
    """
    lab = labelled(features)
    g_rate, _ = _wrate(lab)
    rows = []
    for svc, ds in lab.groupby("service"):
        rs_raw, ns = _wrate(ds)
        rs = (ns * rs_raw + a.k_service * g_rate) / (ns + a.k_service)
        for key, dc in ds.groupby(features):
            rc_raw, nc = _wrate(dc)
            key = key if isinstance(key, tuple) else (key,)
            rows.append({"service": svc, **dict(zip(features, key, strict=True)), "n": len(dc), "n_eff": nc,
                         "rate_raw": rc_raw, "rate": (nc * rc_raw + a.k_cell * rs) / (nc + a.k_cell),
                         "r_service": rs, "r_service_raw": rs_raw, "n_eff_service": ns, "r_all": g_rate})
    return pd.DataFrame(rows)


def rate_of(frame: pd.DataFrame, table: pd.DataFrame, features: list[str]) -> np.ndarray:
    """P(offers) for each row of frame from a rate_table; unseen cells take the service rate, else the all rate."""
    m = frame[["service", *features]].merge(table[["service", *features, "rate"]], on=["service", *features],
                                            how="left")
    svc = table.drop_duplicates("service").set_index("service")
    fill = frame.service.map(svc.r_service).fillna(table.r_all.iloc[0]).to_numpy()
    return np.where(m.rate.isna().to_numpy(), fill, m.rate.to_numpy())


def offer_p(scenario: str, a: Assumptions = DEFAULT, frame: pd.DataFrame | None = None) -> np.ndarray:
    """Expected P(offers) per row of the base frame (or `frame`) under a scenario."""
    if frame is None:
        return _offer_p_base(scenario, a.k_cell, a.k_service, a.no_mention_outside_frame_p).copy()
    return _offer_p(scenario, a, frame)


@cache
def _offer_p_base(scenario: str, k_cell: float, k_service: float, outside_p: float) -> np.ndarray:
    a = replace(DEFAULT, k_cell=k_cell, k_service=k_service, no_mention_outside_frame_p=outside_p)
    return _offer_p(scenario, a, base_frame())


def _offer_p(scenario: str, a: Assumptions, f: pd.DataFrame) -> np.ndarray:
    if scenario == "S1":
        return f.p.to_numpy(dtype=float)
    if scenario == "S0":
        return rate_of(f, rate_table(["group"], a), ["group"])
    feats = ["grade", "attr_other"]
    table = rate_table(feats, a)
    outside = ((f.grade == GRADE_NONE) & ~f.in_no_mention_frame).to_numpy()
    p = rate_of(f, table, feats)
    if scenario == "S3":
        attr = f.attr_other.to_numpy()
        no_own = (f.n_own_distinct == 0).to_numpy() | (f.grade == "attributed_elsewhere").to_numpy()
        p_clean = rate_of(f.assign(attr_other=False), table, feats)
        p = np.where(attr & no_own, 0.0, np.where(attr, p_clean, p))
    elif scenario != "S2":
        raise ValueError(f"unknown scenario {scenario}")
    return np.where(outside, a.no_mention_outside_frame_p, p)


# ---------------------------------------------------------------------------------------------------------------------
def build_truth(scenario: str, seed: int, services: tuple[str, ...] = SERVICES, a: Assumptions = DEFAULT
                ) -> pd.DataFrame:
    """The truth table for one scenario and seed (TRUTH_COLUMNS), restricted to `services`."""
    f = base_frame()
    rng = np.random.default_rng([seed, 92])  # the same draws for every scenario (common random numbers)
    fac = f.unique_id.to_numpy()
    first = np.r_[True, fac[1:] != fac[:-1]]
    fac_idx = np.cumsum(first) - 1
    n_fac = int(first.sum())
    u_exist, u_phone = rng.random(n_fac)[fac_idx], rng.random(n_fac)[fac_idx]
    u_offer = rng.random(len(f))

    exists = u_exist < f.existence_score.fillna(a.exists_p_missing).to_numpy()
    own_number = (f.phone_listed.fillna(False) & ~f.phone_directory.fillna(False)
                  & (f.phone_shared.fillna(0) < a.phone_shared_min)).to_numpy(dtype=bool)
    phone_ok = own_number & (u_phone < a.phone_ok_p)
    offers = u_offer < offer_p(scenario, a)
    lat, lon = f.loc_lat.to_numpy(dtype=float), f.loc_lon.to_numpy(dtype=float)
    if scenario == "S3":
        moved = f.loc_conflict.fillna(False).to_numpy(dtype=bool)
        alt_lat = f.alt_lat.fillna(f.pin_lat).to_numpy(dtype=float)
        alt_lon = f.alt_lon.fillna(f.pin_lon).to_numpy(dtype=float)
        ok = moved & np.isfinite(alt_lat) & np.isfinite(alt_lon)
        lat, lon = np.where(ok, alt_lat, lat), np.where(ok, alt_lon, lon)
    out = pd.DataFrame({
        "unique_id": f.unique_id, "service": f.service, "exists": exists, "offers": offers, "phone_ok": phone_ok,
        "open_now_p": np.where(f.is_24x7.to_numpy(), a.open_now_p_24x7, a.open_now_p_other),
        "accept_p": f.service.map({s: a.accept_p[u] for s, u in URGENCY.items()}).to_numpy(dtype=float),
        "true_lat": lat, "true_lon": lon})
    return out[out.service.isin(services)].reset_index(drop=True)[list(TRUTH_COLUMNS)]


def write_truth(scenario: str, seed: int, services: tuple[str, ...] = SERVICES, a: Assumptions = DEFAULT,
                out_dir: Path = TRUTH_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{scenario}_{seed}.parquet"
    build_truth(scenario, seed, services, a).to_parquet(path, index=False)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Write simulated truth tables (SIMULATED, not field results).")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--services", default=",".join(SERVICES))
    ap.add_argument("--show-rates", action="store_true", help="print the S0 and S2 rate tables")
    args = ap.parse_args()
    if args.show_rates:
        print("S0 rates (SIMULATION INPUT):\n", rate_table(["group"]).round(3).to_string(index=False))
        print("S2 rates (SIMULATION INPUT):\n", rate_table(["grade", "attr_other"]).round(3).to_string(index=False))
    for sc in args.scenarios.split(","):
        for seed in range(args.seeds):
            print("wrote", write_truth(sc, seed, tuple(args.services.split(","))).relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

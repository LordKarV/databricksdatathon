"""Adversarial re-verification of validation/lineage (independent code, not the auditor's).

Every check_<name>() returns dict(name, status pass|warn|fail, metric, threshold, detail, examples).
Read-only on every data layer. Heavy inputs (rebuilds into scratch) are passed by env var:
  SS_REBUILD   a pipelines/source_scoring rebuild out dir (unseeded)      -> check_float_noise_ties
  PACKS_REBUILD a rebuilt app/packs/out dir                              -> check_pack_quote_stability
  CLEAN_REBUILD scratch copy of cleaning/{geo_identity,claims} re-run    -> check_cleaning_rebuild
  LIVE=1       run 3 warehouse SELECTs (row-level fingerprint)           -> check_live_rowprint
Missing inputs give status warn with metric "not run".
Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python -B checks.py
"""
from __future__ import annotations

import collections
import gzip
import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = Path("/Users/karthikvattem/projects/datathon")
V1 = ROOT / "derived/v1"
RAW = ROOT / "data/raw/facilities.parquet"
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
OUT = HERE / "out"


def res(name, status, metric, threshold, detail, examples=None):
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail,
            "examples": list(examples or [])[:5]}


def not_run(name, why):
    return res(name, "warn", "not run", "-", why)


def _load_gz(p: Path):
    return json.loads(gzip.decompress(p.read_bytes()))


# ---------------------------------------------------------------- L1

def check_planner_nan_recount() -> dict:
    """Recount non-finite floats in planner_v1.json.gz by walking the parsed document (a regex on the text
    also matches facility names such as 'Infinity Medical Centre', 8 of the 21 raw token hits)."""
    d = _load_gz(ROOT / "planner/out/planner_v1.json.gz")
    f = d["facilities"]
    hits = collections.Counter()
    ids = []
    for k, col in f.items():
        for i, x in enumerate(col):
            if isinstance(x, float) and not math.isfinite(x):
                hits[k] += 1
                ids.append(f["id"][i])
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id", "district"])
    n_null = int(loc.district.isna().sum())
    st = "fail" if hits else "pass"
    return res("planner_nan_recount", st, f"{sum(hits.values())} non-finite of {len(f['id'])} facilities ({dict(hits)})",
               "0", f"derived/v1 facility_location has {n_null} null districts; every one becomes NaN in the export",
               ids)


def check_itinerary_reachability() -> dict:
    """Does /api/plan's itinerary ever put a NaN-district facility on a route? 49 origins (7x7 grid, +-0.3 deg)
    around each of the 13 facilities x 7 pathway services, through app/itinerary.itinerary()."""
    sys.path.insert(0, str(ROOT / "app"))
    sys.dont_write_bytecode = True
    from facts.engine import Engine  # noqa: PLC0415
    import itinerary as it  # noqa: PLC0415
    from planner import service as svc  # noqa: PLC0415
    eng, st = Engine.load(), svc.store()
    nan = [x for x in st.facilities() if isinstance(x["district"], float) and math.isnan(x["district"])]
    nan_ids = {x["id"] for x in nan}
    steps = (-0.3, -0.15, -0.05, 0, 0.05, 0.15, 0.3)
    n = routed = 0
    crashes = []
    for x in nan:
        for a in steps:
            for b in steps:
                la, lo = round(x["lat"] + a, 2), round(x["lon"] + b, 2)
                for s in sorted(svc.SERVICE_TO_PATHWAY):
                    n += 1
                    out = svc.plan_for_service(s, la, lo)
                    stops = {y["facility_id"] for o in out.get("options", []) for y in o["route"]["stops"]}
                    if stops & nan_ids:
                        routed += 1
                        try:
                            it.itinerary(eng, s, la, lo)
                        except AttributeError as e:
                            crashes.append(f"{s} {la},{lo}: {e}")
    st_ = "fail" if crashes else ("warn" if routed else "pass")
    return res("itinerary_reachability", st_, f"{routed} of {n} plans route through a NaN-district stop; "
               f"{len(crashes)} crashes", "0 crashes",
               "the crash at app/itinerary.py:53 needs such a stop; none was produced near these 13 facilities",
               crashes)


# ---------------------------------------------------------------- L2

def check_pack_quote_stability() -> dict:
    """Per (facility, service) pair, the two shown quotes in canonical packs vs a rebuild (ev.f is delta-coded)."""
    p = os.environ.get("PACKS_REBUILD")
    if not p or not Path(p).is_dir():
        return not_run("pack_quote_stability", "set PACKS_REBUILD to a rebuilt app/packs/out")
    import packquotes  # noqa: PLC0415
    r = packquotes.main(Path(p))
    st = "warn" if r["pairs_quote_changed"] else "pass"
    return res("pack_quote_stability", st,
               f"{r['pairs_quote_changed']} of {r['pairs']} pair rows show different quotes or order; "
               f"{r['pairs_quote_set_changed']} show a different sentence; {len(r['packs_with_change'])}/36 packs",
               "0", f"{r['quotes_shown']} quote slots; scores unchanged in {r['pairs'] - r['pairs_score_changed']} rows",
               [str(e) for e in r["examples"]])


# ---------------------------------------------------------------- L3

def check_float_noise_ties() -> dict:
    """Unseeded source_scoring rebuild vs derived/v1: ulp noise, and whether it breaks or creates exact ties."""
    p = os.environ.get("SS_REBUILD")
    if not p or not Path(p).is_dir():
        return not_run("float_noise_ties", "set SS_REBUILD to an unseeded rebuild out dir")
    import tablediff  # noqa: PLC0415
    r = tablediff.main(Path(p))
    diff = {k: v for k, v in r.items() if isinstance(v, dict) and not v["byte_identical"] and k != "MANIFEST.json"}
    real = [k for k, v in diff.items() if v.get("nonfloat_cols_differ") or v.get("round3_differ")
            or v.get("shape_or_cols_differ") or v.get("max_abs", 0) > 1e-12]
    ranks = {k: {c: n for c, n in v.get("rank_changes", {}).items() if n} for k, v in diff.items()}
    ranks = {k: v for k, v in ranks.items() if v}
    st = "fail" if real else ("warn" if diff else "pass")
    return res("float_noise_ties", st, f"{len(diff)} files differ; {len(real)} beyond 1e-12 or at 3 decimals; "
               f"max {max((v.get('max_abs', 0) for v in diff.values()), default=0):.1e}", "no real diffs",
               f"min-rank changes from tie flips: {ranks}", real)


# ---------------------------------------------------------------- rebuild of the copied cleaning tables (missed)

def check_cleaning_rebuild() -> dict:
    """The 9 copied tables rebuilt from data/raw (geo_identity s1-s5, claims build_claims + grade) in scratch."""
    p = os.environ.get("CLEAN_REBUILD")
    if not p or not Path(p).is_dir():
        return not_run("cleaning_rebuild", "set CLEAN_REBUILD to the scratch copy of cleaning/ after a re-run")
    import cleandiff  # noqa: PLC0415
    import hashlib  # noqa: PLC0415
    from tablediff import frame_diff  # noqa: PLC0415
    out, bad, order_only = {}, [], []
    for t, d in cleandiff.SRC.items():
        a, b = V1 / f"{t}.parquet", Path(p) / d / f"{t}.parquet"
        if not b.exists():
            bad.append(f"{t}: not rebuilt")
            continue
        if hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest():
            out[t] = "identical"
            continue
        x, y = pd.read_parquet(a), pd.read_parquet(b)
        k = list(x.columns)
        if x.astype(str).sort_values(k).reset_index(drop=True).equals(y.astype(str).sort_values(k).reset_index(drop=True)):
            order_only.append(t)
        else:
            bad.append(f"{t}: {frame_diff(x, y)}")
    st = "fail" if bad else ("warn" if order_only else "pass")
    return res("cleaning_rebuild", st, f"{sum(v == 'identical' for v in out.values())}/9 byte-identical; "
               f"{len(order_only)} same rows in another order; {len(bad)} differ or missing", "9/9 identical",
               f"row order only: {order_only} (build_claims.py:54-61 SPEC_SQL GROUP BY has no ORDER BY)", bad)


# ---------------------------------------------------------------- missed: specialties n_raw doubled

def check_specialties_nraw_duplicates() -> dict:
    """SPEC_SQL (cleaning/claims/build_claims.py:54-61) does not drop the 11 byte-identical duplicate rows that
    EXPLODE_SQL drops, so n_raw is doubled for those facilities."""
    f = pd.read_parquet(RAW, columns=["unique_id", "source", "specialties"])
    w = f[f.unique_id.str.match(UUID, na=False) & (f.source == "kie")]
    dup = sorted(w.unique_id[w.unique_id.duplicated()].unique())
    sp = pd.read_parquet(V1 / "specialties.parquet")
    one = w.drop_duplicates("unique_id").set_index("unique_id").specialties
    total = wrong = 0
    ex = []
    for u in dup:
        try:
            items = json.loads(one[u])
        except (TypeError, ValueError):
            continue
        exp = collections.Counter(re.sub("[^a-z]", "", str(x).lower()) for x in items
                                  if x is not None and str(x).strip())
        got = sp[sp.unique_id == u].set_index("spec").n_raw.to_dict()
        for k, v in exp.items():
            total += 1
            if got.get(k) != v:
                wrong += 1
                ex.append(f"{u} {k}: expected {v}, published {got.get(k)}")
    return res("specialties_nraw_duplicates", "warn" if wrong else "pass",
               f"{wrong} of {total} rows for {len(dup)} duplicated ids ({len(sp):,} rows in table)", "0",
               "n_raw is read only by build/measure stats; specialty sets (spec) are right", ex)


# ---------------------------------------------------------------- missed: 30 truncated records

def check_truncated_records() -> dict:
    """Rows with a UUID id but no source: real facilities whose record was cut at a newline in description."""
    f = pd.read_parquet(RAW)
    uu = f.unique_id.astype(str).str.match(UUID)
    t = f[uu & f.source.isna()]
    frag = f[~uu]
    kept = set(f[uu & (f.source == "kie")].unique_id)
    readme = (V1 / "README.md").read_text()
    documented = bool(re.search(r"truncat|\b30 (records|rows)", readme, re.I))
    tail_empty = int(t[["specialties", "capability", "latitude", "source_urls"]].notna().any(axis=1).sum())
    return res("truncated_records", "warn", f"{len(t)} truncated facilities dropped (0 kept under the same id); "
               f"{len(frag)} fragment rows", "documented where the data is used",
               f"PROFILE.json row_integrity records 30/88; derived/v1/README.md mentions it: {documented}; "
               f"truncated rows with any of specialties/capability/lat/source_urls: {tail_empty}; "
               f"ids also present as kie: {int(t.unique_id.isin(kept).sum())}",
               [f"{r.unique_id} {r['name']} ({r.address_city})" for _, r in t.head(5).iterrows()])


# ---------------------------------------------------------------- live, row level

def check_live_rowprint() -> dict:
    """Row-level md5 fingerprint (all columns of a row bound together) live vs local; catches row misalignment
    that per-column order-independent sums cannot."""
    saved = OUT / "rowprint.json"
    if os.environ.get("LIVE") == "1":
        import rowprint  # noqa: PLC0415
        r = {t: {"local": rowprint.local(t), "remote": rowprint.remote(t)} for t in rowprint.TABLES}
    elif saved.exists():
        r = json.loads(saved.read_text())
    else:
        return not_run("live_rowprint", "set LIVE=1 (3 warehouse SELECTs)")
    bad = [t for t, v in r.items() if v["local"] != v["remote"]]
    return res("live_rowprint", "fail" if bad else "pass", f"{3 - len(bad)}/3 tables equal",
               "3/3", "; ".join(f"{t}: rows {v['local']['rows']}, distinct rows {v['local']['distinct']}"
                                for t, v in r.items()), bad)


# ---------------------------------------------------------------- derived/v2 contract for the exports

def check_exports_v2_switch() -> dict:
    """app/facts/build.py:96 and app/packs/build_packs.py:101 switch to derived/v2/facility_service_scores.parquet
    when the file exists. Today the shipped exports say which source they used; this check records it."""
    v2 = ROOT / "derived/v2/facility_service_scores.parquet"
    meta = _load_gz(ROOT / "app/facts/out/facts.json.gz")["meta"]
    band = _load_gz(ROOT / "app/packs/out/delhi.json.gz")["band_note"]
    v2_now = v2.is_file()
    built_from_v2 = meta.get("scores", "").startswith("derived/v2")
    st = "warn" if v2_now != built_from_v2 else "pass"
    return res("exports_v2_switch", st, f"v2 scores file present: {v2_now}; facts built from v2: {built_from_v2}",
               "exports built from the source that exists now", f"facts meta scores: {meta.get('scores')!r}; "
               f"packs band_note: {band!r}. Neither records a hash of the score file it read.")


ALL = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    results = []
    for fn in ALL:
        try:
            r = fn()
        except Exception as e:  # report, do not stop the suite
            r = res(fn.__name__[6:], "fail", "check crashed", "runs", f"{type(e).__name__}: {e}")
        results.append(r)
        print(f"{r['status']:5} {r['name']}: {r['metric']}", flush=True)
    (OUT / "checks.json").write_text(json.dumps(results, indent=1, default=str))

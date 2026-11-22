"""Build one offline referral pack per state from derived/v1 (issue #9).

For every PIN in a state and each of the 7 app services: the 3 nearest candidate facilities (straight
line from the PIN centroid, candidates from all of India so border PINs see the next state), plus the
nearest "likely" candidate when it is not already among them. Each row carries name, one facility
phone, coordinates, a confidence band, the score with its 90% interval, and the two shortest evidence
quotes with their claim ids. The pack also holds the PIN list (centroid, district) for the offline picker.

Layout (pack format v1, JSON, gzip on the wire):
- facilities, evidence rows and PINs are columnar arrays, sorted so coordinates and PINs delta-encode
  to small integers;
- quotes are dictionary-encoded (one table, rows point at it by index);
- the per-PIN top lists are deduplicated: neighbouring PINs usually share the same list, so the index is
  one small integer per (service, PIN) pointing into a table of distinct lists.
The loader in app/static/pack.js decodes it.

Bands: when derived/v2/facility_service_scores.parquet exists (published from #11), band, p, lo and hi come
from it and pairs the model calls unlikely are dropped. Until then a conservative PLACEHOLDER applies:
likely only for pairs verified true by the gold web checks; every other candidate is not_verified, with the
derived/v1 score and interval. Each pack records its band source. Ranking is straight-line distance, not
the decision layer's expected time to treatment.

Run from the repo root:  .venv-app/bin/python app/packs/build_packs.py [--states BIHAR,...]
Writes app/packs/out/<slug>.json.gz (git-ignored: facility data), out/index.json, app/packs/sizes.json
and app/packs/SIZES.md.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DERIVED = ROOT / "derived" / "v1"
sys.path.insert(0, str(ROOT))
from common.eligibility import (  # noqa: E402, RUF100
    eligible_facilities,
    eligible_pairs,
    groups,
    report,
    same_site_groups,
    to_sites,
)

sys.path.insert(0, str(ROOT / "app"))  # facts.redact: the same name redaction as the live answer (#86)
from facts.redact import redact_names  # noqa: E402, RUF100

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

FORMAT_VERSION = 1
BUDGET_GZIP = 150_000
TOP_K = 3
QUOTE_MAX = 160  # characters on a phone card; longer quotes are cut with "..."
FAC_SCALE = 10_000  # facility coordinates in 1e-4 degree (about 11 m)
PIN_SCALE = 1_000  # PIN centroids in 1e-3 degree (about 110 m)
MODEL_SCORES = ROOT / "derived" / "v2" / "facility_service_scores.parquet"

# derived/v1 service names -> app service keys (app/stub_data.py). "icu" has no app tile, so it is dropped.
SERVICE_MAP = {
    "csection": "emergency_csection", "nicu": "nicu", "trauma": "trauma_emergency", "burns": "burn_care",
    "dialysis": "dialysis", "mri": "mri", "cardiac_surgery": "cardiac_surgery",
}
SERVICES = list(SERVICE_MAP.values())
TAXONOMY_TO_APP = {"trauma_care": "trauma_emergency"}  # kb/taxonomy ids that differ from the app keys
V2_BAND = {"LIKELY": "likely", "CALL_FIRST": "not_verified", "NO_SERVICE_TEXT": "not_verified", "UNLIKELY": "unlikely"}


def slug(state: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", state.lower()).strip("_")


def _is_list(x: object) -> bool:
    """A parquet list cell (array or list); False for None or NaN (a record with no trust row)."""
    return isinstance(x, (list, tuple, np.ndarray))


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns facilities, candidate (facility, service) evidence rows, and PINs."""
    loc = pd.read_parquet(DERIVED / "facility_location.parquet",
                          columns=["unique_id", "name", "loc_lat", "loc_lon", "loc_conf"])
    trust = pd.read_parquet(DERIVED / "record_trust.parquet",
                            columns=["unique_id", "display_phones", "trust_flags", "trust_level"])
    fac = loc.merge(trust, on="unique_id", how="left")
    keep, counts = eligible_facilities(fac)  # same rule as the facts engine and the planner (#78)
    report("packs.facilities", counts)
    fac = fac[keep]
    # Facility switchboard only: the record's own first phone, never a chain helpline. A phone the cleaning
    # step marked as a directory number is kept but flagged so the card can say so.
    fac["tel"] = fac.display_phones.map(lambda p: str(p[0]) if _is_list(p) and len(p) else "")
    fac["tel_dir"] = fac.trust_flags.map(lambda f: int(_is_list(f) and "official_phone_is_directory" in list(f)))

    dps = pd.read_parquet(DERIVED / "data_point_scores.parquet",
                          columns=["dp_type", "unique_id", "claim_id", "service", "original_value",
                                   "score", "score_lo", "score_hi", "status", "grade"])
    svc = dps[(dps.dp_type == "service_claim") & dps.service.isin(SERVICE_MAP)].copy()
    keep, counts = eligible_pairs(svc)
    report("packs.pairs", counts)
    svc = svc[keep]
    svc["service"] = svc.service.map(SERVICE_MAP)
    svc = svc[svc.unique_id.isin(fac.unique_id)]
    # Duplicate listings of one site become one facility (#78): the canonical record, with every member's quotes.
    sites, counts = same_site_groups(groups(DERIVED), fac)
    report("packs.same_site_groups", counts)
    text_of = {(u, sv): v for u, sv, v in zip(svc.unique_id, svc.service, svc.original_value, strict=True)}
    svc, counts = to_sites(svc, sites)
    report("packs.duplicates", counts)
    svc = apply_bands(svc, MODEL_SCORES)

    # Sentence text -> claim id, so every quote cites the claim it came from (a merged member's own claim id).
    sent = dps[dps.dp_type == "claim_attribution"][["unique_id", "claim_id", "original_value"]]
    cid = {(u, t): c for u, c, t in sent.itertuples(index=False)}
    svc["quotes"] = [_site_quotes(rep, [(m, text_of[(m, sv)]) for m in members], cid)
                     for rep, sv, members in zip(svc.unique_id, svc.service, svc.members, strict=True)]

    pins = pd.read_parquet(DERIVED / "pin_gazetteer.parquet", columns=["pin", "state", "district", "lat", "lon"])
    pins = pins.dropna(subset=["state", "lat", "lon"])
    pins["district"] = pins.district.fillna("")
    return fac.reset_index(drop=True), svc.reset_index(drop=True), pins.reset_index(drop=True)


def apply_bands(svc: pd.DataFrame, model_path: Path) -> pd.DataFrame:
    """Set likely/score/score_lo/score_hi from the model table if published, else the placeholder.

    The source used is kept in svc.attrs["band_source"] and written into every pack.
    """
    if not model_path.is_file():
        out = svc.assign(likely=(svc.status == "verified_true").astype(int))
        out.attrs["band_source"] = "placeholder: likely only for pairs verified true; model scores not published yet"
        return out
    m = pd.read_parquet(model_path, columns=["unique_id", "service_id", "band", "p", "lo", "hi", "as_of"])
    # service_id is a kb/taxonomy id (derived/v2); also accept derived/v1 names or app keys.
    m["service"] = m.service_id.map(lambda s: TAXONOMY_TO_APP.get(s, SERVICE_MAP.get(s, s)))
    m = m[m.service.isin(SERVICES)].drop_duplicates(["unique_id", "service"])
    m["band"] = m.band.map(lambda b: V2_BAND.get(str(b).upper(), b))  # the same mapping as app/facts/build.py
    unknown = set(m.band) - {"likely", "not_verified", "unlikely"}
    if unknown:
        raise ValueError(f"unknown bands in {model_path}: {sorted(unknown)}")
    out = svc.drop(columns=["score", "score_lo", "score_hi"]).merge(
        m[["unique_id", "service", "band", "p", "lo", "hi"]], on=["unique_id", "service"], how="inner")
    out = out[out.band != "unlikely"].rename(columns={"p": "score", "lo": "score_lo", "hi": "score_hi"})
    out = out.assign(likely=(out.band == "likely").astype(int)).drop(columns=["band"]).reset_index(drop=True)
    out.attrs["band_source"] = f"model: {model_path.name} as of {m.as_of.max()}"
    return out


def _site_quotes(rep: str, members: list[tuple[str, str | None]], cid: dict[tuple[str, str], str]
                 ) -> list[tuple[str, str]]:
    """The two shortest distinct sentences over a site's listings, as (text, claim reference).

    The reference is the claim id's suffix after the facility's uid8 (pack.js adds the prefix back). A sentence from
    a merged duplicate listing keeps its own claim id, stored whole after a leading "=".
    """
    owner: dict[str, str] = {}
    for m, joined in members:
        for t in (joined or "").split(" || "):
            if t.strip():
                owner.setdefault(t.strip(), m)
    out = []
    # (length, text): ties between equal-length sentences break the same way on every build (#78)
    for t in sorted(owner, key=lambda t: (len(t), t))[:2]:
        c = cid.get((owner[t], t), "")
        ref = "" if not c else (c.split(":", 1)[1] if owner[t] == rep else "=" + c)
        shown = redact_names(t)  # never a doctor's name on a phone card (#86)
        out.append((shown if len(shown) <= QUOTE_MAX else shown[:QUOTE_MAX - 3] + "...", ref))
    return out


def _two_shortest(uid: str, joined: str | None, cid: dict[tuple[str, str], str]) -> list[tuple[str, str]]:
    """The two shortest distinct cited sentences of one listing as (text, claim_id suffix after uid8)."""
    return _site_quotes(uid, [(uid, joined)], cid)


def _haversine(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    la1, lo1, la2, lo2 = map(np.radians, (lat1[:, None], lon1[:, None], lat2[None, :], lon2[None, :]))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def top_lists(pins: pd.DataFrame, cand: pd.DataFrame, fac_ll: pd.DataFrame) -> list[tuple[int, ...]]:
    """Per PIN: row ids (into cand) of the TOP_K nearest candidates, plus the nearest likely one."""
    ll = fac_ll.loc[cand.unique_id]
    d = _haversine(pins.lat.to_numpy(), pins.lon.to_numpy(), ll.loc_lat.to_numpy(), ll.loc_lon.to_numpy())
    near = np.argsort(d, axis=1)[:, :TOP_K]
    likely = cand.likely.to_numpy().astype(bool)
    best_likely = np.where(likely.any(), np.argmin(np.where(likely[None, :], d, np.inf), axis=1), -1)
    out = []
    for row, bl in zip(near, best_likely, strict=True):
        ids = [int(i) for i in row]
        if bl >= 0 and bl not in ids:
            ids.append(int(bl))
        out.append(tuple(cand.index[ids]))
    return out


def delta(values: np.ndarray) -> list[int]:
    v = np.asarray(values, dtype=np.int64)
    return np.diff(v, prepend=0).tolist()


def build_state(state: str, pins: pd.DataFrame, fac: pd.DataFrame, svc: pd.DataFrame, built: str) -> dict:
    sp = pins[pins.state == state].sort_values("pin").reset_index(drop=True)
    fac_ll = fac.set_index("unique_id")[["loc_lat", "loc_lon"]]
    per_service: dict[str, list[tuple[int, ...]]] = {}
    for s in SERVICES:
        cand = svc[svc.service == s]
        per_service[s] = top_lists(sp, cand, fac_ll) if len(cand) else [() for _ in range(len(sp))]

    used_ev = sorted({i for lists in per_service.values() for lst in lists for i in lst})
    ev = svc.loc[used_ev]
    # Facilities sorted by latitude so the coordinate deltas stay small.
    f = fac[fac.unique_id.isin(ev.unique_id)].sort_values(["loc_lat", "loc_lon"]).reset_index(drop=True)
    listings = dict(zip(ev.unique_id, ev.listings, strict=False))
    fidx = {u: i for i, u in enumerate(f.unique_id)}
    ev = ev.assign(f=ev.unique_id.map(fidx), s=ev.service.map(SERVICES.index)).sort_values(["f", "s"])
    evidx = {old: new for new, old in enumerate(ev.index)}

    quotes: dict[tuple[str, str], int] = {}
    q1, q2 = [], []
    for qs in ev.quotes:
        ids = [quotes.setdefault(q, len(quotes)) for q in qs] + [-1, -1]
        q1.append(ids[0])
        q2.append(ids[1])

    lists: dict[tuple[int, ...], int] = {}
    index = {}
    for s in SERVICES:
        index[s] = [lists.setdefault(tuple(evidx[i] for i in lst), len(lists)) for lst in per_service[s]]
    districts = sorted(set(sp.district))
    didx = {d: i for i, d in enumerate(districts)}

    return {
        "v": FORMAT_VERSION, "state": state, "built": built, "source": "derived/v1",
        "band_note": svc.attrs.get("band_source", "unknown"),
        "ranking_note": "nearest by straight line from the PIN centroid; not the decision layer's ranking",
        "services": SERVICES,
        "fac": {
            "uid8": [u[:8] for u in f.unique_id], "name": f.name.tolist(), "tel": f.tel.tolist(),
            "tel_dir": f.tel_dir.tolist(), "loc_low": [int(c != "high") for c in f.loc_conf],
            "dup": f.unique_id.map(listings).fillna(1).astype(int).tolist(),  # duplicate listings merged (#78)
            "lat": delta(np.round(f.loc_lat * FAC_SCALE)), "lon": delta(np.round(f.loc_lon * FAC_SCALE)),
        },
        "ev": {
            "f": delta(ev.f), "s": ev.s.tolist(), "likely": ev.likely.tolist(),
            "p": np.round(ev.score * 100).astype(int).tolist(),
            "lo": np.round(ev.score_lo * 100).astype(int).tolist(),
            "hi": np.round(ev.score_hi * 100).astype(int).tolist(),
            "q1": q1, "q2": q2,
        },
        "q": [[t, c] for (t, c) in quotes],
        "lists": [list(k) for k in lists],
        "pins": {
            "pin": delta(sp.pin),
            "lat": delta(np.round(sp.lat * PIN_SCALE)),
            "lon": delta(np.round(sp.lon * PIN_SCALE)),
            "d": [didx[d] for d in sp.district],
        },
        "districts": districts,
        "index": index,
        "scale": {"fac": FAC_SCALE, "pin": PIN_SCALE},
    }


def encode(pack: dict) -> tuple[bytes, bytes]:
    raw = json.dumps(pack, separators=(",", ":"), ensure_ascii=False).encode()
    return raw, gzip.compress(raw, 9, mtime=0)


def self_check(pack: dict, n_pins: int) -> None:
    """Decode a pack the way the loader does and check every PIN gets usable rows."""
    nf = len(pack["fac"]["name"])
    f_ids = np.cumsum(pack["ev"]["f"])
    assert len(pack["pins"]["d"]) == n_pins
    for s in pack["services"]:
        idx = pack["index"][s]
        assert len(idx) == n_pins
        for li in set(idx):
            for e in pack["lists"][li]:
                assert 0 <= f_ids[e] < nf
                assert pack["services"][pack["ev"]["s"][e]] == s, "list row has the wrong service"
                q = pack["ev"]["q1"][e]
                assert q == -1 or pack["q"][q][0], "empty quote"


def write_pin_index(pins: pd.DataFrame) -> None:
    """All-India PIN -> state table for /api/pack/locate, written on every build (also partial ones), so the
    server resolves the right state even when that state's pack is not built."""
    p = pins.sort_values("pin").reset_index(drop=True)
    states = sorted(p.state.unique())
    sidx = {st: i for i, st in enumerate(states)}
    obj = {"v": FORMAT_VERSION, "scale": PIN_SCALE, "states": [[slug(st), st] for st in states],
           "pin": delta(p.pin), "lat": delta(np.round(p.lat * PIN_SCALE)), "lon": delta(np.round(p.lon * PIN_SCALE)),
           "s": [sidx[st] for st in p.state]}
    (OUT / "pin_index.json").write_text(json.dumps(obj, separators=(",", ":")) + "\n")


def write_report(rows: list[dict]) -> None:
    (HERE / "sizes.json").write_text(json.dumps(rows, indent=1) + "\n")
    over = [r for r in rows if r["gzip_bytes"] > BUDGET_GZIP]
    lines = [
        "# Offline state pack sizes",
        "",
        f"Built by `app/packs/build_packs.py` from derived/v1 on {rows[0]['built']}. Budget: {BUDGET_GZIP:,} B gzip",
        f"per state. States over budget: {len(over)} of {len(rows)}. Largest: {rows[0]['state']} "
        f"{rows[0]['gzip_bytes']:,} B. Total for all states: {sum(r['gzip_bytes'] for r in rows):,} B gzip.",
        "",
        "| State | PINs | Facilities | Evidence rows | Quotes | Distinct lists | Raw bytes | Gzip bytes | Budget |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        ok = "ok" if r["gzip_bytes"] <= BUDGET_GZIP else "OVER"
        lines.append(f"| {r['state']} | {r['pins']:,} | {r['facilities']:,} | {r['evidence_rows']:,} | "
                     f"{r['quotes']:,} | {r['lists']:,} | {r['raw_bytes']:,} | {r['gzip_bytes']:,} | {ok} |")
    (HERE / "SIZES.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", help="comma-separated state names (default: all)")
    ap.add_argument("--built", default=json.loads((DERIVED / "MANIFEST.json").read_text()).get("build_date", ""),
                    help="build date written into each pack")
    args = ap.parse_args()
    fac, svc, pins = load()
    states = args.states.split(",") if args.states else sorted(pins.state.unique())
    built = args.built or "unknown"
    OUT.mkdir(exist_ok=True)
    rows, index = [], {}
    for st in states:
        pack = build_state(st, pins, fac, svc, built)
        self_check(pack, int((pins.state == st).sum()))
        raw, gz = encode(pack)
        name = slug(st)
        (OUT / f"{name}.json.gz").write_bytes(gz)
        index[name] = {"state": st, "gzip_bytes": len(gz), "sha256": hashlib.sha256(gz).hexdigest()[:16],
                       "built": built}
        rows.append({"state": st, "slug": name, "built": built, "pins": len(pack["pins"]["d"]),
                     "facilities": len(pack["fac"]["name"]), "evidence_rows": len(pack["ev"]["s"]),
                     "quotes": len(pack["q"]), "lists": len(pack["lists"]),
                     "raw_bytes": len(raw), "gzip_bytes": len(gz)})
    # A partial build keeps the index entries of packs built earlier whose files are still there.
    old_index = OUT / "index.json"
    if args.states and old_index.is_file():
        prev = json.loads(old_index.read_text()).get("packs", {})
        index = {**{k: v for k, v in prev.items() if (OUT / f"{k}.json.gz").is_file()}, **index}
    (OUT / "index.json").write_text(json.dumps({"v": FORMAT_VERSION, "packs": index}, indent=1) + "\n")
    write_pin_index(pins)
    rows.sort(key=lambda r: -r["gzip_bytes"])
    if not args.states:
        write_report(rows)
    for r in rows[:5]:
        print(f"{r['state']}: {r['gzip_bytes']:,} B gzip ({r['pins']} PINs, {r['facilities']} facilities)")
    over = [r["state"] for r in rows if r["gzip_bytes"] > BUDGET_GZIP]
    print(f"{len(rows)} packs, over budget: {over or 'none'}")
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())

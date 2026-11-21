"""Prototype offline referral pack: size of a Bihar pack, and of every other state and all India.

For each location key (Bihar PIN centroid, or a ~10 km grid cell holding a Bihar post office) and
each of the 7 services: the 3 nearest candidate facilities, with name, up to 2 phones, coordinates,
a confidence placeholder and the two shortest own evidence quotes with their claim ids.

Candidate = facility with at least one claim atom for the service that counts as its own and is
not quarantined (model/proto/evidence/claim_atoms.parquet). Confidence placeholder =
p_e * p_s * p_l from the in-progress prototype (model/proto/fusion/pair_scores.parquet).
ponytail: straight-line nearest 3, not the decision layer's ranking; pack size depends on the
number of rows and fields, not on which facilities win, so this is enough to size it.

Two layouts are measured:
  denorm: one object per (key, service) with the facility fields repeated (what the task names);
  norm:   a facility table, an evidence table per (facility, service) and an index key -> 3 ids.
Run: ../../../../.venv-offline/bin/python build_pack.py   Writes out/pack_*.json, out/sizes.json.
"""
import gzip
import json
import math
import re
from pathlib import Path

import duckdb
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = ROOT / "data" / "raw"
ATOMS = ROOT / "model" / "proto" / "evidence" / "claim_atoms.parquet"
SCORES = ROOT / "model" / "proto" / "fusion" / "pair_scores.parquet"
OUT = HERE / "out"
SERVICES = ["dialysis", "emergency_csection", "nicu", "cardiac_surgery", "mri", "burn_care", "trauma_emergency"]
TOP_K = 3
QUOTE_MAX = 240  # characters shown on a phone card; longer quotes are cut with "..."
CELL_DEG = 0.09  # ~10 km of latitude; ~9 km of longitude at 25 N
SNAPSHOT = "2026-11-21"
E164 = re.compile(r"^\+\d{10,13}$")


def load():
    fac = duckdb.sql(f"""
      select unique_id, any_value(name) name, any_value(latitude) lat, any_value(longitude) lon,
             any_value(officialPhone) p0, any_value(phone_numbers) pl
      from '{RAW}/facilities.parquet'
      where latitude between 6 and 38 and longitude between 68 and 98 and name is not null
      group by unique_id""").df()

    def phones(r):
        out = [r.p0] if isinstance(r.p0, str) and E164.match(r.p0) else []
        try:
            pl = json.loads(r.pl or "[]")
            out += [p for p in (pl if isinstance(pl, list) else []) if isinstance(p, str) and E164.match(p)]
        except ValueError:
            pass  # 15 shifted rows hold non-JSON text here; they keep officialPhone only
        return list(dict.fromkeys(out))[:2]

    fac["phones"] = [phones(r) for r in fac.itertuples()]
    atoms = duckdb.sql(f"""
      select unique_id, service, claim_id, text from '{ATOMS}'
      where counts_as_own and not quarantined""").df()
    scores = duckdb.sql(f"select unique_id, service, round(p_e*p_s*p_l, 2) conf from '{SCORES}'").df()
    pins = duckdb.sql(f"""
      select statename st, mode(district) district, pincode pin,
             avg(try_cast(latitude as double)) lat, avg(try_cast(longitude as double)) lon,
             list(distinct officename) offices
      from '{RAW}/india_post_pincode_directory.parquet'
      where try_cast(latitude as double) between 6 and 38 and try_cast(longitude as double) between 68 and 98
      group by statename, pincode""").df()
    return fac, atoms, scores, pins


def evidence_table(fac, atoms, scores):
    """(uid, service) -> [conf, [quote, claim_id], [quote, claim_id]] for every candidate pair."""
    conf = {(r.unique_id, r.service): float(r.conf) for r in scores.itertuples()}
    atoms = atoms.assign(n=atoms.text.str.len()).sort_values("n")
    ev = {}
    for (uid, svc), g in atoms.groupby(["unique_id", "service"], sort=False):
        qs = []
        for r in g.itertuples():  # shortest first; skip exact duplicate texts echoed across fields
            t = r.text if len(r.text) <= QUOTE_MAX else r.text[:QUOTE_MAX - 3] + "..."
            if t not in [q[0] for q in qs]:
                qs.append([t, r.claim_id])
            if len(qs) == 2:
                break
        ev[(uid, svc)] = [conf.get((uid, svc)), *qs]
    keep = set(fac.unique_id)
    return {k: v for k, v in ev.items() if k[0] in keep}


def nearest(points, cand_lat, cand_lon, k=TOP_K):
    """Indices of the k nearest candidates per point by haversine, and their distances in km."""
    la1, lo1 = np.radians(points[:, :1]), np.radians(points[:, 1:])
    la2, lo2 = np.radians(cand_lat)[None, :], np.radians(cand_lon)[None, :]
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    d = 2 * 6371 * np.arcsin(np.sqrt(a))
    idx = np.argsort(d, axis=1)[:, :k]
    return idx, np.take_along_axis(d, idx, axis=1)


def build(keys, fac, ev):
    """keys: list of (key, lat, lon). Returns denorm and norm packs as dicts."""
    pts = np.array([[la, lo] for _, la, lo in keys])
    by_uid = fac.set_index("unique_id")
    denorm, index, used = {}, {}, {}
    for svc in SERVICES:
        cand = [u for u in by_uid.index if (u, svc) in ev]
        cl, co = by_uid.loc[cand, "lat"].to_numpy(), by_uid.loc[cand, "lon"].to_numpy()
        idx, dist = nearest(pts, cl, co)
        for (key, _, _), ii, dd in zip(keys, idx, dist):
            rows, ids = [], []
            for i, km in zip(ii, dd):
                u = cand[i]
                f = by_uid.loc[u]
                c, *qs = ev[(u, svc)]
                rows.append({"name": f["name"], "phones": f["phones"], "lat": round(float(f.lat), 4),
                             "lon": round(float(f.lon), 4), "km": round(float(km), 1), "conf": c, "quotes": qs})
                sid = used.setdefault(u, len(used))
                ids.append(sid)
            denorm.setdefault(key, {})[svc] = rows
            index.setdefault(key, {})[svc] = ids
    inv = {sid: u for u, sid in used.items()}
    facilities = [[by_uid.loc[inv[s], "name"], by_uid.loc[inv[s], "phones"],
                   round(float(by_uid.loc[inv[s], "lat"]), 4), round(float(by_uid.loc[inv[s], "lon"]), 4),
                   inv[s][:8]] for s in range(len(inv))]
    evidence = {f"{used[u]}|{svc}": ev[(u, svc)] for u in used for svc in SERVICES if (u, svc) in ev}
    norm = {"snapshot": SNAPSHOT, "services": SERVICES,
            "fac_cols": ["name", "phones", "lat", "lon", "uid8"], "facilities": facilities,
            "evidence_cols": ["conf", "quote1", "quote2"], "evidence": evidence, "index": index}
    return {"snapshot": SNAPSHOT, "packs": denorm}, norm


def size(obj):
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()
    return raw, {"raw_bytes": len(raw), "gzip9_bytes": len(gzip.compress(raw, 9))}


def pin_picker(pins_state):
    """Offline place picker: PIN -> [lat, lon, district, post office names]."""
    return {str(r.pin): [round(r.lat, 3), round(r.lon, 3), r.district, sorted(r.offices)]
            for r in pins_state.itertuples()}


def grid_keys(p):
    cells = {}
    for r in p.itertuples():
        key = f"{math.floor(r.lat / CELL_DEG)}_{math.floor(r.lon / CELL_DEG)}"
        cells.setdefault(key, ((math.floor(r.lat / CELL_DEG) + .5) * CELL_DEG, (math.floor(r.lon / CELL_DEG) + .5) * CELL_DEG))
    return [(k, la, lo) for k, (la, lo) in cells.items()]


def main():
    OUT.mkdir(exist_ok=True)
    fac, atoms, scores, pins = load()
    ev = evidence_table(fac, atoms, scores)
    res = {"facilities_geocoded": len(fac), "candidate_pairs": len(ev),
           "candidates_per_service": {s: sum(1 for k in ev if k[1] == s) for s in SERVICES}}

    bihar = pins[pins.st == "BIHAR"]
    for name, keys in [("bihar_pin", [(str(r.pin), r.lat, r.lon) for r in bihar.itertuples()]),
                       ("bihar_grid10km", grid_keys(bihar))]:
        d, n = build(keys, fac, ev)
        rd, sd = size(d)
        rn, sn = size(n)
        (OUT / f"pack_{name}_denorm.json").write_bytes(rd)
        (OUT / f"pack_{name}_norm.json").write_bytes(rn)
        res[name] = {"keys": len(keys), "distinct_facilities": len(n["facilities"]),
                     "evidence_rows": len(n["evidence"]), "denorm": sd, "norm": sn}
    rp, sp = size(pin_picker(bihar))
    (OUT / "picker_bihar.json").write_bytes(rp)
    res["bihar_pin_picker"] = {"pins": len(bihar), "post_offices": int(bihar.offices.map(len).sum()), **sp}

    # Bihar per district (the pack a field worker would carry for one district)
    per_d = []
    for dist, g in bihar.groupby("district"):
        _, n = build([(str(r.pin), r.lat, r.lon) for r in g.itertuples()], fac, ev)
        _, s = size({"pack": n, "picker": pin_picker(g)})
        per_d.append({"district": dist, "pins": len(g), **s})
    res["bihar_district_packs_norm_plus_picker"] = sorted(per_d, key=lambda x: -x["gzip9_bytes"])

    # every state and all India, normalized layout, PIN keys, picker included
    states, all_keys = [], []
    for st, g in pins.groupby("st"):
        keys = [(str(r.pin), r.lat, r.lon) for r in g.itertuples()]
        all_keys += keys
        _, n = build(keys, fac, ev)
        _, s = size({"pack": n, "picker": pin_picker(g)})
        states.append({"state": st, "pins": len(g), "distinct_facilities": len(n["facilities"]), **s})
    res["states_norm_plus_picker"] = sorted(states, key=lambda x: -x["gzip9_bytes"])
    d, n = build(all_keys, fac, ev)
    _, sn = size({"pack": n, "picker": pin_picker(pins)})
    _, sd = size(d)
    res["all_india_pin"] = {"pins": len(all_keys), "distinct_facilities": len(n["facilities"]),
                            "norm_plus_picker": sn, "denorm_without_picker": sd}
    (OUT / "sizes.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))

    # self-check: every Bihar PIN has 3 facilities for every service, each with a quote and a claim id
    b = json.loads((OUT / "pack_bihar_pin_denorm.json").read_text())["packs"]
    assert len(b) == len(bihar)
    assert all(len(b[k][s]) == 3 and b[k][s][0]["quotes"][0][1] for k in b for s in SERVICES)
    assert all(v[1] for v in n["evidence"].values()), "every evidence row cites at least one quote"
    print(json.dumps({k: v for k, v in res.items() if not isinstance(v, list)}, indent=1))
    print("top states:", res["states_norm_plus_picker"][:5])
    print("SELF-CHECK PASSED")


if __name__ == "__main__":
    main()

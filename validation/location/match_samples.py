"""Fixed-seed accepted / rejected match samples per outside source, printed for hand judgment.
Accepted = the source's own accepted tier. Rejected = best candidate the matcher refused, restricted to
plausible ones (name score >= 70) so that a judged 'same facility' is a real miss, not a trivially different pair."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import EXT, ROOT, SEED, loc, raw  # noqa: E402

N_ACC, N_REJ = 20, 10


def _take(df, n, salt):
    return df.sample(min(n, len(df)), random_state=SEED + salt) if len(df) else df


def opendata(source):
    m = pd.read_parquet(ROOT / "kb/opendata/vf_opendata_match.parquet")
    m = m[m.source == source]
    acc = m[m.tier.isin(["high", "medium"])]
    rej = m[m.tier.isna() & (m.score >= 70)]
    salt = 10 if source == "osm" else 20
    return _take(acc, N_ACC, salt), _take(rej, N_REJ, salt + 1), len(acc), len(rej)


def hot():
    h = pd.read_parquet(EXT / "hotosm_ind_health_facilities/vf_osm_matches.parquet")
    h = h[h.unique_id.isin(loc().unique_id)]  # same 9,959 universe
    acc = h[h.tier == "strong"]
    rej = h[h.tier.isna() & (h.score >= 70)]
    return _take(acc, N_ACC, 30), _take(rej, N_REJ, 31), len(acc), len(rej)


def nabh():
    m = pd.read_parquet(EXT / "nabh_accredited/nabh_vf_match.parquet")
    return _take(m[m.accept], N_ACC, 40), m.iloc[0:0], int(m.accept.sum()), 0


def trauma():
    t = pd.read_csv(EXT / "mohfw_trauma_196/tcf_vf_candidates.csv")
    a = pd.read_csv(EXT / "mohfw_trauma_196/tcf_vf_matches.csv")
    acc = t[t.sno.isin(a.sno)]
    rej = t[~t.sno.isin(a.sno) & t.vf_id.notna() & (t.score >= 70)]
    return _take(acc, N_ACC, 50), _take(rej, N_REJ, 51), len(acc), len(rej)


def simple(path, salt):
    m = pd.read_parquet(EXT / path)
    return _take(m, N_ACC, salt), m.iloc[0:0], len(m), 0


GENERIC = set("""hospital hospitals blood bank centre center bsu storage unit medical college and research institute
institutes pvt ltd private limited govt government district sub divisional the of multispeciality multi speciality
specialty super clinic health care unit m s dr pvt. ltd. trust memorial general nursing home sciences science
mc dh sdh chc area taluk taluka civil maternity hospital""".split())


def core(s):
    from common import norm
    return " ".join(w for w in norm(s).split() if w not in GENERIC)


def _best_vf(names, lats, lons, states, max_km=10.0):
    """Best VF candidate (by core-name token_set_ratio, ties by distance) within max_km of the list point,
    restricted to the same normalised state when no coordinate. Returns DataFrame(i, unique_id, vf_name, score, km)."""
    from rapidfuzz import fuzz
    from common import hav_km, nstate
    L = loc()
    vcore = L.name.map(core).values
    vst = L.state_final.map(nstate).values
    out = []
    for i, (nm, la, lo, st) in enumerate(zip(names, lats, lons, states)):
        c = core(nm)
        if len(c) < 3:
            continue
        if np.isfinite(la):
            d = hav_km(la, lo, L.loc_lat.values, L.loc_lon.values)
            idx = np.where(d <= max_km)[0]
        else:
            d = np.full(len(L), np.nan)
            idx = np.where(vst == nstate(st))[0]
        if not len(idx):
            continue
        sc = np.array([fuzz.token_set_ratio(c, vcore[j]) if vcore[j] else 0 for j in idx])
        k = idx[np.lexsort((np.nan_to_num(d[idx], nan=0), -sc))[0]]
        out.append((i, L.unique_id.values[k], L.name.values[k], L.address_city.values[k], float(sc.max()), float(d[k])))
    return pd.DataFrame(out, columns=["i", "unique_id", "vf_name", "vf_city", "score", "km"])


def rejected_from_list(lst, name_col, lat_col, lon_col, state_col, extra_cols, salt, min_score=85):
    b = _best_vf(lst[name_col].values, lst[lat_col].astype(float).values if lat_col else np.full(len(lst), np.nan),
                 lst[lon_col].astype(float).values if lon_col else np.full(len(lst), np.nan), lst[state_col].values)
    b = b.join(lst.reset_index(drop=True)[[name_col] + extra_cols], on="i")
    pool = b[b.score >= min_score]
    return _take(pool, N_REJ, salt), len(pool)


def erk_rejected():
    c = pd.read_parquet(EXT / "eraktkosh_blood_centres/erk_centres.parquet")
    m = pd.read_parquet(EXT / "eraktkosh_blood_centres/erk_vf_matches.parquet")
    u = c[~c.hospital_code.isin(m.hospital_code) & c.latitude.notna()]
    u = u[~((u.latitude.round(4) == 22.3511) & (u.longitude.round(4) == 78.6677))]  # failed geocodes at India centroid
    return rejected_from_list(u, "name", "latitude", "longitude", "district", ["address", "district"], 61)


def nabh_rejected():
    h = pd.read_parquet(EXT / "nabh_accredited/nabh_hco.parquet").reset_index().rename(columns={"index": "nabh_id"})
    m = pd.read_parquet(EXT / "nabh_accredited/nabh_vf_match.parquet")
    u = h[~h.nabh_id.isin(m.nabh_id) & h.lat.notna()]
    return rejected_from_list(u, "name", "lat", "lng", "addr_state", ["address", "acc_no"], 41)


def laqshya_rejected():
    f = pd.read_parquet(EXT / "laqshya_master/laqshya_facilities.parquet")
    m = pd.read_parquet(EXT / "laqshya_master/laqshya_vf_matches.parquet")
    u = f[~f.lq_id.isin(m.lq_id)].assign(full=lambda d: d.name + " " + d.district)
    return rejected_from_list(u, "full", None, None, "state", ["district", "ftype"], 71)


def nmc_rejected():
    c = pd.read_parquet(EXT / "nmc_colleges/nmc_colleges.parquet")
    m = pd.read_parquet(EXT / "nmc_colleges/nmc_vf_matches.parquet")
    u = c[~c.college_id.isin(m.college_id)]
    return rejected_from_list(u, "college_name", None, None, "state_name", ["address", "pin"], 81)

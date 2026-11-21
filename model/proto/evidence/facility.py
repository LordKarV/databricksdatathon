"""Facility-level witnesses: existence (spec 4.5), location votes for p1 (4.6) and leakage groups (4.7).

Location votes are +1 when a witness lies within VOTE_KM of p1 (district witnesses: same district as p1),
-1 when it points elsewhere, 0 when absent. The same votes are also computed against p2 so the card can say
which witnesses back the alternative point.
"""
import base64
import re
import sys

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from common import GEOI, INPUTS, ROOT, hav_km, jlist, norm

sys.path.insert(0, str(ROOT / "audit/geo"))
from geo_common import CITY_ALIAS, nearest  # noqa: E402

VOTE_KM = 25.0
MAX_OFFICE_SPREAD = 30.0   # same refusal rule as cleaning/geo_identity/places.city_point
GOOD_SRC = ["pin_median", "facility_consensus", "district_median"]
WITNESSES = ["coords", "pin", "city", "name_place", "state", "text_pin", "map_link"]
FAC_WORDS = r"(hospitals?|clinics?|cent(re|er)s?|nursing home|polyclinic|dispensary|institute|medicare|healthcare|" \
            r"health care|labs?|laboratory|diagnostics?|maternity home|infirmary|sanatorium)"
GENERIC = set("""the and of hospital hospitals clinic clinics centre center nursing home medical multi multispeciality
multispecialty speciality specialty super care health healthcare dental eye children child maternity diagnostic
diagnostics research institute foundation trust pvt ltd private limited sciences memorial general city life new
heart kidney cancer women womens mother hosp dr shri sri sree and co unit branch main road nagar colony""".split())
DIRECTORY_HOST = {"business.site", "practo.com", "justdial.com", "lybrate.com", "facebook.com", "google.com",
                  "sites.google.com", "wixsite.com", "blogspot.com", "instagram.com"}
PIN_RX = re.compile(r"(?<!\d)([1-8]\d{2}\s?\d{3})(?!\d)")


def phone10(s) -> str | None:
    d = re.sub(r"\D", "", str(s or ""))
    return d[-10:] if len(d) >= 10 else None


def domain(s) -> str | None:
    if not isinstance(s, str):
        return None
    s = s.strip().lower()
    if not s or s in ("null", "nan", "none"):
        return None
    s = re.sub(r"^[a-z]+://", "", s).split("/")[0]
    return s[4:] if s.startswith("www.") else s


class Places:
    """District and office layers of cleaning/geo_identity/place_gazetteer.parquet keyed by (state, name)."""

    def __init__(self):
        pg = pd.read_parquet(INPUTS["place_gazetteer"])
        self.by_key = {(k, st, n): r for k, st, n, r in zip(pg.kind, pg.state, pg.name, pg.itertuples(index=False))}
        d = pg[pg.kind == "district"]
        self.district_any = d.groupby("name").filter(lambda g: len(g) == 1).set_index("name")

    def lookup(self, name: str, state: str | None, any_state: bool = False):
        """(lat, lon, kind, place_name, state) or None. Same refusal rules as places.city_point; with any_state,
        a district name that is unique across India is accepted (a place in another state is a strong dissent)."""
        n = CITY_ALIAS.get(name, name)
        if not n or len(n) < 4:
            return None
        if isinstance(state, str):
            for kind in ("district", "office"):
                for nn in {n, n.replace(" district", "")}:
                    r = self.by_key.get((kind, state, nn))
                    if r is not None and not (kind == "office" and r.spread_km > MAX_OFFICE_SPREAD):
                        return float(r.lat), float(r.lon), kind, nn, state
        if any_state and n in self.district_any.index:
            r = self.district_any.loc[n]
            return float(r.lat), float(r.lon), "district", n, r.state
        return None


def name_place_candidates(name: str) -> list:
    """Place phrases in a facility name, most specific first: the segment after the last comma / dash /
    bracket, and the words after the last facility-type word ('Wockhardt Hospital Nagpur' -> 'nagpur')."""
    raw = str(name or "")
    cands = []
    parts = re.split(r",| - | \| |\(|\)", raw)
    if len(parts) > 1:
        cands.append(norm(parts[-1]) or norm(parts[-2]))
    m = list(re.finditer(rf"\b{FAC_WORDS}\b", raw, re.I))
    if m:
        cands.append(norm(raw[m[-1].end():]))
    out = []
    for c in cands:
        w = [x for x in c.split() if x not in GENERIC and not x.isdigit()]
        for k in (len(w), 2, 1):
            if 0 < k <= len(w):
                out.append(" ".join(w[-k:]))
    return list(dict.fromkeys(out))


ZD = re.compile(r"mappls\.com/place-([^@\s\"]+)@zdata=([A-Za-z0-9+/]+=*)")


def mappls_points(f: pd.DataFrame) -> dict:
    """Name-matched map-link points. Same rule as cleaning/geo_identity/s2_facility_location.mappls_points
    (copied: importing that module would shadow this folder's common.py): the link slug's leading words
    must match the facility name with token_set_ratio >= 85."""
    out = {}
    for u, nm, urls in zip(f.unique_id, f.name, f.source_urls):
        for slug, z in ZD.findall(str(urls)):
            try:
                t = base64.b64decode(z + "=" * (-len(z) % 4)).decode("ascii", "ignore")
            except ValueError:
                continue
            x = re.match(r"(-?\d+\.\d+)\+(-?\d+\.\d+)", t)
            words = slug.split("-")[0].replace("+", " ")
            if x and fuzz.token_set_ratio(norm(words), norm(nm)) >= 85:
                out.setdefault(u, []).append((float(x.group(1)), float(x.group(2))))
    return out


def text_pins(claims: pd.DataFrame, gz: pd.DataFrame) -> pd.DataFrame:
    """PINs written inside claim sentences (only values present in the gazetteer)."""
    known = set(gz.pin.astype(int))
    rows = []
    for u, t in zip(claims.unique_id, claims.text):
        for m in PIN_RX.findall(t):
            p = int(m.replace(" ", ""))
            if p in known:
                rows.append((u, p))
    return pd.DataFrame(rows, columns=["unique_id", "pin"]).drop_duplicates()


def _vote(d_km, ok, same_district=None):
    v = np.where(d_km <= VOTE_KM, 1, -1)
    if same_district is not None:
        v = np.where(same_district, 1, v)
    return np.where(ok, v, 0).astype(int)


def location_votes(fl: pd.DataFrame, fg: pd.DataFrame, rs: pd.DataFrame, claims: pd.DataFrame) -> pd.DataFrame:
    gz = pd.read_parquet(INPUTS["pin_gazetteer"])
    good = gz[gz.src.isin(GOOD_SRC)].dropna(subset=["lat"]).reset_index(drop=True)
    places = Places()
    f = fl.merge(fg[["unique_id", "state_n", "coord_dup_names"]], on="unique_id", how="left")
    out = pd.DataFrame({"unique_id": f.unique_id})
    pts = {}
    # witness points
    ok = f.raw_lat.between(6, 38) & f.raw_lon.between(68, 98)
    pts["coords"] = (f.raw_lat.where(ok), f.raw_lon.where(ok), None)
    pinpt = f[["pin"]].merge(gz[["pin", "lat", "lon"]].astype({"pin": float}), on="pin", how="left")
    pts["pin"] = (pinpt.lat, pinpt.lon, None)
    city = [places.lookup(norm(c), s) for c, s in zip(f.address_city, f.state_final)]
    pts["city"] = (pd.Series([c[0] if c else np.nan for c in city]), pd.Series([c[1] if c else np.nan for c in city]),
                   pd.Series([c[3] if c and c[2] == "district" else None for c in city]))
    npl = []
    for nm, s in zip(f.name, f.state_final):
        hit = None
        for c in name_place_candidates(nm):
            hit = places.lookup(c, s) or places.lookup(c, None, any_state=True)
            if hit:
                break
        npl.append(hit)
    pts["name_place"] = (pd.Series([h[0] if h else np.nan for h in npl]), pd.Series([h[1] if h else np.nan for h in npl]),
                         pd.Series([h[3] if h and h[2] == "district" else None for h in npl]))
    out["name_place_text"] = [f"{h[3]} ({h[2]}, {h[4]})" if h else None for h in npl]
    mp = mappls_points(rs)
    pts["map_link"] = (f.unique_id.map(lambda u: mp[u][0][0] if u in mp else np.nan),
                       f.unique_id.map(lambda u: mp[u][0][1] if u in mp else np.nan), None)
    tp = text_pins(claims, gz).merge(gz[["pin", "lat", "lon"]], on="pin")
    out["text_pins"] = f.unique_id.map(tp.groupby("unique_id").pin.agg(lambda x: "|".join(map(str, x))))

    # p1 / p2 and their nearest-PIN state and district
    for p, (la, lo) in {"p1": ("loc_lat", "loc_lon"), "p2": ("alt_lat", "alt_lon")}.items():
        lat, lon = f[la].to_numpy(float), f[lo].to_numpy(float)
        has = np.isfinite(lat)
        idx, _ = nearest(np.nan_to_num(lat), np.nan_to_num(lon), good.lat.to_numpy(), good.lon.to_numpy())
        out[f"{p}_lat"], out[f"{p}_lon"] = np.where(has, lat, np.nan), np.where(has, lon, np.nan)
        out[f"{p}_state"] = np.where(has, good.state.to_numpy()[idx], None)
        out[f"{p}_district"] = np.where(has, good.district.to_numpy()[idx], None)
        for w in ["coords", "pin", "city", "name_place", "map_link"]:
            wl, wo, wdist = pts[w]
            d = hav_km(lat, lon, wl.to_numpy(float), wo.to_numpy(float))
            okw = np.isfinite(d) & has
            same = None if wdist is None else np.array([isinstance(a, str) and isinstance(b, str) and norm(a) == norm(b)
                                                         for a, b in zip(wdist, out[f"{p}_district"])])
            out[f"vote_{w}" + ("" if p == "p1" else "_p2")] = _vote(d, okw, same)
            if p == "p1":
                out[f"d_{w}_km"] = np.round(np.where(okw, d, np.nan), 1)
        st_ok = f.state_n.notna() & has
        out[f"vote_state" + ("" if p == "p1" else "_p2")] = np.where(st_ok, np.where(f.state_n == out[f"{p}_state"], 1, -1), 0)
        tpd = tp.merge(out[["unique_id", f"{p}_lat", f"{p}_lon"]], on="unique_id")
        tpd["v"] = np.where(hav_km(tpd[f"{p}_lat"], tpd[f"{p}_lon"], tpd.lat, tpd.lon) <= VOTE_KM, 1, -1)
        out[f"vote_text_pin" + ("" if p == "p1" else "_p2")] = f.unique_id.map(tpd.groupby("unique_id").v.sum()).fillna(0).clip(-1, 1).astype(int)
    out["n_votes_for"] = sum((out[f"vote_{w}"] == 1).astype(int) for w in WITNESSES)
    out["n_votes_against"] = sum((out[f"vote_{w}"] == -1).astype(int) for w in WITNESSES)
    flags = f.loc_flags.map(lambda x: set(x) if x is not None else set())
    for fl_ in ["copied_geocode", "coords_look_wrong", "pin_looks_wrong"]:
        out[fl_] = flags.map(lambda s: fl_ in s)
    out["loc_flags"] = f.loc_flags.map(lambda x: "|".join(x) if x is not None else "")
    out["p1_src"], out["loc_radius_km"], out["loc_conf"] = f.loc_src, f.loc_radius, f.loc_conf
    out["p2_src"] = np.where(f.alt_lat.notna(), "alt_point", None)
    out["loc_note"] = f.loc_note
    out["coord_dup_names"] = f.coord_dup_names
    return out


def existence(rs: pd.DataFrame, fg: pd.DataFrame) -> pd.DataFrame:
    es = pd.read_csv(INPUTS["existence_signals"], usecols=["unique_id", "web", "phone", "dom"])
    dg = pd.read_csv(INPUTS["dup_groups"], usecols=["unique_id", "grp_strong"])
    sp = pd.read_csv(INPUTS["shared_phones"], dtype={"phone": str})
    nc = dict(zip(sp.phone.map(phone10), sp.n_city))
    e = rs[["unique_id", "name", "facilityTypeId", "officialPhone", "officialWebsite", "source_ids",
            "recency_of_page_update"]].merge(es, on="unique_id", how="left").merge(dg, on="unique_id", how="left")
    e = e.merge(fg[["unique_id", "coord_dup_names"]], on="unique_id", how="left")
    out = pd.DataFrame({"unique_id": e.unique_id})
    out["website"] = e.dom
    out["website_class"] = e.web.fillna("none")
    out["phone"] = e.officialPhone.map(phone10)
    out["phone_n_cities"] = out.phone.map(nc).fillna(1).astype(int)
    pc = e.phone.fillna("none").replace({"shared_3plus_cities": "shared_3plus"})
    out["phone_class"] = np.where(out.phone_n_cities >= 3, "shared_3plus", pc)
    out["n_source_ids"] = e.source_ids.map(lambda s: len(set(jlist(s))))
    out["source_ids_bin"] = pd.cut(out.n_source_ids, [-1, 1, 3, 10**6], labels=["1", "2-3", "4+"]).astype(str)
    out["page_recency_present"] = e.recency_of_page_update.map(lambda s: isinstance(s, str) and s not in ("", "null"))
    out["coord_shared_3plus_names"] = e.coord_dup_names.fillna(0) >= 3
    out["non_facility_type"] = e.facilityTypeId.isin(["pharmacy", "farmacy"]) | \
        e.name.str.contains(r"pharmac|farmac|chemist|druggist|medical store", case=False, na=False)
    out["strong_dup_member"] = e.grp_strong.notna()
    out["strong_dup_group"] = e.grp_strong
    out["osm_nin_match"] = None   # abstains until an external list exists (spec 4.5)
    return out


class UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def leakage_groups(rs: pd.DataFrame, ex: pd.DataFrame) -> pd.DataFrame:
    """Union-find over strong duplicate groups, official domain, official phone, chain and shared
    source_content_id. Phone and domain keys seen in 3+ cities (directory numbers, hosting sites) are skipped."""
    dg = pd.read_csv(INPUTS["dup_groups"], usecols=["unique_id", "grp_strong"])
    cm = pd.read_csv(INPUTS["chain_membership"], usecols=["unique_id", "chain"])
    sd = pd.read_csv(INPUTS["shared_domains"])
    bad_dom = set(sd[sd.n_city >= 3].domain) | DIRECTORY_HOST
    keys = pd.DataFrame({"unique_id": rs.unique_id})
    keys["k_strong"] = keys.unique_id.map(dict(zip(dg.unique_id, dg.grp_strong))).map(lambda x: f"strong:{int(x)}" if pd.notna(x) else None)
    dom = [domain(x) for x in rs.officialWebsite.astype(object)]
    keys["k_domain"] = [f"dom:{d}" if isinstance(d, str) and d not in bad_dom else None for d in dom]
    ph = ex.set_index("unique_id").reindex(rs.unique_id)
    keys["k_phone"] = [f"tel:{p}" if isinstance(p, str) and n < 3 else None for p, n in zip(ph.phone, ph.phone_n_cities)]
    keys["k_chain"] = keys.unique_id.map(dict(zip(cm.unique_id, cm.chain))).map(lambda c: f"chain:{c}" if isinstance(c, str) else None)
    sc = rs.source_content_id.where(rs.source_content_id.duplicated(keep=False))
    keys["k_content"] = sc.map(lambda c: f"content:{c}" if isinstance(c, str) else None).to_numpy()
    uf = UF(keys.unique_id)
    first = {}
    for col in ["k_strong", "k_domain", "k_phone", "k_chain", "k_content"]:
        for u, k in zip(keys.unique_id, keys[col]):
            if isinstance(k, str):
                if k in first:
                    uf.union(first[k], u)
                else:
                    first[k] = u
    root = keys.unique_id.map(uf.find)
    out = pd.DataFrame({"unique_id": keys.unique_id, "leakage_group_id": "lg:" + root.str[:8]})
    out["group_size"] = out.groupby("leakage_group_id").unique_id.transform("size")
    out["leakage_keys"] = keys[["k_strong", "k_domain", "k_phone", "k_chain", "k_content"]].apply(
        lambda r: "|".join(x for x in r if isinstance(x, str)), axis=1).to_numpy()
    return out

"""Join test: LGD PIN mapping vs facilities, India Post and NFHS-5.

Usage: python -I join_test.py <lgd_dir> <raw_dir> <out_dir>

Writes to out_dir:
  pin_district.parquet      PIN -> LGD district candidates (rural + urban)
  facility_lgd.parquet      one row per facility with LGD district and checks
  lgd_nfhs_map.csv          LGD district -> NFHS-5 district (fuzzy, within state)
  handcheck_facilities.csv  20 random matched facilities for manual review
  join_stats.json           all reported rates with denominators
"""
import json
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd
from rapidfuzz import fuzz, process

CITY_AGREE = 85   # token_set_ratio threshold for city vs LGD names
NFHS_AGREE = 80   # fuzz.ratio threshold; WRatio matched Prayagraj to Agra
SEED = 7

ULB_PREFIX = re.compile(
    r"\b(municipal corporation|municipal council|municipal committee|municipality|"
    r"nagar panchayat|nagar palika parishad|nagar parishad|nagar nigam|town panchayat|"
    r"cantonment board|notified area committee|census town|city|of|the)\b")
STATE_ALIAS = {"orissa": "odisha", "maharastra": "maharashtra", "tamilnadu": "tamil nadu", "up": "uttar pradesh",
               "pondicherry": "puducherry", "uttaranchal": "uttarakhand",
               "punjab region": "punjab", "nct of delhi": "delhi",
               "jammu kashmir": "jammu and kashmir",
               "dadra and nagar haveli": "the dadra and nagar haveli and daman and diu",
               "daman and diu": "the dadra and nagar haveli and daman and diu",
               "andaman nicobar islands": "andaman and nicobar islands"}


def norm(s: object) -> str:
    s = str(s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_state(s: object) -> str:
    n = norm(s)
    return STATE_ALIAS.get(n, n)


def norm_ulb(s: object) -> str:
    return re.sub(r"\s+", " ", ULB_PREFIX.sub(" ", norm(s))).strip()


def pin_candidates(con: duckdb.DuckDBPyConnection, lgd: Path) -> pd.DataFrame:
    """Every (PIN, district) pair LGD knows, with the evidence behind it."""
    return con.execute(f"""
        with rural as (
          select pincode, district_code, any_value(district_name) district_name,
                 any_value(state_name) state_name, count(*) n_villages, 0 n_ulbs,
                 list(distinct subdistrict_name) subdistricts, list(distinct village_name) places
          from '{lgd}/pincode_villages.parquet' group by pincode, district_code),
        ulb_d as (select distinct local_body_code, district_code, district_name, state_name
                  from '{lgd}/statewise_ulbs_coverage.parquet'),
        urban as (
          select p.pincode, d.district_code, any_value(d.district_name) district_name,
                 any_value(d.state_name) state_name, 0 n_villages,
                 count(distinct p.local_body_code) n_ulbs, [] subdistricts,
                 list(distinct p.local_body_name) places
          from '{lgd}/pincode_urban.parquet' p join ulb_d d using (local_body_code)
          group by p.pincode, d.district_code)
        select pincode, district_code, any_value(district_name) district_name,
               any_value(state_name) state_name, sum(n_villages)::int n_villages,
               sum(n_ulbs)::int n_ulbs, flatten(list(subdistricts)) subdistricts,
               flatten(list(places)) places
        from (select * from rural union all select * from urban)
        group by pincode, district_code""").fetchdf()


def pick_primary(c: pd.DataFrame) -> pd.DataFrame:
    # ponytail: urban ULB evidence outranks village counts because most facilities sit in towns
    c = c.assign(rank_key=c.n_ulbs * 100000 + c.n_villages)
    c = c.sort_values(["pincode", "rank_key", "district_code"], ascending=[True, False, True])
    agg = c.groupby("pincode").agg(
        lgd_district_code=("district_code", "first"), lgd_district=("district_name", "first"),
        lgd_state=("state_name", "first"), n_districts=("district_code", "nunique"),
        all_districts=("district_name", lambda s: "; ".join(s)),
        has_urban=("n_ulbs", lambda s: bool((s > 0).any())))
    names = c.groupby("pincode").apply(
        lambda g: sorted({norm(x) for col in ("district_name",) for x in g[col]}
                         | {norm(x) for l in g.subdistricts for x in l}
                         | {norm_ulb(x) for l in g.places for x in l} - {""}),
        include_groups=False).rename("names")
    return agg.join(names).reset_index()


def city_agrees(city: object, names: list) -> tuple[bool, str, float]:
    c = norm(city)
    if not c or not names:
        return False, "", 0.0
    best = process.extractOne(c, names, scorer=fuzz.token_set_ratio)
    return best[1] >= CITY_AGREE, best[0], round(best[1], 1)


def facilities(con, raw: Path, primary: pd.DataFrame, ip: pd.DataFrame) -> pd.DataFrame:
    f = con.execute(f"""select unique_id, name, address_city, address_stateOrRegion,
        regexp_replace(coalesce(address_zipOrPostcode,''), '[^0-9]', '', 'g') pin
        from '{raw}/facilities.parquet'""").fetchdf()
    f["pin_valid"] = f.pin.str.fullmatch(r"[1-9][0-9]{5}")
    f = f.merge(primary, how="left", left_on="pin", right_on="pincode").drop(columns="pincode")
    f = f.merge(ip, how="left", left_on="pin", right_on="pincode").drop(columns="pincode")
    f["matched"] = f.lgd_district_code.notna()
    chk = [city_agrees(c, n if isinstance(n, list) else [])
           for c, n in zip(f.address_city, f.names)]
    f["city_agrees"], f["city_best"], f["city_score"] = zip(*chk)
    f["state_agrees"] = [norm_state(a) == norm_state(b) if m else None
                         for a, b, m in zip(f.address_stateOrRegion, f.lgd_state, f.matched)]
    f["ip_district_agrees"] = [
        (fuzz.ratio(norm(a), norm(b)) >= NFHS_AGREE or norm(a) in norm(alld))
        if m and isinstance(a, str) else None
        for a, b, alld, m in zip(f.ip_district, f.lgd_district, f.all_districts, f.matched)]
    return f.drop(columns="names")


def lgd_to_nfhs(con, lgd: Path, raw: Path) -> pd.DataFrame:
    d = con.execute(f"select district_code, district_name, state_name from '{lgd}/districts.parquet'").fetchdf()
    n = con.execute(f"select district_name, state_ut from '{raw}/nfhs_5_district_health_indicators.parquet'").fetchdf()
    n["s"] = n.state_ut.map(norm_state)
    rows = []
    for r in d.itertuples():
        pool = n[n.s == norm_state(r.state_name)]
        hit = process.extractOne(norm(r.district_name), pool.district_name.map(norm).tolist(),
                                 scorer=fuzz.ratio) if len(pool) else None
        ok = hit is not None and hit[1] >= NFHS_AGREE
        rows.append({"district_code": r.district_code, "lgd_district": r.district_name,
                     "lgd_state": r.state_name, "nfhs_district": pool.district_name.iloc[hit[2]] if ok else None,
                     "score": round(hit[1], 1) if hit else None, "state_in_nfhs": len(pool) > 0})
    return pd.DataFrame(rows)


def main(lgd: Path, raw: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    cand = pin_candidates(con, lgd)
    cand.drop(columns=["subdistricts", "places"]).to_parquet(out / "pin_district.parquet")
    primary = pick_primary(cand)
    ip = con.execute(f"""select pincode::varchar pincode, mode(district) ip_district, mode(statename) ip_state
        from '{raw}/india_post_pincode_directory.parquet' group by 1""").fetchdf()
    f = facilities(con, raw, primary, ip)
    f.to_parquet(out / "facility_lgd.parquet")
    nf = lgd_to_nfhs(con, lgd, raw)
    nf.to_csv(out / "lgd_nfhs_map.csv", index=False)
    m = f[f.matched]
    hc = m.sample(20, random_state=SEED)[["unique_id", "name", "address_city", "address_stateOrRegion",
                                          "pin", "lgd_district", "lgd_state", "all_districts",
                                          "ip_district", "city_best", "city_score"]]
    hc.to_csv(out / "handcheck_facilities.csv", index=False)
    ip_pins, lgd_pins = set(ip.pincode), set(primary.pincode)
    nfhs_hit = nf.nfhs_district.dropna()
    stats = {
        "facilities": len(f), "facilities_pin_valid": int(f.pin_valid.sum()),
        "facilities_matched_lgd": int(f.matched.sum()),
        "match_rate_of_valid_pin": round(f.matched.sum() / f.pin_valid.sum(), 4),
        "match_rate_of_all": round(f.matched.sum() / len(f), 4),
        "matched_pin_in_india_post": int(m.ip_district.notna().sum()),
        "valid_pin_not_in_lgd_but_in_india_post": int((f.pin_valid & ~f.matched & f.ip_district.notna()).sum()),
        "matched_single_district": int((m.n_districts == 1).sum()),
        "matched_multi_district": int((m.n_districts > 1).sum()),
        "matched_has_urban_mapping": int(m.has_urban.sum()),
        "state_agrees": int(m.state_agrees.sum()), "state_checked": len(m),
        "city_agrees": int(m.city_agrees.sum()), "city_checked": int(m.address_city.notna().sum()),
        "ip_district_agrees": int(m.ip_district_agrees.fillna(False).sum()),
        "ip_district_checked": int(m.ip_district_agrees.notna().sum()),
        "lgd_pins": len(lgd_pins), "india_post_pins": len(ip_pins),
        "pins_in_both": len(lgd_pins & ip_pins), "india_post_pins_missing_in_lgd": len(ip_pins - lgd_pins),
        "lgd_pins_missing_in_india_post": len(lgd_pins - ip_pins),
        "lgd_districts": len(nf), "lgd_districts_matched_nfhs": int(nf.nfhs_district.notna().sum()),
        "nfhs_districts": int(con.execute(f"select count(*) from '{raw}/nfhs_5_district_health_indicators.parquet'").fetchone()[0]),
        "nfhs_districts_reached": int(nfhs_hit.nunique()),
        "lgd_states_absent_in_nfhs": sorted(nf.loc[~nf.state_in_nfhs, "lgd_state"].unique().tolist()),
    }
    (out / "join_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))

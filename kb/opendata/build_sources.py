"""Normalise the OSM extract and the Wikidata pull into two facility tables plus tag coverage.

Run: .venv/bin/python -I kb/opendata/build_sources.py
Inputs (read only): data/crawl/opendata/osm/health_alltags.parquet (extract_osm.py),
data/crawl/opendata/wikidata/*.json (fetch_wikidata.py), the HOT export (coordinates of the
108 relations, and its geoBoundaries state), cleaning/geo_identity/pin_gazetteer.parquet
(state and district by nearest PIN centre).
Outputs: kb/opendata/osm_health_facilities.parquet, wikidata_medical_facilities.parquet,
tag_coverage.json.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from osm_hours import parse, week_text  # noqa: E402

ROOT = Path("/Users/karthikvattem/projects/datathon")
OUT = ROOT / "kb/opendata"
CRAWL = ROOT / "data/crawl/opendata"
HOT = ROOT / "data/external/hotosm_ind_health_facilities/health_facilities.parquet"
PINS = ROOT / "cleaning/geo_identity/pin_gazetteer.parquet"
# Switchboard numbers are kept only for kinds that are institutions, not one person's practice.
INSTITUTION = {"hospital", "clinic", "centre", "health_post", "nursing_home", "laboratory",
               "blood_donation", "dialysis", "rehabilitation", "hospice", "birthing_centre"}


def first(tags: dict, *keys: str) -> str | None:
    for k in keys:
        v = tags.get(k)
        if v not in (None, ""):
            return v
    return None


def to_int(v: str | None) -> int | None:
    m = re.match(r"^\s*(\d{1,5})\s*$", v or "")
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def nearest_pin(lat: np.ndarray, lon: np.ndarray, pins: pd.DataFrame) -> pd.DataFrame:
    """State and district of the nearest PIN centre.
    ponytail: nearest-centroid, can be wrong within a few km of a state border; upgrade to
    point-in-polygon on data/external/pincode_boundaries if that matters."""
    from scipy.spatial import cKDTree  # noqa: PLC0415
    k = cKDTree(np.c_[pins.lat.values, pins.lon.values * np.cos(np.radians(22))])
    ok = ~np.isnan(lat)
    idx = np.full(len(lat), -1)
    idx[ok] = k.query(np.c_[lat[ok], lon[ok] * np.cos(np.radians(22))])[1]
    p = pins.iloc[np.where(idx >= 0, idx, 0)].reset_index(drop=True)
    return pd.DataFrame({"state": np.where(ok, p.state.str.upper(), None),
                         "district": np.where(ok, p.district, None),
                         "nearest_pin": np.where(ok, p.pin, None)})


def build_osm(pins: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_parquet(CRAWL / "osm/health_alltags.parquet")
    hot = pd.read_parquet(HOT, columns=["id", "bbox", "adm1_name"]).drop_duplicates("id")
    hot = hot.assign(hlat=[(b["ymin"] + b["ymax"]) / 2 for b in hot.bbox],
                     hlon=[(b["xmin"] + b["xmax"]) / 2 for b in hot.bbox]).drop(columns="bbox")
    raw = raw.merge(hot.rename(columns={"id": "osm_id"}), on="osm_id", how="left")
    raw["lat"] = raw.lat.fillna(raw.hlat)
    raw["lon"] = raw.lon.fillna(raw.hlon)
    rows = []
    for r in raw.itertuples(index=False):
        t = json.loads(r.tags)
        kind = t.get("amenity") if t.get("amenity") in ("hospital", "clinic", "doctors", "dentist",
                                                        "health_post", "nursing_home") else t.get("healthcare")
        oh = first(t, "opening_hours")
        h = parse(oh)
        spec = first(t, "healthcare:speciality")
        phone = first(t, "phone", "contact:phone") if kind in INSTITUTION else None
        rows.append(dict(
            osm_id=r.osm_id, name=first(t, "name", "name:en"), name_en=first(t, "name:en"),
            lat=r.lat, lon=r.lon, amenity=t.get("amenity"), healthcare=t.get("healthcare"), kind=kind,
            opening_hours_raw=oh, hours_parse_ok=h.parse_ok if oh else None, is_24x7=h.is_24x7 if oh else None,
            hours_readable=h.readable or None, hours_week=week_text(h.week) if oh else None,
            emergency=first(t, "emergency"),
            speciality_raw=spec,
            specialities=[s.strip().lower().replace("_", " ") for s in re.split(r"[;,]", spec) if s.strip()]
            if spec else None,
            beds=to_int(first(t, "beds", "capacity:beds")), beds_raw=first(t, "beds", "capacity:beds"),
            operator=first(t, "operator"), operator_type=first(t, "operator:type"),
            phone=phone, website=first(t, "website", "contact:website", "url"),
            wheelchair=first(t, "wheelchair"), source_tag=first(t, "source"), check_date=first(t, "check_date"),
            description=first(t, "description"), health_facility_type=first(t, "health_facility:type"),
            addr_postcode=first(t, "addr:postcode"), addr_city=first(t, "addr:city"),
            addr_district=first(t, "addr:district"), addr_state=first(t, "addr:state"),
            addr_full=first(t, "addr:full") or " ".join(
                v for v in (t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:suburb")) if v) or None,
            wikidata=first(t, "wikidata"), last_edit=r.timestamp, version=r.version,
            hot_adm1=r.adm1_name, tags_json=r.tags,
        ))
    osm = pd.DataFrame(rows)
    return pd.concat([osm, nearest_pin(osm.lat.values.astype(float), osm.lon.values.astype(float), pins)], axis=1)


def _bindings(name: str) -> list[dict]:
    return json.load(open(CRAWL / f"wikidata/{name}.json"))["results"]["bindings"]


def _qid(b: dict, k: str) -> str:
    return b[k]["value"].rsplit("/", 1)[1]


def build_wikidata(pins: pd.DataFrame) -> pd.DataFrame:
    core: dict = {}
    for b in _bindings("core"):
        q = _qid(b, "item")
        d = core.setdefault(q, {"qid": q, "name": None, "lat": None, "lon": None})
        if "label" in b:
            d["name"] = b["label"]["value"]
        if "coord" in b and d["lat"] is None:
            m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", b["coord"]["value"], re.I)
            if m:
                d["lon"], d["lat"] = float(m.group(1)), float(m.group(2))
    props: dict = {}
    for b in _bindings("props"):
        p = b["prop"]["value"].rsplit("/", 1)[1]
        v = b.get("valueLabel", b["value"])["value"]
        props.setdefault((_qid(b, "item"), p), set()).add(v)
    cols = {"P31": "instance_of", "P6801": "beds_raw", "P856": "website", "P137": "operator", "P131": "located_in",
            "P281": "postcode", "P1995": "health_specialty", "P912": "has_facility", "P571": "inception",
            "P127": "owned_by"}
    wd = pd.DataFrame(core.values())
    for p, c in cols.items():
        wd[c] = [sorted(props[(q, p)]) if (q, p) in props else None for q in wd.qid]
    wd["beds"] = [max(int(float(x)) for x in v) if v else None for v in wd.beds_raw]
    wd["website"] = [v[0] if v else None for v in wd.website]
    wd["postcode"] = [v[0] if v else None for v in wd.postcode]
    wd["kind"] = [";".join(v) if v else None for v in wd.instance_of]
    wd = wd.astype({"lat": float, "lon": float})
    return pd.concat([wd, nearest_pin(wd.lat.values, wd.lon.values, pins)], axis=1)


def coverage(df: pd.DataFrame, fields: list[str]) -> dict:
    n = len(df)
    return {"n": n, **{f: {"non_null": int(df[f].notna().sum()), "share": round(df[f].notna().mean(), 4)}
                       for f in fields}}


def main() -> None:
    pins = pd.read_parquet(PINS, columns=["pin", "state", "district", "lat", "lon"]).dropna(subset=["lat"])
    osm = build_osm(pins)
    osm.to_parquet(OUT / "osm_health_facilities.parquet", index=False)
    wd = build_wikidata(pins)
    wd.to_parquet(OUT / "wikidata_medical_facilities.parquet", index=False)
    f = ["name", "opening_hours_raw", "emergency", "speciality_raw", "beds", "operator", "operator_type", "phone",
         "website", "wheelchair", "source_tag", "check_date", "addr_postcode", "addr_city", "wikidata"]
    cov = {"osm_all": coverage(osm, f),
           "osm_hospital": coverage(osm[osm.kind == "hospital"], f),
           "osm_clinic": coverage(osm[osm.kind == "clinic"], f),
           "osm_kind_counts": osm.kind.value_counts().head(25).to_dict(),
           "osm_type_counts": osm.osm_id.str.split("/").str[0].value_counts().to_dict(),
           "osm_no_coordinate": int(osm.lat.isna().sum()),
           "hours": {"with_tag": int(osm.opening_hours_raw.notna().sum()),
                     "parsed": int((osm.hours_parse_ok == True).sum()),  # noqa: E712
                     "is_24x7_true": int((osm.is_24x7 == True).sum()),  # noqa: E712
                     "is_24x7_false": int((osm.is_24x7 == False).sum()),  # noqa: E712
                     "top_raw": osm.opening_hours_raw.value_counts().head(25).to_dict(),
                     "unparsed_examples": osm.loc[osm.hours_parse_ok == False, "opening_hours_raw"]  # noqa: E712
                     .value_counts().head(25).to_dict()},
           "emergency_values": osm.emergency.value_counts().head(10).to_dict(),
           "top_specialities": osm.specialities.explode().value_counts().head(40).to_dict(),
           "beds_quantiles": osm.beds.dropna().quantile([0.1, 0.5, 0.9, 0.99]).to_dict(),
           "last_edit_year": pd.to_datetime(osm.last_edit, utc=True).dt.year.value_counts().sort_index().to_dict(),
           "state_counts": osm.state.value_counts().to_dict(),
           "wikidata": coverage(wd, ["name", "lat", "beds", "website", "operator", "postcode", "health_specialty",
                                     "inception"]),
           "wikidata_kind_top": wd.instance_of.explode().value_counts().head(20).to_dict(),
           "wikidata_state_counts": wd.state.value_counts().to_dict()}
    json.dump(cov, open(OUT / "tag_coverage.json", "w"), indent=1, default=str)
    print(json.dumps({k: cov[k] for k in ("osm_all", "osm_hospital", "hours", "emergency_values", "wikidata")},
                     indent=1, default=str))


if __name__ == "__main__":
    main()

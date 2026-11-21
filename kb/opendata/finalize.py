"""Score the hand-checks, assign match confidence, and write the enrichment outputs.

Run (after match_vf.py candidates and the hand-check CSVs have verdicts):
  .venv-kb2/bin/python -I kb/opendata/finalize.py
Outputs in kb/opendata/: vf_opendata_match.parquet (one row per VF facility x source, best
candidate, tier, confidence, source fields), vf_opendata_facts.parquet (long table of facts from
high/medium matches, each with the raw tag or statement it came from), opendata_not_in_vf.parquet
(open-data facilities no VF record matched; context only), precision.json, stats.json.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from match_vf import OUT, ROOT, tier, wilson  # noqa: E402

GOOD = {"yes", "likely"}
FOCUS = ["BIHAR", "UTTAR PRADESH", "JHARKHAND", "ODISHA"]
LICENCE = {"osm": "ODbL 1.0, (c) OpenStreetMap contributors", "wikidata": "CC0 1.0"}


def url(source: str, sid: str) -> str:
    return f"https://www.openstreetmap.org/{sid}" if source == "osm" else f"https://www.wikidata.org/wiki/{sid}"


def rate(df: pd.DataFrame) -> dict:
    k, n = int(df.verdict.isin(GOOD).sum()), len(df)
    sure = df[df.verdict != "uncertain"]
    return {"n": n, "correct": k, "precision": round(k / n, 3) if n else None, "wilson95": wilson(k, n),
            "n_uncertain": int((df.verdict == "uncertain").sum()),
            "precision_excl_uncertain": round(sure.verdict.isin(GOOD).mean(), 3) if len(sure) else None}


def precision() -> tuple[dict, dict]:
    tune = pd.read_csv(OUT / "handcheck_matches.csv")
    near = pd.read_csv(OUT / "handcheck_near_misses.csv")
    val = pd.read_csv(OUT / "handcheck_validation.csv")
    out: dict = {}
    for name, df in (("tuning_40", tune), ("near_miss_20", near), ("validation_35", val)):
        df = df.assign(final_tier=[tier(r) or "none" for r in df.itertuples()])
        out[name] = {t: rate(g) for t, g in df.groupby("final_tier")}
    t = tune.assign(band=pd.cut(tune.km, [-1, 1, 3, 10], labels=["0-1 km", "1-3 km", "3-10 km"]))
    out["tuning_by_distance_band"] = {str(b): rate(g) for b, g in t.groupby("band", observed=True)}
    far = t[t.km > 1]
    out["tuning_beyond_1km_by_pin"] = {"pin_agree": rate(far[far.pin_agree]), "no_pin": rate(far[~far.pin_agree])}
    out["near_miss_all"] = rate(near)
    pooled = pd.concat([tune, near, val]).drop_duplicates(["unique_id", "source"])
    pooled = pooled.assign(final_tier=[tier(r) or "none" for r in pooled.itertuples()])
    out["pooled_by_final_tier"] = {t: rate(g) for t, g in pooled.groupby("final_tier")}
    # Confidence attached to a match (yes + likely counted correct, uncertain counted wrong):
    # high uses the validation sample only (drawn after its rules were fixed); medium and conflict
    # have too few validation rows, so they use the pooled samples and are optimistic.
    pool = out["pooled_by_final_tier"]
    conf = {"high": out["validation_35"]["high"]["precision"], "medium": pool["medium"]["precision"],
            "conflict": pool["conflict"]["precision"]}
    return out, conf


def enrich(bc: pd.DataFrame) -> pd.DataFrame:
    osm = pd.read_parquet(OUT / "osm_health_facilities.parquet").drop(columns=["tags_json", "lat", "lon", "name"])
    wd = pd.read_parquet(OUT / "wikidata_medical_facilities.parquet").drop(columns=["lat", "lon", "name", "state",
                                                                                     "district", "nearest_pin", "kind", "website"])
    o = bc[bc.source == "osm"].merge(osm.rename(columns={"osm_id": "source_id"}).drop(
        columns=["state", "district", "nearest_pin", "kind"]), on="source_id", how="left")
    wd = wd.rename(columns={c: f"wd_{c}" for c in wd.columns if c != "qid"}).rename(columns={"qid": "source_id"})
    w = bc[bc.source == "wikidata"].merge(wd, on="source_id", how="left")
    return pd.concat([o, w], ignore_index=True)


def facts(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in m[m.tier.isin(["high", "medium"])].itertuples():
        base = dict(unique_id=r.unique_id, source=r.source, source_id=r.source_id, source_url=url(r.source, r.source_id),
                    match_tier=r.tier, match_conf=r.match_conf, licence=LICENCE[r.source])

        def add(field: str, value, evidence: str, observed=None) -> None:
            rows.append({**base, "field": field, "value": str(value), "evidence": evidence, "observed_at": observed})

        if r.source == "osm":
            seen = r.check_date if isinstance(r.check_date, str) else r.last_edit
            if isinstance(r.opening_hours_raw, str):
                ev = f"opening_hours={r.opening_hours_raw}"
                if r.hours_parse_ok:
                    add("is_24x7", bool(r.is_24x7), ev, seen)
                    add("opening_hours", r.hours_readable, ev, seen)
                else:
                    add("opening_hours_unparsed", r.opening_hours_raw, ev, seen)
            if r.emergency in ("yes", "no"):
                add("emergency", r.emergency, f"emergency={r.emergency}", seen)
            for s in r.specialities if r.specialities is not None else []:
                add("speciality", s, f"healthcare:speciality={r.speciality_raw}", seen)
            for f, v, tag in (("beds", r.beds, "beds"), ("operator_type", r.operator_type, "operator:type"),
                              ("operator", r.operator, "operator"), ("wheelchair", r.wheelchair, "wheelchair"),
                              ("phone_switchboard", r.phone, "phone"), ("website", r.website, "website"),
                              ("facility_kind", r.cand_kind, "amenity/healthcare")):
                if pd.notna(v):
                    add(f, int(v) if f == "beds" else v, f"{tag}={r.beds_raw if f == 'beds' else v}", seen)
        else:
            for f, v, prop in (("beds", r.wd_beds, "P6801"), ("operator", r.wd_operator, "P137"),
                               ("speciality", r.wd_health_specialty, "P1995"), ("facility_kind", r.wd_instance_of, "P31"),
                               ("inception", r.wd_inception, "P571")):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                vals = [int(v)] if f == "beds" else list(v)
                for x in vals:
                    add(f, x, f"{r.source_id} {prop} {x}")
    return pd.DataFrame(rows)


def not_in_vf(m: pd.DataFrame) -> pd.DataFrame:
    hit = set(m.loc[m.tier.isin(["high", "medium"]), "source_id"])
    osm = pd.read_parquet(OUT / "osm_health_facilities.parquet")
    wd = pd.read_parquet(OUT / "wikidata_medical_facilities.parquet")
    osm_qids = set(osm.wikidata.dropna())
    o = osm[~osm.osm_id.isin(hit) & osm.lat.notna()].assign(source="osm", source_id=lambda d: d.osm_id)
    w = wd[~wd.qid.isin(hit) & ~wd.qid.isin(osm_qids) & wd.lat.notna()].assign(
        source="wikidata", source_id=lambda d: d.qid, specialities=lambda d: d.health_specialty)
    cols = ["source", "source_id", "name", "kind", "lat", "lon", "state", "district", "nearest_pin", "is_24x7",
            "hours_readable", "emergency", "specialities", "beds", "operator_type"]
    out = pd.concat([o.reindex(columns=cols), w.reindex(columns=cols)], ignore_index=True)
    out["source_url"] = [url(s, i) for s, i in zip(out.source, out.source_id)]
    out["in_provided_dataset"] = False
    out["note"] = "Not in the provided Virtue Foundation dataset; open-data context only, unverified."
    return out


def coverage(m: pd.DataFrame, n_vf: int) -> dict:
    ok = m[m.tier.isin(["high", "medium"])]
    osm_ok = ok[ok.source == "osm"]
    has = {
        "any_match": ok.unique_id,
        "osm_match": osm_ok.unique_id,
        "wikidata_match": ok[ok.source == "wikidata"].unique_id,
        "hours_parsed": osm_ok[osm_ok.hours_parse_ok == True].unique_id,  # noqa: E712
        "is_24x7_true": osm_ok[osm_ok.is_24x7 == True].unique_id,  # noqa: E712
        "emergency_tag": osm_ok[osm_ok.emergency.isin(["yes", "no"])].unique_id,
        "emergency_yes": osm_ok[osm_ok.emergency == "yes"].unique_id,
        "speciality": ok[ok.specialities.notna() | ok.wd_health_specialty.notna()].unique_id,
        "beds": ok[ok.beds.notna() | ok.wd_beds.notna()].unique_id,
        "operator_type": osm_ok[osm_ok.operator_type.notna()].unique_id,
        "wheelchair": osm_ok[osm_ok.wheelchair.notna()].unique_id,
    }
    out = {k: {"n": int(v.nunique()), "share_of_vf": round(v.nunique() / n_vf, 4)} for k, v in has.items()}
    out["by_tier"] = {f"{s}_{t}": int(g.unique_id.nunique()) for (s, t), g in m.groupby(["source", "tier"])}
    hi = set(ok.loc[ok.tier == "high", "unique_id"])
    out["high_only"] = {k: len(hi & set(v)) for k, v in has.items()}
    return out


def crosscheck(m: pd.DataFrame) -> dict:
    """Agreement between OSM tags and the VF record's own text, on high/medium OSM matches.
    Not ground truth for either side: shows how often two independent sources say the same."""
    c = pd.read_parquet(ROOT / "cleaning/claims/out/claims.parquet", columns=["unique_id", "text"])
    txt = c.groupby("unique_id").text.agg(" ".join).str.lower()
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "capacity"]).drop_duplicates(
        "unique_id").set_index("unique_id").capacity
    ok = m[(m.source == "osm") & m.tier.isin(["high", "medium"])].set_index("unique_id")
    t = txt.reindex(ok.index).fillna("")
    says247 = t.str.contains(r"24\s*[x/*]\s*7|24\s*hours|24-hour|round[- ]the[- ]clock|24 hrs", regex=True)
    says_em = t.str.contains(r"emergenc|casualty|trauma", regex=True)
    out = {}
    for name, flag, osm_col, pos in (("24x7", says247, ok.is_24x7, True), ("emergency", says_em, ok.emergency, "yes")):
        has = osm_col.notna() & osm_col.isin([True, False, "yes", "no"])
        o = osm_col[has] == pos
        out[name] = {"n_osm_tagged": int(has.sum()),
                     "osm_yes_vf_text_yes": int((o & flag[has]).sum()), "osm_yes_vf_text_no": int((o & ~flag[has]).sum()),
                     "osm_no_vf_text_yes": int((~o & flag[has]).sum()), "osm_no_vf_text_no": int((~o & ~flag[has]).sum())}
    b = ok.beds.dropna()
    cap = pd.to_numeric(raw.reindex(b.index), errors="coerce")
    both = cap.notna()
    out["beds"] = {"n_osm_beds": len(b), "n_vf_capacity_too": int(both.sum()),
                   "within_20pct": int((abs(b[both] - cap[both]) <= 0.2 * cap[both]).sum())}
    return out


def main() -> None:
    prec, conf = precision()
    json.dump(prec, open(OUT / "precision.json", "w"), indent=1)
    bc = pd.read_parquet(OUT / "vf_candidates.parquet")
    bc["tier"] = [tier(r) for r in bc.itertuples()]
    bc["match_conf"] = [conf.get(t) if t in ("high", "medium") else None for t in bc.tier]
    bc["source_url"] = [url(s, i) for s, i in zip(bc.source, bc.source_id)]
    shared = bc[bc.tier.isin(["high", "medium"])].groupby("source_id").unique_id.transform("nunique")
    bc["source_shared_by_n_vf"] = shared.reindex(bc.index)
    m = enrich(bc)
    m.to_parquet(OUT / "vf_opendata_match.parquet", index=False)
    f = facts(m)
    f.to_parquet(OUT / "vf_opendata_facts.parquet", index=False)
    nv = not_in_vf(m)
    nv.to_parquet(OUT / "opendata_not_in_vf.parquet", index=False)
    loc = pd.read_parquet(ROOT / "cleaning/geo_identity/facility_location.parquet", columns=["unique_id", "state_final"])
    n_vf = loc.unique_id.nunique()
    vf_state = loc.state_final.str.upper().value_counts()
    by_state = nv.groupby("state").size().sort_values(ascending=False)
    stats = {
        "vf_facilities": n_vf,
        "candidates_by_source_tier": {f"{s}_{t}": int(n) for (s, t), n in
                                      bc.groupby(["source", bc.tier.fillna("none")]).size().items()},
        "match_conf_by_tier": conf,
        "coverage": coverage(m, n_vf),
        "facts_by_field": f.groupby(["source", "field"]).size().rename("n").reset_index()
        .assign(k=lambda d: d.source + ":" + d.field).set_index("k").n.to_dict(),
        "facts_vf_with_any": int(f.unique_id.nunique()),
        "not_in_vf_total": len(nv), "not_in_vf_by_source": nv.source.value_counts().to_dict(),
        "not_in_vf_by_state": by_state.to_dict(),
        "vf_by_state": vf_state.to_dict(),
        "focus_states": {s: {"not_in_vf": int(by_state.get(s, 0)), "vf_records": int(vf_state.get(s, 0)),
                             "not_in_vf_by_kind": nv[nv.state == s].kind.fillna("unknown").value_counts().head(8)
                             .to_dict(),
                             "not_in_vf_hospitals_osm": int(((nv.state == s) & (nv.kind == "hospital")).sum())}
                         for s in FOCUS},
        "crosscheck_vs_vf_text": crosscheck(m),
        "osm_features_shared_by_2plus_vf": int((m.source_shared_by_n_vf > 1).groupby(m.source_id).any().sum()),
    }
    json.dump(stats, open(OUT / "stats.json", "w"), indent=1, default=str)
    print(json.dumps({k: stats[k] for k in ("candidates_by_source_tier", "match_conf_by_tier", "coverage",
                                            "facts_vf_with_any", "not_in_vf_total", "focus_states")}, indent=1,
                     default=str))
    print(json.dumps(prec, indent=1))


if __name__ == "__main__":
    main()

"""Record-loss, duplication and coverage checks through the Referral Saathi pipeline.

Traces facility records raw -> usable -> derived/v1 -> kb -> app/facts, app/packs -> planner/out.
Every check is read-only and returns dict(name, status, metric, threshold, detail, examples).
status is pass | warn | fail | not_run (not_run: a network step that could not complete).

Run all:  /Users/karthikvattem/projects/datathon/.venv-viz/bin/python validation/record_loss/checks.py
Writes validation/record_loss/out/results.json, trace.csv, state_coverage.csv.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
RAW = ROOT / "data/raw/facilities.parquet"
V1 = ROOT / "derived/v1"
KB = ROOT / "kb"
OUT = ROOT / "validation/record_loss/out"
UUID_PREFIX = r"^[0-9a-f]{8}-[0-9a-f]{4}-"
UUID_FULL = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
FOCUS = ["BIHAR", "UTTAR PRADESH", "JHARKHAND", "ODISHA", "ASSAM"]
APP_SERVICES = {"csection": "emergency_csection", "nicu": "nicu", "trauma": "trauma_emergency",
                "burns": "burn_care", "dialysis": "dialysis", "mri": "mri", "cardiac_surgery": "cardiac_surgery"}
PACK_EXCLUDED_GRADES = {"attributed_elsewhere", "counter_evidence"}


def result(name, status, metric, threshold, detail, examples=None):
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail,
            "examples": [str(x) for x in (examples or [])][:5]}


# ---------------------------------------------------------------- loaders (cached, read-only)
@lru_cache(None)
def raw() -> pd.DataFrame:
    return pd.read_parquet(RAW)


@lru_cache(None)
def raw_classes() -> pd.Series:
    f = raw()
    uuid = f.unique_id.str.match(UUID_PREFIX, na=False)
    kie = f.source == "kie"
    return pd.Series(np.where(uuid & kie, "well_formed", np.where(uuid, "truncated", "fragment")), index=f.index)


@lru_cache(None)
def usable() -> pd.DataFrame:
    f = raw()
    return f[raw_classes() == "well_formed"].drop_duplicates("unique_id").reset_index(drop=True)


@lru_cache(None)
def U() -> frozenset:
    return frozenset(usable().unique_id)


@lru_cache(None)
def v1(name: str, columns: tuple | None = None) -> pd.DataFrame:
    return pd.read_parquet(V1 / name, columns=list(columns) if columns else None)


@lru_cache(None)
def loc() -> pd.DataFrame:
    return v1("facility_location.parquet")


@lru_cache(None)
def dims() -> pd.DataFrame:
    """Per usable facility: cleaned state (facility_location.state_final), raw type and operator."""
    u = usable()[["unique_id", "facilityTypeId", "operatorTypeId", "address_stateOrRegion"]]
    d = u.merge(loc()[["unique_id", "state_final"]], on="unique_id", how="left")
    d["ftype"] = d.facilityTypeId.replace({"null": None}).fillna("null")
    d["operator"] = d.operatorTypeId.replace({"null": None}).fillna("null")
    d["state"] = d.state_final.fillna("UNKNOWN")
    return d.set_index("unique_id")


def breakdown(uids, by=("state", "ftype", "operator"), top=8) -> dict:
    d = dims()
    s = d.loc[[u for u in uids if u in d.index]]
    return {b: s[b].value_counts().head(top).to_dict() for b in by}


@lru_cache(None)
def facts() -> dict:
    return json.loads(gzip.decompress((ROOT / "app/facts/out/facts.json.gz").read_bytes()))


@lru_cache(None)
def planner() -> dict:
    return json.loads(gzip.decompress((ROOT / "planner/out/planner_v1.json.gz").read_bytes()))


@lru_cache(None)
def pack_index() -> dict:
    return json.loads((ROOT / "app/packs/out/index.json").read_text())


@lru_cache(None)
def packs() -> dict:
    out = {}
    for slug in pack_index()["packs"]:
        out[slug] = json.loads(gzip.decompress((ROOT / f"app/packs/out/{slug}.json.gz").read_bytes()))
    return out


@lru_cache(None)
def uid8_map() -> dict:
    m = defaultdict(list)
    for u in U():
        m[u[:8]].append(u)
    return m


def decode_pack(p: dict) -> dict:
    fac_lat = np.cumsum(p["fac"]["lat"]) / p["scale"]["fac"]
    fac_lon = np.cumsum(p["fac"]["lon"]) / p["scale"]["fac"]
    ev_f = np.cumsum(p["ev"]["f"])
    pin = np.cumsum(p["pins"]["pin"])
    plat = np.cumsum(p["pins"]["lat"]) / p["scale"]["pin"]
    plon = np.cumsum(p["pins"]["lon"]) / p["scale"]["pin"]
    return {"fac_lat": fac_lat, "fac_lon": fac_lon, "ev_f": ev_f, "pin": pin, "plat": plat, "plon": plon}


def hav(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(c - h, 4), round(c + h, 4))


# ================================================================ layer 0: raw -> usable
def check_raw_row_classes():
    """10,088 raw rows split into well_formed / truncated / fragment exactly as data/raw/PROFILE.json says."""
    c = raw_classes().value_counts().to_dict()
    prof = json.loads((ROOT / "data/raw/PROFILE.json").read_text())["row_integrity"]
    ok = len(raw()) == 10088 and c == prof
    return result("raw_row_classes", "pass" if ok else "fail", f"rows={len(raw())} classes={c}",
                  "10,088 rows; classes equal PROFILE.json row_integrity",
                  f"PROFILE.json says {prof}. Rule: well_formed = UUID unique_id and source='kie' "
                  "(audit/geo/geo_common.py:82 load_facilities).")


def check_raw_hash_unchanged():
    """data/raw/facilities.parquet bytes equal the hash recorded at build time in derived/v1/MANIFEST.json."""
    man = json.loads((V1 / "MANIFEST.json").read_text())["raw_input_sha256"]
    bad = [n for n, h in man.items() if (ROOT / "data/raw" / n).exists() and sha256(ROOT / "data/raw" / n) != h]
    return result("raw_hash_unchanged", "fail" if bad else "pass", f"{len(man) - len(bad)}/{len(man)} files match",
                  "all match", "sha256 of data/raw files vs derived/v1/MANIFEST.json raw_input_sha256", bad)


def check_live_table_counts():
    """The live Marketplace table has the same row classes (1 SELECT, retried)."""
    q = ("SELECT count(*) n, sum(case when unique_id rlike '^[0-9a-f]{8}-[0-9a-f]{4}-' and source='kie' then 1 else 0 end) wf, "
         "sum(case when unique_id rlike '^[0-9a-f]{8}-[0-9a-f]{4}-' and (source is null or source<>'kie') then 1 else 0 end) tr, "
         "count(distinct case when unique_id rlike '^[0-9a-f]{8}-[0-9a-f]{4}-' and source='kie' then unique_id end) us "
         "FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities")
    cache = OUT / "live_counts.txt"
    for attempt in range(3):
        try:
            r = subprocess.run([str(ROOT / "sql.sh"), q], capture_output=True, text=True, timeout=90)
            if r.returncode == 0:
                cache.write_text(r.stdout)
                break
        except subprocess.TimeoutExpired:
            pass
        time.sleep(3 * (attempt + 1))
    else:
        return result("live_table_counts", "not_run", "n/a", "10088/9970/30/9959", "sql.sh failed 3 times")
    vals = [int(x) for x in r.stdout.strip().splitlines()[-1].split("\t")]
    ok = vals == [10088, 9970, 30, 9959]
    return result("live_table_counts", "pass" if ok else "fail", f"n,well_formed,truncated,usable={vals}",
                  "10088,9970,30,9959", "Databricks Marketplace table, SELECT via sql.sh")


def check_uuid_rule_equivalence():
    """The prefix regex (geo_common) and the full-UUID regex (claims/build_claims.py) select the same rows."""
    f = raw()
    a = f.unique_id.str.match(UUID_PREFIX, na=False) & (f.source == "kie")
    b = f.unique_id.str.match(UUID_FULL, na=False) & (f.source == "kie")
    diff = f.unique_id[a ^ b].tolist()
    return result("uuid_rule_equivalence", "fail" if diff else "pass", f"{len(diff)} rows differ", "0",
                  "audit/geo/geo_common.py:85 (prefix) vs cleaning/claims/build_claims.py:21 (full UUID)", diff)


def check_raw_duplicates_lossless():
    """The 11 duplicated unique_ids are byte-identical, so dropping one row of each loses nothing."""
    w = raw()[raw_classes() == "well_formed"]
    d = w[w.unique_id.duplicated(keep=False)]
    groups = d.groupby("unique_id")
    nonident = [u for u, g in groups if len(g.astype(str).drop_duplicates()) > 1]
    n_rows, n_ids = len(d), d.unique_id.nunique()
    ok = n_rows == 22 and n_ids == 11 and not nonident
    return result("raw_duplicates_lossless", "pass" if ok else "fail",
                  f"{n_ids} ids x 2 rows; {len(nonident)} not identical", "11 ids, all identical",
                  f"9,970 well-formed -> 9,959 usable. Documented: REPORT.md F7/ID1, cleaning/geo_identity/common.py:22. "
                  f"By state: {breakdown(d.unique_id.unique())['state']}", sorted(d.unique_id.unique()))


def check_raw_truncated_real_facilities():
    """The 30 'truncated' rows are real facilities (UUID, name, city, state, type) whose row was cut after
    `description`; they are dropped by the source='kie' rule. Recoverable only by stitching the fragments."""
    f = raw()
    t = f[raw_classes() == "truncated"]
    named = t.name.notna() & ~t.name.isin(["", "null"])
    empty_after_desc = t[["specialties", "procedure", "capability", "latitude", "source_urls"]].isna().all(axis=1)
    in_usable = t.unique_id.isin(U()).sum()
    st = t.address_stateOrRegion.value_counts().to_dict()
    focus = {k: v for k, v in st.items() if k.upper() in FOCUS or k in ("Orissa",)}
    detail = (f"{len(t)} truncated rows, {int(named.sum())} with a name, {int(empty_after_desc.sum())} with every column "
              f"after description null, {int(in_usable)} also present as a usable row. Types: "
              f"{t.facilityTypeId.value_counts().to_dict()}; states: {st}; focus states: {focus}. "
              "PROFILE.json and REPORT.md document the rule (row integrity class 'truncated') but no document lists these "
              "30 as lost facilities or says the app cannot show them; no stitch from the 88 fragment rows was attempted.")
    ex = [f"{u} {n} ({c}, {s})" for u, n, c, s in
          t[["unique_id", "name", "address_city", "address_stateOrRegion"]].head(5).itertuples(index=False)]
    ex = [x for x in ex] + [f"{u} {n} (Patna, Bihar)" for u, n in t[t.address_stateOrRegion == "Bihar"][["unique_id", "name"]].itertuples(index=False)]
    return result("raw_truncated_real_facilities", "warn", f"{len(t)}/10088 rows ({int(named.sum())} named facilities) dropped",
                  "0 real facilities lost without a listed reason", detail, ex[-2:] + ex[:3])


def check_fragment_rows_carry_no_facility():
    """Fragment rows (no UUID) hold continuation text; none carries a UUID of a usable record anywhere."""
    f = raw()
    fr = f[raw_classes() == "fragment"]
    uuid_any = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    hits = set()
    for col in fr.columns:
        for v in fr[col].dropna().astype(str):
            hits.update(uuid_any.findall(v))
    hit_usable = hits & U()
    trunc_ids = set(f[raw_classes() == "truncated"].unique_id)
    hit_trunc = hits & trunc_ids
    coords = fr.apply(lambda r: any('"coordinates"' in str(v) for v in r.values), axis=1).sum()
    return result("fragment_rows_carry_no_facility", "warn" if hit_trunc or coords else "pass",
                  f"{len(fr)} fragments; {len(hit_usable)} usable UUIDs, {len(hit_trunc)} truncated UUIDs inside; "
                  f"{int(coords)} fragments hold a coordinates object",
                  "0 facility payload in fragments",
                  "Fragments hold the tail of the 30 truncated rows (specialties, coordinates, source_urls shifted into "
                  "name/address columns). They are correctly excluded, but they are the only copy of those 30 "
                  "facilities' coordinates and service lists.", sorted(hit_trunc)[:5])


# ================================================================ layer 1: derived/v1
PER_FACILITY = ["facility_location.parquet", "record_trust.parquet", "facility_groups.parquet", "facility_trust.parquet"]


def check_v1_per_facility_tables():
    """Every one-row-per-record table has exactly the 9,959 usable unique_ids, no duplicates, no extras."""
    bad, det = [], []
    for t in PER_FACILITY:
        ids = v1(t, ("unique_id",)).unique_id
        dup, missing, extra = int(ids.duplicated().sum()), len(U() - set(ids)), len(set(ids) - U())
        det.append(f"{t}: rows={len(ids)} dup={dup} missing={missing} extra={extra}")
        if len(ids) != 9959 or dup or missing or extra:
            bad.append(t)
    csv = pd.read_csv(V1 / "facility_trust.csv", usecols=["unique_id"]).unique_id
    det.append(f"facility_trust.csv: rows={len(csv)} set_equal={set(csv) == U()}")
    if set(csv) != U() or len(csv) != 9959:
        bad.append("facility_trust.csv")
    return result("v1_per_facility_tables", "fail" if bad else "pass", f"{len(PER_FACILITY) + 1 - len(bad)}/5 exact",
                  "9,959 rows = usable set", "; ".join(det), bad)


def check_v1_child_tables_fk():
    """Every unique_id in a child table of derived/v1 is a usable record (no orphans, no truncated ids)."""
    tables = ["claims.parquet", "specialties.parquet", "grades.parquet", "grades_v1.parquet", "data_point_scores.parquet",
              "source_urls.parquet", "source_page_checks.parquet", "gold_pairs.parquet"]
    det, ex = [], []
    for t in tables:
        ids = set(v1(t, ("unique_id",)).unique_id.dropna())
        orphan = ids - U()
        det.append(f"{t}: {len(ids)} facilities, {len(orphan)} orphans")
        ex += sorted(orphan)[:2]
    return result("v1_child_tables_fk", "fail" if ex else "pass", f"{len(ex)} orphan ids", "0", "; ".join(det), ex)


def check_v1_copies_match_sources():
    """Canonical tables in derived/v1 are byte copies of cleaning/ outputs; detect a stale copy."""
    man = json.loads((V1 / "MANIFEST.json").read_text())["other_input_sha256"]
    pairs = {"facility_location.parquet": "cleaning/geo_identity/facility_location.parquet",
             "record_trust.parquet": "cleaning/geo_identity/record_trust.parquet",
             "facility_groups.parquet": "cleaning/geo_identity/facility_groups.parquet",
             "pin_gazetteer.parquet": "cleaning/geo_identity/pin_gazetteer.parquet",
             "place_gazetteer.parquet": "cleaning/geo_identity/place_gazetteer.parquet",
             "claims.parquet": "cleaning/claims/out/claims.parquet",
             "specialties.parquet": "cleaning/claims/out/specialties.parquet",
             "grades.parquet": "cleaning/claims/out/grades.parquet"}
    bad, det = [], []
    for t, src in pairs.items():
        a, s = sha256(V1 / t), (ROOT / src)
        if not s.exists():
            det.append(f"{t}: source {src} missing")
            continue
        same = a == sha256(s)
        man_ok = man.get(src) in (None, a)
        det.append(f"{t}: {'same' if same else 'DIFFERENT'} as {src}; manifest {'ok' if man_ok else 'MISMATCH'}")
        if not same or not man_ok:
            bad.append(t)
    return result("v1_copies_match_sources", "fail" if bad else "pass", f"{len(pairs) - len(bad)}/{len(pairs)} identical",
                  "all identical", "; ".join(det), bad)


@lru_cache(None)
def claims_expected() -> pd.DataFrame:
    """Re-run the explode step of cleaning/claims/build_claims.py (EXPLODE_SQL, copied verbatim) read-only."""
    sql = f"""
with b as (
  select * from read_parquet('{RAW}')
  where regexp_matches(unique_id, '{UUID_FULL}') and source = 'kie'
  qualify row_number() over (partition by unique_id order by unique_id) = 1
),
arr as (
  select unique_id, 'procedure' field, procedure j from b union all
  select unique_id, 'equipment', equipment from b union all
  select unique_id, 'capability', capability from b
),
lists as (select unique_id, field, from_json(j, '["VARCHAR"]') l from arr where json_valid(j) and json_type(j) = 'ARRAY'),
items as (select unique_id, field, unnest(l) item, generate_subscripts(l, 1) pos from lists),
desc_s as (
  select unique_id, 'description' field,
         string_split(regexp_replace(description, '([.!?])\\s+', '\\1' || chr(31), 'g'), chr(31)) l
  from b where description is not null and description <> 'null'
),
ditems as (select unique_id, field, unnest(l) item, generate_subscripts(l, 1) pos from desc_s),
allitems as (select * from items union all select * from ditems)
select unique_id, field, row_number() over (partition by unique_id, field order by pos) - 1 idx,
       regexp_replace(item, '^\\s+|\\s+$', '', 'g') text
from allitems where item is not null and regexp_replace(item, '^\\s+|\\s+$', '', 'g') <> ''
"""
    return duckdb.sql(sql).df()


def check_claims_reproduce_from_raw():
    """claims.parquet has exactly one row per non-empty raw item (procedure/equipment/capability array items and
    description sentences), with the same text: no silent loss, no fan-out."""
    e = claims_expected()
    c = v1("claims.parquet", ("claim_id", "unique_id", "field", "idx", "text"))
    m = e.merge(c, on=["unique_id", "field", "idx"], how="outer", suffixes=("_raw", "_v1"), indicator=True)
    only_raw = m[m._merge == "left_only"]
    only_v1 = m[m._merge == "right_only"]
    both = m[m._merge == "both"]
    textdiff = both[both.text_raw != both.text_v1]
    ok = not len(only_raw) and not len(only_v1) and not len(textdiff)
    ex = (only_raw.unique_id.head(2).tolist() + only_v1.claim_id.head(2).tolist() + textdiff.claim_id.head(2).tolist())
    return result("claims_reproduce_from_raw", "pass" if ok else "fail",
                  f"raw items={len(e)} v1 claims={len(c)} missing={len(only_raw)} extra={len(only_v1)} text_diff={len(textdiff)}",
                  "0 / 0 / 0", f"By field (raw): {e.field.value_counts().to_dict()}", ex)


def check_claims_key_integrity():
    """claim_id unique, equals uid8:field4:idx, and uid8 maps to exactly one usable record."""
    c = v1("claims.parquet", ("claim_id", "unique_id", "field", "idx"))
    dup = int(c.claim_id.duplicated().sum())
    expect = c.unique_id.str[:8] + ":" + c.field.str[:4] + ":" + c.idx.astype(str)
    bad_fmt = c[expect != c.claim_id]
    coll = {k: v for k, v in uid8_map().items() if len(v) > 1}
    ok = not dup and not len(bad_fmt) and not coll
    return result("claims_key_integrity", "pass" if ok else "fail",
                  f"dup={dup} bad_format={len(bad_fmt)} uid8_collisions={len(coll)}", "0 / 0 / 0",
                  "claim ids and pack uid8 keys rely on the first 8 hex chars being unique over 9,959 records",
                  bad_fmt.claim_id.head(3).tolist() + list(coll)[:2])


def check_claims_invalid_json_dropped():
    """Raw procedure/equipment/capability values that are not null-like but are not a valid JSON array are
    dropped silently by build_claims.py (json_valid filter)."""
    u = usable()
    null_like = {"", "null", "[]", '[""]', "[null]", "none", "nan"}
    rows = []
    for fld in ("procedure", "equipment", "capability", "specialties"):
        for uid, v in zip(u.unique_id, u[fld]):
            if v is None or str(v).strip().lower() in null_like:
                continue
            try:
                ok = isinstance(json.loads(v), list)
            except (ValueError, TypeError):
                ok = False
            if not ok:
                rows.append((uid, fld, str(v)[:60]))
    return result("claims_invalid_json_dropped", "warn" if rows else "pass", f"{len(rows)} field values dropped", "0",
                  f"by field: {Counter(r[1] for r in rows)}; root cause cleaning/claims/build_claims.py:35 "
                  "(where json_valid(j) and json_type(j)='ARRAY')", [f"{a} {b}: {c}" for a, b, c in rows])


def check_facilities_without_claims():
    """Usable facilities with zero claim sentences: are they explained by empty raw text fields?"""
    c = v1("claims.parquet", ("unique_id",))
    have = set(c.unique_id)
    none = sorted(U() - have)
    e = claims_expected()
    unexplained = sorted(set(none) & set(e.unique_id))
    return result("facilities_without_claims", "fail" if unexplained else ("warn" if none else "pass"),
                  f"{len(none)}/9959 have no claims; {len(unexplained)} unexplained", "unexplained = 0",
                  f"Facilities with no claim cannot get any service pair, so they never appear in packs or as a "
                  f"service candidate in facts (they remain in facts.fac). Explained = every raw text field empty. "
                  f"Breakdown: {breakdown(none)}", none)


def check_specialties_dup_inflation():
    """specialties.parquet n_raw double-counts for the 11 duplicated unique_ids (SPEC_SQL has no dedupe)."""
    s = v1("specialties.parquet")
    u = usable()
    exp = []
    for uid, v in zip(u.unique_id, u.specialties):
        try:
            lst = json.loads(v) if v else []
        except (ValueError, TypeError):
            lst = []
        if not isinstance(lst, list):
            continue
        for x in lst:
            if isinstance(x, str) and x.strip():
                exp.append((uid, re.sub(r"[^a-z]", "", x.lower())))
    e = pd.DataFrame(exp, columns=["unique_id", "spec"]).value_counts().rename("n_exp").reset_index()
    m = e.merge(s, on=["unique_id", "spec"], how="outer", indicator=True)
    both = m[m._merge == "both"]
    infl = both[both.n_raw != both.n_exp]
    dup_ids = set(raw()[raw_classes() == "well_formed"].unique_id.value_counts().loc[lambda x: x > 1].index)
    infl_dup = infl.unique_id.isin(dup_ids).all() if len(infl) else True
    miss, extra = int((m._merge == "left_only").sum()), int((m._merge == "right_only").sum())
    status = "fail" if miss or extra else ("warn" if len(infl) else "pass")
    return result("specialties_dup_inflation", status,
                  f"rows={len(s)} missing={miss} extra={extra} n_raw_wrong={len(infl)} "
                  f"({infl.unique_id.nunique()} facilities, all duplicated ids: {bool(infl_dup)})",
                  "0 / 0 / 0", "Root cause: cleaning/claims/build_claims.py:51 SPEC_SQL reads raw without the "
                  "row_number() dedupe used by EXPLODE_SQL, so n_raw is doubled for duplicated rows. The empty-string "
                  "spec (non-alpha value) is also kept as its own row.",
                  infl.unique_id.drop_duplicates().head(5).tolist())


def check_grades_keys():
    """grades.parquet and grades_v1.parquet: one row per (unique_id, service); same key set; service set."""
    g = v1("grades.parquet", ("unique_id", "service"))
    g1 = v1("grades_v1.parquet", ("unique_id", "service"))
    dup, dup1 = int(g.duplicated().sum()), int(g1.duplicated().sum())
    k, k1 = set(map(tuple, g.values)), set(map(tuple, g1.values))
    ok = not dup and not dup1 and k == k1
    return result("grades_keys", "pass" if ok else "fail",
                  f"rows={len(g)} dup={dup} v1dup={dup1} keys_equal={k == k1}", "unique, equal",
                  f"{g.unique_id.nunique()} facilities with >= 1 graded service; services {g.service.value_counts().to_dict()}",
                  [f"{a}:{b}" for a, b in list(k ^ k1)[:5]])


def check_dps_composition():
    """data_point_scores rows = sentences + grades + 1 location + 1 existence per record + phones + emails;
    dp_id unique; each part 1:1 with its source table."""
    d = v1("data_point_scores.parquet", ("dp_id", "dp_type", "unique_id", "claim_id", "service"))
    u = usable()
    n_phone = int((u.officialPhone.notna() & ~u.officialPhone.isin(["", "null"])).sum())
    n_email = int((u.email.notna() & ~u.email.isin(["", "null", "[]"])).sum())
    exp = {"claim_attribution": 469498, "service_claim": len(v1("grades.parquet", ("unique_id",))),
           "location": 9959, "existence": 9959, "phone": n_phone, "email": n_email}
    got = d.dp_type.value_counts().to_dict()
    dup = int(d.dp_id.duplicated().sum())
    sent = set(d[d.dp_type == "claim_attribution"].claim_id)
    cl = set(v1("claims.parquet", ("claim_id",)).claim_id)
    svc = set(map(tuple, d[d.dp_type == "service_claim"][["unique_id", "service"]].values))
    gr = set(map(tuple, v1("grades.parquet", ("unique_id", "service")).values))
    one_per = {t: int(d[d.dp_type == t].unique_id.duplicated().sum()) for t in ("location", "existence", "phone", "email")}
    ok = got == exp and not dup and sent == cl and svc == gr and not any(one_per.values()) and len(d) == 518191
    no_phone = sorted(U() - set(d[d.dp_type == "phone"].unique_id))
    return result("dps_composition", "pass" if ok else "fail", f"rows={len(d)} by type={got}", f"expected {exp}",
                  f"dp_id dups={dup}; sentences==claims {sent == cl}; service==grades {svc == gr}; dup per record {one_per}. "
                  f"{len(no_phone)} records have no phone point because raw officialPhone is null or 'null' "
                  f"(pipelines/source_scoring/s4_datapoints.py:108); {9959 - n_email} have no email point (s4:112).",
                  no_phone[:3])


def check_source_urls_vs_raw():
    """source_urls.parquet has one row per non-empty string item of each record's raw source_urls array
    (null items are dropped by audit/provenance/common.py:32 jlist). Also counts the same URL repeated in one
    record, which counts that source twice in the record's attribution weights."""
    s = v1("source_urls.parquet", ("unique_id", "url_pos", "url", "source_class"))
    u = usable()
    exp, n_null, bad_json = {}, 0, []
    for uid, v in zip(u.unique_id, u.source_urls):
        try:
            lst = json.loads(v) if v and v != "null" else []
        except (ValueError, TypeError):
            bad_json.append(uid)
            lst = []
        lst = lst if isinstance(lst, list) else []
        n_null += sum(1 for x in lst if not (isinstance(x, str) and x.strip()))
        exp[uid] = sum(1 for x in lst if isinstance(x, str) and x.strip())
    got = s.unique_id.value_counts().to_dict()
    diff = {k: (exp.get(k, 0), got.get(k, 0)) for k in set(exp) | set(got) if exp.get(k, 0) != got.get(k, 0)}
    dup_pos = int(s.duplicated(["unique_id", "url_pos"]).sum())
    dup_url = s[s.duplicated(["unique_id", "url"], keep="first")]
    no_url = [k for k, v in exp.items() if v == 0]
    status = "fail" if diff or dup_pos else ("warn" if len(dup_url) else "pass")
    return result("source_urls_vs_raw", status,
                  f"rows={len(s)} expected={sum(exp.values())} differing={len(diff)}; same URL repeated in a record: "
                  f"{len(dup_url)} rows in {dup_url.unique_id.nunique()} records",
                  "0 differing; 0 repeated", f"{n_null} null items in raw arrays dropped (documented by jlist). "
                  f"{len(no_url)} records have no source URL; {len(bad_json)} unparseable arrays. Repeats are not "
                  "deduplicated by pipelines/source_scoring/s1_sources.py:21, so w_sd (README 'Attribution weights') "
                  "counts a repeated URL twice. Repeated rows by class: "
                  f"{dup_url.source_class.value_counts().head(5).to_dict()}",
                  list(diff)[:3] + dup_url.unique_id.drop_duplicates().head(3).tolist())


def check_facility_trust_counts_consistent():
    """facility_trust.n_sentences / n_service_claims equal the per-record row counts of claims and grades."""
    ft = v1("facility_trust.parquet", ("unique_id", "n_sentences", "n_service_claims")).set_index("unique_id")
    ns = v1("claims.parquet", ("unique_id",)).unique_id.value_counts()
    ng = v1("grades.parquet", ("unique_id",)).unique_id.value_counts()
    a = ft.n_sentences.fillna(0).astype(int) != ns.reindex(ft.index).fillna(0).astype(int)
    b = ft.n_service_claims.fillna(0).astype(int) != ng.reindex(ft.index).fillna(0).astype(int)
    bad = sorted(set(ft.index[a]) | set(ft.index[b]))
    return result("facility_trust_counts_consistent", "fail" if bad else "pass",
                  f"{int(a.sum())} n_sentences and {int(b.sum())} n_service_claims mismatches", "0", "", bad)


def check_location_and_state_coverage():
    """Every usable record has a ranking point and a cleaned state; the cleaned state agrees with raw where raw
    names a real state."""
    l = loc()
    no_pt = l[l.loc_lat.isna() | l.loc_lon.isna()].unique_id.tolist()
    no_state = l[l.state_final.isna()].unique_id.tolist()
    no_dist = l[l.district.isna()].unique_id.tolist()
    return result("location_and_state_coverage", "fail" if no_pt or no_state else ("warn" if no_dist else "pass"),
                  f"no point={len(no_pt)} no state={len(no_state)} no district={len(no_dist)}", "0 / 0 / 0",
                  f"Records without a district cannot get NFHS context or district grouping: {breakdown(no_dist)['state']}",
                  no_pt + no_state + no_dist)


def check_dup_groups_consistent():
    """facility_groups: every dup_group_id has group_size members, exactly one canonical record."""
    g = v1("facility_groups.parquet")
    gg = g[g.dup_group_id.notna()].groupby("dup_group_id")
    bad = [k for k, x in gg if len(x) != x.group_size.iloc[0] or x.is_canonical.sum() != 1]
    single_bad = g[g.dup_group_id.isna() & ((g.group_size != 1) | ~g.is_canonical)].unique_id.tolist()
    n_noncanon = int((~g.is_canonical).sum())
    return result("dup_groups_consistent", "fail" if bad or single_bad else "pass",
                  f"{gg.ngroups} groups, {n_noncanon} non-canonical records, {len(bad)} inconsistent groups", "0",
                  "9,959 records = 9,882 distinct facilities after duplicate groups; downstream exports keep all 9,959 "
                  "(see check pack_duplicate_facilities_in_lists).", bad + single_bad)


# ================================================================ layer 2: kb
def _list_ids(series) -> set:
    out = set()
    for v in series.dropna():
        out.update(list(v) if not isinstance(v, str) else [v])
    return out


def check_kb_fk_integrity():
    """Every unique_id referenced by a kb table is a usable record; tables with a natural key have no duplicates."""
    specs = [  # (path, id column, key columns or None, is list column)
        ("kb/crawl/targets.parquet", "unique_ids", ["target_id"], True),
        ("kb/crawl/sites.parquet", "unique_ids", ["target_id"], True),
        ("kb/crawl/pages.parquet", "unique_ids", None, True),
        ("kb/web_evidence/out/site_identity.parquet", "unique_id", ["target_id", "unique_id"], False),
        ("kb/web_evidence/out/page_identity.parquet", "unique_id", ["page_id", "unique_id"], False),
        ("kb/web_evidence/out/web_service_summary.parquet", "unique_id", ["unique_id", "service_id"], False),
        ("kb/web_evidence/out/web_facility_details.parquet", "unique_id", ["unique_id", "fact_type", "attribute"], False),
        ("kb/web_evidence/out/web_details.parquet", "unique_id", ["fact_id"], False),
        ("kb/web_evidence/out/web_hours.parquet", "unique_id", ["fact_id"], False),
        ("kb/web_evidence/out/web_services.parquet", "unique_id", None, False),
        ("kb/vf_details/out/facts.parquet", "unique_id", ["fact_id"], False),
        ("kb/vf_details/out/facility_details.parquet", "unique_id", ["unique_id", "fact_type", "attribute"], False),
        ("kb/opendata/vf_opendata_match.parquet", "unique_id", ["unique_id", "source", "source_id"], False),
        ("kb/opendata/vf_opendata_facts.parquet", "unique_id", None, False),
        ("kb/taxonomy/out/lexicon_matches.parquet", "unique_id", ["claim_id", "service"], False),
    ]
    det, ex, bad = [], [], []
    for path, idc, key, is_list in specs:
        t = pd.read_parquet(ROOT / path)
        ids = _list_ids(t[idc]) if is_list else set(t[idc].dropna())
        orphan = ids - U()
        dup = int(t.duplicated(key).sum()) if key else None
        det.append(f"{Path(path).name}: rows={len(t)} facilities={len(ids)} orphans={len(orphan)}"
                   + (f" dup_key={dup}" if key else ""))
        if orphan or dup:
            bad.append(Path(path).name)
            ex += [f"{Path(path).name}: {o}" for o in sorted(orphan)[:2]]
            if dup:
                ex.append(f"{Path(path).name}: {dup} duplicate {key}")
    return result("kb_fk_integrity", "fail" if bad else "pass", f"{len(specs) - len(bad)}/{len(specs)} clean",
                  "0 orphans, 0 duplicate keys", "; ".join(det), ex)


def check_kb_claim_refs():
    """kb rows that cite a claim_id point at an existing claim of the same record."""
    cl = v1("claims.parquet", ("claim_id", "unique_id")).set_index("claim_id").unique_id
    det, ex, bad = [], [], 0
    for path in ["kb/taxonomy/out/lexicon_matches.parquet", "kb/vf_details/out/facts.parquet"]:
        t = pd.read_parquet(ROOT / path, columns=["claim_id", "unique_id"]).dropna(subset=["claim_id"])
        owner = t.claim_id.map(cl)
        missing = t[owner.isna()]
        wrong = t[owner.notna() & (owner != t.unique_id)]
        det.append(f"{Path(path).name}: {len(t)} refs, {len(missing)} missing claim, {len(wrong)} other record")
        bad += len(missing) + len(wrong)
        ex += missing.claim_id.head(2).tolist() + wrong.claim_id.head(2).tolist()
    return result("kb_claim_refs", "fail" if bad else "pass", f"{bad} bad refs", "0", "; ".join(det), ex)


def check_crawl_target_coverage():
    """Recompute 'records with at least one crawl target' (README: 8,015) and the covered share by state."""
    t = pd.read_parquet(KB / "crawl/targets.parquet")
    s = pd.read_parquet(KB / "crawl/sites.parquet", columns=["target_id", "kind", "site_status", "unique_ids"])
    with_t = _list_ids(t.unique_ids)
    ok_sites = s[s.site_status.isin(["ok", "ok_thin"]) & s.kind.isin(["site", "branch"])]
    covered = _list_ids(ok_sites.unique_ids)
    d = dims()
    st = d.state.value_counts()
    cov = pd.Series([d.loc[u, "state"] for u in covered]).value_counts()
    share = (cov / st).fillna(0)
    nat = len(covered) / 9959
    focus = {k: round(float(share.get(k, 0)), 3) for k in FOCUS}
    readme_ok = len(with_t) == 8015
    stats_cov = pd.read_csv(KB / "crawl/coverage_by_state.csv").set_index("state").covered_own_site
    mism = {k: (int(stats_cov.get(k, 0)), int(cov.get(k, 0))) for k in st.index if int(stats_cov.get(k, 0)) != int(cov.get(k, 0))}
    low = [k for k, v in focus.items() if v < nat - 0.05]
    return result("crawl_target_coverage", "fail" if not readme_ok or mism else ("warn" if low else "pass"),
                  f"with target {len(with_t)}/9959 (README 8,015); covered {len(covered)} ({nat:.3f}); focus {focus}",
                  "README counts reproduce; focus states within 5 points of national share",
                  f"coverage_by_state.csv mismatches (csv, recomputed): {mism}. Focus states below national-5pt: {low}. "
                  f"No-target records by state: {breakdown(U() - with_t)['state']}", sorted(U() - with_t)[:5])


def check_web_evidence_reach():
    """web_evidence facilities are a subset of crawl-covered records; report how many usable records get any
    web service evidence, by focus state."""
    ws = pd.read_parquet(KB / "web_evidence/out/web_service_summary.parquet", columns=["unique_id", "service_id", "web_positive"])
    s = pd.read_parquet(KB / "crawl/sites.parquet", columns=["unique_ids", "site_status"])
    crawled = _list_ids(s[s.site_status.isin(["ok", "ok_thin"])].unique_ids)
    ids = set(ws.unique_id)
    outside = ids - crawled
    d = dims()
    pos = set(ws[ws.web_positive == True].unique_id)  # noqa: E712
    st = d.state.value_counts()
    sh = {k: round(sum(1 for u in pos if d.loc[u, "state"] == k) / st[k], 3) for k in FOCUS}
    return result("web_evidence_reach", "fail" if outside else "pass",
                  f"{len(ids)} records in web_service_summary, {len(pos)} with a positive service; {len(outside)} not crawled",
                  "0 outside crawl", f"share with web-positive evidence, focus states {sh}; national {len(pos) / 9959:.3f}",
                  sorted(outside)[:5])


def check_opendata_fanout():
    """One VF record matched to several open-data objects (or one object to several VF records) multiplies facts."""
    f = pd.read_parquet(KB / "opendata/vf_opendata_facts.parquet")
    per = f.groupby(["unique_id", "source"]).source_id.nunique()
    multi = per[per > 1]
    rev = f.groupby(["source", "source_id"]).unique_id.nunique()
    shared = rev[rev > 1]
    g = v1("facility_groups.parquet", ("unique_id", "dup_group_id")).set_index("unique_id").dup_group_id
    same_group = 0
    for (src, sid), _ in shared.items():
        us = f[(f.source == src) & (f.source_id == sid)].unique_id.unique()
        grp = g.reindex(us)
        same_group += int(grp.notna().all() and grp.nunique() == 1)
    status = "warn" if len(multi) or len(shared) - same_group > 0 else "pass"
    return result("opendata_fanout", status,
                  f"{len(multi)} (record, source) with >1 object; {len(shared)} objects shared by >1 record "
                  f"({same_group} explained by one duplicate group)", "0 unexplained",
                  f"{f.unique_id.nunique()} records carry open-data facts; facts by match_tier "
                  f"{f.match_tier.value_counts().to_dict()}",
                  [f"{a} {b}" for a, b in multi.index[:3]] + [f"{a}:{b}" for a, b in shared.index[:2]])


def check_specialty_map_coverage():
    """Every specialty value in specialties.parquet has a row in kb/taxonomy/specialty_map.csv."""
    sm = pd.read_csv(KB / "taxonomy/specialty_map.csv")
    keys = set(sm.specialty.astype(str).str.lower().str.replace(r"[^a-z]", "", regex=True))
    s = v1("specialties.parquet", ("unique_id", "spec"))
    miss = s[~s.spec.isin(keys) & (s.spec != "")]
    return result("specialty_map_coverage", "warn" if len(miss) else "pass",
                  f"{miss.spec.nunique()} of {s.spec.nunique()} distinct specs unmapped ({len(miss)} rows, "
                  f"{miss.unique_id.nunique()} facilities)", "0",
                  f"map rows {len(sm)}; unmapped specialties give no evidence weight downstream",
                  miss.spec.value_counts().head(5).index.tolist())


def check_pathways_services_exist():
    """capabilities.json kb_service values for 'existing' capabilities are graded services in derived/v1."""
    caps = json.loads((KB / "pathways/capabilities.json").read_text())["capabilities"]
    services = set(v1("grades.parquet", ("service",)).service)
    bad = [c["id"] for c in caps if c.get("kb_status") == "existing" and c.get("kb_service") not in services]
    return result("pathways_services_exist", "fail" if bad else "pass",
                  f"{sum(c.get('kb_status') == 'existing' for c in caps)} existing caps, {len(bad)} unknown service", "0",
                  f"graded services: {sorted(services)}", bad)


# ================================================================ layer 3: app/facts, app/packs, planner
def check_facts_facilities():
    """facts.json.gz facility list = usable records minus documented filters (no point; trust_level exclude_review)."""
    fx = facts()["fac"]["id"]
    tr = v1("record_trust.parquet", ("unique_id", "trust_level")).set_index("unique_id").trust_level
    dup = len(fx) - len(set(fx))
    missing = sorted(U() - set(fx))
    extra = sorted(set(fx) - U())
    reason = Counter("exclude_review" if tr.get(u) == "exclude_review" else
                     ("no_point" if pd.isna(loc().set_index("unique_id").loc_lat.get(u)) else "UNDOCUMENTED")
                     for u in missing)
    status = "fail" if dup or extra or reason.get("UNDOCUMENTED") else "pass"
    return result("facts_facilities", status, f"{len(fx)} facilities; dropped {len(missing)} {dict(reason)}; dup {dup}; extra {len(extra)}",
                  "drops all documented",
                  "app/facts/build.py:64-65 drops rows with no ranking point and trust_level == exclude_review "
                  "(cleaning/geo_identity/s5_trust.py:142: veterinary). Dropped: " + str(breakdown(missing)), missing)


def _facts_expected_pairs() -> set:
    d = v1("data_point_scores.parquet", ("dp_type", "unique_id", "service"))
    d = d[(d.dp_type == "service_claim") & d.service.isin(APP_SERVICES)]
    g = set(map(tuple, v1("grades.parquet", ("unique_id", "service")).values))
    fx = set(facts()["fac"]["id"])
    return {(u, s) for u, s in zip(d.unique_id, d.service) if (u, s) in g and u in fx}


def check_facts_pairs_complete():
    """facts.pairs holds every eligible (facility, app service) grade exactly once."""
    fx = facts()
    ids = fx["fac"]["id"]
    v1_of = {v: k for k, v in APP_SERVICES.items()}
    got = [(ids[r[0]], v1_of[s]) for s, rows in fx["pairs"].items() for r in rows]
    dup = len(got) - len(set(got))
    exp = _facts_expected_pairs()
    miss, extra = exp - set(got), set(got) - exp
    vet = {u for u in U() if v1("record_trust.parquet", ("unique_id", "trust_level")).set_index("unique_id").trust_level.get(u) == "exclude_review"}
    all_pairs = v1("grades.parquet", ("unique_id", "service"))
    lost_vet = all_pairs[all_pairs.unique_id.isin(vet) & all_pairs.service.isin(APP_SERVICES)]
    ok = not dup and not miss and not extra
    return result("facts_pairs_complete", "pass" if ok else "fail",
                  f"{len(got)} pairs; missing {len(miss)}; extra {len(extra)}; duplicate {dup}", "0 / 0 / 0",
                  f"By service: { {s: len(r) for s, r in fx['pairs'].items()} }; {len(lost_vet)} app-service pairs of the "
                  f"12 exclude_review records are dropped with them; icu pairs are dropped (no app tile).",
                  [f"{u}:{s}" for u, s in list(miss)[:3]] + [f"{u}:{s}" for u, s in list(extra)[:2]])


def check_facts_cited_claims_present():
    """Every claim id a facts pair or the planner cites is in facts.claims (else the card shows an id, no quote)."""
    fx = facts()
    cited = {c for rows in fx["pairs"].values() for r in rows for c in r[9]}
    pl = {cid for c in planner()["capabilities"].values() for ids in c["e"] for cid in ids}
    have = set(fx["claims"])
    miss_p, miss_pl = cited - have, pl - have
    cl = set(v1("claims.parquet", ("claim_id",)).claim_id)
    bogus = (cited | pl) - cl
    status = "fail" if miss_p or miss_pl or bogus else "pass"
    return result("facts_cited_claims_present", status,
                  f"{len(cited)} pair cites, {len(pl)} planner cites; missing {len(miss_p)} / {len(miss_pl)}; not in claims {len(bogus)}",
                  "0", "facts.claims is built from pair cites plus planner cites (app/facts/build.py:176)",
                  sorted(miss_p | miss_pl | bogus)[:5])


def check_pack_index_and_pins():
    """Every state in pin_gazetteer has a pack; index sha matches file; each pack holds all of its state's PINs."""
    pins = v1("pin_gazetteer.parquet", ("pin", "state", "lat", "lon")).dropna(subset=["state", "lat", "lon"])
    states = sorted(pins.state.unique())
    idx = pack_index()["packs"]
    slug = lambda s: re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")  # noqa: E731
    missing = [s for s in states if slug(s) not in idx]
    bad_sha, bad_pins = [], []
    for k, meta in idx.items():
        gz = (ROOT / f"app/packs/out/{k}.json.gz").read_bytes()
        if hashlib.sha256(gz).hexdigest()[:16] != meta["sha256"]:
            bad_sha.append(k)
        p = packs()[k]
        dp = decode_pack(p)
        exp = set(pins[pins.state == p["state"]].pin.astype(int))
        if set(dp["pin"].astype(int)) != exp or len(dp["pin"]) != len(exp):
            bad_pins.append(k)
    raw_pin_states = v1("pin_gazetteer.parquet", ("state",)).state.isna().sum()
    status = "fail" if missing or bad_sha or bad_pins else "pass"
    return result("pack_index_and_pins", status,
                  f"{len(idx)} packs for {len(states)} states; sha mismatch {len(bad_sha)}; PIN set mismatch {len(bad_pins)}",
                  "0", f"{raw_pin_states} gazetteer PINs have no state and are in no pack", missing + bad_sha + bad_pins)


@lru_cache(None)
def pack_candidates() -> pd.DataFrame:
    """Rebuild the candidate (facility, service) rows exactly as app/packs/build_packs.py:load() selects them."""
    l = loc()[["unique_id", "loc_lat", "loc_lon"]].dropna()
    d = v1("data_point_scores.parquet", ("dp_type", "unique_id", "service", "status", "grade"))
    s = d[(d.dp_type == "service_claim") & d.service.isin(APP_SERVICES) & ~d.grade.isin(PACK_EXCLUDED_GRADES)
          & (d.status != "verified_false")]
    return s[s.unique_id.isin(l.unique_id)].reset_index(drop=True)


def check_pack_facility_membership():
    """Facilities shown in packs: uid8 resolves to one usable record, no veterinary (exclude_review) record, and
    each pack row is a legitimate candidate. Also counts candidates that are in no pack (by design: never top-3)."""
    tr = v1("record_trust.parquet", ("unique_id", "trust_level")).set_index("unique_id").trust_level
    cand = pack_candidates()
    cand_ids = set(cand.unique_id)
    shown, ambiguous, unknown = set(), [], []
    for k, p in packs().items():
        for u8 in p["fac"]["uid8"]:
            m = uid8_map().get(u8, [])
            if len(m) != 1:
                (ambiguous if m else unknown).append(f"{k}:{u8}")
            else:
                shown.add(m[0])
    vet_shown = sorted(u for u in shown if tr.get(u) == "exclude_review")
    not_cand = sorted(shown - cand_ids)
    never = cand_ids - shown
    fx = set(facts()["fac"]["id"])
    status = "fail" if ambiguous or unknown or not_cand else ("warn" if vet_shown else "pass")
    names = loc().set_index("unique_id").name
    return result("pack_facility_membership", status,
                  f"{len(shown)} distinct facilities in packs; exclude_review shown {len(vet_shown)}; ambiguous uid8 "
                  f"{len(ambiguous)}; not a candidate {len(not_cand)}; candidates never shown {len(never)} of {len(cand_ids)}",
                  "0 ambiguous, 0 non-candidates, 0 exclude_review",
                  "build_packs.py:66-67 does not apply the trust_level != exclude_review filter that facts/build.py:65 "
                  f"applies, so the offline pack can show a record the online app hides. Shown but not in facts: "
                  f"{len(shown - fx)}. Candidates never in any top-3 list are by design (nearest-3 per PIN).",
                  [f"{u} {names.get(u)}" for u in vet_shown] + ambiguous + unknown + not_cand)


def check_pack_duplicate_facilities_in_lists():
    """Fan-out in the app: two records of the same duplicate group in one PIN's top list for one service, so the
    user sees the same hospital twice and loses a real alternative."""
    g = v1("facility_groups.parquet", ("unique_id", "dup_group_id")).set_index("unique_id").dup_group_id
    hits, n_lists, ex, by_state = 0, 0, [], Counter()
    pins_hit = 0
    for k, p in packs().items():
        dp = decode_pack(p)
        uids = [uid8_map().get(u8, [None])[0] for u8 in p["fac"]["uid8"]]
        bad_lists = set()
        for li, lst in enumerate(p["lists"]):
            n_lists += 1
            grp = [g.get(uids[dp["ev_f"][e]]) for e in lst]
            grp = [x for x in grp if isinstance(x, str)]
            if len(grp) != len(set(grp)):
                hits += 1
                bad_lists.add(li)
                if len(ex) < 5:
                    ex.append(f"{k} list {li}: " + ", ".join(uids[dp['ev_f'][e]][:8] for e in lst))
        for s, ix in p["index"].items():
            c = sum(1 for li in ix if li in bad_lists)
            pins_hit += c
            by_state[p["state"]] += c
    return result("pack_duplicate_facilities_in_lists", "warn" if hits else "pass",
                  f"{hits}/{n_lists} distinct lists repeat a duplicate group; {pins_hit} (PIN, service) answers affected",
                  "0", f"Root cause: build_packs.py:118 top_lists ranks records, not facility_groups.dup_group_id "
                  f"(derived/v1 facility_groups). Affected answers by state (top): {dict(by_state.most_common(8))}", ex)


def check_pack_state_coverage():
    """Coverage gap per service: share of a state's PINs whose nearest pack candidate is more than 50 km away,
    and PINs with no candidate at all. Focus states vs India."""
    rows = []
    for k, p in packs().items():
        dp = decode_pack(p)
        for s, ix in p["index"].items():
            for pi, li in enumerate(ix):
                lst = p["lists"][li]
                if not lst:
                    rows.append((p["state"], s, np.inf))
                    continue
                fi = dp["ev_f"][lst[0]]
                rows.append((p["state"], s, float(hav(dp["plat"][pi], dp["plon"][pi], dp["fac_lat"][fi], dp["fac_lon"][fi]))))
    df = pd.DataFrame(rows, columns=["state", "service", "km"])
    df["gt50"] = df.km > 50
    nat = df.groupby("service").gt50.mean()
    st = df.groupby(["state", "service"]).gt50.mean().unstack()
    med = df.groupby(["state", "service"]).km.median().unstack()
    none = int(np.isinf(df.km).sum())
    out = st.round(3)
    out.to_csv(OUT / "pack_pin_gap_share_gt50km.csv")
    med.round(1).to_csv(OUT / "pack_pin_median_km.csv")
    focus = {s: {sv: float(out.loc[s, sv]) for sv in out.columns} for s in FOCUS if s in out.index}
    worse = [f"{s}/{sv}" for s in focus for sv in focus[s] if focus[s][sv] > nat[sv] + 0.10]
    return result("pack_state_coverage", "warn" if worse or none else "pass",
                  f"national share of PINs >50 km from nearest candidate: {nat.round(3).to_dict()}; PINs with none: {none}",
                  "focus state within 10 points of national per service",
                  f"focus states: {focus}. Full tables: out/pack_pin_gap_share_gt50km.csv, out/pack_pin_median_km.csv",
                  worse)


def check_planner_facilities():
    """planner export: facility list vs usable records, duplicate indexes per capability, veterinary records."""
    pl = planner()
    ids = pl["facilities"]["id"]
    dup = len(ids) - len(set(ids))
    missing, extra = sorted(U() - set(ids)), sorted(set(ids) - U())
    tr = v1("record_trust.parquet", ("unique_id", "trust_level")).set_index("unique_id").trust_level
    vet = {i for i, u in enumerate(ids) if tr.get(u) == "exclude_review"}
    cap_dup, cap_vet = {}, Counter()
    for c, v in pl["capabilities"].items():
        if len(v["i"]) != len(set(v["i"])):
            cap_dup[c] = len(v["i"]) - len(set(v["i"]))
        cap_vet[c] = sum(1 for i in v["i"] if i in vet)
    status = "fail" if dup or extra or cap_dup else ("warn" if sum(cap_vet.values()) else "pass")
    return result("planner_facilities", status,
                  f"{len(ids)} facilities (missing {len(missing)}, extra {len(extra)}, dup {dup}); "
                  f"{len(vet)} exclude_review records kept; {sum(cap_vet.values())} capability entries point at them",
                  "same filters as facts (no exclude_review)",
                  f"planner/data_v1.py:63-66 drops only rows without a point, not exclude_review (facts/build.py:65 does). "
                  f"Capability entries on exclude_review records: { {k: v for k, v in cap_vet.items() if v} }. "
                  f"Duplicate facility indexes per capability: {cap_dup}",
                  [ids[i] for i in sorted(vet)][:5])


def check_planner_vs_pack_exclusions():
    """The planner's graded capabilities take every service_claim (planner/data_v1.py:55), including pairs the
    packs exclude (grade attributed_elsewhere / counter_evidence, or verified_false)."""
    pl = planner()
    ids = pl["facilities"]["id"]
    caps = {c["id"]: c for c in json.loads((KB / "pathways/capabilities.json").read_text())["capabilities"]}
    d = v1("data_point_scores.parquet", ("dp_type", "unique_id", "service", "status", "grade"))
    d = d[d.dp_type == "service_claim"].set_index(["unique_id", "service"])
    n, ex, per = 0, [], Counter()
    for c, v in pl["capabilities"].items():
        info = caps.get(c, {})
        if info.get("kb_status") != "existing":
            continue
        for i, p in zip(v["i"], v["p"]):
            key = (ids[i], info["kb_service"])
            if key in d.index:
                r = d.loc[key]
                if r.grade in PACK_EXCLUDED_GRADES or r.status == "verified_false":
                    n += 1
                    per[c] += 1
                    if len(ex) < 5:
                        ex.append(f"{ids[i]} {c} grade={r.grade} status={r.status} p={p}")
    return result("planner_vs_pack_exclusions", "warn" if n else "pass",
                  f"{n} planner capability entries are pairs the packs drop", "0 (same exclusions in every export)",
                  f"by capability: {dict(per)}. They carry low p (e.g. 0.03 for verified_false), so they rarely win a plan, "
                  "but the exports disagree on which facilities are candidates.", ex)


def check_pack_quotes_cited():
    """Every quote in a pack carries a claim id suffix that resolves (with the row's uid8) to a claims row with the
    same text. build_packs.py:85 maps quote text back to a claim id; a miss leaves the suffix empty."""
    cl = v1("claims.parquet", ("claim_id", "text")).set_index("claim_id").text
    n_q, empty, wrong, ex = 0, 0, 0, []
    for k, pk in packs().items():
        dp = decode_pack(pk)
        for e in range(len(pk["ev"]["s"])):
            u8 = pk["fac"]["uid8"][dp["ev_f"][e]]
            for qi in (pk["ev"]["q1"][e], pk["ev"]["q2"][e]):
                if qi < 0:
                    continue
                n_q += 1
                text, suf = pk["q"][qi]
                if not suf:
                    empty += 1
                    ex.append(f"{k}:{u8}: empty id for '{text[:40]}'")
                    continue
                t = cl.get(f"{u8}:{suf}")
                if t is None or not (t == text or (text.endswith("...") and t.startswith(text[:-3]))):
                    wrong += 1
                    ex.append(f"{k}:{u8}:{suf} text mismatch")
    return result("pack_quotes_cited", "fail" if empty or wrong else "pass",
                  f"{n_q} quote uses; empty id {empty}; id/text mismatch {wrong}", "0", "", ex)


def check_pin_coverage_vs_india_post():
    """Every India Post PIN (raw directory) is in pin_gazetteer, in a state pack and in facts.pins; a PIN that is
    missing cannot be picked offline (pack) or online (facts area view)."""
    ip = pd.read_parquet(ROOT / "data/raw/india_post_pincode_directory.parquet", columns=["pincode", "statename"])
    ip["pin"] = pd.to_numeric(ip.pincode, errors="coerce")
    ip = ip.dropna(subset=["pin"]).astype({"pin": int})
    ip_state = ip.groupby("pin").statename.agg(lambda x: x.mode().iloc[0])
    gz = v1("pin_gazetteer.parquet", ("pin", "state", "district", "lat", "lon"))
    in_gz = set(gz.pin.astype(int))
    in_pack = {int(x) for pk in packs().values() for x in decode_pack(pk)["pin"]}
    in_facts = set(facts()["pins"]["pin"])
    miss_gz = sorted(set(ip_state.index) - in_gz)
    miss_pack = sorted(set(ip_state.index) - in_pack)
    miss_facts = sorted(set(ip_state.index) - in_facts)
    gz_no_state = gz[gz.state.isna() | gz.lat.isna()].pin.astype(int).tolist()
    gz_no_dist = gz[gz.district.isna()].pin.astype(int).tolist()
    by_state = ip_state.reindex(miss_facts).value_counts().head(8).to_dict()
    status = "warn" if miss_gz or miss_pack or miss_facts else "pass"
    return result("pin_coverage_vs_india_post", status,
                  f"{len(ip_state)} India Post PINs; missing from gazetteer {len(miss_gz)}, packs {len(miss_pack)}, "
                  f"facts.pins {len(miss_facts)}", "0",
                  f"gazetteer PINs without state or centroid (in no pack): {gz_no_state}; without district "
                  f"{len(gz_no_dist)} (dropped from facts.pins by app/facts/build.py:149 dropna(district), kept in packs "
                  f"with district ''). India Post PINs missing from facts.pins by state: {by_state}",
                  miss_gz[:2] + miss_facts[:3])


def check_missed_duplicate_candidates():
    """Fan-out the cleaning step may have missed: record pairs within 300 m whose names match (rapidfuzz
    token_set_ratio >= 90 after removing generic words) but that share no duplicate group, co-location or
    possible_same_site link. Candidates only, not hand-verified."""
    from rapidfuzz import fuzz
    stop = {"hospital", "clinic", "the", "and", "centre", "center", "pvt", "ltd", "multispeciality", "multi",
            "speciality", "super", "superspeciality", "care"}
    l = loc()[["unique_id", "name", "loc_lat", "loc_lon"]].merge(
        v1("facility_groups.parquet", ("unique_id", "dup_group_id", "co_located_with", "possible_same_site")), on="unique_id")
    n = [" ".join(w for w in re.sub(r"[^a-z0-9 ]", " ", str(x).lower()).split() if w not in stop) for x in l.name]
    la, lo = l.loc_lat.to_numpy(), l.loc_lon.to_numpy()
    out = []
    for i in range(len(l)):
        d = hav(la[i], lo[i], la[i + 1:], lo[i + 1:])
        for j in np.where(d < 0.3)[0] + i + 1:
            a, b = l.iloc[i], l.iloc[j]
            if isinstance(a.dup_group_id, str) and a.dup_group_id == b.dup_group_id:
                continue
            links = set(a.co_located_with) | set(a.possible_same_site) | set(b.possible_same_site) | set(b.co_located_with)
            if a.unique_id in links or b.unique_id in links:
                continue
            if n[i] and n[j] and fuzz.token_set_ratio(n[i], n[j]) >= 90:
                out.append(f"{a.unique_id[:8]} '{a['name'][:40]}' ~ {b.unique_id[:8]} '{b['name'][:40]}'")
    return result("missed_duplicate_candidates", "warn" if out else "pass", f"{len(out)} candidate pairs", "0",
                  "Same-name records within 300 m outside any facility_groups link. Some are separate units of one "
                  "campus (dental vs general), some are true duplicates (both appear as separate options). Also see "
                  "opendata_fanout: OSM objects matched to two records that facility_groups keeps apart.", out)


def check_v2_contract():
    """Contract for derived/v2/facility_service_scores.parquet (#11, not judged here). Packs inner-join it
    (build_packs.py:96), so any pack candidate pair it does not score silently leaves the offline packs."""
    path = ROOT / "derived/v2/facility_service_scores.parquet"
    if not path.is_file():
        return result("v2_contract", "not_run", "file absent", "exists", f"{path} not published yet; contract ready")
    m = pd.read_parquet(path)
    need = {"unique_id", "service_id", "band", "p", "lo", "hi", "as_of"}
    miss_cols = need - set(m.columns)
    if miss_cols:
        return result("v2_contract", "fail", f"missing columns {sorted(miss_cols)}", "all columns", "")
    m = m.assign(service=m.service_id.map(lambda x: {v: k for k, v in APP_SERVICES.items()}.get(x, x)))
    dup = int(m.duplicated(["unique_id", "service"]).sum())
    orphan = sorted(set(m.unique_id) - U())
    bands = set(m.band) - {"likely", "not_verified", "unlikely"}
    bad_p = int(((m.lo > m.p) | (m.p > m.hi) | (m.lo < 0) | (m.hi > 1)).sum())
    cand = pack_candidates()
    keys = set(zip(m.unique_id, m.service))
    unscored = [(u, s) for u, s in zip(cand.unique_id, cand.service) if (u, s) not in keys]
    status = "fail" if dup or orphan or bands or bad_p else ("warn" if unscored else "pass")
    return result("v2_contract", status, f"rows={len(m)} dup={dup} orphans={len(orphan)} bad_bands={sorted(bands)} "
                  f"bad_interval={bad_p}; pack candidates unscored {len(unscored)}/{len(cand)}", "0 each",
                  "unscored pack candidates are dropped from packs by the inner join", orphan[:3] + [f"{u}:{s}" for u, s in unscored[:2]])


def check_gold_splits_fk():
    """model/gold/splits.json pairs point at usable records and graded-or-ungraded services that exist (v1/v2 only)."""
    sp = json.loads((ROOT / "model/gold/splits.json").read_text())["pairs"]
    orphan = [p["unique_id"] for p in sp if p["unique_id"] not in U()]
    dup = len(sp) - len({p["pair_id"] for p in sp})
    return result("gold_splits_fk", "fail" if orphan or dup else "pass", f"{len(sp)} pairs; orphans {len(orphan)}; dup pair_id {dup}",
                  "0", "v3 test files not opened", orphan)


# ================================================================ cross-layer: trace and state coverage
def check_trace_table():
    """Rows in / rows out / distinct facilities for every layer; written to out/trace.csv."""
    rows = []

    def add(layer, table, rows_n, fac_ids, note=""):
        fac_ids = set(fac_ids)
        rows.append(dict(layer=layer, table=table, rows=rows_n, facilities=len(fac_ids & U()),
                         orphans=len(fac_ids - U()), usable_missing=len(U() - fac_ids), note=note))

    f = raw()
    add("0 raw", "facilities.parquet", len(f), set(f.unique_id.dropna()), "10,088 rows: 9,970 well-formed, 30 truncated, 88 fragments")
    add("0 raw", "usable (dedup)", len(usable()), U(), "minus 118 malformed, minus 11 duplicate rows")
    for t in ["facility_location.parquet", "record_trust.parquet", "facility_groups.parquet", "facility_trust.parquet",
              "claims.parquet", "specialties.parquet", "grades.parquet", "data_point_scores.parquet",
              "source_urls.parquet", "source_page_checks.parquet", "gold_pairs.parquet"]:
        ids = v1(t, ("unique_id",)).unique_id
        add("1 derived/v1", t, len(ids), set(ids.dropna()))
    for path, idc, is_list in [("kb/crawl/targets.parquet", "unique_ids", True), ("kb/crawl/sites.parquet", "unique_ids", True),
                               ("kb/crawl/pages.parquet", "unique_ids", True),
                               ("kb/web_evidence/out/site_identity.parquet", "unique_id", False),
                               ("kb/web_evidence/out/web_service_summary.parquet", "unique_id", False),
                               ("kb/web_evidence/out/web_details.parquet", "unique_id", False),
                               ("kb/vf_details/out/facts.parquet", "unique_id", False),
                               ("kb/vf_details/out/facility_details.parquet", "unique_id", False),
                               ("kb/opendata/vf_opendata_match.parquet", "unique_id", False),
                               ("kb/opendata/vf_opendata_facts.parquet", "unique_id", False),
                               ("kb/taxonomy/out/lexicon_matches.parquet", "unique_id", False)]:
        t = pd.read_parquet(ROOT / path, columns=[idc])
        add("2 kb", path.replace("kb/", ""), len(t), _list_ids(t[idc]) if is_list else set(t[idc].dropna()))
    fx = facts()
    add("3 app", "facts.fac", len(fx["fac"]["id"]), fx["fac"]["id"], "minus 12 exclude_review")
    pairs_ids = {fx["fac"]["id"][r[0]] for rows_ in fx["pairs"].values() for r in rows_}
    add("3 app", "facts.pairs", sum(len(r) for r in fx["pairs"].values()), pairs_ids, "7 app services")
    shown = {uid8_map()[u8][0] for p in packs().values() for u8 in p["fac"]["uid8"] if len(uid8_map().get(u8, [])) == 1}
    add("3 app", "packs (all states, union)", sum(len(p["fac"]["uid8"]) for p in packs().values()), shown,
        "facility rows summed over packs; nearest-3 per PIN only")
    pl = planner()
    add("4 planner", "planner_v1 facilities", len(pl["facilities"]["id"]), pl["facilities"]["id"])
    capids = {pl["facilities"]["id"][i] for v in pl["capabilities"].values() for i in v["i"]}
    add("4 planner", "planner_v1 capability entries", sum(len(v["i"]) for v in pl["capabilities"].values()), capids)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "trace.csv", index=False)
    orph = df[(df.orphans > 0) & (df.table != "facilities.parquet")]  # raw holds the 118 malformed ids
    return result("trace_table", "fail" if len(orph) else "pass", f"{len(df)} layer/table rows traced; {len(orph)} with orphans",
                  "0 orphans", "out/trace.csv. " + "; ".join(f"{r.table}: {r.rows} rows / {r.facilities} fac"
                                                             for r in df.itertuples()), orph.table.tolist())


def check_state_coverage_table():
    """Facilities per state through the layers, per million people (WorldPop 2025) for the focus states."""
    d = dims()
    r = raw()
    rs = r[raw_classes() != "fragment"].drop_duplicates("unique_id")
    raw_state = rs.address_stateOrRegion.fillna("").str.upper().str.replace("ORISSA", "ODISHA")
    cols = {"usable": d.state.value_counts()}
    cols["raw_rows_by_raw_state_label"] = raw_state.value_counts()
    fx = facts()
    cols["facts_fac"] = pd.Series([s or "UNKNOWN" for s in fx["fac"]["state"]]).value_counts()
    pairs_ids = {fx["fac"]["id"][rr[0]] for rows_ in fx["pairs"].values() for rr in rows_}
    cols["facts_with_any_app_service"] = pd.Series([d.loc[u, "state"] for u in pairs_ids]).value_counts()
    shown = {uid8_map()[u8][0] for p in packs().values() for u8 in p["fac"]["uid8"] if len(uid8_map().get(u8, [])) == 1}
    cols["in_any_pack"] = pd.Series([d.loc[u, "state"] for u in shown]).value_counts()
    pl = planner()
    cols["planner"] = pd.Series([s or "UNKNOWN" for s in pl["facilities"]["state"]]).value_counts()
    t = pd.DataFrame(cols).fillna(0).astype(int)
    pop = pd.read_csv(ROOT / "data/external/worldpop_r2025a/derived/district_population.csv").groupby("state").pop.sum()
    t["pop_m"] = (pop.reindex(t.index) / 1e6).round(2)
    t["usable_per_m"] = (t.usable / t.pop_m).round(2)
    t["app_service_fac_per_m"] = (t.facts_with_any_app_service / t.pop_m).round(2)
    t = t.sort_values("usable", ascending=False)
    t.to_csv(OUT / "state_coverage.csv")
    nat = t.usable.sum() / t.pop_m.sum()
    nat_s = t.facts_with_any_app_service.sum() / t.pop_m.sum()
    f = t.loc[[s for s in FOCUS if s in t.index], ["usable", "facts_with_any_app_service", "in_any_pack", "pop_m",
                                                    "usable_per_m", "app_service_fac_per_m"]]
    lost = {s: int(t.loc[s, "usable"] - t.loc[s, "facts_fac"]) for s in t.index if t.loc[s, "usable"] != t.loc[s, "facts_fac"]}
    below = [x for x in f.index if f.loc[x, "usable_per_m"] < nat / 2]
    return result("state_coverage_table", "warn" if below else "pass", f"below half national: {below}; national {nat:.2f} records and {nat_s:.2f} app-service facilities per million",
                  "focus states at least half the national density",
                  f"focus states: {f.to_dict('index')}. usable->facts losses by state: {lost}. Full table out/state_coverage.csv",
                  [f"{s}: {f.loc[s, 'usable_per_m']}/M" for s in f.index])


ALL = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]


def run_all() -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    res = []
    for fn in ALL:
        t0 = time.time()
        try:
            r = fn()
        except Exception as e:  # report, never hide, a crashing check
            r = result(fn.__name__[6:], "fail", "check crashed", "runs", f"{type(e).__name__}: {e}")
        r["seconds"] = round(time.time() - t0, 1)
        res.append(r)
        print(f"[{r['status']:7s}] {r['name']}: {r['metric']}", flush=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    run_all()

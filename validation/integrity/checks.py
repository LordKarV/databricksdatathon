"""Schema, keys and referential-integrity checks for the Referral Saathi data layers.

Every check_<name>() returns dict(name, status in pass|warn|fail, metric, threshold, detail, examples).
All checks are read-only. Run the suite with: .venv-viz/bin/python validation/integrity/run.py
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import (LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, OUT, PRIMARY_KEYS, RAW, ROOT, UUID_RE, V1, claim_ids,
                    claim_text, claims, duck, is_null_like, jload, nrows, raw, raw_ids, result, scope_files, sha256,
                    table, tabular_files, uid8_map, usable, usable_ids, wilson, worst)

CLAIM_RE = re.compile(r"^([0-9a-f]{8}):(proc|capa|equi|desc):(\d+)$")
FIELD4 = {"proc": "procedure", "capa": "capability", "equi": "equipment", "desc": "description"}


def _in_india(lat, lon) -> np.ndarray:
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return (lat >= LAT_MIN) & (lat <= LAT_MAX) & (lon >= LON_MIN) & (lon <= LON_MAX)


# ----------------------------------------------------------------------------------------------- manifests


def check_raw_hashes_unchanged() -> dict:
    """data/raw files hash to what derived/v1/MANIFEST.json recorded as its raw inputs."""
    m = jload("derived/v1/MANIFEST.json")["raw_input_sha256"]
    bad = [f"{f}: manifest {h[:12]} disk {sha256(RAW / f)[:12]}" for f, h in m.items() if sha256(RAW / f) != h]
    return result("raw_hashes_unchanged", "fail" if bad else "pass", f"{len(m) - len(bad)}/{len(m)} match",
                  "all match", "sha256 of data/raw/* vs derived/v1 MANIFEST raw_input_sha256", bad)


def check_raw_manifest_aggregates() -> dict:
    """Recompute the 345 aggregate checks of data/raw/MANIFEST.json (count, non-null count, sum of string lengths,
    rounded numeric sums) on the local parquet files with DuckDB."""
    m = jload("data/raw/MANIFEST.json")
    con, bad, n = duck(), [], 0
    for t, spec in m["tables"].items():
        f = RAW / spec["file"]
        cols = list(spec["schema"])
        sel = []
        for k in spec["checks"]:
            if k == "rows":
                sel.append('count(*) AS "rows"')
            else:
                op, c = k.split("__", 1)
                expr = {"nn": f'count("{c}")', "len": f'sum(length("{c}"))', "sum": f'round(sum("{c}"), 3)'}[op]
                sel.append(f'{expr} AS "{k}"')
        got = con.sql(f"SELECT {', '.join(sel)} FROM '{f}'").df().iloc[0]
        for k, v in spec["checks"].items():
            n += 1
            w, loc = v["warehouse"], got[k]
            if k.startswith("sum__"):  # rounded to 3 dp on both sides; allow float summation-order noise
                same = abs(float(loc) - float(w)) <= 0.002 + 1e-12 * abs(float(w))
            else:
                same = not pd.isna(loc) and int(loc) == int(w) if w not in (None, "") else pd.isna(loc)
            if not same:
                bad.append(f"{t}.{k}: warehouse {w} local {loc}")
        if len(cols) != spec["columns"]:
            bad.append(f"{t}: schema lists {len(cols)} columns, manifest says {spec['columns']}")
        got_rows = pq.ParquetFile(f).metadata.num_rows
        if got_rows != spec["rows"]:
            bad.append(f"{t}: rows {got_rows} vs {spec['rows']}")
    return result("raw_manifest_aggregates", "fail" if bad else "pass", f"{n - len(bad)}/{n} checks reproduce",
                  "all reproduce", "data/raw/MANIFEST.json warehouse values recomputed locally", bad)


def check_raw_live_warehouse() -> dict:
    """One aggregate query on the live Marketplace table: row count, distinct ids and three length sums."""
    q = ("SELECT count(*) n, count(DISTINCT unique_id) d, sum(length(unique_id)) lu, sum(length(name)) ln, "
         "sum(length(source_urls)) ls, round(sum(latitude),3) slat FROM "
         "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities")
    live = None
    for _ in range(3):  # transient network errors are retried
        try:
            r = subprocess.run([str(ROOT / "sql.sh"), q], capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and "\n" in r.stdout:
                live = dict(zip(*[x.split("\t") for x in r.stdout.strip().splitlines()[:2]]))
                break
        except (subprocess.TimeoutExpired, OSError):
            pass
    if live is None:
        return result("raw_live_warehouse", "warn", "not run", "live == local", "sql.sh failed 3 times")
    loc = duck().sql(f"SELECT count(*) n, count(DISTINCT unique_id) d, sum(length(unique_id)) lu, "
                     f"sum(length(name)) ln, sum(length(source_urls)) ls, round(sum(latitude),3) slat "
                     f"FROM '{RAW / 'facilities.parquet'}'").df().iloc[0]
    bad = [f"{k}: live {live[k]} local {loc[k]}" for k in live if abs(float(live[k]) - float(loc[k])) > 0.002]
    return result("raw_live_warehouse", "fail" if bad else "pass", f"{len(live) - len(bad)}/{len(live)} equal",
                  "all equal", f"live {live}", bad)


def check_v1_manifest_rows_bytes() -> dict:
    m = jload("derived/v1/MANIFEST.json")
    entries = {**m["tables"], **m["csv_copies"]}
    bad = []
    for f, spec in entries.items():
        p = V1 / f
        if not p.is_file():
            bad.append(f"{f}: missing")
            continue
        rows = nrows(f"derived/v1/{f}")
        size = p.stat().st_size
        if rows != spec["rows"] or size != spec["bytes"]:
            bad.append(f"{f}: rows {rows} vs {spec['rows']}, bytes {size} vs {spec['bytes']}")
    on_disk = {p.name for p in V1.iterdir() if p.suffix in (".parquet", ".csv")}
    unlisted = sorted(on_disk - set(entries))
    note = f"; on disk but not in MANIFEST: {unlisted}" if unlisted else ""
    st = "fail" if bad else "warn" if unlisted else "pass"
    return result("v1_manifest_rows_bytes", st, f"{len(entries) - len(bad)}/{len(entries)} match",
                  "rows and bytes equal; every file listed", "MANIFEST tables + csv_copies vs disk" + note,
                  bad + unlisted)


def check_v1_canonical_copies() -> dict:
    """The canonical cleaned tables in derived/v1 are byte copies of their cleaning/ source, and the source has
    not moved on since the build (a moved source means derived/v1 is stale)."""
    m = jload("derived/v1/MANIFEST.json")["other_input_sha256"]
    bad, stale, n = [], [], 0
    for src, h in m.items():
        if not src.startswith("cleaning/") or not src.endswith(".parquet"):
            continue
        n += 1
        copy = V1 / os.path.basename(src)
        hc = sha256(copy)
        hs = sha256(ROOT / src) if (ROOT / src).is_file() else "missing"
        if hc != h:
            bad.append(f"{copy.name}: copy {hc[:12]} != manifest {h[:12]}")
        if hs != h:
            stale.append(f"{src}: source now {hs[:12]} != manifest {h[:12]}")
    st = "fail" if bad else "warn" if stale else "pass"
    return result("v1_canonical_copies", st, f"{n - len(bad)}/{n} copies identical; {len(stale)} sources moved",
                  "copy == manifest == source", "sha256 of derived/v1 copies and cleaning/ sources", bad + stale)


def check_v1_inputs_not_stale() -> dict:
    """Non-table inputs (audit labels, gold labels, hand checks) and pipeline scripts still hash to MANIFEST."""
    m = jload("derived/v1/MANIFEST.json")
    moved, n = [], 0
    for src, h in m["other_input_sha256"].items():
        if src.startswith("cleaning/") and src.endswith(".parquet"):
            continue
        n += 1
        p = ROOT / src
        if not p.is_file() or sha256(p) != h:
            moved.append(f"{src}: {'missing' if not p.is_file() else 'changed'}")
    for s, h in m["script_sha256"].items():
        n += 1
        p = ROOT / "pipelines/source_scoring" / s
        if not p.is_file() or sha256(p) != h:
            moved.append(f"pipelines/source_scoring/{s}: {'missing' if not p.is_file() else 'changed'}")
    return result("v1_inputs_not_stale", "warn" if moved else "pass", f"{n - len(moved)}/{n} unchanged",
                  "all unchanged", "an input or script changed after the build means the build is not reproducible "
                  "from the tree as it stands", moved)


def check_v1_build_stats() -> dict:
    """build_stats.json counts agree with the tables."""
    b = jload("derived/v1/build_stats.json")
    dps = table("derived/v1/data_point_scores.parquet")
    su = table("derived/v1/source_urls.parquet")
    bad = []
    by_type = dps.dp_type.value_counts().to_dict()
    for t, n in b["s6_stats"]["data_points"].items():
        if by_type.get(t) != n:
            bad.append(f"dps {t}: table {by_type.get(t)} vs stats {n}")
    st = dps.groupby(["dp_type", "status"]).size()
    for t, d in b["s6_stats"]["status_by_type"].items():
        for s, n in d.items():
            got = int(st.get((t, s), 0))
            if got != n:
                bad.append(f"dps {t}/{s}: table {got} vs stats {n}")
    s1 = b["s1_stats"]
    for k, got in [("rows", len(su)), ("records", su.unique_id.nunique()), ("distinct_urls", su.url.nunique()),
                   ("distinct_domains", su.domain.nunique())]:
        if got != s1[k]:
            bad.append(f"source_urls {k}: table {got} vs stats {s1[k]}")
    if su.url_kind.value_counts().to_dict() != s1["url_kind"]:
        bad.append("source_urls url_kind counts differ")
    return result("v1_build_stats", "fail" if bad else "pass", f"{len(bad)} mismatches", "0",
                  "build_stats.json s1 and s6 counts vs tables", bad)


DOC_COUNTS = {  # documented row counts in the READMEs
    "derived/v1/data_point_scores.parquet": 518191, "derived/v1/claims.parquet": 469498,
    "derived/v1/facility_trust.parquet": 9959, "derived/v1/source_domains.parquet": 10951,
    "derived/v1/source_classes.parquet": 16, "derived/v1/source_urls.parquet": 158444,
    "derived/v1/source_page_checks.parquet": 6492, "derived/v1/evidence_rules.parquet": 20,
    "derived/v1/gold_pairs.parquet": 176, "derived/v1/pin_gazetteer.parquet": 19713,
    "derived/v1/place_gazetteer.parquet": 147345, "derived/v1/specialties.parquet": 117964,
    "derived/v1/grades.parquet": 10799, "kb/vf_details/out/facts.parquet": 42036,
    "kb/vf_details/out/facility_details.parquet": 26046, "kb/vf_details/out/hour_candidates.parquet": 64,
    "kb/vf_details/out/llm_hours.parquet": 64, "kb/web_evidence/out/site_identity.parquet": 6770,
    "kb/web_evidence/out/page_identity.parquet": 30517, "kb/web_evidence/out/web_services.parquet": 153160,
    "kb/web_evidence/out/web_service_summary.parquet": 20886, "kb/web_evidence/out/web_hours.parquet": 43540,
    "kb/web_evidence/out/web_details.parquet": 41191, "kb/web_evidence/out/web_facility_details.parquet": 17908,
    "kb/web_evidence/out/hour_candidates.parquet": 833, "kb/web_evidence/out/llm_hours.parquet": 633,
    "kb/taxonomy/out/lexicon_matches.parquet": 64670, "kb/taxonomy/specialty_map.csv": 2933,
    "kb/taxonomy/specialty_evidence_weights.csv": 1346, "kb/web_evidence/out/compare_by_service.csv": 37,
    "kb/crawl/targets.parquet": 9405, "kb/crawl/pages.parquet": 31075,
    "kb/opendata/opendata_not_in_vf.parquet": 147080,
}


def check_documented_row_counts() -> dict:
    bad = [f"{f}: disk {nrows(f)} vs doc {n}" for f, n in DOC_COUNTS.items() if nrows(f) != n]
    return result("documented_row_counts", "fail" if bad else "pass", f"{len(DOC_COUNTS) - len(bad)}/"
                  f"{len(DOC_COUNTS)} match", "all match", "row counts stated in README/VF_DETAILS/WEB_EVIDENCE/"
                  "TAXONOMY/crawl_stats vs disk", bad)


# ----------------------------------------------------------------------------------------------- schema, nulls


def _profile_column(s: pd.Series) -> dict:
    n = len(s)
    nulls = int(s.isna().sum()) if s.dtype != object else int(sum(x is None or (isinstance(x, float) and
                                                                                 np.isnan(x)) for x in s))
    enc = Counter()
    empty_lists = 0
    nonnull = s.dropna() if s.dtype != object else s[[x is not None for x in s]]
    sample = None
    for x in nonnull:
        if isinstance(x, str):
            k = is_null_like(x)
            if k:
                enc[k] += 1
        elif isinstance(x, (list, np.ndarray)) and len(x) == 0:
            empty_lists += 1
        if sample is None:
            sample = x
    mn = mx = None
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) and len(nonnull):
        mn, mx = float(np.nanmin(nonnull)), float(np.nanmax(nonnull))
    try:
        nd = int(nonnull.map(lambda x: x if not isinstance(x, (list, np.ndarray)) else tuple(x)).nunique())
    except TypeError:
        nd = -1
    return {"n": n, "nulls": nulls, "null_rate": round(nulls / n, 4) if n else 0, "empty_string": enc["empty"],
            "null_string": enc["null_string"], "empty_container_string": enc["empty_container"],
            "empty_list": empty_lists, "distinct": nd, "min": mn, "max": mx, "example": str(sample)[:80]}


def check_schema_profile() -> dict:
    """Document every tabular file: column, type, null rate, null encodings, distinct count, range.
    Writes outputs/schema_profile.csv and outputs/json_inventory.csv."""
    OUT.mkdir(exist_ok=True)
    rows, inv = [], []
    for f in tabular_files():
        df = table(f)
        types = ({fld.name: str(fld.type) for fld in pq.read_schema(ROOT / f)} if f.endswith(".parquet")
                 else {c: "string (csv)" for c in df.columns})
        for c in df.columns:
            rows.append({"file": f, "rows": len(df), "column": c, "type": types.get(c, str(df[c].dtype)),
                         **_profile_column(df[c])})
    pd.DataFrame(rows).to_csv(OUT / "schema_profile.csv", index=False)
    for f in scope_files():
        if f.endswith((".parquet", ".csv")):
            continue
        size = (ROOT / f).stat().st_size
        try:
            o = jload(f) if f.endswith((".json", ".gz", ".jsonl")) else None
            shape = (f"dict keys={list(o)[:12]}" if isinstance(o, dict) else f"list len={len(o)}" if
                     isinstance(o, list) else type(o).__name__)
            ok = True
        except Exception as e:  # unparseable JSON is a finding
            shape, ok = f"PARSE ERROR {type(e).__name__}: {e}", False
        inv.append({"file": f, "bytes": size, "parses": ok, "shape": shape[:300]})
    pd.DataFrame(inv).to_csv(OUT / "json_inventory.csv", index=False)
    bad = [i["file"] + ": " + i["shape"] for i in inv if not i["parses"] and not i["file"].endswith(".sha")]
    return result("schema_profile", "fail" if bad else "pass",
                  f"{len({r['file'] for r in rows})} tables, {len(rows)} columns; {len(inv)} other files",
                  "every JSON parses", "outputs/schema_profile.csv, outputs/json_inventory.csv", bad)


# Columns that copy raw text verbatim, so raw null strings are expected there and are not cleaning failures.
VERBATIM_COLS = {"original_value", "source_text", "quote", "text", "best_quote", "context", "snippet", "title",
                 "value_text", "vf_address", "name_quote", "match", "note", "notes"}


JSON_COLS = {"cite_evidence", "cite_prereqs", "cite_counter", "cite_elsewhere", "evidence_urls", "entries_json",
             "top_sources", "class_mix", "tags_json"}


def check_null_encodings() -> dict:
    """String-encoded nulls ('null', 'None', 'nan', 'N/A', '[]') in derived and kb tables. Outside verbatim text
    and JSON-encoded columns these should be real nulls. Empty strings are counted separately (several tables use
    '' for 'no value' by design)."""
    check_schema_profile() if not (OUT / "schema_profile.csv").is_file() else None
    p = pd.read_csv(OUT / "schema_profile.csv")
    p["encoded"] = p.null_string + p.empty_container_string.where(~p.column.isin(JSON_COLS), 0)
    p.to_csv(OUT / "null_encodings.csv", index=False, columns=[
        "file", "column", "rows", "nulls", "null_string", "empty_container_string", "empty_string", "empty_list"])
    hit = p[(p.encoded > 0) & ~p.column.isin(VERBATIM_COLS) & ~p.file.str.contains("/qa/|selfcheck|handcheck")]
    verb = p[(p.null_string > 0) & p.column.isin(VERBATIM_COLS)]
    empties = p[(p.empty_string > 0)]
    ex = [f"{r.file}.{r.column}: {r.null_string} null strings, {r.empty_container_string} empty containers of "
          f"{r.rows}" for r in hit.sort_values("encoded", ascending=False).itertuples()]
    ex += [f"verbatim {r.file}.{r.column}: {r.null_string} null-placeholder values" for r in verb.itertuples()]
    return result("null_encodings", "warn" if len(hit) else "pass",
                  f"{len(hit)} key/enum columns carry string nulls ({int(hit.encoded.sum())} cells)",
                  "0 outside verbatim text and JSON columns",
                  f"{len(empties)} columns use '' for missing ({int(empties.empty_string.sum())} cells); full "
                  "list outputs/null_encodings.csv", ex)


def _dup_keys(df: pd.DataFrame, key: list[str]) -> tuple[int, int, list]:
    k = df[key].copy()
    for c in key:
        k[c] = k[c].map(lambda x: tuple(x) if isinstance(x, (list, np.ndarray)) else x)
    nul = int(k.isna().any(axis=1).sum())
    d = k[k.duplicated(keep=False)]
    ex = ["|".join(map(str, r)) for r in d.drop_duplicates().head(5).itertuples(index=False)]
    return int(k.duplicated().sum()), nul, ex


# Documented rows where part of the key is legitimately null; they are checked separately below.
NULLABLE_KEYS = {
    # "URLs with no usable page have one row with claim_id null" (derived/v1/README.md)
    "derived/v1/source_page_checks.parquet": lambda d: d.claim_id.isna() & (d.fetch_status != "ok_html"),
    # raw specialties holds one empty string value, mapped with basis "empty or whitespace"
    "kb/taxonomy/specialty_map.csv": lambda d: d.specialty.isna() & (d.basis == "empty or whitespace"),
}


def check_primary_keys() -> dict:
    bad, rows = [], []
    for f, key in PRIMARY_KEYS.items():
        if not (ROOT / f).is_file():
            bad.append(f"{f}: missing")
            continue
        df = table(f)
        miss = [c for c in key if c not in df.columns]
        if miss:
            bad.append(f"{f}: key columns missing {miss}")
            continue
        if f in NULLABLE_KEYS:
            df = df[~NULLABLE_KEYS[f](df)]
        nd, nul, ex = _dup_keys(df, key)
        rows.append({"file": f, "key": "+".join(key), "rows": len(df), "dup_keys": nd, "null_keys": nul})
        if nd or nul:
            bad.append(f"{f} ({'+'.join(key)}): {nd} duplicate keys, {nul} null keys of {len(df)}; e.g. {ex[:2]}")
    pd.DataFrame(rows).to_csv(OUT / "primary_keys.csv", index=False)
    return result("primary_keys", "fail" if bad else "pass", f"{len(PRIMARY_KEYS) - len(bad)}/{len(PRIMARY_KEYS)}"
                  " keys unique and non-null", "all", "outputs/primary_keys.csv", bad)


def check_exact_duplicate_rows() -> dict:
    con, bad, rows = duck(), [], []
    for f in tabular_files():
        if f.endswith(".parquet"):
            n, d = con.execute(f"SELECT count(*), (SELECT count(*) FROM (SELECT DISTINCT * FROM '{ROOT / f}')) "
                               f"FROM '{ROOT / f}'").fetchone()
        else:
            df = table(f)
            n, d = len(df), len(df.drop_duplicates())
        rows.append({"file": f, "rows": n, "exact_duplicates": n - d})
        if n != d:
            bad.append(f"{f}: {n - d} exact duplicate rows of {n}")
    pd.DataFrame(rows).to_csv(OUT / "exact_duplicates.csv", index=False)
    return result("exact_duplicate_rows", "warn" if bad else "pass", f"{len(bad)} tables with duplicates",
                  "0", f"{len(rows)} tables scanned; outputs/exact_duplicates.csv", bad)


def check_csv_copies_match_parquet() -> dict:
    """derived/v1 CSV copies hold the same rows and values as their parquet tables."""
    bad = []
    for name in ["facility_trust", "source_classes", "source_domains"]:
        p = table(f"derived/v1/{name}.parquet")
        c = pd.read_csv(V1 / f"{name}.csv")
        if list(p.columns) != list(c.columns) or len(p) != len(c):
            bad.append(f"{name}: columns/rows differ ({len(p)} vs {len(c)})")
            continue
        for col in p.columns:
            a, b = p[col], c[col]
            if pd.api.types.is_numeric_dtype(a) and not pd.api.types.is_bool_dtype(a):
                diff = ~np.isclose(a.astype(float), pd.to_numeric(b, errors="coerce").astype(float),
                                   rtol=1e-9, atol=1e-12, equal_nan=True)
            else:
                diff = a.fillna("<NA>").astype(str).values != b.fillna("<NA>").astype(str).values
            if diff.sum():
                i = int(np.argmax(diff))
                bad.append(f"{name}.{col}: {int(diff.sum())} cells differ, e.g. row {i}: {a.iloc[i]!r} vs "
                           f"{b.iloc[i]!r}")
    return result("csv_copies_match_parquet", "fail" if bad else "pass", f"{len(bad)} differing columns", "0",
                  "facility_trust, source_classes, source_domains", bad)


# ----------------------------------------------------------------------------------------------- record ids


def check_usable_set_definition() -> dict:
    """The 9,959 usable records: well-formed raw rows whose duplicate unique_ids are byte-identical, so
    keep-first deduplication loses nothing; and every 9,959-row table holds exactly that set."""
    f = raw()
    ok = f.unique_id.str.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", na=False) & (f.source == "kie")
    w = f[ok]
    dup = w[w.unique_id.duplicated(keep=False)]
    differing = [u for u, g in dup.astype(str).groupby("unique_id") if len(g.drop_duplicates()) > 1]
    bad = [f"duplicate unique_id with differing rows: {u}" for u in differing]
    non_uuid = int((~w.unique_id.str.fullmatch(UUID_RE.strip("^$"))).sum())
    if non_uuid:
        bad.append(f"{non_uuid} usable ids are not full UUIDs")
    if len(usable_ids()) != 9959:
        bad.append(f"usable set has {len(usable_ids())} ids, documented 9,959")
    per_record = ["derived/v1/facility_location.parquet", "derived/v1/record_trust.parquet",
                  "derived/v1/facility_groups.parquet", "derived/v1/facility_trust.parquet"]
    for t in per_record:
        ids = set(table(t).unique_id)
        if ids != usable_ids():
            bad.append(f"{t}: {len(ids - usable_ids())} ids outside the usable set, "
                       f"{len(usable_ids() - ids)} usable ids missing")
    return result("usable_set_definition", "fail" if bad else "pass",
                  f"{len(usable_ids())} usable of {len(f)} raw; {dup.unique_id.nunique()} duplicated ids, "
                  f"{len(differing)} differ", "duplicates identical; per-record tables == usable set",
                  f"rule: UUID unique_id and source == 'kie' ({int(ok.sum())} rows), keep first per id", bad)


def _uid_values(df: pd.DataFrame, col: str) -> pd.Series:
    s = df[col].dropna()
    if len(s) and isinstance(s.iloc[0], (list, np.ndarray)):
        s = s.explode().dropna()
    return s.astype(str)


UID_COLS = ("unique_id", "unique_ids")


def check_unique_id_fk() -> dict:
    """Every unique_id in every in-scope table exists in data/raw and is a usable record."""
    rows, bad = [], []
    for f in tabular_files():
        df = table(f)
        for c in [c for c in df.columns if c in UID_COLS]:
            v = _uid_values(df, c)
            d = set(v)
            not_raw = sorted(d - raw_ids())
            not_usable = sorted(d - usable_ids() - set(not_raw))
            rows.append({"file": f, "column": c, "rows": len(df), "nulls": int(df[c].isna().sum()),
                         "distinct": len(d), "not_in_raw": len(not_raw), "in_raw_not_usable": len(not_usable)})
            if not_raw or not_usable:
                bad.append(f"{f}.{c}: {len(not_raw)} not in raw, {len(not_usable)} not usable of {len(d)}; "
                           f"e.g. {(not_raw + not_usable)[:3]}")
            if df[c].isna().sum() and f.startswith(("derived/", "kb/")) and "/qa/" not in f:
                bad.append(f"{f}.{c}: {int(df[c].isna().sum())} null ids")
    pd.DataFrame(rows).to_csv(OUT / "unique_id_fk.csv", index=False)
    return result("unique_id_fk", "fail" if bad else "pass", f"{len(rows) - len(bad)}/{len(rows)} id columns "
                  "fully resolve", "every id in raw and usable", "outputs/unique_id_fk.csv", bad)


def check_uid8_prefix_unique() -> dict:
    """claim ids and app packs key records by the first 8 hex chars of unique_id; they must not collide."""
    c = Counter(u[:8] for u in usable_ids())
    coll = [k for k, n in c.items() if n > 1]
    return result("uid8_prefix_unique", "fail" if coll else "pass", f"{len(coll)} colliding prefixes of {len(c)}",
                  "0", "uid8 = unique_id[:8] over the usable set", coll)


def check_claim_id_format() -> dict:
    """claim_id == uid8:field4:idx and agrees with the row's unique_id, field and idx; idx is dense per field."""
    c = table("derived/v1/claims.parquet")
    m = c.claim_id.str.extract(CLAIM_RE)
    bad_fmt = c[m[0].isna()]
    ok = m[0].notna()
    mism = c[ok & ((m[0] != c.unique_id.str[:8]) | (m[1].map(FIELD4) != c.field) |
                   (pd.to_numeric(m[2], errors="coerce") != c.idx))]
    g = c.groupby(["unique_id", "field"]).idx.agg(["min", "max", "count"])
    gaps = g[(g["min"] != 0) | (g["max"] + 1 != g["count"])]
    nf = c.field.value_counts().to_dict()
    bad = ([f"bad format: {x}" for x in bad_fmt.claim_id.head(3)] +
           [f"disagrees with row: {x}" for x in mism.claim_id.head(3)] +
           [f"idx not dense 0..n-1: {i}" for i in gaps.index[:3]])
    st = "fail" if len(bad_fmt) or len(mism) else "warn" if len(gaps) else "pass"
    return result("claim_id_format", st, f"{len(bad_fmt)} malformed, {len(mism)} disagree, {len(gaps)} "
                  f"(record, field) groups with idx gaps", "0", f"{len(c)} claims; fields {nf}", bad)


def _cites(df: pd.DataFrame, col: str) -> list[tuple]:
    """(claim_id, owner unique_id, cited text) from a JSON citation column: a list of {claim_id, text} or a
    dict prereq -> {claim_id, text} | {tag} (tag-only prerequisites carry no claim id)."""
    out = []
    for uid, v in zip(df.unique_id, df[col]):
        if v is None:
            continue
        o = json.loads(v)
        items = o.values() if isinstance(o, dict) else o
        for x in items:
            if isinstance(x, dict) and x.get("claim_id"):
                out.append((x["claim_id"], uid, x.get("text")))
    return out


def _plain(ids, owners=None) -> list[tuple]:
    owners = owners if owners is not None else [None] * len(ids)
    return [(c, u, None) for c, u in zip(ids, owners) if isinstance(c, str) and c]


def claim_refs() -> dict[str, list[tuple]]:
    """Every place a claim id is cited, as {source: [(claim_id, owner unique_id or None, text or None)]}."""
    refs: dict[str, list[tuple]] = {}
    dps = table("derived/v1/data_point_scores.parquet")
    d = dps[dps.claim_id.notna()]
    refs["data_point_scores.claim_id"] = _plain(d.claim_id.tolist(), d.unique_id.tolist())
    sent = dps[dps.dp_type == "claim_attribution"]
    refs["data_point_scores.dp_id(sent:)"] = _plain(sent.dp_id.str.removeprefix("sent:").tolist(),
                                                    sent.unique_id.tolist())
    spc = table("derived/v1/source_page_checks.parquet").dropna(subset=["claim_id"])
    refs["source_page_checks.claim_id"] = _plain(spc.claim_id.tolist(), spc.unique_id.tolist())
    for g in ["grades", "grades_v1"]:
        t = table(f"derived/v1/{g}.parquet")
        for col in ["cite_evidence", "cite_prereqs", "cite_counter", "cite_elsewhere"]:
            refs[f"{g}.{col}"] = _cites(t, col)
    for f in ["kb/taxonomy/out/lexicon_matches.parquet", "kb/vf_details/out/hour_candidates.parquet"]:
        t = table(f)
        refs[f.split("/")[-1] + ".claim_id"] = _plain(t.claim_id.tolist(), t.unique_id.tolist())
    refs["vf llm_hours.claim_id"] = _plain(table("kb/vf_details/out/llm_hours.parquet").claim_id.tolist())
    vf = table("kb/vf_details/out/facts.parquet").dropna(subset=["claim_id"])
    refs["vf facts.claim_id"] = [(c, u, t) for c, u, t in zip(vf.claim_id, vf.unique_id, vf.source_text)]
    fd = table("kb/vf_details/out/facility_details.parquet")
    refs["vf facility_details.claim_ids"] = [(c, u, None) for u, v in zip(fd.unique_id, fd.claim_ids)
                                             if isinstance(v, str) for c in v.split("|") if c]
    b = fd.dropna(subset=["best_claim_id"])
    refs["vf facility_details.best_claim_id"] = _plain(b.best_claim_id.tolist(), b.unique_id.tolist())
    facts = jload("app/facts/out/facts.json.gz")
    refs["app facts.claims"] = [(k, None, v[1]) for k, v in facts["claims"].items()]
    fid = facts["fac"]["id"]
    refs["app facts.pairs evidence"] = [(c, fid[r[0]], None) for rows in facts["pairs"].values() for r in rows
                                        for c in r[9]]
    pl = jload("planner/out/planner_v1.json.gz")
    pid = pl["facilities"]["id"]
    refs["planner capabilities.e"] = [(c, pid[i], None) for cap in pl["capabilities"].values()
                                      for i, ids in zip(cap["i"], cap["e"]) for c in ids]
    return refs


def check_claim_id_fk() -> dict:
    """Every cited claim id resolves in derived/v1/claims.parquet, belongs to the citing record, and any text
    copied next to it equals the claim text."""
    ids, txt = claim_ids(), claim_text()
    rows, bad, warn = [], [], []
    for src, lst in claim_refs().items():
        miss = sorted({c for c, _, _ in lst if c not in ids})
        foreign = sorted({(c, u) for c, u, _ in lst if u and c in ids and c[:8] != u[:8]})
        # vf facts quote the claim sentence as source_text; compare exactly
        changed = sorted({c for c, _, t in lst if t is not None and c in txt and t != txt[c]})
        rows.append({"source": src, "refs": len(lst), "distinct": len({c for c, _, _ in lst}),
                     "unresolved": len(miss), "foreign_record": len(foreign), "text_differs": len(changed)})
        if miss:
            bad.append(f"{src}: {len(miss)} distinct ids unresolved, e.g. {miss[:3]}")
        if foreign:
            bad.append(f"{src}: {len(foreign)} ids cite another record, e.g. {foreign[:2]}")
        if changed:
            warn.append(f"{src}: {len(changed)} copied texts differ from claims.text, e.g. {changed[:3]}")
    pd.DataFrame(rows).to_csv(OUT / "claim_id_fk.csv", index=False)
    return result("claim_id_fk", "fail" if bad else "warn" if warn else "pass",
                  f"{len(rows) - len(bad)}/{len(rows)} sources resolve; {len(warn)} with text drift",
                  "all resolve, own record, text equal", "outputs/claim_id_fk.csv (packs: app_packs_integrity)",
                  bad + warn)


# ----------------------------------------------------------------------------------------------- derived/v1 joins

DP_PREFIX = {"location": "loc", "existence": "exist", "phone": "phone", "email": "email",
             "service_claim": "svc", "claim_attribution": "sent"}


def check_dp_id_format() -> dict:
    """dp_id agrees with dp_type, unique_id, service and claim_id; per-record types appear once per record."""
    d = table("derived/v1/data_point_scores.parquet")
    exp = d.dp_type.map(DP_PREFIX) + ":" + np.where(
        d.dp_type == "service_claim", d.unique_id + ":" + d.service.fillna(""),
        np.where(d.dp_type == "claim_attribution", d.claim_id.fillna(""), d.unique_id))
    bad_id = d[exp != d.dp_id]
    bad = [f"dp_id {r.dp_id} != expected {e}" for r, e in zip(bad_id.head(3).itertuples(), exp[bad_id.index][:3])]
    unknown = sorted(set(d.dp_type) - set(DP_PREFIX))
    if unknown:
        bad.append(f"unknown dp_type {unknown}")
    for t in ["location", "existence"]:
        ids = set(d[d.dp_type == t].unique_id)
        if ids != usable_ids():
            bad.append(f"{t}: {len(ids)} records, {len(usable_ids() - ids)} usable records missing")
    sent = d[d.dp_type == "claim_attribution"]
    if set(sent.claim_id) != claim_ids():
        bad.append(f"claim_attribution: {len(claim_ids() - set(sent.claim_id))} claims have no data point")
    cl = claims().set_index("claim_id")
    s = sent.set_index("claim_id")
    for col in ["unique_id", "attribution", "field"]:
        src = cl[col] if col != "field" else table("derived/v1/claims.parquet").set_index("claim_id")[col]
        diff = (s[col] != src.reindex(s.index)).sum()
        if diff:
            bad.append(f"claim_attribution.{col}: {diff} rows differ from claims.parquet")
    txt = (s.original_value != pd.Series(claim_text()).reindex(s.index)).sum()
    if txt:
        bad.append(f"claim_attribution.original_value: {txt} differ from claims.text")
    return result("dp_id_format", "fail" if bad else "pass", f"{len(bad_id)} bad dp_ids; {len(bad)} issues", "0",
                  f"{len(d)} data points", bad)


def check_dps_copies_raw_values() -> dict:
    """data_point_scores original_value is the raw record value as documented (location rounded to 5 dp)."""
    d = table("derived/v1/data_point_scores.parquet")
    r = usable().set_index("unique_id")
    bad, n = [], 0
    ex = d[d.dp_type == "existence"].set_index("unique_id")
    exp = (r["name"].fillna("") + " | " + r.address_city.fillna("")).reindex(ex.index)
    m = ex.original_value != exp
    n += int(m.sum())
    bad += [f"existence {u}: {ex.original_value[u]!r} vs {exp[u]!r}" for u in ex.index[m][:2]]
    for t, col in [("phone", "officialPhone"), ("email", "email")]:
        x = d[d.dp_type == t].set_index("unique_id")
        m = x.original_value != r[col].reindex(x.index)
        n += int(m.sum())
        bad += [f"{t} {u}: differs from raw {col}" for u in x.index[m][:2]]
        enc = x[x.original_value.map(lambda v: is_null_like(v) is not None)]
        n += len(enc)
        bad += [f"{t} {u}: scored a null-encoded raw value {v!r}" for u, v in enc.original_value.head(3).items()]
        has = r[col].map(lambda v: isinstance(v, str) and is_null_like(v) is None)
        missing = sorted(set(has[has].index) - set(x.index))
        n += len(missing)
        bad += [f"{t}: raw value present but no data point: {u}" for u in missing[:2]]
    loc = d[d.dp_type == "location"].set_index("unique_id")
    rl = r.reindex(loc.index)
    lat = loc.original_value.str.extract(r"^(-?[\d.]+|nan),(-?[\d.]+|nan) \|")
    dl = (pd.to_numeric(lat[0], errors="coerce") - rl.latitude).abs()
    m = ~((dl <= 6e-6) | (dl.isna() & rl.latitude.isna()))
    n += int(m.sum())
    bad += [f"location {u}: {loc.original_value[u]!r} vs raw lat {rl.latitude[u]}" for u in loc.index[m][:2]]
    sv = d[d.dp_type == "service_claim"].set_index(["unique_id", "service"])
    g = table("derived/v1/grades.parquet").set_index(["unique_id", "service"])
    joined = g.cite_evidence.map(lambda s: " || ".join(x["text"] for x in json.loads(s))).reindex(sv.index)
    m = sv.original_value != joined
    n += int(m.sum())
    bad += [f"service_claim {i}: original_value != joined cite_evidence" for i in sv.index[m][:2]]
    return result("dps_copies_raw_values", "fail" if n else "pass", f"{n} mismatches", "0",
                  "existence, phone, email, location (5 dp) and service_claim originals vs raw / grades", bad)


def check_grades_vs_dps() -> dict:
    """Every (unique_id, service) grade has exactly one service_claim data point with the same grade, and
    facility_trust counts agree with the detail tables."""
    d = table("derived/v1/data_point_scores.parquet")
    g = table("derived/v1/grades.parquet")
    sv = d[d.dp_type == "service_claim"]
    a = set(zip(g.unique_id, g.service))
    b = set(zip(sv.unique_id, sv.service))
    bad = []
    if a != b:
        bad.append(f"grades-only {len(a - b)}, dps-only {len(b - a)}; e.g. {sorted(a ^ b)[:2]}")
    m = sv.merge(g[["unique_id", "service", "grade"]], on=["unique_id", "service"], suffixes=("", "_g"))
    gd = m[m.grade != m.grade_g]
    if len(gd):
        bad.append(f"{len(gd)} service_claim grades differ from grades.parquet")
    g1 = table("derived/v1/grades_v1.parquet")
    if set(zip(g1.unique_id, g1.service)) != a:
        bad.append("grades_v1 (unique_id, service) set differs from grades")
    ft = table("derived/v1/facility_trust.parquet").set_index("unique_id")
    nsent = claims().groupby("unique_id").size().reindex(ft.index).fillna(0)
    nsvc = g.groupby("unique_id").size().reindex(ft.index).fillna(0)
    noth = claims()[claims().attribution == "other_facility"].groupby("unique_id").size().reindex(ft.index).fillna(0)
    vt = sv[sv.status == "verified_true"].groupby("unique_id").size().reindex(ft.index).fillna(0)
    vf = sv[sv.status == "verified_false"].groupby("unique_id").size().reindex(ft.index).fillna(0)
    for col, exp in [("n_sentences", nsent), ("n_service_claims", nsvc), ("n_sentences_other_facility", noth),
                     ("n_service_verified_true", vt), ("n_service_verified_false", vf)]:
        k = int((ft[col] != exp).sum())
        if k:
            bad.append(f"facility_trust.{col}: {k} records disagree, e.g. {list(ft.index[ft[col] != exp][:2])}")
    rt = table("derived/v1/record_trust.parquet").set_index("unique_id")
    k = int((ft.trust_level_cleaning != rt.trust_level.reindex(ft.index)).sum())
    if k:
        bad.append(f"facility_trust.trust_level_cleaning: {k} differ from record_trust.trust_level")
    for t, col in [("location", "location_score"), ("existence", "existence_score")]:
        s = d[d.dp_type == t].set_index("unique_id").score.reindex(ft.index)
        k = int((~np.isclose(s, ft[col])).sum())
        if k:
            bad.append(f"facility_trust.{col}: {k} differ from data_point_scores")
    ov = ft.existence_score * ft.location_score * ft.attribution_score
    k = int((~np.isclose(ov, ft.overall_score, atol=1e-4, equal_nan=True)).sum())
    if k:
        bad.append(f"overall_score != existence x location x attribution for {k} records")
    return result("grades_vs_dps", "fail" if bad else "pass", f"{len(bad)} inconsistencies", "0",
                  f"{len(a)} graded pairs; facility_trust counts recomputed from claims/grades/dps", bad)


def check_evidence_rules_vs_dps() -> dict:
    """evidence_rules n_points and q_ev = a / (a + b) agree with data_point_scores; every dps rule is defined."""
    e = table("derived/v1/evidence_rules.parquet").set_index("rule")
    d = table("derived/v1/data_point_scores.parquet")
    cnt = d.rule.value_counts()
    bad = [f"rule {r}: n_points {e.n_points[r]} vs dps {cnt.get(r, 0)}" for r in e.index if e.n_points[r] != cnt.get(r, 0)]
    bad += [f"dps rule {r} not in evidence_rules" for r in cnt.index if r not in e.index]
    q = e.a / (e.a + e.b)
    # EMAIL_PLACEHOLDER is deterministic (README: q_ev 0.010 fixed, a and b unused)
    bad += [f"rule {r}: q_ev {e.q_ev[r]} != a/(a+b) {q[r]:.4f}" for r in e.index
            if abs(q[r] - e.q_ev[r]) > 1e-9 and r != "EMAIL_PLACEHOLDER"]
    ab = (e.handcheck_true + e.dev_true + 1 != e.a) | (e.handcheck_false + e.dev_false + 1 != e.b)
    bad += [f"rule {r}: a, b != counts + 1" for r in e.index[ab] if r != "EMAIL_PLACEHOLDER"]
    dq = d.groupby("rule").q_ev.agg(["min", "max"])
    bad += [f"rule {r}: dps q_ev range {dq.loc[r].tolist()} vs {e.q_ev[r]}" for r in dq.index
            if r in e.index and not (np.isclose(dq.loc[r, "min"], e.q_ev[r]) and np.isclose(dq.loc[r, "max"],
                                                                                          e.q_ev[r]))]
    return result("evidence_rules_vs_dps", "fail" if bad else "pass", f"{len(bad)} mismatches", "0",
                  f"{len(e)} rules", bad)


# ----------------------------------------------------------------------------------------------- gold labels

APP_TO_V1 = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "mri": "mri",
             "cardiac_surgery": "cardiac_surgery", "burn_care": "burns", "trauma_emergency": "trauma"}
LABEL_ENUMS = {"exists": {"yes", "no", "unclear"}, "location_ok": {"yes", "no", "unclear"},
               "service": {"confirmed", "contradicted", "no_info"}, "confidence": {"high", "medium", "low"}}


def _labels() -> list[dict]:
    out = []
    for f in sorted((ROOT / "audit/ground_truth").glob("web_*.json")) + sorted((ROOT / "model/gold")
                                                                              .glob("labels_*.json")):
        for r in json.loads(f.read_text())["results"]:
            out.append({**r, "location_ok": r.get("location_ok", r.get("location_matches")),
                        "file": str(f.relative_to(ROOT))})
    return out


def check_gold_keys_and_fk() -> dict:
    """splits.json pairs: unique ids and pairs, usable records, valid services; every label resolves to a pair;
    label enums; gold_pairs.parquet == splits."""
    sp = jload("model/gold/splits.json")
    pairs = pd.DataFrame(sp["pairs"])
    bad = []
    for k in (["pair_id"], ["unique_id", "service"]):
        d = pairs[pairs.duplicated(k, keep=False)]
        if len(d):
            bad.append(f"splits {'+'.join(k)} duplicated: {d[k].astype(str).agg('|'.join, axis=1).tolist()[:3]}")
    nu = pairs[~pairs.unique_id.isin(usable_ids())]
    bad += [f"splits pair {r.pair_id}: unique_id {r.unique_id} not usable" for r in nu.itertuples()]
    bad += [f"splits pair {r.pair_id}: unknown service {r.service}" for r in pairs.itertuples()
            if r.service not in APP_TO_V1]
    if pairs.split.value_counts().to_dict() != sp["counts"]:
        bad.append(f"split counts {pairs.split.value_counts().to_dict()} != header {sp['counts']}")
    cells = pairs.assign(cell=pairs.service + "_" + pairs.stratum).groupby(["cell", "split"]).size().unstack(
        fill_value=0)
    for cell, d in sp["by_cell"].items():
        got = {s: int(cells.loc[cell, s]) if cell in cells.index else 0 for s in d}
        if got != d:
            bad.append(f"by_cell {cell}: header {d} vs pairs {got}")
    sv2 = {p["pair_id"]: p for p in jload("model/gold/sample_v2.json")}
    v1s = {p["pair_id"]: p for p in jload("audit/ground_truth/sample.json")}
    e2e = {p["pair_id"]: p for p in json.loads((ROOT / "model/proto/decision/e2e_pairs_to_label.json").read_text())}
    known = set(pairs.pair_id) | set(e2e)
    labs = _labels()
    unres = sorted({(x["file"], x["pair_id"]) for x in labs if x["pair_id"] not in known})
    bad += [f"label {f}:{p} resolves to no pair" for f, p in unres[:5]]
    for x in labs:
        for fld, allowed in LABEL_ENUMS.items():
            if x.get(fld) not in allowed:
                bad.append(f"label {x['file']}:{x['pair_id']} {fld}={x.get(fld)!r}")
    for src, d in [("sample_v2", sv2), ("audit sample", v1s), ("e2e pairs", e2e)]:
        for pid, p in d.items():
            if p["unique_id"] not in usable_ids():
                bad.append(f"{src} {pid}: unique_id {p['unique_id']} not usable")
    sp_by = pairs.set_index("pair_id")
    for pid, p in list(sv2.items()) + list(v1s.items()):
        if pid in sp_by.index and (sp_by.unique_id[pid] != p["unique_id"] or sp_by.service[pid] != p["service"]):
            bad.append(f"{pid}: sample and splits disagree on unique_id/service")
    gp = table("derived/v1/gold_pairs.parquet").set_index("pair_id")
    if set(gp.index) != set(pairs.pair_id):
        bad.append(f"gold_pairs vs splits pair ids differ: {sorted(set(gp.index) ^ set(pairs.pair_id))[:3]}")
    for pid, r in sp_by.iterrows():
        if pid in gp.index:
            g = gp.loc[pid]
            if (g.unique_id, g.service, g.split, g.stratum) != (r.unique_id, APP_TO_V1[r.service], r.split,
                                                                r.stratum):
                bad.append(f"gold_pairs {pid} disagrees with splits")
    nlab = Counter(x["pair_id"] for x in labs)
    bad += [f"gold_pairs {pid}: n_labels {gp.n_labels[pid]} vs {nlab[pid]} label rows" for pid in gp.index
            if gp.n_labels[pid] != nlab[pid]]
    return result("gold_keys_and_fk", "fail" if bad else "pass", f"{len(bad)} issues", "0",
                  f"{len(pairs)} pairs ({pairs.split.value_counts().to_dict()}); {len(labs)} label rows; "
                  f"{len(e2e)} e2e pairs", bad)


def check_gold_split_leakage() -> dict:
    """No duplicate-group, same-site or same-record link crosses the dev/test boundary, so test stays held out."""
    pairs = pd.DataFrame(jload("model/gold/splits.json")["pairs"])
    fg = table("derived/v1/facility_groups.parquet").set_index("unique_id")
    split_of = defaultdict(set)
    for r in pairs.itertuples():
        split_of[r.unique_id].add(r.split)
    bad = [f"record {u} has pairs in both splits" for u, s in split_of.items() if len(s) > 1]
    grp = pairs.groupby("group").split.nunique()
    bad += [f"splits group {g} in both splits" for g in grp[grp > 1].index]
    gid = pairs.unique_id.map(fg.dup_group_id)
    g2 = pairs.assign(g=gid).dropna(subset=["g"]).groupby("g").split.nunique()
    bad += [f"facility_groups dup_group {g} in both splits" for g in g2[g2 > 1].index]
    for r in pairs.itertuples():
        for col in ["possible_same_site", "co_located_with"]:
            links = fg[col].get(r.unique_id)
            for other in (links if links is not None else []):
                if other in split_of and r.split not in split_of[other]:
                    bad.append(f"{r.pair_id} ({r.split}) {col} {other} ({sorted(split_of[other])})")
    return result("gold_split_leakage", "warn" if bad else "pass", f"{len(bad)} cross-split links", "0",
                  "links from splits.json group, facility_groups dup_group_id, possible_same_site, co_located_with",
                  sorted(set(bad)))


def check_gold_merge_reproduces() -> dict:
    """Recompute the documented merge (informative value from the most confident label; disagreement =
    conflict) and compare with gold_pairs; count TEST verdicts baked into published data_point_scores."""
    conf = {"high": 3, "medium": 2, "low": 1}
    inf = {"exists": {"yes", "no"}, "location_ok": {"yes", "no"}, "service": {"confirmed", "contradicted"}}
    by = defaultdict(list)
    for x in _labels():
        by[x["pair_id"]].append(x)
    gp = table("derived/v1/gold_pairs.parquet")
    bad = []
    for r in gp.itertuples():
        labs = sorted(by[r.pair_id], key=lambda x: -conf.get(x.get("confidence"), 0))
        for fld, col in [("exists", "exists"), ("location_ok", "location_ok"), ("service", "service_verdict")]:
            vals = {x[fld] for x in labs if x.get(fld) in inf[fld]}
            exp = "conflict" if len(vals) > 1 else vals.pop() if vals else (labs[0].get(fld) or "unclear")
            if getattr(r, col) != exp:
                bad.append(f"{r.pair_id}.{col}: {getattr(r, col)} vs recomputed {exp}")
    d = table("derived/v1/data_point_scores.parquet")
    test_verified = d[(d.gold_split == "test") & d.status.str.startswith("verified")]
    n_conf = int((gp.service_verdict == "conflict").sum() + (gp.location_ok == "conflict").sum())
    detail = (f"{len(test_verified)} data points carry a TEST gold verdict in score/status "
              f"({test_verified.dp_type.value_counts().to_dict()}); score_model holds the pre-override value. "
              f"{n_conf} conflict verdicts")
    st = "fail" if bad else "warn" if len(test_verified) else "pass"
    return result("gold_merge_reproduces", st, f"{len(bad)} merge mismatches; {len(test_verified)} TEST-verified "
                  "points published", "0 mismatches; TEST verdicts not in model inputs", detail,
                  bad + test_verified.dp_id.head(4).tolist())


# ----------------------------------------------------------------------------------------------- kb layers


def _taxonomy_ids() -> tuple[set, set]:
    s = jload("kb/taxonomy/services.json")
    ids = [sv["id"] for c in s["categories"] for sv in c["services"]]
    cand = {c["id"] for c in s.get("candidates_not_included", [])}
    return set(ids), cand


def check_taxonomy_domains() -> dict:
    """Service ids are unique and every service reference in kb tables resolves to services.json; the specialty
    map covers exactly the distinct raw specialties values."""
    s = jload("kb/taxonomy/services.json")
    ids_list = [sv["id"] for c in s["categories"] for sv in c["services"]]
    ids, cand = _taxonomy_ids()
    allowed = ids | cand
    bad = [f"duplicate service id {k}" for k, n in Counter(ids_list).items() if n > 1]
    if len(ids) != 36:
        bad.append(f"{len(ids)} services, documented 36")
    lex = jload("kb/taxonomy/lexicon.json")["services"]
    bad += [f"lexicon service {k} not in services.json" for k in lex if k not in allowed]
    bad += [f"services.json id {k} has no lexicon entry" for k in ids if k not in lex]
    special = {"too_general", "out_of_scope", "not_a_service"}
    refs = {
        "web_services.service_id": table("kb/web_evidence/out/web_services.parquet").service_id,
        "web_service_summary.service_id": table("kb/web_evidence/out/web_service_summary.parquet").service_id,
        "lexicon_matches.service": table("kb/taxonomy/out/lexicon_matches.parquet").service,
        "specialty_evidence_weights.service": table("kb/taxonomy/specialty_evidence_weights.csv").service,
        "compare_by_service.service_id": table("kb/web_evidence/out/compare_by_service.csv").service_id,
    }
    for name, col in refs.items():
        unk = sorted(set(col.dropna()) - allowed - {"all", "ALL", "all_services"})
        if unk:
            bad.append(f"{name}: unknown ids {unk[:5]}")
    sm = table("kb/taxonomy/specialty_map.csv")
    vals = {x for v in sm.service_id.dropna() for x in v.split(";")}
    unk = sorted(vals - allowed - special)
    if unk:
        bad.append(f"specialty_map.service_id unknown {unk[:5]}")
    raw_specs = set()
    for v in usable().specialties.dropna():
        try:
            lst = json.loads(v)
        except json.JSONDecodeError:
            continue
        if isinstance(lst, list):
            raw_specs.update(str(x) for x in lst if x is not None)
    mapped = set(sm.specialty.fillna(""))
    miss, extra = raw_specs - mapped, mapped - raw_specs
    if miss or extra:
        bad.append(f"specialty_map vs raw specialties (usable rows): {len(miss)} unmapped, {len(extra)} not in "
                   f"raw; e.g. {sorted(miss)[:2]} {sorted(extra)[:2]}")
    w = table("kb/taxonomy/specialty_evidence_weights.csv")
    nw = sorted(set(w.specialty) - mapped)
    if nw:
        bad.append(f"evidence weights cite {len(nw)} specialties not in the map, e.g. {nw[:3]}")
    for c in ["weight", "pooled_rate", "weight_fit_half"]:
        x = pd.to_numeric(w[c], errors="coerce")
        if ((x < 0) | (x > 1)).any():
            bad.append(f"specialty_evidence_weights.{c} outside [0, 1]")
    k, n = pd.to_numeric(w.k_text_positive), pd.to_numeric(w.n_facilities)
    if (k > n).any():
        bad.append(f"specialty_evidence_weights: k_text_positive > n_facilities in {(k > n).sum()} rows")
    # derived/v1/specialties.spec is regexp_replace(lower(s), '[^a-z]', '') (cleaning/claims/build_claims.py:57)
    sm = sm.assign(k=sm.specialty.fillna("").map(lambda x: re.sub(r"[^a-z]", "", x.lower())))
    spec = table("derived/v1/specialties.parquet")
    nspec = sorted(set(spec.spec) - set(sm.k))
    if nspec:
        bad.append(f"derived/v1/specialties.spec values with no map row: {nspec[:5]}")
    amb = sm.groupby("k").service_id.nunique()
    amb = amb[amb > 1]
    warn = [f"spec key {k!r} maps to {sorted(sm[sm.k == k].service_id.unique())} via "
            f"{sm[sm.k == k].specialty.tolist()}" for k in amb.index]
    nf = int(spec[spec.spec.isin(amb.index)].unique_id.nunique())
    svc_keys = [k for k in amb.index if set(sm[sm.k == k].service_id) & allowed]
    nsv = int(spec[spec.spec.isin(svc_keys)].unique_id.nunique())
    return result("taxonomy_domains", "fail" if bad else "warn" if warn else "pass",
                  f"{len(bad)} issues; {len(amb)} spec keys map to 2+ labels ({nf} records); {len(svc_keys)} of "
                  f"them disagree on a real service ({nsv} records)", "0",
                  f"{len(ids)} services + {len(cand)} candidate; {len(sm)} specialty values; "
                  "derived/v1/specialties joins to the map only through the lowercased key", bad + warn)


def check_vf_details_fk() -> dict:
    """vf_details: fact ids are owned by their record, facility_details aggregates resolve to facts of the same
    record/type/attribute, counts reproduce, quotes are substrings of source_text."""
    f = table("kb/vf_details/out/facts.parquet")
    fd = table("kb/vf_details/out/facility_details.parquet")
    bad = []
    own = f.fact_id.str[:8] != f.unique_id.str[:8]
    if own.any():
        bad.append(f"{own.sum()} fact_ids not prefixed by their record's uid8, e.g. {f.fact_id[own].head(2).tolist()}")
    cid = f.dropna(subset=["claim_id"])
    pre = ~cid.apply(lambda r: r.fact_id.startswith(r.claim_id + ":"), axis=1)
    if pre.any():
        bad.append(f"{pre.sum()} fact_ids do not start with their claim_id")
    q = f[~f.apply(lambda r: isinstance(r.quote, str) and isinstance(r.source_text, str) and r.quote in r.source_text,
                   axis=1)]
    if len(q):
        bad.append(f"{len(q)} quotes not a substring of source_text, e.g. {q.fact_id.head(3).tolist()}")
    fi = f.set_index("fact_id")
    b = fd.dropna(subset=["best_fact_id"])
    miss = b[~b.best_fact_id.isin(fi.index)]
    if len(miss):
        bad.append(f"{len(miss)} best_fact_id unresolved, e.g. {miss.best_fact_id.head(2).tolist()}")
    ok = b[b.best_fact_id.isin(fi.index)]
    ref = fi.loc[ok.best_fact_id]
    wrong = ((ref.unique_id.values != ok.unique_id.values) | (ref.fact_type.values != ok.fact_type.values) |
             (ref.attribute.values != ok.attribute.values))
    if wrong.any():
        bad.append(f"{wrong.sum()} best_fact_id point at another record/type/attribute")
    st = (ref.status.values != ok.best_status.values)
    if st.any():
        bad.append(f"{st.sum()} best_status differ from the fact's status")
    agg = f.groupby(["unique_id", "fact_type", "attribute"]).status.value_counts().unstack(fill_value=0)
    fdi = fd.set_index(["unique_id", "fact_type", "attribute"])
    for col, s in [("n_ok", "ok"), ("n_flagged", "flagged"), ("n_excluded", "excluded")]:
        exp = agg[s].reindex(fdi.index).fillna(0) if s in agg else 0
        k = int((fdi[col] != exp).sum())
        if k:
            bad.append(f"facility_details.{col}: {k} rows differ from facts counts")
    keys_f = set(map(tuple, f[["unique_id", "fact_type", "attribute"]].drop_duplicates().values))
    keys_d = set(fdi.index)
    if keys_d - keys_f:
        bad.append(f"{len(keys_d - keys_f)} facility_details keys with no fact")
    lh, hc = table("kb/vf_details/out/llm_hours.parquet"), table("kb/vf_details/out/hour_candidates.parquet")
    if set(lh.claim_id) - set(hc.claim_id):
        bad.append("llm_hours claim_id outside hour_candidates")
    nll = int((f.method == "llm").sum())
    kept = int(lh.keep.sum())
    detail = f"{len(f)} facts, {len(fd)} facility rows; {len(keys_f - keys_d)} (record, type, attribute) keys have " \
             f"facts but no facility row; llm facts {nll}, llm kept {kept}"
    return result("vf_details_fk", "fail" if bad else "pass", f"{len(bad)} issues", "0", detail, bad)


def _web_tables() -> dict[str, pd.DataFrame]:
    w = "kb/web_evidence/out/"
    return {n: table(w + n + ".parquet") for n in ["web_services", "web_details", "web_hours", "page_identity",
                                                   "site_identity", "web_service_summary", "web_facility_details",
                                                   "hour_candidates", "llm_hours"]}


def check_web_evidence_fk() -> dict:
    """web_evidence rows resolve to crawl targets, stored pages, page and site identity rows of the same record;
    quotes are substrings of their segment/source text; summaries reproduce from row tables."""
    t = _web_tables()
    pages = table("kb/crawl/pages.parquet")
    targets = table("kb/crawl/targets.parquet").set_index("target_id")
    tgt_uids = {k: set(v) for k, v in targets.unique_ids.items()}
    page_paths = set(pages.path.dropna())
    pid = t["page_identity"].set_index(["page_id", "unique_id"])
    sid = set(zip(t["site_identity"].target_id, t["site_identity"].unique_id))
    bad = []
    for n in ["web_services", "web_details", "web_hours"]:
        d = t[n]
        k = list(zip(d.page_id, d.unique_id))
        miss = [x for x in k if x not in pid.index]
        if miss:
            bad.append(f"{n}: {len(miss)} (page_id, unique_id) not in page_identity, e.g. {miss[:2]}")
        j = pid.reindex(k)
        for col in ["path", "target_id", "final_url"]:
            diff = int((j[col].values != d[col].values).sum())
            if diff:
                bad.append(f"{n}.{col}: {diff} rows disagree with page_identity")
        nt = d[~d.target_id.isin(targets.index)]
        if len(nt):
            bad.append(f"{n}: {len(nt)} target_id not in crawl targets")
        nu = sum(u not in tgt_uids.get(tg, set()) for tg, u in zip(d.target_id, d.unique_id))
        if nu:
            bad.append(f"{n}: {nu} rows whose unique_id is not linked to the target")
        ns = sum((tg, u) not in sid for tg, u in zip(d.target_id, d.unique_id))
        if ns:
            bad.append(f"{n}: {ns} (target_id, unique_id) not in site_identity")
        npth = int((~d.path.isin(page_paths)).sum())
        if npth:
            bad.append(f"{n}: {npth} paths not stored in crawl pages")
        own = d.fact_id.str[:8] != d.unique_id.str[:8] if "fact_id" in d else pd.Series(False, index=d.index)
        if own.any():
            bad.append(f"{n}: {own.sum()} fact_ids not prefixed by the record uid8")
        src = "segment" if n == "web_services" else "source_text"
        q = sum(not (isinstance(a, str) and isinstance(b, str) and a in b) for a, b in zip(d.quote, d[src]))
        if q:
            bad.append(f"{n}: {q} quotes not a substring of {src}")
    ws = t["web_services"]
    att = ws[ws.attributable]
    pairs_att = set(zip(att.unique_id, att.service_id))
    summ = t["web_service_summary"]
    sp = set(zip(summ.unique_id, summ.service_id))
    if sp != pairs_att:
        bad.append(f"web_service_summary pairs vs attributable web_services: {len(sp - pairs_att)} extra, "
                   f"{len(pairs_att - sp)} missing")
    grp = att.groupby(["unique_id", "service_id"])
    exp = pd.DataFrame({"n_rows": grp.size(), "n_positive_rows": grp.positive.sum(),
                        "web_positive": grp.positive.any()})
    si = summ.set_index(["unique_id", "service_id"])
    for c in exp.columns:
        k = int((si[c] != exp[c].reindex(si.index)).sum())
        if k:
            bad.append(f"web_service_summary.{c}: {k} rows do not reproduce from web_services")
    facts = pd.concat([t["web_details"], t["web_hours"]])
    fi = facts.set_index("fact_id")
    if facts.fact_id.duplicated().any():
        bad.append(f"{facts.fact_id.duplicated().sum()} fact_ids shared by web_details and web_hours")
    wfd = t["web_facility_details"].dropna(subset=["best_fact_id"])
    miss = wfd[~wfd.best_fact_id.isin(fi.index)]
    if len(miss):
        bad.append(f"web_facility_details: {len(miss)} best_fact_id unresolved, e.g. "
                   f"{miss.best_fact_id.head(2).tolist()}")
    ok = wfd[wfd.best_fact_id.isin(fi.index)]
    r = fi.loc[ok.best_fact_id]
    wrong = (r.unique_id.values != ok.unique_id.values) | (r.attribute.values != ok.attribute.values)
    if wrong.any():
        bad.append(f"web_facility_details: {wrong.sum()} best_fact_id point at another record/attribute")
    lh = t["llm_hours"]
    orphan = lh[~lh.cand_key.isin(t["hour_candidates"].cand_key)]
    warn = [f"web llm_hours: {len(orphan)} cand_key not in hour_candidates ({int(orphan.keep.sum())} kept): "
            f"{orphan.cand_key.tolist()[:2]}"] if len(orphan) else []
    if orphan.keep.any():
        bad += warn
        warn = []
    return result("web_evidence_fk", "fail" if bad else "warn" if warn else "pass", f"{len(bad)} issues", "0",
                  f"{len(ws)} service rows, {len(facts)} fact rows, {len(t['page_identity'])} page identity rows",
                  bad + warn)


def check_crawl_fk() -> dict:
    """crawl: sites == targets, pages belong to targets and their records, stored page files exist on disk,
    per-site page counts reproduce."""
    tg = table("kb/crawl/targets.parquet").set_index("target_id")
    si = table("kb/crawl/sites.parquet").set_index("target_id")
    pg = table("kb/crawl/pages.parquet")
    bad = []
    if set(tg.index) != set(si.index):
        bad.append(f"sites vs targets target_id differ by {len(set(tg.index) ^ set(si.index))}")
    diff = sum(set(tg.unique_ids[t]) != set(si.unique_ids[t]) for t in tg.index if t in si.index)
    if diff:
        bad.append(f"{diff} targets whose unique_ids differ between targets and sites")
    for c in ["site", "domain", "kind", "shared"]:
        k = int((tg[c] != si[c].reindex(tg.index)).sum())
        if k:
            bad.append(f"sites.{c}: {k} differ from targets")
    nt = pg[~pg.target_id.isin(tg.index)]
    if len(nt):
        bad.append(f"{len(nt)} pages with unknown target_id")
    tu = {t: set(v) for t, v in tg.unique_ids.items()}
    nu = sum(not set(u) <= tu.get(t, set()) for t, u in zip(pg.target_id, pg.unique_ids))
    if nu:
        bad.append(f"{nu} pages list records not linked to their target")
    on_disk = {f"data/crawl/pages/{n}" for n in os.listdir(ROOT / "data/crawl/pages")}
    paths = set(pg.path.dropna())
    missing = sorted(paths - on_disk)
    orphan = sorted(on_disk - paths)
    if missing:
        bad.append(f"{len(missing)} stored page paths missing on disk, e.g. {missing[:2]}")
    stored = pg.dropna(subset=["path"]).groupby("target_id").size().reindex(si.index).fillna(0)
    k = int((si.n_pages_stored != stored).sum())
    if k:
        bad.append(f"sites.n_pages_stored differs from pages for {k} targets, e.g. "
                   f"{list(si.index[si.n_pages_stored != stored][:2])}")
    hs = pg.http_status.dropna()
    if ((hs < 100) | (hs > 599)).any():
        bad.append("http_status outside 100..599")
    err_and_path = int((pg.error.notna() & pg.path.notna()).sum())
    warn = [f"{len(orphan)} page files on disk not referenced by pages.parquet, e.g. {orphan[:2]}"] if orphan else []
    if err_and_path:
        warn.append(f"{err_and_path} pages have both an error and a stored path")
    return result("crawl_fk", "fail" if bad else "warn" if warn else "pass", f"{len(bad)} issues, {len(warn)} notes",
                  "0", f"{len(tg)} targets, {len(pg)} page attempts, {len(paths)} stored files, {len(on_disk)} on disk",
                  bad + warn)


def check_opendata_fk() -> dict:
    """opendata: matches point at real OSM / Wikidata rows, facts come from accepted matches, copied VF fields
    equal the record, not-in-VF rows are not matched to a VF record."""
    osm = set(table("kb/opendata/osm_health_facilities.parquet").osm_id)
    wd = set(table("kb/opendata/wikidata_medical_facilities.parquet").qid)
    m = table("kb/opendata/vf_opendata_match.parquet")
    c = table("kb/opendata/vf_candidates.parquet")
    f = table("kb/opendata/vf_opendata_facts.parquet")
    n = table("kb/opendata/opendata_not_in_vf.parquet")
    bad = []
    for name, d in [("match", m), ("candidates", c), ("facts", f), ("not_in_vf", n)]:
        miss = d[d.source_id.notna() & ~np.where(d.source == "osm", d.source_id.isin(osm), d.source_id.isin(wd))]
        if len(miss):
            bad.append(f"{name}: {len(miss)} source_id not in the {sorted(set(miss.source))} table, e.g. "
                       f"{miss.source_id.head(2).tolist()}")
    if set(zip(m.unique_id, m.source)) != set(zip(c.unique_id, c.source)):
        bad.append("vf_opendata_match and vf_candidates key sets differ")
    shared = [x for x in c.columns if x in m.columns and x not in ("unique_id", "source")]
    mm = m.set_index(["unique_id", "source"])[shared].sort_index()
    cc = c.set_index(["unique_id", "source"])[shared].sort_index()
    for col in mm.columns:
        a, b = mm[col], cc[col].reindex(mm.index)
        k = int((~((a == b) | (a.isna() & b.isna()))).sum())
        if k:
            bad.append(f"match.{col}: {k} rows differ from vf_candidates")
    acc = m[m.tier.isin(["high", "medium"])].set_index(["unique_id", "source"])
    fk = list(zip(f.unique_id, f.source))
    nacc = [k for k in fk if k not in acc.index]
    if nacc:
        bad.append(f"facts: {len(nacc)} rows from a match that is not high/medium, e.g. {nacc[:2]}")
    ok = [k in acc.index for k in fk]
    fa = f[ok]
    j = acc.reindex(list(zip(fa.unique_id, fa.source)))
    for col_f, col_m in [("source_id", "source_id"), ("match_tier", "tier")]:
        k = int((fa[col_f].values != j[col_m].values).sum())
        if k:
            bad.append(f"facts.{col_f}: {k} rows disagree with the match table")
    lic = {"osm": "ODbL", "wikidata": "CC0"}
    k = int(sum(lic[s] not in str(x) for s, x in zip(f.source, f.licence)))
    if k:
        bad.append(f"facts: {k} rows with a licence that does not match the source")
    r = usable().set_index("unique_id")
    k = int((m.vf_name.values != r["name"].reindex(m.unique_id).values).sum())
    if k:
        bad.append(f"match.vf_name differs from the raw name for {k} rows")
    matched = set(acc.source_id)
    both = n[n.source_id.isin(matched)]
    warn = []
    if len(both):
        warn.append(f"not_in_vf: {len(both)} rows are also an accepted match of a VF record, e.g. "
                    f"{both.source_id.head(3).tolist()}")
    exp_n = {"osm": len(osm), "wikidata": len(wd)}
    got = n.source.value_counts().to_dict()
    note = f"not_in_vf {got} vs source tables {exp_n}; accepted matches {len(acc)}"
    return result("opendata_fk", "fail" if bad else "warn" if warn else "pass", f"{len(bad)} issues", "0", note,
                  bad + warn)


def check_source_tables_fk() -> dict:
    """source_urls / source_domains / source_classes / source_page_checks agree with each other and with raw
    source_urls."""
    su = table("derived/v1/source_urls.parquet")
    sd = table("derived/v1/source_domains.parquet").set_index("domain")
    sc = table("derived/v1/source_classes.parquet").set_index("source_class")
    spc = table("derived/v1/source_page_checks.parquet")
    bad = []
    miss = sorted(set(su.domain) - set(sd.index))
    if miss:
        bad.append(f"{len(miss)} source_urls domains not in source_domains, e.g. {miss[:3]}")
    if set(sd.index) - set(su.domain):
        bad.append(f"{len(set(sd.index) - set(su.domain))} source_domains never cited")
    for d, name in [(su, "source_urls"), (sd.reset_index(), "source_domains")]:
        unk = sorted(set(d.source_class) - set(sc.index))
        if unk:
            bad.append(f"{name}.source_class not in source_classes: {unk}")
    rel = sd.reliability.reindex(su.domain).values
    k = int((~np.isclose(rel, su.domain_reliability.values)).sum())
    if k:
        bad.append(f"source_urls.domain_reliability differs from source_domains for {k} rows")
    g = su.groupby("domain")
    for col, exp in [("n_records", g.unique_id.nunique()), ("n_urls", g.size()), ("n_distinct_urls", g.url.nunique())]:
        k = int((sd[col] != exp.reindex(sd.index)).sum())
        if k:
            bad.append(f"source_domains.{col}: {k} domains do not reproduce from source_urls")
    gc = sd.groupby("source_class")
    for col, exp in [("n_domains", gc.size()), ("n_urls", su.groupby("source_class").size()),
                     ("n_records", su.groupby("source_class").unique_id.nunique())]:
        k = int((sc[col] != exp.reindex(sc.index)).sum())
        if k:
            bad.append(f"source_classes.{col}: {k} classes do not reproduce (e.g. "
                       f"{[(i, sc[col][i], exp.get(i)) for i in sc.index if sc[col][i] != exp.get(i)][:2]})")
    r = usable().set_index("unique_id").source_urls

    def urls(v):
        try:
            x = json.loads(v) if isinstance(v, str) else []
        except json.JSONDecodeError:
            return []
        return [s for s in x if isinstance(s, str) and s.strip()] if isinstance(x, list) else []

    exp = {(u, i): s for u, v in r.items() for i, s in enumerate(urls(v))}
    got = dict(zip(zip(su.unique_id, su.url_pos), su.url))
    if exp != got:
        diff = sorted(set(exp.items()) ^ set(got.items()))
        bad.append(f"source_urls vs raw source_urls: {len(diff)} (record, pos, url) differ, e.g. {diff[:2]}")
    pairs = set(zip(su.unique_id, su.url))
    k = [(a, b) for a, b in zip(spc.unique_id, spc.url) if (a, b) not in pairs]
    if k:
        bad.append(f"source_page_checks: {len(k)} (unique_id, url) not in source_urls, e.g. {k[:2]}")
    dom = dict(zip(su.url, su.domain))
    k = int(sum(dom.get(u) != d for u, d in zip(spc.url, spc.domain)))
    if k:
        bad.append(f"source_page_checks.domain disagrees with source_urls for {k} rows")
    return result("source_tables_fk", "fail" if bad else "pass", f"{len(bad)} issues", "0",
                  f"{len(su)} urls, {len(sd)} domains, {len(sc)} classes, {len(spc)} page checks", bad)


def check_facility_groups() -> dict:
    """Duplicate groups have one canonical record and the stated size; links point at usable records, never
    at the record itself, and are symmetric."""
    fg = table("derived/v1/facility_groups.parquet").set_index("unique_id")
    bad = []
    g = fg.dropna(subset=["dup_group_id"]).groupby("dup_group_id")
    can = g.is_canonical.sum()
    bad += [f"group {k}: {int(v)} canonical records" for k, v in can[can != 1].items()]
    size = g.size()
    gs = fg.dropna(subset=["dup_group_id"])
    k = gs[gs.group_size != gs.dup_group_id.map(size)]
    bad += [f"{u}: group_size {r.group_size} vs {size[r.dup_group_id]} members" for u, r in k.head(3).iterrows()]
    solo = fg[fg.dup_group_id.isna()]
    if (solo.group_size != 1).any() or (~solo.is_canonical).any():
        bad.append(f"{int(((solo.group_size != 1) | ~solo.is_canonical).sum())} ungrouped records with "
                   "group_size != 1 or not canonical")
    asym = []
    for col in ["possible_same_site", "co_located_with"]:
        for u, links in fg[col].items():
            for o in links:
                if o == u or o not in usable_ids():
                    bad.append(f"{u}.{col} -> {o}: {'self' if o == u else 'not usable'}")
                elif u not in set(fg[col].get(o, [])):
                    asym.append(f"{col}: {u} -> {o} not reciprocated")
    return result("facility_groups", "fail" if bad else "warn" if asym else "pass",
                  f"{len(bad)} issues, {len(asym)} one-way links", "0",
                  f"{gs.dup_group_id.nunique()} groups over {len(gs)} records", bad + asym)


def check_pathways_refs() -> dict:
    """care_pathways stages and rules reference defined capabilities and sources; capability kb_service names a
    graded derived/v1 service; the planner export uses only defined capabilities."""
    cp = jload("kb/pathways/care_pathways.json")
    caps = jload("kb/pathways/capabilities.json")["capabilities"]
    cap_ids = [c["id"] for c in caps]
    bad = [f"duplicate capability {k}" for k, v in Counter(cap_ids).items() if v > 1]
    srcs = set(cp["sources"])
    graded = set(table("derived/v1/grades.parquet").service)
    used = set()
    for p in cp["pathways"]:
        bad += [f"pathway {p['id']}: unknown source {s}" for s in p.get("sources", []) if s not in srcs]
        for st in p["stages"]:
            flat = st.get("requires_all", []) + [x for g in st.get("requires_any", []) for x in
                                                  (g if isinstance(g, list) else [g])]
            for c in flat:
                used.add(c)
                if c not in cap_ids:
                    bad.append(f"{p['id']}.{st['id']}: unknown capability {c}")
            for blk in [st.get("window"), st.get("dwell_minutes")]:
                if isinstance(blk, dict) and blk.get("basis") == "guideline" and blk.get("source") not in srcs:
                    bad.append(f"{p['id']}.{st['id']}: guideline number cites unknown source {blk.get('source')}")
    for c in caps:
        if c.get("kb_status") == "existing" and c.get("kb_service") not in graded:
            bad.append(f"capability {c['id']}: kb_service {c.get('kb_service')} is not a graded service")
        for ref in c.get("used_by", []):
            pid, _, sid = ref.partition(".")
            ok = any(p["id"] == pid and any(s["id"] == sid for s in p["stages"]) for p in cp["pathways"])
            if not ok:
                bad.append(f"capability {c['id']}: used_by {ref} does not exist")
    unused = sorted(set(cap_ids) - used)
    pl = set(jload("planner/out/planner_v1.json.gz")["capabilities"])
    bad += [f"planner capability {k} not defined" for k in pl - set(cap_ids)]
    return result("pathways_refs", "fail" if bad else "pass", f"{len(bad)} issues", "0",
                  f"{len(cp['pathways'])} pathways, {len(cap_ids)} capabilities; unused by any stage: {unused}", bad)


# ----------------------------------------------------------------------------------------------- app exports


def _facts_hash(facts: dict) -> str:
    """Same content hash as app/facts/build.py main()."""
    content = {k: v for k, v in facts.items() if k != "meta"} | {"meta": {**facts["meta"], "built_at": None}}
    return hashlib.sha256(json.dumps(content, separators=(",", ":"), sort_keys=True).encode()).hexdigest()[:12]


def check_app_hashes_and_sizes() -> dict:
    """facts.sha matches the content of facts.json.gz; pack index sha256/bytes and sizes.json match the files."""
    bad = []
    facts = jload("app/facts/out/facts.json.gz")
    sha = (ROOT / "app/facts/out/facts.sha").read_text().strip()
    if _facts_hash(facts) != sha:
        bad.append(f"facts.sha {sha} != recomputed {_facts_hash(facts)}")
    idx = jload("app/packs/out/index.json")["packs"]
    on_disk = {p.name.removesuffix(".json.gz") for p in (ROOT / "app/packs/out").glob("*.json.gz")}
    if set(idx) != on_disk:
        bad.append(f"index.json vs pack files differ: {sorted(set(idx) ^ on_disk)}")
    sizes = {r["slug"]: r for r in jload("app/packs/sizes.json")}
    for slug_, e in idx.items():
        p = ROOT / f"app/packs/out/{slug_}.json.gz"
        if not p.is_file():
            continue
        b = p.read_bytes()
        if hashlib.sha256(b).hexdigest()[:16] != e["sha256"] or len(b) != e["gzip_bytes"]:
            bad.append(f"{slug_}: index sha/bytes do not match the file")
        s = sizes.get(slug_)
        pk = json.loads(gzip.decompress(b))
        if s is None or s["gzip_bytes"] != len(b) or s["facilities"] != len(pk["fac"]["name"]) or \
                s["evidence_rows"] != len(pk["ev"]["s"]) or s["pins"] != len(pk["pins"]["d"]):
            bad.append(f"{slug_}: sizes.json disagrees with the pack")
        if pk["state"] != e["state"]:
            bad.append(f"{slug_}: pack state {pk['state']} != index {e['state']}")
    return result("app_hashes_and_sizes", "fail" if bad else "pass", f"{len(bad)} mismatches", "0",
                  f"facts.sha {sha}; {len(idx)} packs", bad)


def check_app_facts_integrity() -> dict:
    """facts.json.gz: facility ids usable and unique, copied values equal derived/v1, pair indices valid and pair
    values equal data_point_scores, quoted claims equal claims.parquet, PINs equal the gazetteer."""
    facts = jload("app/facts/out/facts.json.gz")
    fac = pd.DataFrame(facts["fac"])
    bad, warn = [], []
    if fac.id.duplicated().any():
        bad.append(f"{fac.id.duplicated().sum()} duplicate facility ids")
    nu = fac[~fac.id.isin(usable_ids())]
    if len(nu):
        bad.append(f"{len(nu)} facility ids not usable, e.g. {nu.id.head(2).tolist()}")
    loc = table("derived/v1/facility_location.parquet").set_index("unique_id")
    rt = table("derived/v1/record_trust.parquet").set_index("unique_id")
    ft = table("derived/v1/facility_trust.parquet").set_index("unique_id")
    exp_ids = set(loc.dropna(subset=["loc_lat", "loc_lon"]).index) - set(rt.index[rt.trust_level == "exclude_review"])
    if set(fac.id) != exp_ids:
        bad.append(f"facility set != located and not exclude_review: {len(set(fac.id) ^ exp_ids)} differ")
    f = fac.set_index("id")
    L = loc.reindex(f.index)
    for col, src, nd in [("lat", L.loc_lat, 5), ("lon", L.loc_lon, 5), ("p_e", ft.existence_score.reindex(f.index), 3),
                         ("p_l", ft.location_score.reindex(f.index), 3)]:
        k = int((~np.isclose(f[col].astype(float), src.round(nd), atol=10 ** -nd)).sum())
        if k:
            bad.append(f"fac.{col}: {k} values differ from derived/v1")
    for col, src in [("name", L["name"]), ("state", L.state_final), ("district", L.district), ("city", L.address_city)]:
        a, b = f[col], src
        k = int((~((a == b) | (a.isna() & b.isna()))).sum())
        if k:
            bad.append(f"fac.{col}: {k} values differ from facility_location")
    if not _in_india(f.lat, f.lon).all():
        bad.append(f"{int((~_in_india(f.lat, f.lon)).sum())} facilities outside India")
    d = table("derived/v1/data_point_scores.parquet")
    svd = d[d.dp_type == "service_claim"]
    sv = {(u, s): [g, ru, st, round(sc, 4), round(lo, 4), round(hi, 4), round(q, 4), round(sm, 4)]
          for u, s, g, ru, st, sc, lo, hi, q, sm in zip(svd.unique_id, svd.service, svd.grade, svd.rule, svd.status,
                                                         svd.score, svd.score_lo, svd.score_hi, svd.q_ev,
                                                         svd.score_model)}
    seen = set()
    nmis = 0
    for app_s, rows in facts["pairs"].items():
        v1s = APP_TO_V1[app_s]
        for r in rows:
            if not 0 <= r[0] < len(fac):
                bad.append(f"pairs.{app_s}: facility index {r[0]} out of range")
                continue
            u = fac.id[r[0]]
            if (u, app_s) in seen:
                bad.append(f"pairs.{app_s}: duplicate facility {u}")
            seen.add((u, app_s))
            if (u, v1s) not in sv:
                bad.append(f"pairs.{app_s}: {u} has no service_claim")
                continue
            exp = sv[(u, v1s)]
            if r[1:9] != exp:
                nmis += 1
                if nmis <= 3:
                    bad.append(f"pairs.{app_s} {u}: {r[1:9]} != dps {exp}")
            if not (0 <= r[5] <= r[4] <= r[6] <= 1):
                bad.append(f"pairs.{app_s} {u}: score outside its interval")
    fids = set(fac.id)
    n_exp = int(sum(1 for (u, s) in sv if s in APP_TO_V1.values() and u in fids))
    if len(seen) != n_exp:
        bad.append(f"{len(seen)} pairs exported, {n_exp} service claims exist for these facilities and services")
    cl = table("derived/v1/claims.parquet")
    cl = cl[cl.claim_id.isin(set(facts["claims"]))]
    src = {c: [f_, t, bool(no), a] for c, f_, t, no, a in zip(cl.claim_id, cl.field, cl.text, cl.nonoffer,
                                                              cl.attribution)}
    k = sum(1 for cid, v in facts["claims"].items() if src.get(cid) != list(v))
    if k:
        bad.append(f"{k} quoted claims differ from claims.parquet")
    p = table("derived/v1/pin_gazetteer.parquet")
    pg = p.dropna(subset=["lat", "lon"])
    fp = pd.DataFrame(facts["pins"])
    lost = sorted(set(pg.pin) - set(fp.pin))
    if lost:
        warn.append(f"facts pins: {len(lost)} gazetteer PINs with coordinates are dropped because district is "
                    f"null (packs and pin_index keep them), e.g. {lost[:3]}")
    pj = fp.merge(p, on="pin", suffixes=("", "_g"))
    k = int((~np.isclose(pj.lat, pj.lat_g.round(5), atol=1e-5) | (pj.district != pj.district_g)).sum())
    if k:
        bad.append(f"{k} facts pins differ from pin_gazetteer")
    nofac = int(fac.pin.isna().sum())
    return result("app_facts_integrity", "fail" if bad else "warn" if warn else "pass",
                  f"{len(bad)} issues, {nmis} pair value mismatches", "0",
                  f"{len(fac)} facilities ({nofac} without PIN), {len(seen)} pairs, {len(facts['claims'])} claims, "
                  f"{len(fp)} PINs", bad + warn)


def _decode_pack(pk: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sf, sp = pk["scale"]["fac"], pk["scale"]["pin"]
    fac = pd.DataFrame({"uid8": pk["fac"]["uid8"], "name": pk["fac"]["name"], "tel": pk["fac"]["tel"],
                        "tel_dir": pk["fac"]["tel_dir"], "loc_low": pk["fac"]["loc_low"],
                        "lat": np.cumsum(pk["fac"]["lat"]) / sf, "lon": np.cumsum(pk["fac"]["lon"]) / sf})
    ev = pd.DataFrame({k: pk["ev"][k] for k in pk["ev"]})
    ev["f"] = np.cumsum(ev.f)
    pins = pd.DataFrame({"pin": np.cumsum(pk["pins"]["pin"]), "lat": np.cumsum(pk["pins"]["lat"]) / sp,
                         "lon": np.cumsum(pk["pins"]["lon"]) / sp, "d": pk["pins"]["d"]})
    return fac, ev, pins


def check_app_packs_integrity() -> dict:
    """Every state pack decodes; facility uid8 resolve to one usable record with the same name and position;
    evidence rows, quotes and lists are in range; quote claim ids resolve to the same sentence; scores equal
    data_point_scores; PINs equal the gazetteer; pin_index covers the gazetteer."""
    loc = table("derived/v1/facility_location.parquet").set_index("unique_id")
    u8 = uid8_map()
    d = table("derived/v1/data_point_scores.parquet")
    sv = d[d.dp_type == "service_claim"].set_index(["unique_id", "service"])
    txt = claim_text()
    gz = table("derived/v1/pin_gazetteer.parquet").set_index("pin")
    inv = {v: k for k, v in APP_TO_V1.items()}
    bad, warn = [], []
    tot = Counter()
    for p in sorted((ROOT / "app/packs/out").glob("*.json.gz")):
        pk = json.loads(gzip.decompress(p.read_bytes()))
        fac, ev, pins = _decode_pack(pk)
        st = p.name.removesuffix(".json.gz")
        tot["packs"] += 1
        tot["fac"] += len(fac)
        tot["ev"] += len(ev)
        uids = fac.uid8.map(u8)
        if uids.isna().any():
            bad.append(f"{st}: {int(uids.isna().sum())} uid8 resolve to no usable record")
        if fac.uid8.duplicated().any():
            bad.append(f"{st}: duplicate uid8 in fac")
        L = loc.reindex(uids)
        if (L["name"].values != fac.name.values).any():
            bad.append(f"{st}: {(L['name'].values != fac.name.values).sum()} facility names differ")
        dl = np.maximum(np.abs(L.loc_lat.values - fac.lat.values), np.abs(L.loc_lon.values - fac.lon.values))
        if (dl > 1.01e-4).any():
            bad.append(f"{st}: {(dl > 1.01e-4).sum()} facility positions differ from facility_location by >1e-4 deg")
        if not _in_india(fac.lat, fac.lon).all():
            bad.append(f"{st}: facilities outside India")
        if ((ev.f < 0) | (ev.f >= len(fac))).any() or ((ev.s < 0) | (ev.s >= len(pk["services"]))).any():
            bad.append(f"{st}: evidence row facility/service index out of range")
            continue
        nq = len(pk["q"])
        if ((ev.q1 >= nq) | (ev.q2 >= nq) | (ev.q1 < -1) | (ev.q2 < -1)).any():
            bad.append(f"{st}: quote index out of range")
        empty_cid = 0
        for i, r in ev.iterrows():
            u = uids.iloc[r.f]
            s = inv.get(pk["services"][r.s], pk["services"][r.s])
            s = APP_TO_V1[pk["services"][r.s]]
            if (u, s) not in sv.index:
                bad.append(f"{st}: ev {i} {u}/{s} has no service_claim")
                continue
            x = sv.loc[(u, s)]
            if [r.p, r.lo, r.hi] != [int(np.round(x.score * 100)), int(np.round(x.score_lo * 100)),
                                     int(np.round(x.score_hi * 100))]:
                tot["score_mismatch"] += 1
            if r.likely != int(x.status == "verified_true"):
                tot["likely_mismatch"] += 1
            if x.status == "verified_false" or x.grade in ("attributed_elsewhere", "counter_evidence"):
                bad.append(f"{st}: excluded pair shipped {u}/{s}")
            for qi in (r.q1, r.q2):
                if qi < 0:
                    continue
                text, suffix = pk["q"][qi]
                if not suffix:
                    empty_cid += 1
                    continue
                cid = f"{u[:8]}:{suffix}"
                full = txt.get(cid)
                if full is None:
                    bad.append(f"{st}: quote claim {cid} unresolved")
                elif not (text == full or (text.endswith("...") and full.startswith(text[:-3]))):
                    bad.append(f"{st}: quote for {cid} is not its sentence")
        if empty_cid:
            tot["quotes_without_claim_id"] += empty_cid
            warn.append(f"{st}: {empty_cid} quotes carry no claim id")
        for s, lst in pk["index"].items():
            if len(lst) != len(pins):
                bad.append(f"{st}.index.{s}: {len(lst)} entries for {len(pins)} PINs")
            for li in set(lst):
                rows = pk["lists"][li]
                if any(not 0 <= e < len(ev) for e in rows):
                    bad.append(f"{st}.lists[{li}]: row out of range")
                elif any(pk["services"][ev.s[e]] != s for e in rows):
                    bad.append(f"{st}.lists[{li}]: row of another service under {s}")
        G = gz.reindex(pins.pin)
        if G.lat.isna().any():
            bad.append(f"{st}: {int(G.lat.isna().sum())} pack PINs not in the gazetteer")
        if (G.state.values != pk["state"]).any():
            bad.append(f"{st}: {(G.state.values != pk['state']).sum()} PINs belong to another state")
        dd = np.maximum(np.abs(G.lat.values - pins.lat.values), np.abs(G.lon.values - pins.lon.values))
        if (dd > 1.01e-3).any():
            bad.append(f"{st}: {(dd > 1.01e-3).sum()} PIN centroids differ from the gazetteer")
        dist = [pk["districts"][i] for i in pins.d]
        exp_d = G.district.fillna("").values
        if (np.array(dist) != exp_d).any():
            bad.append(f"{st}: PIN districts differ from the gazetteer")
        tot["pins"] += len(pins)
        tot["pins_blank_district"] += int((exp_d == "").sum())
    pi = jload("app/packs/out/pin_index.json")
    pin_all = np.cumsum(pi["pin"])
    gzp = table("derived/v1/pin_gazetteer.parquet").dropna(subset=["state", "lat", "lon"])
    if set(pin_all) != set(gzp.pin):
        bad.append(f"pin_index vs gazetteer PINs differ by {len(set(pin_all) ^ set(gzp.pin))}")
    if tot["pins"] != len(gzp):
        bad.append(f"sum of pack PINs {tot['pins']} != gazetteer PINs with state and coordinates {len(gzp)}")
    for k in ("score_mismatch", "likely_mismatch"):
        if tot[k]:
            bad.append(f"{tot[k]} evidence rows with {k.replace('_', ' ')}")
    return result("app_packs_integrity", "fail" if bad else "warn" if warn else "pass",
                  f"{len(bad)} issues; {tot['quotes_without_claim_id']} quotes without claim id",
                  "0", f"{dict(tot)}", bad + warn)


def check_planner_integrity() -> dict:
    """planner_v1.json.gz: facility ids usable and unique with derived/v1 coordinates; capability indices,
    probabilities and evidence in range; the planner can only name facilities the app's facts table knows."""
    pl = jload("planner/out/planner_v1.json.gz")
    f = pd.DataFrame(pl["facilities"])
    bad, warn = [], []
    if f.id.duplicated().any() or not set(f.id) <= usable_ids():
        bad.append("planner facility ids duplicated or not usable")
    loc = table("derived/v1/facility_location.parquet").set_index("unique_id").reindex(f.id)
    dl = np.maximum(np.abs(loc.loc_lat.values - f.lat.values), np.abs(loc.loc_lon.values - f.lon.values))
    if (dl > 1e-5).any():
        bad.append(f"{(dl > 1e-5).sum()} planner coordinates differ from facility_location")
    if not _in_india(f.lat, f.lon).all():
        bad.append("planner facilities outside India")
    for cap, c in pl["capabilities"].items():
        if not (len(c["i"]) == len(c["p"]) == len(c["e"])):
            bad.append(f"{cap}: i/p/e lengths differ")
        if any(not 0 <= i < len(f) for i in c["i"]) or len(set(c["i"])) != len(c["i"]):
            bad.append(f"{cap}: facility index out of range or repeated")
        if any(not 0 <= p <= 1 for p in c["p"]):
            bad.append(f"{cap}: probability outside [0, 1]")
    facts_ids = set(jload("app/facts/out/facts.json.gz")["fac"]["id"])
    extra = sorted(set(f.id) - facts_ids)
    rt = table("derived/v1/record_trust.parquet").set_index("unique_id")
    if extra:
        lv = Counter(rt.trust_level.reindex(extra))
        used = sorted({f.id[i] for c in pl["capabilities"].values() for i in c["i"]} & set(extra))
        warn.append(f"{len(extra)} planner facilities are not in facts.json ({dict(lv)}); {len(used)} carry "
                    f"capability evidence, e.g. {used[:3]}")
    gs = table("derived/v1/grades.parquet").set_index(["unique_id", "service"])
    caps = {c["id"]: c for c in jload("kb/pathways/capabilities.json")["capabilities"]}
    shipped_bad = Counter()
    for cap, c in pl["capabilities"].items():
        s = caps[cap].get("kb_service") if caps[cap].get("kb_status") == "existing" else None
        if not s:
            continue
        for i in c["i"]:
            g = gs.grade.get((f.id[i], s))
            if g in ("attributed_elsewhere", "counter_evidence"):
                shipped_bad[(cap, g)] += 1
    if shipped_bad:
        warn.append(f"planner capabilities include pairs the packs exclude: {dict(shipped_bad)}")
    pins = pl["pins"]
    if any(not 0 <= s < len(pins["states"]) for s in pins["s"]) or not _in_india(pins["lat"], pins["lon"]).all():
        bad.append("planner pins: state index out of range or point outside India")
    return result("planner_integrity", "fail" if bad else "warn" if warn else "pass", f"{len(bad)} issues, "
                  f"{len(warn)} notes", "0", f"{len(f)} facilities, {len(pl['capabilities'])} capabilities, "
                  f"{len(pins['s'])} PINs", bad + warn)


def check_exclude_review_not_shipped() -> dict:
    """Records cleaning marked exclude_review (all 12 are veterinary facilities) must not reach any app export.
    facts.json filters them; the packs and the planner must too."""
    rt = table("derived/v1/record_trust.parquet")
    ex = rt[rt.trust_level == "exclude_review"]
    ex_ids, ex8 = set(ex.unique_id), {u[:8]: n for u, n in zip(ex.unique_id, ex["name"])}
    bad = []
    if set(jload("app/facts/out/facts.json.gz")["fac"]["id"]) & ex_ids:
        bad.append("facts.json ships exclude_review records")
    for p in sorted((ROOT / "app/packs/out").glob("*.json.gz")):
        pk = json.loads(gzip.decompress(p.read_bytes()))
        fac, ev, _ = _decode_pack(pk)
        for i, u in enumerate(fac.uid8):
            if u in ex8:
                svcs = sorted({pk["services"][s] for f_, s in zip(ev.f, ev.s) if f_ == i})
                bad.append(f"pack {p.name}: {u} {ex8[u]!r} shipped for {svcs}")
    pl = jload("planner/out/planner_v1.json.gz")
    ids = pl["facilities"]["id"]
    for cap, c in pl["capabilities"].items():
        for i, pr in zip(c["i"], c["p"]):
            if ids[i] in ex_ids:
                bad.append(f"planner capability {cap}: {ids[i][:8]} {ex8[ids[i][:8]]!r} p={pr}")
    reasons = Counter(r for lst in ex.trust_reasons for r in lst)
    return result("exclude_review_not_shipped", "fail" if bad else "pass", f"{len(bad)} leaks of {len(ex)} "
                  "excluded records", "0", f"exclude_review reasons: {dict(reasons)}", bad)


# ----------------------------------------------------------------------------------------------- ranges, enums

LATLON_PAIRS = [("lat", "lon"), ("loc_lat", "loc_lon"), ("raw_lat", "raw_lon"), ("alt_lat", "alt_lon"),
                ("cand_lat", "cand_lon"), ("dir_lat", "dir_lon")]
STRICT_LATLON = {("derived/v1/facility_location.parquet", "loc_lat"), ("derived/v1/pin_gazetteer.parquet", "lat"),
                 ("derived/v1/place_gazetteer.parquet", "lat"), ("derived/v1/facility_location.parquet", "alt_lat")}


def check_lat_lon_bounds() -> dict:
    """Coordinates inside India. Ranking points and gazetteers must be (fail); raw and third-party points are
    reported (warn)."""
    bad, warn, rows = [], [], []
    for f in tabular_files():
        df = table(f)
        for la, lo in LATLON_PAIRS:
            if la not in df.columns or lo not in df.columns:
                continue
            a, b = pd.to_numeric(df[la], errors="coerce"), pd.to_numeric(df[lo], errors="coerce")
            have = a.notna() & b.notna()
            half = a.notna() ^ b.notna()
            out = have & ~_in_india(a.fillna(0), b.fillna(0))
            zero = have & (a == 0) & (b == 0)
            rows.append({"file": f, "lat": la, "n": int(have.sum()), "outside": int(out.sum()), "zero": int(zero.sum()),
                         "half_null": int(half.sum())})
            if out.any() or half.any():
                idc = next((c for c in ("unique_id", "pin", "osm_id", "qid", "name") if c in df.columns), None)
                ex = df.loc[out, idc].astype(str).head(3).tolist() if idc else []
                msg = f"{f} {la}/{lo}: {int(out.sum())} outside India ({int(zero.sum())} at 0,0), " \
                      f"{int(half.sum())} half-null of {int(have.sum())}; e.g. {ex}"
                (bad if (f, la) in STRICT_LATLON else warn).append(msg)
    for name, pts in [("queries.json", [(q["lat"], q["lon"]) for q in jload("model/gold/queries.json")])]:
        a = np.array(pts, float)
        if not _in_india(a[:, 0], a[:, 1]).all():
            bad.append(f"{name}: query points outside India")
    pd.DataFrame(rows).to_csv(OUT / "lat_lon_bounds.csv", index=False)
    return result("lat_lon_bounds", "fail" if bad else "warn" if warn else "pass",
                  f"{len(bad)} strict failures, {len(warn)} reported columns",
                  f"lat {LAT_MIN}-{LAT_MAX}, lon {LON_MIN}-{LON_MAX}", "outputs/lat_lon_bounds.csv", bad + warn)


PROB_COLS = re.compile(r"^(score|score_lo|score_hi|score_model|q_ev|source_support|existence_score|location_score|"
                       r"location_lo|location_hi|attribution_score|service_score_mean|overall_score|overall_lo|"
                       r"reliability|ci05|ci95|class_prior_mean|median_domain_reliability|domain_reliability.*|"
                       r"domain_reliability|share_.*|top_blame_share|match_conf|weight.*|pooled_rate|confirm_.*|"
                       r"token_coverage|share_covered|confidence|.*_rate|p|lo|hi|p_e|p_l)$")
INTERVALS = [("derived/v1/data_point_scores.parquet", "score_lo", "score", "score_hi"),
             ("derived/v1/facility_trust.parquet", "location_lo", "location_score", "location_hi"),
             ("derived/v1/facility_trust.parquet", "overall_lo", "overall_score", None),
             ("derived/v1/source_domains.parquet", "ci05", "reliability", "ci95"),
             ("derived/v1/source_classes.parquet", "ci05", "reliability", "ci95"),
             ("derived/v1/source_classes.parquet", "domain_reliability_p10", "median_domain_reliability",
              "domain_reliability_p90"),
             ("derived/v1/source_urls.parquet", "ci05", "domain_reliability", "ci95")]


def check_probabilities() -> dict:
    """Probability-like columns lie in [0, 1]; every interval satisfies lo <= point <= hi; verified overrides
    carry the documented values."""
    bad, rows = [], []
    for f in tabular_files():
        if any(s in f for s in ("/qa/", "handcheck", "selfcheck", "review/")):
            continue
        df = table(f)
        for c in df.columns:
            # opendata 'score' is a 0-100 rapidfuzz name score, not a probability
            if not PROB_COLS.match(c) or (f.startswith("kb/opendata/") and c == "score"):
                continue
            x = pd.to_numeric(df[c], errors="coerce")
            if x.notna().sum() == 0:
                continue
            out = x.notna() & ((x < 0) | (x > 1))
            rows.append({"file": f, "column": c, "n": int(x.notna().sum()), "outside": int(out.sum()),
                         "min": float(x.min()), "max": float(x.max())})
            if out.any():
                bad.append(f"{f}.{c}: {int(out.sum())} outside [0, 1] (min {x.min()}, max {x.max()})")
    for f, lo, mid, hi in INTERVALS:
        df = table(f)
        k = (df[lo] > df[mid] + 1e-9) | ((df[mid] > df[hi] + 1e-9) if hi else False)
        if k.any():
            bad.append(f"{f}: {int(k.sum())} rows with {lo} <= {mid}{' <= ' + hi if hi else ''} broken")
    d = table("derived/v1/data_point_scores.parquet")
    exp = {"verified_true": (0.97, 0.90, 0.995), "verified_false": (0.03, 0.005, 0.10)}
    for st, (s, lo, hi) in exp.items():
        x = d[(d.status == st) & (d.rule != "EMAIL_PLACEHOLDER")]
        k = ~(np.isclose(x.score, s) & np.isclose(x.score_lo, lo) & np.isclose(x.score_hi, hi))
        if k.any():
            bad.append(f"{int(k.sum())} {st} points without the documented {s} [{lo}, {hi}]")
    em = d[d.rule == "EMAIL_PLACEHOLDER"]
    if not np.isclose(em.score, 0.01).all() or (em.status != "verified_false").any():
        bad.append("placeholder emails not scored 0.01 verified_false")
    pd.DataFrame(rows).to_csv(OUT / "probabilities.csv", index=False)
    return result("probabilities", "fail" if bad else "pass", f"{len(rows)} columns checked, {len(bad)} issues",
                  "[0, 1]; lo <= point <= hi", "outputs/probabilities.csv", bad)


COUNT_COLS = re.compile(r"^(n_.*|k_.*|.*_count|count|rows|records|.*_rows|page_chars|text_len|chrome_len|"
                        r"group_size|rank|idx|url_pos|seg_start|alpha|beta|credit|blame|effective_.*|a|b|"
                        r"handcheck_.*|dev_true|dev_false|radius_km|spread_km|km|loc_radius|beds|version|"
                        r"raw_coords_to_pin_km|d_consensus_km|pin_to_cand_km|page_.*|dataset_claims|confirmed|"
                        r"claims_.*|sentences.*|facilities.*|with_candidate|covered_.*|chain_home_only|"
                        r"qty_value|page_sentences_.*|value_num)$")


def check_counts_nonneg() -> dict:
    """Counts, distances and sizes are >= 0; count columns hold integers."""
    bad, warn, n = [], [], 0
    for f in tabular_files():
        if any(s in f for s in ("/qa/", "handcheck", "selfcheck", "review/")):
            continue
        df = table(f)
        for c in df.columns:
            if not COUNT_COLS.match(c) or df[c].dtype == bool:
                continue
            x = pd.to_numeric(df[c], errors="coerce")
            if x.notna().sum() == 0:
                continue
            n += 1
            neg = x < 0
            if neg.any():
                bad.append(f"{f}.{c}: {int(neg.sum())} negative values (min {x.min()})")
            if c.startswith(("n_", "k_")) and (x.dropna() % 1 != 0).any():
                warn.append(f"{f}.{c}: non-integer counts ({int((x.dropna() % 1 != 0).sum())})")
    vf = table("kb/vf_details/out/facts.parquet")
    zero = vf[(vf.fact_type.isin(["unit_beds", "equipment_count", "staffing"])) & (vf.value_num <= 0) &
              (vf.status != "excluded")]
    if len(zero):
        bad.append(f"vf facts: {len(zero)} non-excluded counts <= 0, e.g. {zero.fact_id.head(2).tolist()}")
    return result("counts_nonneg", "fail" if bad else "warn" if warn else "pass", f"{n} columns, {len(bad)} with "
                  f"negatives, {len(warn)} with fractional counts", ">= 0", "", bad + warn)


def _year(v) -> float:
    m = re.search(r"\b(1[6-9]\d\d|20\d\d)\b", str(v))
    return float(m.group(1)) if m else np.nan


def check_dates_and_years() -> dict:
    """Founding years plausible (1600-2026); crawl and evidence timestamps parse and are not in the future
    relative to the build day (2026-11-21)."""
    bad, warn = [], []
    r = usable()
    ye = r.yearEstablished[r.yearEstablished.map(lambda v: isinstance(v, str) and is_null_like(v) is None)]
    yrs = ye.map(_year)
    unparsed = ye[yrs.isna()]
    odd = ye[(yrs < 1700) | (yrs > 2026)]
    if len(unparsed):
        warn.append(f"raw yearEstablished: {len(unparsed)} of {len(ye)} non-null values have no year, e.g. "
                    f"{unparsed.head(3).tolist()}")
    if len(odd):
        warn.append(f"raw yearEstablished: {len(odd)} outside 1700-2026, e.g. {odd.head(3).tolist()}")
    limit = pd.Timestamp("2026-11-22T00:00:00Z")
    cols = [("kb/crawl/pages.parquet", "fetched_at"), ("kb/crawl/sites.parquet", "finished_at"),
            ("kb/web_evidence/out/web_services.parquet", "fetched_at"),
            ("kb/web_evidence/out/web_details.parquet", "fetched_at"),
            ("kb/web_evidence/out/web_hours.parquet", "fetched_at"),
            ("kb/opendata/vf_opendata_facts.parquet", "observed_at"),
            ("kb/opendata/osm_health_facilities.parquet", "last_edit"),
            ("kb/opendata/osm_health_facilities.parquet", "check_date")]
    for f, c in cols:
        s = table(f)[c].dropna()
        t = pd.to_datetime(s, utc=True, errors="coerce", format="mixed")
        if t.isna().sum():
            (bad if c in ("fetched_at", "finished_at") else warn).append(
                f"{f}.{c}: {int(t.isna().sum())} unparseable, e.g. {s[t.isna()].head(2).tolist()}")
        fut = t > limit
        if fut.any():
            (bad if c in ("fetched_at", "finished_at", "observed_at") else warn).append(
                f"{f}.{c}: {int(fut.sum())} after the build day, e.g. {s[fut].head(2).tolist()}")
    inc = table("kb/opendata/vf_opendata_facts.parquet")
    iy = inc[inc.field == "inception"].value.map(_year)
    if ((iy < 1600) | (iy > 2026)).any():
        warn.append(f"opendata inception years outside 1600-2026: {int(((iy < 1600) | (iy > 2026)).sum())}")
    return result("dates_and_years", "fail" if bad else "warn" if warn else "pass", f"{len(bad)} fail, "
                  f"{len(warn)} notes", "parseable, 1700-2026, not after 2026-11-21",
                  f"{len(ye)} raw yearEstablished values; year median {yrs.median()}", bad + warn)


ENUMS = {
    ("derived/v1/claims.parquet", "attribution"): {"own_anchored", "unanchored", "ambiguous", "other_facility"},
    ("derived/v1/claims.parquet", "field"): set(FIELD4.values()),
    ("derived/v1/data_point_scores.parquet", "dp_type"): set(DP_PREFIX),
    ("derived/v1/data_point_scores.parquet", "status"): {"verified_true", "verified_false", "unverified"},
    ("derived/v1/data_point_scores.parquet", "attribution"): {"own_anchored", "unanchored", "ambiguous",
                                                              "other_facility"},
    ("derived/v1/data_point_scores.parquet", "gold_split"): {"dev", "test"},
    ("derived/v1/grades.parquet", "grade"): {"strong", "moderate", "weak", "tag_only", "attributed_elsewhere",
                                             "counter_evidence"},
    ("derived/v1/grades.parquet", "service"): set(APP_TO_V1.values()) | {"icu"},
    ("derived/v1/gold_pairs.parquet", "split"): {"dev", "test"},
    ("derived/v1/gold_pairs.parquet", "exists"): {"yes", "no", "unclear", "conflict"},
    ("derived/v1/gold_pairs.parquet", "location_ok"): {"yes", "no", "unclear", "conflict"},
    ("derived/v1/gold_pairs.parquet", "service_verdict"): {"confirmed", "contradicted", "no_info", "conflict"},
    ("derived/v1/facility_location.parquet", "loc_conf"): {"high", "medium", "low", "disputed"},
    ("derived/v1/record_trust.parquet", "trust_level"): {"no_concerns", "minor", "caution", "exclude_review"},
    ("derived/v1/source_urls.parquet", "url_kind"): {"about", "list", "unverified"},
    ("derived/v1/source_urls.parquet", "source_class"): set(jload("derived/v1/build_stats.json")["s1_stats"]
                                                            ["source_class"]),
    ("derived/v1/facility_trust.parquet", "location_status"): {"verified_true", "verified_false", "unverified"},
    ("kb/vf_details/out/facts.parquet", "status"): {"ok", "flagged", "excluded"},
    ("kb/vf_details/out/facts.parquet", "polarity"): {"positive", "neutral", "negative"},
    ("kb/vf_details/out/facts.parquet", "method"): {"regex", "llm", "structured"},
    ("kb/web_evidence/out/web_details.parquet", "status"): {"ok", "flagged", "excluded"},
    ("kb/web_evidence/out/web_hours.parquet", "status"): {"ok", "flagged", "excluded"},
    ("kb/web_evidence/out/web_services.parquet", "strength"): {"strong", "weak", "none"},
    ("kb/web_evidence/out/web_services.parquet", "scope"): {"own_site", "branch_page", "chain_home"},
    ("kb/web_evidence/out/web_services.parquet", "identity_conf"): {"high", "medium", "low", "none"},
    ("kb/web_evidence/out/site_identity.parquet", "confidence"): {"high", "medium", "low", "none"},
    ("kb/web_evidence/out/site_identity.parquet", "kind"): {"site", "branch", "shared_home"},
    ("kb/crawl/targets.parquet", "kind"): {"site", "branch", "shared_home"},
    ("kb/opendata/vf_opendata_match.parquet", "tier"): {"high", "medium", "conflict"},
    ("kb/opendata/vf_opendata_match.parquet", "source"): {"osm", "wikidata"},
    ("kb/taxonomy/specialty_map.csv", "method"): {"rule", "fuzzy", "llm", "manual"},
}
REASON_EXTRA = {"GOLD_TRUE", "GOLD_FALSE", "SOURCES_ABOVE_AVERAGE", "SOURCES_BELOW_AVERAGE", "PAGE_CHECKED"}


def check_enums() -> dict:
    """Categorical columns hold only their documented values; reason_codes tokens are rules or documented
    modifiers. Writes the value counts of every low-cardinality string column to outputs/enum_values.csv."""
    bad = []
    for (f, c), allowed in ENUMS.items():
        vals = table(f)[c].dropna()
        unk = vals[~vals.isin(allowed)].value_counts()
        if len(unk):
            bad.append(f"{f}.{c}: undocumented {unk.head(5).to_dict()}")
    rules = set(table("derived/v1/evidence_rules.parquet").rule) | REASON_EXTRA
    for f, c in [("derived/v1/data_point_scores.parquet", "reason_codes"),
                 ("derived/v1/facility_trust.parquet", "location_reason_codes")]:
        toks = Counter(t for v in table(f)[c].dropna() for t in v.split("|"))
        unk = {t: n for t, n in toks.items() if t not in rules}
        if unk:
            bad.append(f"{f}.{c}: unknown tokens {dict(list(unk.items())[:5])}")
    d = table("derived/v1/data_point_scores.parquet")
    gt = d.reason_codes.fillna("").str.contains("GOLD_TRUE")
    gf = d.reason_codes.fillna("").str.contains("GOLD_FALSE")
    k = int(((gt != (d.status == "verified_true")) | (gf != ((d.status == "verified_false") &
                                                             (d.rule != "EMAIL_PLACEHOLDER")))).sum())
    if k:
        bad.append(f"{k} data points where GOLD_TRUE/GOLD_FALSE disagrees with status")
    rows = []
    p = pd.read_csv(OUT / "schema_profile.csv")
    for r in p[(p.distinct <= 40) & (p.distinct > 0) & p.type.str.contains("string") &
               ~p.type.str.contains("list")].itertuples():
        for v, n in table(r.file)[r.column].value_counts(dropna=False).items():
            rows.append({"file": r.file, "column": r.column, "value": v, "n": int(n)})
    pd.DataFrame(rows).to_csv(OUT / "enum_values.csv", index=False)
    return result("enums", "fail" if bad else "pass", f"{len(ENUMS)} enum columns, {len(bad)} with undocumented "
                  "values", "documented sets only", "outputs/enum_values.csv", bad)


def check_location_fk() -> dict:
    """facility_location: raw copies equal raw, PIN parses from the raw postcode and resolves in the gazetteer,
    district and NFHS keys resolve in their reference tables, every record has a ranking point."""
    loc = table("derived/v1/facility_location.parquet").set_index("unique_id")
    r = usable().set_index("unique_id").reindex(loc.index)
    gz = table("derived/v1/pin_gazetteer.parquet")
    nf = pd.read_parquet(RAW / "nfhs_5_district_health_indicators.parquet", columns=["district_name", "state_ut"])
    bad, warn = [], []
    for c, rc in [("raw_lat", "latitude"), ("raw_lon", "longitude")]:
        k = int((~((loc[c] == r[rc]) | (loc[c].isna() & r[rc].isna()))).sum())
        if k:
            bad.append(f"{c}: {k} differ from raw {rc}")
    for c in ["name", "address_city", "address_stateOrRegion"]:
        k = int((~((loc[c] == r[c]) | (loc[c].isna() & r[c].isna()))).sum())
        if k:
            bad.append(f"{c}: {k} differ from raw")
    if loc.loc_lat.isna().any():
        bad.append(f"{int(loc.loc_lat.isna().sum())} records without a ranking point")
    pins = set(gz.pin)
    lp = loc.pin.dropna().astype(int)
    miss = lp[~lp.isin(pins)]
    if len(miss):  # invalid postcodes kept as the pin (not in the India Post directory either)
        warn.append(f"{len(miss)} facility PINs not in pin_gazetteer, e.g. "
                    f"{[(u, int(v)) for u, v in miss.head(3).items()]}")
    rawpin = r.address_zipOrPostcode.map(lambda z: re.sub(r"[\s-]", "", str(z or "")))
    ok = rawpin.str.fullmatch(r"[1-9]\d{5}")
    parsed = rawpin.where(ok).astype(float)
    diff = loc.pin.notna() & (parsed != loc.pin)
    if diff.any():
        warn.append(f"{int(diff.sum())} records whose pin differs from the raw postcode (repaired), e.g. "
                    f"{loc.index[diff][:3].tolist()}")
    gdist = set(zip(gz.state, gz.district.dropna())) | {(s, d) for s, ds in zip(gz.state, gz.districts)
                                                       for d in (ds if ds is not None else [])}
    dk = loc.dropna(subset=["district"])
    nod = [u for u, s, d in zip(dk.index, dk.district_state, dk.district) if (s, d) not in gdist]
    if nod:
        warn.append(f"{len(nod)} (district_state, district) pairs not in the PIN gazetteer, e.g. {nod[:3]}")
    nk = set(zip(nf.state_ut, nf.district_name))
    nn = loc.dropna(subset=["nfhs_district_name"])
    badn = [u for u, s, d in zip(nn.index, nn.nfhs_state_ut, nn.nfhs_district_name) if (s, d) not in nk]
    if badn:
        bad.append(f"{len(badn)} NFHS keys (nfhs_state_ut, nfhs_district_name) not in the NFHS table, e.g. {badn[:3]}")
    nonfhs = loc[loc.nfhs_district_name.isna()]
    states = set(gz.state.dropna())
    bs = loc[~loc.state_final.isin(states)]
    if len(bs):
        bad.append(f"{len(bs)} state_final values not a gazetteer state: {bs.state_final.value_counts().head(3).to_dict()}")
    if (loc.district_state.notna() & (loc.district_state != loc.state_final)).any():
        warn.append(f"{int((loc.district_state.notna() & (loc.district_state != loc.state_final)).sum())} records "
                    "with district_state != state_final")
    return result("location_fk", "fail" if bad else "warn" if warn else "pass", f"{len(bad)} issues, {len(warn)} "
                  "notes", "0", f"{len(loc)} records; {int(loc.pin.isna().sum())} without PIN, {len(nonfhs)} without "
                  f"an NFHS key ({nonfhs.nfhs_how.value_counts(dropna=False).to_dict()})", bad + warn)


def check_v2_contract() -> dict:
    """Contract for derived/v2/facility_service_scores.parquet (#11), as the app (app/facts/build.py,
    app/packs/build_packs.py) reads it. derived/v2 is being written now, so the check runs only when
    INTEGRITY_CHECK_V2=1 and never judges the scores themselves."""
    p = ROOT / "derived/v2/facility_service_scores.parquet"
    if os.environ.get("INTEGRITY_CHECK_V2") != "1" or not p.is_file():
        return result("v2_contract", "warn", "not run", "contract holds",
                      f"skipped: derived/v2 is in flux (exists: {p.is_file()}); set INTEGRITY_CHECK_V2=1 to run")
    d = pd.read_parquet(p)
    bad = []
    need = ["unique_id", "service_id", "band", "p", "lo", "hi", "as_of"]
    miss = [c for c in need if c not in d.columns]
    if miss:
        return result("v2_contract", "fail", f"missing {miss}", "columns present", str(list(d.columns)))
    app_ids = set(APP_TO_V1) | set(APP_TO_V1.values()) | _taxonomy_ids()[0]
    if d.duplicated(["unique_id", "service_id"]).any():
        bad.append(f"{int(d.duplicated(['unique_id', 'service_id']).sum())} duplicate (unique_id, service_id)")
    if not set(d.unique_id) <= usable_ids():
        bad.append(f"{len(set(d.unique_id) - usable_ids())} unique_id not usable")
    if set(d.service_id) - app_ids:
        bad.append(f"unknown service_id {sorted(set(d.service_id) - app_ids)[:5]}")
    if set(d.band) - {"likely", "not_verified", "unlikely"}:
        bad.append(f"unknown band {sorted(set(d.band) - {'likely', 'not_verified', 'unlikely'})}")
    for c in ["p", "lo", "hi"]:
        if d[c].isna().any() or ((d[c] < 0) | (d[c] > 1)).any():
            bad.append(f"{c}: null or outside [0, 1]")
    if ((d.lo > d.p + 1e-9) | (d.p > d.hi + 1e-9)).any():
        bad.append("lo <= p <= hi broken")
    ex = set(table("derived/v1/record_trust.parquet").query("trust_level == 'exclude_review'").unique_id)
    if set(d.unique_id) & ex:
        bad.append(f"{len(set(d.unique_id) & ex)} exclude_review (veterinary) records scored")
    return result("v2_contract", "fail" if bad else "pass", f"{len(bad)} contract breaks", "0",
                  f"{len(d)} rows", bad)


def check_web_quotes_in_pages() -> dict:
    """Exhaustive: every web_services / web_details / web_hours row points at a stored page file whose text
    (or chrome_text) holds its segment at seg_start and contains its quote; the file's target and fetch time
    match the row."""
    cache: dict[str, dict] = {}

    def page(path: str) -> dict | None:
        if path not in cache:
            try:
                with gzip.open(ROOT / path, "rt", encoding="utf-8") as fh:
                    cache[path] = json.load(fh)
            except (OSError, ValueError):
                cache[path] = None
        return cache[path]

    bad, stats = [], Counter()
    w = "kb/web_evidence/out/"
    pg = table("kb/crawl/pages.parquet")[["target_id", "url", "path", "final_url", "fetched_at"]]
    for n, seg_col in [("web_services", "segment"), ("web_details", "source_text"), ("web_hours", "source_text")]:
        d = table(w + n + ".parquet")
        ex = []
        for r in d[["path", "field", "seg_start", seg_col, "quote"]].itertuples(index=False):
            stats[f"{n}_rows"] += 1
            o = page(r.path)
            if o is None:
                stats[f"{n}_unreadable"] += 1
                continue
            txt = o.get(r.field) or ""
            seg = getattr(r, seg_col)
            at = txt[r.seg_start:r.seg_start + len(seg)] == seg
            if not at:
                stats[f"{n}_segment_not_at_offset"] += 1
                if seg not in txt:
                    stats[f"{n}_segment_not_on_page"] += 1
                    if len(ex) < 2:
                        ex.append(f"{n}: segment not on page {r.path} {r.field}@{r.seg_start}")
            if r.quote not in txt:
                stats[f"{n}_quote_not_on_page"] += 1
        # page files are de-duplicated by content, so the file's own target/time is the first fetch's;
        # the row must instead match its crawl pages row on (target_id, url)
        m = d[["target_id", "url", "path", "final_url", "fetched_at"]].merge(
            pg, on=["target_id", "url"], how="left", suffixes=("", "_p"))
        stats[f"{n}_no_pages_row"] = int(m.path_p.isna().sum())
        for c in ["path", "final_url", "fetched_at"]:
            stats[f"{n}_{c}_differs_from_pages"] = int((m[c] != m[c + "_p"])[m.path_p.notna()].sum())
        bad += ex
    pi = table(w + "page_identity.parquet")
    for qc, fc in [("name_quote", "name_field"), ("pin_quote", "pin_field"), ("loc_quote", "loc_field")]:
        x = pi.dropna(subset=[qc, fc])
        for path, fld, q in zip(x.path, x[fc], x[qc]):
            stats["identity_quotes"] += 1
            o = page(path)
            if o is None or q.lower() not in (o.get(fld) or "").lower():
                stats["identity_quote_not_on_page"] += 1
                if len(bad) < 6:
                    bad.append(f"page_identity {qc} not in {fld} of {path}: {q[:60]!r}")
    hard = {k: v for k, v in stats.items() if k.endswith(("unreadable", "not_on_page", "no_pages_row",
                                                          "differs_from_pages"))}
    soft = {k: v for k, v in stats.items() if k.endswith("not_at_offset")}
    st = "fail" if any(hard.values()) else "warn" if any(soft.values()) else "pass"
    return result("web_quotes_in_pages", st, f"{sum(hard.values())} rows not found on their page, "
                  f"{sum(soft.values())} segments not at seg_start", "0", f"{dict(stats)}; {len(cache)} files",
                  bad + [f"{k}: {v}" for k, v in {**hard, **soft}.items() if v])


def check_copied_columns() -> dict:
    """Columns documented as copies (names, facility type, claim attributes) equal their source."""
    r = usable().set_index("unique_id")
    bad, n = [], 0
    for f, cols in [("derived/v1/grades.parquet", ["name", "facilityTypeId"]),
                    ("derived/v1/grades_v1.parquet", ["name", "facilityTypeId"]),
                    ("derived/v1/facility_groups.parquet", ["name"]), ("derived/v1/record_trust.parquet", ["name"]),
                    ("derived/v1/facility_trust.parquet", ["name"]),
                    ("kb/opendata/vf_opendata_match.parquet", ["vf_name"])]:
        d = table(f)
        for c in cols:
            src = r["name" if c == "vf_name" else c].reindex(d.unique_id).values
            k = int((~((d[c].values == src) | (pd.isna(d[c].values) & pd.isna(src)))).sum())
            n += 1
            if k:
                bad.append(f"{f}.{c}: {k} rows differ from raw")
    cl = table("derived/v1/claims.parquet").set_index("claim_id")
    for f, cols in [("kb/taxonomy/out/lexicon_matches.parquet", ["unique_id", "field", "attribution", "kind",
                                                               "dup_in_record"]),
                    ("kb/vf_details/out/facts.parquet", ["unique_id", "attribution", "context", "kind",
                                                         "dup_in_record"])]:
        d = table(f).dropna(subset=["claim_id"])
        j = cl.reindex(d.claim_id)
        for c in cols:
            a, b = d[c].values, j[c].values
            k = int((~((a == b) | (pd.isna(a) & pd.isna(b)))).sum())
            n += 1
            if k:
                bad.append(f"{f}.{c}: {k} rows differ from claims.parquet")
    return result("copied_columns", "fail" if bad else "pass", f"{n - len(bad)}/{n} copied columns equal", "all",
                  "names and facility type vs raw; claim attributes vs claims.parquet", bad)


def check_source_url_repeats() -> dict:
    """A URL repeated inside one record's source_urls is kept as separate rows in source_urls, so it counts
    twice in the per-record attribution weights (s5_fit sums kind weights over a record's URLs) and in
    source_domains.n_urls."""
    su = table("derived/v1/source_urls.parquet")
    d = su[su.duplicated(["unique_id", "url"])]
    rec = d.unique_id.nunique()
    top = d.groupby("unique_id").size().sort_values(ascending=False).head(3)
    return result("source_url_repeats", "warn" if len(d) else "pass",
                  f"{len(d)} repeated (record, url) rows of {len(su)} in {rec} of {su.unique_id.nunique()} records",
                  "0", f"domains most affected: {d.domain.value_counts().head(3).to_dict()}",
                  [f"{u}: {n} repeats" for u, n in top.items()])

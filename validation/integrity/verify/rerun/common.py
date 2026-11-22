"""Shared loaders, table registry and result helpers for the integrity checks.

Read-only: nothing here writes outside validation/integrity/. Loaders are cached so a suite run reads each
table once.
"""
from __future__ import annotations

import glob
import gzip
import hashlib
import json
import math
import os
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "validation" / "integrity" / "verify" / "rerun"
OUT = HERE / "outputs"
V1 = ROOT / "derived" / "v1"
RAW = ROOT / "data" / "raw"

# India bounding box (Indira Point 6.75 N to Siachen 37.1 N; Gujarat 68.1 E to Arunachal 97.4 E), padded.
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 6.0, 37.5, 68.0, 97.5
# Case-sensitive: lowercase "none" is a documented enum value (identity_conf, strength, name_how, lang).
NULL_STRINGS = {"null", "Null", "NULL", "None", "nan", "NaN", "N/A", "n/a", "nil", "Nil", "NIL", "undefined"}
EMPTY_CONTAINERS = {"[]", "{}", '[""]', "['']"}
UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# Data layers in scope. model/gold/v3 is excluded by name so it is never opened.
SCOPE_GLOBS = [
    "derived/v1/*.parquet", "derived/v1/*.csv", "derived/v1/*.json",
    "kb/**/*.parquet", "kb/**/*.csv", "kb/**/*.json", "kb/**/*.jsonl",
    "app/facts/out/*", "app/packs/out/*", "app/packs/sizes.json",
    "planner/out/*", "model/gold/*.json",
]

# Primary keys (documented grain). None = no natural key (aggregate or free-form file).
PRIMARY_KEYS: dict[str, list[str] | None] = {
    "derived/v1/claims.parquet": ["claim_id"],
    "derived/v1/data_point_scores.parquet": ["dp_id"],
    "derived/v1/evidence_rules.parquet": ["rule"],
    "derived/v1/facility_groups.parquet": ["unique_id"],
    "derived/v1/facility_location.parquet": ["unique_id"],
    "derived/v1/facility_trust.parquet": ["unique_id"],
    "derived/v1/facility_trust.csv": ["unique_id"],
    "derived/v1/gold_pairs.parquet": ["pair_id"],
    "derived/v1/grades.parquet": ["unique_id", "service"],
    "derived/v1/grades_v1.parquet": ["unique_id", "service"],
    "derived/v1/pin_gazetteer.parquet": ["pin"],
    "derived/v1/place_gazetteer.parquet": ["state", "name", "kind"],
    "derived/v1/record_trust.parquet": ["unique_id"],
    "derived/v1/source_classes.parquet": ["source_class"],
    "derived/v1/source_classes.csv": ["source_class"],
    "derived/v1/source_domains.parquet": ["domain"],
    "derived/v1/source_domains.csv": ["domain"],
    "derived/v1/source_urls.parquet": ["unique_id", "url_pos"],
    "derived/v1/source_page_checks.parquet": ["unique_id", "url", "claim_id"],
    "derived/v1/specialties.parquet": ["unique_id", "spec"],
    "kb/crawl/pages.parquet": ["target_id", "url"],
    "kb/crawl/sites.parquet": ["target_id"],
    "kb/crawl/targets.parquet": ["target_id"],
    "kb/crawl/coverage_by_state.csv": ["state"],
    "kb/crawl/coverage_by_type.csv": ["ftype"],
    "kb/opendata/osm_health_facilities.parquet": ["osm_id"],
    "kb/opendata/wikidata_medical_facilities.parquet": ["qid"],
    "kb/opendata/opendata_not_in_vf.parquet": ["source", "source_id"],
    "kb/opendata/vf_candidates.parquet": ["unique_id", "source"],
    "kb/opendata/vf_opendata_match.parquet": ["unique_id", "source"],
    "kb/opendata/vf_opendata_facts.parquet": ["unique_id", "source", "source_id", "field", "value"],
    "kb/taxonomy/specialty_map.csv": ["specialty"],
    "kb/taxonomy/specialty_evidence_weights.csv": ["specialty", "service"],
    "kb/taxonomy/out/lexicon_matches.parquet": ["claim_id", "service"],
    "kb/taxonomy/out/lexicon_matches_v0.parquet": ["claim_id", "service"],
    "kb/taxonomy/out/v1_0/lexicon_matches.parquet": ["claim_id", "service"],
    "kb/taxonomy/out/coverage.csv": ["service"],
    "kb/vf_details/out/facts.parquet": ["fact_id"],
    "kb/vf_details/out/facility_details.parquet": ["unique_id", "fact_type", "attribute"],
    "kb/vf_details/out/hour_candidates.parquet": ["claim_id"],
    "kb/vf_details/out/llm_hours.parquet": ["claim_id"],
    "kb/vf_details/handcheck_labels.csv": ["fact_id"],
    "kb/web_evidence/out/site_identity.parquet": ["target_id", "unique_id"],
    "kb/web_evidence/out/page_identity.parquet": ["page_id", "unique_id"],
    "kb/web_evidence/out/web_services.parquet":
        ["unique_id", "page_id", "field", "seg_start", "service_id", "quote"],
    "kb/web_evidence/out/web_service_summary.parquet": ["unique_id", "service_id"],
    "kb/web_evidence/out/web_details.parquet": ["fact_id"],
    "kb/web_evidence/out/web_hours.parquet": ["fact_id"],
    "kb/web_evidence/out/web_facility_details.parquet": ["unique_id", "fact_type", "attribute"],
    "kb/web_evidence/out/hour_candidates.parquet": ["cand_key"],
    "kb/web_evidence/out/llm_hours.parquet": ["cand_key"],
    "kb/web_evidence/out/compare_by_service.csv": ["service_id"],
}


def rel(p: Path | str) -> str:
    return str(Path(p).resolve().relative_to(ROOT))


def scope_files() -> list[str]:
    seen: list[str] = []
    for g in SCOPE_GLOBS:
        for f in sorted(glob.glob(str(ROOT / g), recursive=True)):
            r = rel(f)
            if "/v3" in r or not os.path.isfile(f) or r.endswith((".py", ".md", ".mjs")) or r in seen:
                continue
            seen.append(r)
    return seen


def tabular_files() -> list[str]:
    return [f for f in scope_files() if f.endswith((".parquet", ".csv"))]


@lru_cache(maxsize=None)
def table(relpath: str) -> pd.DataFrame:
    p = ROOT / relpath
    if relpath.endswith(".parquet"):
        return pd.read_parquet(p)
    if relpath.endswith(".csv"):
        return pd.read_csv(p, keep_default_na=False, na_values=[""], dtype=str)
    raise ValueError(relpath)


@lru_cache(maxsize=None)
def jload(relpath: str):
    p = ROOT / relpath
    if relpath.endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    if relpath.endswith(".jsonl"):
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return json.loads(p.read_text())


def nrows(relpath: str) -> int:
    if relpath.endswith(".parquet"):
        return pq.ParquetFile(ROOT / relpath).metadata.num_rows
    return len(table(relpath))


@lru_cache(maxsize=None)
def raw() -> pd.DataFrame:
    return pd.read_parquet(RAW / "facilities.parquet")


@lru_cache(maxsize=None)
def raw_ids() -> frozenset:
    return frozenset(raw().unique_id.dropna())


@lru_cache(maxsize=None)
def usable() -> pd.DataFrame:
    """The documented usable set: UUID unique_id, source == 'kie', first row per unique_id (9,959 rows).

    Same rule as cleaning/geo_identity/common.py facilities() via audit/geo/geo_common.py load_facilities().
    """
    f = raw()
    ok = f.unique_id.str.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", na=False) & (f.source == "kie")
    return f[ok].drop_duplicates("unique_id").reset_index(drop=True)


@lru_cache(maxsize=None)
def usable_ids() -> frozenset:
    return frozenset(usable().unique_id)


@lru_cache(maxsize=None)
def uid8_map() -> dict[str, str]:
    return {u[:8]: u for u in usable_ids()}


@lru_cache(maxsize=None)
def claims() -> pd.DataFrame:
    return pd.read_parquet(V1 / "claims.parquet", columns=["claim_id", "unique_id", "field", "idx", "text",
                                                          "attribution"])


@lru_cache(maxsize=None)
def claim_ids() -> frozenset:
    return frozenset(claims().claim_id)


@lru_cache(maxsize=None)
def claim_text() -> dict[str, str]:
    c = claims()
    return dict(zip(c.claim_id, c.text))


def sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def duck() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def result(name: str, status: str, metric, threshold, detail: str, examples=None) -> dict:
    assert status in ("pass", "warn", "fail"), status
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail,
            "examples": list(examples or [])[:8]}


def worst(statuses) -> str:
    s = set(statuses)
    return "fail" if "fail" in s else "warn" if "warn" in s else "pass"


def is_null_like(v) -> str | None:
    """Classify a string value as a null encoding; None when it is a real value."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s == "":
        return "empty"
    if s in NULL_STRINGS:
        return "null_string"
    if s.replace(" ", "") in EMPTY_CONTAINERS:
        return "empty_container"
    return None

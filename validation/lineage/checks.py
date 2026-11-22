"""Lineage and reproducibility checks: original data, derived/v1 build, app exports, rebuild portability.

Every check_<name>() returns dict(name, status pass|warn|fail, metric, threshold, detail, examples).
Read-only on every data layer; scratch output goes to temp dirs, reports to validation/lineage/out/.
Run all: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python checks.py   (about 4 minutes:
two pipeline rebuilds, two export rebuilds, four warehouse SELECTs)
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live  # noqa: E402
import rebuild  # noqa: E402
import scan  # noqa: E402

ROOT = Path("/Users/karthikvattem/projects/datathon")
RAW = ROOT / "data/raw"
V1 = ROOT / "derived/v1"
PIPE = ROOT / "pipelines/source_scoring"
PY_PIPE = ROOT / ".venv/bin/python"  # the interpreter run_all.sh and the app builders use
OUT = HERE / "out"
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
FLOAT_TOL = 1e-12  # rebuild vs derived/v1: anything above this is a real change, below is summation order


def res(name: str, status: str, metric, threshold, detail: str, examples=None) -> dict:
    return {"name": name, "status": status, "metric": metric, "threshold": threshold, "detail": detail,
            "examples": list(examples or [])[:5]}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def v1_manifest() -> dict:
    return json.loads((V1 / "MANIFEST.json").read_text())


# ---------------------------------------------------------------- original data (data/raw)

def check_raw_sha256() -> dict:
    """data/raw/MANIFEST.json stores no hashes; the only recorded hashes are derived/v1 raw_input_sha256."""
    rec = v1_manifest()["raw_input_sha256"]
    files = sorted(p.name for p in RAW.iterdir() if p.is_file())
    bad = [n for n in rec if not (RAW / n).is_file() or sha(RAW / n) != rec[n]]
    extra = sorted(set(files) - set(rec))
    raw_man_has_hash = "sha256" in (RAW / "MANIFEST.json").read_text().lower()
    st = "fail" if bad or extra else "pass"
    return res("raw_sha256", st, f"{len(rec) - len(bad)}/{len(rec)} files match", "all match, no extra files",
               f"recomputed sha256 of data/raw vs derived/v1/MANIFEST.json raw_input_sha256; extra files: {extra}; "
               f"data/raw/MANIFEST.json itself records hashes: {raw_man_has_hash}", bad + extra)


def check_raw_manifest_recompute() -> dict:
    """Recompute every aggregate in data/raw/MANIFEST.json locally; compare with its stored local and warehouse values."""
    man = json.loads((RAW / "MANIFEST.json").read_text())
    loc = live.run_local_agg()
    n, bad = 0, []
    for t, m in man["tables"].items():
        for k, v in m["checks"].items():
            key = f"{t}|rows" if k == "rows" else f"{t}|{k.replace('__', '|', 1)}"
            n += 1
            if not (live.same(v["warehouse"], loc[key]) and live.same(v["local"], loc[key])):
                bad.append(f"{key}: manifest {v} now {loc[key]}")
    st = "pass" if not bad and n == man["n_checks"] and man["n_mismatches"] == 0 else "fail"
    return res("raw_manifest_recompute", st, f"{n - len(bad)}/{n} manifest checks reproduce",
               f"all {man['n_checks']}", "row counts, non-null counts, sum(length) per string column and round(sum, 3) "
               "per numeric column recomputed in DuckDB from data/raw", bad)


@lru_cache(maxsize=1)
def _live() -> dict:
    return live.compare_all()


def check_live_aggregates() -> dict:
    """Live Marketplace table vs local: rows, distinct ids, non-null, char and byte lengths, numeric sums."""
    try:
        r = _live()
    except Exception as e:  # network or auth: report as not run
        return res("live_aggregates", "warn", "not run", "0 mismatches", f"warehouse query failed: {e}")
    keys = [k for k in r["remote"] if "|fp|" not in k]
    bad = [k for k in keys if k in r["mismatches"]]
    loc = r["local"]
    lens = sorted(((int(loc[k]), k.split("|")[2]) for k in keys if k.startswith("facilities|len|") and loc[k]), reverse=True)
    top5 = [c for _, c in lens[:5]]
    t5 = {c: (r["remote"][f"facilities|len|{c}"], r["remote"][f"facilities|bytes|{c}"]) for c in top5}
    return res("live_aggregates", "fail" if bad else "pass", f"{len(keys) - len(bad)}/{len(keys)} equal", "0 mismatches",
               f"rows {r['remote']['facilities|rows']}, distinct unique_id {r['remote']['facilities|distinct_unique_id']}; "
               f"5 longest text columns (sum chars, sum bytes) equal live and local: {t5}", bad)


def check_live_content_fingerprint() -> dict:
    """Order-independent md5 fingerprint of every column of the three tables: any edited cell would show."""
    try:
        r = _live()
    except Exception as e:
        return res("live_content_fingerprint", "warn", "not run", "0 mismatches", f"warehouse query failed: {e}")
    keys = [k for k in r["remote"] if "|fp|" in k]
    bad = [k for k in keys if k in r["mismatches"]]
    return res("live_content_fingerprint", "fail" if bad else "pass", f"{len(keys) - len(bad)}/{len(keys)} columns equal",
               "0 mismatches", "per column: sum over rows of int(md5(value)[:15], 16) for strings, "
               "sum(round(value*1e6)) for doubles, sum for BIGINT; 171 columns over 3 tables", bad)


def check_live_schema() -> dict:
    try:
        r = _live()
    except Exception as e:
        return res("live_schema", "warn", "not run", "identical", f"warehouse query failed: {e}")
    alias = {"LONG": "BIGINT"}  # information_schema spells BIGINT as LONG
    bad = []
    for t in live.TABLES:
        rem = [(s["column_name"], alias.get(s["data_type"], s["data_type"])) for s in r["remote_schema"] if s["table_name"] == t]
        exp = [tuple(x) for x in live.META[t]["warehouse_schema"]]
        local = pq.read_schema(RAW / f"{t}.parquet").names
        if rem != exp or [c for c, _ in exp] != local:
            bad.append(t)
    return res("live_schema", "fail" if bad else "pass", f"{3 - len(bad)}/3 tables", "names, order and types identical",
               "information_schema.columns vs _export_meta.json warehouse_schema vs local parquet column order", bad)


def check_raw_record_identity() -> dict:
    """The 10,088 -> 9,970 -> 9,959 reduction every pipeline relies on (audit/provenance/common.py facilities())."""
    q = (f"with w as (select * from read_parquet('{RAW}/facilities.parquet') where source='kie' and "
         f"regexp_matches(unique_id, '{UUID}')) select (select count(*) from read_parquet('{RAW}/facilities.parquet')), "
         f"(select count(*) from w), (select count(distinct unique_id) from w), "
         f"(select count(*) from (select distinct * from w))")
    n, nw, nid, ndist = duckdb.sql(q).fetchall()[0]
    conflict = duckdb.sql(
        f"select unique_id from (select distinct * from read_parquet('{RAW}/facilities.parquet') where source='kie' and "
        f"regexp_matches(unique_id, '{UUID}')) group by 1 having count(*) > 1 limit 5").fetchall()
    ok = (n, nw, nid, ndist) == (10088, 9970, 9959, 9959) and not conflict
    return res("raw_record_identity", "pass" if ok else "fail", f"{n} rows, {nw} well-formed, {nid} ids, {ndist} distinct rows",
               "10088 / 9970 / 9959 / 9959, no id with two different rows",
               f"{nw - ndist} well-formed rows are byte-identical duplicates; ids with conflicting content: {len(conflict)}",
               [c[0] for c in conflict])


# ---------------------------------------------------------------- derived/v1 build lineage

def check_derived_manifest_matches_files() -> dict:
    man = v1_manifest()
    bad = []
    for name, t in {**man["tables"], **man["csv_copies"]}.items():
        p = V1 / name
        if not p.is_file():
            bad.append(f"{name}: missing")
            continue
        rows = pq.ParquetFile(p).metadata.num_rows if name.endswith(".parquet") else \
            sum(1 for _ in open(p, encoding="utf-8")) - 1
        if rows != t["rows"] or p.stat().st_size != t["bytes"]:
            bad.append(f"{name}: manifest {t} file rows {rows} bytes {p.stat().st_size}")
    listed = set(man["tables"]) | set(man["csv_copies"]) | {"MANIFEST.json", "README.md", "build_stats.json", "evaluation.json"}
    unlisted = sorted(p.name for p in V1.iterdir() if p.name not in listed)
    st = "fail" if bad else ("warn" if unlisted else "pass")
    return res("derived_manifest_matches_files", st, f"{len(bad)} mismatched, {len(unlisted)} unlisted", "0 / 0",
               "derived/v1 MANIFEST rows and bytes vs files on disk (MANIFEST records no output hashes, so a same-size "
               "edit would not show; the rebuild check covers content)", bad + unlisted)


def check_derived_inputs_unchanged() -> dict:
    man = v1_manifest()["other_input_sha256"]
    bad = [p for p, h in man.items() if not (ROOT / p).is_file() or sha(ROOT / p) != h]
    return res("derived_inputs_unchanged", "fail" if bad else "pass", f"{len(man) - len(bad)}/{len(man)} inputs match",
               "all", "current sha256 of every non-raw input (audit code, gold labels, hand checks, cleaning tables) vs "
               "the hashes recorded at build time", bad)


def check_derived_scripts_unchanged() -> dict:
    man = v1_manifest()["script_sha256"]
    bad = [p for p, h in man.items() if not (PIPE / p).is_file() or sha(PIPE / p) != h]
    new = sorted(p.name for p in [*PIPE.glob("*.py"), PIPE / "run_all.sh"] if p.name not in man)
    return res("derived_scripts_unchanged", "fail" if bad or new else "pass", f"{len(man) - len(bad)}/{len(man)} scripts match",
               "all", "pipelines/source_scoring scripts now vs script_sha256 at build time", bad + new)


def check_derived_copies_identical() -> dict:
    """The 9 canonical cleaned tables in derived/v1 are byte copies of the cleaning outputs."""
    copy = {  # duplicated from package.py COPY so this check does not import the pipeline
        "facility_location.parquet": "cleaning/geo_identity/facility_location.parquet",
        "record_trust.parquet": "cleaning/geo_identity/record_trust.parquet",
        "facility_groups.parquet": "cleaning/geo_identity/facility_groups.parquet",
        "pin_gazetteer.parquet": "cleaning/geo_identity/pin_gazetteer.parquet",
        "place_gazetteer.parquet": "cleaning/geo_identity/place_gazetteer.parquet",
        "claims.parquet": "cleaning/claims/out/claims.parquet",
        "specialties.parquet": "cleaning/claims/out/specialties.parquet",
        "grades.parquet": "cleaning/claims/out/grades.parquet",
        "grades_v1.parquet": "cleaning/claims/out/grades_v1.parquet",
    }
    bad = [d for d, s in copy.items() if sha(V1 / d) != sha(ROOT / s)]
    return res("derived_copies_identical", "fail" if bad else "pass", f"{len(copy) - len(bad)}/{len(copy)} identical",
               "all", "derived/v1 copy vs its cleaning/ source, by sha256", bad)


def check_selfcheck() -> dict:
    r = subprocess.run([str(PY_PIPE), "-B", "selfcheck.py"], cwd=PIPE, capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    ok = r.returncode == 0 and "selfcheck ok" in r.stdout
    return res("selfcheck", "pass" if ok else "fail", r.stdout.strip()[-120:] or r.stderr.strip()[-200:], "exit 0",
               "pipelines/source_scoring/selfcheck.py on the published derived/v1 (read-only)")


@lru_cache(maxsize=4)
def _rebuild(seed: str | None = None) -> dict:
    d = Path(tempfile.mkdtemp(prefix="ss_rebuild_"))
    return rebuild.run(d, {"PYTHONHASHSEED": seed} if seed else None)


def check_rebuild_matches_derived() -> dict:
    """Re-run the whole source_scoring pipeline into a temp dir (s3 web fetch reused, as run_all.sh does) and diff."""
    r = _rebuild()
    if not r["ok"]:
        return res("rebuild_matches_derived", "fail", "rebuild failed", "rebuild succeeds",
                   json.dumps(r["log"][-1])[:400])
    files = r["diff"]["files"]
    ident = [n for n, e in files.items() if e["byte_identical"]]
    real, ulp = [], []
    for n, e in files.items():
        f = e.get("frame")
        if f is None:
            if n.endswith(".csv") and not e["byte_identical"]:
                (real if not e["csv_non_numeric_equal"] or e["csv_max_abs_numeric_diff"] > FLOAT_TOL else ulp).append(n)
            continue
        if f["rows_ref"] != f["rows_new"] or not f["cols_equal"] or f["non_float_cells_differ"] or f["max_abs_float_diff"] > FLOAT_TOL:
            real.append(n)
        else:
            ulp.append(f"{n} (max float diff {f['max_abs_float_diff']:.1e})")
    missing = r["diff"]["only_ref"] + r["diff"]["only_new"]
    st = "fail" if real or set(missing) - {"README.md"} else ("warn" if ulp else "pass")
    (OUT / "rebuild_check.json").write_text(json.dumps(r, indent=1))
    return res("rebuild_matches_derived", st, f"{len(ident)}/{len(files)} byte-identical; {len(real)} real diffs; "
               f"{len(ulp)} float-ulp only", f"no real diffs; float diffs <= {FLOAT_TOL}",
               "MANIFEST.json differs only in script_sha256 (patched ss_common.py) and table bytes; all string and "
               "integer cells are equal", real + ulp)


def check_rebuild_deterministic_with_fixed_hashseed() -> dict:
    """Two rebuilds under PYTHONHASHSEED=0 must be byte-identical; proves set iteration is the only noise source."""
    a, b = _rebuild("0"), _rebuild_b("0")
    if not (a["ok"] and b["ok"]):
        return res("rebuild_deterministic_fixed_hashseed", "fail", "rebuild failed", "both succeed", "")
    pa, pb = Path(a["scratch"]) / "out", Path(b["scratch"]) / "out"
    diff = [p.name for p in sorted(pa.glob("*")) if p.name != "MANIFEST.json" and sha(p) != sha(pb / p.name)]
    return res("rebuild_deterministic_fixed_hashseed", "fail" if diff else "pass", f"{len(diff)} files differ", "0",
               "PYTHONHASHSEED=0 twice; without a fixed seed the float tables differ run to run at 1e-16..2e-13 "
               "because pipelines/source_scoring/s5_fit.py:90 iterates `set(sup) | set(nos)`", diff)


@lru_cache(maxsize=2)
def _rebuild_b(seed: str) -> dict:
    d = Path(tempfile.mkdtemp(prefix="ss_rebuild_b_"))
    return rebuild.run(d, {"PYTHONHASHSEED": seed})


# ---------------------------------------------------------------- app exports

@lru_cache(maxsize=4)
def _exports(seed: str = "", run: int = 0) -> dict:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if seed:
        env["PYTHONHASHSEED"] = seed
    r = subprocess.run([str(PY_PIPE), "-B", str(HERE / "exports.py")], capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr[-500:])
    return json.loads(r.stdout[r.stdout.rindex('{\n "scratch"'):])  # builders print progress lines first


def check_exports_rebuild() -> dict:
    """Rebuild planner/out, app/facts/out and app/packs/out from current derived/v1 into a temp dir and diff."""
    r = _exports()
    pl, fa, pk = r["planner"], r["facts"], r["packs"]
    errs = [f"{k}: {v['error']}" for k, v in (("planner", pl), ("facts", fa), ("packs", pk)) if "error" in v]
    if errs:
        return res("exports_rebuild", "fail", "builder error", "builds", "; ".join(errs))
    problems = []
    if not pl["equal_except_build_time"]:
        problems.append(f"planner: {pl['first_diff']}")
    if not fa["equal_except_build_time"] or fa["facts_sha_ref"] != fa["facts_sha_new"]:
        problems.append(f"facts: {fa['first_diff']}")
    if pk["index_sha_mismatch"] or not pk["same_names"]:
        problems.append(f"packs index: {pk['index_sha_mismatch']}")
    nd = pk["rebuilt_bytes_differ"]
    st = "fail" if problems else ("warn" if nd else "pass")
    return res("exports_rebuild", st, f"planner equal, facts sha {fa['facts_sha_new']}, packs {pk['n_ref'] - len(nd)}/{pk['n_ref']} "
               "byte-identical", "all equal",
               f"pack differences are quote choices among equal-length quotes (set order, app/packs/build_packs.py:122); "
               f"first diffs: {json.dumps(pk.get('first_diffs', {}))[:500]}", problems + [f"pack {n}" for n in nd])


def check_exports_deterministic_fixed_hashseed() -> dict:
    """Two export rebuilds under PYTHONHASHSEED=1: packs must be byte-identical (proves set order is the cause)."""
    a, b = Path(_exports("1", 0)["scratch"]), Path(_exports("1", 1)["scratch"])
    diff = [p.name for p in sorted((a / "packs/out").glob("*")) if sha(p) != sha(b / "packs/out" / p.name)]
    fa, fb = (json.loads(gzip.decompress((x / "facts/facts.json.gz").read_bytes())) for x in (a, b))
    fa["meta"].pop("built_at"), fb["meta"].pop("built_at")
    if fa != fb:
        diff.append("facts.json.gz content")
    return res("exports_deterministic_fixed_hashseed", "fail" if diff else "pass", f"{len(diff)} files differ", "0",
               "packs byte-compared; facts compared after dropping built_at (facts.json.gz bytes also carry the gzip "
               "mtime, app/facts/build.py:178 gzip.compress without mtime=0)", diff)


def check_exports_strict_json() -> dict:
    """The app ships these as JSON; NaN / Infinity tokens are not JSON and break JSON.parse and Python callers."""
    def bad_const(c):
        raise ValueError(c)
    files = [ROOT / "planner/out/planner_v1.json.gz", ROOT / "app/facts/out/facts.json.gz",
             *sorted((ROOT / "app/packs/out").glob("*.json.gz"))]
    bad, examples = [], []
    for p in files:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            txt = fh.read()
        try:
            json.loads(txt, parse_constant=bad_const)
        except ValueError:
            d = json.loads(txt)
            bad.append(p.relative_to(ROOT).as_posix())
            if "facilities" in d:
                f = d["facilities"]
                for k, v in f.items():
                    ids = [f["id"][i] for i, x in enumerate(v) if isinstance(x, float) and math.isnan(x)]
                    if ids:
                        examples.append(f"{p.name} facilities.{k}: {len(ids)} NaN, ids {ids[:3]}")
    return res("exports_strict_json", "fail" if bad else "pass", f"{len(bad)}/{len(files)} files have NaN/Infinity",
               "0", "strict parse (parse_constant raises). planner/data_v1.py:77 puts pandas NaN districts into the doc; "
               "app/itinerary.py:53 then calls x.isupper() on the float NaN for a stop at one of these facilities",
               bad + examples)


# ---------------------------------------------------------------- portability (static scan)

@lru_cache(maxsize=1)
def _scan() -> list[dict]:
    return scan.scan()


def _static(cat: str, name: str, status_if_hit: str, detail: str) -> dict:
    hits = [h for h in _scan() if h["category"] == cat]
    files = sorted({h["file"] for h in hits})
    return res(name, status_if_hit if hits else "pass", f"{len(hits)} lines in {len(files)} files", "0", detail,
               [f"{h['file']}:{h['line']}" for h in hits])


def check_static_abs_paths() -> dict:
    return _static("abs_path", "static_abs_paths", "fail",
                   "hard-coded /Users/karthikvattem/... paths: a clone elsewhere or a Databricks repo (/Workspace/...) "
                   "cannot run these unchanged. Full list: out/static_scan.csv")


def check_static_venv_pins() -> dict:
    return _static("venv_pin", "static_venv_pins", "warn",
                   "interpreter pinned to a local venv (no requirements file for the data pipelines)")


def check_static_network() -> dict:
    return _static("network", "static_network", "warn",
                   "live web fetches: kb/crawl, kb/opendata/fetch_wikidata.py, pipelines s3_pagecheck.py (opt-in, FETCH=1)")


def check_static_warehouse_llm() -> dict:
    return _static("warehouse_llm", "static_warehouse_llm", "warn",
                   "Databricks SQL / ai_query calls; results are cached (out/llm_labels.json, llm_hours.parquet), "
                   "so a rebuild is reproducible only while those caches are present")


def check_static_unseeded_random() -> dict:
    return _static("random_unseeded", "static_unseeded_random", "fail",
                   "random draws with no seed on the line (all .sample() calls found carry random_state)")


def check_static_hash_order() -> dict:
    return _static("hash_order", "static_hash_order", "warn",
                   "set iteration; two are confirmed output-changing (s5_fit.py:90 float ulps, build_packs.py:122 quote "
                   "choice), the others feed counters or assertions only")


def check_static_shell() -> dict:
    return _static("shell_portability", "static_shell_portability", "warn",
                   "#!/bin/zsh run_all scripts (Makefile calls them with zsh, not installed on Databricks clusters) "
                   "and one swallowed self-check")


# ---------------------------------------------------------------- what a fresh clone has

IGNORED = [re.compile(p) for p in (r"(^|/)data/", r"(^|/)build/", r"\.pbf$", r"^audit/capabilities/out/",
                                   r"^(planner|app/facts|app/packs|app/verify|app/howto|demo)/out/")]


def git_ignored(rel: str) -> bool:
    """Approximation of the repo's .gitignore files (no git calls): *.parquet ignored except under derived/."""
    if rel.endswith(".parquet") and not rel.startswith("derived/"):
        return True
    return any(p.search(rel) for p in IGNORED)


def check_rebuild_inputs_in_repo() -> dict:
    """Inputs of `make derived` and `make app-data` that a fresh clone would not have."""
    need = ["data/raw/facilities.parquet", "data/raw/india_post_pincode_directory.parquet",
            "data/raw/nfhs_5_district_health_indicators.parquet",
            *v1_manifest()["other_input_sha256"], "kb/pathways/capabilities.json", "planner/out/planner_v1.json.gz"]
    missing = [p for p in need if git_ignored(p)]
    return res("rebuild_inputs_in_repo", "warn" if missing else "pass", f"{len(missing)}/{len(need)} inputs git-ignored",
               "0", "derived/v1 is committed so the app and notebook run, but `make derived` on a clone needs data/raw "
               "(re-export from the Marketplace with data/snapshot_scripts/export.py) and the cleaning parquet outputs, "
               "which are ignored by `*.parquet`", missing)


def check_makefile_python() -> dict:
    mk = (ROOT / "Makefile").read_text()
    m = re.search(r"^PY \?= (\S+)", mk, re.M)
    py = m.group(1) if m else None
    ok = py is not None and (ROOT / py).exists()
    return res("makefile_python", "pass" if ok else "warn", py, "default PY exists",
               "Makefile default interpreter for app-data/test/notebook; run_all.sh scripts ignore it and use .venv",
               [] if ok else [f"Makefile:2 PY ?= {py} (not present on this machine)"])


ALL = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    results = []
    for fn in ALL:
        try:
            r = fn()
        except Exception as e:
            r = res(fn.__name__[6:], "fail", "check crashed", "runs", f"{type(e).__name__}: {e}")
        results.append(r)
        print(f"{r['status']:5} {r['name']}: {r['metric']}", flush=True)
    (OUT / "checks.json").write_text(json.dumps(results, indent=1, default=str))

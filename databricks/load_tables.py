"""Load the project tables listed in tables.yaml into workspace.referral_saathi.

For each table: build or convert the local file to parquet if needed, upload it to the volume
workspace.referral_saathi.uploads/<table>/<table>.parquet, CREATE OR REPLACE TABLE ... AS SELECT * FROM
read_files(...), set table and column comments, then verify row count, primary-key uniqueness and 3 spot
values against the local file. Safe to re-run: every step overwrites.

Run from the project root (pyyaml is not in .venv, uv adds it):
  uv run --offline --with pyyaml --python .venv/bin/python python databricks/load_tables.py
  ... --only claims,facility_trust          # some tables
  ... --only derived --derived derived/v2   # reload every derived table from derived/v2
  ... --local-only                          # local checks only, nothing sent to Databricks
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import duckdb
import yaml

import build_staging

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "build" / "databricks_staging"
SCHEMA = "workspace.referral_saathi"
VOLUME = "/Volumes/workspace/referral_saathi/uploads"
WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID", "6a2f5637720a2c17")
ENV = {**os.environ, "DATABRICKS_CONFIG_PROFILE": os.environ.get("DATABRICKS_CONFIG_PROFILE", "vf")}
POLL_SECONDS = 5  # ponytail: fixed poll interval; statements here take seconds, no backoff needed
SCALAR_TYPES = ("VARCHAR", "DOUBLE", "BIGINT", "INTEGER", "BOOLEAN", "FLOAT", "SMALLINT", "TINYINT")


def cli(*args: str) -> str:
    r = subprocess.run(["databricks", *args], capture_output=True, text=True, env=ENV)
    if r.returncode:
        raise RuntimeError(f"databricks {args[0]} {args[1]} failed: {r.stderr.strip()[:500]}")
    return r.stdout


def sql(statement: str) -> list[list]:
    """Run one statement on the warehouse through the SQL Statement API and return its rows."""
    body = json.dumps({"warehouse_id": WAREHOUSE_ID, "statement": statement, "wait_timeout": "50s",
                       "disposition": "INLINE", "format": "JSON_ARRAY"})
    r = json.loads(cli("api", "post", "/api/2.0/sql/statements", "--json", body))
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(POLL_SECONDS)
        r = json.loads(cli("api", "get", f"/api/2.0/sql/statements/{r['statement_id']}"))
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"{r['status']['state']}: {r['status'].get('error', {}).get('message', '')[:800]}\n{statement[:300]}")
    return r.get("result", {}).get("data_array") or []


def q(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def lit(v) -> str:
    return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else q(str(v))


def stage(t: dict, derived: str) -> Path:
    """Return a local parquet path for the table, building or converting it when needed."""
    if "build" in t:
        return getattr(build_staging, t["build"])()
    src = ROOT / t["file"].format(derived=derived)
    if not src.exists():
        raise FileNotFoundError(src)
    if src.suffix == ".parquet":
        return src
    STAGING.mkdir(parents=True, exist_ok=True)
    out = STAGING / f"{t['table']}.parquet"
    duckdb.connect().execute(f"COPY (SELECT * FROM read_csv_auto('{src}')) TO '{out}' (FORMAT parquet)")
    return out


def local_stats(t: dict, path: Path) -> dict:
    con = duckdb.connect()
    src = f"read_parquet('{path}')"
    pk = t["primary_key"]
    cols = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
    spot = t.get("spot") or next(c[0] for c in cols if c[0] not in pk and c[1] in SCALAR_TYPES)
    keys = ", ".join(f'"{k}"' for k in pk)
    n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    dups = con.execute(f"SELECT count(*) FROM (SELECT 1 FROM {src} GROUP BY {keys} HAVING count(*) > 1)").fetchone()[0]
    nulls = con.execute(f"SELECT count(*) FROM {src} WHERE " + null_test(t, '"')).fetchone()[0]
    rows = [con.execute(f'SELECT {keys}, CAST("{spot}" AS VARCHAR) FROM {src} ORDER BY {keys} LIMIT 1 OFFSET {o}').fetchone()
            for o in sorted({0, n // 2, n - 1})]
    return {"rows": n, "dup_keys": dups, "null_keys": nulls, "spot": spot, "samples": rows,
            "columns": [c[0] for c in cols]}


def null_test(t: dict, quote: str) -> str:
    """SQL test for a null in a key column that must not be null (nullable_key columns are exempt)."""
    cols = [k for k in t["primary_key"] if k not in t.get("nullable_key", [])]
    return " OR ".join(f"{quote}{k}{quote} IS NULL" for k in cols) or "FALSE"


def same(a, b) -> bool:
    if a == b:
        return True
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    except (TypeError, ValueError):
        return str(a).lower() == str(b).lower()  # booleans print True/true across engines


def load(t: dict, path: Path, stats: dict) -> None:
    name, fq = t["table"], f"{SCHEMA}.{t['table']}"
    vol_path = f"{VOLUME}/{name}/{name}.parquet"
    cli("fs", "mkdirs", f"dbfs:{VOLUME}/{name}")
    cli("fs", "cp", "--overwrite", str(path), f"dbfs:{vol_path}")
    desc = " ".join(t["description"].split()) + " Primary key: " + ", ".join(t["primary_key"]) + "."
    sql(f"CREATE OR REPLACE TABLE {fq} COMMENT {q(desc)} AS "
        f"SELECT * EXCEPT (_rescued_data) FROM read_files({q(vol_path)}, format => 'parquet')")
    comments = {c: v for c, v in (t.get("columns") or {}).items() if c in stats["columns"]}
    missing = set(t.get("columns") or {}) - set(comments)
    if missing:
        print(f"  warning: no such columns for comments: {sorted(missing)}")
    if comments:
        sql(f"ALTER TABLE {fq} ALTER COLUMN " + ", ".join(f"`{c}` COMMENT {q(v)}" for c, v in comments.items()))


def verify(t: dict, stats: dict) -> dict:
    fq, pk, spot = f"{SCHEMA}.{t['table']}", t["primary_key"], stats["spot"]
    keys = ", ".join(f"`{k}`" for k in pk)
    n, dups, nulls = sql(
        f"SELECT (SELECT count(*) FROM {fq}), "
        f"(SELECT count(*) FROM (SELECT 1 FROM {fq} GROUP BY {keys} HAVING count(*) > 1)), "
        f"(SELECT count(*) FROM {fq} WHERE " + null_test(t, "`") + ")")[0]
    where = " OR ".join("(" + " AND ".join(f"`{k}` <=> {lit(v)}" if v is not None else f"`{k}` IS NULL"
                                           for k, v in zip(pk, s[:-1])) + ")" for s in stats["samples"])
    remote = {tuple(map(str, r[:-1])): r[-1] for r in sql(f"SELECT {keys}, CAST(`{spot}` AS STRING) FROM {fq} WHERE {where}")}
    spots_ok = sum(same(s[-1], remote.get(tuple(map(str, s[:-1])), "<missing>")) for s in stats["samples"])
    known = t.get("known_dup_keys", 0)
    ok = int(n) == stats["rows"] and int(dups) == stats["dup_keys"] == known and int(nulls) == 0 and spots_ok == len(stats["samples"])
    return {"table": t["table"], "local_rows": stats["rows"], "uc_rows": int(n), "uc_dup_keys": int(dups),
            "uc_null_keys": int(nulls), "spot_column": spot, "spots_equal": f"{spots_ok}/{len(stats['samples'])}",
            "ok": ok}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated table names or groups (derived, kb, dashboard, lists)")
    ap.add_argument("--derived", default="derived/v1", help="directory that {derived} expands to")
    ap.add_argument("--local-only", action="store_true", help="stage and check locally, send nothing")
    a = ap.parse_args()
    tables = yaml.safe_load((Path(__file__).parent / "tables.yaml").read_text())["tables"]
    if a.only:
        want = set(a.only.split(","))
        unknown = want - {t["table"] for t in tables} - {t["group"] for t in tables}
        if unknown:
            sys.exit(f"unknown tables or groups: {sorted(unknown)}")
        tables = [t for t in tables if t["table"] in want or t["group"] in want]

    results, failed = [], []
    for t in tables:
        print(f"{t['table']} ...", flush=True)
        try:
            path = stage(t, a.derived)
            stats = local_stats(t, path)
            print(f"  local rows {stats['rows']}, dup keys {stats['dup_keys']}, null keys {stats['null_keys']}")
            if a.local_only:
                continue
            load(t, path, stats)
            res = verify(t, stats)
            res["local_dup_keys"] = stats["dup_keys"]
            results.append(res)
            print(f"  {'OK' if res['ok'] else 'MISMATCH'} {res}")
            if not res["ok"]:
                failed.append(t["table"])
        except Exception as e:  # one bad table must not stop the rest; it is reported at the end
            print(f"  FAILED: {e}")
            failed.append(t["table"])

    if results:
        STAGING.mkdir(parents=True, exist_ok=True)
        out = STAGING / "verify_results.json"
        old = {r["table"]: r for r in json.loads(out.read_text())} if out.exists() else {}
        old.update({r["table"]: r for r in results})
        out.write_text(json.dumps(list(old.values()), indent=1))
        print(f"verification written to {out}")
    print(f"failed: {failed}" if failed else "all tables passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

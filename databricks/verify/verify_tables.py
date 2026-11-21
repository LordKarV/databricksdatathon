"""Independent check of workspace.referral_saathi against the local sources named in tables.yaml.

Counts rows locally with duckdb straight from the source file (CSV read as CSV, not the staged copy; build
entries use the staged parquet, the only copy that exists), then runs one UNION ALL on the warehouse for
row count, duplicate keys and null keys per table, plus information_schema for comments.
Run: uv run --offline --with pyyaml --python .venv/bin/python python databricks/verify/verify_tables.py
"""
import json
import sys
from pathlib import Path

import duckdb
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from load_tables import ROOT, SCHEMA, STAGING, sql  # reuse the Statement API helper

OUT = ROOT / "build" / "databricks_staging" / "independent_verify.json"


def local_rows(t: dict) -> int:
    if "build" in t:
        src = f"read_parquet('{STAGING / (t['table'] + '.parquet')}')"
    else:
        p = ROOT / t["file"].format(derived="derived/v1")
        src = f"read_parquet('{p}')" if p.suffix == ".parquet" else f"read_csv_auto('{p}')"
    return duckdb.connect().execute(f"SELECT count(*) FROM {src}").fetchone()[0]


def uc_stats(tables: list[dict]) -> dict:
    parts = []
    for t in tables:
        fq, pk = f"{SCHEMA}.{t['table']}", t["primary_key"]
        keys = ", ".join(f"`{k}`" for k in pk)
        nn = [k for k in pk if k not in t.get("nullable_key", [])]
        nulls = " OR ".join(f"`{k}` IS NULL" for k in nn) or "FALSE"
        parts.append(f"SELECT '{t['table']}' AS t, (SELECT count(*) FROM {fq}) AS n, "
                     f"(SELECT count(*) FROM (SELECT 1 FROM {fq} GROUP BY {keys} HAVING count(*) > 1)) AS d, "
                     f"(SELECT count(*) FROM {fq} WHERE {nulls}) AS z")
    return {r[0]: (int(r[1]), int(r[2]), int(r[3])) for r in sql(" UNION ALL ".join(parts))}


def main() -> int:
    tables = yaml.safe_load((ROOT / "databricks" / "tables.yaml").read_text())["tables"]
    uc = uc_stats(tables)
    comments = {r[0]: r[1] for r in sql(
        "SELECT table_name, comment FROM workspace.information_schema.tables WHERE table_schema = 'referral_saathi'")}
    col_comments = {r[0]: int(r[1]) for r in sql(
        "SELECT table_name, count(comment) FROM workspace.information_schema.columns "
        "WHERE table_schema = 'referral_saathi' GROUP BY table_name")}
    rows, bad = [], 0
    for t in tables:
        name = t["table"]
        n, d, z = uc[name]
        loc = local_rows(t)
        ok = n == loc and d == t.get("known_dup_keys", 0) and z == 0 and bool(comments.get(name))
        bad += not ok
        rows.append({"table": name, "local": loc, "uc": n, "dup_keys": d, "null_keys": z,
                     "table_comment": bool(comments.get(name)), "col_comments": col_comments.get(name, 0), "ok": ok})
        print(f"{'PASS' if ok else 'FAIL'} {name:32} local={loc} uc={n} dup={d} null={z} "
              f"comment={bool(comments.get(name))} col_comments={col_comments.get(name, 0)}")
    extra = sorted(set(comments) - {t["table"] for t in tables})
    print(f"{len(tables) - bad}/{len(tables)} pass; tables in UC not in manifest: {extra}")
    OUT.write_text(json.dumps({"tables": rows, "extra_uc_tables": extra}, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

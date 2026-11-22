"""Compare the local data/raw snapshot with the live Marketplace tables (SELECT only, via sql.sh).

Four warehouse queries per run:
  agg    count(*), count(distinct unique_id), count(col), sum(length(col)), sum(octet_length(col)) per string
         column, round(sum(col), 3) per numeric column, for all three tables (superset of verify.py).
  fp_fac content fingerprint per facilities column: sum over rows of the first 15 hex digits of md5(value)
         for strings, sum(round(value * 1e6)) for doubles. Order-independent; any edited cell changes it.
  fp_oth the same fingerprint for the PIN directory and NFHS-5 tables.
  schema information_schema column names, types and positions.
The same quantities are computed locally from the parquet files and compared exactly.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import duckdb
import numpy as np
import pyarrow.parquet as pq

ROOT = Path("/Users/karthikvattem/projects/datathon")
RAW = ROOT / "data/raw"
CATALOG = "databricks_virtue_foundation_dataset_dais_2026"
SCHEMA = f"{CATALOG}.virtue_foundation_dataset"
META = json.loads((RAW / "_export_meta.json").read_text())
TABLES = list(META)
OUT = Path(__file__).resolve().parent / "out"


def sql(stmt: str, retries: int = 3) -> list[dict]:
    """Run one SELECT through sql.sh; retry transient failures (warehouse cold start, network)."""
    err = ""
    for i in range(retries):
        r = subprocess.run([str(ROOT / "sql.sh"), stmt], capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            lines = r.stdout.rstrip("\n").split("\n")
            head = lines[0].split("\t")
            return [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]
        err = (r.stderr or r.stdout)[-500:]
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"warehouse query failed after {retries} tries: {err}")


def q(c: str) -> str:
    return f"`{c}`"


def agg_items(table: str) -> list[tuple[str, str, str]]:
    """(key, remote expr, local duckdb expr)."""
    items = [(f"{table}|rows", "count(*)", "count(*)")]
    if table == "facilities":
        items.append((f"{table}|distinct_unique_id", "count(distinct unique_id)", "count(distinct unique_id)"))
    for col, typ in META[table]["warehouse_schema"]:
        r, l = q(col), f'"{col}"'
        items.append((f"{table}|nn|{col}", f"count({r})", f"count({l})"))
        if typ == "STRING":
            items.append((f"{table}|len|{col}", f"sum(length({r}))", f"sum(length({l}))"))
            items.append((f"{table}|bytes|{col}", f"sum(octet_length({r}))", f"sum(strlen({l}))"))
        else:
            items.append((f"{table}|sum|{col}", f"round(sum({r}), 3)", f"round(sum({l}), 3)"))
    return items


def fp_remote(table: str) -> list[tuple[str, str]]:
    out = []
    for col, typ in META[table]["warehouse_schema"]:
        r = q(col)
        if typ == "STRING":
            e = f"sum(cast(conv(substr(md5({r}), 1, 15), 16, 10) as decimal(38,0)))"
        elif typ == "DOUBLE":
            e = f"sum(cast(round({r} * 1000000) as decimal(38,0)))"
        else:
            e = f"sum(cast({r} as decimal(38,0)))"
        out.append((f"{table}|fp|{col}", e))
    return out


def fp_local(table: str) -> dict[str, int | None]:
    t = pq.read_table(RAW / f"{table}.parquet")
    res = {}
    for col, typ in META[table]["warehouse_schema"]:
        vals = t.column(col).to_pylist()
        nn = [v for v in vals if v is not None]
        if not nn:
            res[f"{table}|fp|{col}"] = None
        elif typ == "STRING":
            res[f"{table}|fp|{col}"] = sum(int(hashlib.md5(v.encode("utf-8")).hexdigest()[:15], 16) for v in nn)
        elif typ == "DOUBLE":
            x = np.array(nn, dtype=float) * 1000000
            # Spark round() is HALF_UP (away from zero); numpy rint is half-to-even, so do it by hand.
            res[f"{table}|fp|{col}"] = int(sum(int(v) for v in np.sign(x) * np.floor(np.abs(x) + 0.5)))
        else:
            res[f"{table}|fp|{col}"] = int(sum(nn))
    return res


def select_of(items: list[tuple[str, str]], src_of) -> tuple[str, list[str]]:
    """One SELECT with positional aliases c0..cN (the names are long); returns (sql, keys)."""
    by_table: dict[str, list[tuple[str, str]]] = {}
    for k, e in items:
        by_table.setdefault(k.split("|")[0], []).append((k, e))
    subs, keys, i = [], [], 0
    for t, its in by_table.items():
        parts = []
        for k, e in its:
            parts.append(f"{e} AS c{i}")
            keys.append(k)
            i += 1
        subs.append(f"(SELECT {', '.join(parts)} FROM {src_of(t)})")
    return "SELECT * FROM " + " CROSS JOIN ".join(f"{s} t{j}" for j, s in enumerate(subs)), keys


def run_remote(items: list[tuple[str, str]]) -> dict[str, str | None]:
    stmt, keys = select_of(items, lambda t: f"{SCHEMA}.{t}")
    row = sql(stmt)[0]
    return {k: (row[f"c{i}"] or None) for i, k in enumerate(keys)}


def run_local_agg() -> dict:
    res = {}
    con = duckdb.connect()
    for t in TABLES:
        its = agg_items(t)
        stmt = "SELECT " + ", ".join(f"{l} AS c{i}" for i, (_, _, l) in enumerate(its)) + \
               f" FROM read_parquet('{RAW}/{t}.parquet')"
        row = con.execute(stmt).fetchone()
        res.update({k: row[i] for i, (k, _, _) in enumerate(its)})
    return res


def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    sa, sb = str(a), str(b)
    if any(ch in s for s in (sa, sb) for ch in ".eE"):
        return float(sa) == float(sb)  # round(sum, 3) values
    return int(sa) == int(sb)  # counts and fingerprints: exact integer compare


def compare_all() -> dict:
    """Run the four live queries and the local equivalents; write out/live_compare.json."""
    agg = [it for t in TABLES for it in agg_items(t)]
    remote_agg = run_remote([(k, r) for k, r, _ in agg])
    local_agg = run_local_agg()
    fp_fac_r = run_remote(fp_remote("facilities"))
    fp_oth_r = run_remote(fp_remote(TABLES[1]) + fp_remote(TABLES[2]))
    local_fp = {k: v for t in TABLES for k, v in fp_local(t).items()}
    remote_fp = {**fp_fac_r, **fp_oth_r}
    sch = sql(f"SELECT table_name, column_name, data_type, ordinal_position FROM {CATALOG}.information_schema.columns "
              f"WHERE table_schema = 'virtue_foundation_dataset' ORDER BY table_name, ordinal_position")
    remote = {**remote_agg, **remote_fp}
    local = {**local_agg, **local_fp}
    mism = {k: [remote[k], None if local[k] is None else str(local[k])] for k in remote if not same(remote[k], local[k])}
    res = {"n_checks": len(remote), "n_mismatches": len(mism), "mismatches": mism,
           "remote": remote, "local": {k: None if v is None else str(v) for k, v in local.items()},
           "remote_schema": sch}
    OUT.mkdir(exist_ok=True)
    (OUT / "live_compare.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = compare_all()
    print(r["n_checks"], r["n_mismatches"], json.dumps(r["mismatches"], indent=1)[:3000])

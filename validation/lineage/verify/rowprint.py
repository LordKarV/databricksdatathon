"""Row-level fingerprint (binds columns within a row, unlike the auditor's per-column sums): live vs local.

Per row: md5 of all columns joined by char(1), NULL as char(2), doubles as floor(x*1e6+0.5), ints as decimal text.
Per table: count(*), count(distinct row md5), sum of int(md5[:15], 16). One SELECT per table.
"""
import hashlib, json, math, subprocess, sys
import pyarrow.parquet as pq

ROOT = "/Users/karthikvattem/projects/datathon"
CAT = "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset"
TABLES = ["facilities", "india_post_pincode_directory", "nfhs_5_district_health_indicators"]


def sql_expr(schema) -> str:
    parts = []
    for f in schema:
        t, c = str(f.type), f"`{f.name}`"
        if t == "double":
            v = f"cast(floor({c} * 1000000 + 0.5) as string)"
        elif t == "int64":
            v = f"cast({c} as string)"
        else:
            v = c
        parts.append(f"coalesce({v}, char(2))")
    return "md5(concat_ws(char(1), " + ", ".join(parts) + "))"


def local_row(vals, schema) -> str:
    out = []
    for f, v in zip(schema, vals):
        t = str(f.type)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append("\x02")
        elif t == "double":
            out.append(str(math.floor(v * 1000000 + 0.5)))
        else:
            out.append(str(v))
    return hashlib.md5("\x01".join(out).encode("utf-8")).hexdigest()


def local(t: str) -> dict:
    tab = pq.read_table(f"{ROOT}/data/raw/{t}.parquet")
    cols = [tab.column(i).to_pylist() for i in range(tab.num_columns)]
    hs = [local_row(r, tab.schema) for r in zip(*cols)]
    return {"rows": len(hs), "distinct": len(set(hs)), "fp": str(sum(int(h[:15], 16) for h in hs))}


def remote(t: str) -> dict:
    schema = pq.read_schema(f"{ROOT}/data/raw/{t}.parquet")
    e = sql_expr(schema)
    q = (f"SELECT count(*) AS rows, count(DISTINCT h) AS distinct_rows, "
         f"cast(sum(cast(conv(substr(h, 1, 15), 16, 10) AS decimal(38,0))) AS string) AS fp "
         f"FROM (SELECT {e} AS h FROM {CAT}.{t})")
    for attempt in range(3):
        r = subprocess.run([f"{ROOT}/sql.sh", q], capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            row = r.stdout.strip().splitlines()[1].split("\t")
            return {"rows": int(row[0]), "distinct": int(row[1]), "fp": row[2]}
    raise RuntimeError(r.stderr[-400:])


if __name__ == "__main__":
    res = {}
    for t in TABLES:
        lo = local(t)
        try:
            re_ = remote(t)
        except Exception as ex:
            re_ = {"error": str(ex)}
        res[t] = {"local": lo, "remote": re_, "equal": lo == re_}
    print(json.dumps(res, indent=1))
    json.dump(res, open(f"{ROOT}/validation/lineage/verify/out/rowprint.json", "w"), indent=1)

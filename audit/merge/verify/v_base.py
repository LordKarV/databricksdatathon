"""Independent base loader and F7 checks (dedup, cluster_id, source_content_id). Uses DuckDB, not the finder's common.py."""
import duckdb, json, re
RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
UUIDRX = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
con = duckdb.connect()
con.execute(f"create view raw as select * from read_parquet('{RAW}')")
con.execute(f"create view wf as select * from raw where regexp_matches(unique_id, '{UUIDRX}') and source='kie'")

def q(sql):
    return con.execute(sql).fetchall()

if __name__ == "__main__":
    print("raw rows", q("select count(*) from raw"))
    print("well-formed rows, distinct uid, distinct cluster", q("select count(*), count(distinct unique_id), count(distinct cluster_id) from wf"))
    # full-row identity: hash every column cast to text
    cols = [r[0] for r in q("select column_name from (describe wf)")]
    rowexpr = "concat_ws('\x1f', " + ", ".join(f"coalesce(cast(\"{c}\" as varchar),'<NULL>')" for c in cols) + ")"
    print("distinct full rows", q(f"select count(distinct {rowexpr}) from wf"))
    print("uids appearing >1 and whether all copies identical", q(f"select count(*), sum(case when nrow=1 then 1 else 0 end) from (select unique_id, count(distinct {rowexpr}) nrow from wf group by 1 having count(*)>1)"))
    print("dupe examples", q("select unique_id, any_value(name), count(*) from wf group by 1 having count(*)>1 order by 1 limit 12"))
    print("cluster_id per uid >1 ?", q("select count(*) from (select unique_id from wf group by 1 having count(distinct cluster_id)>1)"))
    print("uid per cluster >1 ?", q("select count(*) from (select cluster_id from wf group by 1 having count(distinct unique_id)>1)"))
    print("cluster format hex32/uuid/other", q(f"select sum(regexp_matches(cluster_id,'^[0-9a-f]{{32}}$')::int), sum(regexp_matches(cluster_id,'{UUIDRX}')::int), count(*) from (select distinct unique_id, cluster_id from wf)"))
    print("source_content_id <> content_table_id (or one null)", q("select count(*) filter (where source_content_id is distinct from content_table_id), count(*) from wf"))
    # hex cluster_id among own source_ids
    rows = q("select distinct unique_id, cluster_id, source_ids from wf")
    hx = [(c, s) for _, c, s in rows if re.fullmatch(r"[0-9a-f]{32}", c or "")]
    def pl(s):
        try:
            x = json.loads(s)
            return x if isinstance(x, list) else []
        except Exception:
            return []
    print("hex cluster in own source_ids", sum(c in pl(s) for c, s in hx), "of", len(hx))
    # source_content_id groups
    g = q("select n, count(*) from (select source_content_id, count(distinct unique_id) n from wf group by 1) group by 1 order by 1")
    shared_recs = sum(n * k for n, k in g if n > 1); groups = sum(k for n, k in g if n > 1)
    print("records sharing source_content_id", shared_recs, "groups", groups, "max", max(n for n, _ in g))

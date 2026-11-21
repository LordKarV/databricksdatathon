"""Independent re-derivation of base population and provenance-structure counts (PROV-09, Q1)."""
import duckdb, json
F = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
con = duckdb.connect()
q = lambda s: con.sql(s).fetchall()
con.sql(f"create view f as select * from '{F}'")
out = {}
out["rows"] = q("select count(*) from f")[0][0]
out["uuid_ok"] = q("select count(*) from f where regexp_full_match(unique_id,'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')")[0][0]
out["uuid_and_kie"] = q("select count(*) from f where regexp_full_match(unique_id,'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}') and source='kie'")[0][0]
con.sql("""create view w as select * from f where regexp_full_match(unique_id,'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}') and source='kie'""")
out["distinct_uid_w"] = q("select count(distinct unique_id) from w")[0][0]
out["uids_twice"] = q("select count(*) from (select unique_id from w group by 1 having count(*)>1)")[0][0]
# full-row duplicate check: distinct over all columns
out["distinct_full_rows_w"] = q("select count(*) from (select distinct * from w)")[0][0]
# do duplicated-uid rows differ on any column?
out["dup_uid_groups_full_distinct"] = q("select count(*) from (select distinct * from w where unique_id in (select unique_id from w group by 1 having count(*)>1))")[0][0]
con.sql("create view b as select distinct * from w")
out["base"] = q("select count(*) from b")[0][0]
out["cluster_distinct_base"] = q("select count(distinct cluster_id), count(cluster_id) from b")[0]
out["cluster_null_base"] = q("select count(*) from b where cluster_id is null or cluster_id in ('','null')")[0][0]
out["source_values"] = q("select source, count(*) from b group by 1")
out["cti_eq_sci"] = q("select count(*) from b where content_table_id = source_content_id")[0][0]
out["cti_null"] = q("select count(*) from b where content_table_id is null or content_table_id in ('','null')")[0][0]
out["cti_shared"] = q("""select sum(n), count(*), max(n) from (select content_table_id, count(*) n from b group by 1 having count(*)>1)""")[0]
# arrays
con.sql("""create view a as select unique_id,
  case when source_urls like '[%' then json_array_length(source_urls) end nu,
  case when source_types like '[%' then json_array_length(source_types) end nt,
  case when source_ids like '[%' then json_array_length(source_ids) end ni,
  source_urls, source_types, source_ids from b""")
out["nu_eq_nt_w"] = q("select count(*) from a where nu = nt")[0][0]
out["nu_eq_nt_on_well_formed_9970"] = q("""select count(*) from w where source_urls like '[%' and source_types like '[%' and json_array_length(source_urls)=json_array_length(source_types)""")[0][0]
out["url_total_raw_elements"] = q("select sum(nu) from a")[0][0]
out["url_median"] = q("select median(nu), max(nu), sum(case when nu=50 then 1 else 0 end), sum(case when nu>50 then 1 else 0 end) from a")[0]
# non-empty string URL elements
out["url_nonempty_elements"] = q("""select count(*) from (select unnest(cast(json(source_urls) as varchar[])) u from b where source_urls like '[%') where u is not null and trim(u)<>''""")[0][0]
out["distinct_source_ids_gt1"] = q("""select count(*) from (select unique_id, list_distinct(list_filter(cast(json(source_ids) as varchar[]), lambda x: x is not null and trim(x)<>'')) l from b where source_ids like '[%') where len(l)>1""")[0][0]
out["source_ids_zero_distinct"] = q("""select count(*) from b where not (source_ids like '[%') or len(list_filter(cast(json(source_ids) as varchar[]), lambda x: x is not null and trim(x)<>''))=0""")[0][0]
out["source_types_values"] = q("""select t, count(*) from (select unnest(cast(json(source_types) as varchar[])) t from b where source_types like '[%') group by 1 order by 2 desc limit 10""")
print(json.dumps(out, indent=1, default=str))
json.dump(out, open("v1_base.json","w"), indent=1, default=str)

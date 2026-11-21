"""Is source_types aligned with source_ids rather than source_urls? Empty URL elements? Median URLs."""
import duckdb, json
F = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
con = duckdb.connect()
con.sql(f"""create view b as select distinct * from '{F}' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""")
q = lambda s: con.sql(s).fetchall()
o = {}
o["nt_eq_ni"] = q("select count(*), count(*) filter (where json_array_length(source_types)=json_array_length(source_ids)) from b where source_types like '[%' and source_ids like '[%'")[0]
o["nt_eq_nonempty_urls"] = q("""select count(*) filter (where json_array_length(source_types)=len(list_filter(cast(json(source_urls) as varchar[]), lambda x: x is not null and trim(x)<>''))) from b where source_types like '[%' and source_urls like '[%'""")[0]
o["median_nonempty_urls"] = q("""select median(n), quantile_cont(n,0.5), count(*) filter (where n=0) from (select case when source_urls like '[%' then len(list_filter(cast(json(source_urls) as varchar[]), lambda x: x is not null and trim(x)<>'')) else 0 end n from b)""")[0]
o["rows_with_empty_url_element"] = q("""select count(*), sum(len(list_filter(cast(json(source_urls) as varchar[]), lambda x: x is null or trim(x)='')))  from b where source_urls like '[%' and len(list_filter(cast(json(source_urls) as varchar[]), lambda x: x is null or trim(x)=''))>0""")[0]
o["sample_types_ids"] = q("select source_types, left(source_ids,300), json_array_length(source_urls) from b using sample 4 (reservoir, 42)")
print(json.dumps(o, indent=1, default=str))

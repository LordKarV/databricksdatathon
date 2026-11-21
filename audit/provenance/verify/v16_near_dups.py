"""Missed-issue probe: near-duplicate facilities (different unique_id, same normalised name and city, or same exact coordinates)."""
import duckdb, json
R = "/Users/karthikvattem/projects/datathon/data/raw"
con = duckdb.connect()
con.sql(f"""create view b as select distinct * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""")
o = {}
o["same_name_city"] = con.sql("""select count(*), sum(n), max(n) from (select regexp_replace(lower(name),'[^a-z0-9]','','g') k, lower(trim(address_city)) c, count(*) n from b group by 1,2 having count(*)>1)""").fetchall()[0]
o["same_name_city_examples"] = con.sql("""select any_value(name), any_value(address_city), count(*) from b group by regexp_replace(lower(name),'[^a-z0-9]','','g'), lower(trim(address_city)) having count(*)>1 order by 3 desc limit 8""").fetchall()
o["same_name_city_within_1km"] = con.sql("""select count(*) from (select a.unique_id from b a join b c on regexp_replace(lower(a.name),'[^a-z0-9]','','g')=regexp_replace(lower(c.name),'[^a-z0-9]','','g') and lower(trim(a.address_city))=lower(trim(c.address_city)) and a.unique_id<c.unique_id
  and abs(a.latitude-c.latitude)<0.009 and abs(a.longitude-c.longitude)<0.009)""").fetchall()[0][0]
o["same_exact_coords_groups"] = con.sql("select count(*), sum(n), max(n) from (select latitude, longitude, count(*) n from b where latitude is not null group by 1,2 having count(*)>1)").fetchall()[0]
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v16_near_dups.json", "w"), indent=1, default=str)

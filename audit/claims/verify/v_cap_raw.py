"""Claims-07: the 50 cap measured on RAW JSON array length (blank and null items included), which is what
the warehouse's size(from_json(...)) returns. Also checks whether raw-50 rows carry blank items. Writes out/v_cap_raw.json."""
import json, duckdb
RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
W = "regexp_full_match(unique_id, '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}') and source='kie'"
L = lambda c: f"case when json_valid({c}) and left({c},1)='[' then json_array_length({c}) end"
q = f"""select
 sum(({L('procedure')})=50)::int proc50, sum(({L('capability')})=50)::int cap50, sum(({L('equipment')})=50)::int equip50,
 sum(({L('specialties')})=50)::int spec50,
 sum((({L('procedure')})=50 or ({L('capability')})=50 or ({L('equipment')})=50))::int any_text50,
 max({L('procedure')}) pmax, max({L('capability')}) cmax, max({L('equipment')}) emax, max({L('specialties')}) smax,
 sum(({L('capability')})=49)::int cap49
 from '{RAW}' where {W}"""
d = duckdb.sql(q).df(); r = {k: (None if v != v else int(v)) for k, v in d.iloc[0].items()}
# rows at raw 50 whose blank-filtered list is below 50: how many blank items do they carry?
q2 = f"""select count(*) n, avg(json_array_length(capability) - len(list_filter(from_json(capability,'["VARCHAR"]'), lambda x: x is not null and trim(x) <> ''))) mean_blank
 from '{RAW}' where {W} and json_valid(capability) and json_array_length(capability)=50
 and len(list_filter(from_json(capability,'["VARCHAR"]'), lambda x: x is not null and trim(x) <> ''))<50"""
r["cap_raw50_below50_after_blank_filter"] = list(duckdb.sql(q2).fetchall()[0])
json.dump(r, open("out/v_cap_raw.json", "w"), indent=1, default=float)
print(r)

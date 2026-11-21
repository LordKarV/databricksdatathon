"""Misc checks: duplicate ids cited, facilities on circle-mismatch PINs, 'null' handling in capacity/year coverage."""
import duckdb, pandas as pd, json
R = "/Users/karthikvattem/projects/datathon/data/raw"
con = duckdb.connect()
con.sql(f"""create view w as select * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""")
o = {}
o["dup_cited"] = con.sql("select unique_id, name, count(*) from w where unique_id in ('08344cdb-f455-4c22-8d31-a0a8e849124b','9264b21d-4aea-460a-9c77-613407df8439') group by 1,2").fetchall()
o["dup_all"] = con.sql("select name, address_city from w group by all having count(*)>1 and count(distinct unique_id)=1 order by 1").fetchall()
p = pd.read_parquet(f"{R}/india_post_pincode_directory.parquet")
nn = p[(p.statename != "NA")]
circ = nn.circlename.str.upper().str.replace(" CIRCLE", "", regex=False).str.strip()
ALLOW = {"NORTH EASTERN": {"ARUNACHAL PRADESH","MANIPUR","MEGHALAYA","MIZORAM","NAGALAND","TRIPURA"}, "WEST BENGAL": {"WEST BENGAL","SIKKIM","ANDAMAN AND NICOBAR ISLANDS"},
         "KERALA": {"KERALA","LAKSHADWEEP","PUDUCHERRY"}, "TAMILNADU": {"TAMIL NADU","PUDUCHERRY"}, "ANDHRA PRADESH": {"ANDHRA PRADESH","PUDUCHERRY"}, "MAHARASHTRA": {"MAHARASHTRA","GOA"},
         "GUJARAT": {"GUJARAT","THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"}, "PUNJAB": {"PUNJAB","CHANDIGARH"}, "JAMMU KASHMIR": {"JAMMU AND KASHMIR","LADAKH"}, "ASSAM": {"ASSAM","MEGHALAYA"},
         "CHATTISGARH": {"CHHATTISGARH"}, "APS": set()}
bad = set(nn[[s not in ALLOW.get(c, {c}) for c, s in zip(circ, nn.statename)]].pincode)
f = con.sql("select distinct * from w").df()
z = f.address_zipOrPostcode.fillna("").str.replace(r"\s+", "", regex=True)
pin = pd.to_numeric(z.where(z.str.fullmatch(r"[1-9]\d{5}")), errors="coerce")
o["fac_on_circle_mismatch_pins"] = int(pin.isin(bad).sum())
o["official_is_aggregator_social"] = con.sql("select count(*) from (select distinct * from w) where regexp_matches(lower(officialWebsite), 'practo|justdial|facebook|instagram|lybrate|goo\\.gl|google\\.')").fetchall()[0][0]
o["websites_with_aggregator"] = con.sql("select count(*), count(*) filter (where websites like '%practo%' or websites like '%justdial%') from (select distinct * from w) where websites like '[%'").fetchall()[0]
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v15_misc.json", "w"), indent=1, default=str)

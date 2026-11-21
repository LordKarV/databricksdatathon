"""Missed-issue probe: US-style template text (911, board certified, patient portal) and 'Dr. ' name prefix artefacts."""
import duckdb, json
R = "/Users/karthikvattem/projects/datathon/data/raw"
con = duckdb.connect()
con.sql(f"""create view b as select distinct * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""")
q = lambda s: con.sql(s).fetchall()
o = {}
for lab, rx in {"call_911": r"\b911\b", "board_certified": r"(?i)board[- ]certified", "patient_portal": r"(?i)patient portal",
                "exceptional_cardiac": r"(?i)exceptional cardiac care", "open_24_hours_status": r"(?i)status: open 24 hours"}.items():
    o[lab] = q(f"""select count(*) filter (where regexp_matches(description, '{rx}')),
       count(*) filter (where regexp_matches(coalesce(procedure,'')||coalesce(equipment,'')||coalesce(capability,''), '{rx}')),
       count(*) filter (where regexp_matches(coalesce(description,'')||coalesce(procedure,'')||coalesce(equipment,'')||coalesce(capability,''), '{rx}')) from b""")[0]
o["name_dr_dot_prefix"] = q("select count(*) from b where name like 'Dr. %'")[0][0]
o["name_dr_dr"] = q("select count(*) from b where name like 'Dr. Dr%'")[0][0]
o["dr_prefix_nonperson_examples"] = q("select name from b where regexp_matches(name, '^Dr\\. .*(Hospital|Clinic|Centre|Center|Healthcare)') limit 12")
o["dr_prefix_with_hospital_word"] = q("select count(*) from b where regexp_matches(name, '^Dr\\. .*(Hospital|Hospitals|Healthcare|Medical Cent)')")[0][0]
o["call911_examples"] = q("select name, address_city, left(description, 200) from b where regexp_matches(coalesce(description,'')||coalesce(capability,''), '\\b911\\b') limit 5")
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v7_template.json", "w"), indent=1, default=str)

"""Extra probes: MRI name false positives, ambulance-only trauma claims, paediatric ICU counted as ICU,
'Siddha'/'nayan' name caps, duplicate unique_id rows. Writes out/v_extra.json."""
import json, re
import duckdb, pandas as pd
m = pd.read_parquet("../out/mentions.parquet"); g = pd.read_parquet("../out/grades.parquet")
r = {}
mri = m[m.service == "mri"]
fake = mri[mri.sentence.str.contains(r"(?i)\bmri[a-z]") & ~mri.sentence.str.contains(r"(?i)\bmris?\b|magnetic resonance|\bmra\b|\bmr (scan|imaging|angio)")]
r["mri_name_fp_sentences"] = len(fake); r["mri_name_fp_facilities_only_fp"] = int(len(set(fake.unique_id) - set(mri[~mri.index.isin(fake.index)].unique_id)))
t = m[(m.service == "trauma") & ~m.nonoffer]
amb = t.sentence.str.contains(r"(?i)ambulance")
amb_only = t.groupby("unique_id").apply(lambda x: amb[x.index].all())
ids = set(amb_only[amb_only].index)
tg = g[(g.service == "trauma") & (g.n_core > 0)]
r["trauma_ambulance_sentences"] = int(amb.sum()); r["trauma_facilities_ambulance_only"] = len(ids)
r["trauma_ambulance_only_grades"] = tg[tg.unique_id.isin(ids)].grade.value_counts().to_dict()
icu = m[m.service == "icu"]
ped = icu.sentence.str.contains(r"(?i)p(a)?ediatric icu|\bpicu\b") & ~icu.sentence.str.contains(r"(?i)\b(adult|medical|surgical|cardiac|general)\b")
r["icu_sentences_paediatric_icu"] = int(ped.sum())
pon = icu.groupby("unique_id").apply(lambda x: ped[x.index].all())
r["icu_facilities_only_paediatric_icu"] = int(pon.sum())
W = "regexp_full_match(unique_id, '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}') and source='kie'"
d = duckdb.sql(f"""select unique_id, count(*) n, count(distinct md5(concat_ws('|', name, procedure, equipment, capability, description, address_city))) variants
  from '/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet' where {W} group by 1 having count(*) > 1""").df()
r["dup_uid_groups"] = len(d); r["dup_uid_groups_with_differing_content"] = int((d.variants > 1).sum())
json.dump(r, open("out/v_extra.json", "w"), indent=1)
print(json.dumps(r, indent=1))

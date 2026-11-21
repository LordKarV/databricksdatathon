WITH f AS (
  SELECT unique_id, name, capability, procedure, equipment, specialties, description,
         from_json(procedure, 'array<string>') AS p, from_json(capability, 'array<string>') AS c,
         from_json(equipment, 'array<string>') AS e, from_json(specialties, 'array<string>') AS s
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities
  WHERE unique_id RLIKE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND source = 'kie')
SELECT count(*) AS rows_wf, count(DISTINCT unique_id) AS distinct_uid,
  sum(CASE WHEN size(p) = 50 THEN 1 ELSE 0 END) AS proc50,
  sum(CASE WHEN size(c) = 50 THEN 1 ELSE 0 END) AS cap50,
  sum(CASE WHEN size(e) = 50 THEN 1 ELSE 0 END) AS equip50,
  sum(CASE WHEN size(s) = 50 THEN 1 ELSE 0 END) AS spec50,
  sum(CASE WHEN size(p) = 50 OR size(c) = 50 OR size(e) = 50 THEN 1 ELSE 0 END) AS any_text50,
  count(DISTINCT CASE WHEN lower(concat_ws(' ', procedure, equipment, capability, description)) RLIKE 'dialy[sz]|haemodial|hemodial' THEN unique_id END) AS dialysis_text_uid,
  sum(CASE WHEN array_contains(s, 'nephrology') THEN 1 ELSE 0 END) AS neph_tag_rows,
  sum(CASE WHEN name = 'Aravind Eye Hospital' AND capability LIKE '%Pradhan Mantri National Dialysis%' THEN 1 ELSE 0 END) AS aravind_pmndp
FROM f

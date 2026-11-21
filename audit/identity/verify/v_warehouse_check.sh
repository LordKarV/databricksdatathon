#!/bin/sh
# One warehouse query and the same SQL on the local snapshot (DuckDB) for comparison.
Q="SELECT count(*) AS wf, count(DISTINCT unique_id) AS du, count(DISTINCT cluster_id) AS dc, sum(CASE WHEN phone_numbers LIKE '%9693969347%' OR officialPhone LIKE '%9693969347%' THEN 1 ELSE 0 END) AS p969, sum(CASE WHEN email LIKE '%email%protected%' THEN 1 ELSE 0 END) AS em_ph, count(DISTINCT source_content_id) AS dsc FROM TBL WHERE regexp_like(unique_id, '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') AND source = 'kie'"
echo "== warehouse"
/Users/karthikvattem/projects/datathon/sql.sh "$(echo "$Q" | sed 's/TBL/databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities/; s/regexp_like(unique_id, /unique_id RLIKE (/')"
echo "== local"
/Users/karthikvattem/projects/datathon/.venv/bin/python -c "import duckdb,sys; print(duckdb.sql(sys.argv[1]).df().to_string(index=False))" "$(echo "$Q" | sed "s#TBL#'/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet'#; s/regexp_like/regexp_matches/")"

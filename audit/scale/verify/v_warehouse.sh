#!/bin/zsh
# One live-warehouse cross-check of headline numbers (read-only SELECT).
export DATABRICKS_CONFIG_PROFILE=vf
/Users/karthikvattem/projects/datathon/sql.sh "SELECT count(*) AS wf_rows,
 sum(CASE WHEN numberDoctors = '1' THEN 1 ELSE 0 END) AS doctors_eq_1,
 sum(CASE WHEN numberDoctors RLIKE '^[0-9]+$' THEN 1 ELSE 0 END) AS doctors_filled,
 sum(CASE WHEN capacity RLIKE '^[0-9]+$' THEN 1 ELSE 0 END) AS capacity_filled,
 sum(CASE WHEN yearEstablished RLIKE '^[0-9]+$' THEN 1 ELSE 0 END) AS year_filled,
 sum(CASE WHEN try_cast(numberDoctors AS BIGINT) > 1000 THEN 1 ELSE 0 END) AS doctors_gt_1000,
 sum(CASE WHEN facilityTypeId = 'clinic' AND try_cast(capacity AS BIGINT) >= 100 THEN 1 ELSE 0 END) AS clinic_cap_ge_100,
 sum(CASE WHEN affiliationTypeIds LIKE '%\"government\"%' AND operatorTypeId = 'private' THEN 1 ELSE 0 END) AS gov_affil_private,
 sum(CASE WHEN post_metrics_most_recent_social_media_post_date LIKE '2026-%' THEN 1 ELSE 0 END) AS posts_2026,
 sum(CASE WHEN post_metrics_most_recent_social_media_post_date LIKE '2025-%' THEN 1 ELSE 0 END) AS posts_2025,
 sum(CASE WHEN affiliated_staff_presence = 'true' THEN 1 ELSE 0 END) AS staff_true
FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities
WHERE source = 'kie' AND unique_id RLIKE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"

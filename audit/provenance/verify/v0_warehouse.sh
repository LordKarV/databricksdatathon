#!/usr/bin/env bash
# One aggregate warehouse query to cross-check headline numbers against the live share.
S=databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset
/Users/karthikvattem/projects/datathon/sql.sh "
with w as (select * from $S.facilities where unique_id rlike '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\$' and source='kie'),
b as (select distinct * from w)
select
 (select count(*) from w) as well_formed,
 (select count(*) from b) as base_distinct_rows,
 (select count(distinct cluster_id) from b) as cluster_distinct,
 (select sum(n) from (select content_table_id, count(*) n from b group by 1 having count(*)>1)) as cti_shared_records,
 (select count(*) from $S.india_post_pincode_directory where latitude='NA') as pin_lat_na,
 (select count(distinct pincode) from $S.india_post_pincode_directory) as pin_distinct,
 (select count(*) from $S.india_post_pincode_directory where district='NA') as pin_district_na,
 (select count(*) from $S.nfhs_5_district_health_indicators) as nfhs_rows,
 (select count(*) from $S.nfhs_5_district_health_indicators where trim(births_in_a_private_fac_that_were_delivered_by_csection_5y_pct) = '*') as nfhs_priv_cs_star
"

WITH d AS (
  SELECT pincode, statename, try_cast(latitude AS DOUBLE) AS a, try_cast(longitude AS DOUBLE) AS b
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory),
s AS (SELECT pincode, statename,
  CASE WHEN a BETWEEN 68 AND 98 AND b BETWEEN 6 AND 38 THEN b ELSE a END AS la,
  CASE WHEN a BETWEEN 68 AND 98 AND b BETWEEN 6 AND 38 THEN a ELSE b END AS lo
  FROM d WHERE a IS NOT NULL AND b IS NOT NULL AND a <> 0 AND b <> 0),
g AS (SELECT * FROM s WHERE la BETWEEN 6 AND 37.6 AND lo BETWEEN 68 AND 97.6
  AND NOT (la BETWEEN 15.5895 AND 15.5935 AND statename NOT IN ('GOA','KARNATAKA','ANDHRA PRADESH','MAHARASHTRA'))),
c AS (SELECT pincode, percentile(la, 0.5) AS cla, percentile(lo, 0.5) AS clo FROM g GROUP BY pincode),
f AS (SELECT unique_id, latitude AS lat, longitude AS lon,
  CAST(regexp_replace(address_zipOrPostcode, '[ -]', '') AS BIGINT) AS pin
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities
  WHERE unique_id RLIKE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND source = 'kie'
    AND regexp_replace(address_zipOrPostcode, '[ -]', '') RLIKE '^[1-9][0-9]{5}$'
    AND latitude BETWEEN 6 AND 37.6 AND longitude BETWEEN 68 AND 97.6),
j AS (SELECT 12742 * asin(sqrt(pow(sin(radians(c.cla - f.lat) / 2), 2) + cos(radians(f.lat)) * cos(radians(c.cla)) * pow(sin(radians(c.clo - f.lon) / 2), 2))) AS km
  FROM f JOIN c ON f.pin = c.pincode)
SELECT count(*) AS n, sum(CASE WHEN km > 50 THEN 1 ELSE 0 END) AS gt50, sum(CASE WHEN km > 100 THEN 1 ELSE 0 END) AS gt100,
  (SELECT count(*) FROM d WHERE a BETWEEN 15.5895 AND 15.5935) AS lat1559,
  (SELECT count(*) FROM d WHERE a IS NULL OR b IS NULL) AS unparseable,
  (SELECT count(*) FROM g) AS offices_kept_naive
FROM j

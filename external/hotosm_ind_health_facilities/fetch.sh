#!/usr/bin/env bash
# Re-runnable fetch of the HOT OSM India health facilities export (HDX).
# Downloads the GeoParquet layer (about 14.5 MB), the STAC metadata and the
# data quality report, plus the HDX package metadata (licence, dates).
set -euo pipefail
OUT=/Users/karthikvattem/projects/datathon/data/external/hotosm_ind_health_facilities
BASE=https://production-raw-data-api.s3.amazonaws.com/ISO3/IND
mkdir -p "$OUT"
curl -fsS "https://data.humdata.org/api/3/action/package_show?id=hotosm_ind_health_facilities" -o "$OUT/package_show.json"
curl -fsS "$BASE/_layers/osm/health_facilities.parquet" -o "$OUT/health_facilities.parquet"
curl -fsS "$BASE/health_facilities/hotosm_ind_health_facilities_osm_metadata.json" -o "$OUT/stac_metadata.json"
curl -fsS "$BASE/health_facilities/hotosm_ind_health_facilities_report.html" -o "$OUT/quality_report.html"
ls -l "$OUT"
shasum -a 256 "$OUT/health_facilities.parquet"

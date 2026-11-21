#!/usr/bin/env bash
# Fetch India clips of the Malaria Atlas Project 2020 accessibility rasters
# (Weiss et al. 2020) from the public MAP GeoServer WCS 2.0.1 endpoint.
# Re-runnable: skips files that already exist. One request at a time with a
# pause between them to stay well under 1 request per second.
set -euo pipefail

OUT=/Users/karthikvattem/projects/datathon/data/external/map_travel_time_healthcare_2020/raw
BASE="https://data.malariaatlas.org/geoserver/Accessibility/wcs"
UA="datathon-research-client"
# India bbox: 68-98 E, 6-38 N (3600 x 3840 cells at 1/120 degree)
LAT="Lat(6,38)"
LON="Long(68,98)"
COVERAGES=(
  Accessibility__202001_Global_Motorized_Travel_Time_to_Healthcare
  Accessibility__202001_Global_Walking_Only_Travel_Time_To_Healthcare
  Accessibility__202001_Global_Motorized_Friction_Surface
)

mkdir -p "$OUT"
[ -s "$OUT/caps.xml" ] || curl -sS -f -m 120 -A "$UA" -o "$OUT/caps.xml" \
  "$BASE?service=WCS&version=2.0.1&request=GetCapabilities"

for c in "${COVERAGES[@]}"; do
  f="$OUT/india_$c.tif"
  if [ -s "$f" ]; then echo "exists $f"; continue; fi
  url="$BASE?service=WCS&version=2.0.1&request=GetCoverage&coverageId=$c&format=image/tiff&subset=$LAT&subset=$LON"
  echo "GET $url"
  curl -sS -f -m 900 -A "$UA" -o "$f.part" -w "%{http_code} %{size_download} bytes\n" "$url"
  mv "$f.part" "$f"
  sleep 2
done
ls -l "$OUT"

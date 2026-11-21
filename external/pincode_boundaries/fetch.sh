#!/usr/bin/env bash
# Fetch the data.gov.in PIN boundary GeoParquet (26.6 MB) from the ramSeraph mirror.
# Skipped on purpose: PincodeBoundaries.parquet (PostalGIS, 335 MB, over the 300 MB cap).
set -euo pipefail
OUT=/Users/karthikvattem/projects/datathon/data/external/pincode_boundaries
BASE=https://github.com/ramSeraph/indian_admin_boundaries/releases/download/postal
mkdir -p "$OUT"
curl -fL --retry 3 -o "$OUT/Datagov_Pincode_Boundaries.parquet" "$BASE/Datagov_Pincode_Boundaries.parquet"
curl -fsS https://api.github.com/repos/ramSeraph/indian_admin_boundaries/releases/tags/postal -o "$OUT/release_postal.json"
shasum -a 256 "$OUT/Datagov_Pincode_Boundaries.parquet" | tee "$OUT/sha256.txt"

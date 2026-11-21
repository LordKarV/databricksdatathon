#!/bin/sh
# Re-runnable fetch of LGD district polygons (ramSeraph mirror, release tag "districts", 2023-12-11).
# LGD_Districts.parquet is about 34.5 MB, under the 300 MB cap. Also saves the licence and release notes.
set -eu
OUT=/Users/karthikvattem/projects/datathon/data/external/lgd_district_polygons
BASE=https://github.com/ramSeraph/indian_admin_boundaries/releases/download/districts
mkdir -p "$OUT"
curl -fsSL -o "$OUT/LGD_Districts.parquet" "$BASE/LGD_Districts.parquet"
curl -fsSL -o "$OUT/DATA_LICENSE.md" https://raw.githubusercontent.com/ramSeraph/indianopenmaps/main/DATA_LICENSE.md
curl -fsSL -o "$OUT/release_districts.json" https://api.github.com/repos/ramSeraph/indian_admin_boundaries/releases/tags/districts
shasum -a 256 "$OUT"/LGD_Districts.parquet > "$OUT/SHA256SUMS"
ls -l "$OUT"

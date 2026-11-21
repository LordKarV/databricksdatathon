#!/usr/bin/env bash
# Fetch WorldPop Global2 R2025A India 2025 grids (1 km, constrained, UN-adjusted).
# Re-runnable: curl -z skips files that are unchanged on the server.
# Subset only: the 100 m total (742 MB) and the 1 km age-sex zip (874 MB) exceed
# the 300 MB cap, so we take the individual 1 km bands we need.
set -euo pipefail
OUT="${1:-/Users/karthikvattem/projects/datathon/data/external/worldpop_r2025a}"
POP=https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/IND/v1/1km_ua/constrained
AS=https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/2025/IND/v1/1km_ua/constrained
mkdir -p "$OUT"
get() {  # url
  local f="$OUT/$(basename "$1")"
  curl -sS -fL -A "datathon-research-client" --max-filesize 314572800 -z "$f" -o "$f" "$1"
  echo "$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f") $f"
  sleep 1  # stay at or under 1 request per second
}
get "$POP/ind_pop_2025_CN_1km_R2025A_UA_v1.tif"
# women 15-49 (delivery need), total under-1 and 1-4 (NICU / paediatric need)
for a in 15 20 25 30 35 40 45; do get "$AS/ind_f_${a}_2025_CN_1km_R2025A_UA_v1.tif"; done
for a in 00 01; do get "$AS/ind_t_${a}_2025_CN_1km_R2025A_UA_v1.tif"; done
(cd "$OUT" && shasum -a 256 *.tif > SHA256SUMS)

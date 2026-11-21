#!/bin/zsh
# Re-run the location and identity cleaning prototype end to end (about 20 s, local snapshot only).
# Inputs: data/raw/*.parquet plus audit outputs (audit/geo/pin_centroids.parquet, facility_geo.parquet,
# merge_signal.parquet, district_nfhs_map.csv; audit/scale/scale_flags.parquet; audit/claims/out/grades.parquet;
# audit/identity labels and out/chain_membership.csv).
set -e
cd /Users/karthikvattem/projects/datathon/cleaning/geo_identity
PY=/Users/karthikvattem/projects/datathon/.venv/bin/python
$PY places.py >/dev/null 2>&1 || true   # self-check needs pin_gazetteer.parquet; re-run after s1
for s in s1_pin_gazetteer s2_facility_location s3_resolve s4_groups s5_trust s6_eval s7_summary; do
  echo "== $s"; $PY $s.py > ${s}_stdout.txt
done
$PY places.py

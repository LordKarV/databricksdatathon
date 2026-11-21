#!/bin/zsh
# Rebuild derived/v1 from data/raw plus the audit and cleaning outputs (local only, no warehouse queries).
# About 30 s without the page fetch. The Goal 3 page fetch (about 1 minute, live web) runs only when
# FETCH=1 or derived/v1/source_page_checks.parquet is missing; otherwise the stored results are reused.
# Upstream tables are not rebuilt here: run cleaning/geo_identity/run_all.sh and cleaning/claims/run_all.sh first
# if their inputs changed.
set -e
export PYTHONDONTWRITEBYTECODE=1   # do not write __pycache__ into the audit directories we import from
cd /Users/karthikvattem/projects/datathon/pipelines/source_scoring
PY=/Users/karthikvattem/projects/datathon/.venv/bin/python
PYFETCH=/Users/karthikvattem/projects/datathon/.venv-sources/bin/python   # has pypdf for PDF pages
OUT=/Users/karthikvattem/projects/datathon/derived/v1
mkdir -p $OUT/_work
$PY ss_common.py
$PY package.py --hashes-before
echo "== s1 sources";     $PY s1_sources.py   > $OUT/_work/s1_stdout.txt
echo "== s2 gold";        $PY s2_gold.py      > $OUT/_work/s2_stdout.txt
if [[ "$FETCH" == "1" || ! -f $OUT/source_page_checks.parquet ]]; then
  echo "== s3 page check (live fetch)"; $PYFETCH s3_pagecheck.py > $OUT/_work/s3_stdout.txt
else
  echo "== s3 page check: reusing stored source_page_checks.parquet"
fi
echo "== s4 data points"; $PY s4_datapoints.py > $OUT/_work/s4_stdout.txt
echo "== s5 fit";         $PY s5_fit.py        > $OUT/_work/s5_stdout.txt
echo "== s6 scores";      $PY s6_score.py      > $OUT/_work/s6_stdout.txt
echo "== s7 evaluation";  $PY s7_eval.py       > $OUT/_work/s7_stdout.txt
echo "== package";        $PY package.py
echo "== selfcheck";      $PY selfcheck.py

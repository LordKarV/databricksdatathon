#!/bin/sh
# Re-run the claims cleaning prototype from the local snapshot (no warehouse queries). About 4 minutes.
set -e
cd "$(dirname "$0")"
PY=/Users/karthikvattem/projects/datathon/.venv/bin/python
$PY lexicon.py                      # regex self-checks
$PY build_claims.py > out/build_stdout.txt
$PY grade.py > out/grade_stdout.txt  # v1, v2 and both quarantine ablations
$PY evaluate.py > out/eval_stdout.txt
$PY measure.py > out/measure_stdout.txt
$PY handcheck.py score

#!/bin/sh
# Fetch the NHSRC LaQshya certification master PDF and convert it to layout text.
set -eu
URL="https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf"
OUT=/Users/karthikvattem/projects/datathon/data/external/laqshya_master
mkdir -p "$OUT"
curl -sSfL --max-filesize 314572800 -A "Mozilla/5.0 (datathon research)" -o "$OUT/LaQshya_Master_data-08-04-2026.pdf" -D "$OUT/headers.txt" "$URL"
shasum -a 256 "$OUT/LaQshya_Master_data-08-04-2026.pdf" > "$OUT/sha256.txt"
pdftotext -layout "$OUT/LaQshya_Master_data-08-04-2026.pdf" "$OUT/laqshya.txt"
pdftotext -tsv "$OUT/LaQshya_Master_data-08-04-2026.pdf" "$OUT/words.tsv"
HERE=$(cd "$(dirname "$0")" && pwd)
PY=/Users/karthikvattem/projects/datathon/.venv/bin/python
cd "$HERE"
"$PY" -I parse.py "$OUT/words.tsv" "$OUT/laqshya.parquet"
"$PY" -I join.py "$OUT" /Users/karthikvattem/projects/datathon > "$OUT/join_stdout.txt"

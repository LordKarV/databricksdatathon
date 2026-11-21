#!/bin/sh
# Fetch the MoHFW NPPMTBI trauma care facility list (Annexure-I, 196 TCFs) and the
# 2019 programme brief that carries the level (I/II/III) and functionality status.
# The live MoHFW URLs no longer resolve (main.mohfw.gov.in: DNS failure; www: 404 on
# 2026-11-21), so each file falls back to its Wayback Machine raw ("id_") snapshot.
set -u
OUT=/Users/karthikvattem/projects/datathon/data/external/mohfw_trauma_196
UA="Mozilla/5.0 (datathon research fetch)"
mkdir -p "$OUT"
date -u >> "$OUT/fetch_log.txt"

# fetch NAME URL [URL...]: first URL that returns HTTP 200 and a %PDF header wins.
fetch() {
  name=$1; shift
  for url in "$@"; do
    code=$(curl -sS -L -A "$UA" --max-time 90 --max-filesize 314572800 \
      -o "$OUT/$name.part" -w '%{http_code}' "$url" 2>>"$OUT/curl_err.txt")
    echo "$name: $url -> HTTP $code" | tee -a "$OUT/fetch_log.txt"
    if [ "$code" = "200" ] && head -c 5 "$OUT/$name.part" | grep -q '%PDF'; then
      mv "$OUT/$name.part" "$OUT/$name"
      echo "$url" > "$OUT/$name.url"
      shasum -a 256 "$OUT/$name" | tee -a "$OUT/fetch_log.txt"
      return 0
    fi
    rm -f "$OUT/$name.part"
    sleep 2
  done
  echo "$name: all URLs failed" | tee -a "$OUT/fetch_log.txt" >&2
  return 1
}

P1="sites/default/files/List%20of%20Trauma%20Care.pdf"
fetch source.pdf \
  "https://main.mohfw.gov.in/$P1" \
  "https://www.mohfw.gov.in/$P1" \
  "https://web.archive.org/web/20231215043518id_/https://main.mohfw.gov.in/$P1"

P2="sites/default/files/Prog%20brief%20Trauma%20component%20.pdf"
fetch brief.pdf \
  "https://www.mohfw.gov.in/$P2" \
  "https://web.archive.org/web/2023id_/https://main.mohfw.gov.in/$P2"

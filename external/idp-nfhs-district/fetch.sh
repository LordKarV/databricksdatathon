#!/usr/bin/env bash
# Fetch the India Data Portal NFHS package metadata plus its two CSVs.
# ckan.indiadataportal.com refused TCP connections on 2026-11-21, so this
# tries it first and falls back to ckandev.indiadataportal.com, which served
# the same package id (591d88dd-...).
set -euo pipefail
OUT=/Users/karthikvattem/projects/datathon/data/external/idp-nfhs-district
UA="datathon-research-client"
PKG=national-family-health-survey-nfhs
mkdir -p "$OUT"

HOST=""
for h in ckan.indiadataportal.com ckandev.indiadataportal.com; do
  if curl -sS -f -m 30 -A "$UA" -o "$OUT/package_show.json" \
       "https://$h/api/3/action/package_show?id=$PKG"; then
    HOST=$h; break
  fi
  echo "host $h failed, trying next" >&2
  sleep 1
done
[ -n "$HOST" ] || { echo "no CKAN host reachable" >&2; exit 1; }
echo "metadata from https://$HOST/api/3/action/package_show?id=$PKG"

# Resource URLs come from the metadata; only accept https URLs on the IDP CKAN hosts.
/Users/karthikvattem/projects/datathon/.venv/bin/python -I -c '
import json, sys
for r in json.load(open(sys.argv[1]))["result"]["resources"]:
    u = r["url"]
    assert u.startswith(("https://ckan.indiadataportal.com/", "https://ckandev.indiadataportal.com/")), u
    print(u)
' "$OUT/package_show.json" | while read -r url; do
  name=$(basename "$url")
  case "$name" in *[!A-Za-z0-9._-]*|.*) echo "bad name $name" >&2; exit 1;; esac
  sleep 1
  curl -sS -f -L --max-redirs 3 -m 120 -A "$UA" -o "$OUT/$name" -w "%{http_code} %{size_download} $url\n" "$url"
  if head -c 200 "$OUT/$name" | grep -qi "<html"; then echo "got HTML, not CSV: $name" >&2; exit 1; fi
done
shasum -a 256 "$OUT"/*.csv
date -u +"fetched %Y-%m-%dT%H:%M:%SZ" > "$OUT/FETCHED_AT"

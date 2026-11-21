#!/usr/bin/env bash
# The HOT export keeps only 12 OSM tags (no emergency, addr:postcode, beds, phone).
# This pulls one state (Bihar) of hospitals and clinics with ALL tags from the
# public Overpass API, to measure how often the dropped tags exist. One request.
set -euo pipefail
OUT=/Users/karthikvattem/projects/datathon/data/external/hotosm_ind_health_facilities
Q='[out:json][timeout:180];area["ISO3166-2"="IN-BR"]->.a;(nwr["amenity"~"^(hospital|clinic)$"](area.a);nwr["healthcare"~"^(hospital|clinic|centre)$"](area.a););out tags center;'
curl -fsS --retry 3 --retry-delay 15 --retry-all-errors -A "datathon-research-client" --data-urlencode "data=$Q" https://overpass-api.de/api/interpreter -o "$OUT/overpass_bihar_hospitals_clinics.json"
ls -l "$OUT/overpass_bihar_hospitals_clinics.json"

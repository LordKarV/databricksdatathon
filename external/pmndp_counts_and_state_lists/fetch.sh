#!/bin/sh
# Fetch PMNDP state counts (NHSRC table + PMNDP portal map data) and the Goa state centre list.
# Polite: one request at a time, 1 s apart. Re-runnable; overwrites the files it writes.
set -eu
OUT=/Users/karthikvattem/projects/datathon/data/external/pmndp_counts_and_state_lists
UA="Mozilla/5.0 (datathon research)"
mkdir -p "$OUT/state_lists" "$OUT/js"
get() { curl -sSfL -A "$UA" --max-filesize 300000000 -o "$OUT/$1" "$2"; echo "$(date -u +%FT%TZ) $2 -> $1" >> "$OUT/fetch_log.txt"; sleep 1; }
get map_table.html             https://www.nhsrcindia.org/pmndp-map-table
get copyright-policy.html      https://www.nhsrcindia.org/copyright-policy
get terms-and-conditions.html  https://www.nhsrcindia.org/terms-and-conditions
# Home page embeds the requester IP in form URLs; keep only the "as on" date and headline counters.
get pmndp_home.html            https://pmndp.mohfw.gov.in/en
grep -oE 'Statewise Status of PMNDP \(As on [^)]*\)|Last Updated On: [0-9-]+' "$OUT/pmndp_home.html" > "$OUT/portal_as_on.txt"
rm -f "$OUT/pmndp_home.html"
get js/settings.js             https://pmndp.mohfw.gov.in/themes/rvs/js/settings.js
get pmndp_terms.html           https://pmndp.mohfw.gov.in/en/terms-and-conditions
get pmndp_website_policies.html https://pmndp.mohfw.gov.in/en/website-policies
get pmndp_copyright.html       https://pmndp.mohfw.gov.in/node/139
get state_lists/goa_pmndp_list_of_centres_2020.pdf https://nhm.goa.gov.in/wp-content/uploads/2020/07/PMNDP-List-of-centres.pdf
# The PDF carries staff names, e-mails and mobile numbers. Keep only the PIN codes (used by parse.py to
# check the hand transcription) and delete the PDF and its full text.
pdftotext -layout "$OUT/state_lists/goa_pmndp_list_of_centres_2020.pdf" - | grep -oE '\b40[0-9]{4}\b' | sort -u > "$OUT/state_lists/goa_pins.txt"
rm -f "$OUT/state_lists/goa_pmndp_list_of_centres_2020.pdf" "$OUT/state_lists/goa.txt"

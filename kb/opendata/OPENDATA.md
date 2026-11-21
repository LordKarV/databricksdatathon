# Open-data enrichment: hours, emergency, specialities, beds

Independent facts about our facilities from OpenStreetMap (OSM) and Wikidata, joined to the
Virtue Foundation (VF) records with a hand-checked matcher. Every fact carries the source id, a
link, the raw tag or statement it came from, and the match confidence of the join. All numbers
below come from the scripts in this folder; denominators are stated.

Short version: 2,844 of 9,959 VF facilities (28.6%) match an open-data record at high or medium
confidence, but the tags we wanted are rare in OSM, so only 134 (1.3%) gain opening hours, 177
(1.8%) an emergency tag, 260 (2.6%) specialities and 51 (0.5%) a bed count. The match itself
(existence and location confirmed by an independent map) is the larger contribution. The
facts table is an extra, independently cited signal for the few facilities that have it, and
nothing more.

## Files

| file | rows | what |
|---|---|---|
| osm_health_facilities.parquet | 136,396 | every OSM health feature in India with all tags parsed (hours, emergency, speciality, beds, operator, switchboard phone, website, wheelchair, source, check_date, last edit) |
| wikidata_medical_facilities.parquet | 14,286 | Wikidata items that are a medical facility (Q4260475 or subclass) in India |
| tag_coverage.json | | tag coverage for OSM (all, hospitals, clinics) and Wikidata, hours parse results |
| vf_candidates.parquet | 17,662 | best OSM and best Wikidata candidate for each VF facility, with match features and tier |
| vf_opendata_match.parquet | 17,662 | the same, plus the source fields, match_conf and source_url |
| vf_opendata_facts.parquet | 6,001 | long table: one fact per row (field, value, evidence, source_url, match_tier, match_conf, observed_at, licence), high and medium matches only |
| opendata_not_in_vf.parquet | 147,080 | OSM and Wikidata facilities that no VF record matched, `in_provided_dataset = False` |
| handcheck_matches.csv, handcheck_near_misses.csv, handcheck_validation.csv | 40, 20, 35 | hand-check samples with my verdict and a note |
| precision.json, stats.json | | precision with Wilson intervals; coverage, counts by state, cross-checks |

Scripts, in run order (the first three fetch or read big inputs, the rest take seconds to a minute):

```
.venv/bin/python -I kb/opendata/fetch_wikidata.py
curl -A datathon-facility-check/0.1 -o data/crawl/opendata/osm/india-261120.osm.pbf https://download.geofabrik.de/asia/india/india-261120.osm.pbf
.venv-kb2/bin/python -I kb/opendata/extract_osm.py data/crawl/opendata/osm/india-261120.osm.pbf data/crawl/opendata/osm/health_alltags.parquet
.venv-kb2/bin/python -I kb/opendata/build_sources.py
.venv-kb2/bin/python -I kb/opendata/match_vf.py candidates
.venv-kb2/bin/python -I kb/opendata/finalize.py
.venv/bin/python -I kb/opendata/osm_hours.py        # parser self-check
```

`.venv-kb2` is this step's own venv (pyosmium, scipy, pandas, pyarrow, rapidfuzz, duckdb).

## Sources, access and licence

The task named the public Overpass API and query.wikidata.org, but both block us under our
robots.txt rule: overpass-api.de/robots.txt has `Disallow: /api/` and
query.wikidata.org/robots.txt has `Disallow: /sparql` for all agents. (Python's robotparser
returned "allowed" for Overpass, because the server answered its robots request with a 5xx at
capacity. The robots.txt fetched with curl disallows it, so I treated it as disallowed.) The two
public Overpass mirrors (overpass.kumi.systems, overpass.private.coffee) have no robots.txt but
timed out after 60 s on a 3-node test query. The HOT raw-data API caps anonymous exports at
80,000 sq km.

What I used instead:
- OSM: the Geofabrik India extract `india-261120.osm.pbf` (OSM data up to 2026-11-20,
  1,716,543,956 bytes, md5 de05cd22fcffedad76ad165e94d43ee7, checked against Geofabrik's .md5).
  One download; Geofabrik's robots.txt allows it. Public Geofabrik extracts carry version and
  timestamp but no user names, so no contributor data is kept. Raw file under
  data/crawl/opendata/osm/ (gitignored).
- Wikidata: the QLever SPARQL endpoint https://qlever.dev/api/wikidata (University of
  Freiburg). It serves full Wikidata (dump of 2026-08-10 plus live updates, per its `cmd=stats`).
  It has no robots.txt (404). Three queries, 2 s apart, fetched 2026-11-21T19:15Z. Query text
  and raw JSON are in data/crawl/opendata/wikidata/*.rq and *.json.
- Licences: OSM is ODbL 1.0 ("(c) OpenStreetMap contributors", credit and share-alike on an
  adapted database; see external/hotosm_ind_health_facilities/README.md for our reading).
  Wikidata is CC0 1.0. Every fact row has a `licence` column. The match table is an adapted
  database under ODbL: keep it as a separate table, and be ready to publish
  (unique_id, osm_id, tier, distance) if the demo is public.

The Wikidata queries (full text in data/crawl/opendata/wikidata/):
- core: `?item wdt:P31/wdt:P279* wd:Q4260475 ; wdt:P17 wd:Q668`, English label, P625 coordinate.
- props: same items, statements P31, P6801 (beds), P856 (website), P137 (operator), P131, P281
  (postcode), P1995 (health specialty), P912 (has facility), P571 (inception), P1813, P127.
- state: P131+ up to a state item. It returned only 46 rows (my state classes were wrong), so it is
  unused. State comes from the nearest PIN centre instead, see below.

## Step 1: OSM tags

Selection: amenity in hospital, clinic, doctors, dentist, health_post, nursing_home, or any
`healthcare=*` except pharmacy. The result is 136,396 features (126,700 nodes, 9,590 ways, 106
relations). Ways get the mean of their node locations. Relations take the HOT export's bbox
centre. 4 relations have no coordinate. State and district come from the nearest PIN centre in
cleaning/geo_identity/pin_gazetteer.parquet (a shortcut that can be wrong within a few km of a
state border).

Tag coverage (non-null rows / features):

| tag | all 136,396 | hospitals 56,215 | clinics 22,949 |
|---|---|---|---|
| name | 134,099 (98.3%) | 54,999 (97.8%) | 22,571 (98.4%) |
| opening_hours | 3,962 (2.9%) | 1,253 (2.2%) | 1,313 (5.7%) |
| emergency | 1,831 (1.3%) | 1,756 (3.1%) | 53 (0.2%) |
| healthcare:speciality | 6,499 (4.8%) | 2,273 (4.0%) | 1,947 (8.5%) |
| beds (or capacity:beds) | 271 (0.2%) | 214 (0.4%) | 44 (0.2%) |
| operator | 5,809 (4.3%) | 2,540 (4.5%) | 1,641 (7.2%) |
| operator:type | 10,065 (7.4%) | 4,139 (7.4%) | 1,562 (6.8%) |
| phone (institutions only) | 7,653 (5.6%) | 3,994 (7.1%) | 1,691 (7.4%) |
| website | 2,988 (2.2%) | 1,920 (3.4%) | 587 (2.6%) |
| wheelchair | 978 (0.7%) | 552 (1.0%) | 151 (0.7%) |
| source | 110,580 (81.1%) | 43,989 (78.3%) | 17,470 (76.1%) |
| check_date | 2,788 (2.0%) | 1,398 (2.5%) | 640 (2.8%) |
| addr:postcode | 107,049 (78.5%) | 45,501 (80.9%) | 17,177 (74.9%) |
| wikidata | 286 (0.2%) | 275 (0.5%) | 3 (0.0%) |

Other values: emergency is yes 1,483, no 344, plus 4 junk values. The most common specialities
are general 2,433, gynaecology 569, ophthalmology 413, paediatrics 384 and orthopaedics 360
(`top_specialities` in tag_coverage.json). Beds: median 22, 90th percentile 200. Last edit
year: 73,333 features were last edited in 2020 and 11,056 in 2019 (bulk imports), with 7,280 in
2026.

Phone policy: `phone` / `contact:phone` is kept only for institution kinds (hospital, clinic,
centre, health_post, nursing_home, laboratory, blood bank and similar). It is dropped for
doctors, dentists and other one-person practices, and for any nodal-officer contact tags. No
emails are kept.

### Opening hours

osm_hours.py parses the subset of OSM opening_hours syntax that appears here: 24/7, day ranges,
lists and wrap-around ranges, several spans a day, overnight spans, off/closed, `;` overrides,
`,` additional rules, PH/SH ignored, lower-case and English day names. Anything else (months,
week numbers, sunrise, quoted comments, "9am") gets parse_ok False and is_24x7 null. No guesses.
Outputs per feature: `opening_hours_raw` (kept verbatim), `is_24x7`, `hours_readable` (for
example "Mon-Sat 09:00-21:00; Sun closed") and `hours_week` (per-day spans).

Results: 3,836 of 3,962 tagged features parse (96.8%). Of those, 1,346 are 24x7 (1,339 are the
literal "24/7") and 2,490 are not. Unparsed examples: "sunrise-sunset", "\"by appointment\"",
"available on call", "Mon - Sun : 9:00am to 8:00pm", "Mo-Su 08:30-20:00; Tu[3] off".

## Step 2: Wikidata

14,286 items, 13,789 with a coordinate. Mostly government sub-centres: P31 health sub-centre
11,382, primary health centre 1,104, hospital 1,103, public hospital 267. 11,523 of them sit in
West Bengal and 1,088 in Tripura (bulk imports). Statement coverage: beds 106 (0.7%), website
601, operator 5, postcode 12,714 (89%), health specialty 47, inception 494. Wikidata adds
little service detail. It is useful mainly for big public hospitals and medical colleges (beds,
inception) and as a second existence source.

## Step 3: matching VF facilities

Inputs: the 9,959 facilities in cleaning/geo_identity/facility_location.parquet (cleaned point
loc_lat/loc_lon plus alt_lat/alt_lon), phones and website domain from record_trust.parquet, PIN
centres from pin_gazetteer.parquet.

Method (match_vf.py):
- Candidates: every named OSM or Wikidata point within 10 km of either VF point. The best
  candidate per source is the one with the highest name score, then the shortest distance.
- Name score: the existing HOT join scorer, imported from
  external/hotosm_ind_health_facilities/match.py, not copied. It takes the min of rapidfuzz
  token_set_ratio on full names and on "core" names (kind-of-place and service words removed).
  Generic-only names are penalised. `is_distinctive` is false when the core has only admin or
  place words.
- Signals that do not come from the coordinate: PIN equality (OSM addr:postcode or Wikidata
  P281 against the VF PIN), a shared 10-digit phone, the same website domain (shared hosts like
  facebook or practo excluded), and city or district in the candidate's own address
  (`place_agree`, recorded but not used: it was true on almost every pair). `location_conflict`:
  the candidate is more than 25 km from the VF PIN centre.

### Thresholds, from the hand-check

Tuning sample: 40 distinctive pairs with name score >= 85, stratified by distance (15 at 0-1 km,
13 at 1-3 km, 12 at 3-10 km, seed 7). Plus 20 near-misses (score 70-84 within 3 km). I judged
each pair as the same facility (yes, likely), uncertain, or no, using names, both addresses,
PINs, phones and websites. Correct means yes or likely; uncertain counts as wrong.

| tuning slice | correct / n | precision | 95% Wilson |
|---|---|---|---|
| 0-1 km | 15 / 15 | 1.00 | 0.80-1.00 |
| 1-3 km | 7 / 13 | 0.54 | 0.29-0.77 |
| 3-10 km | 4 / 12 | 0.33 | 0.14-0.61 |
| beyond 1 km, PIN agrees | 8 / 8 | 1.00 | 0.68-1.00 |
| beyond 1 km, no PIN agreement | 3 / 17 | 0.18 | 0.06-0.41 |
| near-misses (score 70-84, within 3 km) | 5 / 20 | 0.25 | 0.11-0.47 |

What the samples showed:
- Within 1 km a name match is reliable. Beyond 1 km it is reliable only with PIN agreement.
- 3 to 10 km without a PIN is mostly a different facility with the same or a subset name.
- Website agreement is not identity: chains share one domain across branches (Yashoda
  Secunderabad vs Somajiguda, Anand Diagnostics).
- Subset names score 100 on token_set ("Vijaya Nethralaya Eye Hospital" vs "Vijaya Hospital").
  Requiring core-name balance >= 60 between 1 and 3 km removes most of these.
- Location conflicts are mostly wrong. These are VF coordinates copied from a same-name
  facility in another town (Veer Hospital Pimpri vs Beed, Shri Ram Hospital Jodhpur vs Sri
  Ganganagar), which is the REPORT.md finding 2 pattern.

Final rules (`tier()` in match_vf.py, in this order):
1. score >= 85 and shared phone: high.
2. score >= 85 and location_conflict: conflict. Same name, more than 25 km from the VF PIN.
   Show it as a warning and never use it as evidence.
3. Name not distinctive: medium only if score >= 95, within 0.5 km and the PIN agrees; else none.
4. score >= 90 and (within 1 km or PIN agrees): high.
5. score >= 90, within 3 km, core balance >= 60: medium.
6. score >= 70, within 0.5 km, same own website domain: medium (rescues spelling variants such as
   "Makkad" vs "Makkar Hospital" at the same address).
7. Otherwise none.

Validation: after drawing the rules I took a fresh sample of 20 high and 15 medium matches
(seed 8, excluding the tuning rows). That sample showed medium-tier conflicts were 2 of 9
correct, so I revised the rules once: conflict became its own tier, and a PIN-only rescue rule
was dropped after it produced "Drishti Eye Care" = "Smile Dental Care" in the same building.
The revision only narrowed high (a conflict now overrides a PIN match), and all 20 validation
high rows stay high, so the high number is out-of-sample. Medium and
conflict are not: their numbers include the rows the rules were set on.

| tier under final rules | sample | correct / n | precision | 95% Wilson |
|---|---|---|---|---|
| high | validation (out-of-sample) | 17 / 20 | 0.85 | 0.64-0.95 |
| high | all samples pooled | 39 / 42 | 0.93 | 0.81-0.98 |
| medium | all samples pooled | 7 / 10 | 0.70 | 0.40-0.89 |
| conflict | all samples pooled | 4 / 15 | 0.27 | 0.11-0.52 |
| none (rejected best candidate) | all samples pooled | 4 / 28 | 0.14 | 0.06-0.32 |

`match_conf` on each row is the precision of its tier: high 0.85 (validation), medium 0.70 and
conflict 0.27 (pooled, optimistic). The high errors in validation were "Burdwan Medical College"
matched to "Burdwan Homoeopathic Medical College" (Wikidata, a subset name at 10 m), and "Cimar
Women's Hospital Edappally" matched to the Cimar Cochin branch, with one uncertain Srikara
branch. All three are chain or subset-name cases where the VF point sits on the other site.

Match counts (best candidate per VF facility):

| source | high | medium | conflict | none |
|---|---|---|---|---|
| OSM | 2,596 | 195 | 634 | 6,531 |
| Wikidata | 182 | 24 | 31 | 7,469 |

44 OSM or Wikidata records are the high/medium match of more than one VF record
(`source_shared_by_n_vf`). These are mostly VF duplicates (see facility_groups.parquet).

## Coverage of our 9,959 facilities

Counted on high or medium matches. A facility counts once even if both sources match.

| gains | facilities | share | of which via a high match |
|---|---|---|---|
| any open-data match | 2,844 | 28.6% | 2,643 |
| OSM match | 2,791 | 28.0% | |
| Wikidata match | 206 | 2.1% | |
| parsed opening hours | 134 | 1.3% | 124 |
| is_24x7 = true | 88 | 0.9% | 83 |
| emergency tag (yes or no) | 177 | 1.8% | 168 |
| emergency = yes | 162 | 1.6% | 154 |
| specialities (OSM or Wikidata) | 260 | 2.6% | 236 |
| beds (OSM or Wikidata) | 51 | 0.5% | 49 |
| operator:type | 292 | 2.9% | 277 |
| wheelchair | 80 | 0.8% | 76 |

vf_opendata_facts.parquet has 6,001 facts over those 2,844 facilities. OSM contributes:
facility_kind 2,791, speciality 959 (one row per value), phone_switchboard 387, website 457,
operator_type 292, emergency 177, is_24x7 134, opening_hours 134, operator 95, wheelchair 80,
beds 19, and 5 unparsed hours strings. Wikidata contributes facility_kind 296, inception 131,
beds 32, specialities 10 and operators 2.

## Step 4: open-data facilities not in our data

opendata_not_in_vf.parquet has 147,080 rows (144,780 named): 133,640 OSM features not matched
at high/medium, and 13,440 Wikidata items that are neither matched nor linked from an OSM
`wikidata` tag. Every row has `in_provided_dataset = False` and a note saying it is open-data
context only. The app may show these as "other facilities nearby (not verified, not in the
provided dataset)". The model must not rank them.

Caveat: "not matched" is not "absent from VF". 5 of 20 near-misses were the same facility, so
some VF facilities are in this table under a spelling variant.

Focus states (rows in the table / VF records in that state):

| state | not in VF | of which OSM | of which Wikidata | OSM kind breakdown | VF records |
|---|---|---|---|---|---|
| Bihar | 6,543 | 6,520 | 23 | centre 4,932, hospital 781, clinic 499, doctors 134, dentist 115 | 260 |
| Uttar Pradesh | 8,784 | 8,758 | 26 | centre 4,308, hospital 3,444, clinic 714, doctors 126 | 948 |
| Jharkhand | 2,032 | 1,990 | 42 | centre 657, hospital 652, clinic 312, health_post 243 | 157 |
| Odisha | 3,358 | 3,330 | 28 | centre 1,436, hospital 1,010, clinic 556, dentist 167 | 119 |

The large `centre` counts are the government sub-centre and PHC bulk import, the facility level
the HOT export strips (see the HOT README). In Bihar the open-data layer has 25 times as many
facilities as VF. All states are in stats.json (`not_in_vf_by_state`). The West Bengal total is
inflated by 11.5k Wikidata sub-centres.

## Quality notes

- OSM tags are crowd-sourced and mostly old. For the 1,423 OSM hours, emergency, speciality and
  beds facts, the date (check_date if present, else the feature's last edit) falls in 2014-2018 for
  11, 2019 for 276, 2020-2022 for 315 and 2023-2026 for 821. observed_at is the feature's last edit, not the
  edit that set the tag.
- Agreement with the VF record's own text (claims.parquet, regex), on high/medium OSM matches.
  These are two independent sources saying the same thing, not ground truth:
  - OSM 24/7: 60 of 88 VF texts mention 24-hour service. OSM not 24/7: 11 of 46 VF texts claim
    24-hour service.
  - OSM emergency=yes: 115 of 162 VF texts mention emergency, casualty or trauma. Of the 15
    emergency=no, 8 VF texts still mention one.
  - Beds: 19 OSM bed counts, 7 with a VF capacity, 4 within 20%.
- Not run: no hand-check of whether OSM's tag values are true (for example, whether a "24/7"
  hospital is really open at night). The match precision above is identity only.
- A clinic's opening_hours is usually OPD hours. For a hospital, "Mo-Sa 09:00-17:00" may be
  OPD hours while emergency runs 24x7. The KB step should read is_24x7 = false on a hospital as
  "OPD hours known", not "no night emergency".
- Dialysis shifts, accreditation and insurance empanelment are not in OSM or Wikidata in any
  usable amount (dialysis appears as a speciality on a handful of features). Those need the
  PMNDP, NABH and PM-JAY sources.
- Matching uses the cleaned VF location, which follows the record's own coordinates when they
  agree with the PIN. Where the VF coordinate was geocoded from the name, distance agreement is
  not independent evidence. That is why PIN, phone and the conflict flag carry the weight.

## How the knowledge-base step should use this

- Join `vf_opendata_facts` on unique_id. Treat each row as one independent source observation
  with weight match_conf. Cite `source_url` and `evidence` (the raw `key=value` tag or the
  Wikidata statement) on the facility card, with the ODbL or CC0 credit.
- `tier = conflict` rows in vf_opendata_match are a location warning ("same name found 128 km
  away"), not evidence about services.
- Speciality values are raw OSM vocabulary (lower case, underscores removed). Mapping them to
  the canonical service taxonomy is left to the taxonomy step.

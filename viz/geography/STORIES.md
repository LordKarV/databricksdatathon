# Where care is missing: data stories

Six stories about where facility evidence exists in India and where it does not. Each has one
primary chart; four have a supporting chart. Every number below was produced by the scripts in this
directory and is stored in `data/<story>_numbers.json` and the CSV behind each chart. Charts are in
`charts/` as PNG (2x), SVG and an alt-text `.txt`.

Read every chart with one rule in mind: **no evidence in this dataset is not no care.** The Virtue
Foundation records are 88% private (8,805 of 9,959 usable records). Government hospitals, public
dialysis centres and certified public maternity theatres are mostly missing from it, and stories 2,
3 and 6 measure how much.

Reproduce: `/Users/karthikvattem/projects/datathon/.venv-viz/bin/python notebook.py` (Databricks
source format, about 40 s from a clean cache on a laptop). Each story script also runs on its own.

## Shared method

- Facilities: the 9,959 usable records in `derived/v1/facility_location.parquet`, placed by their
  cleaned ranking point (`loc_lat`, `loc_lon`). The LGD state of that point agrees with the stated
  state for 99.3%.
- Population: WorldPop 2025, 1 km, constrained, UN-adjusted (total 1,457 M; women 15-49 summed from
  the 5-year bands). District totals are zonal sums over LGD district polygons. The polygons are used
  only to aggregate and are never drawn; maps show points only, with no outline of any kind.
- NFHS-5: `data/raw/nfhs_5_district_health_indicators.parquet`, joined to LGD districts by
  `data/external/lgd_district_polygons/nfhs_lgd_crosswalk.csv` (784 of 785 polygons get a key; districts
  carved out after NFHS-5 are summed into their parent). The unit for district stories is the NFHS-5
  district (704 reached).
- Evidence ladder per (record, service), `common.evidence_flags`:
  - claimed: a dataset sentence names the service (kb/taxonomy lexicon) with non-offer, negated,
    other-facility, staff and directory lines removed (same filter as kb/web_evidence/compare_dataset.py);
  - confirmed: claimed, and a second check agrees: the facility's own website (quote-verified;
    quotes confirming a claim were right 21 of 22 times, Wilson 0.78-0.99, WEB_EVIDENCE.md), OSM
    `emergency=yes` (trauma), the MoHFW list of 196 trauma care facilities (trauma), or an NHSRC LaQshya
    Maternity OT certificate (C-section). The website is not independent of the dataset: 1,883 of 2,059
    website confirmations come from a site already in the record's own `source_urls` (s6), so a
    confirmation shows the claim is really on the facility's site, not that a second witness agrees.
  - Counts: trauma or 24x7 emergency 3,186 claimed, 1,525 confirmed; dialysis 1,035 and 474; emergency
    C-section 437 and 115.
- Drive time: least-cost motorized minutes over the MAP 2020 friction surface (Weiss et al. 2020),
  8-neighbour Dijkstra on the 1 km grid inside India (`common.travel_minutes`, scipy). Checked against
  1,398 measured OSRM road routes from `geo/out/road_factor_pairs.csv` (`travel_check.py`): median
  OSRM / raster ratio 1.00 (10th-90th percentile 0.70-1.74), Spearman 0.91 for routes of 10+ minutes,
  and the two agree on "within 60 minutes" for 91.1% of pairs.
- Intervals: Poisson (Garwood) 95% intervals for counts per million; Wilson 95% for proportions; for
  travel-time shares, the share recomputed at 60 / 1.74 = 34 min and 60 / 0.70 = 85 min (measured route
  error, not sampling error). NFHS district values are survey estimates whose intervals are not in the
  file; charts say so.
- Sealed test: no gold label of any split is used.

## 1. Bihar has 1.9 records per million people, under a third of the national 6.8

Chart: `charts/s1_state_density.png` (primary), `charts/s1_district_dots.png`.
Script: `s1_density.py`. Data: `data/s1_state.csv`, `data/s1_district.csv`.

- Bihar: 260 records for 133.5 M people = 1.95 per million (95% 1.72-2.20). India: 6.83. Delhi has
  8.0 times Bihar's rate; Chandigarh is highest at 36.5.
- Bihar has the highest child stunting of the 21 states with over 10 M people (42.6%,
  population-weighted from NFHS-5 districts) and the second-highest of the 32 over 1 M, after
  Meghalaya (43.2%, 3.5 M people). Across those states, records per
  million and stunting have Spearman rho -0.45 (95% bootstrap -0.69 to -0.12): the dataset is thinnest
  where need is highest.
- 144 of Bihar's 260 records (55%) are in Patna district, home to 5.8% of Bihar's people; 7 of 38
  Bihar districts have none.
- Nationally, 227 of 784 districts, home to 163 M people, have no record at all (district dot map).

Why it matters: a health worker in rural Bihar gets far fewer candidates than one in Punjab, and the
candidates she gets sit in Patna. The App should say when a district is thin rather than return a
distant "best" option silently. For the model, records per million in the user's district is a
coverage prior: it tells the card how much to trust an empty result.

Caveats: a record is a listing, not a hospital; duplicates (77 non-canonical records, 0.8%) are counted.
WorldPop 2025 is a modelled projection from census rounds c.2010-2020. Stunting is weighted by total
population, not under-5 population.

## 2. 104 million people live in high-need districts over an hour from confirmed dialysis

Chart: `charts/s2_dialysis_need_access.png` (primary), `charts/s2_public_vs_dataset.png`.
Script: `s2_dialysis.py`. Data: `data/s2_district.csv`, `data/s2_by_quartile.csv`,
`data/s2_public_vs_dataset.csv`.

- Need proxy: mean of four NFHS-5 prevalences (women and men 15+ with high blood pressure, with high
  blood sugar), range 9.4% to 37.7% across 704 districts. Supply: 474 confirmed dialysis records.
- 69 districts are in the top quarter of need (proxy >= 21.2%) and have under half their people within
  60 minutes of confirmed dialysis: 104 M people, 68 of the 69 with no confirmed facility inside the
  district. Most are in coastal Andhra Pradesh (27.9 M people), Telangana (19.0 M), Karnataka (13.3 M)
  and Tamil Nadu (9.6 M). East Godavari (5.7 M people, proxy 27.6%) has nobody within an hour; its
  population-weighted median drive is 140 minutes.
- At the national scale supply does follow need: confirmed dialysis per million is 0.60 (95% 0.52-0.68)
  in the highest-need quarter of districts and 0.13 (0.10-0.18) in the lowest; Spearman rho between
  need and the share within an hour is 0.26.
- The public network is mostly absent: NHSRC reports 1,994 functional PMNDP dialysis centres serving
  all 751 districts, but 8 states have fewer centres than districts, so some districts are served from a
  neighbour (the README warns against reading it as a centre in every district). Only 75 public records
  in this dataset claim dialysis, so at most 75 of the 1,994 public centres can be in it. The dataset
  confirms dialysis at 474 records (437 private, 92%, Wilson 89-94%) in 176 of 785 districts. Bihar: 94
  public centres, 19 confirmed records. Andhra Pradesh: 61 public centres for 26 districts.
- Overall, access rises with need: 68% of people in the top need quarter are within an hour of
  confirmed dialysis, 34% in the bottom quarter. The 69 hot districts are the exception to that
  pattern, not the rule.

Why it matters: dialysis is three sessions a week, so an hour each way decides whether a patient keeps
treatment. A coordinator in East Godavari would get no confirmed option from the dataset alone while
PMNDP reports every Andhra Pradesh district as served (61 centres for 26 districts, possibly from a
neighbouring district). The App should add the PMNDP layer (state counts are redistributable with NHSRC
attribution) and flag "public dialysis reported for this district, not in our list".

Caveats: the proxy is risk, not kidney failure. The 60-minute threshold is an assumption, not a
guideline. PMNDP gives counts, not facility locations, so public centres are not routed.

## 3. Where under 10% of births are caesareans, the dataset has 13 C-section claims

Chart: `charts/s3_csection_access.png` (primary), `charts/s3_public_private.png`.
Script: `s3_csection.py`. Data: `data/s3_bands.csv`, `data/s3_district.csv`, `data/s3_laqshya_match.csv`.

- 152 NFHS-5 districts (63.6 M women 15-49, mostly Uttar Pradesh, Bihar, Madhya Pradesh, Rajasthan)
  have caesarean rates under 10%, the level WHO (2015) associates with unmet need. The dataset has 13
  records claiming emergency C-section there, 3 confirmed. The NHSRC LaQshya list places 91 public
  maternity theatres ever certified in the same districts, of which 27 were still valid on the file date
  (an exact-name placement, done in verification, gives 86).
- Dataset claims per million women rise from 0.19 (rate under 5%) to 2.22 (30-45%): 9.2 times higher
  where rates top 30% than under 10%. LaQshya theatres rise too, but only about 2 times (2.1 with the fuzzy district match, 1.9 with exact names).
- In 427 of 430 districts with both rates on 50+ births (99.3%), private facilities deliver a larger
  share of babies by C-section than public ones (Wilson 98.0-99.8%); median gap 28.9 points. The dataset's C-section
  evidence comes from that private sector.

Why it matters: the places where a woman most needs a referral to a theatre are the places the dataset
cannot see. LaQshya certificates are dated, third-party evidence that a public facility does
caesareans; for the model they are a strong independent witness, and for planners they show capacity
the dataset misses. Of 902 LaQshya Maternity OT facilities only 49 match a dataset record.

Caveats: LaQshya facilities are placed in districts by name (832 of 902 matched); only 324 certificates
were valid on the file date; an expired certificate does not prove the theatre stopped. A low rate can
also reflect low need; WHO's threshold is a population-level signal, not a target.

## 4. About 500 million people live more than an hour from confirmed trauma or emergency care

Chart: `charts/s4_golden_hour.png`. Script: `s4_golden_hour.py`. Data: `data/s4_state.csv`.

- Share of India's people within 60 minutes' drive, by the evidence behind the nearest facility:
  any hospital or clinic (MAP reference) 98.5%; any record in this dataset 87.5%; a record claiming
  trauma or 24x7 emergency 79.0%; a confirmed claim 65.6% (43.6% to 80.6% across the measured route
  error). That leaves 501 M people (283 M to 821 M) more than an hour from confirmed care; an
  independent re-solve on MAP's own grid (verify/v_travel.py) gives 487 M, so the chart says "about 500".
- Lowest confirmed shares: Arunachal Pradesh 5%, Mizoram 9% (10% and 16% in the independent re-solve;
  each rests on one confirmed facility), Odisha 35%, Madhya Pradesh 38%. Madhya
  Pradesh is the largest gap in people: 97% are within an hour of some clinic, 38% of confirmed trauma
  care, leaving 56 M people outside.
- Bihar: 99% within an hour of some clinic, 63% (34% to 84%) of confirmed trauma care, from 50
  confirmed records.

Why it matters: the golden hour is the window in which trauma care most changes outcomes. The gap
between the MAP reference and the confirmed tier is the size of the evidence problem, not of the
care problem: most of those 500 M people live near a facility that may well treat trauma but whose
claim we could not check. The planner should show the nearest confirmed option and the nearest
unconfirmed one, with drive times for both.

Caveats: MAP's own facility layer (2019) counts any clinic. Raster drive times assume free-flow roads
and a vehicle; the route check shows real routes can take 0.7 to 1.7 times as long. The MoHFW trauma
list matched only 20 of 196 facilities, so most government trauma centres are not in the confirmed tier.

## 5. 93% of records sit in urban centres, home to 34% of people

Chart: `charts/s5_urban_rural.png`. Script: `s5_urban_rural.py`. Data: `data/s5_classes.csv`.

- Settlement classes (simplified Degree of Urbanisation on WorldPop): urban centres hold 34% of people
  and 9,247 of 9,959 records (93%); towns and semi-dense areas 50% of people and 557 records; rural
  areas (the sparsest class, not the Census rural population) 15% of people and 155 records. That is 18.4 records per million people in urban centres and
  0.7 in rural areas.
- Within an hour of a confirmed facility: trauma or emergency 86% of urban-centre people, 61% in towns,
  36% rural; dialysis 72%, 42%, 20%; emergency C-section 51%, 22%, 10%.

Why it matters: the gap is steepest for C-section, the service where delay is measured in minutes and
where rural women give birth. The App's default radius should grow with settlement class, and the card
should name the class so a coordinator knows why the options are far.

Caveats: the simplified method (no gap filling) calls many dense Gangetic villages "towns", so its rural
share (15%) is far below the Census 2011 rural share (68.8%); read the classes as density bands. A
record geocoded to its town centre counts as urban.

## 6. "Confirmed" mostly means "has a website"

Chart: `charts/s6_website_test.png`. Script: `s6_website_test.py`. Data: `data/s6_confirmation.csv`,
`data/s6_coverage.csv`.

- Of records that claim trauma, dialysis or C-section, 80.3% (1,653 of 2,058; Wilson 78.5-82.0%) are
  confirmed when the crawl found the facility's own website, and 2.5% (38 of 1,496; 1.9-3.5%) when it
  did not. Dialysis without a website: 0 of 374.
- This split is partly mechanical: for dialysis the only second check is the website, so 0 of 374 is
  by construction. And 1,883 of 2,059 website confirmations come from a site already in the record's own
  source list, so "confirmed" means "the claim is on the facility's site", not an independent witness.
- Who has a website the crawl could check: 51% of private records (4,528 of 8,805), 18% of public ones
  (83 of 467); 50% of
  records in urban centres, 27% in rural areas (42 of 155).

Why it matters, mostly for the model: an unconfirmed claim at a facility with no website is missing
evidence, not evidence against. If the score treats "not confirmed" as negative, it will
systematically demote public and rural facilities, which are exactly the ones stories 1 to 5 found
missing. The scorecard should carry a "has a checkable website" indicator so that the confirmation
term only counts where confirmation was possible, and the card should say "no public website to check".

Caveats: the website crawl covers 6,770 site-record pairs; government portals were skipped by design,
which lowers public coverage further. Web quotes have their own error (see the 21 of 22 check).

## Features this suggests for the model and the App

Each is computed in this directory and joins on `unique_id` or district:

| Feature | Grain | Where | Use |
|---|---|---|---|
| has_own_website | record | s6 (`site_identity` attributable site or branch) | missingness indicator for the confirmation term |
| settlement class (urban centre / town / rural) | record, user location | `common.facilities().degurba`, grid | search radius, card wording |
| district records per million | district | `data/s1_district.csv` | coverage prior; "thin district" warning |
| drive minutes to nearest confirmed facility per service | 1 km cell | `common.cached_travel` | planner, golden-hour badge |
| operator public/private | record | data/raw `operatorTypeId` | explains missing web confirmation |
| external list membership (LaQshya MOT, MoHFW TCF, PMNDP state count) | record / state | s3, s4, s2 | independent witnesses not tied to websites |
| NFHS need (NCD proxy, C-section rate, stunting) | district | s1-s3 CSVs | planner ranking of gaps, never facility scores |

## Licences and sources

WorldPop (CC BY 4.0, doi:10.5258/SOTON/WP00840 and WP00842); MAP travel time and friction surface,
Weiss et al. 2020 (CC BY); LGD district polygons via Datameet / ramSeraph (CC0, used for aggregation
only, never drawn); NFHS-5 district fact sheets (GODL-India); NHSRC LaQshya master list and PMNDP state
table (reproduction permitted with acknowledgement); MoHFW trauma care list used only as per-facility
match facts, never redistributed; OpenStreetMap (ODbL). Facility records: Virtue Foundation via
Databricks Marketplace, team use only; the CSVs here are aggregates except `travel_check.csv` and
`s3_laqshya_match.csv`, which stay in the private repo.

# Storybook: 15 data stories for Referral Saathi

This is the curated set of charts the datathon presentation, the demo, the app's "How this works"
page, the model card and the district planner dashboard draw from. It picks 15 of the 37 verified
theme stories plus the feature study and orders them as one argument: the records cannot be trusted
as written, here is what we measured, here is how we rebuilt trust, here is how the model decides and
how well it does, here is what that means for patients, and here is what we still do not know.

Machine-readable version: `viz/gallery.json` (one entry per story: headline, presenter line, PNG and
SVG paths, alt text, data CSV, script, use_in, caveat, verification). Dashboard built from these
stories: `viz/dashboard/DASHBOARD_SPEC.md`.

All paths are relative to `/Users/karthikvattem/projects/datathon`. Every chart was drawn with
`viz/style.py` and has a `.txt` alt-text sidecar. Numbers are the ones printed by each theme's
scripts and confirmed by its verifier; where this step found a difference, the story says so.

## The arc at a glance

| # | Act | Story | Primary chart | Use in |
|---|---|---|---|---|
| 1 | Problem | 1 record in 8 names another facility | `viz/trust/out/s1_who.png` | demo, slides, how page, model card |
| 2 | Problem | 1 pin in 7 is 50+ km from its own postcode | `viz/trust/out/s2_map.png` | demo, slides, how page, model card, dashboard |
| 3 | Measured | 5.4% of sentences appear on their cited page | `viz/sources/s3_paraphrase.png` | demo, slides, how page |
| 4 | Measured | 10.5% of mentions have an outside confirmation | `viz/claims/charts/s3_funnel.png` | demo, slides, how page, model card, dashboard |
| 5 | Trust: cleaning | 26% keep a problem no rule can fix | `viz/trust/out/s6_cleaning.png` | slides, how page, model card |
| 6 | Trust: external lists | 43% of NABH claims not on NABH's list | `viz/claims/charts/s4_lists.png` | demo, slides, dashboard, how page |
| 7 | Trust: websites | "Confirmed" mostly means "has a website" | `viz/geography/charts/s6_website_test.png` | model card, how page, slides, dashboard |
| 8 | Model | Every score is a sum of named points | `viz/model/s1_service_waterfalls.png` | demo, how page, slides, model card |
| 9 | Model | Type and web footprint out-earn the service text | `viz/model/s5_points_by_text_level.png` | model card, how page, slides |
| 10 | Model | The LLM judge said yes 239 of 243 times | `viz/model/s2_llm_vs_ledger.png` | demo, slides, model card, how page |
| 11 | Model | Honest evaluation: no gain from fitting, location holds | `viz/model/s3_auroc_forest.png` | model card, slides, how page |
| 12 | Impact: deserts | Bihar: 1.9 records per million, highest stunting | `viz/geography/charts/s1_state_density.png` | demo, slides, dashboard, how page |
| 13 | Impact: golden hour | About 500 M people an hour from confirmed trauma care | `viz/geography/charts/s4_golden_hour.png` | demo, slides, dashboard, how page |
| 14 | Impact: journeys | Muzaffarpur to Patna in 105 min, Yavatmal dialysis 133 km | `viz/journeys/charts/s3_itineraries.png` | demo, slides, how page |
| 15 | Limits | "No information" mostly means "not searched" | `viz/model/s4_label_budget.png` | model card, slides, how page |

Suggested slide budget: one slide per story (15), with stories 2, 8 and 13 as the three a judge should
remember. The demo uses 1, 2, 4, 8, 10, 12, 13 and 14 in that order, then opens the app.

## Act 1. The problem: data you cannot trust

### 1. One record, two hospitals

Headline: 1 record in 8 (1,232 of 9,959, 12.4%, 95% CI 11.7 to 13.0) carries a sentence that places
care at another named facility; the share climbs from 1.5% (5 of 324) in records built from 1-2 web
pages to 33.1% (638 of 1,930) in records built from 30-50, while states range only 4.5% to 16.3%.

Chart: `viz/trust/out/s1_who.png` (state, type, URL-count panels). For the demo open with
`viz/trust/out/s1_anatomy.png`: every sentence of "Aravind Eye Hospital" (listed in Hyderabad, Delhi
postcode, coordinates in Tamil Nadu, a 20-bed dialysis unit) and "Wockhardt Hospital Nagpur" (Mumbai
postcode, Nair Hospital dialysis text) as tiles.

Presenter: "An eye hospital listed in Hyderabad carries a Delhi government hospital's 20-bed dialysis
unit. That is not rare: one record in eight names another facility, and what predicts it is how many
web pages were merged into the record, not the state."

Caveat: the flag was right on about 20 of 30 sentences in the audit's hand check and misses copied
text that names no facility, so 12.4% is neither an upper nor a lower bound (audit estimate about
1,405, 14%). source_urls is capped at 50; hospitals have more URLs, so type and breadth overlap. The
anatomy records were picked by hand.

### 2. The hospital that moved

Headline: 1,367 records (13.9%) put their map pin more than 50 km from their own postcode; when the
record's own text says the facility is located elsewhere, the pin is far off 52.9% of the time (723 of
1,367) against 10.1% (821 of 8,165).

Chart: `viz/trust/out/s2_map.png` (arrows from postcode centre to pin; points and arrows only, no
boundaries). Supporting: `viz/trust/out/s2_distance.png`.

Presenter: "A distance on a referral slip is only as good as the pin. One record in seven sits more
than 50 km from its own postcode, and when the text itself says the facility is somewhere else, the pin
is off half the time: the coordinates followed the copied text."

Caveat: the verifier counts 1,373 of 9,875 far pins (still 13.9%) and 129 cross-state pins where the
chart title says 128; REPORT.md's method gives 67 of 1,407. Say "about 130" aloud. A far pin is
sometimes right and the postcode wrong (coordinates right 14 of 40 in REPORT.md's hand check).

## Act 2. What we measured

### 3. Follow the citation

Headline: only 5.4% of claim sentences (346 of 6,364 tests, 95% CI 4.4 to 6.5) appear near-verbatim on
a page from the record's own source list; even on the facility's own site only 9.6% (277 of 2,891) do.

Chart: `viz/sources/s3_paraphrase.png`.

Presenter: "The source list looks like citations but behaves like search results. So Referral Saathi
quotes the crawled page text and labels the record's own sentences as a summary, not a quote."

Caveat: a stratified sample of 385 URLs (258 fetched), so 5.4% is a pooled sample rate. Strict
matching understates support; the 70%-of-words rule gives 24.2%. Pages may have changed. Trust story 7
(`viz/trust/out/s7_citations.png`) reads the same table and is dropped as a duplicate.

### 4. A mention is not a confirmation

Headline: of 7,969 mentions of the 7 core services, 1,798 (23%) pass the record's own checks and 837
(10.5%, 9.8 to 11.2) also have a website or official-list confirmation; of 1,039 records that mention
dialysis, 106 are on an official list.

Chart: `viz/claims/charts/s3_funnel.png` (one funnel per service).

Presenter: "Mentions are cheap. 442 records mention emergency C-section; 52 have a website that says
so and 10 have a LaQshya certificate or an obstetrics postgraduate course. Each step of this ladder is
one line on the result card."

Caveat: list coverage is structural (NABH scopes for 7 codes, LaQshya and MoHFW are public subsets,
NMC is teaching hospitals only, no list covers MRI). Websites are not independent of the record.

## Act 3. How we built trust

### 5. What cleaning could and could not fix

Headline: cleaning fixes geometry, contacts and duplicates but cannot see copied text: 2,610 of 9,959
records (26.2%) keep a problem no rule can fix, 1,589 of them among the 7,812 rated "no concerns".

Chart: `viz/trust/out/s6_cleaning.png` (fixed / flagged / cannot fix).

Presenter: "We fixed what has a stated reason: 1,171 records ranked on a corrected point, 292
directory phones hidden, 9,506 sentences about other facilities quarantined. A quarter of records
still hold something no rule can see, so 'call first' is the default on every card."

Caveat: bars overlap. "No concerns" covers location and contact data only, so the overlap with copied
text is by design. Copied text that names no facility is only counted in records that also name
another facility, so the true count is likely higher.

### 6. Official lists against the record

Headline: 540 of 1,242 records that say NABH (43%, 41 to 46%) were not found on NABH's current list,
while 1,359 list-matched records never mention NABH; the government reports 1,994 public dialysis
centres against 75 public records that mention dialysis.

Chart: `viz/claims/charts/s4_lists.png`. Supporting: `viz/claims/charts/s4_pmndp.png`.

Presenter: "Official lists are the only evidence not written by the same extraction as the record. They
cut both ways: they catch stale accreditation claims and they reveal facilities the record never
admits to."

Caveat: matcher recall was not measured, so "not found" is an upper bound on false claims. LaQshya and
MoHFW are subset lists (their dataset-only segments are not false-claim rates); the LaQshya claim group
is n = 18. NABH, NMC and MoHFW facts are for per-facility citation only, never redistribution.

### 7. "Confirmed" mostly means "has a website"

Headline: 80.3% of claims (1,653 of 2,058) are confirmed when the crawl found the facility's own site
and 2.5% (38 of 1,496) when it did not; only 18% of public records (83 of 467) have one, against 51% of
private records.

Chart: `viz/geography/charts/s6_website_test.png`.

Presenter: "If we treated 'not confirmed' as 'no', we would quietly demote public and rural hospitals,
the ones poor patients use. So an unconfirmed claim at a facility with no website is shown as missing
evidence, not evidence against."

Caveat: partly mechanical (dialysis has only the website as a second check, so 0 of 374 is by
construction), and 1,883 of 2,059 website confirmations come from a site already in the record's own
sources. Observational split; website presence goes with size and type.

## Act 4. How the model decides

### 8. The witness ledger

Headline: every score is a sum of named points: Civil Hospital, Panipat gets +41.6 points for dialysis
from hospital type and web footprint and +8.3 from its own dialysis sentences; Wockhardt Hospital
Nagpur ranks 51 of 63 near Nagpur because its pin and PIN are in Mumbai, 890 km away.

Chart: `viz/model/s1_service_waterfalls.png`. Supporting: `viz/model/s1_location_waterfalls.png`.

Presenter: "Anyone can add these bars up: base, plus what the facility says, plus hints, minus
contamination, and the total equals the shipped score to 1e-9. The Nagpur case also shows what we
throw away: two sentences about Nair Hospital, Mumbai."

Caveat: three hand-picked cases. This is the fallback model (hash de82eeee9ea0d0f6-fallback);
numbers move with the v2 evidence build. Panipat holds 2 of the 2 Likely badges among 69,713 pairs.

### 9. What each evidence family contributes

Headline: across all 69,713 pairs, own service text earns 8.3 points for a single tag and only 9.2 for
sentences in several fields; prerequisite hints (ICU, OT, blood bank) out-earn the text on average at
levels 1 to 4, and text pulls ahead only at level 5 (20.8 points).

Chart: `viz/model/s5_points_by_text_level.png`. Supporting: `viz/model/s5_prior_vs_fitted.png`.

Presenter: "The fitted score mostly measures what kind of facility it is and how visible it is online,
not how clearly it describes the service. Fitting on about 22 effective labels pushed the expert's
'more text' steps to zero; we show that rather than hide it."

Caveat: levels differ in which facilities reach them. Published ablations on 39 searched test pairs
find no family whose removal changes AUROC detectably.

### 10. The LLM judge says yes

Headline: an LLM judge (llama-3.3-70b) said yes to 239 of 243 benchmark candidates (98.4%, Wilson 95.8
to 99.4), 208 of them at confidence 1, including bypass surgery at an eye hospital; the ledger spread
the same candidates from P_S 0.16 to 0.65.

Chart: `viz/model/s2_llm_vs_ledger.png`.

Presenter: "We tried an LLM as the judge. It said yes to almost everything it was shown, including
cardiac bypass at an eye hospital. That is why the LLM stays off the trust and explanation path."

Caveat: candidates are keyword-selected (all T >= 1). The test AUROC gap (0.776 vs 0.585) holds only in
the all-71 raw view; reweighted on 39 searched pairs it is -0.016 [-0.269, 0.316]. The label-free
finding stands. Use 208: the task brief's "209 at confidence 1" includes one "no".

### 11. Honest evaluation

Headline: on all 71 sealed-test pairs the fitted ledger (AUROC 0.776 [0.680, 0.862]) does not beat the
same scorecard with unfitted expert priors (0.789; difference -0.013 [-0.076, 0.048]); P_S runs high
(IPW ECE 0.197), while location scores of 0.7 or more were right 30 of 33 times.

Chart: `viz/model/s3_auroc_forest.png`. Supporting: `viz/model/s3_calibration_location.png`.

Presenter: "We show the failures next to the wins. Fitting added nothing measurable over expert priors,
and P_S is not a calibrated probability, so the card says 'chance a public check confirms it'. The
location score holds up: trust 0.7 and above, call first below it."

Caveat: 17 confirmed and 1 contradicted among 71. On the 39 searched pairs reweighted (ESS 13.4) the
ledger's AUROC is 0.498 and expert priors win by 0.129 [0.026, 0.252]. The selection rule was written
after this test was read, so this test cannot evaluate v2. Quoted from published files only.

## Act 5. Impact: deserts, golden hour, journeys

### 12. Bihar, where the data is thinnest

Headline: Bihar has 1.9 facility records per million people (260 for 133.5 M; 95% 1.72 to 2.20),
under a third of the national 6.8, and the highest child stunting (42.6%) of the 21 states with over
10 million people.

Chart: `viz/geography/charts/s1_state_density.png`. Supporting:
`viz/geography/charts/s1_district_dots.png` (227 of 784 districts, 163 M people, have no record).

Presenter: "The dataset is thinnest where need is highest: across states, records per million and
child stunting have Spearman rho -0.45. And 144 of Bihar's 260 records sit in Patna district, home to
5.8% of its people."

Caveat: a record is a listing, not a hospital, and the data is 88% private, so absence here is not
absence of care. NFHS intervals are not in the file. The theme summary called Bihar "second-highest of
any large state"; the chart's denominator (21 states over 10 M) makes it the highest, and it is
second to Meghalaya among the 32 over 1 M. Use the chart's wording.

### 13. The golden hour

Headline: about 500 million people (501 M; 283 M to 821 M across measured route error) live more than
an hour's drive from a facility whose trauma or emergency claim a second source confirms, yet 98.5%
live within an hour of some hospital or clinic.

Chart: `viz/geography/charts/s4_golden_hour.png`.

Presenter: "The gap between 98.5% and 66% is the size of the evidence problem, not the care problem:
most of those people live near a facility that may well treat trauma but whose claim nobody could
check. So the planner shows the nearest confirmed and the nearest unconfirmed option."

Caveat: an independent re-solve gives 487 M, hence "about 500". Small north-eastern states rest on one
confirmed facility each. The whisker is route error, not sampling error; travel is free-flow.

### 14. Three journeys

Headline: from Muzaffarpur, the trauma plan stabilises 4.5 km away in 6 minutes, then travels 81 km to
Patna, arriving at 105 minutes (range 91 to 130); in Yavatmal, dialysis means 133 km each way, three
times a week.

Chart: `viz/journeys/charts/s3_itineraries.png`.

Presenter: "This is the product's answer format: every stop has a time with a range, a probability, a
quoted sentence with its claim id, and any location warning. In Beed the card says 'confirm the
address by phone' because both locations are flagged."

Caveat: probabilities are the derived/v1 stub (`planner/data_v1.py`), not the fitted model.
Connectors are straight lines. Quotes are claims, picked by length, so the dialysis assessment stop
shows laboratory sentences rather than its nephrology evidence.

## Act 6. Limits

### 15. The label problem

Headline: 53 of 71 sealed-test labels say "no public information" and 32 of those were never searched;
within labelling batches the never-searched share rose from 16 of 70 (first 10 pairs) to 42 of 70 (last
10) as one 200-search budget ran out.

Chart: `viz/model/s4_label_budget.png`. Supporting: `viz/model/s4_label_agreement.png`.

Presenter: "Our biggest limit is labels, not modelling. How we treat 'no information' and how we weight
the sample move AUROC by up to 0.16, more than any model change (0.013). The next hour is better spent
searching than fitting."

Caveat: "never searched" is inferred from no_info with no URLs. Kappa is 0.38 on 30 double-labelled
pairs, but all 9 disagreements pair a verdict with "no info". Quoted from results.json.

Close the talk on the limits slide with the three standing caveats every card carries: the journeys use
stub probabilities until the fitted model replaces them; P_S is a ranking, not a probability; and no
evidence in this dataset is not no care.

## Five charts for the app's "How this works" page

These are the charts that best show how the model reaches an answer, in reading order.

1. `viz/model/s1_service_waterfalls.png`: a score is a sum of named points, shown for a strong, an
   uncertain and a contaminated case; the total reproduces the shipped score.
2. `viz/model/s1_location_waterfalls.png`: how the location witnesses (PIN, stated city, state)
   vote, and why a Nagpur hospital pinned in Mumbai drops to rank 51 of 63.
3. `viz/model/s5_points_by_text_level.png`: where points come from across all 69,713 pairs; says
   plainly that facility type and web footprint carry more weight than the service text below level 5.
4. `viz/model/s3_calibration_location.png`: how far to trust the two numbers on the card (P_S runs
   high; P_L of 0.7 or more was right 30 of 33 times).
5. `viz/features/charts/13_card_phrases.png`: all 41 kept features in the exact words the card prints,
   with how well each separated confirmed from unconfirmed pairs (DEV, location, NABH codes).

Runners-up: `viz/claims/charts/s3_funnel.png` (the evidence ladder as counts) and
`viz/model/s2_llm_vs_ledger.png` (why an LLM is not the judge).

## Cross-chart consistency

I viewed every primary chart above and checked each story script for its `viz/style.py` import
(directly or through the theme's shared module), `save()` with alt text, source notes, interval helpers
and hard-coded colours. All 15 use the shared palette, finding-style titles, zero-based bars, n and
denominators, and intervals or a stated reason for none. These need a style fix in the theme folders
(not edited here):

| Chart | Problem | Fix |
|---|---|---|
| `viz/claims/charts/s4_lists.png` | Title runs off the right edge ("NABH'" is cut) | Wrap the title narrower (`finding_title(..., wrap=60)` or `fig_title`) |
| `viz/model/s2_llm_vs_ledger.png` | Subtitle is clipped at the right edge ("Wilson", "on") | Wrap the subtitle; move the AUROC sentence to the source note |
| `viz/model/s5_points_by_text_level.png` | Legend repeats the direct labels and shows dashed lines for solid series; "Contamination, non-offer, scope" label runs past the axes | Drop the legend; shorten the label to "Flags" (as the source note already calls it) |
| `viz/journeys/charts/s3_itineraries.png` | Location warnings are drawn in hard-coded `#9a3c14` (text in a series colour; style says text in ink); a large empty band sits between title and panels; 16 x 10.5 in, not the slide ratio | Warnings in `S.INK` with a "!" prefix or italic; tighten the layout; use `S.SLIDE_SIZE` |
| `viz/trust/out/s6_cleaning.png` | Reuses semantic `verified` and `unlikely` colours for "fixed" and "cannot fix" (README: do not reuse semantic colours for ordinary series) | Use `CATEGORICAL[0]`, keep `flagged` yellow, and a neutral or `CATEGORICAL[1]` for "cannot fix" |
| `viz/trust/out/s1_anatomy.png` | Same semantic reuse for attribution classes; legend at the bottom far from the tiles | Acceptable as is for the demo; if redrawn, use categorical tokens and a legend under the title |
| `viz/model/s4_label_budget.png`, `viz/model/s3_calibration_location.png` | Right panels have a % axis but print intervals as proportions ("[0.15, 0.34]") | Print intervals in % to match the axis |
| `viz/features/charts/13_card_phrases.png` | Title describes the table, not a finding; custom fill `#f4f3ef` instead of `S.NEUTRAL` | Title such as "Of 41 kept features, 12 separate right from wrong locations with a 95% interval clear of 0.5, but only 4 do so for the service (61 DEV pairs)" (counted from `viz/features/features_catalogue.csv`, small-n rows excluded for the service); use `S.NEUTRAL` |
| `viz/trust/out/s2_map.png` | Title says 128 cross-state pins; the verifier finds 129 | Say "about 130" in the title |
| `viz/geography/charts/s4_golden_hour.png` | Four blues from the sequential ramp separated only by a legend; the two lightest dots sit below 3:1 contrast | Direct-label the four tiers on the first row (Chandigarh) or at the India row |
| `viz/model/s3_auroc_forest.png` | Three-line title | Cut to two lines; move the searched-39 clause to the subtitle |

Passed without changes: `viz/trust/out/s1_who.png`, `viz/sources/s3_paraphrase.png`,
`viz/claims/charts/s3_funnel.png`, `viz/geography/charts/s6_website_test.png`,
`viz/model/s1_service_waterfalls.png`, `viz/model/s1_location_waterfalls.png`,
`viz/geography/charts/s1_state_density.png`.

## Numbers that differ between stories

Say these the same way everywhere:

- PMNDP public dialysis in Bihar: claims story 4 counts 4 public records mentioning dialysis against 94
  centres (taxonomy claim rule, model public flag); journeys story 5 quotes 7 against 94 from
  `external/pmndp_counts_and_state_lists/README.md`. Both are right for their definitions; on slides
  use "75 public records nationally against 1,994 centres".
- Public websites: geography story 6 says 18% of public records (83 of 467) have a crawlable own site;
  the unverified patterns study (`viz/patterns/PATTERNS.md`) says a website answers for 29.8% of public
  hospitals (94 of 315, discovery split). Different denominators; use 18%.
- Cross-state far pins: 128 (chart), 129 (verifier), 67 of 1,407 (REPORT.md method). Say "about 130".
- Records with a far pin: 1,367 of 9,869 (story) vs 1,373 of 9,875 (verifier); both 13.9%.
- Top shared phone number (trust story 4, on the bench): 432 records here, 431 in REPORT.md; its "37
  states" are spellings of 16 distinct states (verifier).
- LLM judge at confidence 1: 208 yes answers (209 answers in all had confidence 1).
- Snakebite (journeys story 4, on the bench): the task brief's headline ("all 5 records are in Kerala
  and Tamil Nadu; the eight high-burden states have none") was corrected in verification to "17 records
  describe snakebite care, 3 of them in the eight states with 69% of deaths; the planner's matcher finds
  5". Never use the old headline.
- Journeys story 2 headline was reframed in verification: the 10% definitive-care figure is the
  planner's choice, and 37% of Bihar origins have a definitive site within 60 minutes that it passes
  over.

## Bench: strong stories not in the 15

No story was killed in verification; these were left out for length or overlap. All are verified
except where noted and can replace a story above.

| Story | Chart | Why it is on the bench |
|---|---|---|
| One phone number on 432 records (trust 4) | `viz/trust/out/s4_phones.png` | Vivid; its product point (directory phones hidden) is inside story 5. Verified here with `viz/trust/verify/v_s4.py` |
| Half the links are aggregators (sources 1) | `viz/sources/s1_composition.png` | Good opener for a sources slide; story 3 carries the point |
| Social media's reliability is Simpson's paradox (sources 2) | `viz/sources/s2_simpson.png` | Best pure statistics story; use in a model-card appendix |
| Research papers carry other institutions' claims (sources 4) | `viz/sources/s4_vectors.png` | Overlaps story 1 |
| Small records claim big services (claims 2) | `viz/claims/charts/s2_inflation.png` | Good demo flag ("1 doctor, claims ICU") |
| Websites confirm 60% and add 9,557 services (claims 5) | `viz/claims/charts/s5_web_by_service.png` | Overlaps story 7 |
| Hours live on websites (claims 6) | `viz/claims/charts/s6_hours.png` | Product feature ("hours unknown, call first") |
| 104 M people in high-need districts far from dialysis (geography 2) | `viz/geography/charts/s2_dialysis_need_access.png` | Strong dashboard tile |
| C-section claims where caesarean rates are under 10% (geography 3) | `viz/geography/charts/s3_csection_access.png` | Strong dashboard tile |
| 93% of records are urban (geography 5) | `viz/geography/charts/s5_urban_rural.png` | National only |
| Stop-to-stabilise plan mix (journeys 1) | `viz/journeys/charts/s1_plan_mix.png` | Stub probabilities |
| Bihar: first care 85%, definitive 10% (journeys 2) | `viz/journeys/charts/s2_time_to_care.png` | Strong demo line; stub probabilities |
| Snakebite (journeys 4, corrected headline) | `viz/journeys/charts/s4_snakebite.png` | Surprising; rests on 17 records and a lexicon gap |
| Dialysis burden of 384+ km a week (journeys 5) | `viz/journeys/charts/s5_dialysis_burden.png` | Dashboard tile |
| One hospital absorbs a state (journeys 6) | `viz/journeys/charts/s6_funnel.png` | Best picture of the stub's failure mode; model card appendix |
| Feature study charts 01, 03, 10 | `viz/features/charts/` | Model card appendix (who speaks for each service; DEV effects; NABH EBM shapes) |

Dropped: trust story 7 (same page-check table as sources story 3), trust stories 3 and 5 (true, but
less central), sources stories 5 and 6 and claims story 1 (appendix material). The patterns study in
`viz/patterns/` was not part of the verified theme results and is not used.

## What this step ran and did not run

Ran (2026-11-21):
- `viz/trust/verify/v_s1.py` to `v_s4.py`, which existed without output (the theme's verdicts were
  "unverified"). Stories 1, 3 and 4 reproduced exactly; story 2's comparison reproduced exactly and its
  far-pin count differs by 6 (above).
- An independent recomputation of trust story 6 (none existed): duckdb over `derived/v1`
  (facility_location, claims, grades, record_trust) gave 9,959 records, 1,390 with copied service
  text, 1,232 merged, 1,495 truncated, 2,610 in the union, 7,812 "no concerns", 1,589 in both, all as
  charted. The query unions records with an unanchored service sentence in a record that also has an
  `other_facility` sentence, records with a `context = 'direct'` sentence, and records with a truncated
  grade, then intersects with `trust_level = 'no_concerns'`.
- A file check that every PNG, SVG, alt-text TXT, CSV and script named in `viz/gallery.json` exists.

Not run:
- No chart was redrawn and no theme folder was edited; the style fixes above are for their owners.
- No new number on gold labels of any split; test figures are quoted from
  `model/review/stats/results.json` and `model/proto/fusion/test_metrics.json`.
- No Databricks read or write; the dashboard SQL in `viz/dashboard/DASHBOARD_SPEC.md` has not been
  executed against a warehouse.

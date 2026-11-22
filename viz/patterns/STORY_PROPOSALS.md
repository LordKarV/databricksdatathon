# Proposed storybook additions from viz/patterns

Sources read: viz/patterns/PATTERNS.md, the eight charts and alt-text sidecars in viz/patterns/charts/,
viz/patterns/p5_public_private.py, p3_quality.py (parts), p9_multiple.py, viz/STORYBOOK.md, viz/gallery.json.

## Read this first: what could and could not be checked

- viz/patterns/data/ does not exist in this checkout. The root .gitignore rule `data/` excludes it, and
  viz/patterns/common.py hard-codes ROOT = /Users/karthikvattem/projects/datathon, so the scripts cannot be
  rerun here. Every CSV named below (p5_public_private.csv, p3_coefficients.csv, all_tests.csv,
  multiple_summary.json) is "named by the study, not in the files". No number below was checked against a CSV
  row; each was copied from PATTERNS.md prose and cross-checked against the printed labels on the chart PNG
  where the chart prints it.
- STORYBOOK.md already calls the patterns study "unverified" and "not part of the verified theme results"
  (sections "Numbers that differ between stories" and "Bench"). None of these stories has a verification note
  yet. Each needs a verifier run on the author's machine before it enters gallery.json.
- Replication status below is the study's own verdict (p9_multiple.py: BH q < 0.05 on discovery, same direction
  on holdout, holdout 95% interval excludes the null).

## Story A (lead's priority): public_hospital_invisibility

Placement: Act 3 "How we built trust", directly after existing story 7 ("Confirmed" mostly means "has a
website"), as 7b, or as a replacement for the second half of story 7's headline.

Closest existing story: story 7 (geography_s6_website). Story 7 already says "only 18% of public records (83 of
467) have one, against 51% of private records" and already makes the "do not demote public hospitals" point.
Still distinct because (a) it is hospitals only with a stated operator, not all record types; (b) it is adjusted
for stated beds, URL count and region, so "public hospitals are just smaller or thinner records" is addressed;
(c) it adds two evidence channels story 7 does not have (own-site service confirmation and NABH list match) and
the PM-JAY counterpoint; (d) it has a holdout check. Risk: it overlaps story 7 enough that a judge may hear the
same point twice; consider merging it into story 7 rather than adding a slide.

Headline (numbers copied exactly from PATTERNS.md, "Findings", section 2, discovery split):
"A website answers for 94 of 315 public hospitals (29.8%) vs 2,197 of 3,297 private (66.6%), adjusted OR 0.15
(0.11 to 0.20); the facility's own website confirms at least one service for 15.6% vs 49.3% (OR 0.15, 0.10 to
0.20); and the NABH list matches 9.5% vs 36.3% (OR 0.13, 0.09 to 0.20)."
- Source of each number: PATTERNS.md section 2 headline. The three adjusted ORs and intervals also appear as
  printed row labels on charts/p5_public_private.png ("Website answers" 0.15 (0.11-0.20), "Own website confirms
  a service" 0.15 (0.10-0.20), "Matched to the NABH list" 0.13 (0.09-0.20)); n = 315 and n = 3,297 appear in
  the chart legend.
- Counts (k of n) for the 15.6% vs 49.3% and 9.5% vs 36.3% rows: not in the files (PATTERNS.md gives only the
  percentages; the counts would be pub_k / pri_k in data/p5_public_private.csv, which is absent).
- Optional second sentence, same section: "Yet public hospitals state PM-JAY empanelment more often: 19.0% vs
  10.9%, adjusted OR 1.96 (1.41 to 2.71; holdout 1.76, 1.02 to 3.03)."
- Adjustment set: stated beds, URL count, region (PATTERNS.md section 1 headline; chart subtitle;
  p5_public_private.py adj_or formula).

Presenter line: "Public hospitals are hard to see online: fewer than a third have a working website, against
two thirds of private hospitals, and accreditation lists cover them far less. A score that gives credit for a
website or an accreditation would rank them down for being offline, not for the care they give."

Chart: viz/patterns/charts/p5_public_private.png (and .svg). It serves as is for the data, but its title leads
with the PM-JAY result ("Public hospitals say PM-JAY 2.0 times the odds of private ones, yet only 30% have a
website that answers vs 67%") and it shows 11 rows. For a slide, a redraw is recommended: keep the three rows
(Website answers, Own website confirms a service, Matched to the NABH list) plus PM-JAY, with an invisibility
title. That redraw is a new chart and needs data/p5_public_private.csv, so it must be done on the author's
machine. Alt text sidecar exists: viz/patterns/charts/p5_public_private.txt.

Data CSV: viz/patterns/data/p5_public_private.csv (rows metric = site_alive, any_web_service, nabh_listed,
pmjay), written by p5_public_private.py line 98. Not present in this checkout. Test rows would be
p5_site_alive_adj, p5_any_web_service_adj, p5_nabh_listed_adj in viz/patterns/data/all_tests.csv, also absent.

Caveat (what it does not show):
- Observational. It shows public hospitals have less web and list evidence in this dataset, not that they give
  equal or better care, and not that a web-rewarding model actually ranks them lower: the ranking effect is an
  inference; no ranking experiment is in viz/patterns.
- Operator comes from operatorTypeId: 467 public, 687 not stated (PATTERNS.md section 1 caveat). Hospitals with
  operator not stated are excluded; labelled public hospitals may differ from unlabelled government hospitals.
- "Website answers" is coded with missing set to 0 (p5_public_private.py line 43), so "no website on record" and
  "website did not answer" are one category in this figure.
- List coverage is structural: NABH is a voluntary accreditation that public hospitals pursue less; a low match
  rate is a property of the list as much as of the hospitals. Matcher recall was not measured (story 6 caveat).
- The dataset is a web-visibility sample (PATTERNS.md section 9), so public hospitals with no web trace at all
  are missing entirely; the gap among all public hospitals is unknown.
- Different denominator from story 7 (18%, 83 of 467 public records of all types, "crawl found own site").
  STORYBOOK.md says to use 18% on slides; the two figures must not be shown as the same measure.
- Holdout: PATTERNS.md states "All replicated (q < 0.001)". Holdout ORs and intervals for the three headline
  rows are not in the files (only the PM-JAY holdout OR is printed); holdout rates appear only as unlabelled
  tick marks on the chart. The PM-JAY holdout interval (1.02 to 3.03) only just excludes 1.
- "CGHS (2 public hospitals) gave an unstable fit; ignore that row" (section 2 caveat).

Why it matters for the product: treat missing website and NABH evidence as missing, not negative, for public
facilities (a "no website" state separate from "website silent") and add public-sector evidence sources
(LaQshya, MoHFW lists, IPHS level) with their own weights.

## Story B: public_records_mixed_text

Placement: Act 1 "The problem", after story 1 (One record, two hospitals), as its equity follow-up; or paired
with Story A in Act 3 as one "public hospitals" slide (text is worse, evidence is thinner).

Closest existing story: story 1 (1 record in 8 names another facility; what predicts it is URL count, not
state). Still distinct: story 1 says breadth drives it; this says operator still matters with URL count held
fixed, and it names who is hit. Different outcome definition, see caveat.

Headline (PATTERNS.md section 1 headline):
"157 of 315 public hospitals in discovery (49.8%) contain a sentence attributed to another facility vs 1,061 of
3,297 private hospitals (32.2%); adjusted for stated beds, URL count and region the odds ratio is 2.34 (95% CI
1.79 to 3.07, q < 0.001); holdout 59.2% vs 32.8%, adjusted OR 2.76 (1.81 to 4.20)."
- Chart cross-check: p5_public_private.png row "Has another facility's text" prints adj. OR 2.34 (1.79-3.07).
- Supporting, same section: across all facility types with type, size, year, sources, web and region held
  fixed, public operator OR 1.73 (1.29 to 2.32; holdout 2.16, 1.43 to 3.26); this also appears in the title of
  charts/p3_forest.png. Archetype view: 50.5% discovery, 61.1% holdout.
- Mechanism line: "39% of the 467 public records carry such a name" (generic names such as District Hospital).

Presenter line: "Half of the public hospital records contain a sentence that belongs to some other hospital,
against a third for private ones, and it is not just because they have more web pages. Names like 'District
Hospital' are shared by hundreds of places, so their text gets mixed."

Chart: viz/patterns/charts/p5_public_private.png (row "Has another facility's text") serves; the cleaner single
picture is the "Operator: public (vs private)" row of viz/patterns/charts/p3_forest.png, whose title already
states 1.73 (1.29 to 2.32). No new chart strictly needed; a one-row extract would read better on a slide.

Data CSV: viz/patterns/data/p5_public_private.csv (metric = contaminated) and viz/patterns/data/
p3_coefficients.csv (named in the p3_forest.png source note). Neither is present in this checkout.

Caveat:
- "Contaminated" here is the broad flag: 2,487 of 9,959 records, vs the 1,232 used in story 1; the detector's
  sentence precision was 20 of 30 in the audit (PATTERNS.md "How to read the numbers"). Do not put 49.8% next to
  story 1's 12.4% without saying the definitions differ.
- Detector error may itself be worse for generic names, so part of the gap could be the detector, not the
  records. Not tested in the files.
- Operator labelling caveat as in Story A. Observational; residual confounding by size and teaching status is
  possible (beds are stated for only some records; a beds_missing term is used).
- The 39% generic-name share is over 467 public records of all types, a different denominator from the 315
  discovery hospitals; "generic names 75% contaminated" is quoted from viz/trust and the audit, not computed here.
- Holdout: replicated per the study, with holdout numbers printed.

Why it matters for the product: a public-hospital card should warn "this record may mix text from other
government hospitals" and lean on official lists over record text; the model gets an operator_public
contamination prior.

## Story C (optional third): list_match_not_text_claim

Placement: Act 3, after story 6 (Official lists against the record).

Closest existing story: story 6 (43% of NABH claims not on NABH's list). Still distinct: story 6 shows the text
claim and the list disagree; this shows which one predicts a correct map pin.

Headline (PATTERNS.md section 4 headline):
"A match to the NABH list halves the odds that the pin is more than 50 km from the PIN: OR 0.49 (0.40 to 0.60,
q < 0.001; holdout 0.52, 0.37 to 0.72), while records whose text says PM-JAY empanelled have drift OR 1.59 (1.20
to 2.10, q = 0.003; holdout 1.65, 1.04 to 2.61)."
- Do not headline the text-NABH contrast: "Saying 'NABH' in text without a list match does not replicate (0.62
  discovery, 0.77 holdout with CI crossing 1)". It can be said aloud only as "not established".

Presenter line: "Being on the official accreditation list goes with a pin in the right place; saying so in your
own text does not reliably. An outside list is evidence, a sentence is a claim."

Chart: viz/patterns/charts/p3_forest.png, middle panel, rows "Matched to the NABH list" and "Text says PM-JAY
empanelled". The chart has 24 rows and 3 panels and its title is about another finding, so a new 3-row extract
is needed for a slide (needs data/p3_coefficients.csv).

Data CSV: viz/patterns/data/p3_coefficients.csv. Not present in this checkout.

Caveat:
- Observational: NABH-listed facilities are larger, urban and better documented; the model adjusts for type,
  size, year, sources, web and region but the list match is not shown to cause a correct pin.
- "Drift" compares the pin with the record's own PIN centroid; either can be the wrong one (story 2 caveat:
  coordinates right 14 of 40 in a hand check).
- The PM-JAY mechanism (multi-hospital scheme pages) is labelled "Hypothesis, not tested here". The PM-JAY
  holdout interval starts at 1.04.
- Tension with Story A: public hospitals state PM-JAY more often and match NABH less, so using these two as
  features lowers location confidence for public hospitals. Present A and C together or the product advice
  looks contradictory.
- Holdout: both headline effects replicated per the study.

Why it matters for the product: use nabh_listed as a location-confidence prior and never treat the text claim
as equivalent to the list match.

## Rejected candidates

- Archetypes (section 6): the study itself says "the structure is weak" (silhouette 0.142 at k = 6, bootstrap
  ARI 0.68, k chosen because it isolates public hospitals); exploratory, not a headline.
- Off-focus claims (section 8): raw gap replicates but the adjusted effect disappears (OR 0.89, 0.55 to 1.43,
  q = 0.70); the study says do not add it.
- Top-5% anomaly score (section 11): "did not replicate (holdout 31.4% vs 24.6%, CI crossing 0)"; top-20
  verdicts by one reader.
- District supply vs need (section 9): replicated correlations but ecological, records per million partly
  measures how online a district is, and it overlaps story 12; blood-sugar link not replicated.
- Service co-occurrence (section 7): replicated and new to the storybook, but pairs come from one extraction so
  it is not independent evidence, the chart layout is hand-placed, and the product use is weak; best bench item.
- Breadth (section 5) and year established (section 10): breadth duplicates story 1; year is a null after
  adjustment (q = 0.08).

## Inconsistent or unverifiable items in viz/patterns

1. No data directory: every CSV and JSON the study cites is absent here; 613 / 407 / 293 cannot be confirmed
   (the family counts in PATTERNS.md do sum to 613, and the six archetype sizes sum to 6,970).
2. Holdout numbers for the three Story A headline rows are asserted ("All replicated") but not printed.
3. Public website share: 29.8% (94 of 315 hospitals, "website answers") vs story 7's 18% (83 of 467 records).
   Already noted in STORYBOOK.md; different measures.
4. Districts: 704 in PATTERNS.md (492 / 212 split; "531 of 704") vs 784 in story 12 ("227 of 784"). Not
   explained in the files.
5. p1_network.txt alt text says "17 of 40" pairs on a pathway among "4,217 discovery facilities"; PATTERNS.md
   says "15 of" the 25 highest-lift pairs and discovery has 6,970 records. Probably different subsets (top 40
   vs top 25; facilities with a service claim), but neither is stated.
6. Public operator and drift: p5_public_private.png prints adj. OR 1.87 (1.37-2.53) for "Pin over 50 km from
   PIN" among hospitals, while the p3_forest.png all-types row for public operator and drift crosses 1 by eye.
   PATTERNS.md mentions neither; do not claim a public drift effect.
7. Sections 3 and 2 pull in opposite directions ("no website" as a risk prior vs "do not penalise no website");
   reconcilable (uncertainty about the record, not evidence against the service) but the study does not say so.
8. Scripts and STORYBOOK.md paths point at /Users/karthikvattem/projects/datathon, not this checkout.

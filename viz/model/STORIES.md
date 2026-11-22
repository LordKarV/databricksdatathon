# How the model decides: data stories

Five stories about the Witness Ledger model (model hash de82eeee9ea0d0f6-fallback), each with one
primary chart and at most one supporting chart, sized for slides and the model card. Every chart is
in this folder as PNG (2x), SVG, an alt-text `.txt` and the tidy CSV behind it. Scripts are
`s1_ledger.py` to `s5_families.py`; `notebook.py` (Databricks source format) runs all five and was
run locally as a script (3.6 s, 9 charts, all files present).

Sealed test rule: no script reads gold labels. Stories 3 and 4 quote the published sealed-test
numbers in `model/review/stats/results.json` and `model/proto/fusion/test_metrics.json`. Stories 1,
2 and 5 use stored model outputs (no labels) and the weight table fitted on dev labels.

Paths below are relative to `/Users/karthikvattem/projects/datathon`.

## Story 1. The witness ledger: every score is a sum of named points

Headline: Civil Hospital, Panipat gets +41.6 points for dialysis from its hospital type and web
footprint and only +8.3 from its own dialysis sentences. Wockhardt Hospital Nagpur ranks 51 of 63
for dialysis near Nagpur mainly because its map point and PIN are in Mumbai, 890 km away (P_L 0.58,
G 0.216); ignoring its two Nair Hospital sentences costs it only 6.4 points (P_S 0.54 vs 0.64).

Charts: `s1_service_waterfalls.png` (primary), `s1_location_waterfalls.png`.

| case | service | own text T | P_S (90% range) | P_L | rank |
| --- | --- | --- | --- | --- | --- |
| Strong: Civil Hospital, Panipat | dialysis | 4 | 0.70 (0.38 to 0.97) | 0.99 | 1 of 12 |
| Uncertain: Referal Hospital (Nalanda/Sheikhpura) | emergency C-section | 0 | 0.24 (0.04 to 0.47) | 0.36 | 1 of 5 |
| Contaminated: Wockhardt Hospital Nagpur | dialysis | 5 | 0.54 (0.29 to 0.85) | 0.58 | 51 of 63 |

Points by family (base / own text / related-service hints / flags / web footprint / type and size):
Panipat -35.0 / +8.3 / +10.0 / 0 / +11.6 / +30.0 = +24.8; Referal -35.6 / 0 / +11.1 / 0 / +5.0 / -14.5
= -34.0; Wockhardt -35.0 / +20.1 / +10.0 / -6.4 / +5.0 / +11.0 = +4.7. Each total reproduces the
stored P_S to 1e-9 (asserted in the script).

Why it matters. A health worker can read why a facility is first, and a judge can add the bars up.
The waterfall also shows what the score is made of. Only 2 of 69,713 pairs are badged Likely, both
at Civil Hospital, Panipat (dialysis and emergency C-section); the dialysis badge rests mostly on "district hospital", "IPHS essential" and "20+ specialties", not on the dialysis sentences.
The uncertain case is the top answer for an emergency C-section in Sitamarhi, yet it has no sentence
of its own about C-sections, and the model charges it -4.8 points for being public. Its location is
split: the stated city vote costs 63.3 points, so P_L is 0.36. That case is why the v2 plan rule says
emergencies never lead with a NO SERVICE TEXT option (MODEL_SPEC 3.4). For Wockhardt, the location
chart shows what drives the rank. The map point (19.16 N, 72.94 E) and PIN 400078 (Mumbai Suburban)
are in Mumbai, 890 km from the query; the stated city says Nagpur (-63.3 points), so only the 0.42
chance that the facility sits at the Nagpur fallback point (10 km) keeps G at 0.216. The two ignored sentences cost only 6.4 points (term c1); without the
ownership filter P_S would be 0.64 instead of 0.54 (`variant_scores.parquet`, p_abl_noown).

Method. Service-head rows from `model/proto/fusion/pair_contributions.parquet`, grouped into six
families, with points = (20 / ln 2) x logit contribution. The location chart uses
`facility_contributions.parquet`. Ranks, G and U come from `model/review/explain/cases.json`. The
ignored sentences come from `rejected_atom_ids` joined to `model/proto/fusion/atoms.parquet`.

Caveats. Three hand-picked cases, chosen by the explainability review; they illustrate the
arithmetic and are not a sample. The fitted location head gives the coordinates and place-in-name
votes weight 0, so those witnesses appear on the card but cannot move P_L. The P_S range is the
stored posterior range, from draws with a 1.4% acceptance rate (MODEL_SPEC 3.2). Numbers will move
when the v2 evidence build replaces the fallback inputs.

## Story 2. The LLM judge said yes 239 of 243 times

Headline: llama-3.3-70b said "offers it" on 239 of 243 benchmark candidates (98.4%, Wilson 95.8% to
99.4%), 208 of them at confidence 1 (209 answers had confidence 1; one was a "no"). The ledger spread the same candidates from P_S 0.16 to 0.65.

Chart: `s2_llm_vs_ledger.png`.

Numbers. The LLM said yes on 60 of 60 candidates at own-text level 5 and 16 of 16 at level 1 (a tag
or list item only). It said yes on all 4 candidates with a sentence about another hospital, all 3
eye or dental candidates (2 facilities), and all 9 the ledger badged Unlikely. Example: Deshmukh Eye Hospital,
cardiac surgery, LLM yes with confidence 1, quoting "Coronary artery bypass grafting (CABG),
including intra operative balloon pump"; ledger P_S 0.23 with the scope flag. Published test AUROC
on 71 pairs: LLM judge 0.585 [0.486, 0.685], ledger 0.776 [0.680, 0.862], paired gain +0.191
[0.090, 0.284]. That gap holds only in the all-71 view: on the 39 searched pairs reweighted to the
population (fusion's IPW comparison, test_metrics.json) ledger minus LLM is -0.016 [-0.269, 0.316].
The robust part of this story is label-free: the LLM said yes to nearly everything it was shown.

Why it matters. An LLM verdict looks like an answer but carries almost no ranking information on
this data: nearly every keyword hit becomes "yes, certain". A coordinator cannot tell a CABG claim on
an eye hospital from a dialysis unit described in three fields. This is the evidence behind the
design choice to keep the LLM off the trust and explanation path (MODEL_SPEC section 2, point 5).

Method. `model/proto/decision/llm_b3_pairs.parquet` (243 rows: the top 10 keyword candidates for
each of 40 benchmark queries, 218 distinct facilities) joined to the stored P_S, T, C, S and badge in
`pair_scores.parquet`. The 243 rows cover 38 of the 40 queries (q14 and q17 had no keyword
candidate), 1 to 10 candidates each. The count matches `llm_b3_stats.json` (asserted).

Caveats. The candidates are keyword-selected, so every one has some service text (T >= 1); the LLM
was never shown a T = 0 pair here. Rows are query x facility, so a facility in two queries counts
twice. No outcome labels are used in this chart; the AUROC is quoted from the published test.

## Story 3. Honest evaluation: fitting adds nothing, P_S runs high, location works

Headline: on all 71 test pairs the fitted ledger (AUROC 0.776 [0.680, 0.862]) does not beat the
same scorecard with unfitted expert priors (0.789 [0.692, 0.875]; difference -0.013 [-0.076, 0.048]).
In that view it beats any-mention (+0.216), the LLM judge (+0.191), own-text level alone (+0.149) and
zero-prior fitting (+0.088), all with intervals above 0. On the 39 searched pairs reweighted to the
population (test_metrics.json, ESS 13.4) the ledger's own AUROC is 0.498 [0.241, 0.850], expert priors
beat it by 0.129 [0.026, 0.252], and no other difference excludes 0. The forest chart now shows both
views.

Charts: `s3_auroc_forest.png` (primary), `s3_calibration_location.png`.

Calibration. P_S fails: mean P_S 0.34 against 0.24 observed; ECE raw 0.097 [0.078, 0.180], IPW 0.197
[0.143, 0.292], so acceptance rule A3 (ECE <= 0.10) fails. The bins are monotone (0 of 15, 2 of 14,
3 of 14, 5 of 14, 7 of 14 confirmed), and on the 39 searched pairs ECE is still 0.107 raw and 0.147
IPW, so P_S must not be shown as a probability that the facility offers the service. The card says "chance a public check confirms it" instead.

Location. Only the 38 test pairs whose location label is yes or no count (33 'unclear' are excluded).
30 of 33 with P_L >= 0.7 had their location confirmed (Wilson 0.76 to 0.97); 0 of the 5 pairs below
0.7 were confirmed (derived from the published totals, 38 pairs, 30 yes).
Location AUROC 0.923, no interval (8 negatives).

Why it matters. Planners and judges should see the failures next to the wins. The fitted model adds
nothing measurable over expert priors on about 22 effective dev labels, which is why v2 ships the
least-fitted candidate unless a fitted one wins by one SE (MODEL_SPEC 3.2). The location head is the
part that holds up: trust a P_L of 0.7 or more, and call first below it.

Method. Values quoted from `results.json` (pair_level_test: primary_target_all, paired_diff_raw_primary,
calibration_primary_all, calibration_primary_searched) and `test_metrics.json` (location_head,
headline_checked). Nothing is recomputed.

Caveats. 17 positives and 1 contradicted label in 71 test pairs; intervals are wide. In this all-71
view never-searched pairs count as not confirmed (story 4 shows how much that choice moves AUROC).
The selection rule that favours B4 was written after this test was read, so this test cannot
evaluate v2 (disclosed in MODEL_SPEC 3.2).

## Story 4. The label problem: "no information" mostly means "not searched"

Headline: 53 of 71 test labels say "no public information", and 32 of those were never searched.
Within each labelling batch, the never-searched share rose from 16 of 70 (first 10 pairs, Wilson 0.15
to 0.34) to 42 of 70 (last 10, 0.48 to 0.71), consistent with the shared 200-search budget running out
(labels_p1.json note). Dev pairs alone show the same pattern: 9 of 35 early, 17 of 34 late.

Charts: `s4_label_budget.png` (primary), `s4_label_agreement.png`.

Numbers. Test: 17 confirmed, 1 contradicted, 21 searched with nothing found, 32 never searched. Dev:
14, 3, 26, 26 (dev never-searched = 58 across all 140 v2 pairs minus the 32 published for test). On
30 double-labelled pairs, service kappa is 0.38 [0.02, 0.70] with 70% raw agreement. When both
labellers reached a verdict they agreed 6 of 6 times; all 9 disagreements pair a decisive label with
"no info". The same scores give ledger AUROC 0.776 on all 71 (never-searched counted as not
confirmed) and 0.711 [0.614, 0.810] on the 39 searched pairs: that is the label-treatment effect
(0.065). Reweighting the all-71 view to the population (IPW, never-searched still counted as not
confirmed) gives 0.615 [0.406, 0.866]: that is a sampling-weight effect, not a label treatment. The
unfitted scorecard gives 0.789, 0.754 and 0.684. (The earlier version of the chart called all three
"ways to treat no info" and showed the agreement table with its axes swapped; both are fixed.)

What labels would change. Re-searching the 58 never-searched v2 pairs and drawing a uniform sample
(MODEL_SPEC section 7, step 3) would turn most "no info" rows into decisive labels. Until then the
model's AUROC depends more on evaluation choices (label treatment and weighting together move it by
up to 0.16) than on which model is used (B4 minus ledger is 0.013).

Why it matters. Kappa 0.38 reads as "labellers disagree", but every disagreement is a verdict
against "found nothing", which is consistent with uneven search effort rather than conflicting facts. For the product this is why P_S is worded as "chance a public check confirms it", why
never-searched pairs are treated as missing, and why the next hour is better spent labelling than
modelling.

Method. Quoted from `results.json` (inputs, visibility_bias_all_v2, kappa, pair_level_test). No
labels were read by these scripts. Batch position is the order of pairs in each labels_p*.json file
(checked equal to splits.json order). The crosstab in results.json is pandas
crosstab(primary, overlap).to_dict(), so its outer key is the second labeller.

Caveats. The batch-position comparison pools dev and test pairs across 7 batches; it shows the
budget effect, not a cause within any one pair. The overlap set spans dev and test (13 and 17).

## Story 5. What each evidence family contributes

Headline: across all 69,713 (facility, service) pairs, the listing's own service text earns 8.3
points for a single tag and still only 9.2 for sentences in several fields; prerequisite hints
(ICU, operating theatre, blood bank) earn more than the text on average at every level from 1 to 4
(9.1 to 10.8 points), and for 76% to 87% of individual pairs at those levels. Text only pulls ahead
at level 5 (20.8 points).

Charts: `s5_points_by_text_level.png` (primary), `s5_prior_vs_fitted.png`.

| own-text level T | pairs | own text | hints | web footprint | type and size | median P_S |
| --- | --- | --- | --- | --- | --- | --- |
| 0 none | 61,746 | 0.6 | 2.9 | 5.7 | -13.2 | 0.18 |
| 1 tag or list | 1,097 | 8.3 | 9.4 | 6.7 | -2.4 | 0.37 |
| 2 one sentence | 3,169 | 8.3 | 9.1 | 6.6 | -2.6 | 0.37 |
| 3 2+ sentences | 1,393 | 8.3 | 10.8 | 6.8 | -0.1 | 0.41 |
| 4 2+ fields | 822 | 9.2 | 10.4 | 6.8 | -1.1 | 0.40 |
| 5 plus unit | 1,486 | 20.8 | 8.7 | 6.9 | -1.0 | 0.51 |

Mean points per pair; exact population means over the stored contributions, not estimates.

Why the text line is flat (supporting chart). Fitting on dev labels set the expert's "more text"
steps to their zero bound: t3 went from +23 points to 0 and t2, t4, tb_mid, tb_high and c2 ended at
their bound. It also moved the web-footprint term the expert had set at 0 to g_mid +30 points before
Platt (90% interval -4 to +54, so 0 is not excluded) and
raised district hospital, IPHS-essential and 20+ specialties. Shipped points are these weights x the
Platt slope 0.38. Published ablations on the 39 searched test pairs (IPW, `test_metrics.json`) find
no family whose removal changes AUROC detectably (shipped minus ablation): no ownership filter +0.050 [-0.018, 0.167], no
context -0.062 [-0.153, 0.031], no merge-bucket -0.020 [-0.093, 0.057], no echo collapse -0.014
[-0.072, 0.063].

Why it matters. For the model: the score mostly measures what kind of facility it is and how visible
it is on the web, not how clearly it states the service. That is a web-visibility effect (confirmed
share 1 of 21 without a website against 30 of 119 with one, results.json), and v2 must decide whether
to keep it. For health workers: two hospitals with very different service descriptions can get the
same score; the level-1 card names the actual drivers so they are not misled.

Method. `pair_contributions.parquet` grouped into families and joined to `pair_scores.parquet`;
families sum to the stored logit for every pair (asserted to 1e-9). Weights from
`model/proto/fusion/weights.parquet` (service head, global terms, prior mean, posterior mean and 90%
interval) and the Platt slope from `platt.json`.

Caveats. Levels 1 to 4 differ in which facilities reach them, so the hints and context columns mix
the model's weights with the population at each level. The weights were fitted on about 22 effective
dev labels; their 90% intervals are wide and most include the prior. The ablation intervals are from
39 pairs.

## Not run

- `notebook.py` in Unity Catalog mode on Databricks (only the local-file mode was run). UC mode assumes
  the MODEL_SPEC 3.6 tables were registered from these parquet files and the JSON results uploaded to a
  volume.
- Any new metric on test labels (by rule). Dev-only re-scoring of ablations was not attempted: the
  variant scores were fitted on all dev rows, so a dev AUROC would be in-sample.

## Adversarial verification (viz/model/verify)

Every headline number was recomputed with independent scripts (`verify/v1_ledger.py`,
`verify/v2_llm.py`, `verify/v34_published.py`, `verify/v5_families.py`; own term grouping, no import of
the story scripts). Test-split numbers were only read from the published files and checked by
arithmetic; label values were read only for dev pairs. Corrections made: story 1 (only Likely claim,
Wockhardt rank attribution, distances on the location chart), story 2 (208 not 209 yes at confidence
1, 38 not 40 queries, small-n flags, IPW caveat), story 3 (IPW searched-39 view added, location
denominator, overlapping titles), story 4 (agreement table axes were swapped; IPW was mislabelled as a
label treatment), story 5 (pre-Platt and 90% interval in the title, per-pair share, 3-hue palette).

# Planner against the gold DEV labels

Question: when the planner picks a definitive facility, is it one the gold labels confirm?

Run: `.venv/bin/python planner/eval_gold_dev.py` (after `planner/export_v1.py`). Output:
`planner/out_eval/gold_dev.json` (git-ignored). TEST pairs are never read.

Databricks: `planner/eval_gold_dev_notebook.py` is the same evaluation in notebook format. With
`PLANNER_EVAL_SOURCE=uc` it reads `gold_pairs` (dev rows only), `grades`, `facility_location`,
`pin_gazetteer`, `claims` and `data_point_scores` from `workspace.referral_saathi`. The local path
was run; the Unity Catalog path has not been run on a workspace.

## Model v2, nearest plausible first in emergencies (#92)

Run on model v2 (`planner/export_v2.py`, 61 gold DEV pairs with a pathway: 20 confirmed, 4
contradicted, 37 no information), with implied capabilities on, the same way `plan_for_service`
runs. "Before" is the planner on dev at ce068ae. "Stop 1 nearest" makes stop 1 of an emergency
route the nearest place that can give first care. "Definitive nearest" also picks the nearest
plausible definitive facility that can be reached within the window (else the nearest beyond it),
with p only breaking ties between plans that arrive in the same minute. "Direct when in time" adds:
when going direct reaches a plausible definitive facility within the window and stopping first
would reach definitive care after the window or more than 15 minutes later, the route goes direct
and names stop 1 as first care if needed sooner. Definitive times are total arrival along the
route. Planned pathways (dialysis) are unchanged in every column.

| | Before | Stop 1 nearest | Definitive nearest | Direct when in time | Nearest mention |
|---|---|---|---|---|---|
| Abstained | 6 | 6 | 6 | 6 | 0 |
| Picked a confirmed facility | 10 | 12 | 11 | 11 | 17 |
| Picked a contradicted facility | 0 | 0 | 0 | 0 | 4 |
| Picked a no-information facility | 10 | 11 | 11 | 11 | 25 |
| Picked a facility with no DEV label | 35 | 32 | 33 | 33 | 15 |
| Picks the gold facility when it is confirmed | 9 of 20 | 11 of 20 | 11 of 20 | 11 of 20 | 17 of 20 |
| Picks the gold facility when it is contradicted | 0 of 4 | 0 of 4 | 0 of 4 | 0 of 4 | 4 of 4 |
| Picks the gold facility when there is no information | 10 of 37 | 11 of 37 | 11 of 37 | 11 of 37 | 25 of 37 |

By pathway, definitive nearest and direct when in time (the same counts; gold facility picked when confirmed): burns 1 of 1, dialysis 5 of 7,
trauma 1 of 4, obstetric 1 of 4, newborn 3 of 4. Against before, trauma gains 1 (0 to 1) and newborn
gains 1 (2 to 3). Between the second and third columns trauma picks one confirmed facility fewer
(2 to 1, now a facility with no DEV label); the gold-facility counts do not change. 9 confirmed facilities are still not picked: 8 were never candidates (trauma blood
transfusion 3, obstetric comprehensive_emoc 2, dialysis unit 2, newborn SNCU 1), 1 was outranked.

The query still sits on the gold facility, so this measures whether the planner trusts that
facility's own claim; nearest-first helps exactly when that facility can give first care. The
earlier sections below are the derived/v1 stub era and are kept as the record of those changes.

## Setup

- 63 gold DEV pairs whose service has a pathway (burns 10, dialysis 13, trauma 13, C-section 14,
  NICU 13). Gold verdicts for the service: 20 confirmed, 4 contradicted, 39 no information.
- Each query is placed at the gold facility's own location. The planner runs with the derived/v1
  stub probabilities and estimated travel (no network).
- For a scheduled pathway the "definitive facility" is the one chosen for the recurring sessions.
- Baseline "nearest mention": the nearest facility with a graded mention of the service; at
  distance 0 that is the gold facility itself whenever its record mentions the service.
- A picked facility with no DEV label for the service counts as unknown.

## Result

Three versions of the planner on the same 63 queries. "As merged in #69" is the planner before
issue #70. "Least travel first" changes only how scheduled (dialysis) plans are ranked. "With
implied capabilities" adds planner/implied.py on top; it is what `plan_for_service` now does.

| | As merged in #69 | Least travel first | With implied capabilities | Nearest mention |
|---|---|---|---|---|
| Abstained | 4 | 4 | 2 | 0 |
| Picked a confirmed facility | 6 | 12 | 13 | 17 |
| Picked a contradicted facility | 0 | 0 | 0 | 0 | 4 |
| Picked a no-information facility | 8 | 11 | 11 | 27 |
| Picked a facility with no DEV label | 45 | 36 | 37 | 15 |
| Confirmed, among picks with a clear label | 6 of 6 | 12 of 12 | 13 of 13 (95% CI 0.77 to 1.00) | 17 of 21, 0.81 (0.60 to 0.92) |
| Picks the gold facility when it is confirmed | 5 of 20, 0.25 (0.11 to 0.47) | 11 of 20, 0.55 (0.34 to 0.74) | 12 of 20, 0.60 (0.39 to 0.78) | 17 of 20, 0.85 (0.64 to 0.95) |
| Picks the gold facility when it is contradicted | 0 of 4 | 0 of 4 | 0 of 4 (0.00 to 0.49) | 4 of 4 (0.51 to 1.00) |
| Picks the gold facility when there is no information | 8 of 39 | 11 of 39 | 11 of 39, 0.28 (0.17 to 0.44) | 27 of 39, 0.69 (0.54 to 0.81) |

By pathway, final version (picks the gold facility when confirmed / contradicted): burns 1 of 1 /
0 of 1; dialysis 6 of 7 / none; trauma 1 of 4 / 0 of 1; obstetric 1 of 4 / 0 of 2; newborn 3 of 4 /
none.

## What changed and what each change did

1. Ranking of scheduled plans (the larger effect: 5 to 11 of 20). The planner ranked dialysis plans
   by fewest sites first, so a far hospital with everything beat a near dialysis unit plus a one-off
   trip for fistula surgery. Example, Yavatmal district: one site 150 minutes away (11,400 minutes
   of travel over 12 weeks) was preferred to sessions 109 minutes away with assessment and surgery
   elsewhere (8,216 minutes). Plans are now ranked by travel over the planning weeks, then by
   sites. Dialysis went from 0 of 7 confirmed facilities used to 6 of 7.
2. Implied capabilities (11 to 12 of 20, and 4 abstentions to 2). A strongly evidenced capability
   lends a discounted probability to the ones it implies, shown on the stop as "implied by a
   strongly evidenced ...", with no quote attached. 18 of the 63 best plans use one: laboratory 8,
   nephrology 8, blood transfusion 7, IV fluids 1. It changed the pick in 13 queries.
3. Blood from the blood-centre list. The e-RaktKosh outputs are not in git, so the table above was
   run without them (blood from record text or from the caesarean implication). The lead ran the
   list-based path on the machine that has them (365 matched facilities, 5,230 centres) and
   reported on issue #70: the planner picks the gold facility 13 of 20 times when it is confirmed
   and 0 of 4 times when it is contradicted. That run's full table is not in this file.

## What is still missed

8 confirmed facilities are still not picked. 4 were never candidates: major trauma needs blood
transfusion and 2 trauma facilities have no blood evidence (the list should settle these), 1
dialysis record and 1 obstetric record have no usable evidence for the core service itself. 4 were
candidates and another plan ranked higher.

The planner still sends no patient to a contradicted facility (0 of 4) and the baseline sends all
four. With 4 cases the intervals overlap.

## Limits

- 63 queries; 4 contradicted. Every interval is wide.
- The query sits on the gold facility, which favours the baseline: it picks that facility at
  distance 0 whenever the record mentions the service at all.
- 45 of the planner's 59 picks have no DEV label, so most of its choices are unscored.
- Gold labels judge the service, not the pathway's other capabilities.
- Stub probabilities, estimated travel. Numbers will change with the fitted model.
- The strengths of the implications (0.6 to 0.9) and the "strongly evidenced" cut (0.75) are
  assumptions. They were set once, before this run, and were not tuned on these labels.
- The ranking of scheduled plans (least travel first) was chosen after seeing these DEV results.
  Its gain here is in-sample for that decision. Only the sealed TEST evaluation (issue #66) counts
  as independent evidence for it. The lead reviewed the change and kept it as clinically sound for
  dialysis three times a week.

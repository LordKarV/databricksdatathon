# Planner against the gold DEV labels

Question: when the planner picks a definitive facility, is it one the gold labels confirm?

Run: `.venv/bin/python planner/eval_gold_dev.py` (after `planner/export_v1.py`). Output:
`planner/out_eval/gold_dev.json` (git-ignored). TEST pairs are never read.

## Setup

- 63 gold DEV pairs whose service has a pathway (burns 10, dialysis 13, trauma 13, C-section 14,
  NICU 13). Gold verdicts for the service: 20 confirmed, 4 contradicted, 39 no information.
- Each query is placed at the gold facility's own location. The planner runs with the derived/v1
  stub probabilities and estimated travel (no network).
- Baseline "nearest mention": the nearest facility with a graded mention of the service; at
  distance 0 that is the gold facility itself whenever its record mentions the service.
- A picked facility with no DEV label for the service counts as unknown.

## Result

| | Planner | Nearest mention |
|---|---|---|
| Abstained | 4 of 63 | 0 of 63 |
| Picked a confirmed facility | 6 | 17 |
| Picked a contradicted facility | 0 | 4 |
| Picked a no-information facility | 8 | 27 |
| Picked a facility with no DEV label | 45 | 15 |
| Confirmed, among picks with a clear label | 6 of 6 (95% CI 0.61 to 1.00) | 17 of 21, 0.81 (0.60 to 0.92) |
| Picks the gold facility when it is confirmed | 5 of 20, 0.25 (0.11 to 0.47) | 17 of 20, 0.85 (0.64 to 0.95) |
| Picks the gold facility when it is contradicted | 0 of 4 (0.00 to 0.49) | 4 of 4 (0.51 to 1.00) |
| Picks the gold facility when there is no information | 8 of 39, 0.21 (0.11 to 0.36) | 27 of 39, 0.69 (0.54 to 0.81) |

By pathway (planner, picks the gold facility when confirmed / contradicted): burns 1 of 1 / 0 of 1;
dialysis 0 of 7 / none; trauma 1 of 4 / 0 of 1; obstetric 0 of 4 / 0 of 2; newborn 3 of 4 / none.

## What it says

- The planner never sent a patient to a contradicted facility (0 of 4) and the baseline always did
  (4 of 4). With 4 cases the intervals overlap, so this is a direction, not a result.
- The planner is far too cautious about confirmed facilities: it uses 5 of 20, the baseline 17 of
  20. It routes around three in four facilities whose service the web check confirmed.
- The cause is the pathway's extra requirements, not distrust of the service claim. Of the 15
  confirmed facilities it skipped, 13 were never candidates because one required capability has no
  mention in the record (stub probability 0.02): nephrology 5, blood transfusion 5, comprehensive
  obstetric care 1, vascular access surgery 1, laboratory 1. The other 2 were candidates and
  another plan ranked higher.
- So the gold label and the planner answer different questions. Gold says "this facility does
  dialysis". The pathway asks for nephrology, a laboratory and fistula surgery as well, and a
  dialysis unit that never writes "nephrology" is dropped.

## What to change

1. Treat a confirmed or strongly evidenced core service as evidence for the capabilities it
   implies (a working dialysis unit implies nephrology cover and a laboratory; a caesarean service
   implies an operating theatre and anaesthesia). Today each tag is scored alone.
2. Blood transfusion should come from the blood-centre list, not from record text (5 of the 13).
3. Until then, the planner's choice of a far "fully evidenced" facility over a near confirmed one
   should be shown as a trade-off on the card, not as the single answer.

## Limits

- 63 queries; 4 contradicted. Every interval is wide.
- The query sits on the gold facility, which favours the baseline: it picks that facility at
  distance 0 whenever the record mentions the service at all.
- 45 of the planner's 59 picks have no DEV label, so most of its choices are unscored.
- Gold labels judge the service, not the pathway's other capabilities.
- Stub probabilities, estimated travel. Numbers will change with the fitted model.

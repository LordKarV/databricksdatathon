# gold v3 TEST evaluation

Frozen model v2 against the sealed gold v3 TEST, opened once (`../OPENING_LOG.md`). Agent-labelled, not human-checked.

| File | Written by | What |
| --- | --- | --- |
| `results.json` | `evaluate.py` | the original TEST evaluation (#51). Frozen: byte-identical to dev (#140). |
| `extras.json` | `evaluate.py` | #66 additions: ECE interval, calibration by score bin, location and existence heads, conformal, end-to-end top-1, and `model_card_test`. |
| `top1_benchmark.json` | `top1_benchmark.py` | end-to-end top-1 on the 40 benchmark queries; run first, it needs `app/facts/out`. |

`extras.json` key `model_card_test` is the frozen model's compact result on TEST for the app, How page, notebook and
README. It lives here, not in `derived/v2`, because `derived/v2/model_card.json` is hashed into model_version and
`derived/v2` is frozen.

Run: `.venv-app/bin/python model/gold/v3/test_eval/evaluate.py` (after `top1_benchmark.py`).

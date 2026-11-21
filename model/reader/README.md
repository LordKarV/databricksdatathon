# Evidence reader

A small transformer cross-encoder that reads one claim sentence in the context of a facility and a
service and outputs two probabilities:

- `p_about_this`: the sentence is about THIS facility, not another hospital merged into the record
- `p_offers`: the sentence says the facility offers the service (not a referral, a plan, a negation,
  a staff history or another hospital's service)

Status: the pipeline is built and proven end to end on a small subset. **The full training has not
been run.** No reader scores are in `derived/v2/` yet, and nothing here shows the reader beats the
rules. The numbers below for the reader come from a 20,000-example, 1-epoch test run and are only
evidence that the code works.

## Run it

```
pip install -r model/reader/requirements.txt

# full run (three backbones, all data, scores every claim)
python -m model.reader.run --config model/reader/configs/full.yaml

# small run to prove the pipeline (about 3 minutes on an Apple M5, 16 GB)
python -m model.reader.run --config model/reader/configs/dev.yaml
```

- Unattended and restartable: every step is skipped when its output exists, and training resumes
  from the last checkpoint (`checkpoint_every` steps). Re-run the same command after an interruption.
- Each backbone trains in its own process. If one crashes, it is recorded under
  `failed_backbones` and the run continues.
- Device: MPS, then CUDA, then CPU. `READER_DEVICE=cpu` forces the CPU.
- Outputs: `model/reader/out/metrics_<config>.json` (everything measured), the eval files under
  `model/reader/eval/`, and `derived/v2/reader_scores.parquet`. Weights, training data and
  `out/` are git-ignored.
- `--force` redoes every step; `--skip-score` stops before scoring.

## Files

| File | What |
|---|---|
| `run.py` | The single entry point |
| `configs/full.yaml`, `configs/dev.yaml` | Settings for the full run and the laptop test |
| `build_eval.py` | Collects the hand-labelled sentences in the repo into `eval/eval_set.csv` |
| `make_data.py` | Builds the weak-label training set from `derived/v1/claims.parquet` |
| `train.py` | Fine-tunes one backbone (checkpoints, resume, memory guard) |
| `evaluate.py` | Scores the rules and a reader on the hand labels, with intervals and calibration |
| `score.py` | Scores every claim, writes the parquet and the disagreement samples |
| `common.py` | Rule baseline, model, prediction, token attribution |
| `test_reader.py` | 8 tests, no weights needed: `python -m pytest model/reader/test_reader.py -q` |
| `eval/eval_set.csv`, `eval/eval_set_stats.json`, `eval/results_rules.json` | The eval set and the rule baseline on it |

## Eval set (hand labels already in the repo)

629 rows collected from 12 files in `cleaning/claims`, `audit/merge/handcheck` and
`kb/taxonomy/out`; 564 are usable, from 506 facilities. 65 rows have an original label that does
not settle the target (for example "names another facility" with no judgement of harm) and are kept
with label -1. Every row carries its source file, row and the mapping rule.

| Target | Rows | Label 1 | Label 0 |
|---|---|---|---|
| about_this | 234 | 173 | 61 |
| offers | 330 | 281 | 49 |

Things to know before trusting any comparison on it:

- It was not sampled at random. Most rows were drawn from sentences the rules flagged, and the
  lexicon was then fixed using these same rows, so the rule baseline is in-sample on them. That
  favours the rules.
- Two label conventions were inverted where 'correct' meant "the lexicon was right to reject this
  sentence" (the `clause_veto` set and rows with a non-offer cue). See `build_eval.py`.
- Rows labelled under the old `trauma_emergency` tag are mapped to `emergency_24x7` when the
  sentence matches that pattern, else `trauma_care`, because the old tag covered both.
- `kb/vf_details/handcheck_labels.csv` and the `audit/claims/out/handcheck*.tsv` samples are not
  used: the first labels extracted facts, not sentences, and the second have no row-level labels in
  the repo.
- No new hand labels were added.

## The bar: rule baseline on the hand labels

Reported for the class that matters: label 0 (a sentence about another facility; a sentence that is
not an offer). 95% Wilson intervals.

| Target | Accuracy | Precision on label 0 | Recall on label 0 | F1 |
|---|---|---|---|---|
| about_this | 0.795 | 0.644 (0.50 to 0.77), 29 of 45 | 0.475 (0.36 to 0.60), 29 of 61 | 0.547 |
| offers | 0.964 | 0.974 (0.87 to 1.00), 38 of 39 | 0.776 (0.64 to 0.87), 38 of 49 | 0.864 |

The offers rules are already very accurate here (in-sample, as noted). The room for a reader is on
`about_this`, where the rules find fewer than half of the sentences about another facility.

## Training data (weak labels)

`make_data.py` builds 138,354 examples (123,947 train, 14,407 validation) from 8,917 facilities.
Held out completely: the 88 gold TEST facilities, 1 record in the same duplicate group, and the 561
facilities with any row in the eval set (634 in all). Validation is 10% of the remaining
facilities, chosen by a hash of the id, so no facility is in both splits.

Model input: `"<name>, <city> | <service name>"` as the first segment, the sentence as the second.

| Head | Tag | Rule | Label | Examples |
|---|---|---|---|---|
| about_this | other | attribution is other_facility | 0 | 8,103 |
| about_this | own | attribution is own_anchored | 1 | 20,000 |
| about_this | unanch | attribution is unanchored (sample, weight 0.5) | 1 | 15,000 |
| about_this | swap | an own_anchored sentence shown with another facility's name and city | 0 | 14,996 |
| offers | pos | lexicon match, no non-offer cue, usable sentence kind, not other_facility | 1 | 40,475 |
| offers | related | only the service's 'related' pattern hits | 0 | 21,001 |
| offers | random | a service the sentence does not mention | 0 | 15,000 |
| offers | veto | include pattern hits but exclude or clause veto rejects it | 0 | 2,739 |
| offers | kind | lexicon match in a template, research, directory or staff sentence | 0 | 664 |
| offers | foreign | lexicon match in a sentence attributed to another facility | 0 | 242 |
| offers | cue | lexicon match with a negation, referral, future, past or camp cue | 0 | 134 |

The weakness is visible in the last four rows: hard negatives for `offers` are rare (3,779 in all,
134 with a non-offer cue), so the offers head mostly learns "does the sentence mention the service".
The `swap` examples are synthetic. The lead's LLM-distilled support labels are not included.

Loss: binary cross-entropy per head with label smoothing 0.05, masked where a head has no label.
The epoch with the lowest validation loss is kept; one temperature per head is fitted on the
validation split. The hand labels are never used for training, selection or calibration.

## Backbones

`full.yaml` trains three and keeps the one with the lowest validation loss (weak labels). The hand
labels are reported for all three and are not used to choose.

| Name | Backbone | Parameters | Why | Speed on Apple M5, 16 GB (batch 128, length 192) |
|---|---|---|---|---|
| minilm-l12 | microsoft/MiniLM-L12-H384-uncased | 33M | general-purpose small English encoder | 193 examples/s |
| bge-small | BAAI/bge-small-en-v1.5 | 33M | same size, trained for sentence matching | 218 examples/s |
| me5-small | intfloat/multilingual-e5-small | 118M | multilingual, for Hindi and transliterated names | 174 examples/s |

Speeds are from 30 to 50 training steps each, so they are rough.
`microsoft/deberta-v3-small` is left out: on MPS with torch 2.15.0 it aborts the process with a
Metal assertion in matrix multiplication. It is commented in the config for a CPU run.

Memory guard: a batch is sent to the device in chunks of at most `max_cells` = rows x padded
length squared, and the gradients are added up, so the batch size is unchanged. Without it a batch
of 128 long sentences made a 16 GB Mac swap until the run stalled (no error was raised). Batches
are also grouped by length to cut padding.

## What has been checked on this machine (Apple M5, 16 GB, MPS)

- `dev.yaml` end to end, twice (once with `--force`): eval set, training data, training, rule and
  reader evaluation, backbone choice, scoring of a 5,000-claim sample with token attribution,
  metrics file. 152 seconds without other load (98 s of it training).
- Resume: a run killed with SIGKILL just after its first checkpoint (step 30 of 250) restarted from
  step 30 and finished. A finished run is skipped on the next start.
- Each of the three backbones trains for 30 to 50 steps at the full-run settings.
- Scoring speed on the sample: 5,508 rows predicted in 7 s; token attribution for 1,003 rows in 6 s.

The 20,000-example, 1-epoch test model scores below the rules on the hand labels (F1 on label 0:
about_this 0.50 against 0.55; offers 0.22 against 0.86). It is undertrained and says nothing about
the full run.

## Expected wall time for the full run

Not measured. From the speeds above: 123,947 examples x 3 epochs at about 200 examples/s is about
31 minutes per backbone on an M5 with 16 GB. Scoring about 530,000 rows plus token attribution is
about 20 minutes at the sample's speed. That gives roughly 2 hours for three backbones on this
machine, and less on a faster one; how much less is a guess.

## Output

`derived/v2/reader_scores.parquet`: `claim_id, service_id, p_about_this, p_offers,
top_tokens_about, top_tokens_offers, model_version`.

- One row per (claim, service) where the service's lexicon `include` pattern hits the sentence,
  including sentences the rules then reject.
- One row per claim with `service_id` = "" carrying `p_about_this` only.
- `top_tokens_*`: up to 3 words of the sentence, joined by "|", that most support the predicted
  class. Method: gradient x input on the embeddings (a one-step approximation of integrated
  gradients), summed over word pieces. Computed for service rows and for claim rows with
  `p_about_this` below 0.5. They can be empty when no sentence word supports the prediction.
- `model/reader/eval/disagreements_<run>.csv`: 20 sentences each way where reader and rules
  disagree, per head, for hand checking.

## Decision rule for shipping

The reader's scores should feed the model only if, on the hand labels, the F1 on label 0 is higher
than the rules' and the paired bootstrap interval of the difference excludes zero. `run.py` prints
that line for both heads. If it is not met, say so and keep the rules. Given how the eval set was
built, a win on `offers` is unlikely; `about_this` is the head to watch.

## Not done

- The full training, and therefore every claim about the reader's quality.
- Hand-checking the 80 disagreement sentences (needs the full model).
- No new hand labels; no random-sample eval set, so the comparison is biased toward the rules.
- No run on CPU only, no run on the lead's machine.
- LLM-distilled support labels are not used.

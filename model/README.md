# model/: index

| Path | What it is |
| --- | --- |
| [`v2/`](v2/) | The shipped model: `assemble/` builds the witnesses, `fit_*/` the candidates, `final/` selects ([`SELECT.md`](v2/final/SELECT.md)), freezes and exports to [`derived/v2/`](../derived/v2/README.md); `test_predictions.parquet` is the frozen TEST prediction file |
| [`gold/v3/`](gold/v3/README.md) | DEV and sealed TEST web labels; [`test_eval/`](gold/v3/test_eval/) scores the frozen model once (`results.json`, `independence.json`); `human_check/` is the human spot-check sheet |
| [`reader/`](reader/README.md) | The transformer sentence reader: trained, beaten by the rules, weight 0 in v2 |
| [`MODEL_SPEC.md`](MODEL_SPEC.md) | v1 history: the prototype spec and its review, superseded by v2 |
| `proto/`, `review/`, `design/` | v1 prototypes, the statistical and explainability reviews of them, and the design proposals |
| `gold/` (top level) | v1 and v2 gold labels and the 40 benchmark queries (`queries.json`) |

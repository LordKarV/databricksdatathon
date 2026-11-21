# Referral Saathi

A health worker in rural India types a service (dialysis, emergency caesarean, accident care) and gets whom to call
first, two backups and the one question to ask on the phone, each with the facility's own words as evidence and
how sure we are, in plain language. It reads a messy public facility list honestly. It says "call to confirm"
instead of guessing, and it keeps working offline on a cheap phone.

![Results screen on a phone](app/checks/screens/results_dialysis-light.png)

The submission is three things:

- **Video demo:** the app on a phone, start to finish. Link to come (#12).
- **This repository**, with the code for every step from audit to app.
- **The notebook**, with all our code and its outputs:
  [`submission/referral_saathi.ipynb`](submission/referral_saathi.ipynb). It is readable on GitHub as is, and runs
  on Databricks Free Edition ([`submission/README.md`](submission/README.md)).

The app itself runs on Databricks Apps in the team workspace, as shown in the video. Its "How this works" page
tells the same story as the notebook, in plain words.

## How it works

```
provided facility table (Databricks Marketplace, 9,959 usable records)
  -> audit/        what is wrong: merged records, misplaced map points, copied sentences, shared phones
  -> cleaning/     fix what can be fixed, flag the rest; split every listing into sentences with ids
  -> derived/v1/   cleaned tables + a score with an interval for every data point (pipelines/source_scoring)
  -> kb/           taxonomy of services, care pathways, website crawl and open-data witnesses
  -> model/        evidence grades, source reliability, scores for "exists", "is here", "offers it"
  -> app/          FastAPI + one plain HTML page: whom to call, WHY (quotes) and HOW (points), offline packs
     planner/      multi-stop routes for time-critical cases (stabilise first, then definitive care)
     geo/          travel-time estimates, with hill-road factors by state
```

At request time the app needs only the Python standard library plus FastAPI. Its data exports are built from
`derived/v1` in a few seconds.

## Reproduce

**On Databricks Free Edition:**
1. Install the Marketplace listing.
2. Add this repository as a Git folder.
3. Open `submission/referral_saathi.ipynb`, attach serverless compute, and Run all.
   - If your catalog has a different name, set `CATALOG` in its first code cell.
   - Details are in `submission/README.md`.

**Locally** (Python 3.11+, a venv with pandas, pyarrow, fastapi, uvicorn and pytest):

```
make app-data     # planner export, facts, offline packs, "How this works" data (from derived/v1)
make test         # app, planner and travel tests
make serve        # http://127.0.0.1:8000
make notebook     # re-run the submission notebook and save it with outputs
make help         # everything else: a11y check, data audit, public copy, deploy (lead only)
```

`make derived` rebuilds `derived/v1` itself. It needs the raw dataset under `data/raw/` (not in git) and the
upstream cleaning steps; see `derived/v1/README.md`.

## Map of the repository

| Folder | What is in it |
| --- | --- |
| `app/` | The Databricks App: API, page, service worker, offline packs, faithfulness and accessibility tests |
| `planner/`, `geo/` | Multi-stop referral planner; travel-time estimates |
| `audit/` | The data audit: each finding with its hand check (`REPORT.md` summarises it) |
| `cleaning/` | Location and identity cleaning; sentence attribution and service grades |
| `pipelines/` | Builds `derived/v1` (source reliability and data-point scores) |
| `derived/v1/` | The cleaned tables every other part reads |
| `kb/` | Service taxonomy, care pathways, website crawl, open-data matches |
| `external/` | Fetch and join code for 14 public lists, with licence notes |
| `model/` | Model spec, prototypes, gold labels, the statistical review |
| `app_design/`, `design/`, `research/` | Product spec, feasibility probes, concept notes, dataset research |
| `submission/` | The notebook and its builder |
| `demo/` | Storyboard, narration script and the Playwright capture for the video |
| `tools/` | Deploy script, data audit, public-copy script |

## Results, honestly

- **The data problem** (`REPORT.md`, hand-checked):
  - about 14% of records carry a sentence about another facility;
  - 1,367 of 9,869 map points are more than 50 km from their own PIN code.
- **What the app can confirm today:** 45 of the 8,012 facility-service pairs it serves are confirmed by a second
  source and shown as "Likely". Every other option says "Not verified: call to confirm", and when nothing is
  confirmed the app says so.
- **Ranking quality** on 71 held-out pairs (`model/MODEL_SPEC.md` section 4.2): the prototype scored AUROC 0.776
  [0.680, 0.862], against 0.585 for an LLM judge (llama-3.3-70b) and 0.560 for "any mention". An unfitted expert
  prior did as well (0.789). We report this rather than claim the fitted model beats it.
- **What did not work** is listed in `model/MODEL_SPEC.md` section 4.11 and on the app's "How this works" page.
- **Faithfulness:** every number and quote the app shows is checked against its stored row by
  `app/tests/test_faithfulness.py` before release.

The fitted model (#11) will replace the interim scores. This section and the notebook's section 6 will be updated
then.

## Limits

- Rural coverage is thin: 260 of 9,959 records are in Bihar.
- Labels come from public web pages, not from phone calls or visits.
- The data says nothing about whether a bed or a slot is free today, which is why every answer ends with a call.
- Travel times are rough estimates, shown as ranges.

## Data sources and licences

- **Facility records:** the Virtue Foundation dataset from the Databricks Marketplace, used under its consumer
  terms.
- **PIN code boundaries and the NFHS district tables:** Government Open Data Licence (GODL) and ODC-BY.
  LGD and NHSRC lists: reproduced with credit, as their policies allow.
- **NABH, NMC and the MoHFW trauma list:** used only as per-facility facts with a citation. The lists themselves
  are not in this repository.
- **OpenStreetMap:** (c) OpenStreetMap contributors, ODbL. WorldPop and MAP travel time: CC BY.
- **e-RaktKosh blood centres:** no licence stated; shown only as single-centre facts with a link.
- The full table, with each source's terms and hand-check results, is in `research/DATASETS.md`.
- What this repository holds, file by file, is in `DATA_AUDIT.md`.

Not clinical advice. In an emergency call 108.

# Submission notebook

`referral_saathi.ipynb` is the code and the reasoning behind Bharosa, in plain words first. It is
committed with its outputs, so it can be read on GitHub without running it. It runs end to end on Databricks
Free Edition, and also locally.

## Run it on Databricks Free Edition

1. Install the provided dataset from the Marketplace. The notebook expects the catalog
   `databricks_virtue_foundation_dataset_dais_2026` and the table `virtue_foundation_dataset.facilities`. If
   you installed it under another name, change `CATALOG` in the first code cell.
2. Add this repository as a Git folder (Workspace > Create > Git folder), then open
   `submission/referral_saathi.ipynb`.
3. Attach serverless compute and Run all. pandas, pyarrow and matplotlib are already there; nothing else is
   installed.
   - The first run builds the app's small data exports from `derived/v1` and `derived/v2`, which takes about 10
     seconds.
   - The rest runs in under a minute.

To rebuild the team dataset itself on Databricks, run `submission/00_rebuild_derived.ipynb` first (serverless,
about 15 minutes). It exports the Marketplace tables with Spark, runs the cleaning, claims and source-scoring
pipeline in `run_all.sh` order, writes `derived/v1` to `/Volumes/workspace/referral_saathi/uploads/rebuild/`
(a widget) and checks every table against `derived/v1/MANIFEST.json`. On Free Edition serverless it gave 20 of
20 tables passing (17 equal to the manifest, 3 CSV copies by rows). The page check that fetches live websites is
not run; its stored result is reused.

### Release runs (2026-11-22, ran on Databricks serverless)

All three notebooks ran end to end on Databricks Free Edition serverless on 2026-11-22, as one-off notebook runs
(`databricks jobs submit`) from a workspace copy of the tracked files on the release branch:

| notebook | run id | result |
| --- | --- | --- |
| `referral_saathi.ipynb` | 796897435272535 | SUCCESS, 67 cells, 0 error cells |
| `02_simulation.ipynb` | 418325743233710 | SUCCESS, 12 cells, 0 error cells |
| `00_rebuild_derived.ipynb` | 245706239328385 | SUCCESS, 31 pipeline steps ok, 20 of 20 tables pass against `derived/v1/MANIFEST.json` |

The committed notebooks are the local runs (`build_notebook.py`, `build_sim_notebook.py`), not the Databricks
exports: a job run exports as an HTML view, not as `.ipynb`, and the rebuild notebook's output prints a workspace
path that holds a user name.

Steps that cannot run inside Free Edition were run offline: the website crawl, web labelling and external
downloads. The notebook loads their committed summaries (`kb/`, `derived/v1/`) and says so where it does.

## Run it locally

```
.venv-app/bin/python submission/build_notebook.py
```

This writes the notebook from `build_notebook.py` (where the cells live as plain text, for review), runs it
with the local kernel against `derived/v1`, and saves it with outputs. It fails if any cell errors, if any
code cell has no output, or if the file is 20 MB or more. The notebook tooling (nbformat, nbclient, ipykernel,
matplotlib) is for development only and is not in `app/requirements.txt`. To register the kernel once:
`.venv-app/bin/python -m ipykernel install --user --name rs-app`.

## Simulation appendix (SIMULATED)

`02_simulation.ipynb` is the appendix for the simulated referral world in `sim/` (#92). Everything in it is
SIMULATED, not field results. Simulated patients in Bihar and Uttar Pradesh who need trauma care (60-minute window)
or dialysis (120-minute window) are sent through five referral policies: the app, the app offline, nearest,
nearest + call first, and best on paper. Each policy is run under five hidden-truth scenarios: S0-high and S0-low
(read together), S1, S2 and S3. The notebook shows:
- the share treated within the window, with seed-bootstrap intervals;
- how much the result depends on the assumed rates: the phone reaches the facility, a "yes" is wrong, the
  facility is open, it accepts the patient;
- the emergency ranking fix (#101), before and after.

It is built and run by `build_sim_notebook.py`, in about 3 minutes locally at 20 seeds x 200 cases.
`referral_saathi.ipynb` section 7b reads the run's aggregate table from `sim_results.csv`, which is committed, so
it needs no simulation output. The CSV header gives the seeds, cases and commit.

## Still to fill

- **Section 10** reads the voice latency measured on the deployed app from `measured_on_databricks.json` (the lead's
  smoke test, posted on #2), since no other file in the repository records it.

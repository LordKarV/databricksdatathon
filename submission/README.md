# Submission notebook

`referral_saathi.ipynb` is the code and the reasoning behind Referral Saathi, in plain words first. It is
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
   - The first run builds the app's small data exports from `derived/v1`, which takes about 10 seconds.
   - The rest runs in under a minute.

To rebuild the team dataset itself on Databricks, run `submission/00_rebuild_derived.ipynb` first (serverless,
about 15 minutes). It exports the Marketplace tables with Spark, runs the cleaning, claims and source-scoring
pipeline in `run_all.sh` order, writes `derived/v1` to `/Volumes/workspace/referral_saathi/uploads/rebuild/`
(a widget) and checks every table against `derived/v1/MANIFEST.json`. On Free Edition serverless it gave 20 of
20 tables passing (17 equal to the manifest, 3 CSV copies by rows). The page check that fetches live websites is
not run; its stored result is reused.

## What a rebuild reproduces, and what it does not

1. **derived/v1, fully.** `00_rebuild_derived.ipynb` rebuilds every table from the Marketplace table on Free
   Edition (20 of 20 pass against `derived/v1/MANIFEST.json`). With the `data_root` widget set to its output,
   `referral_saathi.ipynb` reads the rebuild, and its section 0.1 checks that the app built from it is identical
   to the one built from the repository.
2. **The v2 scoring method, as code.** The v2 pipeline is in the repository: `model/v2/assemble`, the A prior
   parameters (`model/v2/final/out/A/params_A.json`), the Platt step (a and c in `derived/v2/model_card.json`)
   and `model/v2/final/export.py`. It can be read, but not rerun from the public copy: its inputs include the
   website crawl and web evidence, restricted official lists and other facility-level files that cannot be
   published. Dropping them would give a different model, not the frozen one.
3. **The frozen v2 scores** are the export identified by `model_version` and the `test_predictions` sha256 in
   `derived/v2/model_card.json`. Judges with access to the team workspace can read them in Unity Catalog as
   `workspace.referral_saathi.facility_service_scores_v2`.
4. **Without the v2 export, the app falls back to the interim v1 bands and says so.** The app build prints
   `scores: interim v1 (v2 export not present)`, and the app's "How this works" page shows the same line.

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

## Still to fill

- **Section 6** (the fitted model and its final evaluation): the lead fills it after #11. Until then it shows
  the current measured evaluation from `model/MODEL_SPEC.md`.
- **Section 8** (data stories): lists the stories once `viz/` lands (#53).

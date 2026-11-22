# One-command entry points (issue #58). Run `make help`. PY is the Python with pandas, pyarrow, fastapi and pytest.
PY ?= .venv-app/bin/python

.PHONY: help derived app-data test a11y notebook serve audit public-copy deploy

help:  ## list targets
	@grep -E '^[a-z0-9-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t 14

derived:  ## rebuild derived/v1 from data/raw (needs the raw dataset and the upstream cleaning outputs; see derived/v1/README.md)
	zsh cleaning/geo_identity/run_all.sh
	zsh cleaning/claims/run_all.sh
	zsh pipelines/source_scoring/run_all.sh

app-data:  ## build the app's run-time exports from derived/v1, in deploy order
	$(PY) planner/export_v1.py
	$(PY) app/facts/build.py
	$(PY) app/packs/build_packs.py
	$(PY) app/howto/build.py
	$(PY) app/stories/build.py

test:  ## run the app, planner and travel test suites
	cd app && ../$(PY) -m pytest tests -q
	$(PY) -m pytest planner geo -q

a11y:  ## axe check, phone screenshots and page weight for every app state (about 10 minutes)
	$(PY) app/checks/a11y_check.py

notebook:  ## write and execute submission/referral_saathi.ipynb with outputs
	$(PY) submission/build_notebook.py

serve:  ## run the app locally on http://127.0.0.1:8000
	cd app && ../$(PY) -m uvicorn app:app --port 8000

audit:  ## regenerate DATA_AUDIT.md and tools/public_exclude.txt
	$(PY) tools/data_audit.py

public-copy:  ## option B: build the code-only copy in build/public (local only, never pushed)
	PY=$(PY) bash tools/public_copy.sh

deploy:  ## build and deploy the Databricks App (lead only: needs the workspace profile)
	bash tools/deploy/deploy.sh

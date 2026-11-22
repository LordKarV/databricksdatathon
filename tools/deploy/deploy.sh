#!/usr/bin/env bash
# Build the Referral Saathi bundle and deploy it as a Databricks App.
# Usage: bash tools/deploy/deploy.sh            (build + upload + deploy)
#        SKIP_BUILD=1 bash tools/deploy/deploy.sh (reuse existing build outputs)
# Databricks Apps copies only the source folder, so the bundle mirrors the repo layout
# (app/ imports geo/ via the repo root) with a root app.yaml that starts app/main.py.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_NAME="${APP_NAME:-referral-saathi}"
export DATABRICKS_CONFIG_PROFILE="${DATABRICKS_CONFIG_PROFILE:-vf}"
BUNDLE="$ROOT/build/deploy_bundle"
UV_DEPS=(--with duckdb --with pandas --with pyarrow)

cd "$ROOT"
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "== build data files from derived/"
  # Planner first: app/facts/build.py copies the claims the planner cites, so route stops show quotes (#47).
  uv run --no-project "${UV_DEPS[@]}" python planner/export_v2.py
  # phonenumbers formats the shown phone numbers (national format) at build time only; it is not an app dependency
  # and stays out of app/requirements.txt. Without it build.py warns and shows each listing's own spelling.
  uv run --no-project "${UV_DEPS[@]}" --with phonenumbers python app/facts/build.py
  uv run --no-project "${UV_DEPS[@]}" python app/packs/build_packs.py
  # 'How this works' page data (#45): reads REPORT.md, model/MODEL_SPEC.md, research/DATASETS.md and the facts
  # export at build time, writes app/howto/out/how.json (the docs themselves are not bundled).
  uv run --no-project "${UV_DEPS[@]}" python app/howto/build.py
  # 'Data stories' page data (#53): copies text from viz/gallery.json and the chart SVGs it names into
  # app/stories/out/ (standard library only; order does not matter).
  uv run --no-project "${UV_DEPS[@]}" python app/stories/build.py
  # Website check (#37, #85 H1): official URLs and service patterns for /api/verify.
  uv run --no-project "${UV_DEPS[@]}" python app/verify/build_sites.py
fi

echo "== check every feature's data file exists"
for f in planner/out/planner_v2.json.gz app/facts/out/facts.json.gz app/packs/out/index.json \
         app/howto/out/how.json app/stories/out/stories.json app/verify/out/sites.json.gz; do
  [ -s "$f" ] || { echo "missing build output: $f (a feature would be off in the deployed app)" >&2; exit 1; }
done

echo "== assemble bundle"
rm -rf "$BUNDLE" && mkdir -p "$BUNDLE/kb"
rsync -a --exclude '__pycache__' --exclude 'tests' --exclude 'checks' app common geo planner "$BUNDLE/"
rsync -a kb/pathways "$BUNDLE/kb/"
cp app/requirements.txt "$BUNDLE/requirements.txt"
cat > "$BUNDLE/app.yaml" <<'YAML'
command: ["python", "app/main.py"]
env:
  - name: DATABRICKS_WAREHOUSE_ID
    valueFrom: sql-warehouse
  - name: SERVING_ENDPOINT_TEXT
    valueFrom: serving-endpoint-text
  - name: SERVING_ENDPOINT_VISION
    valueFrom: serving-endpoint-vision
  - name: REPORTER_KEY
    valueFrom: reporter-key
YAML
du -sh "$BUNDLE"

USER_NAME=$(databricks current-user me -o json | python3 -c 'import sys, json; print(json.load(sys.stdin)["userName"])')
SRC="/Workspace/Users/$USER_NAME/$APP_NAME-src"

echo "== upload to $SRC"
databricks workspace mkdirs "$SRC"
databricks workspace import-dir "$BUNDLE" "$SRC" --overwrite >/dev/null

echo "== ensure app exists"
if ! databricks apps get "$APP_NAME" >/dev/null 2>&1; then
  databricks apps create "$APP_NAME" --description "Referral Saathi: evidence-backed facility referrals" >/dev/null
fi

echo "== deploy"
databricks apps deploy "$APP_NAME" --source-code-path "$SRC" -o json \
  | python3 -c 'import sys, json; d = json.load(sys.stdin); s = d.get("status", {}); print(s.get("state"), "|", s.get("message", ""))'
databricks apps get "$APP_NAME" -o json | python3 -c 'import sys, json; d = json.load(sys.stdin); print("url:", d.get("url"))'

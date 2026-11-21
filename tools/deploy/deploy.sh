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
  uv run --no-project "${UV_DEPS[@]}" python app/facts/build.py
  uv run --no-project "${UV_DEPS[@]}" python app/packs/build_packs.py
  uv run --no-project "${UV_DEPS[@]}" python planner/export_v1.py
  # 'How this works' page data (#45): reads REPORT.md, model/MODEL_SPEC.md, research/DATASETS.md and the facts
  # export at build time, writes app/howto/out/how.json (the docs themselves are not bundled).
  uv run --no-project "${UV_DEPS[@]}" python app/howto/build.py
fi

echo "== assemble bundle"
rm -rf "$BUNDLE" && mkdir -p "$BUNDLE/kb"
rsync -a --exclude '__pycache__' --exclude 'tests' --exclude 'checks' app geo planner "$BUNDLE/"
rsync -a kb/pathways "$BUNDLE/kb/"
cp app/requirements.txt "$BUNDLE/requirements.txt"
cat > "$BUNDLE/app.yaml" <<'YAML'
command: ["python", "app/main.py"]
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

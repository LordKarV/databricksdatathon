#!/usr/bin/env bash
# SUPERSEDED: the lead made this repo public (#2), so no separate copy is published. The rule on #82 is now checked
# on the repo itself: `.venv-app/bin/python tools/data_audit.py --repo origin/dev`. Kept for reference only.
#
# Option B of DATA_AUDIT.md: build a clean code-only copy of this repo in build/public/ (git-ignored).
# Local only: it never adds a remote, pushes or changes this repo's visibility. A human reviews the copy and decides.
# The copy is one fresh commit with no history, because this repo's history still holds the excluded files.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/public"
cd "$ROOT"
"${PY:-.venv-app/bin/python}" tools/data_audit.py   # refresh the exclude list first
rm -rf "$OUT" && mkdir -p "$OUT"
git ls-files | grep -vxF -f <(grep -v '^#' tools/public_exclude.txt) > "$OUT.files"
rsync -a --files-from="$OUT.files" "$ROOT/" "$OUT/"
rm "$OUT.files"
# The rule on #82: no facility-level row, quote, name, phone or restricted-list fact. Fail before committing anything.
"${PY:-.venv-app/bin/python}" tools/data_audit.py --check "$OUT" || { echo "public copy FAILED the facility check"; exit 1; }
cd "$OUT"
git init -q && git add -A && git -c user.name="public copy" -c user.email="public-copy@localhost" \
  commit -q -m "Referral Saathi: code-only public copy (data regenerated from the Marketplace on Databricks)"
echo "built $OUT: $(git ls-files | wc -l | tr -d ' ') files, $(du -sh . | cut -f1); no remote set"

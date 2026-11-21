#!/usr/bin/env bash
# Run one SQL statement on the workspace SQL warehouse and print rows as TSV.
# Usage: ./sql.sh "SELECT 1"
set -euo pipefail
export DATABRICKS_CONFIG_PROFILE="${DATABRICKS_CONFIG_PROFILE:-vf}"
WAREHOUSE_ID="${WAREHOUSE_ID:-6a2f5637720a2c17}"
[ $# -eq 1 ] || { echo "usage: $0 \"<sql>\"" >&2; exit 2; }

body=$(python3 -c 'import json,sys; print(json.dumps({"warehouse_id": sys.argv[1], "statement": sys.argv[2], "wait_timeout": "50s", "disposition": "INLINE", "format": "JSON_ARRAY"}))' "$WAREHOUSE_ID" "$1")

databricks api post /api/2.0/sql/statements --json "$body" | python3 -c '
import json, sys
r = json.load(sys.stdin)
state = r["status"]["state"]
if state != "SUCCEEDED":
    err = r["status"].get("error", {}).get("message", "still running, retry")
    sys.exit(state + ": " + err)
print("\t".join(c["name"] for c in r["manifest"]["schema"]["columns"]))
for row in r.get("result", {}).get("data_array", []):
    print("\t".join("" if v is None else str(v) for v in row))
'

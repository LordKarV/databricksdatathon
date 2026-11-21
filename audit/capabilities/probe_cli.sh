#!/usr/bin/env bash
# Read-only CLI probes of the Free Edition workspace. Saves raw output per command.
export DATABRICKS_CONFIG_PROFILE=vf
cd "$(dirname "$0")"; mkdir -p out
while IFS= read -r c; do
  f=out/$(echo "$c" | tr ' /@.' '____' | cut -c1-50)
  databricks $c -o json > "$f.json" 2> "$f.err"; echo "$? | $c"
done <<'L'
serving-endpoints list
apps list
vector-search-endpoints list-endpoints
genie list-spaces
warehouses get 6a2f5637720a2c17
warehouses list
lakeview list
database list-database-instances
clusters list
catalogs list
current-user me
supervisor-agents list-supervisor-agents
L
# second batch
databricks postgres list-projects -o json > out/postgres_list-projects.json 2> out/postgres_list-projects.err; echo "$? | postgres list-projects"
databricks api get /api/2.0/serving-endpoints/databricks-gpt-oss-120b > out/ep_gpt_oss_120b.json 2>&1; echo "$? | get endpoint gpt-oss-120b"
databricks api get /api/2.1/unity-catalog/metastore_summary > out/metastore_summary.json

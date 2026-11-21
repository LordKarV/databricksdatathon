# Workspace capabilities (Free Edition, profile vf)

Probed 2026-11-21, read-only. Nothing was created in the workspace.

Re-run: `./probe_cli.sh` (CLI list/get, raw JSON in `out/`), then
`../../sql.sh "$(cat aiq1.sql)"` and `../../sql.sh "$(cat aiq2.sql)"` (results in `out/aiq1.tsv`, `out/aiq2.tsv`).
Warehouse queries used by this step: 2.

## Workspace facts (seen)

- Host dbc-ea4e0abe-8cd4.cloud.databricks.com, AWS, metastore region us-east-2 (`out/metastore_summary.json`).
- Current user is in groups `users` and `admins`.
- Catalogs: system, samples, workspace, databricks_virtue_foundation_dataset_dais_2026. So `workspace` is the writable catalog for our own tables later.
- One warehouse: 6a2f5637720a2c17, "Serverless Starter Warehouse", PRO, serverless, 2X-Small, max 1 cluster, auto-stop 10 min, Photon on, state RUNNING at probe time.
- No classic clusters (`clusters list` = []).
- Existing objects: 0 apps, 0 vector search endpoints, 0 AI/BI dashboards, 0 Lakebase provisioned instances, 0 Lakebase autoscaling projects, 0 supervisor agents, 1 Genie space ("Bakehouse Sales Starter Space", a built-in sample).

## Model serving (seen)

11 serving endpoints, all READY (`out/serving-endpoints_list.json`):

- Chat: databricks-gpt-oss-120b, databricks-gpt-oss-20b, databricks-qwen3-next-80b-a3b-instruct, databricks-qwen35-122b-a10b, databricks-gemma-3-12b, databricks-meta-llama-3-1-8b-instruct, databricks-meta-llama-3-3-70b-instruct, databricks-llama-4-maverick.
- Embeddings: databricks-gte-large-en, databricks-bge-large-en, databricks-qwen3-embedding-0-6b.
- No Claude, GPT-5 or Gemini endpoints are listed.

## ai_query tests (seen)

Test 1 (`aiq1.sql`): one statement, six chat models asked to "Reply with exactly: OK". All six returned `OK`: llama-3-3-70b, gpt-oss-120b, qwen3-next-80b, llama-4-maverick, gemma-3-12b, qwen35-122b. `ai_query('databricks-gte-large-en', ...)` returned a 1024-dim vector. Wall time about 12 s.

Test 2 (`aiq2.sql`): llama-3-3-70b with `responseFormat` json_schema (strict) over 2 facility rows whose procedure mentions dialysis. Both returned valid JSON matching the schema in about 4 s. Important finding: both rows were the known contaminated records (Aravind Eye Hospital "Hyderabad", Wockhardt Hospital Nagpur), and the model answered `offers_dialysis: yes, confidence: 1` with a verbatim quote for each. The LLM extracts the claim faithfully but does not notice that the quoted sentence belongs to a different facility or city. Contamination checks must be deterministic (PIN vs city vs coordinates vs names mentioned in the text), not delegated to the LLM's self-reported confidence.

## Capability table

| Capability | Status | Detail |
| --- | --- | --- |
| SQL warehouse | verified_available | 2X-Small serverless PRO, 1 cluster. Statement API works. |
| ai_query (chat) | verified_available | 6 of 8 chat endpoints tested, all respond. |
| ai_query structured output | verified_available | responseFormat json_schema strict works on llama-3-3-70b. |
| Embeddings via ai_query | verified_available | gte-large-en returns 1024 dims. bge and qwen3-embedding listed READY, not called. |
| Foundation model endpoints | verified_available | 11 READY pay-per-token endpoints listed. |
| Databricks Apps | docs_only | API reachable (empty list). Free Edition: up to 3 apps, auto-stop 24 h after start/deploy, restartable. Runtime Ubuntu 22.04, Python 3.11, Node 22, 2 vCPU / 6 GB default. Pre-installed: streamlit 1.38, dash 2.18, gradio 4.44, shiny 1.1, flask 3.0, fastapi 0.115, plotly, databricks-sql-connector, databricks-sdk. Node apps declare deps in package.json. |
| App reads UC via warehouse | docs_only | Add `sql_warehouse` resource (CAN_USE) and `uc_securable` TABLE (SELECT); app.yaml `valueFrom: sql-warehouse`; query with databricks-sql-connector or SDK. |
| App calls model endpoints | docs_only | `serving_endpoint` resource with CAN_QUERY; call with SDK `serving_endpoints.query`, OpenAI client, or ai_query through the warehouse. |
| App calls Genie | docs_only | `genie_space` resource (CAN_RUN); Genie Agents API (Conversation / start-conversation). |
| App with Vector Search / Lakebase | docs_only | Resource types exist for both. |
| Genie spaces | verified_available | `genie list-spaces` returns the sample space. Creating our own space and starting a conversation not tried (would write state). |
| AI/BI dashboards | docs_only | lakeview API reachable, 0 dashboards. Publish with embed_credentials so viewers use publisher's access. |
| Vector Search (AI Search) | docs_only | 0 endpoints. Free Edition: one endpoint, one search unit, Direct Vector Access not supported, so Delta Sync index only. |
| Lakebase Postgres | docs_only | 0 instances, 0 projects. Free Edition: one project per account, scale-to-zero. |
| Agent Bricks | docs_only | supervisor-agents API reachable (empty). Knowledge Assistant / Supervisor Agent are legacy since 2026-10-12; recommended path is Agent Bricks CLI (deploys to Apps) or Genie Agents. us-east-2 is a supported region for Knowledge Assistant. Free Edition availability of each brick not verified. |
| Public / anonymous app access | verified_unavailable (docs) | Docs: apps cannot be public, no anonymous access. Viewers must be authenticated Databricks users granted CAN_USE. Judges would need to be added as workspace users. |
| Classic clusters / GPU serving | verified_unavailable | No clusters; Free Edition docs: serverless only, no GPU, no provisioned throughput. |

## Implications for the build

- An App (Streamlit or Dash, both pre-installed) on the one warehouse is the most flexible front end, and can call ai_query, embeddings and optionally Genie from the same code.
- Judges cannot open the app anonymously. Plan for: add judges as workspace users, plus a recorded demo and a published dashboard or notebook as fallback. Apps also stop after 24 h, so restart before judging.
- LLM output needs deterministic guards; ai_query self-confidence was 1.0 on contaminated records.
- Batch ai_query over 10k rows uses the shared daily quota; precompute once into a `workspace` table rather than per request.

## Sources

- https://docs.databricks.com/aws/en/getting-started/free-edition-limitations
- https://docs.databricks.com/aws/en/dev-tools/databricks-apps/system-env
- https://docs.databricks.com/aws/en/dev-tools/databricks-apps/dependencies
- https://docs.databricks.com/aws/en/dev-tools/databricks-apps/resources
- https://docs.databricks.com/aws/en/dev-tools/databricks-apps/permissions
- https://docs.databricks.com/aws/en/dev-tools/databricks-apps/key-concepts
- https://docs.databricks.com/aws/en/genie-agents/conversation-api
- https://docs.databricks.com/aws/en/dashboards/tutorials/dashboard-crud-api
- https://docs.databricks.com/aws/en/release-notes/product/2026/october
- https://docs.databricks.com/aws/en/agents/agent-bricks/knowledge-assistant
- https://community.databricks.com/t5/databricks-free-edition-help/not-able-to-create-pubic-link-for-databricks-web-app/td-p/138583

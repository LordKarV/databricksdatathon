# GPU access and how a model runs in the submission

Checked 2026-11-21, read-only, profile vf. Nothing was submitted or created.

## Answer

GPU training: available per docs, not verified in our workspace. The CLI and the
AI Runtime API respond, but no GPU has been attached yet, and the docs tie Free
Edition GPU access to LinkedIn identity verification, available capacity and an
unpublished fair-use quota.

GPU serving: not available. Free Edition docs say "No GPU serving endpoints" and
"No custom models on GPU or batch inference".

So: if we use a GPU at all, use it once, offline, and write results to Delta.
Nothing in the live demo may depend on a GPU.

## What the CLI showed (commands run)

- `databricks -v`: CLI v1.27.0. `databricks -h` lists group `air` ("Run and
  manage AI Runtime workloads on serverless GPU compute").
- `databricks air list -o json` and `air list --all-status -o json`: success
  envelope, `runs: []`. The AI Runtime API is reachable from this workspace and is
  not feature-gated with an error. We have never run a GPU workload.
- `databricks air pools list -o json`: error `FEATURE_DISABLED`, "the GPU pools API
  is not enabled for this workspace". Pools are dedicated capacity provisioned by
  an account team and are optional ("not required to run" per CLI help), so this
  only means we have no reserved GPUs.
- `databricks air run -h config.compute`: accepted types GPU_1xA10, GPU_1xH100,
  GPU_8xH100.
- `databricks clusters list`: []. `databricks jobs list`: []. `experiments
  list-experiments`: [].
- `databricks cluster-policies list`: Personal Compute, Power User Compute, Shared
  Compute, Job Compute, Legacy Shared Compute (default policies; Free Edition docs
  say only serverless compute, so these are not usable for classic GPU clusters).
- `clusters list-node-types` returns 631 node types, 39 with GPUs (g4dn, g5, ...).
  This is the cloud catalog, not an entitlement; ignore it.
- `current-user me`: active = True, groups users and admins.
- `serving-endpoints list`: 11 READY pay-per-token foundation endpoints (8 chat,
  3 embeddings), matching audit/capabilities/CAPABILITIES.md. No custom endpoints.

Not run: `databricks air run --dry-run` (the rules allow only list/get/help) and
any real workload.

## What the docs say

- Free Edition limitations
  (https://docs.databricks.com/aws/en/getting-started/free-edition-limitations):
  serverless only, no custom compute configurations; model serving: "No GPU
  serving endpoints", "No provisioned throughput", "No custom models on GPU or
  batch inference", "Limits on the number of active endpoints"; Jobs "Max of 5
  concurrent job tasks per account"; after LinkedIn verification "you get limited
  access to AI Runtime". Verification is a "Verify identity" button in the
  workspace top bar, shown only to eligible accounts. Exceeding the fair-use quota
  shuts compute down until reset.
- Blog "What's coming next for Free Edition", June 17, 2026
  (https://databricks.com/blog/whats-coming-next-free-edition): Free Edition "now
  includes access to GPUs, subject to availability". No hours or quota given.
- AI Runtime overview
  (https://docs.databricks.com/aws/en/machine-learning/ai-runtime/overview):
  A10 (24 GB), H100 (80 GB), 8xH100; "GPU capacity can be constrained or
  unavailable at times"; CLI jobs can run up to 14 days, notebooks 2 days.
- Serverless GPU page (https://docs.databricks.com/aws/en/compute/serverless/gpu):
  A10s and H100s through CLI, notebooks, jobs and Ray; models trained there can be
  deployed to Model Serving on CPU or GPU (GPU excluded on Free Edition).
- Community thread, July 2026
  (https://community.databricks.com/t5/machine-learning/what-is-the-gpu-quota-limit-for-free-edition/m-p/161101):
  a Free Edition user got "quota exceeded" after about 5 minutes of GPU use;
  Databricks staff said there is no published numeric GPU quota and throttling can
  last the rest of the day or month. Forum answer, not documentation.

## Hackathon programmes

- Apps & Agents for Good Hackathon, June 15-16, 2026, at Data + AI Summit
  (https://developers.databricks.com/hackathon/): links a "Set up Free Edition"
  guide; no GPU credits or other workspace tier mentioned. Our dataset catalog is
  named databricks_virtue_foundation_dataset_dais_2026, which suggests the data
  comes from that programme, but I found no page granting GPU credits or a higher
  tier to datathon teams. Unverified: ask the organisers directly.

## Verification step (needs user approval)

1. In the workspace UI, check whether the top bar shows "Verify identity". If it
   does, the account is not yet verified and GPU access is likely blocked until
   it is. Verification shares name, email and status with Databricks via
   LinkedIn; that is the user's call.
2. Validate config only (no compute):
   `databricks air run --file research/gpu/verify_gpu.yaml --dry-run -o json -p vf`
3. Smallest real test, about 1-10 GPU minutes on one A10, no retries:
   `databricks air run --file research/gpu/verify_gpu.yaml --idempotency-key gpu-smoke-20261121-v1 --watch -p vf`
   Success = `nvidia-smi` prints an A10. Failure modes to record: quota exceeded,
   AI Runtime not available, capacity unavailable.
   The file is research/gpu/verify_gpu.yaml in this directory. It uses fair-use
   quota shared with the warehouse and Apps, so do not run it on judging day.

## Do we need a GPU at all

Probably not. The data is about 10,088 facilities. Likely models (claim
classifiers on short sentences, record-merge scoring, a learned ranking over a few
dozen features) train in seconds to minutes on CPU (serverless notebook, or
locally then upload the artifact). Embeddings and LLM extraction already run
through the pay-per-token foundation endpoints (ai_query, gte-large-en verified
in CAPABILITIES.md), which need no GPU of ours. A GPU only pays off for
fine-tuning a transformer (for example a small encoder for claim support); if we
do that, it is a one-off AI Runtime job whose outputs we keep.

## How the submission runs on Free Edition

1. Batch scoring into Delta (default). A serverless notebook or job (or an AI
   Runtime job if the GPU works) scores every facility once and writes tables to
   the `workspace` catalog: per-facility service probabilities, evidence quotes
   with source row ids, confidence and flags. The App only reads these through
   the 2X-Small warehouse (databricks-sql-connector). No model runs at request
   time, so GPU, serving limits and cold starts do not matter during judging.
   Re-scoring 10k rows with ai_query spends fair-use quota: do it once.
2. Small model inside the App container, for query-time work such as distance
   and travel scoring or re-ranking the candidates for one query. Apps sizes per
   https://docs.databricks.com/aws/en/dev-tools/databricks-apps/compute-size:
   Medium (default) up to 2 vCPU / 6 GB, Large 4 vCPU / 12 GB; no GPU mentioned.
   Whether Free Edition allows Large is unverified. Keep the model a few MB
   (sklearn, LightGBM, or ONNX on CPU) and load it from the app source or a UC
   volume at startup. The App stops 24 h after start, so restart it before
   judging.
3. CPU custom model serving endpoint (optional, least preferred). Allowed in
   principle (docs forbid only GPU custom models and batch inference), but Free
   Edition limits the number of active endpoints (number not published), scale
   to zero after 30 minutes idle causes a cold start
   (https://docs.databricks.com/aws/en/machine-learning/model-serving/custom-models),
   and it adds a moving part. Only worth it if the model is too big for the App.
4. LLM explanations at query time can call a READY foundation endpoint (for
   example databricks-meta-llama-3-3-70b-instruct) as an App resource, but per
   CAPABILITIES.md the LLM's self-confidence is not trustworthy on contaminated
   records, so citations and scores must come from the precomputed tables.

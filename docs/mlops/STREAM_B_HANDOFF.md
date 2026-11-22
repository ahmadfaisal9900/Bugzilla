# Stream B integration handoff

Stream B provides contracts-compatible tracking and registry clients in
`src/bugzilla_serving/tracking/`, bounded dev experiment planning/execution in
`experiments/`, and the nine-page Streamlit dashboard in `dashboard/`. Research
code remains unchanged. Shared contracts/engine/configs and synthetic fixtures
are reused. See [CI.md](CI.md) for validation, images, exact local CI equivalents,
PR commands and required GitHub checks; [BACKFILL_MAPPING.md](BACKFILL_MAPPING.md)
for provenance/denominators; [promotion policy](../PROMOTION_POLICY.md) for gates.

## CLI reference

Use `conda activate iqfm`, Python 3.11, from the existing Project root. All paths
containing spaces/apostrophes must be quoted. `PYTHONPATH=src` works without an
editable installation. No `.env` is loaded by tests or CI. Backfills default to
planning; only the explicit owner `--apply` commands below write tracking data.
These are instructions, not claims that remote execution occurred.

```bash
# Synthetic local tracking/registry. Repeating reports created_runs=0.
python scripts/seed_mlflow_fixture.py --tracking-uri "file:$PWD/outputs/mlflow/dashboard-demo" --dry-run
python scripts/seed_mlflow_fixture.py --tracking-uri "file:$PWD/outputs/mlflow/dashboard-demo"

# Historical dev answer ledger adapter; no inference. Existing raw files stay local.
python scripts/backfill_answer_eval.py --mode ledgers
python scripts/backfill_answer_eval.py --mode ledgers --apply --resume
# Retrieval aggregates, idempotent/checkpointed uploads.
python scripts/backfill_retrieval_eval.py
python scripts/backfill_retrieval_eval.py --apply --resume

# Publish: inspect comparison/policy first; RUN_ID must identify a dev run.
python scripts/publish_preset.py --run-id RUN_ID --slug fast --label Fast --description 'BM25 dev configuration'
python scripts/publish_preset.py --run-id RUN_ID --slug fast --label Fast --description 'BM25 dev configuration' --apply
# Optional champion path; strict execute validation always applies.
python scripts/publish_preset.py --run-id RUN_ID --slug recommended --label Recommended --description 'Dev selection' --champion
# Only an explicit justified owner decision may add --override-policy 'reason'.
python scripts/publish_preset.py --slug fast --unpublish --apply

# Dev qid sets only (no question/gold text in YAML).
python scripts/make_eval_sets.py --dry-run
python scripts/make_eval_sets.py
# Default run plans only. Use --limit for a bounded subset.
python scripts/run_experiment.py --preset fast --eval-set smoke-5 --limit 1 --set context_budget_tokens=512 --set top_k=2 --dry-run
# Synthetic engine plumbing; local file store, no model download or provider call.
python scripts/run_experiment.py --preset fast --eval-set smoke-5 --limit 1 --set context_budget_tokens=512 --set top_k=2 --mock --fixture-bundle tests/fixtures/serving_bundle --tracking-uri "file:$PWD/outputs/mlops/mlflow" --label mock-smoke
# Live owner command requires A's real dev bundle and quota; preflight first.
python scripts/run_experiment.py --preset fast --eval-set smoke-5 --limit 1 --set context_budget_tokens=512 --set top_k=2 --enable-llm --max-requests 4 --label live-smoke
# Sweeps: ≤2 knobs, combined budget, sequential points, shared sweep_id.
python scripts/run_experiment.py --preset fast --eval-set smoke-5 --limit 1 --set context_budget_tokens=512 --sweep top_k=1,2 --dry-run
python scripts/run_experiment.py --preset fast --eval-set smoke-5 --limit 1 --set context_budget_tokens=512 --sweep top_k=1,2 --mock --fixture-bundle tests/fixtures/serving_bundle --tracking-uri "file:$PWD/outputs/mlops/mlflow"
python scripts/run_experiment.py --status JOB_ID
python scripts/run_experiment.py --cancel JOB_ID
```

Expected: dry-run JSON plans; seed COMPLETE/9 new runs/2 presets on a new store;
mock COMPLETED means plumbing finished, never answer quality. Backfill resume
skips completed hashes and preserves run IDs. Job manifests/checkpoints live in
`outputs/mlops/jobs/`; rerun the identical command to resume. Cancellation is
checked between questions, not during an in-flight call. See
[experiments README](../../src/bugzilla_serving/experiments/README.md) for quota,
checkpoint identity, cancellation and scoring details. Local `--preset` uses YAML
fallbacks; `--registry-presets` or `--run-id` explicitly reads MLflow. YAML's
recommended fallback is S8 and is not the published S2 champion.

## Dashboard modes and environment

```bash
# Local seed above first. CI-source runs are intentionally hidden from evaluation
# tables, but the synthetic champion and presets demonstrate registry plumbing.
MLFLOW_TRACKING_URI="file:$PWD/outputs/mlflow/dashboard-demo" LANGSMITH_SOURCE=fixture DASHBOARD_LAB_ENABLED=false python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
# Existing real dev local store, when present:
MLFLOW_TRACKING_URI="file:$PWD/outputs/mlflow/b1-ledgers" LANGSMITH_SOURCE=fixture DASHBOARD_LAB_ENABLED=false python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
# DagsHub: securely export the MLFLOW variables from local .env first.
LANGSMITH_SOURCE=fixture DASHBOARD_LAB_ENABLED=false python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
# Local Lab: mock toggle is default; real bundle required to enable live requests.
LANGSMITH_SOURCE=fixture DASHBOARD_LAB_ENABLED=true python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
```

| Variable | Purpose |
| --- | --- |
| MLFLOW_TRACKING_URI | DagsHub HTTPS endpoint or absolute local file URI |
| MLFLOW_TRACKING_USERNAME / MLFLOW_TRACKING_PASSWORD | Remote credentials, environment only |
| LANGSMITH_SOURCE | `fixture` offline; `live` for Production reads |
| LANGSMITH_API_KEY | Required only for real Production reads |
| DASHBOARD_LAB_ENABLED | Exact `true` enables local controls; `false` on host |
| DASHBOARD_PASSWORD | Shared dashboard login; optional for local fixture checks |
| LLM_PROVIDER / GROQ_API_KEY | Mock for offline checks; live provider requires key |
| BUNDLE_DIR | Verified real dev bundle/indexes for live Lab |
| HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE | `1` at image runtime and in CI |

Readonly mode hides Presets and disables Lab execution. Sources cache reads for
60 seconds and display fetch times. The dashboard never calls FastAPI. It loads
neither engine/experiments nor torch when Lab is disabled; a fresh-process test
executes all readonly pages and checks these module boundaries. Mock writes stay
in a local file store even when browsing DagsHub.

## Current tracking state and limitations

The local `outputs/mlflow/b1-ledgers` metadata was inspected offline on
2026-11-22: experiments `research-answer-eval`, `research-retrieval-eval`,
`playground`; registered model `bugzilla-qa-config`; champion alias version 1,
recommended/S2; published fast/S1 version 2. No DagsHub query was made, so its
current state is **not independently verified**. Owner-provided remote state is
recommended/S2 champion and fast/S1 preset; existing versions/aliases are untouched.

The recorded champion override reason is: “Policy winner S5 (0.6446) uses a 12K
dossier that exceeds the serving cap; S2 (0.6444) is within 0.01 pt and fits the
cap. Capped-S5 vs S2 comparison scheduled as a Lab run.” This reason records a
selection decision; it does not claim that the scheduled Lab comparison ran.

Existing versions may reference old config-only carrier runs in playground
(`source=lab`, `eval_set=config-registry`). Dashboard tables exclude these and
all sources outside `{backfill, lab}`. New publication attaches the config model
to its evaluated source run. If an archived run refuses artifact writes with
PERMISSION_DENIED, fallback carriers go to experiment `registry`, tagged
`source=registry`, `source_run_id=<original>`. Standalone fixture registration uses
`source_run_id=standalone`. No shared evaluation contract was expanded for these
metadata-only runs. Transport/authentication errors surface instead of fallback.

- pilot125 is a development pilot subset, not full dev or hidden-test evidence.
  Current answer denominators are 119/125, with six shared F5 questions pending
  human answer review. No synthetic replacements or automated human decisions.
- MH=0 and F3≈0 across systems. BACKFILL_MAPPING's source trace audit found genuine
  failures: direction/out-of-cohort/abstention problems and singleton-list versus
  scalar count outputs. Set order/ID normalization already works. Do not present
  these scores as merely a missing scorer fix; research behavior remains unchanged.
- S3 has zero fresh calls and all 125 answers match S2: `reused_from=S2`, duplicate
  outcome evidence, no independent S3 latency claim.
- Batch latency includes quota/rate-limit waits. Lab is end-to-end wall time;
  backfill uses final successful per-question timings. Missing usage remains
  explicit; positive partial token totals are lower bounds, unknown is not zero.
- Live Lab is blocked until A supplies `scripts/build_serving_bundle.py` and a
  verified real dev bundle/indexes/weights. Baking weights into an image supplies
  no canonical database or serving bundle. The synthetic bundle is mock-only.
- Historical S5/S8 12K configs are recordable but fail serving execute caps;
  policy override cannot make them deployable. v3 lacks F2/F5 and test F3;
  retrieval N/A differs from a missing family. No test questions/gold are exposed.

## Stream A integration expectations

Read presets through `Registry.list_presets()` and `get_champion()` under the
shared registry contract: model `bugzilla-qa-config`, alias `champion`, version tags
`preset_slug`, `preset_label`, `preset_description`, `published=true`; pyfunc
config artifact. Keep YAML fallback behavior explicit. Do not infer a champion
from leaderboard ordering or assume carrier runs are evaluations.

Write serving root traces to `ensf621-serving` (optional dev traces to
`ensf621-dev`) with metadata `config_hash`, `preset_slug` or `custom`, `system_id`,
`model`, `retriever`, `corpus`, `route`, `degraded`, `request_id`, `session_id`.
Feedback key `user_rating` is 0/1 with comment. B only reads these sources.

Ports: API 8000, chat 8501, dashboard 8502. Image names:
`ghcr.io/<owner>/bugzilla-{api,chat,dashboard}:<tag>`. B supplies
`docker/dashboard.Dockerfile` targets `dashboard-readonly` (host default) and
`dashboard-lab` (local only, CPU torch and config-pinned model revisions).
A owns API/chat Dockerfiles, Compose and CD. Mount real bundle read-only, keep
credentials outside images, disable Lab on deployed host. CI builds but never
pushes images. API/chat builds are conditional on file presence and main PR/manual.

At integration perform OVERVIEW §6: registry mode picker, champion parity on
three dev questions with MockProvider + real bundle, chat feedback visible in
Production, then enable compose smoke. No parity, compose, remote or deployment
success is claimed by this handoff. Docker builds/sizes/smoke are owner-run per
the latest task instruction.

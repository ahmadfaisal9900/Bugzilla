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

## B5 operator commands

B5 is implemented and tested offline with tiny fixtures. The real bundle, DagsHub,
Groq, live LangSmith, Docker images and GitHub CI execution remain operator checks.
Do not run model jobs during an interactive agent session. No new dependencies
were added; existing exact versions in `pyproject.toml` remain in force.

Run from the existing repository (the quote in its path matters):

```bash
conda activate iqfm
cd "/home/ict317/master's/ENSF 621/Project"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
# Only in your own terminal; never paste the values into chat or commit .env.
set -a
source .env
set +a
```

1. Verify the delivered bundle. The first call hashes listed files; a subsequent
   call re-stats them. `--rehash` explicitly repeats hashing. Unlisted HF cache
   blobs/refs/locks are ignored; listed symlinks are followed.

   ```bash
   python scripts/verify_bundle.py --bundle ./serving_bundle --json
   python scripts/verify_bundle.py --bundle ./serving_bundle --json
   ```

   Expected: exit 0, `ok: true`, split `dev`, `synthetic: false`, available `C1`,
   missing `C0,C2`, then `cache_reused: true`. A failed check exits 1; invalid CLI
   syntax exits 2. Inspect `pins_source`: the frozen serving YAML lacks model pins,
   so the verifier reports its exact `retrieval_v3.yaml` fallback. No bundle file
   is modified. The cache lives in `outputs/bundle_verify/`.

2. Build and time the DagsHub snapshot in your terminal. Artifact checkpoints make
   repeating this command resumable; failed refreshes keep the last good snapshot.
   The cap counts SDK calls, not hidden SDK HTTP retries or provider requests.

   ```bash
   scripts/run_phase05_dashboard_snapshot.sh --dry-run --max-requests 1000
   /usr/bin/time -p scripts/run_phase05_dashboard_snapshot.sh --max-requests 1000
   # Optional warmed page measurements with stderr call timings, no model calls:
   env -u DASHBOARD_PASSWORD LANGSMITH_SOURCE=fixture DASHBOARD_LAB_ENABLED=true \
     scripts/run_phase05_dashboard_snapshot.sh --max-requests 1000 --profile-pages
   ```

   Expected: timestamp/PID/log paths, then `COMPLETE`, sanitized tracking URI,
   `run_counts`, `built_at` UTC and `duration_seconds`. Snapshot JSON and metadata
   are under `outputs/dashboard_cache/<source slug>/`; wrapper logs and summary
   JSON are under its `jobs/<UTC timestamp>/`. `--profile-pages` adds each page's
   total seconds, slowest calls and errors. A warm page should have no MLflow SDK
   calls. A request cap, failed artifact or unavailable source reports `PARTIAL`
   and exit 1; repeat after resolving it. To include live production reads, set
   `LANGSMITH_SOURCE=live` explicitly; the default command uses the fixture.
   Offline BEFORE/AFTER measurements and their scope are in AGENT_NOTES.md.

3. Start the dashboard with profiling. This uses only reads until an explicit Lab
   or registry action; live inference stays off by default.

   ```bash
   BUNDLE_DIR="$PWD/serving_bundle" LANGSMITH_SOURCE=fixture \
   DASHBOARD_PROFILE=1 DASHBOARD_LAB_ENABLED=true \
     python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
   ```

   Expected: nine pages at localhost:8502, named modes/families, local snapshot
   time in the sidebar, technical IDs off, and render/data timings in stderr and
   the sidebar. Change filters and switch pages: no SDK calls should recur.
   A first immutable detail read is allowed, then cached. Refresh data rebuilds
   explicitly. The readonly deployment uses `DASHBOARD_LAB_ENABLED=false` and
   hides Presets. Set `DASHBOARD_SNAPSHOT_MAX_AGE_MIN=30` and
   `DASHBOARD_LANGSMITH_MAX_AGE_MIN=5` to change stale indicators; stale data stays
   visible. Docker's background entrypoint uses writable `DASHBOARD_CACHE_DIR`
   and preserves the torch-free readonly target; Docker health/build remains an
   operator CI check, not validated by AppTest.

4. Plan capped smoke-20 runs against the verified bundle. These are dry-runs:
   no inference, embedding generation, model loading or tracking writes.

   ```bash
   python scripts/run_experiment.py --bundle ./serving_bundle --preset recommended \
     --set system_id=S8 --set corpus=C1 --set s5_dossier_budget=4096 \
     --set s7_max_tool_steps=1 --eval-set smoke-20 --limit 20 \
     --max-requests 160 --dry-run
   python scripts/run_experiment.py --bundle ./serving_bundle --preset recommended \
     --set system_id=S2 --set corpus=C1 --set top_k=2 \
     --set context_budget_tokens=512 --eval-set smoke-20 --limit 20 \
     --max-requests 60 --dry-run
   ```

   Expected: verified bundle report, `actual_api_calls: 0`, 20 selected questions,
   request cap, `fits_request_cap`, estimates and today's remaining safe budget.
   S8 estimates 160 logical calls with one tool step; S2 estimates 60. S8's token
   estimate exceeds the configured daily allowance; S2 may also be refused,
   depending on current usage. `fits: false` is a safe planning refusal, not an
   executed failure or evidence of successful scoring. Do not replace `--dry-run`
   with execution merely to make this check pass. Dry-run always reports planning;
   execution additionally refuses an estimate above its cap. Scored Lab questions
   still come from `configs/eval_sets.yaml`, never the bundle's no-gold examples.

5. Review, commit, push and open a draft PR yourself. The B5 files are staged by
   exact name for the clean-checkout regression; the pre-existing `.gitignore`
   edit is excluded. Check the staged list before committing anything.

   ```bash
   git diff --cached --check
   git diff --cached --name-only
   git diff --cached --stat
   git commit -m "Implement B5 bundle verification and snapshot-backed dashboard"
   git push origin feature/mlops
   cat > /tmp/bugzilla-b5-pr.md <<'EOF'
   The dashboard now reads persisted snapshots so ordinary reruns avoid remote
   data calls, and presents named systems, family comparisons and usage in plain
   language. Lab execution verifies bundle integrity/corpus availability and sets
   offline Hugging Face paths before loading models.

   Validation: bounded offline fixture, tracking, experiment, CI, contract and
   Streamlit checks; exact results and timing scope are in docs/AGENT_NOTES.md.
   Remote service measurements and Docker/GitHub execution remain operator gates.
   No contracts, research code, Stream A files or delivered bundle were changed.
   EOF
   gh pr create --draft --base main --head feature/mlops \
     --title "B5: verified bundles and faster, readable dashboard" \
     --body-file /tmp/bugzilla-b5-pr.md
   ```

   Expected: one local commit, normal branch push and a draft PR URL. If a PR for
   this branch already exists, review/update that PR instead of creating another.
   These commands were not executed by the agent.

### Page layout checklist (three lines per page)

| Page | First line | Second line | Third line |
| --- | --- | --- | --- |
| Overview | Five mode/coverage KPI cards | Score-sorted named leaderboard, score bar and family shading | Key findings; collapsed technical records |
| Answer evaluation | Question-set/source filters | Named family correctness bars with n; declined/errors table | Saved intervals and technical records collapsed |
| Retrieval evaluation | Named source/family/search-measure filters | Search × archive heatmap and formatted scores/counts | Missing/N/A distinction and technical records |
| Cost & latency | Model usage table, calls and fresh-token bars | Typical/slow-case seconds table and grouped bars | Exact requested Notes and technical records collapsed |
| Error analysis | Named dev run picker | Failure categories and answer text, no gold fields | Run identifiers/config only in Technical details |
| Experiment Lab | Verified bundle status, split/corpora/models/size/date | Catalog-labelled knobs; missing corpora disabled | Readable preflight, explicit run controls, bounded progress |
| Compare runs | Named baseline/candidate pickers and question title | Automatic summary plus paired bars/differences with words/signs | n mismatch warnings, noise labels, collapsed family glossary |
| Presets | Named published modes | Snapshot-only policy preview and scalar comparison | Confirmed registry action; technical configs collapsed |
| Production | Local date filter over the retained window | Named mode aggregates in seconds and question-volume chart | Sanitized feedback; source freshness in sidebar |

Every page includes its purpose sentence, collapsed How to read this and Notes.
Streamlit 1.45.1 forbids nested expanders, so raw-config debugging uses a popover
inside each Technical details expander. IDs remain inside that technical view.

Open questions: serving.yaml's missing model pins need a future approved shared
change; missing manifest build dates are shown as Not recorded. The supplied
findings are reproduced verbatim, including their counting-tool explanation;
B5 does not rerun or revalidate those research claims. No new experiment success
is claimed. DagsHub/browser paint/Docker/GitHub performance remains unvalidated.

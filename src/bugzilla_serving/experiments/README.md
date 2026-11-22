# B2 dev experiment lab backend

This module reuses shared RunConfig/engine and the B1 validated MLflow writer.
It implements no new answering algorithms and changes no research or Stream A
code. `pilot125` is a separate historical PILOT subset, not these smoke sets.
No new dependencies: existing pinned Python 3.11 serving/dashboard/dev groups.
Use Conda `iqfm`.

## Data and scoring

`configs/eval_sets.yaml` contains only seed, named sets and dataset/qid pairs.
Sets are generated with an isolated seed-317 RNG and round-robin family sampling:
smoke-5, smoke-20, family-<F> up to 20. Some families have fewer dev examples:
F2=8, F5=6, MH=8, F6H=11 across the three dev collections. The source population
is 350 dev questions (Phase 5=34, natural=51, v3=265), not independent bug clusters.
Smoke-5 cannot represent all nine families. No test file or test gold is loaded.
Mixed natural rows are byte-filtered to dev before gold parsing (B1 helper).

The loader checks frozen hashes and dev membership. Gold stays in scoring;
engine calls receive only question text. The partner scorer receives adapted
AnswerRecords. F5 and ambiguous answers needing human assessment stay NOT_SCORED
with null per-item score and explicit source/scored/pending n. No fabricated
human judgments. Missing families have no metric. If the partner cannot handle
a gold type or is unavailable, only F1/F3/F4/F6/F6H/KI fallbacks apply; F4 fallback
is set-F1 (the partner path uses its existing scoring semantics). Family scorer
tags distinguish these. The adapter conservatively treats nonempty engine errors
as execution failures (including retained recovery diagnostics); it cannot infer
a richer terminal status from AnswerRecord. Lab latency is end-to-end engine
wall time, including quota pacing/cache effects, not B1's uncached-only latency. Macro averages scored families only; inspect n/coverage.

## Quota and execution

Preflight is offline: per-model Pacific-date REQUEST_STARTED reservations and
SUCCESS token usage from `configs/llm.yaml` ledger, 90% RPD/TPD limits from
serving.yaml. Unknown failed/incomplete usage gets a conservative token reserve;
cache hits are not charged again. Other clients can consume quota, and provider
headers/dashboard remain authoritative. Per-system estimates include one answer
repair, query transforms, tool turns/searches, and optional router repair. They
are conservative logical-call estimates, not guaranteed actual consumption.
Context budgets in the current graphs are UTF-8 bytes despite knob names;
planning estimates bytes/4 plus shared prompt/question/schema allowance/output.

One shared provider enforces max_requests for the whole job. Cache is isolated
by RunConfig hash (including temperature), ledger remains shared. SDK/provider
HTTP retries are disabled for experiments to avoid retry bursts; failed method
records are retained and scored as failures, never silently replaced. Runtime
pacing uses a conservative byte upper bound plus output allowance per request
and may refuse a large payload even when approximate planning fitted. Use a
smaller context/limit rather than bypass the guard. Bulk tracing is disabled.

CLI default is planning only. `--mock` executes with MockProvider, forces a
local file store, tags simulated=true, omits API cost metrics and uses a distinct
MLflow eval_set identity from live runs. Mock scores are plumbing checks, not
method performance. Mock mode uses real retrieval by default. The explicit `--fixture-bundle` option
requires --mock and reuses Phase 0 synthetic model fixtures without downloads;
it is a plumbing demo, not evidence that real retrieval performed well. No remote MLflow connection in default dry-run.
`--registry-presets` and `--run-id` explicitly allow reading the chosen MLflow;
normal `--preset` resolves local fallback presets and makes no champion claim.

## Checkpoints, status and cancellation

`outputs/mlops/jobs/<job-id>/` contains status.json, manifest.json,
predictions.jsonl and scores.jsonl. Job ID pins config, dev roster/source hashes,
engine/experiment code hashes and serving bundle manifest. The manifest contains
output hashes; completed ledger tampering is refused. A single flock excludes
other running jobs. Partial trailing JSON bytes are backed up before truncating
to the last committed newline. Existing completed records never execute again;
failed engine records are terminal method outcomes. A crash before a completed
row can rerun the engine; the provider cache reduces repeated calls. Exactly-once
remote execution across a crash cannot be guaranteed.

Status states: PREFLIGHT, REFUSED, RUNNING, SCORING, COMPLETED, FAILED, CANCELLED.
Completed means the job ran/logged, not that answers were correct. Errors and
pending family counts remain visible. Cancel is checked between questions;
in-flight requests finish. Status and cancel:

```bash
python scripts/run_experiment.py --status JOB_ID
python scripts/run_experiment.py --cancel JOB_ID
```

Rerun the same command to resume a crash/logging failure. A cancelled job keeps
its flag: explicitly remove its `outputs/mlops/jobs/JOB_ID/cancel.flag` before
resuming. CLI emits compact status progress to stderr and final JSON to stdout.
Sweep points are sequential, separately logged, share sweep_id and an aggregate
invocation request cap. Combined grid preflight must fit before any point starts;
it conservatively takes no credit for previously completed/cached points.

## Ordered terminal commands

Agent verification used synthetic fixtures only; no live run or DagsHub write.
Current real `recommended` smoke-5 plan estimates 70 requests / 278,950 tokens
and refuses a fresh safe 180,000-token day. Use bounded Fast for initial execution.

1. Generate/recheck qid-only sets and offline tests:

```bash
conda activate iqfm
python scripts/make_eval_sets.py --dry-run
python scripts/make_eval_sets.py
python -m pytest tests/b_experiments tests/b_tracking -q
python scripts/run_experiment.py --preset recommended --eval-set smoke-5 --dry-run
```

Expected: 11 named sets; smoke sizes 5 and 20; passing tests; zero-call preflight.

2. A standalone mock demo uses the existing synthetic bundle/model fixtures:
its questions are from smoke-5, but answers/evidence are simulated. No downloads
or Stream A artifact is needed for this CLI plumbing check:

```bash
python scripts/run_experiment.py --preset fast --eval-set smoke-5 \
  --set context_budget_tokens=512 --set top_k=2 --mock \
  --fixture-bundle tests/fixtures/serving_bundle \
  --tracking-uri "file:$PWD/outputs/mlops/mlflow" --label mock-smoke
```

Expected: COMPLETED job, source=lab/simulated=true, one local MLflow run. Repeating
uses the same job/run without new engine calls. No Groq requests.

3. Live execution prerequisite: export BUNDLE_DIR to Stream A's actual verified
**dev-only** serving bundle with valid indexes and locally available weights.
The current default serving_bundle/ is absent; B2 does not build A's artifacts.
Securely export Groq and DagsHub variables (do not put keys on the CLI).
Do not use the synthetic demo bundle for live research results:

```bash
python scripts/run_experiment.py --preset fast --eval-set smoke-5 \
  --set context_budget_tokens=512 --set top_k=2 --dry-run
python scripts/run_experiment.py --preset fast --eval-set smoke-5 \
  --set context_budget_tokens=512 --set top_k=2 \
  --enable-llm --max-requests 12 --label live-smoke
```

Observed fresh-day estimate: 10 requests / 30,890 tokens; actual use/cache may
reduce it. Preflight checks the current day's remaining budget before execution.
Expected: one DagsHub playground run with explicit scoring coverage and request cap.

4. Small one-day sweep (after checking remaining quota):

```bash
python scripts/run_experiment.py --preset fast --eval-set smoke-5 \
  --set context_budget_tokens=512 --sweep top_k=1,2 --dry-run
python scripts/run_experiment.py --preset fast --eval-set smoke-5 \
  --set context_budget_tokens=512 --sweep top_k=1,2 \
  --enable-llm --max-requests 24 --label top-k-smoke
```

Observed combined estimate: 20 requests / 61,780 tokens; two sequential runs,
shared sweep_id. This fits a fresh safe day, not necessarily the remaining quota
when you run it. Neither command accesses locked test data or publishes presets.

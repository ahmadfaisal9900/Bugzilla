# Task 1 — shared Gemini provider and v3 dataset

Status: implemented and tested on a synthetic 20-bug DuckDB fixture. Real v3
generation and human spot checks have not run. No successful Gemini request is
verified. The final offline suite passed 32 tests, including 20-bug fixtures,
provider mocks, interrupted resume, immutable review fields and freeze recovery.
Original freeze d8ef826fbeb90d13 stays unchanged: 169 primary questions
(34 development, 135 test) and six supplemental challenges.

## Setup and the 404

~~~bash
cd "/home/ict317/master's/ENSF 621/Project"
conda activate iqfm
python -m pip install -r requirements-v3.txt
python scripts/llm_ping.py --list-models --dry-run
python scripts/llm_ping.py --list-models --enable-llm --max-requests 1
~~~

The final command requests exactly one page of available generation model IDs,
without generating content or fetching subsequent pages. A listed model is not
proof of free-tier eligibility or remaining quota. Choose a model supported by
your free project. The configured Gemini 2.0 model and two listed Gemini 2.5
Flash models returned HTTP 404 during user-run generation pings, despite appearing
in the list response. The ping now reports the attempted model and a sanitized
Google error message so the next failure can identify whether Google rejects the
model name, method, API version or project. Stop after a failed ping; do not spend
more requests guessing. Python 3.9 warnings are separate from the HTTP error.

Keep each .env assignment on its own line; a line beginning with # is a comment.
Leave the existing key in .env. GEMINI_MODEL sets the generator and is the aux
fallback; GEMINI_AUX_MODEL sets aux separately. Environment variables override
.env, which overrides configs/llm.yaml. When both roles use one model, the lower
configured quota applies. The provider forces the Gemini Developer API, disables
SDK automatic retries, and does not enable LangSmith tracing.

Choose names from the model-list output in your terminal:

~~~bash
read -r -p "Available free-project generator model ID: " GEMINI_MODEL
export GEMINI_MODEL
read -r -p "Available free-project aux model ID: " GEMINI_AUX_MODEL
export GEMINI_AUX_MODEL
python scripts/llm_ping.py --role aux --dry-run
python scripts/llm_ping.py --role aux --enable-llm --max-requests 1
~~~

You can instead save those model names on separate lines in .env. No model is
automatically substituted after a failure. Configure quotas for the selected
model/project. Defaults are generator 15 RPM / 1,500 RPD and aux 30 RPM / 1,500
RPD, with a 90% daily ceiling on the America/Los_Angeles date.

## User-terminal generation

~~~bash
bash scripts/run_phase08_v3_generate.sh --dry-run --seed 317
bash scripts/run_phase08_v3_generate.sh --enable-llm --max-requests 120 --seed 317 --resume
~~~

The dry run prints two explicitly synthetic example prompts, the effective aux
model, zero calls, and an upper bound of 110 description calls. The 220 KI target
counts question forms: one identification and at most one field question per
parent report. Using 110 parents reduces model calls while preserving that target.
Eligibility/filtering can lower actual counts. Retries count against the
120-attempt invocation cap. A budget-limited run exits with code 2 and PARTIAL;
repeat the same command to continue.

Optional preparation performs source checks and summary embeddings without
Gemini calls:

~~~bash
bash scripts/run_phase08_v3_generate.sh --prepare --seed 317 --resume
~~~

Preparation may download the pinned sentence-transformer weights. Full jobs
verify input hashes, including a sequential canonical-database read. Expect
additional minutes and CPU work; no runtime guarantee is claimed. Existing
corpus/indexes and earlier imports are reused, not rebuilt.

Use --limit 5 with --max-requests 5 for a separate user smoke. Limits are part of
run identity; limited outputs cannot freeze. Start review only after
DRAFT_READY_FOR_SPOTCHECK.

## Outputs and independent validation

Every version goes under outputs/benchmark/v3/run-<identity>/. Source fingerprints,
model/config/code, limit and Git commit determine identity. LATEST_RUN.json points
to the latest completed or budget-limited invocation. Check the printed path
before using --latest.

Important artifacts:

- manifest.json, config_snapshot.json, inputs_verified.json and summary.json:
  actual counts/shortfalls, source/output hashes, public config and Git identity.
- summary_embeddings.npy and its manifest: normalized, revision-pinned summary
  vectors. Overlength summary roots are omitted from KI rather than silently
  accepted after tokenizer truncation.
- descriptions.jsonl: append-only parent decisions, sanitized descriptions and
  prompt/cache fingerprints. Completed/rejected descriptions are reused.
- dev.questions.jsonl and test.questions.jsonl: question schema.
- dev.gold.jsonl, test.gold.jsonl and oracles.jsonl: evaluator-only artifacts.
- qrels_v3_dev.jsonl and qrels_v3_test.jsonl: existing record-ID qrel format with
  incomplete relevance labels; F3/F6/F6H passage scores are not applicable.
- gold_checks.jsonl, gold_mismatches.jsonl and validation_report.json: separate
  SQL/evidence checks. Failed candidates are excluded.
- review/spotcheck_v3.csv: seeded up to 30 KI, 15 MH and 10 F6H items with blank
  verdict and note fields.

~~~bash
bash scripts/run_phase08_v3_validate.sh --latest --dry-run
bash scripts/run_phase08_v3_validate.sh --latest --resume
~~~

Expected: PASS, all retained questions checked, zero mismatches. The generated
validation_recheck.json pins question/gold/qrel/oracle/config files and verifier
code. Numeric checks do not establish KI wording equivalence.

## Human spot checks and freeze

Open review/spotcheck_v3.csv in the printed run directory. Check question, gold
and summary against saved corpus evidence. Fill every verdict with OK,
AMBIGUOUS, WRONG or LEAK and explain concerns in note. Real decisions must come
from the reviewer; scripts never approve actual rows.

~~~bash
bash scripts/run_phase08_v3_freeze.sh --latest --dry-run
bash scripts/run_phase08_v3_freeze.sh --latest
bash scripts/run_phase08_v3_freeze.sh --latest --resume
~~~

Freeze rejects partial/limited jobs, missing reviews, failed rechecks, changed
hashes, edited review questions/gold/source summaries, duplicate QIDs and
cross-split clusters. Non-OK questions are dropped;
rejecting a KI description also removes its sibling form. More than 15% non-OK
sampled KI items produces a regeneration warning.

The immutable frozen-<id>/ contains final questions/gold/qrels, evaluator oracles,
review/config/provenance and a final summary. The manifest status is
FROZEN_HUMAN_SPOTCHECKED, with hashes for every artifact. The ID is the first
16 hex digits of canonical manifest JSON with freeze_id omitted, avoiding a
self-referential hash. Resume verifies an existing release without replacing it.

Do not regenerate or edit a frozen run. Never send gold, oracles, provenance root
IDs, template identity or review sheets to answering methods. For KI, only the
question and its public source-scope description may enter inference. Keep test
artifacts sealed until later method configurations are fixed.

## Scientific and operational limits

- Exclusions use explicit references and parent IDs in original/natural questions,
  never original test gold. Conflicted metadata roots are omitted. Known v2 dev
  roots are also omitted if they would move to new v3 test. Counts can fall short.
- MH participants and KI alternates stay within one root partition. Duplicate
  neighbors and summary cosine are heuristic ambiguity allowances, not proof of
  equivalent reports. A KI field form is omitted if alternate field values differ.
- MH is scoped to recorded links within the Firefox cohort. FIXED requires a
  resolved/closed status and resolution FIXED. Last-change time is not history.
- F6H absence is checked against the entire canonical table, preferring interior
  gaps. Tiny/dense sources can require above-range IDs; counts are reported.
  Absence never asserts live nonexistence. Missing history is checked in the
  separate overlay and saved QC; a parsed empty history is not missing history.
- Priority/severity are absent canonically and skipped. KI requires an indexed
  public first comment and inherits that selection bias; status/resolution counts
  are reported. No unresolved-explanation coverage or as-of date is invented.
- Eligible copied v2 records are independently recomputed; F1 is capped at 150 by
  field. Unsupported/conflicted/missing-evidence records are excluded and counted.
  Copied F3 retains the exact original denominator/population. The whole population
  is an aggregate cluster and can overlap other source populations; report this
  track separately from claims of independent bug-entity holdout.
- Durable request reservations precede HTTP attempts. SDK retries are disabled;
  the shared local ledger controls cooperating processes. Other applications in
  the Google project also consume quota. A crash after remote success but before
  cache commit cannot guarantee exactly-once remote execution. Completed/cached
  descriptions are reused.
- Interrupted derived draft exports may be reconstructed from pinned inputs.
  Committed description prefixes are verified, truncated tails are backed up,
  and actual human review inputs are never replaced after decisions begin.
- Only explicitly public, available canonical comments enter prompts. Known
  identities/emails and configured secrets are sanitized. The ledger contains
  hashes, not raw prompts or keys. All data, reports, caches and logs stay ignored.

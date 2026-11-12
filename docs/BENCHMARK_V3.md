# Task 1 — shared LLM provider and v3 dataset

Status: implemented and tested on a synthetic 20-bug DuckDB fixture. The user subsequently completed generation, review and freeze; see the verified handoff below. The final offline suite passed 35 tests, including 20-bug fixtures,
provider mocks, interrupted resume, immutable review fields and freeze recovery.
Original freeze d8ef826fbeb90d13 stays unchanged: 169 primary questions
(34 development, 135 test) and six supplemental challenges.

## Setup with Groq (current default)

The user requested Groq after Gemini models returned 404 and the recommended
replacement returned 503. `configs/llm.yaml` now selects `provider: groq` and
`openai/gpt-oss-20b` for both roles. Groq documents strict JSON Schema support for
this model: https://console.groq.com/docs/structured-outputs .

Keep `GROQ_API_KEY` in ignored `.env`, one assignment per line. The provider reads
it directly; do not source `.env` or put the key in a command. Old `GEMINI_*` model
variables and `LLM_API_KEY` are ignored for Groq selection/authentication.
Optional `GROQ_MODEL` / `GROQ_AUX_MODEL` override the configured model.

~~~bash
conda activate iqfm
python -m pip install -r requirements-v3.txt
python scripts/llm_ping.py --dry-run
python scripts/llm_ping.py --enable-llm --max-requests 1
~~~

Expect the dry run to show `provider: groq`, model `openai/gpt-oss-20b`, and zero
calls. Continue only after the live ping reports SUCCESS with token counts.
The subsequent complete v3 generation and freeze are verified from saved artifacts; no live calls are made by the coding agent.

The default is deliberately conservative: 3 configured RPM (2 request starts per
rolling minute), 1,000 configured RPD with the existing 90% Pacific-day ceiling,
2,048 completion tokens and low reasoning effort. At that pacing, 110 successful
description calls can take roughly 55 minutes plus source preparation. Groq also
applies token quotas and account-specific limits; a request ledger cannot enforce
limits consumed by other applications. Published limits are at
https://console.groq.com/docs/rate-limits . Use your account's Free Plan for the
zero-cost course project; the code does not configure account billing.

SDK automatic retries are disabled. The shared provider caps retries/requests,
honors numeric Retry-After, and stops for a delay longer than five minutes so you
can resume later. Cache and ledger are isolated under `outputs/llm/groq/` and are
ignored. Structured output is validated locally before caching. Credentials are
redacted from surfaced error messages and never written to manifests or ledgers.

The backend/model/config change intentionally creates a new v3 run identity;
failed Gemini drafts remain preserved. Resume uses the same Groq settings and
code revision. Original Phase 5 frozen files remain protected.

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
LLM calls:

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

## Verified v3 handoff — 2026-11-12

v3 is **FROZEN_HUMAN_SPOTCHECKED**, freeze ID `e2207774a0f2cbad`, at
`outputs/benchmark/v3/run-289a50d1152f547a/frozen-e2207774a0f2cbad/`.
All 15 manifest-listed artifact SHA-256 values matched a read-only check.

| Family | Dev n | Test n |
| --- | ---: | ---: |
| F1 | 64 | 86 |
| F2 | 0 | 0 |
| F3 | 89 | 0 |
| F4 | 29 | 54 |
| F5 | 0 | 0 |
| F6 | 22 | 34 |
| F6H | 11 | 26 |
| KI | 42 | 123 |
| MH | 8 | 47 |
| **Total** | **265** | **370** |

Accepted coverage gaps: F2/F5 are absent from v3; F3 is absent from v3 test.
Do not generate replacement items. F2/F5 retrieval evaluation uses the original
Phase 5 and natural development tracks where present. F3/F6/F6H passage metrics
are N/A, distinct from a family that is not in a dataset.
`qrels_v3_dev.jsonl` has 265 rows (143 applicable, 122 N/A);
`qrels_v3_test.jsonl` has 370 rows (310 applicable, 60 N/A).
No v3 retrieval or answer evaluation is claimed. Earlier statements that v3
generation/review are pending describe the prior implementation handoff.

# B7 one-day amendment

**Superseded by [B7E_RESUME.md](B7E_RESUME.md):** use the plain-JSON/deterministic
tool resume and external F5 grading packet after the native-tool failures.

This supersedes the B7b 7,200-token-per-call / separate-S7 / holdout schedule.
Implemented and tested offline; no live generation, grading, tracking or snapshot
refresh was executed. Original S0–S8 source/prompt/tool-schema/cache-key baseline
remains byte-identical. Existing gold and ledgers are unchanged.

## Scope and budget decision

**The entire requested changed-route set does not fit 180K.** It needs 271,770
estimated tokens including grading. The first work to drop is ordinary tool
reruns in F1 and F6H, outside the four diagnosed families: F1=21 and F6H=11
(32 questions). Explicit `--scope priority` makes that deferral; default
`--scope changed` still plans all 79. This is a scope reduction, not a claim that
those 32 downstream routes are byte-identical. No result has been generated yet.

| Family | Required reruns | One-day priority reruns |
| --- | ---: | ---: |
| F1 | 21 | 0 |
| F2 | 8 | 8 |
| F3 | 12 | 12 |
| F4 | 5 | 5 |
| F5 | 6 | 6 |
| F6 | 7 | 7 |
| F6H | 11 | 0 |
| KI | 1 | 1 |
| MH | 8 | 8 |

| Plan | Rerun | Carried | Fresh generation calls | Generation tokens | Judge calls/tokens | Total | Generation invocations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All changed routes | 79 | 43 | 168 | 260,874 | 6 / 10,896 | **271,770** | 7 |
| Explicit one-day priority | 47 | 75 | 104 | 164,810 | 6 / 10,896 | **175,706** | 5 |

Every number includes the requested 50% token margin. Judge is a sixth invocation.
The one-day option leaves 4,294 tokens below the safe 180K daily ceiling. No
separate S7v2 or holdout job is scheduled. Existing holdout only has F3 questions.

For all 122 qids, rule routing is computed locally; 20 have no rule and their
saved classifier route is S5. No classifier call is needed to select the rerun
set. The required scope is S7v2, pinned-comment S5, or an S7/S8 primary TOOL audit
row. Zero complete cache hits were verified; no speculative cache credit is used.
All other answers are copied to a new composite ledger with
`carried_forward=true`, `source_run_id` (the original immutable prediction-run
folder ID, not an invented remote MLflow ID), and source prediction hash. Carry
rows have zero new-call/token cost; original answers and source ledgers are intact.
The composite MLflow run scores all 122, logs per-question provenance, and tags
`evaluation=composite_changed_routes`, `scope`, and `carried_forward`. The dashboard
footnote explains the composite and the priority deferral.

## Measured estimates and unchanged safety checks

| Parent | Reported tokens / calls | Mean tokens | Old reserve/call | New estimate/call (+50%) |
| --- | ---: | ---: | ---: | ---: |
| S7 → S7v2/tool route | 166,101 / 166 | 1,000.61 | 7,200 | 1,501 |
| S5 → pinned dossier | 249,898 / 127 | 1,967.70 | 7,200 | 2,952 |
| S2 → unchanged retrieval | 300,034 / 260 | 1,153.98 | 7,200 | 1,731 |
| F5 judge | six reported judge calls | 1,210.67 | 7,200 | 1,816 |

These are the exact eligible dev prediction ledgers, not rounded pilot summaries.
S7's 236 calls in incomplete aggregate rows are excluded from both numerator and
denominator. Dividing all reported tokens by all calls would treat missing usage
as zero and understate the estimate. A row aggregates multiple calls; without
per-call attribution its partially reported tokens cannot be assigned reliably.
Future variant history takes precedence over parent fallback, per route for S8v2.
No history retains the 7,200 ceiling fallback. Historical F5 judge calls provide
the closest parent for the new single-answer judge prompt.

Preflight and minute pacing use these means plus 50%; pacing reconciles reported
actual usage and reserves the ceiling when real usage is unknown. The hard
send gate remains estimated input (including schemas/system framing) + maximum
output <= 90% of 8K TPM = 7,200. Dossier trimming and the 2,048 output cap remain.
Every live request checks remaining daily tokens against its input + max-output
ceiling; missing/error usage retains the previous ceiling reserve. Existing shared
provider ledger, locks, cache, retry bounds, bundle verification, dev-only guard,
25-fresh-call invocation cap and checkpoint integrity checks remain in force.
Invocations may repeat within one quota day. Other activity consumes the same
180K safe budget. No .env is needed for tests or planning.

Expected priority invocations in roster order:

| Day | Invocation | Fresh calls | Estimated tokens including margin |
| --- | --- | ---: | ---: |
| 1 | Generation 1 | 25 | 44,780 |
| 1 | Generation 2 | 25 | 38,976 |
| 1 | Generation 3 | 25 | 37,525 |
| 1 | Generation 4 | 25 | 37,525 |
| 1 | Generation 5 | 4 | 6,004 |
| 1 | New-answer F5 grading | 6 | 10,896 |
| 1 | Total | 110 | **175,706** |

These are estimates, not promised future usage. The full repair upper bound is
higher than one day; a hard budget pause wins over completion. If five generation
invocations are insufficient, inspect completion and remaining budget before any
additional invocation. Never remove the gates to force completion.

## Scorer v2 rule (d), zero calls

For scalar duration gold, explicit "in hours" / "how many calendar hours" gives
hours to numeric scalars and numeric singletons. The existing one-hour tolerance
is unchanged. No-unit questions remain ambiguous; wrong numbers stay wrong;
explicit days answers are refused for hours questions without conversion.
Contract/citation/abstention validation still applies before awarding correctness.

Denominators: F1=21, F2=8, F3=12, F4=19, F5=6, F6=13, KI=24, MH=8, F6H=11.

| System | F1 | F2 | F3 | F4 | F5 | F6 | KI | MH | F6H |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S0 | 0→0 | 1→1 | 0→0 | 0→0 | 0→0 | 13→13 | 0→0 | 0→0 | 11→11 |
| S1 | 8→8 | 1→1 | 0→0 | 18→18 | 0→0 | 13→13 | 16→16 | 0→0 | 11→11 |
| S2 | 21→21 | 2→3 | 0→0 | 19→19 | 0→0 | 10→10 | 18→18 | 0→0 | 7→7 |
| S3 | 21→21 | 2→3 | 0→0 | 19→19 | 0→0 | 10→10 | 18→18 | 0→0 | 7→7 |
| S4 | 14→14 | 1→1 | 0→0 | 19→19 | 0→0 | 11→11 | 18→18 | 0→0 | 10→10 |
| S5 | 20→20 | 2→3 | 0→0 | 17→17 | 1→1 | 12→12 | 18→18 | 0→0 | 7→7 |
| S6 | 14→14 | 1→1 | 0→0 | 19→19 | 0→0 | 11→11 | 18→18 | 0→0 | 10→10 |
| S7 | 21→21 | 2→7 | 0→6 | 18→18 | 0→0 | 13→13 | 0→0 | 0→1 | 8→8 |
| S8 | 21→21 | 2→7 | 0→6 | 17→17 | 1→1 | 12→12 | 17→17 | 0→1 | 8→8 |

There are 27 changed rows: the original 14 F3/MH singleton fixes and 13 F2
question-unit fixes (including six that also unwrap a singleton). Every changed
cell is explained below; no wrong count is accepted. Frozen F5 references and
judgments remain unchanged for this ledger-only re-score. Promotion preview
selects no configuration under the unchanged policy.

The regenerated machine outputs are `outputs/analysis/b7b/changed_rows.csv`,
`summary.json`, `scorer-v2-backfill-plan.json`, `one-day-full-plan.json`, and
`one-day-priority-plan.json`. The analysis directory is intentionally ignored.

| System | Dataset | qid | Family | Old → new | Rule |
| --- | --- | --- | --- | --- | --- |
| S2 | natural | natural_d73d4296a1ac26490fdb | F2 | INCORRECT → CORRECT | question_stated_hours |
| S3 | natural | natural_d73d4296a1ac26490fdb | F2 | INCORRECT → CORRECT | question_stated_hours |
| S5 | phase05 | q_f821d5a7d2148d961471 | F2 | INCORRECT → CORRECT | question_stated_hours |
| S7 | natural | natural_45e9307006cfa002436c | F2 | INCORRECT → CORRECT | singleton_number+question_stated_hours |
| S7 | natural | natural_90a3fe83a93721a2e2c9 | F2 | INCORRECT → CORRECT | singleton_number+question_stated_hours |
| S7 | natural | natural_d13b1b77b018f58c7171 | F2 | INCORRECT → CORRECT | singleton_number+question_stated_hours |
| S7 | natural | natural_d73d4296a1ac26490fdb | F2 | INCORRECT → CORRECT | question_stated_hours |
| S7 | natural | natural_14dea18947f819a165f2 | F3 | INCORRECT → CORRECT | singleton_number |
| S7 | natural | natural_1ff9db21c37498214734 | F3 | INCORRECT → CORRECT | singleton_number |
| S7 | phase05 | q_f821d5a7d2148d961471 | F2 | INCORRECT → CORRECT | question_stated_hours |
| S7 | v3 | v3_bb5fff7e16d6b379f9ddade7 | F3 | INCORRECT → CORRECT | singleton_number |
| S7 | v3 | v3_13b1d27d94419f10879fac40 | MH | INCORRECT → CORRECT | singleton_number |
| S7 | v3 | v3_16911b9ae12cae02c201d505 | F3 | INCORRECT → CORRECT | singleton_number |
| S7 | v3 | v3_315be90cc9884d93d950e584 | F3 | INCORRECT → CORRECT | singleton_number |
| S7 | v3 | v3_c405fd55813cd6dfaf9f9b72 | F3 | INCORRECT → CORRECT | singleton_number |
| S8 | natural | natural_45e9307006cfa002436c | F2 | INCORRECT → CORRECT | singleton_number+question_stated_hours |
| S8 | natural | natural_90a3fe83a93721a2e2c9 | F2 | INCORRECT → CORRECT | singleton_number+question_stated_hours |
| S8 | natural | natural_d13b1b77b018f58c7171 | F2 | INCORRECT → CORRECT | singleton_number+question_stated_hours |
| S8 | natural | natural_d73d4296a1ac26490fdb | F2 | INCORRECT → CORRECT | question_stated_hours |
| S8 | natural | natural_14dea18947f819a165f2 | F3 | INCORRECT → CORRECT | singleton_number |
| S8 | natural | natural_1ff9db21c37498214734 | F3 | INCORRECT → CORRECT | singleton_number |
| S8 | phase05 | q_f821d5a7d2148d961471 | F2 | INCORRECT → CORRECT | question_stated_hours |
| S8 | v3 | v3_16911b9ae12cae02c201d505 | F3 | INCORRECT → CORRECT | singleton_number |
| S8 | v3 | v3_bb5fff7e16d6b379f9ddade7 | F3 | INCORRECT → CORRECT | singleton_number |
| S8 | v3 | v3_13b1d27d94419f10879fac40 | MH | INCORRECT → CORRECT | singleton_number |
| S8 | v3 | v3_315be90cc9884d93d950e584 | F3 | INCORRECT → CORRECT | singleton_number |
| S8 | v3 | v3_c405fd55813cd6dfaf9f9b72 | F3 | INCORRECT → CORRECT | singleton_number |

## Owner commands, in order

Use the existing Project checkout with provider/tracking environment variables
already exported in your own terminal. No secrets are included below.
The commands choose the explicit priority deferral; omit `--scope priority` only
if accepting the full **two-day** estimate. No live command below was run here.

1. Activate and regenerate the zero-call scorer/backfill plans:

```bash
conda activate iqfm
export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
python -m bugzilla_serving.experiments.rescore
python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm --scorer-version 2   > outputs/analysis/b7b/scorer-v2-backfill-plan.json
```

Expected: 27 changed rows, nine dry-run scorer-v2 plans, F3 n=12, no promotion;
zero API/MLflow calls.

2. Print both scope plans and save the chosen run identity (zero calls):

```bash
scripts/phases/run_phase07_v2.sh plan --system S8v2 --eval-set pilot122-v2 --dry-run   > outputs/analysis/b7b/one-day-full-plan.json
scripts/phases/run_phase07_v2.sh plan --system S8v2 --eval-set pilot122-v2 --scope priority --dry-run   | tee outputs/analysis/b7b/one-day-priority-plan.json
LEDGER="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["ledger"])'   outputs/analysis/b7b/one-day-priority-plan.json)"
```

Expected: required 79/43 carried, 271,770 tokens, fits_one_day=false; chosen
47/75 carried, 175,706 including judges, fits_one_day=true. Zero verified hits.

3. Day 1 generation, at most 25 fresh calls per invocation:

```bash
for invocation in 1 2 3 4 5; do
  scripts/phases/run_phase07_v2.sh run --system S8v2 --eval-set pilot122-v2 --scope priority     --enable-llm --max-requests 25     | tee "outputs/analysis/b7b/one-day-run-${invocation}.json"
done
python -c 'import json,sys; s=json.load(open(sys.argv[1])); assert s["completed"] == s["total"], s; print(s)'   "$(dirname -- "$LEDGER")/summary.json"
```

Expected aggregate: COMPLETE, 122 rows = 47 fresh + 75 carried; about 104 fresh
calls / 164,810 tokens. A per-invocation PAUSED_QUOTA can resume via cache. A daily
budget exhaustion must stop; this check prevents treating partial runs as complete.

4. Grade only the six new S8v2 F5 answers, Day 1:

```bash
F5_VERDICTS="$(dirname -- "$LEDGER")/f5-verdicts.jsonl"
scripts/phases/run_phase07_v2.sh grade --system S8v2 --eval-set pilot122-v2   --ledger "$LEDGER" --f5-verdicts "$F5_VERDICTS" --dry-run
scripts/phases/run_phase07_v2.sh grade --system S8v2 --eval-set pilot122-v2   --ledger "$LEDGER" --f5-verdicts "$F5_VERDICTS" --enable-llm --max-requests 6
```

Expected: six pending in dry-run; six completed source-bound judgments, at most
six fresh calls in this invocation / 10,896 estimated tokens. No old answers are
regraded and no separate S7v2 grading is scheduled.

5. Backfill to your MLflow store, then rebuild the snapshot (zero Groq calls):

```bash
python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm   --scorer-version 1 --apply --resume
python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm   --scorer-version 2 --apply --resume
scripts/phases/run_phase07_v2.sh backfill --system S8v2 --eval-set pilot122-v2   --ledger "$LEDGER" --f5-verdicts "$F5_VERDICTS" --dry-run
scripts/phases/run_phase07_v2.sh backfill --system S8v2 --eval-set pilot122-v2   --ledger "$LEDGER" --f5-verdicts "$F5_VERDICTS" --apply
LANGSMITH_SOURCE=fixture python scripts/mlops/build_dashboard_snapshot.py --max-requests 1000
```

Expected: old v1 runs retained with exclusions; nine distinct scorer-v2 runs and
superseded_by links; one composite S8v2 run with iteration=v2,
diagnosed_on=pilot125, evaluation=composite_changed_routes, scope=priority,
carried_forward=75, both macro metrics, and per_question.csv provenance. Snapshot
shows current runs and composite footnote. MLflow/snapshot requests are owner-only
network operations, with no model token quota.

## Validation and open questions

403 tests passed across bounded offline module invocations; Ruff check and format
checks pass. This includes original S0–S8 byte identity, scorer negative cases,
measured estimates and request/daily gate preservation, composite source-answer
preservation, cost isolation and local backfill. Only existing dependency warnings
were reported; no warnings from our code. No live calls, pushes or ledger edits.

The full requested scope cannot fit one safe quota day. The priority command is
an explicit optional scope reduction; the remaining 32 reruns are deferred, not
validated. Future usage/repairs may exceed the estimate and trigger a safe pause.
No new quality improvement is claimed before the owner runs and reviews results.

Files changed in this amendment:

- `src/bugzilla_serving/experiments/scorer_v2.py`
- `src/bugzilla_serving/experiments/token_budget.py`
- `src/bugzilla_serving/experiments/preflight.py`
- `src/bugzilla_serving/experiments/runner.py`
- `src/bugzilla_serving/experiments/v2_jobs.py`
- `src/bugzilla_serving/dashboard/views.py`
- `tests/b_experiments/test_b7b.py`
- `docs/AGENT_NOTES.md`
- `docs/mlops/BACKFILL_MAPPING.md`
- `docs/mlops/STREAM_B_HANDOFF.md`
- `docs/mlops/B7_ONE_DAY_PLAN.md` (new)

Prior staged work is preserved. Generated analysis reports are ignored and were
not staged. The two unrelated PDFs are untouched.

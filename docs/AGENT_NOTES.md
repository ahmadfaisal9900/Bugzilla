# Task 1 inventory and limits

| Expected | Found |
| --- | --- |
| Existing repository | `Project/`, origin `https://github.com/ahmadfaisal9900/Bugzilla.git` |
| Phase 5 freeze | `outputs/benchmark/phase05/run-65c5be3381f66811/frozen-d8ef826fbeb90d13/`; state `FROZEN_HUMAN_SIGNED`; all seven manifest artifact hashes matched in a read-only check. |
| Frozen split | The quality report states 169 benchmark questions: 34 dev and 135 test, plus six supplemental challenges. The supplied 141 test count includes those six challenges. |
| Natural rewrites | `outputs/eval_extension/bank-dacb7ca0ceb7e0ef/natural_approved.jsonl`: 110, with 51 dev and 59 test. This is a reviewed export; separate track seal status must be checked before calling it frozen. |
| 12,828 source chunks and 564 truncations | The older v1 corpus. The later v2 dense manifest reports 14,443 chunks and zero truncations. |
| Expanded 3,000/750 draft | V1 exists at `outputs/eval_extension/bank-a34d7d0a4b66911d/`; later v2 at `bank-dacb7ca0ceb7e0ef/` reports 2,489 candidates and 693 selected. Both are drafts. |
| History | `outputs/phase04/enrichment/cohort-8bb3150d29a598d8/api_enrichment.duckdb` is a separate API overlay. The canonical database's field changes are empty; never infer history from current status. |
| LLM client | The baseline uses Ollama. Task 1 adds `src/bugzilla_qa/llm/provider.py`; the owner installed Google GenAI and confirmed HTTP 404 for the requested model. |
| Source/config | `configs/eval_extension.json` identifies canonical and history databases; `src/bugzilla_qa/eval_extension/` contains corpus, retrievers, and bank code. |

The frozen quality report has zero supported historical as-of questions; the original archive date is unknown. F5 is FIXED-selected. Retrieved known-citation labels are incomplete. Public comment text may still contain personal data and needs appropriate handling.

The Gemini provider is opt-in and fixture-tested. It uses a local locked ledger, a model-specific token bucket, Pacific-date daily cap, SQLite response cache, bounded retry and JSON Schema validation. Its ledger enforces quotas only for cooperating processes sharing that ledger; other machines or applications in the same Google project also consume project quota. Crashes between a successful remote call and cache commit can cause a repeated billable request. No successful live API call has verified SDK/model support. Never put API keys in config or command-line arguments.

The owner-run ping established HTTP 404. Model listing and environment overrides are explicit, budgeted commands; no accessible replacement or successful live ping is claimed. The complete Task 1 generator, independent SQL/evidence recheck, review export and freeze integration are implemented with 20-bug fixtures. The owner subsequently completed generation and spot checks; verified freeze details follow. See `BENCHMARK_V3.md` for commands and provenance limits.

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

## Task 2 inventory and implementation — 2026-11-12

See `RETRIEVAL_V3.md` for the expected → found inventory. C0 is the later
14,443-chunk v2 corpus at `outputs/eval_extension/39a751ca190bbbc3/`; dense bytes
are in `bank-dacb7ca0ceb7e0ef/`, not the corpus directory. Provider is
`src/bugzilla_qa/llm/provider.py`, currently Groq, reused with generator role.
Natural dev has no F5 (22 F1, 4 F2, 2 F3, 23 F4); Phase 5 dev supplies F5.
Task 2 wraps existing algorithms and adds tokenizer-safe variants, graph/query
transforms, evaluator/cache, clustered metrics and preregistered selection.
It makes no change to frozen gold/splits or source data. Only fixture jobs ran;
real index builds/evaluation and live R7 are AWAITING_TERMINAL_RUN. Existing
owner edits to `.env.example`, EXTENDED_EVALUATION_RUNBOOK and review_natural_v2
are preserved and excluded from the task commit.

## Task 3 inventory and assumptions — 2026-11-13

See ANSWERING_SYSTEMS.md for expected → found. Both owner-run retrieval manifests
now say COMPLETE; existing selected_retriever.yaml selects R7b/C1. Current C0 is
14,443 chunks, C1 14,195, C2 14,666, not the older 12,828-chunk corpus. Provider is
Groq openai/gpt-oss-20b, not the Gemini placeholders. Native function calling is
added to that shared budget/cache/ledger interface, without rewriting it.
S2/S3 currently share R7b retrieval; this is explicitly reported. S4 checks R5
cross-encoder scores and retries with deterministic local multi-query, allowing
zero-call low-evidence abstention. Conservative byte token budgets are explicit.
Phase 5 lacks family in question files: extract only metadata; never typed gold
for inference. Natural/v3 imported aggregates use expanded-v2 partitions, distinct
from Phase 5. Old M3 remains unchanged and deprecated for this comparison.
No frozen/source edits, answer scoring, live API call or full experiment by agent.

## Stream B inventory and Phase 0 gate — 2026-11-21

Read `docs/mlops/OVERVIEW.md`, `STREAM_B.md` and `STREAM_A.md` before inventory. This inspection used only local metadata/code, the pilot CSV header and saved dev retrieval summaries; no test questions/gold or remote services were accessed.

| Expected | Found |
| --- | --- |
| Integration branch `mlops` | Checkout is `main`; local branches are `main` and `feature/mlops`. No local `mlops` branch. No checkout, branch creation or network fetch performed. |
| Approved `src/bugzilla_serving/contracts/` | Missing in the checkout and in the tracked tree of `feature/mlops`. |
| Shared `engine.py` adapter | Missing on both local branches. |
| Shared `configs/serving.yaml` | Missing on both local branches; no approved model limits or hyperparameter schema to consume. |
| Phase 0 `tests/contracts/`, serving fixtures and MLflow seed script | Missing on both local branches. Existing CSV data fixtures are research fixtures, not the specified serving contracts. |
| B-owned tracking, experiments and dashboard packages/scripts | Not present. |
| Research retrievers/graphs/provider/scorer | Present at the supplied `src/bugzilla_qa/` paths; provider includes `MockProvider`, scorer is `evaluation/systems.py`. Research code was not changed. |
| Answer-evaluation pilot | `outputs/evaluation/phase11/pilot125/` has only `REVIEW.csv` and `START_HERE.html`; no machine-readable score summary. Treat this as a PILOT subset, not full-dev results. The CSV includes references/answers; do not backfill its raw contents as metrics or tracking artifacts. |
| Retrieval evaluation | Two existing versioned `summary.json`/`per_question.jsonl` pairs; summaries report `COMPLETE`, split `dev`. No evaluations rerun. |
| Python 3.11 | `/usr/bin/python3.11` is 3.11.13. Its environment has PyYAML but no pytest, MLflow, Streamlit or Pydantic. Default `python` is 3.13.13. No dependency installation attempted. |
| Spec cross-links | OVERVIEW names `mlops_stream_a_serving_chat.md` / `mlops_stream_b_experiments_dashboard.md`; stream docs name `mlops_overview.md`. Actual provided spec files are `docs/mlops/OVERVIEW.md`, `STREAM_A.md`, `STREAM_B.md`. Specs were left untouched. |

**Gate:** OVERVIEW section 5 requires approved Phase 0 contracts, adapter and fixtures before the streams split. Rule 6 requires stopping rather than changing an impossible/unavailable contract. Stream B cannot validate exact RunConfig fields, engine outputs, configuration hashing or registry/trace fixtures against an approved implementation yet. No Stream A/shared implementation, dependency pins, tracking runs, dashboard or CI changes were made. No tests ran: the required contracts/fixtures and Python 3.11 test dependencies are absent. No commits or pushes were performed.

### Open questions / prerequisite handoff

1. Provide the approved Phase 0 commit/branch with `contracts/`, `engine.py`, `configs/serving.yaml`, serving fixtures, contract tests and the MLflow seed script; identify whether the intended integration branch is `mlops` or `feature/mlops`. No contract revision is proposed.
2. Provide the machine-readable dev pilot scoring export for backfill, or identify its actual path. The supplied `pilot125` directory is a human-review bundle only. Keep its PILOT label and sample denominator when adapting it.
3. Supply an offline Python 3.11 environment/wheel set for the agreed pinned Stream B dependencies. Tests must use MockProvider, synthetic fixtures, temporary file-based MLflow and fake-key output scanning once implementation is authorized by the Phase 0 handoff.


## Stream B prerequisite recheck — 2026-11-21

The current user instruction identifies **`feature/mlops` as the integration branch**, resolving the branch preference in the previous inventory. The checked-out branch remains `main`. Read-only `git ls-tree` inspection confirms that the local `feature/mlops` tracked tree also lacks `src/bugzilla_serving/contracts/`, `src/bugzilla_serving/engine.py`, `configs/serving.yaml`, `tests/contracts/` and `scripts/seed_mlflow_fixture.py`. The binding overview still names `mlops`; no shared spec was edited.

| Expected → found | Result |
| --- | --- |
| Approved Phase 0 shared implementation → local checkout and integration tree | Required contracts, engine and serving config are absent in both. |
| Phase 0 contract tests/seed fixtures → existing research fixtures | Research fixtures exist; the specified serving/MLflow contract fixtures do not. |
| Research scorer/provider → supplied package | `evaluation/systems.py` and `llm/provider.py` including `MockProvider` are present; unchanged. |
| Machine-readable answer pilot metrics → `pilot125` | Only `REVIEW.csv` and `START_HERE.html`. Header inspection confirms a question/answer/reference human-review sheet, not a scored metric export. No row contents were displayed. |
| Dev retrieval results → saved summaries | Two COMPLETE dev summaries with per-question files. No evaluations rerun. |
| Python 3.11 dependencies → `/usr/bin/python3.11` | Python 3.11.13 and PyYAML exist; pytest, MLflow, Streamlit and Pydantic are absent from that interpreter. |

**Disposition:** blocked at the Phase 0 dependency gate, not an implemented Stream B delivery. Per user rule 6 and OVERVIEW section 5, no contracts were invented, no Stream A/shared/research files were changed, and no dashboard, tracking, runner or CI implementation was started. The pre-existing edits in this notes file and untracked `docs/mlops/` specs are preserved. Only this append was made; no commits, pushes, installations, remote calls or tests. No test questions/gold were read.

**Open prerequisites:**
1. Provide the reviewed Phase 0 commit on `feature/mlops`: exact contracts, serving config, engine, contract tests and synthetic fixtures/MLflow seed. No contract change is proposed.
2. Identify or export the scored machine-readable dev pilot results; retain the PILOT subset label and actual denominators. Do not treat the review CSV as full-dev evaluation results.
3. Provide the Python 3.11 offline environment/wheels for agreed, pinned Stream B dependencies. Implement and test against a temporary file MLflow store only after the shared handoff is available.

## Phase 0 creation authorized — 2026-11-21

The current P0 instruction explicitly authorizes creating missing contracts/engine/specs; missing Phase 0 files are no longer a gate. Existing `feature/mlops` and `main` start at the same commit. Work proceeds on `feature/mlops`; previous notes/spec edits are preserved. Python 3.11 exists and pinned local installation is authorized. Research graphs/provider/scorer and two COMPLETE dev retrieval summaries exist; pilot125 remains a human-review PILOT bundle, not machine-readable full-dev scores. The partner handle and model maximum-context value were placeholders; declared choices and remaining review items are in `docs/mlops/PHASE0_NOTES.md`. No contract/fixture implementation existed at inventory.


## Phase 0 creation task — 2026-11-21

The owner explicitly authorizes P0 to create the shared contracts; missing Phase 0 is no longer a reason to stop source implementation. Branch is now `feature/mlops`. Pre-existing uncommitted pyproject changes, package skeleton, partial RunConfig, configs and specs were preserved and extended. The partner username supplied in-session is `SpLasty`; shared CODEOWNERS lists both collaborators.

| Expected → found | Resolution |
| --- | --- |
| Conda iqfm, Python 3.11 | Actual iqfm is Python 3.9.25. No installs: the owner's explicit do-not-install instruction takes precedence over the contradictory generic pip permission. |
| Required packages | FastAPI, MLflow, Streamlit, pytest/pytest-cov and Ruff absent from iqfm; current Pydantic is newer than the pin. Exact extras are in pyproject and included by requirements.txt. |
| Empty shared package | Partial uncommitted work existed; source implementation now adds the remaining contracts, thin graph adapter, API stub, seed script and tests. |
| Model context limit | Not supplied; 4,096 remains a documented operational input cap for review, not an architectural claim. |
| Partner pilot | Human-review CSV/HTML only. Synthetic partner fixtures match the header/two-file layout and remain explicitly PILOT. |

Created deterministic synthetic fixture inputs (20 fake bugs, 61 public chunks, three tiny FTS5 indexes, 10 dev questions), sample answer/SSE/30 LangSmith runs and schema-shaped synthetic retrieval summary. Regenerated twice in temporary directories: bundle manifests are byte-identical. Fixture hashes/counts/dev-only checks and Python 3.11 syntax checks passed. Existing research regressions passed via unittest in the unmodified iqfm environment: 30 answering tests and 14 retrieval tests. No research files or real/frozen questions/gold were edited or loaded.

**Not yet verified:** Python 3.11 Phase 0 pytest, local MLflow seed/registry/idempotence/fake-key checks, OpenAPI snapshot and Ruff. FastAPI is unavailable, so no fake OpenAPI snapshot is substituted; the initial tests/contracts/openapi.json must be generated after installing the declared pins, only with UPDATE_SNAPSHOTS=1. The current Python 3.9 environment cannot import the new Python 3.11 contracts. Source checks do not replace those gates. See docs/mlops/PHASE0_NOTES.md for exact commands and assumptions. No remote calls, dependency installs, commits or pushes during P0.

## Stream B B1/B3 — approved archival amendment, 2026-11-21

Current branch is `feature/mlops`; Python is Conda iqfm 3.11.15 with the pinned
serving/dashboard/dev dependencies already present. Earlier missing-P0/environment
notes above describe previous inspections. No installation or push in this task.

Owner approved record-vs-execute RunConfig validation and the review-only pilot
fallback; partner notified. See `mlops/PHASE0_NOTES.md` approved amendments.
Tracking/backfill/registry/promotion code is implemented under Stream B ownership;
research/API/chat/engine/serving-cap files remain untouched. No real registry,
Groq, LangSmith or DagsHub calls, dataset rebuilds, or test gold access.

Real-data dry runs: nine PILOT answer plans (auto -> review-only) and 24 retrieval
pair plans. The current CSV has 358 rows and **zero human answer verdicts**, not a
completed human evaluation: 272 automatic outcomes, 86 ungraded including all
54 F5 rows. These are the current filesystem observations; no earlier reported
human-decision counts are assumed. Missing exact raw prediction references are
not a blocker for review-only. No raw answers/questions/reviewer identities are
included in MLflow artifacts. Pending F5, absent costs/rates/latency and 12K
historical S5/S8 budgets prevent automatic serving promotion, not archival logging.

Details, source-to-metric mapping and ordered terminal commands are in
`mlops/BACKFILL_MAPPING.md`; promotion was predeclared in `PROMOTION_POLICY.md`
and `configs/promotion.yaml`. No champion was chosen by the coding agent.

Verification: 46 offline contract/Stream B tests passed in 16.21 seconds;
Ruff check and format check passed. The in-process FastAPI TestClient needed
execution outside the sandbox because its AnyIO portal stalled inside it;
no HTTP/live-service calls were made. Both real-data backfills dry-ran cleanly
without tracking writes (9 answer / 24 retrieval plans). No source/frozen or
Stream A code changed. Existing earlier notes edits are preserved unstaged.

## Stream B B2 inventory and implementation — 2026-11-21

| Expected → found | Action |
| --- | --- |
| Integration root/branch → existing Project / feature/mlops | Retained; no remote changes or pushes |
| Shared contracts/engine/B1 tracking → present | Reused unchanged; no new contract amendments |
| Experiments → package stub only | Implemented B2 data/scoring/preflight/runner/sweep and CLI |
| Dev sources → Phase 5=34, natural=51, v3=265 | Verified dev-only loader; generated qid-only sets with seed 317 |
| recommended → configs/presets.yaml local fallback | Offline dry-run works without reading MLflow; not a champion claim |
| Real serving bundle → serving_bundle/ absent | Execution prerequisite remains Stream A's bundle/indexes/local weights; no A implementation attempted |
| Conda iqfm → Python 3.11 and existing pinned dependencies | No installs/new dependencies required |

Real-data inspection is limited to dev inputs, hashes and dry-run estimates. No
model calls, real indexing/evaluation or remote service operations. Mock jobs and
live jobs have separate identities; mock metrics are explicitly simulated. F5 is
not automatically judged. See `src/bugzilla_serving/experiments/README.md` for
quota assumptions, resume/cancel semantics and exact ordered terminal commands.
Current recommended smoke-5 estimate: 70 requests / 278,950 tokens, refused by
the safe 180,000-token daily budget. Fast with context=512/top_k=2 estimates
10 requests / 30,890 tokens; two top_k points estimate 20 / 61,780. No live
consumption is claimed. Actual remaining quota is checked again at execution.

B2 verification: 16 tests passed in 9.88s; unchanged contracts/B1: 46 passed
in 25.05s, run as separate bounded groups (a combined invocation was stopped
at the 30-second limit). Ruff check/format passed. Real recommended/Fast/sweep
preflights and make_eval_sets dry-run succeeded with zero API calls. The explicit
--fixture-bundle mock path reuses P0 synthetic model fixtures without downloads;
live runs refuse synthetic bundles. No source/frozen, contract, engine, API or
chat code changed. No real MLflow/Groq/LangSmith calls or pushes; no installs.

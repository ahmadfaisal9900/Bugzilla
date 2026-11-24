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

The current user instruction identifies **`feature/mlops` as the integration branch**, resolving the branch preference in the previous inventory. The checked-out branch remains `main`. Read-only `git ls-tree` inspection confirms that the local `feature/mlops` tracked tree also lacks `src/bugzilla_serving/contracts/`, `src/bugzilla_serving/engine.py`, `configs/serving.yaml`, `tests/contracts/` and `scripts/testing/seed_mlflow_fixture.py`. The binding overview still names `mlops`; no shared spec was edited.

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


## Stream B1/B3 inventory and contract gate — 2026-11-21

Read the overview and both stream specs. The checkout was clean on main; switched to the requested existing feature/mlops branch. Phase 0 contracts are present on both branches. Conda iqfm now has Python 3.11.15 and the declared MLflow 2.22.1, Pydantic 2.11.7, pytest 8.3.5, Ruff 0.11.13, PyYAML 6.0.2 and FastAPI 0.115.12. No installation was needed or attempted.

| Expected → found | Evidence / handling |
| --- | --- |
| Phase 0 names and validators | Present; no shared contract changes made. CI-low/high are not allowed answer metric names; future backfill can retain intervals as artifacts, as the task permits. |
| B-owned tracking implementation | Only tracking/__init__.py exists. No client, registry, backfills or publisher implemented during this gate inspection. |
| pilot125 human-review bundle | Exactly REVIEW.csv and START_HERE.html. CSV has 358 review rows (86 answer verdicts); embedded HTML JSON contains 1,125 display records across 125 dev questions and nine methods, plus per-dataset comparison aggregates. This remains a PILOT subset. |
| Exact typed prediction/config provenance for that pilot | Not included in the two-file bundle. HTML display rows have qids/methods and displayed answers but lack raw prediction/config hashes, token usage and per-question timings. There are no local phase05/dev or natural/dev prediction manifests. Five v3/dev manifests belong to partial/smoke runs; they cannot be silently substituted for the completed pilot. |
| Original source configuration | Existing saved config snapshots use dossier_tokens=12000. |
| Contract can represent historical runs | RunConfig.validate_against rejects S5 s5_dossier_budget=12000: maximum and operational model cap are 4096. Mapping it to 4096 or omitting the effective S5 budget would misstate the source run. |

**Stopped under task rule 6.** The archived-S5 rejection was reproduced in a bounded offline check. No test questions/gold were loaded; no pytest suite, MLflow write, model request, network call, commit or push was run. Only this notes append was made. The human-review HTML was parsed in memory for schema/provenance inspection; no question, answer or raw source body was displayed or saved.

### Proposed contract change — requires both collaborators' approval

Separate historical tracking validation from deployability validation: permit authentic historical RunConfig values for source=backfill, with the original configuration and provenance retained, while preserving current serving caps and full validate_against checks for lab execution, registry publication and champion selection. This requires an explicitly reviewed shared validator/API change; no bypass or clamping was implemented. An alternative is an approved contract for archived research configs distinct from deployable RunConfig.

### Required source handoff

Provide the pilot125 latest/evaluation manifests, pilot selection, matching dev prediction ledgers and identity/config snapshots for all three collections (including the Phase 5 and natural runs). Dev gold already exists at the configured paths. These permit recomputation with bugzilla_qa.evaluation.systems and audited review-ID joins; the display HTML alone cannot establish typed predictions, actual source configuration or cost/latency. Do not regenerate answers, substitute smoke results, invent missing metrics or label the pilot full-dev.

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

## Stream B B3 — Dev Dashboard, 2026-11-21

| Expected → found | Handling |
| --- | --- |
| Existing Project origin / feature/mlops | Confirmed; no remote or branch changes. |
| Dashboard implementation | Only package stub existed; added nine Streamlit pages under B ownership. |
| B1 tracking/registry and B2 Lab | Present; reused clients, policy, strict execute gate, runner, preflight, sweep and mock fixture adapter. |
| Local b1-local data including a mock Lab run | 9 review-only answer runs and 24 retrieval runs found; no playground run. Missing scores/costs/latency remain unavailable. |
| Real serving bundle | Absent; explicit fixture/mock mode only until BUNDLE_DIR points to a real bundle. |
| LangSmith source | Existing 30-root synthetic fixture and required contract keys reused; live service not contacted. |
| Python / dashboard dependencies | Conda iqfm Python 3.11; declared pinned Streamlit, Plotly, MLflow and LangSmith installed. No installs or dependency changes needed. |

Implemented typed source snapshots with 60-second caches/fetch times, family-cell
missing/N/A distinctions, dev-only artifact gates, production aggregates, password
gate, comparison, explicit registry confirmations and disabled-by-default Lab.
Background mock writes stay local; completion uses that job's tracking URI.
Quota panels reuse B2 estimates; no tracing writes or FastAPI calls. Saved CIs
retain their dataset scope instead of being attached to pooled family scores.
The read-only deployment hides Presets and all Lab controls. pilot125 is labelled
pilot subset throughout. v3's no-F2/no-F5/no-test-F3 gaps stay explicit.

Verification: 17 dashboard/AppTest checks passed (10.29s), including all populated
pages, empty states, auth, cache, registry confirmation/policy, a completed mock
background job and fake-key scan. B1/B2 regression: 27 passed (10.36s). Shared
contracts: 34 passed (15.84s) plus the one offline OpenAPI check (0.24s), separate
bounded invocations. Existing answering/retrieval fixture tests: 44 passed
(8.89s). Total targeted checks: 123 passed. Ruff check/format clean.
App startup on port 8502 confirmed
with a four-second read-only/fixture launch; no browser session or live service
was used. See dashboard/README.md under src/bugzilla_serving for commands and
read caps. Research, frozen data, contracts, engine, API and chat unchanged.
No Groq, DagsHub or live LangSmith calls; no pushes. Real remote integration and
live Lab remain operator checks after a real bundle is available. No contract
amendments requested. The pre-existing unrelated notes edit is preserved.

### Dashboard relative launch-path correction — 2026-11-21

Streamlit's CLI may expose a relative __file__, while st.Page resolves relative
paths against the main script directory. The previous construction could thus
repeat the directory prefix. Page paths now use Path(__file__).resolve().parent,
independent of cwd and safe with spaces/apostrophes. Real subprocess regressions
launch via relative script paths from the repo root and a different temporary
directory named partner's workspace. Each polls /_stcore/health, then connects
over localhost WebSocket to execute all nine pages and reject exceptions or
unsuccessful script completion. Both passed in 6.36s. Sources are fixture/local,
credentials are stripped from child environments, telemetry is off and child
processes are always terminated. No external service requests or contract changes.
Full dashboard regression: 19 passed (15.74s); Ruff check/format clean.

### Backfill foreign-path fallback — 2026-11-21

pilot125/latest.json contains Windows-absolute evaluation output references.
POSIX Path previously prepended the Linux repo root and discovery opened a
missing manifest before auto-mode could fall back. Discovery now treats foreign
absolute paths and missing manifests as unavailable evidence; explicit review-only
skips ledger discovery. No source paths are guessed or rewritten. Explicit ledgers
mode still refuses missing evidence. Fourteen tracking fixture checks pass (1.96s),
including foreign/missing paths and bypassing unusable provenance in review-only.
The actual default dry-run now succeeds: review-only, 358 rows, three datasets,
nine planned systems, no MLflow writes or API requests. Ruff clean; source files
unchanged. Review-only omits unavailable cost/latency metrics as before.

### Backfill verified portable ledger resolution — 2026-11-21

The fallback-only fix was insufficient: the exact local natural/phase05/v3 runs
exist. Resolve saved foreign paths by their exact outputs/ suffix, keep run IDs,
and verify all prediction input hashes against original evaluation manifests.
All 30 referenced prediction inputs match. Never search for substitute runs or
rewrite archived manifests. Normalize relative Windows separators for config
references too. Fixed identity validation to reuse the answering runner's compact
digest; scorer.digest uses a different JSON serialization. Snapshot/identity
checksums are enforced. Test prediction references fail before content access.

The missing archived official_runtime/retrieval.json means historical rrf_k is
unknown (nullable contract field), explicitly recorded in provenance; it is not
inferred from today's config. No shared contract or research changes. Local
default dry-run now uses ledgers: 1,125 system/question rows, three datasets,
nine systems; calls present for nine and latency for seven. Token metrics remain
omitted because saved usage is incomplete. No MLflow writes/API calls or answer
regeneration. Original-to-local path mappings and provenance pins are artifacts.
Tracking/experiment fixtures: 34 passed (10.85s), Ruff clean. Existing immutable
review-only runs are not overwritten when historical config hashes differ.
Seven local b1-local configs differ; use a fresh store for a preserving ledger
import. Missing archived retrieval config, if restored, must match its identity
input hash. Bounded --mode ledgers dry-run also passes without MLflow writes.

### Dashboard Arrow display-type correction — 2026-11-21

Mixed scored and review-only rows placed float metrics and unavailable labels in
the same object column, causing Streamlit's Arrow conversion warning/traceback.
Dashboard tables now prepare a display copy: numeric-only columns stay numeric,
columns with text use nullable string dtype, and nested records use JSON text.
Raw metrics, scores and counts are unchanged; missing values never become zero.
Regression checks serialize mixed/nested fixtures directly through PyArrow and
assert all nine populated fixture pages avoid Arrow automatic-repair messages.
Eighteen unit/AppTest checks passed (9.73s), plus two real localhost subprocess
launch checks (6.03s); Ruff clean. No API, tracking-store or source-data changes.
The separate MLflow model type-hint warning and download progress are benign.
Pre-existing notes changes and untracked .../ and mlruns/ directories preserved.

### Local tracking denominators and dashboard handoff repair — 2026-11-21

Owner explicitly requested answer.<F>.pending: added the nonnegative integer
counter to names/validator and contract docs/tests; no RunConfig or API changes.
Ambiguous duration-unit outputs previously received per-system NEEDS_HUMAN,
causing F2 n to differ. The requested adapter protocol marks malformed outputs
incorrect/failures and shares genuine pending (dataset,qid) exclusions across
all systems. Source grader verdict/reason are retained in score_audit.jsonl;
research scorer/gold/predictions are unchanged. All systems now score 119/125,
with six shared F5 answer-grading reviews pending; F2 n=8 for every system.

Investigated MH/F3 using saved tool traces and original grading code. Set order
and numeric ID normalization already work. S7's tools can count the dev
partition, but several correct counts are returned as singleton lists and fail
the scalar contract. MH also has false abstentions, incoming/outgoing link
direction gaps and out-of-cohort target handling. Four sanitized dev examples
and the complete corrected per-family table are in BACKFILL_MAPPING.md.

Fixed no-champion comparison labels and preset-only policy N/A; predict() has
supported type hints; sidebar footer displays credential-free MLflow host/path
and live/fixture LangSmith source. Local authorized --mode ledgers --apply
updated the original nine b1-ledgers run IDs. Aliases and both registry version
tags/presets match the before snapshot exactly. Ignored backup/summary:
outputs/mlops/backfill_repair/20261122T025849Z/. No DagsHub/Groq/LangSmith calls.

Verification: 37 tracking/experiment fixtures, 19 dashboard unit/AppTests,
35 contract fixtures plus the one offline OpenAPI snapshot and two localhost
subprocess launches passed (94 distinct targeted tests). Ruff check/format
clean. No raw corpus/model/frozen files staged; existing notes and untracked
mlruns/ preserved. No champion/preset publication performed.

### 2026-11-22: Cost and latency inspection

Expected → found: saved usage uses `tokens.input/output/cached_input/cached_output`,
not the old backfill's `input_tokens/output_tokens` keys. S8's cache flag can be
true alongside fresh calls; it cannot filter latency. S3 has zero fresh calls and
all 125 answers match S2; the Phase 5 REUSED_PREDICTIONS file records a separate
run-migration provenance, not on its own proof of S2 reuse. Backfill now checks
answer equality, matching qids and all-cache/zero-call rows before tagging S3.
Registry carriers used `source=lab, eval_set=config-registry`; dashboard excludes
these and non-backfill/non-lab sources. New publishes attach the model artifact
to their source run rather than creating a carrier. Research files unchanged.

## B4 inventory — 2026-11-22

Read RESEARCH_STATUS, research roadmap, OVERVIEW (§4–6), both streams,
PHASE0_NOTES, BACKFILL_MAPPING and PROMOTION_POLICY before implementation.

| Expected → found | Handling |
| --- | --- |
| Project / feature/mlops / original GitHub origin → confirmed | No repository, branch or remote changes |
| Existing B contracts/tracking/experiments/dashboard → present | Reuse; no research or Stream A edits |
| Deprecated min_items → absent; predict annotations → present | Already satisfied; retain contracts unchanged |
| Source attachment and dashboard filter → present; standalone carrier → playground/lab | Move new fallback carriers to registry/source=registry; preserve existing versions |
| Dockerfile/dockerignore/CI/Dependabot → absent | Add B4 files |
| iqfm Python 3.11 → available; Docker CLI → available, daemon permission denied; actionlint → absent | Offline checks only; owner builds images |

Latest pasted instruction takes precedence: do not build Docker images here.
CI readonly builds every PR; Lab/API/chat only PRs into main or manual dispatch.
No live APIs, external tracking, pushes or test-split data access authorized.

### B4 implementation and offline validation

Added two dashboard Docker targets, context exclusions, SHA-pinned CI actions,
weekly grouped Dependabot, CI commands/branch protection guide and Stream B
handoff. Readonly image excludes torch/serving dependencies; Lab adds CPU torch
2.6.0 and downloads only model/config/tokenizer files at the config revisions.
Engine imports stay behind the exact Lab-enabled gate. No images were built,
per the owner's amended request; sizes and container smoke remain owner checks.
CI builds readonly on every public PR/push; Lab/API/chat only main PR/manual.
No A Dockerfiles exist; CI emits notices rather than inventing them.

New preset versions normally attach to source runs. PERMISSION_DENIED on an
immutable source artifact write routes the fallback to registry/source=registry,
with source_run_id; standalone registration uses source_run_id=standalone.
Existing versions/aliases were not modified. Added fallback/source-filter tests.
No deprecated min_items exists in contracts, and predict already had hints.
The malformed model_construct test now checks an invalid enum without an integer
serializer warning. Only exact LangGraph and Starlette/AnyIO upstream warnings
are filtered. Remaining Pydantic warnings originate in MLflow's installed
mlflow/types/chat.py (its own min_items/class-based config); not suppressed.

Verification: **325 distinct offline tests passed**, split into bounded invocations:
36 contracts, 28 tracking, 16 experiments, 21 dashboard unit/AppTests, 2 localhost
Streamlit launch tests, 3 B4 checks and 219 existing research regressions. All
checks use synthetic fixtures; no full-data processing/model downloads. One
combined dashboard/experiment coverage invocation hit its 30-second bound;
both groups then passed separately. Accumulated serving coverage is **85.68%**
(coverage report/XML reviewed; temporary outputs retained under /tmp only).
Ruff check and format check pass. Pre-existing shared/A formatting and existing
lint findings are scoped as explicit Ruff baseline exceptions rather than
editing protected files; remove after owner review. Any broad formatter edits
to protected files were restored byte-for-byte from the clean initial HEAD.

**Not executed/validated:** actionlint and Gitleaks (not installed; offline task
forbids fetching tools), GitHub action execution, Docker builds/container health,
image sizes, remote MLflow state, parity/Compose integration and live Lab.
Workflow YAML, shell syntax and action SHA shapes receive local static checks;
these do not replace actionlint or real builds. Exact owner commands are in
mlops/CI.md. No remote APIs, dataset jobs, credentials, pushes or research/A edits.

### B4 follow-up: inherited environment isolation — 2026-11-22

| Expected → found | Resolution |
| --- | --- |
| Owner full-suite result → 321 passed / four failures, 85.71% coverage | Prior clean-environment grouped checks did not cover inherited provider overrides |
| Failure cause → ambient provider credentials/model selection override temporary synthetic .env files | Reproduced all four exact failure types using synthetic ambient values and a fake Groq response (zero network calls) |
| Research code → read-only | No research or legacy-test changes; CI-owned root conftest loads tests/b_ci pytest plugin |
| Existing local artifacts → modified egg-info SOURCES.txt plus build/, coverage and JUnit files | Preserved; excluded from staging |

The CI plugin removes inherited provider credentials/model overrides before test
collection, preserves local file-store URIs and forces offline/fixture settings
inside the pytest process only. The invoking shell is unchanged. Suite-wide
Requests/HTTPX sync/async transport guards prevent live HTTP even if a test's
fixture configuration regresses; ASGI clients and existing localhost launches
remain usable. Explicit synthetic credentials set within individual tests still
work. Root conftest is CI test configuration, not production/research code.
Added a child-pytest regression for the four failures under synthetic ambient
keys/model and direct no-network transport assertions. No secrets read/printed,
no live API calls or Docker builds. Owner reported Gitleaks scan passed on the
previous commit; no new Gitleaks execution is claimed here.

Follow-up verification: 327 distinct tests pass across bounded groups (all
previous 325 plus two regression checks). The inherited-environment regression
runs the four originally failing tests together under synthetic ambient values;
all four pass. Direct Requests/HTTPX attempts fail before transport. Ruff check,
format check and diff whitespace checks pass. No production source changed;
coverage was not remeasured in this follow-up (owner's full-run result: 85.71%).
Full single-invocation coverage rerun remains the exact command in CI.md for the
owner, respecting the agent's 30-second per-invocation test bound. No pushes.

### B4 follow-up: clean-checkout fixture dependencies — 2026-11-22

| Expected → found | Resolution |
| --- | --- |
| Mock Lab fixture complete in Git → serving_bundle indexes ignored/untracked | Mock worker materializes the existing tiny synthetic builder into a temporary directory, restores BUNDLE_DIR and cleans up after execution |
| Four assisted-review fixture roots → Path('.') reads ignored real normalization manifest | Named failing tests now create a temporary synthetic manifest and pass that fixture root to validators |
| Research package and real source data → read-only | Unchanged; no data/model artifacts added |

Added a CI regression copying only tracked source/config/test files into a temp
source tree, explicitly excluding outputs and ignored fixture indexes. It runs
the entire assisted-review fixture module plus the dashboard mock completion/
secret-scan test there. Commit provenance is read through the existing Git dir;
no new Git repository is initialized. The Lab image includes the existing tiny
fixture builder; no Docker image built here. No HTTP/model requests or real
manifest access are needed by these fixture paths. Real-bundle behavior remains
unchanged and no generated databases/indexes should be committed.

Verification: 53 distinct targeted tests pass (10 assisted-review fixtures,
21 dashboard unit/AppTests, 16 experiments and 6 B4 checks), including the clean
tracked-source regression. Each invocation remained below 30 seconds. Suite
collection reports 328 tests; the full coverage run remains owner-run. Ruff
check/format and diff whitespace checks pass. No skipped failures, real manifest
substitution, new fixture binaries, remote calls, Docker builds or pushes.

## B5 inventory — 2026-11-22

| Expected → found | Handling |
| --- | --- |
| Existing Project / feature/mlops / original origin → confirmed | No repo or remote changes |
| B1–B4 contracts, tracking, experiments, nine pages, CI/Docker → present | Reuse; contracts and A/research read-only |
| Data calls → independent 60-second caches | Profile first, then persisted snapshots |
| Real serving_bundle → present | Accepted delivery, no contents changed |
| Pins in serving.yaml → absent; exact pins in retrieval_v3.yaml | Verifier uses existing pins as explicit fallback; no shared contract edit |
| Pre-existing .gitignore edit → present | Preserve, never stage |

Offline only. No DagsHub, Groq, live LangSmith, pushes, bulk processing or image builds.

### B5 BEFORE / AFTER — offline fixture measurements

Measured with Streamlit AppTest against the same temporary seeded file store
plus the existing sparse dashboard fixture runs. BEFORE clears the old data
caches between pages. AFTER uses a warm disk snapshot and warmed Overview
imports. These are server script times, not browser paint times or DagsHub
measurements. All page exceptions were checked; none occurred. No external
tracking endpoint was contacted.

| Page | BEFORE (s) | Slowest BEFORE calls (s), up to 3 | AFTER (s) |
| --- | ---: | --- | ---: |
| overview | 0.202 | mlflow.champion 0.0104; mlflow.runs 0.0064; mlflow.runs 0.0061 | 0.035 |
| answer_eval | 0.316 | mlflow.runs 0.0090; mlflow.runs 0.0088; mlflow.artifact 0.0025 | 0.396 |
| retrieval_eval | 0.037 | mlflow.runs 0.0062; mlflow.artifact 0.0028 | 0.048 |
| cost_latency | 0.028 | mlflow.runs 0.0062; mlflow.runs 0.0061; mlflow.artifact 0.0019 | 0.049 |
| error_analysis | 0.022 | mlflow.runs 0.0067; mlflow.runs 0.0062; mlflow.artifact 0.0009 | 0.013 |
| experiment_lab | 0.134 | mlflow.presets 0.0192; mlflow.runs 0.0060; mlflow.runs 0.0059 | 0.106 |
| compare_runs | 0.019 | mlflow.runs 0.0059; mlflow.runs 0.0059 | 0.026 |
| presets_page | 0.058 | mlflow.presets 0.0177; mlflow.runs 0.0060; mlflow.runs 0.0059 | 0.032 |
| production | 0.040 | langsmith.roots 0.0032 | 0.040 |

Cold snapshot build: **0.116 s** (same tiny fixture; stderr profile event).
AFTER pages have no run/registry fetches. First Error analysis visit lazily reads
an immutable artifact (0.0015 s); Production parses the local fixture (0.0027 s).
Subsequent detail reads are cached without TTL.

A separate populated B5 fixture adds two synthetic scored systems, both 20-question
families, partial usage and latency. Its acceptance check denies SDK get/search/
download calls, renders all nine pages, scans main-view table cells/labels for
8+-character hex IDs, and checks <2 s per render / <1 s per switch. Reviewed
result: latest cold build 0.1381 s; warm renders 0.015–0.352 s. This is fixture acceptance,
not a remote or live-model performance claim. The comparison includes matching-n
gates, binary paired sign tests when full paired rows exist, and the stated
small-count heuristic otherwise. Aggregate question differences are rounded
score-equivalent counts; they cannot recover individual outcomes from fractional
scores.

### B5 implementation and boundaries

- Implemented manifest/stat/hash verification and atomic integrity cache; every
  listed symlink target is checked. Lab and runner use corpus availability and
  offline HF environment. CLI real bundles require dev / synthetic=false.
- Snapshot generations publish atomically behind a process lock; a failed refresh
  preserves the last good disk pointer. Immutable small-artifact checkpoints
  support restarting an interrupted build. SDK call caps are explicit. Runs and
  registry versions paginate; artifact downloads use at most eight workers while
  holding the MLflow artifact-URI context in the parent.
- Regular filters/page switches read only cached snapshots. Stale data stays
  visible until Refresh data. Production has a separate persisted 31-day fetch
  window and 5-minute stale indicator (1,000 roots / 2,000 feedback cap); date
  widgets filter it locally. This window is a bounded view, not all history.
- Display-only catalog/findings retain the requested text. Extra entries cover
  existing deep, synthetic and retrieval fixture IDs. Findings are owner-supplied
  narrative, not new experiment conclusions. IDs/configs are behind Technical
  details; the raw-config control is a popover inside that expander because
  pinned Streamlit 1.45.1 forbids nested expanders.
- Docker startup builds a snapshot in the background into DASHBOARD_CACHE_DIR;
  readonly remains torch-free. Existing CI workflow unchanged. No Docker build,
  remote calls, bundle rehash of the 300 MB delivery, model execution, commit,
  push, or PR performed. New files are staged by name so the existing tracked-
  checkout regression can include them. The original .gitignore edit is excluded.

Open contract question: configs/serving.yaml contains no embedding/reranker
pins, and this task forbids changing it. Verification compares model names and
revisions against the existing exact configs/retrieval_v3.yaml pins, reports that
source explicitly, and switches to serving.yaml's retrieval mapping if approved
pins are later added. Built date is shown as Not recorded when the manifest has
neither built_at nor created_at; no date is invented.

Commands, page layouts and owner validation gates: see
[Stream B handoff](mlops/STREAM_B_HANDOFF.md#b5-operator-commands).

### B5 final verification — 2026-11-22

**337 distinct offline tests passed**, covering all 337 collected cases, in
bounded invocations: 219 existing research fixture regressions (97 + 49 + 73),
36 contracts (23 + 12 + one OpenAPI), 28 tracking, 16 experiments, 21 existing
page/unit tests, two localhost launch tests, six CI checks and nine new B5
acceptance tests. The new tests cover integrity/cache reuse/symlinks/model pins,
corpus/HF env checks, catalog coverage, comparison math, mismatched n, no-hash UI,
zero SDK calls on warm pages, disk reload and last-good refresh preservation.
Latest affected page and experiment reruns passed (21 and 16 respectively).

The original combined contract invocation hit its 28-second guard at the local
OpenAPI test. Splitting the group and enabling local sockets completed all cases.
The launch assertions were updated for the deliberately renamed page headings;
launch fixtures now explicitly use an absent bundle and temporary cache so they
cannot hash the delivered bundle. Both root and apostrophe/space cwd launches
passed. No skipped failure or real-data substitute was introduced.

Ruff check and format check pass, as do diff whitespace and both shell syntax
checks. Tiny CLI checks confirmed verifier exit 0 / failed-check exit 1 / usage
exit 2, and snapshot dry-run without store creation. All requested catalog texts
were compared against the attachment and match verbatim; added catalog entries
only cover existing IDs. The existing upstream MLflow/Pydantic deprecation
warnings remain unsuppressed; no new warning from project code was found.
No coverage remeasurement, Docker build, actionlint/Gitleaks execution or remote
CI run is claimed. Real DagsHub speed/browser paint and actual bundle verification
remain terminal commands for the owner. No commit/push/PR was performed.

Final staged-checkout CI rerun: six checks passed in 8.81 s. Exact staged
filenames were inspected: 29 B5 files, no contracts/research/A/bundle/workflow
changes. The sole unstaged file is the owner's pre-existing .gitignore edit.

## B6 inventory — 2026-11-22

| Expected → found | Handling |
| --- | --- |
| Existing Project / feature/mlops / clean tree → confirmed | No new repo/remotes; no pushes |
| B4/B5 source, fixtures, snapshot/cache and Compare → present | Reuse; protected A/research/bundle inputs unchanged |
| 54 pending F5 rows → 54 rows, 6 phase05 questions × S0–S8 | CSV references joined with HTML system/qid metadata |
| Reference or verdict for each F5 row → all six references present identically across nine systems; all 54 answer verdicts blank | No missing-reference stop condition |
| F5 research scorer → always NEEDS_HUMAN for valid explanations | User chose a separate capped semantic-grading job, then import saved verdicts; never invent scores |
| Pilot selection → 125 dev questions: phase05 34, natural 20, v3 71 | Exact saved prediction manifests resolve locally |
| Real API → Phase 0 stub only | Fake-engine API and stub parity tests; no A edits |
| Dossier 12K → blocked by byte knob AND mistaken model-token-cap comparison | Approved amendment 2 corrects only dossier eligibility/unit |

References (each applies to all nine systems, not nine different gold answers):

| phase05 qid | Existing reference reason |
| --- | --- |
| q_0f02c856b8576c53962d | Manual ESR request because moz-phab uplift is broken |
| q_103fc1febfb8153ed3d2 | Heading level 2, comparable with Settings |
| q_639f25ec01824d49c28e | Synchronous layout flush before patch; suspected overflow-check race |
| q_7e52cb5dac94d7614825 | Cannot link to about:preferences as a traditional page |
| q_a5c70180da726d9445de | Stop dispatching at/after XPCOMShutdownThreads |
| q_df73d0a04940f296b92e | Nonworking Open in Firefox option; suspected Windows-specific XML issue |

No reference/answer content or verdict was changed. The user explicitly chose
to prepare the semantic-grading job for their own terminal, not to run it here.
Its dry-run has six requests (nine anonymous candidates per question), 54 pending
rows, and zero model requests. Whole-input estimates for the six batches are
723–922 tokens before the 2,048 output reservation. No LLM verdict exists yet,
so 125/125 and the new F5-inclusive macro remain unexecuted owner steps.

### B6 historical validation and unchanged policy preview

Before importing F5, every historical configuration was revalidated. S1, S2, S3,
S4, S5, S6 and S8 pass; S0 and S7 fail only because their recorded top_k is
inapplicable. No archived knobs were silently rewritten. Engine's existing
config update gives an explicit dossier value priority over bundle runtime.

The unmodified policy selects **none**. Every system has existing families
below 0.50 (notably MH=0 and F3 near zero); several also fail abstention/failure
limits. Missing F5 additionally blocks the current preview. Importing F5 cannot
remove the non-F5 minimum-score failures, so no replacement champion can pass
this policy on these ledgers. A post-import preview command is provided; no
post-import result is fabricated and the policy is not loosened. S2 remains
champion and no publication/rollback on DagsHub was performed.

### B6 live exception: one LangSmith smoke trace

The explicitly authorized smoke created one root trace plus one user_rating=1
feedback in ensf621-serving, no model calls. The first immediate read returned
404; a later read of the SAME ID confirmed smoke=true and the feedback. No
second trace/rating was created. Script read-back now retries bounded indexing
delays and forces sampling=1 for this one intentional smoke.

Trace: https://smith.langchain.com/o/e906d1d7-e702-4a19-a9ed-6fa3de69fe08/projects/p/8a6bd5d1-459e-4652-a21c-33d50de2470c/r/96b5c506-32c6-4205-ba1b-9eb67c8b0f50?poll=true

Production visibility is implemented/tested offline; live dashboard Refresh is
an owner check. No DagsHub or Groq calls were made. Credentials were loaded only
into the smoke process and never printed/staged.

### B6 published Fast dry-run

Read the published Fast configuration from the local reference registry without
changing knobs: S1/R1/C1, top_k=10, context_budget_tokens=3000. The smoke-5 plan
with max_requests=8 reports fits=true, fits_request_cap=true, est_calls=8,
est_tokens=34,128, input_estimate_source=UTF-8 bytes/3 and actual_api_calls=0.
The real bundle was not rehashed for this agent check; real-bundle verification
is in the owner's exact command. A separate synthetic fresh-quota test verifies
the same five-base/three-repair cap. No live S1 evaluation was executed here.

### B6 verification and remaining owner gates

All **348 collected offline tests passed** in bounded groups: 219 existing
research fixture regressions (97 + 26 + 23 + 73), 36 contracts (18 + 12 + five
record-mode + one OpenAPI), 28 tracking, 16 B2 experiments, 30 B5 dashboard
checks, two localhost launches, six CI checks and 11 new B6 checks. Both fake
engine API and Phase 0 stub parity paths passed. OpenAPI golden bytes remain
unchanged. Existing cap tests now use 12,001 as the invalid dossier value,
while both 4,096 and 12,000 are tested valid. The real ledger adapter's synthetic
fixture covers F5 verdict import and both macro metrics, not only review-only
mode. Read-index retry, smoke filtering and anti-downgrade checks are covered.

Ruff check/format, shell syntax and diff whitespace checks pass. No dependencies
were installed, no protected A/research/review/bundle file changed, and no raw
verdict/data/model/log/credential file is staged. Existing upstream MLflow /
Pydantic warnings remain unsuppressed; no new project warning was introduced.
One larger fixture group hit its 28-second guard under parallel load; smaller
groups then completed all its cases. No skipped failure was used.

The only live exception was the single LangSmith trace/rating described above.
F5 judgment generation/import, local or remote backfill apply, S1 live execution,
post-F5 policy preview, real API parity, live dashboard Refresh and Docker/GitHub
CI execution remain owner steps. No new research score, 125/125 real denominator,
champion change, DagsHub rollback, commit or push is claimed. The unrelated
untracked ensf621_phase2_report.pdf that appeared during work is preserved and
excluded from staging.
# B6 follow-up: accepted bundle example format (2026-11-22)

The owner's real parity invocation exposed an engine startup mismatch not covered
by the original structured synthetic fixture. All 299 accepted bundle examples
are text-only objects; the verified manifest declares their dev scope. The shared
engine now normalizes only that exact format in memory. Structured rows still
require explicit dev scope. No bundle content or manifest was changed.

Verified: real S2/Mock bundle initialization loads all 299 examples with zero LLM
calls. Six bounded regression cases pass: matching fake API and readable stub
differences for both example formats, plus four invalid/non-dev row cases.
This does not claim a complete real-bundle parity run or partner API validation.

## B7 Part 1 inventory and stop — 2026-11-22

| Expected → found | Handling |
| --- | --- |
| Existing Project / feature/mlops / original origin → confirmed | No repository/remote changes; no pushes |
| Clean baseline → substantial staged B6 edits and two untracked PDFs | Preserve every existing edit and staging entry |
| Stream B contracts/engine/configs/fixtures/tracking/experiments/dashboard → present | Reuse; no shared/A/research code changes |
| Exact pilot125 inputs → manifest-referenced natural, phase05 and v3 ledgers present | Existing checksum/review-binding validation reused |
| Missing partition handling → contradicted | count_bugs already uses sample_membership, conflict exclusion and frozen partition functions |
| Missing lifecycle arithmetic → contradicted | get_lifecycle already computes first_fixed_hours with verified history safeguards |
| All 37 questions use dev populations → contradicted | Three v3 dev-labeled F3 aggregates preserve original test-population scope |

Following the user's explicit stop condition, completed the bounded offline
Part 1 audit only. `outputs/analysis/failure_audit/audit.csv` contains 333 saved
system/question rows (37 questions × nine systems); 17 are correct, 316 incorrect.
Every incorrect row has exactly one primary diagnosis. Source scores, errors,
raw/final answers, context/retrieval IDs and full tools remain separately visible.
Saved 54 F5 judgments are fingerprint-verified, not regenerated. GOLD labels
flag the dev/test-population policy conflict, not a proven wrong numeric gold.
Record presence cannot prove untruncated evidence text; historical official_runtime
is absent. The report states these attribution/provenance limits explicitly.

Reproducible local command: `scripts/phases/run_phase07_failure_audit.sh --apply --limit 37
--max-requests 0` after activating iqfm. Default/`--dry-run` writes nothing.
The task's bounded real audit completed in under one second, zero API requests.
Input hashes are retained in ignored provenance.json; deterministic rebuild is
the resume mechanism. Logs and timestamped summary stay ignored. Generated report
is copied byte-for-byte to docs/mlops/FAILURE_AUDIT.md. Raw audit data remains
ignored and is never staged. No new dependencies; existing exact pins retained.

Parts 2–4, re-scoring, MLflow writes, v2 implementations, holdout selection and
quota plans are deliberately not started. See FAILURE_AUDIT.md for amended-plan
questions. The before-B7 byte pins cover all existing research modules and prompt
files, including schemas and cache identities; the regression checks their bytes.

B7 verification: **363 distinct collected tests pass** (353 existing + ten new),
run in bounded invocations. Initial combined experiment/contract groups exceeded
the 28-second guard; smaller groups completed. Restricted localhost launches
failed socket binding, and TestClient cases stalled under that restriction;
with local socket access, both launch tests, all 16 B6 tests and the single
OpenAPI check pass. Contract checks completed as 19 + 11 + one; five record-mode
checks pass separately. Tracking's 28 checks include the existing fake-key scan.
Existing Pydantic dependency deprecations remain; no new project warning found.
Ruff check/format, shell syntax, audit row/coverage invariants and exact README
copy checks pass. All 72 original research/prompt file hashes match the B7 entry
snapshot. No dependencies changed. The final audit-only rerun takes under one
second and preserves zero calls. Current-corpus metadata lookup confirms all six
public F5 target records exist and none contains its full hash in passage text;
that observation and corpus hash are saved separately from historical evidence.

Inspected the exact Git index: all 40 staged filenames remain the pre-existing
B6 set; B7 staging was not performed. Only the B7 note append is newly unstaged
in an existing tracked file. New B7 source/test/script/report files are untracked;
raw audit CSV, provenance, summary, lookup observation and logs remain ignored.
The user's two untracked PDFs are untouched. No commit or push was performed.

## B7b inventory — 2026-11-22

| Expected → found | Handling |
| --- | --- |
| B7 audit, exact ledgers and 72-file byte baseline → present | Reuse; no legacy research module edits |
| Existing partition-aware count/lifecycle → present | New v2 subclass reuses both |
| Three test-scoped development F3 aggregates → confirmed | Shared exclusions file; no test population computation |
| Six F5 reference strings → exact frozen human-reviewed claims | Update display wording; saved judgments unchanged |
| Historical runtime → absent | Approved record-level diagnosis; current accepted bundle used for future execution |
| Prior B6 staged edits and B7 additions → present | Preserve; no pushes or live calls |

Part A offline re-score: 122 questions per system; F3 n=12. Fourteen verdicts
change (S7/S8 six F3 and one MH each), all numeric singleton unwrapping. F2 units
are not inferred. All six references exactly match rendered signed-freeze claims.
Existing policy preview selects none. TOOL breakdown has no saved 429/5xx;
malformed/schema-rejected outputs and outside-cohort targets explain the saved
messages. Full changed rows and comparison are under ignored outputs/analysis/b7b.

### B7b implementation and verification — 2026-11-22

Implemented scorer v2/exclusions, separate MLflow scorer-version/variant identities,
v1 supersession tagging after successful v2 upload, default-v2 dashboard selection,
and research-only S7v2/S8v2 modules. The shared RunConfig/API/engine and all 72
original research/prompt files remain byte-identical to the B7 entry baseline.
New variants carry canonical base configuration plus explicit variant tags/hash
and artifact; they are not silently represented as shared serving systems.

All six F5 grading-reference strings exactly equal the rendered signed-freeze
claims. Catalog/findings/handoff now distinguish the human-reviewed reference
from the LLM answer judge. The unchanged policy selects none on re-scored v2
numbers. Nine MLflow plans are ready; no real MLflow upload or supersession tag
write was executed. File-store synthetic tests prove distinct/resumable v1/v2 IDs.

New tiny-fixture tests cover numeric singleton/unit rules and negatives, unchanged
abstention, wrong count/list-typed gold/multi-element refusal, counted-quantity
unit matching, cohort/conflict filtering, direction semantics, unknown/private
comment refusal, cited-comment-first packing, one repair and exhaustion, provider
error non-retry, byte preservation, exact legacy response-key hits, checkpoint/
resume, partial-attempt cost preservation, dry-run backfill and selector v2→v1.
Full research fixture regressions remain unchanged and pass. All **391 collected
cases** are covered by passing bounded invocations (353 pre-existing, ten B7 audit,
27 B7b system/scorer/job tests and one version-selector test). The original two
new UI regressions (selector placement/catalog labels) and fixture Git-provenance
issue were corrected and their affected tests rerun. OpenAPI/local launch tests
passed with localhost socket access. Existing Pydantic/LangGraph dependency
warnings remain; no new project warning was added. Ruff check/format and shell
syntax checks pass. No tests or failure checks were skipped to obtain a pass.

Offline plans: S7v2 focused pilot 21 questions, estimated 58 fresh calls / 417,600
reserved tokens; S8v2 full eligible pilot 122 questions, 274 / 1,972,800. Current
verified cache hits are zero; unchanged routes retain the old provider key and
cache-only replay can credit future complete hits. All jobs cap fresh requests at
25 per quota day with at most 180,000 reserved tokens (10% margin) and retain
partial attempts for cost accounting. No live inference was executed. Holdout
counts F2=0/F3=15/F5=0/MH=0; three families have fewer than five held-out items.
Bounded actual executions here were only offline re-scoring, lookup/plan checks
and synthetic tests. New live system accuracy remains unexecuted/unvalidated.

New B7/B7b files were staged by explicit names to support the existing tracked-
checkout CI test; the earlier B6 staged edits are preserved. The sandbox's first
index write was read-only; the named staging operation succeeded with index-write
access. Raw ledgers, ignored analysis reports, credentials, bundle/models/logs and
the two unrelated PDFs are not staged. No commit/push/publication occurred.
Exact commands, per-stage quota/day bounds, full score/error/reference tables and
all fourteen changed rows are in STREAM_B_HANDOFF.md's B7b section.

### B7 one-day amendment inventory (2026-11-22)

Expected → found: feature/mlops and existing Project root → confirmed; B7b scorer,
variant graphs, bounded runner and tests → present; exact pilot ledgers and audit →
present; exclusion list → present (122 eligible dev questions); legacy byte baseline →
present. Existing staged B6/B7 work and two untracked PDFs preserved.
Read the binding MLOps specs, research status, roadmap and attached decisions before
this amendment. Offline only; no research source edits, remote calls, commit or push.

Question-stated hours rule now reads numeric scalars/singletons as hours only when
explicitly asked. No-unit ambiguity, wrong numbers and incompatible days remain
incorrect. Re-score: 27 changed rows, all explained by normalization rules;
F2 S7/S8 become 7/8. Frozen gold, exclusions and all historical ledgers preserved.

Measured planning/pacing uses reported-call input+output means plus 50%; incomplete
aggregate rows do not contribute a misleading zero-usage denominator. The hard
request gate remains input estimate + maximum output <=7,200. Unknown real usage
still reserves the ceiling; live jobs recheck safe daily remaining tokens before
requests. 25 fresh calls is an invocation cap, with repeated invocations allowed.

Required changed-route scope is 79 questions, 43 carried, 271,770 estimated tokens
including grading: it cannot meet 180K. Explicit optional `--scope priority` defers
32 ordinary tool routes in F1/F6H, reruns 47, carries 75 and estimates
175,706 tokens including six new-answer judge calls. Default scope remains all 79;
no reduction is implicit. No separate S7v2 or holdout run is scheduled.
See B7_ONE_DAY_PLAN.md for tables, exact owner commands and remaining limitations.

Final amendment verification: 403 tests passed in bounded offline modules; Ruff
check and format pass (80 Python files). Targeted 49 scorer/audit/variant tests
were rerun after the scorer guard change. All staged prior work was preserved;
new amendment remains reviewable in the working diff. No remote writes or push.

### B7e inventory (2026-11-23)

Expected → found: original Project / feature/mlops → confirmed; B7b/e v2 graph,
count/history and link/comment tools → present; partial run-cf2c6f2cf859a3c6 →
34 rows (18 new, 16 carried), six new F5 answers present; original byte baseline
→ present. Twelve BadRequest failures had unknown usage; no 429 found in that
quota window. Read research status/roadmap and retained binding MLOps contracts.
Implement new plain-JSON planning and deterministic tools only in v2 modules.
Old ledgers stay immutable; supersession will be recorded in a new resume run.
No live calls, external writes, pushes or delegation are authorized here.

B7e completion: pre-parser fully covers all 47 F2/F3/F4/MH pilot texts (8/12/19/8),
without gold. Native tool generation is removed from new variant execution;
strict JSON planning has one repair, then valid parser/BM25 fallback. Count,
lifecycle, field and link answers are deterministic; common structured answers
use JSON text. Original count/history implementations and S0–S8 byte baseline
remain unchanged. Unknown/private evidence stays refused.

Source scoring (new non-F5 rows, scorer v2): F2 2/4, F3 3/6, F4 2/2, MH 0/0.
F4's repair-error entries did not prevent final correct answers; they are still
superseded per request. Nine source qids are marked superseded in a new sidecar;
source prediction and attempt files are not edited. Ten clean new answers,
including six F5, are preserved; the ordered resume runs 83 questions and carries
29 v1 answers. Estimate/upper: 2/3 fresh calls, 4,704/7,056 tokens with 50% margin.

Final quota reconciliation uses exact-purpose reported input+output usage: nine
unknown native turns at 2,309 plus three repairs at 2,629 = 28,668 reserve.
90,171 reported +28,668 =118,839 accounted; 61,161 remains under 180K for Pacific
2026-11-22 (early Nov 23 Winnipeg). No 7,200 default failed-call reservation.
The per-request 7,200 gate, daily ceiling and 25-call invocation cap are retained.

Exported actual blind 60-item F5 packet, public comments only, stable UUIDs and a
separate mode-0600 key. Import validates complete coverage and one judge/packet,
preserves exact prediction fingerprints and updates catalog text only when the
owner supplies a real judge name. Both backfills accept the same complete file;
dashboard judge/batch separation is fixture-tested. No external judgments exist
yet. See docs/mlops/B7E_RESUME.md for commands and limits.

Validation: 419 tests passed across bounded offline modules (including 66 targeted
variant/audit/judge-selector tests); Ruff check/format pass (87 Python files, including the two new packet CLIs).
Only existing dependency warnings, none from our code. No API/remote MLflow or
LangSmith calls, commits or pushes. Prior staged files and unrelated PDFs remain
preserved; generated packets/analysis are ignored and un-staged.

## B8 — offline results pack (2026-11-23)

Expected → found: original three-source pilot ledgers, completed 122-row router-v2
ledger, imported 60-answer external Reasons verdict packet, two complete dev-only
retrieval summaries, freeze/index metadata and 72 original-code byte pins all
present. Generated outputs/analysis/results_pack/results_pack.md and 27 CSVs;
reproducer and bounded validation script are alongside them. All ten systems use
scorer v2, the same 122 eligible question identities and one external Reasons judge.
Overall averages nine family accuracies equally. Original ledgers/code unchanged;
no live calls, MLflow writes, commits or pushes. Dataset test counts use metadata
only; no test gold is opened/exported. See the report for exact denominators,
usage lower bounds, cache-count granularity and development-tuning limitations.

## B9 — final dashboard and publication commands (2026-11-23)

Inventory confirmed B8 pack and imported judge results, saved MLflow snapshot,
original nine pages and 72-byte-hash baseline. All nine pre-edit AppTests passed;
no page crash was reproduced. Streamlit's torch.classes watcher exception was
reproduced and saved under outputs/analysis/b9/. The new three-tab app reads local
B8 CSVs first and ordinary tabs never import research/PyTorch. The new launcher
disables the incompatible watcher; password and Advanced gates remain in place.

Added route-weighted system_cost.csv (0.573246 calls/question; 914.084918 tokens),
validated/cacheable results_source, final-results dry-run/apply publication and
nine ordered config registrations with idempotent run/version tags. Source names
are Core/Extended benchmark and Natural rewrites. Earlier router results are
filtered before renaming the evaluated router. Old page tests target a regression
harness, not the current user navigation. Default app warm reruns measured ~0.23 s;
a real local Streamlit websocket session rendered seven charts without exceptions.

75 focused tests passed across bounded invocations: final UI/publication/byte pins,
retained dashboard/B5/tracking regressions, scorer selectors, secret guards, and
two real local launch tests. Ruff and format checks passed; only existing third-
party Pydantic warnings. No research/contracts/API/Docker/compose edits, live LLM
calls, DagsHub writes, commits or pushes. Existing display-catalog/verdict edits
were preserved. See docs/mlops/B9_DASHBOARD.md for commands and full scope.

Champion is blocked, not moved: shared RunConfig cannot represent the evaluated
identity/metadata; Runner still builds the earlier graph/tools; API remains a
Phase 0 stub. All three route probes report loader FAIL. Registry stores evaluated
configs as research artifacts and marks serving blocked; it never substitutes
the earlier implementation. Stream A integration and the obsolete Docker startup
snapshot job are listed with exact files/functions in the B9 runbook.

## 2026-11-23 — CI coverage source identity repair

Inventory (expected → found): unchanged 70% gate → CI `test` job;
canonical serving sources → canonical tree plus a second `clean source` tree
reported by pytest-cov's inherited subprocess instrumentation;
current read-only UI smoke test → stale nine-page navigation, now three tabs.
Working tree was clean at entry. No research, shared contracts, API, or CD edits.

Added coverage path equivalence for the clean-checkout fixture. Its subprocess
lines merge into the canonical serving files; no modules are omitted and the
70% threshold stays unchanged. A regression combines distinct executed lines
from the two locations and proves both survive under one canonical filename.
Updated the subprocess UI smoke test to use the committed CSV fixture and assert
three tabs/seven charts without research imports or remote access.

Validation: all seven CI boundary tests pass, including source-path merge and
read-only rendering. Offline tests run in bounded file batches; socket-dependent
FastAPI and Streamlit tests run separately with localhost permitted. Ruff check,
format check, and diff whitespace checks pass. Existing Pydantic deprecation
warnings remain third-party issues. No live services, commits, or pushes.

Final combined result: 431/431 tests passed across bounded invocations;
4,459/5,658 serving statements covered (78.81%), zero temporary duplicate source
filenames, and `coverage report --fail-under=70` exits successfully. Diagnostic
reports are in `/tmp/bugzilla-coverage/final/`; coverage batches used threshold
zero only while collecting partial data, followed by the unchanged 70% gate on
the combined complete measurements. Full Ruff check/format: 95 files pass.

## 2026-11-24 — Generated-report secret scan false positives

Inventory (expected → found): reports only as CI artifacts → `junit.xml` and
`.coverage` tracked; ignore rules → no test-report patterns; scanner → pinned
Gitleaks 8.24.3, default rules and exact fingerprint ignore file. Verified the
two reported junit snippets are `cfg.s5_dossier_budget` and the literal token
counter name `utf8_byte_upper_bound`, not credentials. Added only their exact
commit/file/rule/line fingerprints so historical scans remain usable; no broad
rule/path exclusion. Added generated-report ignore patterns and a regression
that checks reports are ignored while application source remains visible.
Owner must untrack the two reports with `git rm --cached -- junit.xml .coverage`;
this retains local files. No history rewriting or pushes. Gitleaks executable
is unavailable locally, so the actual scanner rerun remains owner/CI validation.

Hosting: current app requires a Streamlit Python server; GitHub Pages supports
static files only. A Pages deployment would require a static results export;
Streamlit Community Cloud can run the app, provided the real results CSVs or
configured read-only artifact access and its dependencies are supplied. No
hosting/deployment or results publication was performed.

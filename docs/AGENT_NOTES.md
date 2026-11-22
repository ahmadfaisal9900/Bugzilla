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

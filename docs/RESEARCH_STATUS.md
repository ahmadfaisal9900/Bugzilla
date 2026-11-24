# Research status

## Current phase

2026-11-23 MLOps integration audit: merged local Stream A tip `3160874` into
`integration/merge-audit` with merge commit `efa8bd5`, preserving B9 and all 72
research hashes. Added Linux launchers, updated B9 script paths, repaired preset
artifact loading and offline environment isolation, and enabled Compose CI smoke.
Bounded fixture checks pass. The evaluated S8v2 champion remains refused by the
shared serving contract; no API parity or promotion is claimed. Full tests,
coverage, image builds and Compose smoke are owner-run gates per the latest
instruction. The interrupted merged run measured 81.05% coverage, not a completed
pass. No push or live service validation. See `docs/mlops/INTEGRATION_AUDIT.md`.

2026-11-22 A4 tracing and feedback: Added sampled serving traces, a durable 150-attempt UTC daily cap, sanitized SDK writes and request-to-trace mapping on `feature/streamA`. Feedback always saves locally and attaches to a traced run when LangSmith is available; failed remote submissions remain pending. The combined regression run passed 134 tests, followed by the final focused API/quota/tracing checks (including the preview-only CLI test). OpenAPI is unchanged. The single authorized live mock question was verified remotely in `ensf621-serving`: one root, 15 child runs, all ten agreed metadata fields and `user_rating=1`. Both live screenshots are in the monitoring guide. Changed-file and all-16-run credential scans passed. No Groq requests were made; the temporary 100% sampling server was stopped. The default remains 20%. No commits or pushes were made.

2026-11-22 A3 quota guard: Added `quota.py` and connected daily 90% request/token thresholds, recent request/token checks, cooldown handling and six-questions-per-minute session admission to the API on `feature/streamA`. Daily totals reuse the research `quota_report()` without changing research code or the provider ledger. Near the thresholds, live questions switch to R0 with local retrieval, sources and an extra explanatory stream status. All 124 targeted quota/API/bundle/Phase 0/research tests passed, including the unchanged OpenAPI snapshot. A fake 91% ledger with the real C1 bundle returned four sources, `degraded=true` and zero LLM calls. These are local per-question estimates, not a guarantee of provider remaining quota or coverage of every tool turn. No live Groq calls, commits or pushes were made. A4 tracing remains outstanding.

2026-11-21 A2 API core: Implemented the authenticated `/v1` API on `feature/streamA`, with startup bundle validation, four-runner cache, serialized worker-thread inference, SSE, published MLflow preset caching/YAML fallback and local SQLite feedback. All 108 targeted API/bundle/Phase 0/research tests passed; the real app's OpenAPI exactly matches the unchanged Phase 0 snapshot. A localhost run using the real C1 bundle and mock provider returned sources and the required stream order, also checked with `curl -N`; the seeded local MLflow store supplied two published presets and its synthetic champion. No Groq requests were made. The quota route and basic request/cooldown hook exist; A3 token/session guards and R0 degradation, and A4 tracing, remain outstanding. No commits or pushes were made.

2026-11-21 A1 serving bundle: Added a copy-only builder, cached bundle loader and focused tests on `a/serving-bundle`. The local real bundle was built and checked with S1/R1 and the mock: 3,000 bugs, 299 text-only development examples, real Firefox sources, four status events and no errors. The available runtime has C1 only; C0/C2 remain missing, and strict `--require-all` refuses that incomplete corpus set. No real index or model was regenerated. The builder rejects test/gold file paths and the loader opens DuckDB read-only. The initial combined bundle, Phase 0 and research regression check passed 86 tests. No live API requests, commits or pushes were made. See `docs/mlops/STREAM_A.md` for commands and the remaining corpus limitation.

2026-11-21 reviewed development pilot: The user confirmed completing manual review of the 125-question run. All 358 required review rows and 86 answer grades passed import validation. A verification pass corrected two PDF explanation grades to accept an explicit reason in the exact cited comment, resolved one remaining evidence decision, and updated two contradictory notes. The original export is preserved; `review_verification.json` records the corrections and the user attestation separately. All three collections now report REVIEWED. The main page is `outputs/evaluation/phase11/pilot125/START_HERE.html`. No prediction ledgers changed and no model requests or locked-test runs were made. Forty targeted evaluation tests passed.

2026-11-19 cleanup: Removed the retired generated-question sample builder, its wrapper, tests and separate guide. The official-data verification and history adapter remain in `evaluation/shared_source.py`; prepared data and saved prediction provenance are preserved. Normal official-data evaluation and score-only runs now generate the combined review page and CSV automatically. Those two generated files are explicitly shareable in Git. README documents opening the local page, rebuilding it and importing decisions. No evaluation or tests were rerun for this cleanup, as requested.

2026-11-19 completed pilot collection: All 720 answer slots are resolved for the fixed 80-question development selection across S0 through S8. Human review remains pending: 81 answer decisions within 306 evidence review responses. The single `outputs/evaluation/phase11/START_HERE.html` page shows plain answers, references, source excerpts, grading status and review controls. `REVIEW.csv` is the combined readable alternative. Review import validates content and IDs, preserves earlier queues, and updates scores without model requests. The view was rendered in Chrome; scoring and review import tests pass. This is development evidence, not a completed hidden test or fully human-reviewed result.

2026-11-19 routing fix: The 80-question pilot stopped after 305 resolved answers when S8 emitted the invalid route `abstain`. Groq schema rejections now enter the bounded model repair path, and S8 records routing failures instead of allowing an exception to abort the graph. The one repair budget is shared with answer formatting. Targeted tests cover successful route repair, two invalid routes, transport errors and budget sharing. The 305 answers were validated and copied with explicit source provenance into a new prediction version; originals remain unchanged. The pilot still needs completion and human review.

2026-11-19 pilot update: The requested comparison now selects 80 existing official development questions: all 34 Phase 5 questions, 10 natural rewrites and 36 v3 questions (17 KI, eight MH and 11 F6H). All nine S systems reuse their existing matching predictions. The evaluation worker rotates Groq credentials 2, 3 and 4 with separate quota ledgers and preserved legacy accounting; model and answer rules remain fixed. S4 calibration is complete on the 350-question development retrieval roster. The previous full-roster job stopped on a token limit. The pilot is not a completed or human-reviewed result yet. See `docs/PHASE11_EVALUATION.md` for the resumable command.

2026-11-18 official-data follow-up: The committed Phase 5, natural and v3 development releases contain 34, 51 and 265 questions. Shared-source compatibility checks passed for all 350, including public record hashes, aggregate counts and population scopes. Reconstructed history matches the original summary: 50 parsed histories, 884 changes, 17 reopen events, 13 valid first-FIXED cases, one same-time group and seven source differences. Corrected a Windows timezone error in the history adapter and applied the common recorded one-repair rule to native tool-output rejections. The official development workflow is calibrating S4 before live inference. This uses a reconstructed runtime, not the owner's exact index; no final accuracy or locked-test result is claimed. Command: `scripts/phases/run_phase11_evaluation.ps1 --shared-source --enable-llm --max-requests 900`.

2026-11-18 follow-up: The evaluation defaults to S0 through S8, with Windows and Bash wrappers, portable file locking and paired cluster tests with Holm correction. The delivered 185-question source sample was rebuilt and checked locally. The active stricter variant has 165 verified questions across nine families, with question subjects in all three development partitions; three multi-hop linked targets cross partitions and remain diagnostic. Four explanation references need human review. A local index contains 14,191 chunks with zero reported truncations; S4 was calibrated on development retrieval scores before inference. The actual Groq run has started and is not complete. The 12-question mock fixture remains only a unit check. See `docs/PHASE11_EVALUATION.md`.

2026-11-18: Phase 11 adds a scorer for saved S-system predictions and a thin runner around the existing answering CLI. A 12-question synthetic fixture checks 60 mock answers, report generation and human-review export. This is an offline workflow check, not an executed model comparison. Exact frozen inputs, indexes and modern prediction outputs remain absent from this checkout. See `docs/PHASE11_EVALUATION.md`.

Phase 8 v3 is frozen. Saved Phase 9 build/dev runs are COMPLETE and select R7b/C1. Task 3 / Phase 10 answering graphs are implemented; fixture validation and owner-terminal pilot are tracked in docs/ANSWERING_SYSTEMS.md. No answer comparison is claimed. Final Phase 5/v3 frozen benchmark files and approved natural rewrites are packaged for Git sharing; runtime databases/indexes/caches and prediction ledgers remain ignored. See README section 5.

**Phase 3B VERIFIED; Phase 4 PILOT VERIFIED; Phase 5 FROZEN.** The user-run generation `run-65c5be3381f66811` contains 169 benchmark QIDs and 6 supplemental challenges at seed 317, with 592 development / 2,408 test population IDs. The verified freeze `d8ef826fbeb90d13` has 34 dev and 135 test benchmark questions plus six supplemental challenges. All seven frozen manifest artifact hashes matched a read-only check. No final method evaluation is claimed. See `docs/PHASE05_BENCHMARK.md` and `docs/AGENT_NOTES.md`.

The partner review bundle is explicitly tracked under `outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811/`; setup and browser review instructions are in `README.md`. At packaging on 2026-10-23 it has six recorded approvals and 58 remaining of 64 required reviews. These are signoff-sheet records, not yet transferred to the original generation queue or verified by the freeze validator. The original pre-review backup is preserved. Only the review interface, queues and small provenance manifest are shared; raw/full comment packets, databases and other outputs remain ignored.

On 2026-11-02 the local signoff sheet contained 36 recorded approvals and 28 required rows pending, including 22 F5 rows. A local ignored suggestion file supplies 19 source-attributed drafts for those pending F5 items and flags the other three for source checking or rejection. These are Automated recommendations, not human decisions; the human must verify and save each accepted correction. The original review queue and earlier signoffs were not changed by preparing these suggestions.

Later on 2026-11-02 the signoff sheet contained 40 approvals, 21 corrections and three pending required F5 rows. Per D-043, the UI and validator now support a human-confirmed, source-scoped insufficient-evidence answer for F5, preserving the question rather than requiring rejection. No pending row was automatically approved or reclassified. The exact existing run remains compatible only under the fingerprinted review-only amendment; full freeze still independently recomputes candidate gold and requires actual human signoff. F5 model abstentions need human response review. Fixture tests passed; no real freeze or model evaluation was run.

## Completed

- Phase 0/1 preserved the existing Project root and origin. Earlier commits: `e706e3f`, `35d32c7`.
- Phase 2 user-run audit verified; see `docs/DATA_AUDIT_SUMMARY.md`.
- Phase 3A full user-run QC verified at `outputs/data_exploration/run-20261022T015655Z-1139511`; see `docs/PHASE03A_QC.md`.
- Phase 3B full input: 736,253 source rows; 196,633 unique canonical bugs; 419,458 canonical comments; 308,132 explicit recorded links; zero source quarantines/orphans. 28,533 metadata duplicates, 30 conflicting metadata variants, 91,599 Part 1 duplicate comments; Part 3 adds 11,057 comments. Frozen hashes/counts match 3A; Part 2 duplicate and metadata-all near-repeat excluded.
- Firefox product: 25,025 distinct bugs. Seed 317 sample contains 3,000 unique Firefox bugs and represents all 18 eligible status/resolution groups; includes 757 open/reopened bugs and 2,539 zero-comment bugs.
- DuckDB, Parquet, aggregate QC, sample manifest and 20 sanitized examples are in ignored run outputs. All 19 manifest-listed artifacts exist at recorded sizes with SHA-256 fields. No private/unknown-privacy bodies appear in comments/search documents.
- Base `field_changes` stays empty; its 196,633 first-FIXED durations remain UNKNOWN. The separate verified Phase 4 pilot `cohort-8bb3150d29a598d8` has 50 parsed histories, 884 changes, 13 first-FIXED cases / 37 UNKNOWN, and 17 REOPENED entries. Six overlay hashes and 147 cached response hashes/identities match; no new requests were made.
- Phase 5 v1.1 fixes Python 3.9 SQL timestamp formatting; 6 generation fixture tests and bounded real input verification pass. The user subsequently generated 169 candidates and 6 challenges. The original pre-review backup has SHA-256 `6d2030a6fa0d4abba1a4a6ab09a68465a6f12beb31e9056056ca67b807cb430c`; the active queue now contains transferred human decisions. Candidate/challenge SHA-256 values are pinned in the assisted review protocol. Ten fixture tests cover read-only assisted validators and privacy packet helpers. The benchmark was subsequently frozen as noted above.
- Phase 5 pins that pilot and the verified 3B manifest. Before metadata/partition filters, 9 first-FIXED cases remain after excluding source differences and same-time ambiguity. The user-run candidate set is 169 questions + 6 challenges at seed 317; 180 remains a target, not an achieved count. F5 still requires human rationale review.

## Evidence gaps and limits

- **F2:** validated event answers exist only for eligible pilot cases. Base-only durations and missing transitions remain UNKNOWN; historical snapshot state and original data availability are unverified. Never infer from latest-change time.
- **Paper/data reconciliation:** the paper's 119,585 curated reports and 10,351 quality-selected reports are distinct populations from the 196,633-unique-bug broad metadata base. Local schemas and inspected upstream code have no ordered field-change events; paper-reported October 2024 coverage does not certify every CSV field's exact snapshot time. See `docs/PAPER_DATASET_RECONCILIATION.md`.
- **F4:** parsed snapshot links only; historical validity, past target status and complete link coverage need enrichment. 79,350 recorded targets are outside this canonical bug set.
- CSV source event times parsed, but original snapshot/export date is UNKNOWN (`snapshot_as_of_utc` NULL). Phase 3A observation time and Phase 3B ingestion time are separately recorded; this export cannot recreate a historical snapshot.
- Source redistribution/license review remains unresolved. Private/unknown privacy comment bodies are withheld; local public text can still contain personal data. Do not publish/redistribute derived text without review.
- No genuine historical source-time T0/T1 is verified. Phase 4 selects a controlled base-corpus/API-refresh comparison. The frozen benchmark has 169 questions, below the 180 target; developer-hours cannot be inferred from elapsed days.

## Environment and repository

- Root: `/home/ict317/master's/ENSF 621/Project/`; `origin` remains `https://github.com/ahmadfaisal9900/Bugzilla.git`.
- Inputs remain read-only in ignored `Dataset/`; generated databases, Parquet and reports remain ignored under `outputs/`, with explicit `.gitignore` exceptions for the small partner-review bundle and the 26 final evaluation release artifacts (about 2.7 MB).
- Free DuckDB 1.4.4; no paid API, PyArrow, crawler, proxy rotation or MongoDB job.
- Full normalization used a 512 MB DuckDB budget; elapsed time was about 8m41s. Output database is about 1.89 GB. Sampling is Firefox-product only; that is not all Firefox engineering.

## Next gate

Ahmad's tracked signoff sheet has decisions for all 64 required rows (40 approvals and 24 corrections). These decisions were transferred and the owner ran the freeze validator. The freeze report records 34 development and 135 test questions, plus six supplemental challenges.

Phase 6's model-free code (answer contract, scorer, M3 SQL, BM25) and local M0/M1 generation are implemented and fixture-tested but have not run with a real model or real data. No model is chosen; M2 and the study's M3 intent parser remain unimplemented. No method result exists. See `docs/PHASE06_METHODS.md`. The user authorized provisional acceptance of the remaining 31 answers for development only on 2026-11-02; this uses `--unfrozen-dev-smoke`, changes no official reviews and is not a freeze. The locked test stays closed until the freeze.

The retrieval extension has user-run v1 and v2 development retrieval outputs and opt-in local inference code. LLM inference and a complete QA comparison are not verified. The original Phase 5 freeze and separate expanded-bank seal gate test access. See `docs/EXTENDED_EVALUATION_RUNBOOK.md`.

The user-run v1 development retrieval completed, but its F1-heavy selection, 564 truncated chunks, 349/349 M3 `NO_INTENT` outputs, and 341/349 identical hybrid/hierarchical top-five lists required correction. The user subsequently ran v2: 693 selected questions, 14,443 indexed chunks with zero reported truncations, and 51 reviewed natural development rewrites retrieved. The saved v2 M3 development results still have 31 F3 `NO_INTENT` cases. A parser correction and separate resumable re-evaluation are fixture-tested, awaiting the user's run. No LLM answer comparison is verified. See `docs/EXTENDED_EVALUATION_RUNBOOK.md`.

On 2026-11-11, 64 genuine source-review decisions (40 approvals, 24 corrections) were transferred from the signed sheet into the original generation queue after row-level checks; a pre-transfer backup and audit record are retained locally. The owner subsequently signed and ran the freeze validator. Expanded test has separate seal requirements.


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

Task 2 now wraps existing retrieval behind R1–R7b, with versioned C0/C1/C2,
source-record qrels, resumable top-50 caches, locked-test gates, cluster
bootstrap/Holm and preregistered development selection (eligible cells n>=10).
No full build/evaluation or live R7 was run by the agent. The later owner-run
manifests now report COMPLETE (6,300 offline and 4,200 R7 result rows for 350 dev
questions). The existing selection records R7b/C1; Task 3 reuses it and verifies
its source summary hashes at runtime. This is a retrieval handoff, not an answer
quality result. Phase 10 graphs await the owner pilot in `docs/ANSWERING_SYSTEMS.md`.

Phase 10 / Task 3: **FIXTURE_TESTED; AWAITING_OWNER_PILOT**. Nineteen new
LangGraph/tool/trace/upload/mock tests and 11 existing provider tests passed.
No answer scoring/evaluation or live request was run. Predictions and traces
must be inspected after the bounded owner pilot before proceeding to bulk dev.

Owner Phase 10 pilot is PARTIAL: one S0 success, then Groq rejected a model's
implicit browser tool call. No external tool ran. A bounded repair-classification
fix and explicit no-tool JSON policy are fixture-tested; retry remains owner-run
with the same pilot command, in a new versioned output. No full pilot success or
answer-quality result is claimed.

2026-11-13 pilot inspection: latest v3 pilot is still PARTIAL. S0 completed 21
items (all abstained); S1 reached two unique items and stopped because a valid
source label C1 was treated as an unknown chunk ID. Its raw FIXED claim for bug
1861451 matches the mapped public metadata. Exact provided-label normalization
is now implemented with raw-output audit preservation. S2–S8, Phase 5 and natural
pilots remain unrun. Do not launch daily batches before the fixed pilot completes
and its saved results are reviewed. No answer accuracy/complete success claimed.

Owner requests minimal live wiring check to conserve API calls. Use --qid
v3_03f2ea205396f26d0fef9e5f with --run-tag smoke-one and --max-requests 12 across
S0–S8, per ANSWERING_SYSTEMS.md. Resume stays on this fixed question; cached
successful calls are reused. Larger three-per-family/dataset pilot is no longer
a prerequisite for initial wiring validation. Live smoke and answer-quality
verification remain pending; larger daily batches are not yet approved.

2026-11-13 quota diagnosis: active model is Groq openai/gpt-oss-20b, whereas the
supplied limits row names 120b. Repeated 429s are provider quota blocks; the exact
old token/request dimension and wait were discarded and remain unverified. Failed
429 prompts are not response-cached; combined cache_hit included retrieval.
Offline quota diagnostics and per-model server cooldown persistence are now
implemented; future responses can expose exact token quota/retry metadata without
additional diagnostic calls. Request limits alone do not reserve server tokens.
Do not launch bulk batches or assume a reset time; inspect the active model's
quota and use only the fixed smoke after its budget is available.

Token-efficiency profile: --compact-prompts is opt-in, fixture-tested, and uses a
separate shared answer-v2-compact prompt/version. Measured saved-smoke prompt byte
reduction is 28–41% without removing evidence text. Actual token savings and live
answer equivalence remain unverified. Default v1 and its response-cache keys stay
compatible; do not restart cached work while token-limited. New profile needs a
single-question smoke after the active model's quota is available.

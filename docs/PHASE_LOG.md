# Phase log

2026-11-02 — F5 insufficient-evidence amendment D-043: the user requested retaining questions whose cited comments do not establish the requested reason. The UI can record a reviewer-confirmed, source-scoped `unanswerable` correction with `source_checked=YES`, `rationale_present=NO` and the cited evidence IDs. Freeze validation checks the exact typed schema and review confirmation, labels and counts F5 insufficient-evidence cases separately, and preserves question IDs/splits and original candidate artifacts. A fingerprinted review-only compatibility check allows the existing run only with unchanged generation source/dependencies; full freeze still recomputes the candidates. F5 abstention outputs require human response review. Five focused fixtures, seven Phase 5 synthetic tests including freeze, and 23 Phase 6 fixture tests passed. The local sheet had 40 approvals, 21 corrections, and three pending rows before this amendment; no human decisions were changed by the agent and no real freeze or model job ran.

2026-11-02 — F5 review usability: inspected saved public-comment packets for the 22 F5 rows still pending in the local signoff sheet. Created 19 concise source-attributed correction suggestions and flagged two cases for further evidence and one for possible rejection. The interface displays these suggestions separately from immutable candidate gold, pre-fills them only for an explicit human correction, and prevents accidentally approving the old fragment while a suggestion is displayed. Suggestions remain ignored/local; no human decision or original queue field was changed. Bounded checks passed for packet/evidence hashes, parent/challenge suggestion equality, server output, browser correction behavior, and the existing signoff queue integrity check. No benchmark freeze or human verification is claimed.

2026-11-02 — Sample-data handoff support: added `scripts/run_phase05_share_sample.sh` and standalone exporter for the frozen 3,000-bug membership and unchanged 50-bug API sidecar. Saved metadata confirms all 50 history IDs belong to the 3,000 sample. The ignored archive will contain a subset DuckDB, byte-identical API DuckDB, sample/history provenance, per-file hashes and recipient setup/query instructions. No data or API collection was rerun. Four tiny offline fixtures passed (filtering, public-body guard, source/overlay checksums, limited preview, table/archive resume, changed-input rejection); real-input metadata-only dry-run resolved 3,000 sample IDs and 50 history IDs. **The real export/archive has not been executed or verified.** This subset cannot replace the full pinned canonical database in freeze verification. No source files, review decisions or method results were modified.

2026-11-02 — Phase 6 development continuation: the user authorized provisional acceptance of the 31 remaining answers for development only. Added local Ollama transport, M0 without records, M1 with bounded BM25 evidence, model-call caps, prompt/usage/latency traces, and model-aware resumable development runs. Official review decisions remain unchanged and the benchmark is not frozen. All 34 targeted method/generation tests and 15 Phase 4/5/scaffold regression tests pass on tiny fixtures and fake model replies. Real-input dry-runs correctly report missing saved data with zero model calls. No real model, embedding or evaluation job ran. See `docs/PHASE06_METHODS.md`.

2026-10-23 — Phase 5 partner handoff: README now covers fresh-clone setup, the local review UI, decision semantics, 64 required source reviews, safe partner synchronization, and the owner-only freeze gate. `requirements.txt` pins the existing DuckDB dependency. Five named small review files are allowed under `outputs/`; datasets, API caches, full comment packets and all other generated outputs remain ignored. Packaging preserves all 175 qids, immutable evidence/source hashes, the pre-review backup and six existing recorded approvals (58 required pending). The browser now exposes saved compact evidence and exact source hashes in technical details. `.gitattributes` preserves both CSVs byte-for-byte across platforms, including their intentional CRLF endings. Bounded checks passed: isolated two-row review fixture (source/rationale guards, backup and immutable fields), browser script syntax, current queue `--check`, and packaged file hashes. This does not transfer signoffs, validate the answers, or freeze the benchmark. The planned `docs/Project Report.pdf` is documented as forthcoming.

| Phase | Scope | State | Acceptance / next gate |
|---|---|---|---|
| 0 | Project structure, Git safety, and research workspace | Commit `e706e3f`; present in origin history | Required skeleton and tracking docs exist; roadmap unchanged; datasets and generated artifacts ignored; bounded structure checks passed. |
| 1 | Consolidate foundation into existing repository | Commit `35d32c7`; present in origin history | Existing `Project/` root and remote retained; no nested project Git root; roadmap and Dataset preserved. |
| 2 | Streaming data audit and 20-row fixture | Full user-run audit verified; summary in `docs/DATA_AUDIT_SUMMARY.md` | Exact counts, joins, timestamp rates, NUL handling, and Parts 1/2 SHA-256 verified. Rights/privacy and event-history semantics remain unresolved. |
| 3A | Deeper BugsRepo exploration and chunked profile | Full user-run profile verified | Reviewed `run-20261022T015655Z-1139511`: exact counts/hashes, Part 2 duplicate, Part 3 additional records, FIXED-selected comments and broad metadata negatives. See `docs/PHASE03A_QC.md`. |
| 3B | Canonical DuckDB/Parquet normalization and sampling | **VERIFIED**; user full run `run-20261022T023542Z-1182018` | Manifest COMPLETE; identity `0454ce48d6ed7a52973aea5474bee18304e33b65970c2c8c69dccdd0a630b663`; 736,253 source rows account exactly to 196,633 bugs / 419,458 comments; all input hashes match 3A; 3,000 Firefox sample covers all 18 eligible status/resolution strata. See `docs/PHASE03B_NORMALIZATION.md`. F2/F4 remain limited without API history. |
| 4 | Evidence-gap plan, selective public API enrichment and temporal validity | **50-BUG USER PILOT VERIFIED** | Completed cohort `cohort-8bb3150d29a598d8`: 50 histories, 884 changes, 13 first-FIXED cases, 147 successful HTTP attempts. Six overlay hashes and raw response hashes/parsing verified as Phase 5 prerequisite. Historical API link coverage is zero; source snapshot time UNKNOWN. No larger study run claimed. See `docs/PHASE05_BENCHMARK.md`. |
| 5 | Deterministic benchmark, assisted review and freeze | **USER CANDIDATES GENERATED; ASSISTED PREP IMPLEMENTED; HUMAN REVIEW PENDING** | Run `run-65c5be3381f66811`: 169 benchmark QIDs + 6 challenges, seed 317, population 592 dev / 2,408 test. The 180/36/144 counts remain targets, not achieved. Read-only packet generation and family validators are fixture-tested; full packet scan, F5 judgments, human signoff, freeze and evaluation remain pending. |

Phase 3A full outputs remain ignored under `outputs/data_exploration/`; earlier smoke plots remain prefix-only evidence. Phase 3B fixtures write only synthetic data under ignored normalization outputs. The user full Phase 3B run is VERIFIED. Phase 4 selected a controlled base-corpus/API-refresh comparison, but no source-time T0/T1 snapshot is verified. The user completed the API pilot. The agent made no new live request; no model evaluation or phase beyond benchmark construction has started.

Phase 3B fixture suite: 14 total repository tests passed in about seven seconds, including five normalization tests. Retained synthetic example output: `outputs/normalization/phase03b/synthetic-fixture-20261022T023408Z/run/` (24 bugs / 7 comments / 20 anonymized examples; not corpus counts). Validation covers multiline CSV, NaN IDs, timezone normalization, malformed timestamps, explicit FIXED/reopening/DUPLICATE/INVALID events, duplicate exports/content variants, private/unknown-privacy withholding, deterministic sample, interrupted and completed resume, output hashes and Parquet round trips. History injected by tests is synthetic only. Free pinned DuckDB 1.4.4 is a new local dependency.


### Phase 3B terminal-run evidence (2026-10-22)

Manifest created `2026-10-22T02:35:42.410317Z`, completed `02:44:22.980432Z`. Full unlimited source files: metadata 225,196 rows (`196,633 NORMALIZED`, `28,533 DUPLICATE`, `30 CONFLICT_VARIANT`, zero quarantined); comment Part 1 500,000 (`408,401 NORMALIZED`, `91,599 DUPLICATE`); Part 3 11,057 (`11,057 NORMALIZED`). Source records total 736,253; exact hashes/sizes match frozen 3A; zero orphan source comments. Part 2 duplicate proof excluded its 500,000 rows; metadata-all near-repeat excluded. No optional quality subset imported.

Canonical counts: 196,633 bugs; 419,458 comments; 308,132 parsed explicit links (blocks 97,423; depends_on 86,615; duplicate_of 18,796; has_duplicate 17,348; regressed_by 15,518; regresses 12,991; see_also 59,441); 79,350 targets outside corpus; 0 field changes. All 196,633 fix durations UNKNOWN; no first-FIXED timestamp. 25,025 distinct Firefox-product bugs. Sample: seed 317, target/members 3,000, all 18/18 eligible Firefox status/resolution strata; 757 open/reopened and 2,539 with no comments. Comment text availability: 414,378 AVAILABLE, 5,080 EMPTY, zero private or unknown-privacy rows, zero withheld-body search documents. Twenty anonymized examples contain only sanitized structural fields. No actual DB/Parquet was rehashed in-session; each of the 19 manifest artifact paths exists at its recorded size with a SHA-256 field. The small manifest SHA-256 is `3c924a3741c75230d3a307b7335814f7075108528eebc43a50e2f827bb5daccf`.


## Phase 5 — implemented; awaiting terminal generation and human review

The previously stale Phase 4 status was resolved by bounded offline inspection of the completed user pilot `cohort-8bb3150d29a598d8`. All six small overlay artifact hashes and 147 cached response hashes/identities match; histories and metric parsing replay exactly; current metadata differences and 884 event hashes match DuckDB. Observed: 50 successful histories/metadata, 13 first-FIXED histories, 37 UNKNOWN, 17 REOPENED events, 7 source/current field differences, one same-time group, zero rejected/future events, zero configured historical API links. After conservative source/same-time exclusions, 9 first-FIXED cases precede sampling/metadata conflict checks. The 1.89-GB base was not rehashed in-session.

Phase 5 adds deterministic generation, signed-review preparation and versioned freeze scripts. Target 30/family, development 6/family and test 24/family remain conditional; actual real candidate counts are AWAITING_USER_RUN. All retained F5 and challenge gold require human source review. Fixture tests cover 20 synthetic parent bugs; they do not establish corpus coverage or human labels. No live API/model request or full benchmark job was run. See `docs/PHASE05_BENCHMARK.md`.

Phase 5 bounded check: 5 tests passed in 8.4 seconds. Synthetic fixture only: 20 parents, 30 candidates (5/family), 6 development / 24 test, and 6 challenge items. Real generation and human sign-off remain pending.

Phase 5 v1.1 correction: the first terminal generation failed because DuckDB `+00` timestamp strings are rejected by Python 3.9, producing false creation-time differences. SQL now emits ISO UTC explicitly; no discrepancy check was bypassed and no source pin was changed. Added a current-metadata-response fixture and actionable missing-generation errors. In `iqfm` Python 3.9.25, all 6 generation tests passed in 11.1 seconds and bounded real input verification passed with unchanged counts (50 histories / 884 changes / 13 first-FIXED / 9 after exclusions). At that point candidate generation was pending; the user's completed run is recorded below. Failed run directories are preserved.

### Phase 5 assisted review preparation (2026-10-23)

The filesystem now contains the user's completed candidate run `run-65c5be3381f66811`: 169 candidate QIDs, 6 challenges, seed 317, and the unchanged 592/2,408 population partition. `review_queue.csv` and the existing pre-review backup are byte-identical at SHA-256 `6d2030a6fa0d4abba1a4a6ab09a68465a6f12beb31e9056056ca67b807cb430c`. Candidate and challenge files hash to `3e3d0d8002c5fce2ef075fb8ded5611318954d2ffc808efb9994f9bdf39dfa38` and `f668c668b96a1b16ec909fe37f4518d71e1c527cd7a7965f5b16e4a6a365f6b6` respectively. Source pins and generation artifacts are unchanged.

Added `src/bugzilla_qa/benchmark/assisted_review.py` and `scripts/run_phase05_agent_review_prep.sh`. It checks canonical F1 fields; replays saved public Phase 4 histories and independently recomputes UTC F2 durations; verifies F3 SQL against a Python distinct-ID set over exact 592/2,408 partitions; checks complete explicit F4 relations; and bounds F6 claims to specified evidence. It emits local sanitized F5 full-comment/context packets with advisory flags. It never edits the queue, signs a review, calls an API/model, or freezes. Dry-run/help and ten small fixture tests passed. No full real packet run or judgment of the 31 F5 questions was performed. See `docs/PHASE05_ASSISTED_REVIEW_PROTOCOL.md` for the editable CSV and signoff schema and Prompt 5B.
# Evaluation extension — implementation, awaiting terminal run

2026-11-11 — V2 user outputs: 693 selected (F1 375, F2 6, F3 102, F4 135, F6 75), 14,443 dense chunks and zero reported tokenizer truncations. The separate reviewed-natural track has 110 approvals, of which 51 development questions completed retrieval; these are known-citation proxies, not answer accuracy. Existing v2 M3 development output has 31 F3 `NO_INTENT` cases due to a scope-recognition mismatch. The parser now recognizes the explicitly stated seed-317 Firefox partition; a tiny DuckDB fixture verifies partition-scoped counting and rejects mismatched scope. The separate versioned M3 rerun is awaiting the user. Sixty-four existing signed Phase 5 reviews were copied to the original queue with backup and local audit; global signoff and validator freeze remain pending.

Added independent source-backed factual-bank generation, pending natural/F5 review exports, source-only corpus, SQLite FTS5, local FAISS embedding shards, RRF and optional cross-encoder and parent-first retrieval, known-citation qrels/metrics, and opt-in local Ollama scoring. Synthetic/mocked tests and a three-bug smoke passed for the available stages. Dense model loading and the full workflow remain unverified because FAISS/Sentence Transformers were absent; no download or full evaluation was performed. The original Phase 5 freeze remains a test gate. See `docs/EVAL_EXTENSION_RUNBOOK.md`.
# Extended evaluation repair — awaiting terminal run

Task 1 v3 implementation: original freeze d8ef826fbeb90d13 is confirmed (169 primary questions: 34 dev, 135 test; six supplemental challenges). The owner Gemini ping returned 404. Added explicit model overrides, budgeted one-page model listing, SDK retry suppression, versioned v3 generation, independent SQL/evidence checks, review exports and freeze integration. Tiny DuckDB/MockProvider fixtures exercise interrupted resume, private/unknown comment exclusion, secret redaction, hashes, numerical checks, original-artifact immutability and human-review gates. No full source job, embedding build or network request ran in the agent. Real v3 counts and freeze await the user. See BENCHMARK_V3.md.

Final Task 1 offline acceptance: 32 tests passed in under five seconds; shell syntax and diff whitespace checks passed. Freeze checks immutable review content and can recover a promoted release whose pointer write was interrupted. All long source hashing, embeddings, Gemini generation and full verification are user-terminal jobs. No successful live ping or real v3 generation is claimed.

Audited the saved v1 aggregates, preserved its outputs and implemented a separate v2 selection, source-scoped M3 parser, tokenizer-aware chunks and bug-first hierarchical search. The original signoff has not passed freeze validation. Fixture tests and a bounded source/tokenizer check only; no full v2 job or LLM request was run. See `EXTENDED_EVALUATION_RUNBOOK.md`.

2026-11-12 — Added Groq transport and provider factory; default openai/gpt-oss-20b, GROQ_API_KEY, strict JSON schema, provider-isolated reservations/cache, numeric Retry-After and safe resume. Gemini failures remain archived; original benchmark unchanged. Offline tests only; user-run Groq availability/generation pending. See BENCHMARK_V3.md.

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

2026-11-12 — Task 2 / Phase 9 implementation: corrected v3 handoff docs before
code and preregistered selection before results. Wrapped existing lexical/dense/
RRF/hierarchy/reranker code, added graph expansion and shared-provider R7,
versioned token-budgeted corpus variants, evaluator caches, cluster bootstrap/
Holm and selection. Full runs await the owner terminal. No frozen/source file
was modified; no live request or full index/evaluation was executed. See
RETRIEVAL_V3.md for exact commands and acceptance scope.

Task 2 validation: 38 offline fixture/mock tests passed in about four seconds;
all 22 original/v3 frozen artifact hashes still match. Shell syntax and CLI
help checks passed. This verifies implementation only, not real retrieval scores.

2026-11-13 — Task 3 / Phase 10 implementation: inventoried actual Groq provider,
R7b/C1 selection, completed owner-run retrieval manifests and immutable freezes.
Added shared LangGraph S0–S8/ORACLE, native tool transport on existing provider,
read-only scope-aware tools, public-context packing, opt-in sampled LangSmith,
resumable versioned prediction ledgers, offline tau suggestion and opt-in dev
reference upload. No scoring, live requests or full agent-side run. Existing
retrieval/source/frozen artifacts and old M3 implementation are unchanged.

Task 3 validation: 19 new offline tests passed in about four seconds, including
three questions per arm written through the real runner to fixture JSONL ledgers;
11 existing shared-provider tests also passed. CLI help, module compilation,
shell syntax and whitespace checks passed. No live API/trace/upload or real
answer run occurred. Frozen/source paths have no tracked diff. Owner pilot is
still required; implementation is FIXTURE_TESTED / AWAITING_OWNER_PILOT.

2026-11-13 — Owner Phase 10 pilot stopped after one successful S0 row and a
Groq HTTP 400 rejected implicit browser.run call (two actual requests). No browser
call was executed. Corrected provider classification so no-tool tool_use_failed
responses use the existing single JSON repair, rather than stopping as transport
errors. Plain Groq JSON explicitly disables tools; shared prompt and repair turn
forbid implicit browser/search. Native allowlisted S7 functions remain enabled
only on its native tool turns. Old partial outputs are preserved; changed prompt/
code produces a new prediction identity. Offline mocks check counted repair,
request-cap enforcement and non-execution of the rejected payload. No live retry.
Validation: 21 answering fixture tests and 11 shared-provider tests passed; no
live API call or source/frozen artifact change. Retry behavior is implemented
and mock-verified, not yet verified against a new owner-run provider response.

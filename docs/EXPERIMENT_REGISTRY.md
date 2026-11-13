# Experiment registry

No experiments have been run. Planned comparisons are mandatory M0 closed-book, M1 BM25 RAG, M2 hybrid RAG, and M3 parameterized SQL; M4 small-graph retrieval is optional. The generated 180-candidate target, F1–F6 families, and v0/v1 temporal comparison are documented in `docs/reference/research_roadmap.tex` and `configs/study.yaml`.

| Experiment ID | Method | Dataset snapshot | Configuration | Seed | Status | Results path |
|---|---|---|---|---|---|---|
| — | — | — | — | — | No registered runs | — |

Add a row only after a user-run job has been inspected. Do not enter projected results as observations or mark a run successful before validating outputs. Keep generated results and logs outside Git.


Phase 5 has 169 generated candidates and 6 supplemental challenges, with human review and freeze pending. Phase 6's SQL/BM25/scoring groundwork and local M0/M1 generation are implemented and fixture-tested; no real model run is registered. The user's provisional acceptance of pending answers permits development smoke checks only, never reportable study results. Actual retained counts and the frozen test checksum must be copied from the inspected freeze report before registering M0–M3. Template IDs, typed gold, canonical SQL and review sheets are evaluator-only; tune on development questions, then freeze before test inference. See [PHASE06_METHODS.md](PHASE06_METHODS.md).

Protocol amendment D-043 allows human-confirmed F5 insufficient-evidence gold when the complete cited comment contains no requested rationale; it remains an F5 item and is counted separately from supported explanations and supplemental challenges. Evaluate such F5 abstentions with human review of the full response so a fabricated explanation alongside an abstention is not scored automatically correct. Counts remain pending actual human decisions and freeze QC.
# Extended evaluation v2 — development retrieval run; QA evaluation pending

V1 development retrieval has known-citation proxy outputs only; no end-to-end model result exists. V2 implements quota/split repair, tokenizer-aware chunks and independent hierarchical search. Freeze and test remain gated on the original human-signed Phase 5 freeze and v2 identities. See `EXTENDED_EVALUATION_RUNBOOK.md`.

V2 user-run results: 693 selected factual items, six F2 in total; 110 approved natural rewrites, including 51 development rewrites with completed retrieval. The 59 test rewrites remain unevaluated. V2 M3 saved development scores predate a parser fix and include 31 F3 `NO_INTENT` outputs; do not use them as results for the repaired parser. A separate user-run M3 repair output is required. No end-to-end model comparison is established.

Task 1 v3 was initially handed off for generation and spot checks; the subsequent verified freeze is registered below. No v3 retrieval experiment result is registered. Targets: about 220 KI forms, 80 MH and 40 F6H, plus eligible program-verified v2 records with F1 capped at 150. Actual counts and shortfalls come from the user-run summary. Original freeze d8ef826fbeb90d13 has 169 primary questions and six challenges. The Gemini ping returned 404; no replacement model is assumed. See BENCHMARK_V3.md.

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

Task 2 / Phase 9 retrieval: preregistration `docs/RETRIEVER_SELECTION.md` was
written before Task 2 results. R1–R7b × C0/C1/C2, development tracks only by
default; n>=10 passage-qrel cells from v3/natural determine selection. Full
10,000-resample cluster bootstrap, known-citation metrics and caches are
implemented. No real retrieval score, selected S2, or answering result is claimed.
State: AWAITING_TERMINAL_RUN. Owner commands: `docs/RETRIEVAL_V3.md`.

### Task 3 / Phase 10 prediction-only arms

State: IMPLEMENTED; offline fixture validation; AWAITING_OWNER_PILOT.
Systems S0–S8 plus separately labeled ORACLE; common generator/prompt/schema,
C1 selected corpus. S2 and default S3 both use R7b and are not independent
retrieval treatments. S4 dev tau suggestion is frozen into prediction identity.
Dev-only default; test flag/receipt required. Never score or tune test here.
Fixed three-per-family pilot, then advancing daily batches; all output versions
carry source/config/code hashes and successful qid resume keys. Missing v3 F2/F5
and test F3 remain accepted coverage gaps; no replacement generation.
Protocol/commands/artifacts: ANSWERING_SYSTEMS.md. Live compatibility and answer
quality remain unverified until owner results; no scoring/evaluator is implemented.

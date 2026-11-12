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

Task 1 v3 is implemented and fixture-tested, awaiting generation and human spot checks; no v3 experiment result or freeze is registered. Targets: about 220 KI forms, 80 MH and 40 F6H, plus eligible program-verified v2 records with F1 capped at 150. Actual counts and shortfalls come from the user-run summary. Original freeze d8ef826fbeb90d13 has 169 primary questions and six challenges. The Gemini ping returned 404; no replacement model is assumed. See BENCHMARK_V3.md.

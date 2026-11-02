# Experiment registry

No experiments have been run. Planned comparisons are mandatory M0 closed-book, M1 BM25 RAG, M2 hybrid RAG, and M3 parameterized SQL; M4 small-graph retrieval is optional. The generated 180-candidate target, F1–F6 families, and v0/v1 temporal comparison are documented in `docs/reference/research_roadmap.tex` and `configs/study.yaml`.

| Experiment ID | Method | Dataset snapshot | Configuration | Seed | Status | Results path |
|---|---|---|---|---|---|---|
| — | — | — | — | — | No registered runs | — |

Add a row only after a user-run job has been inspected. Do not enter projected results as observations or mark a run successful before validating outputs. Keep generated results and logs outside Git.


Phase 5 has 169 generated candidates and 6 supplemental challenges, with human review and freeze pending. Phase 6's SQL/BM25/scoring groundwork and local M0/M1 generation are implemented and fixture-tested; no real model run is registered. The user's provisional acceptance of pending answers permits development smoke checks only, never reportable study results. Actual retained counts and the frozen test checksum must be copied from the inspected freeze report before registering M0–M3. Template IDs, typed gold, canonical SQL and review sheets are evaluator-only; tune on development questions, then freeze before test inference. See [PHASE06_METHODS.md](PHASE06_METHODS.md).

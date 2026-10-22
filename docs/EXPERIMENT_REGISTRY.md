# Experiment registry

No experiments have been run. Planned comparisons are mandatory M0 closed-book, M1 BM25 RAG, M2 hybrid RAG, and M3 parameterized SQL; M4 small-graph retrieval is optional. The generated 180-candidate target, F1–F6 families, and v0/v1 temporal comparison are documented in `docs/reference/research_roadmap.tex` and `configs/study.yaml`.

| Experiment ID | Method | Dataset snapshot | Configuration | Seed | Status | Results path |
|---|---|---|---|---|---|---|
| — | — | — | — | — | No registered runs | — |

Add a row only after a user-run job has been inspected. Do not enter projected results as observations or mark a run successful before validating outputs. Keep generated results and logs outside Git.


Phase 5 benchmark construction is implemented, fixture-tested, and awaiting user generation and signed review. It is data/annotation preparation, not a method experiment. The Phase 4 50-bug pilot was verified from local artifacts as its input gate; no model run is registered. Actual family/dev/test/challenge counts and the frozen test checksum must be copied from the inspected user-run quality report before registering M0–M3. Template IDs, typed gold, canonical SQL and review sheets are evaluator-only; tune on development questions, then freeze before any test inference. See [PHASE05_BENCHMARK.md](PHASE05_BENCHMARK.md).

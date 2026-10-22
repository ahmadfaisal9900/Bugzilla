# Phase log

| Phase | Scope | State | Acceptance / next gate |
|---|---|---|---|
| 0 | Project structure, Git safety, and research workspace | Local commit `e706e3f`; push pending | Required skeleton and tracking docs exist; roadmap unchanged; datasets and generated artifacts ignored; bounded structure checks passed. |
| 1 | Consolidate foundation into existing repository | Local commit `35d32c7`; push pending | Existing `Project/` root and remote retained; no nested project Git root; roadmap and Dataset preserved. |
| 2 | Streaming data audit and 20-row fixture | Full user-run audit verified; summary in `docs/DATA_AUDIT_SUMMARY.md` | Exact counts, joins, timestamp rates, NUL handling, and Parts 1/2 SHA-256 verified. Rights/privacy and event-history semantics remain unresolved. |
| 3A | Deeper BugsRepo exploration and chunked profile | Full user-run profile verified | Reviewed `run-20261022T015655Z-1139511`: exact counts/hashes, Part 2 duplicate, Part 3 additional records, FIXED-selected comments and broad metadata negatives. See `docs/PHASE03A_QC.md`. |
| 3B | Canonical DuckDB/Parquet normalization and sampling | Implemented; fixture tests passed; **AWAITING_TERMINAL_RUN** | Agent used synthetic fixtures only; actual paths/QC passed a no-scan dry-run. User runs `bash scripts/phases/run_phase03b_normalize.sh`; review row accounting, hashes, joins, privacy, sample and examples before acceptance. |

Phase 3A full outputs remain ignored under `outputs/data_exploration/`; earlier smoke plots remain prefix-only evidence. Phase 3B fixtures write only synthetic data under ignored normalization outputs. The implementation selects base sources from verified QC but has not normalized actual data or chosen T0/T1. No API collection/model evaluation/later phase has started.

Phase 3B fixture suite: 14 total repository tests passed in about seven seconds, including five normalization tests. Retained synthetic example output: `outputs/normalization/phase03b/synthetic-fixture-20261022T023408Z/run/` (24 bugs / 7 comments / 20 anonymized examples; not corpus counts). Validation covers multiline CSV, NaN IDs, timezone normalization, malformed timestamps, explicit FIXED/reopening/DUPLICATE/INVALID events, duplicate exports/content variants, private/unknown-privacy withholding, deterministic sample, interrupted and completed resume, output hashes and Parquet round trips. History injected by tests is synthetic only. Free pinned DuckDB 1.4.4 is a new local dependency.

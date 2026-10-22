# Phase log

| Phase | Scope | State | Acceptance / next gate |
|---|---|---|---|
| 0 | Project structure, Git safety, and research workspace | Local commit `e706e3f`; push pending | Required skeleton and tracking docs exist; roadmap unchanged; datasets and generated artifacts ignored; bounded structure checks passed. |
| 1 | Consolidate foundation into existing repository | Local commit `35d32c7`; push pending | Existing `Project/` root and remote retained; no nested project Git root; roadmap and Dataset preserved. |
| 2 | Streaming data audit and 20-row fixture | Full user-run audit verified; summary in `docs/DATA_AUDIT_SUMMARY.md` | Exact counts, joins, timestamp rates, NUL handling, and Parts 1/2 SHA-256 verified. Rights/privacy and event-history semantics remain unresolved. |
| 3A | Deeper BugsRepo exploration and chunked profile | Implemented; targeted tests and 12-row smoke passed; **AWAITING_TERMINAL_RUN** | User runs `bash scripts/phases/run_phase03a_explore.sh`; review full per-source counts, hashes, joins, duplicate exports, bias, and plots. No full profile was run in-session. |

Phase 3A smoke output and plots are ignored under `outputs/data_exploration/`. Status/resolution plots from the 12-row smoke are explicitly prefix-only. No preprocessing, corpus selection, T0/T1 choice, or model evaluation has started.

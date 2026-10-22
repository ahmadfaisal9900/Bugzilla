# Research status

## Current phase

**Phase 3A — deeper BugsRepo exploration: AWAITING_TERMINAL_RUN.** The full profile has not been run in the agent session. Run `bash scripts/phases/run_phase03a_explore.sh` from the Project root and review its ignored summary before choosing the Phase 3B corpus.

## Completed

- Phase 0 scaffold: local commit `e706e3f`.
- Phase 1 consolidation: local commit `35d32c7`; the existing `Project/` root and `origin` remain authoritative.
- Phase 2 full audit: user-run, verified from `outputs/audit/phase02/run-20261022T010528Z-1096580/audit_summary.json` and `audit_report.json`; aggregate results are in `docs/DATA_AUDIT_SUMMARY.md`.
- Phase 2 established exact 500,000-row counts for each comment Part 1/2, equal SHA-256, 408,401 shared record IDs, and full metadata/report/comment bug-ID joins. Count Parts 1/2 once.
- Phase 3A profile module, resumable terminal script, 20-row overlapping/malformed-date fixture, and tests are implemented. Targeted tests passed. A 12-row-per-source profile and script dry-run ran; neither is a corpus result.
- Added dataset exploration, data dictionary, plots under ignored `outputs/data_exploration/`, and source paths to the tracked example plus ignored machine-local path config.
- Read the authoritative roadmap's data-source, canonical model, and F1–F6 question sections. The roadmap remains unchanged.

## Open decisions / limitations

- Phase 3A full profiling remains pending: complete status/resolution counts, Part 3 overlaps, metadata-all hash/ID overlap, quality-export relationships, and exact per-source null/date/provenance profile are not yet verified.
- The roadmap describes a resolved/fixed-or-closed collection; the filtered report export is selected. Quantify status/resolution bias before sampling and include open/non-fixed/reopened cases only if source evidence supports them.
- CSVs contain snapshot status plus `last_change_time`, not ordered status-change events. F2/as-of claims need validated `/history` data; do not infer transitions from last-change timestamps.
- The dataset PDF's copyright/publication statement does not establish redistribution permission. License/privacy review remains unresolved; contributor names/emails and private comments require minimization/exclusion.
- `Bug_meta_data_230k_all.csv` is a likely re-export based on size/schema and a bounded ID sample, not proven identical. Part 3's unique contribution is unknown.
- No T0/T1 cutoff, final corpus, or benchmark question set is selected. The 180-question value is a generation target across F1–F6, not a manual authoring quota.

## Environment and repository assumptions

- Project root: `/home/ict317/master's/ENSF 621/Project/`; only project Git root. Existing `origin` is `https://github.com/ahmadfaisal9900/Bugzilla.git`.
- Inputs stay under ignored root-level `Dataset/`; the GindeLab upstream clone remains unmodified. Paths resolve from `configs/data_paths.local.yaml`; tracked template is `configs/data_paths.example.yaml`.
- Current default interpreter: Python 3.13.13 / SQLite 3.51.2; tests also pass under the available Python 3.9.25 environment used for Phase 2 compatibility. The profile uses only the standard library. No paid APIs, new dependencies, crawler, proxy rotation, or MongoDB are required.
- Current filesystem reports 137 GiB free; raw candidate inputs remain in place. The profiler streams rows and writes ignored SQLite/output artifacts.
- Local `main` is ahead of `origin/main`; previous push attempts failed because HTTPS credentials are unavailable non-interactively. Preserve the existing remote and history.

## Scientific scope

Mandatory methods: M0 closed-book, M1 BM25-RAG, M2 hybrid RAG, M3 parameterized SQL. M4 small graph is optional. F1–F6 and temporal v0/v1 follow `docs/reference/research_roadmap.tex`. Firefox-product scope is not all Firefox engineering.

## Next gate

Run the full Phase 3A profile from the user's terminal, review `outputs/data_exploration/<run>/summary.json` and `profile.json`, then record only sanitized aggregate results. Do not begin Phase 3B ingestion or choose T0/T1 before that review and rights/privacy decisions.

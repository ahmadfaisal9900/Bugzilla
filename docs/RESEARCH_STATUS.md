# Research status

## Current phase

Phase 2 — implement a bounded, resumable dataset audit. The full audit remains user-run.

## Completed

- Phase 0 scaffold was committed locally as `e706e3f`.
- Phase 1 repository consolidation was committed locally as `35d32c7`; `Project/` remains the only project Git root and `origin` remains the existing Bugzilla repository.
- Phase 2 adds a standard-library streaming CSV audit, disk-backed ID index, a 20-row fixture, unit tests, ignored local data-path config, and a user-run full-scan script.
- Read only the roadmap's data-source and canonical-data-model sections (`docs/reference/research_roadmap.tex`, lines 135–200).
- Inspected the relevant dataset file sizes, CSV headers, and two deterministic rows per CSV. Sampled values were limited to IDs' presence/length and non-sensitive categories; no report/comment text or contributor values were exposed.
- Inspected upstream GindeLab/EASE_2025_Data_paper at commit `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e`; collection code uses requests, pandas, and MongoDB. No dependency manifest was found in the inspected upstream paths. No crawler or database utility was run or copied.
- Phase 2 reports schema/mappings, row counts, timestamps, ID joins, duplicate keys, product counts, NUL sanitation counts, private-field presence, history-field gaps, and Parts 1/2 SHA-256 and shared IDs when run without a limit.

## Not yet completed

- The user's full-audit run stopped on `csv.Error: line contains NUL` while starting comment Part 1. Its checkpoint records completed metadata (225,196 rows) and reports (120,047 rows); comment Part 1 was not completed. The parser now strips and counts NUL characters, and the latest checkpoint can be resumed.
- No source file was modified. No full comment scan or whole-file checksum has completed. Matching sizes and headers for Parts 1/2 do not establish that they are duplicates.
- Source license/redistribution terms and privacy authorization still need human review before research use.
- History/event coverage is currently inferred from headers only; audit output must be reviewed before selecting a corpus.
- The full audit's row counts, join coverage, duplicate counts, and timestamp rates will be recorded in `docs/DATA_AUDIT_SUMMARY.md` after the user returns its summary report.
- Local commits are ahead of `origin/main`; pushes have previously failed because HTTPS credentials are unavailable in the non-interactive environment.

## Repository and data assumptions

- Repository root: `/home/ict317/master's/ENSF 621/Project/`.
- Existing remote: `https://github.com/ahmadfaisal9900/Bugzilla.git`; never initialize or use a nested project repository.
- Dataset paths are in ignored `configs/data_paths.local.yaml`; the tracked template is `configs/data_paths.example.yaml`. The root `Dataset/` remains ignored and unmodified.
- Audit input is CSV. It streams rows; the distinct identifier index is stored under ignored run output. Relative paths resolve from the project root.
- No paid API, external package, crawler, proxy, or MongoDB access is required by this phase.

## Scientific scope

Compare mandatory methods M0 closed-book, M1 BM25 RAG, M2 hybrid RAG, and M3 parameterized SQL. The benchmark target is 180 generated candidate questions across F1–F6, with temporal v0/v1 evaluation; this is not a manual question-writing quota. M4 small graph remains optional. No corpus snapshot or benchmark questions have been selected.

## Next action

Resume the stopped user run with `bash scripts/run_phase02_audit.sh --resume`. Inspect the completed `audit_summary.json` and `audit_report.json`; then update the tracked data-audit summary and resolve rights/privacy/history decisions. Do not start preprocessing before that review.

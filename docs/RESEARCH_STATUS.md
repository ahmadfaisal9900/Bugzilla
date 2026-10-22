# Research status

## Current phase

**Phase 3B VERIFIED; Phase 4 NEXT.** User-run full normalization completed and was checked from latest run `run-20261022T023542Z-1182018` (manifest identity `0454ce48d6ed7a52973aea5474bee18304e33b65970c2c8c69dccdd0a630b663`). See `docs/PHASE_LOG.md` and `docs/PHASE03B_NORMALIZATION.md` for measured counts and limits.

## Completed

- Phase 0/1 preserved the existing Project root and origin. Earlier commits: `e706e3f`, `35d32c7`.
- Phase 2 user-run audit verified; see `docs/DATA_AUDIT_SUMMARY.md`.
- Phase 3A full user-run QC verified at `outputs/data_exploration/run-20261022T015655Z-1139511`; see `docs/PHASE03A_QC.md`.
- Phase 3B full input: 736,253 source rows; 196,633 unique canonical bugs; 419,458 canonical comments; 308,132 explicit recorded links; zero source quarantines/orphans. 28,533 metadata duplicates, 30 conflicting metadata variants, 91,599 Part 1 duplicate comments; Part 3 adds 11,057 comments. Frozen hashes/counts match 3A; Part 2 duplicate and metadata-all near-repeat excluded.
- Firefox product: 25,025 distinct bugs. Seed 317 sample contains 3,000 unique Firefox bugs and represents all 18 eligible status/resolution groups; includes 757 open/reopened bugs and 2,539 zero-comment bugs.
- DuckDB, Parquet, aggregate QC, sample manifest and 20 sanitized examples are in ignored run outputs. All 19 manifest-listed artifacts exist at recorded sizes with SHA-256 fields. No private/unknown-privacy bodies appear in comments/search documents.
- `field_changes` is empty; all 196,633 first-FIXED durations are UNKNOWN. Full validation details are recorded in the Phase 3B docs.

## Evidence gaps and limits

- **F2:** exact first-FIXED times, reopen sequence and historical state remain unsupported until validated `/history` enrichment. Never infer from latest-change time.
- **F4:** parsed snapshot links only; historical validity, past target status and complete link coverage need enrichment. 79,350 recorded targets are outside this canonical bug set.
- CSV source event times parsed, but original snapshot/export date is UNKNOWN (`snapshot_as_of_utc` NULL). Phase 3A observation time and Phase 3B ingestion time are separately recorded; this export cannot recreate a historical snapshot.
- Source redistribution/license review remains unresolved. Private/unknown privacy comment bodies are withheld; local public text can still contain personal data. Do not publish/redistribute derived text without review.
- No final question set/T0/T1 selected. 180 remains a generated question target; developer-hours cannot be inferred from elapsed days.

## Environment and repository

- Root: `/home/ict317/master's/ENSF 621/Project/`; `origin` remains `https://github.com/ahmadfaisal9900/Bugzilla.git`.
- Inputs remain read-only in ignored `Dataset/`; generated databases, Parquet and reports remain ignored under `outputs/`.
- Free DuckDB 1.4.4; no paid API, PyArrow, crawler, proxy rotation or MongoDB job.
- Full normalization used a 512 MB DuckDB budget; elapsed time was about 8m41s. Output database is about 1.89 GB. Sampling is Firefox-product only; that is not all Firefox engineering.

## Next gate

Phase 4 may begin from the authoritative roadmap. Keep F2/F4 limitations explicit, preserve this verified run, and do not choose T0/T1 until source-time coverage and history enrichment are addressed.

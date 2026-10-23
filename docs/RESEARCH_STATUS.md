# Research status

## Current phase

**Phase 3B VERIFIED; Phase 4 PILOT VERIFIED; Phase 5 CANDIDATES GENERATED, AWAITING ASSISTED PREPARATION AND HUMAN REVIEW.** The user-run generation `run-65c5be3381f66811` contains 169 benchmark QIDs and 6 challenges at seed 317, with 592 development / 2,408 test population IDs. The read-only assisted review prep and deterministic validators are implemented and fixture-tested; no full packet audit, F5 judgment, locked test, freeze, or method evaluation has run in the agent session. See `docs/PHASE05_BENCHMARK.md` and `docs/PHASE05_ASSISTED_REVIEW_PROTOCOL.md`.

## Completed

- Phase 0/1 preserved the existing Project root and origin. Earlier commits: `e706e3f`, `35d32c7`.
- Phase 2 user-run audit verified; see `docs/DATA_AUDIT_SUMMARY.md`.
- Phase 3A full user-run QC verified at `outputs/data_exploration/run-20261022T015655Z-1139511`; see `docs/PHASE03A_QC.md`.
- Phase 3B full input: 736,253 source rows; 196,633 unique canonical bugs; 419,458 canonical comments; 308,132 explicit recorded links; zero source quarantines/orphans. 28,533 metadata duplicates, 30 conflicting metadata variants, 91,599 Part 1 duplicate comments; Part 3 adds 11,057 comments. Frozen hashes/counts match 3A; Part 2 duplicate and metadata-all near-repeat excluded.
- Firefox product: 25,025 distinct bugs. Seed 317 sample contains 3,000 unique Firefox bugs and represents all 18 eligible status/resolution groups; includes 757 open/reopened bugs and 2,539 zero-comment bugs.
- DuckDB, Parquet, aggregate QC, sample manifest and 20 sanitized examples are in ignored run outputs. All 19 manifest-listed artifacts exist at recorded sizes with SHA-256 fields. No private/unknown-privacy bodies appear in comments/search documents.
- Base `field_changes` stays empty; its 196,633 first-FIXED durations remain UNKNOWN. The separate verified Phase 4 pilot `cohort-8bb3150d29a598d8` has 50 parsed histories, 884 changes, 13 first-FIXED cases / 37 UNKNOWN, and 17 REOPENED entries. Six overlay hashes and 147 cached response hashes/identities match; no new requests were made.
- Phase 5 v1.1 fixes Python 3.9 SQL timestamp formatting; 6 generation fixture tests and bounded real input verification pass. The user subsequently generated 169 candidates and 6 challenges. The queue and its pre-review backup remain byte-identical at SHA-256 `6d2030a6fa0d4abba1a4a6ab09a68465a6f12beb31e9056056ca67b807cb430c`; candidate/challenge SHA-256 values are pinned in the assisted review protocol. Ten fixture tests cover read-only assisted validators and privacy packet helpers. The benchmark is not frozen.
- Phase 5 pins that pilot and the verified 3B manifest. Before metadata/partition filters, 9 first-FIXED cases remain after excluding source differences and same-time ambiguity. The user-run candidate set is 169 questions + 6 challenges at seed 317; 180 remains a target, not an achieved count. F5 still requires human rationale review.

## Evidence gaps and limits

- **F2:** validated event answers exist only for eligible pilot cases. Base-only durations and missing transitions remain UNKNOWN; historical snapshot state and original data availability are unverified. Never infer from latest-change time.
- **Paper/data reconciliation:** the paper's 119,585 curated reports and 10,351 quality-selected reports are distinct populations from the 196,633-unique-bug broad metadata base. Local schemas and inspected upstream code have no ordered field-change events; paper-reported October 2024 coverage does not certify every CSV field's exact snapshot time. See `docs/PAPER_DATASET_RECONCILIATION.md`.
- **F4:** parsed snapshot links only; historical validity, past target status and complete link coverage need enrichment. 79,350 recorded targets are outside this canonical bug set.
- CSV source event times parsed, but original snapshot/export date is UNKNOWN (`snapshot_as_of_utc` NULL). Phase 3A observation time and Phase 3B ingestion time are separately recorded; this export cannot recreate a historical snapshot.
- Source redistribution/license review remains unresolved. Private/unknown privacy comment bodies are withheld; local public text can still contain personal data. Do not publish/redistribute derived text without review.
- No genuine historical source-time T0/T1 or final question set is verified. Phase 4 selects a controlled base-corpus/API-refresh comparison. 180 remains a generated question target; developer-hours cannot be inferred from elapsed days.

## Environment and repository

- Root: `/home/ict317/master's/ENSF 621/Project/`; `origin` remains `https://github.com/ahmadfaisal9900/Bugzilla.git`.
- Inputs remain read-only in ignored `Dataset/`; generated databases, Parquet and reports remain ignored under `outputs/`.
- Free DuckDB 1.4.4; no paid API, PyArrow, crawler, proxy rotation or MongoDB job.
- Full normalization used a 512 MB DuckDB budget; elapsed time was about 8m41s. Output database is about 1.89 GB. Sampling is Firefox-product only; that is not all Firefox engineering.

## Next gate

Run `scripts/run_phase05_agent_review_prep.sh --batch 10 --resume` from the user's terminal, inspect its reports, then use Prompt 5B for one F5 packet batch at a time. The human owner must review all retained F5 and challenge candidates plus required factual/F6 spot checks, and sign off before validate-freeze. No phase beyond benchmark construction is started; no locked test or experiment result is claimed.

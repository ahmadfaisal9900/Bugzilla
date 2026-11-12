# Research status

## Current phase

**Phase 3B VERIFIED; Phase 4 PILOT VERIFIED; Phase 5 FROZEN.** The user-run generation `run-65c5be3381f66811` contains 169 benchmark QIDs and 6 supplemental challenges at seed 317, with 592 development / 2,408 test population IDs. The verified freeze `d8ef826fbeb90d13` has 34 dev and 135 test benchmark questions plus six supplemental challenges. All seven frozen manifest artifact hashes matched a read-only check. No final method evaluation is claimed. See `docs/PHASE05_BENCHMARK.md` and `docs/AGENT_NOTES.md`.

The partner review bundle is explicitly tracked under `outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811/`; setup and browser review instructions are in `README.md`. At packaging on 2026-10-23 it has six recorded approvals and 58 remaining of 64 required reviews. These are signoff-sheet records, not yet transferred to the original generation queue or verified by the freeze validator. The original pre-review backup is preserved. Only the review interface, queues and small provenance manifest are shared; raw/full comment packets, databases and other outputs remain ignored.

On 2026-11-02 the local signoff sheet contained 36 recorded approvals and 28 required rows pending, including 22 F5 rows. A local ignored suggestion file supplies 19 source-attributed drafts for those pending F5 items and flags the other three for source checking or rejection. These are Automated recommendations, not human decisions; the human must verify and save each accepted correction. The original review queue and earlier signoffs were not changed by preparing these suggestions.

Later on 2026-11-02 the signoff sheet contained 40 approvals, 21 corrections and three pending required F5 rows. Per D-043, the UI and validator now support a human-confirmed, source-scoped insufficient-evidence answer for F5, preserving the question rather than requiring rejection. No pending row was automatically approved or reclassified. The exact existing run remains compatible only under the fingerprinted review-only amendment; full freeze still independently recomputes candidate gold and requires actual human signoff. F5 model abstentions need human response review. Fixture tests passed; no real freeze or model evaluation was run.

## Completed

- Phase 0/1 preserved the existing Project root and origin. Earlier commits: `e706e3f`, `35d32c7`.
- Phase 2 user-run audit verified; see `docs/DATA_AUDIT_SUMMARY.md`.
- Phase 3A full user-run QC verified at `outputs/data_exploration/run-20261022T015655Z-1139511`; see `docs/PHASE03A_QC.md`.
- Phase 3B full input: 736,253 source rows; 196,633 unique canonical bugs; 419,458 canonical comments; 308,132 explicit recorded links; zero source quarantines/orphans. 28,533 metadata duplicates, 30 conflicting metadata variants, 91,599 Part 1 duplicate comments; Part 3 adds 11,057 comments. Frozen hashes/counts match 3A; Part 2 duplicate and metadata-all near-repeat excluded.
- Firefox product: 25,025 distinct bugs. Seed 317 sample contains 3,000 unique Firefox bugs and represents all 18 eligible status/resolution groups; includes 757 open/reopened bugs and 2,539 zero-comment bugs.
- DuckDB, Parquet, aggregate QC, sample manifest and 20 sanitized examples are in ignored run outputs. All 19 manifest-listed artifacts exist at recorded sizes with SHA-256 fields. No private/unknown-privacy bodies appear in comments/search documents.
- Base `field_changes` stays empty; its 196,633 first-FIXED durations remain UNKNOWN. The separate verified Phase 4 pilot `cohort-8bb3150d29a598d8` has 50 parsed histories, 884 changes, 13 first-FIXED cases / 37 UNKNOWN, and 17 REOPENED entries. Six overlay hashes and 147 cached response hashes/identities match; no new requests were made.
- Phase 5 v1.1 fixes Python 3.9 SQL timestamp formatting; 6 generation fixture tests and bounded real input verification pass. The user subsequently generated 169 candidates and 6 challenges. The original pre-review backup has SHA-256 `6d2030a6fa0d4abba1a4a6ab09a68465a6f12beb31e9056056ca67b807cb430c`; the active queue now contains transferred human decisions. Candidate/challenge SHA-256 values are pinned in the assisted review protocol. Ten fixture tests cover read-only assisted validators and privacy packet helpers. The benchmark was subsequently frozen as noted above.
- Phase 5 pins that pilot and the verified 3B manifest. Before metadata/partition filters, 9 first-FIXED cases remain after excluding source differences and same-time ambiguity. The user-run candidate set is 169 questions + 6 challenges at seed 317; 180 remains a target, not an achieved count. F5 still requires human rationale review.

## Evidence gaps and limits

- **F2:** validated event answers exist only for eligible pilot cases. Base-only durations and missing transitions remain UNKNOWN; historical snapshot state and original data availability are unverified. Never infer from latest-change time.
- **Paper/data reconciliation:** the paper's 119,585 curated reports and 10,351 quality-selected reports are distinct populations from the 196,633-unique-bug broad metadata base. Local schemas and inspected upstream code have no ordered field-change events; paper-reported October 2024 coverage does not certify every CSV field's exact snapshot time. See `docs/PAPER_DATASET_RECONCILIATION.md`.
- **F4:** parsed snapshot links only; historical validity, past target status and complete link coverage need enrichment. 79,350 recorded targets are outside this canonical bug set.
- CSV source event times parsed, but original snapshot/export date is UNKNOWN (`snapshot_as_of_utc` NULL). Phase 3A observation time and Phase 3B ingestion time are separately recorded; this export cannot recreate a historical snapshot.
- Source redistribution/license review remains unresolved. Private/unknown privacy comment bodies are withheld; local public text can still contain personal data. Do not publish/redistribute derived text without review.
- No genuine historical source-time T0/T1 is verified. Phase 4 selects a controlled base-corpus/API-refresh comparison. The frozen benchmark has 169 questions, below the 180 target; developer-hours cannot be inferred from elapsed days.

## Environment and repository

- Root: `/home/ict317/master's/ENSF 621/Project/`; `origin` remains `https://github.com/ahmadfaisal9900/Bugzilla.git`.
- Inputs remain read-only in ignored `Dataset/`; generated databases, Parquet and reports remain ignored under `outputs/`, with only the five named partner-review files allowed by `.gitignore`.
- Free DuckDB 1.4.4; no paid API, PyArrow, crawler, proxy rotation or MongoDB job.
- Full normalization used a 512 MB DuckDB budget; elapsed time was about 8m41s. Output database is about 1.89 GB. Sampling is Firefox-product only; that is not all Firefox engineering.

## Next gate

Ahmad's tracked signoff sheet has decisions for all 64 required rows (40 approvals and 24 corrections). These decisions were transferred and the owner ran the freeze validator. The freeze report records 34 development and 135 test questions, plus six supplemental challenges.

Phase 6's model-free code (answer contract, scorer, M3 SQL, BM25) and local M0/M1 generation are implemented and fixture-tested but have not run with a real model or real data. No model is chosen; M2 and the study's M3 intent parser remain unimplemented. No method result exists. See `docs/PHASE06_METHODS.md`. The user authorized provisional acceptance of the remaining 31 answers for development only on 2026-11-02; this uses `--unfrozen-dev-smoke`, changes no official reviews and is not a freeze. The locked test stays closed until the freeze.

The retrieval extension has user-run v1 and v2 development retrieval outputs and opt-in local inference code. LLM inference and a complete QA comparison are not verified. The original Phase 5 freeze and separate expanded-bank seal gate test access. See `docs/EXTENDED_EVALUATION_RUNBOOK.md`.

The user-run v1 development retrieval completed, but its F1-heavy selection, 564 truncated chunks, 349/349 M3 `NO_INTENT` outputs, and 341/349 identical hybrid/hierarchical top-five lists required correction. The user subsequently ran v2: 693 selected questions, 14,443 indexed chunks with zero reported truncations, and 51 reviewed natural development rewrites retrieved. The saved v2 M3 development results still have 31 F3 `NO_INTENT` cases. A parser correction and separate resumable re-evaluation are fixture-tested, awaiting the user's run. No LLM answer comparison is verified. See `docs/EXTENDED_EVALUATION_RUNBOOK.md`.

On 2026-11-11, 64 genuine source-review decisions (40 approvals, 24 corrections) were transferred from the signed sheet into the original generation queue after row-level checks; a pre-transfer backup and audit record are retained locally. The owner subsequently signed and ran the freeze validator. Expanded test has separate seal requirements.

Task 1 of 3: an opt-in shared Gemini provider and preliminary v3 validation rules have been implemented with mocks and small fixtures. The v3 dataset generation, independent gold verification, review export, and freeze workflow are not yet implemented. No model request has been made. See `docs/AGENT_NOTES.md`.

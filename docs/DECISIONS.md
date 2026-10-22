# Decisions

| ID | Decision | Rationale / status |
|---|---|---|
| D-001 | Use a `src/bugzilla_qa/` Python package with separate data, benchmark, retrieval, methods, evaluation, and app subpackages. | Matches the planned research components while keeping Phase 0 free of system implementation. |
| D-002 | Ignore the complete root-level `Dataset/` directory, including the nested `EASE_2025_Data_paper` clone. | Protects downloaded data and upstream source from accidental staging or commits. |
| D-003 | Keep generated results and logs in `outputs/` and `logs/`, and ignore their contents. | Keeps reproducible source/configuration in Git while excluding local artifacts. |
| D-004 | Add no runtime dependencies in Phase 0. | Dependencies will be selected only when needed for a bounded, reproducible phase. |
| D-005 | Treat `docs/reference/research_roadmap.tex` as the authoritative scientific plan. | It defines scope, methods, benchmark, and temporal protocol; no results are implied by it. |
| D-006 | The only project Git root is `/home/ict317/master's/ENSF 621/Project/`; keep the root-level `Dataset/` external to Git. | The existing repository and `origin` predate the study; never create a nested project repository. |
| D-007 | Use a zero API spend budget and free/local methods. | Course constraint; model and hardware feasibility remain unresolved. |
| D-008 | Treat 180 as a generated candidate-question target across F1–F6. | The roadmap's target is not a quota for manually authored questions. |
| D-009 | Preserve metadata-only source notes in `docs/DATA_INVENTORY.md`; do not hash, import, or alter large source files during setup. | The comments files are multi-gigabyte and may include duplicate/private/contributor data. |
| D-010 | Resolve local dataset paths from ignored `configs/data_paths.local.yaml`; keep a tracked example with repository-relative paths. | Machine-specific paths must not enter Git, while audit runs need an explicit source manifest. |
| D-011 | Use Python's standard-library CSV parser and an ignored SQLite index for streaming audit counts and duplicate/join checks. | Avoid bulk CSV loads and new package dependencies; resumability is at completed-file boundaries. |
| D-012 | Verify comment Parts 1/2 with full SHA-256 on an unlimited user-run audit and report overlapping record IDs. | Equal sizes/headers alone do not prove duplicate content; limited scans never claim checksum verification. |
| D-013 | Treat license/redistribution and private/contributor-field authorization as unresolved until human review. | The audit reports evidence and field presence, not legal permission or a privacy approval. |
| D-014 | Strip embedded NUL characters only in the audit's streamed parser input and record their counts; never rewrite the source CSVs. | Python's CSV reader rejects NUL characters; transparent, non-persistent sanitation allows schema/count auditing while preserving source bytes. |
| D-015 | Count comment Part 1/2 once because the full Phase 2 audit verified matching SHA-256 values and 408,401 shared record IDs. | Exact byte equality is stronger than a matching filename/header; Phase 3A reuses this result only while file size and modification-time signatures match. |
| D-016 | Do not merge `Bug_meta_data_230k_all.csv`, Part 3, or quality-selected exports until full hashes, ID overlap, and comment-key overlap are profiled. | A similar schema, filename, or bounded prefix overlap cannot establish whether an export is a subset, superset, or repeat. |
| D-017 | Interpret status and resolution separately; never use `last_change_time` as a substitute for ordered history. | A sampled row is RESOLVED/INCOMPLETE, and Phase 2 headers do not expose event-time transitions. F2/as-of questions require validated history evidence. |
| D-018 | Keep the Phase 3A full profile user-run; the agent session may run only fixture tests and a tiny bounded sample. | The largest source is 1.6 GB and the operating contract prohibits long corpus jobs in-session. |
| D-019 | Phase 3B candidates are metadata + one verified comment copy + filtered reports, subject to Phase 3A results and rights/privacy review. | Together they provide snapshot facts, dated comment evidence, and report fields with high Phase 2 ID join coverage; the shortlist is not a final corpus or snapshot choice. |

| D-020 | Accept the user-run full 3A QC and select metadata + comment Parts 1/3 for Phase 3B base. | Supersedes the conditional shortlist in D-016/D-019: Parts 1/3 add complementary records, all parents join; Part 2 duplicates Part 1. Metadata-all is a near-repeat with anomalies. See PHASE03A_QC. |
| D-021 | Keep filtered reports/steps optional in a separate QUALITY tier; sample broad metadata without requiring comments. | All selected comment rows are FIXED-selected; open/non-FIXED outcomes exist in metadata and must survive sampling. |
| D-022 | Dedup comments by parent, nullable comment ID, UTC event time, exact parser-visible text hash and privacy flag. | Retain distinct comments and content versions; first metadata row wins deterministically with duplicate/conflict variants retained in provenance. |
| D-023 | Store nullable event/snapshot times and explicit UNKNOWN history; compute first FIXED only from actual qualifying transitions. | No source transition history exists; elapsed days are not engineer-hours. Reopening does not reset first FIXED. |
| D-024 | Use verified QC time as conservative observed-at, new-run time as ingested-at, and leave source snapshot date unknown. | Neither file mtime nor creation time establishes when snapshot status was true. Dual event/observation cutoffs prevent backdating evidence. |
| D-025 | Add pinned free DuckDB 1.4.4 for transactional streaming import and native Parquet export. | No PyArrow, paid API, crawler or MongoDB required; versioned outputs and complete manifests remain ignored. |
| D-026 | Reserve each observed status/resolution outcome before seeded component/year/outcome stratification. | 3,000 Firefox-product bugs is a planning target, not guaranteed coverage; retain smaller populations and zero-comment negative cases. No T0/T1 chosen. |
| D-027 | Withhold private/unknown-privacy bodies; retain local minimal row lineage and quarantines. | Preserve joins/accounting without treating absent authorization as public visibility. Dataset redistribution rights remain unresolved. |

Phase 3B source selection is implemented, not yet normalized/validated on actual inputs. No dataset snapshot, T0/T1, final benchmark corpus or model has been selected.

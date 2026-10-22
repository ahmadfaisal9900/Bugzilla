# Research status

## Current phase

**Phase 3B — canonical normalization: AWAITING_TERMINAL_RUN.** Implementation and synthetic fixture validation are complete. Actual selected CSVs were not ingested in-session. Run `bash scripts/phases/run_phase03b_normalize.sh` from the existing Project root after installing `duckdb==1.4.4` in that interpreter; see `docs/PHASE03B_NORMALIZATION.md`.

## Completed and verified

- Phase 0 scaffold `e706e3f` and Phase 1 consolidation `35d32c7` preserved the existing Project root/remote.
- Phase 2 full user-run audit is verified in `docs/DATA_AUDIT_SUMMARY.md`.
- Phase 3A full **user-run** profile `run-20261022T015655Z-1139511` is now reviewed: unlimited completed scans, exact counts, full input hashes and join/overlap QC. Sanitized evidence is in `docs/PHASE03A_QC.md`.
- Base metadata: 225,196 rows / 196,633 bugs. Parts 1/3: 500,000 + 11,057 rows / 52,243 union bugs, all joining metadata. Part 2 is byte-identical to Part 1. Metadata-all is a distinct near-repeat with malformed status values.
- Broad metadata includes NEW/REOPENED and non-FIXED outcomes. All Part 1/3 comment rows have FIXED snapshot resolution; comment availability must not determine sample eligibility.
- Phase 3B implements streaming canonical DuckDB/Parquet, row provenance, composite dedup, quarantine/accounting, transactional resume, versioned manifests/hashes, seeded stratification, history rules and local QA artifacts. Only synthetic fixtures were normalized in-session.
- Actual-source dry-run validated config paths, size/mtime signatures, full saved QC and selection without reading CSV rows. Roadmap unchanged.

## Selected sources / scope

- Base: `Bug_meta_data.csv`, `comments_Dataset_Part_1.csv`, `comments_Dataset_Part_3.csv`; tracked selection is `configs/phase03b_sources.json`.
- Optional QUALITY tier only: filtered reports and steps export; never pooled into base denominators. Contributors/upstream sample and metadata-all are excluded.
- All products remain in canonical tables. Sample defaults to Firefox product, seed 317, target 3,000; smaller is allowed. Preserve open/non-FIXED outcomes, including bugs without comments. Exact canonical product/sample counts await terminal results.

## Evidence gaps / unresolved decisions

- No selected CSV supplies ordered transitions. All actual F2 first-FIXED durations, reopen sequences and historical-state claims remain UNKNOWN until validated `/history` enrichment. Latest-change time is never a fix event.
- F4 supports parsed recorded snapshot links only; historical validity, historical target status, omitted links and commit/fix attribution remain unsupported without enrichment. Serialized empty lists are not links.
- Snapshot export date is UNKNOWN. Verified QC observation time is conservative local observation, not a backdated snapshot. Historical document queries guard event and observation times. No T0/T1 selected.
- Public comment text can contain personal data; private/unknown-privacy bodies are withheld. Source redistribution/license review remains unresolved. Keep raw and normalized text ignored/local; no publication permission is inferred.
- Metadata first-row winner is deterministic, not claimed latest; conflicting variants stay in provenance. Review actual conflict/quarantine rates before accepting the corpus.
- No benchmark questions or final research corpus selected; 180 remains a generation target. Developer-hours are UNKNOWN and never inferred from elapsed days.

## Environment and repository

- Root: `/home/ict317/master's/ENSF 621/Project/`; origin remains `https://github.com/ahmadfaisal9900/Bugzilla.git`. Never create another project repository or change remotes.
- Inputs stay read-only under ignored `Dataset/`; upstream clone unchanged. Local paths: ignored `configs/data_paths.local.yaml`; tracked example provided.
- Free dependency: DuckDB 1.4.4 (no PyArrow). Fixture tests use Python 3.13 and an isolated temporary dependency installation. User's Python 3.9 can install DuckDB directly; existing editable project metadata requires >=3.10.
- Full selected input approximately 2.0 GB; budget 5–10 GB output/spill, DuckDB 512 MB plus Python batch/row memory. Runtime unmeasured; jobs run only in the user's terminal.
- Generated DBs, Parquet, logs, examples and manifests remain under ignored `outputs/normalization/phase03b/`. Only code/docs/small configuration are committed.

## Scientific scope / next gate

Mandatory methods: M0 closed-book, M1 BM25-RAG, M2 hybrid RAG, M3 parameterized SQL; M4 optional. F1–F6 and temporal v0/v1 follow the authoritative roadmap. Firefox-product scope is not all Firefox engineering.

Review the user's Phase 3B `manifest.json`, `qc_report.json`, sample manifest and 20 anonymized examples before declaring normalization validated or advancing. No enrichment, model jobs, preprocessing of actual inputs or later phase was launched by this agent.

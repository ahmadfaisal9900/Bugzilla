# BugsRepo dataset exploration

## Scope and execution state

Phase 2's saved full audit is verified in [DATA_AUDIT_SUMMARY.md](DATA_AUDIT_SUMMARY.md). **The user's full Phase 3A profile is verified**, with exact counts/hashes/overlaps in [PHASE03A_QC.md](PHASE03A_QC.md). The earlier `smoke-20261021` profile remains prefix-only historical evidence. **Phase 3B's user full run is VERIFIED**; measured aggregates and limitations are in [PHASE03B_NORMALIZATION.md](PHASE03B_NORMALIZATION.md). The Phase 3B agent validated aggregate outputs only and did not ingest source CSVs.

The profiler reads `configs/data_paths.local.yaml`, continues one CSV record at a time (including quoted multiline cells), hashes completed sources while reading, and stores join/dedup keys in ignored SQLite output. It detects UTF-8, Windows-1252, or Latin-1 fallback, tracks malformed row widths and NULs, and never writes comment/report text, email values, names, or raw bug IDs to JSON. Full completed files get exact row/hash labels; a limited scan is explicitly `observed_prefix_only` and has no whole-file checksum claim. Resume reuses complete source checkpoints matching path, size, modification time, limit, seed, and profiler version; an interrupted source restarts from its beginning.

## Source groups and evidence

| File/group | Evidence from schema, bounded samples, and saved audit | Interpretation and confidence |
|---|---|---|
| `Bug_meta_data.csv` (350,195,270 bytes) | 299 columns; `id`, product/component, creation/last-change timestamps, status/resolution, relationship fields; exact Phase 2 count 225,196 rows / 196,633 unique bug IDs. | Broad current/snapshot metadata population. Duplicate bug IDs exist; do not treat each row as a unique bug. High confidence in schema/counts, history semantics still absent. |
| `Bug_meta_data_230k_all.csv` (350,150,509 bytes) | Full 3A: 225,207 rows / 196,631 bugs, 196,630 shared with base metadata; different SHA and malformed status values. | Near-repeat, not identical and not a clean superset. Excluded from base ingestion. |
| `comments_Dataset_Part_1.csv` and Part 2 (1,617,552,267 bytes each) | 315 columns; `id`, `bug_id`, `creation_time_x`, `text`, private flag, plus bug metadata. Full Phase 2 SHA-256 and record-key results prove byte equality. | Same export bytes, not independent populations. Use one copy only. Each has 500,000 rows and 50,764 unique bug IDs; repeated record keys are present. |
| `comments_Dataset_Part_3.csv` (36,310,793 bytes) | Full 3A: 11,057 rows / 1,480 bugs; zero shared profiled comment keys with Part 1; all parents join metadata. | Include in base, with composite content/time/parent dedup. Adds 1,479 bug IDs; one bug overlaps Part 1. |
| `CSV_100k_filtered_bug_reports.csv` (151,977,568 bytes) | Nine columns include `bug_id`, `creation_time`, `text`, report marker, `author_id`, status, resolution, and a steps-to-reproduce flag. Phase 2 found 120,047 rows, 83,596 unique bug IDs, and 83,550 IDs in metadata. | Filtered report/comment-like records; repeated bug IDs mean records are not one-row-per-bug. Product is absent and should be joined through metadata. Full 3A confirms selected/malformed population: 119,123 nonblank FIXED resolution rows, 462 bad creation dates and 19 FALSE statuses. Optional QUALITY tier only. |
| `CSV_Bug_reports_with_steps_to_reproduce (1).csv` (57,298,353 bytes) | 315 columns and fields overlapping comment exports (`bug_id`, `text`/`raw_text`, `is_private`, `creation_time_x`) plus metadata and quality fields. Header decode required Latin-1 fallback. | Full 3A: 12,614 rows / 8,522 bugs, all joining metadata, all FIXED, 4,092 repeated comment IDs. Keep in separate optional QUALITY tier; do not merge base row counts. |
| Contributor files | CSV has 17 columns including user ID/name, activity dates, permissions, and contribution counts; PDF describes contributor profiles. | Separate contributor population with identifying fields. Exclude from the QA corpus unless a later research question and privacy review require minimized, pseudonymized aggregates. |
| `Good_Bug_reports_with_S2r_AR_ER.xlsx`, `Good_CTQRS_filtered_bug_report.xlsx`, other XLSX files | Author-provided quality/sample workbooks; sheet dimensions were read from ZIP metadata only. `Good_CTQRS...` has 10,351 data rows; `Good_Bug...` has 12,614. | Author-selected samples, not independent all-bug populations. Do not concatenate with CSV exports without record-level overlap checks. |
| `EASE_2025_Data_paper/Sample_Dataset/bugs-2025-02-23.csv` | 1,668,674 bytes; 9 columns (`Bug ID`, type, summary, product, component, assignee, status, resolution, updated); Phase 2 found 10,000 rows and 10,000 unique IDs. | A separate dated upstream sample snapshot, not a continuation of the BugsRepo export. Keep its provenance and cutoff distinct. |

Dataset-level citation/provenance: the local three-page `Dataset/0_Dataset_Info.pdf.pdf` describes bug metadata, comments, and contributor information. It says copyright is held by the owner/author(s) and publication rights are licensed to ACM; it does not state a clear dataset redistribution license. The upstream GindeLab clone is at commit `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e`. Its README/scripts describe Bugzilla collection and CSV processing; inspected scripts depend on requests, pandas, and pymongo, and no dependency manifest or top-level license file was found in the inspected locations. No crawler, proxy rotation, or MongoDB utility was run. The profiler is an independent standard-library CSV stream; cite the upstream paper/repository for data provenance, not code reuse.

## Product populations

The figures below are Phase 2 full-scan **row counts**, including repeated bug IDs. Part 2 is byte-identical to Part 1 and is excluded from the comment population totals.

| Product bucket | Metadata rows | Comment Part 1 rows |
|---|---:|---:|
| Firefox | 29,919 | 71,586 |
| Core | 93,645 | 223,525 |
| Toolkit | 10,370 | 23,531 |
| Other Mozilla products/projects | 91,262 | 181,358 |
| **Total** | **225,196** | **500,000** |

These counts are product labels, not unique bug counts. The 29,919 Firefox-product rows are not all Firefox engineering activity: important Firefox work also appears under Core, Toolkit, Fenix, Firefox Build System, GeckoView, and other Mozilla products. Conversely, a broad Mozilla dataset is not equivalent to a Firefox-only benchmark. The 10,000-row upstream sample has a separate product distribution and must not be pooled into these totals.

## Status, resolution, and selection bias

Status and resolution are different fields. Status expresses a workflow state such as `NEW`, `RESOLVED`, or `VERIFIED`; resolution gives the outcome/reason, such as `FIXED`, `DUPLICATE`, `INVALID`, `INCOMPLETE`, or `WONTFIX`. A bounded first metadata row was `RESOLVED` with resolution `INCOMPLETE`, showing directly why `RESOLVED` is not synonymous with `FIXED`. A `FIXED` snapshot still does not reveal when the bug first became fixed or whether it reopened.

The paper reports 119,585 curated metadata/comment reports and a separate 10,351-report structured/quality-selected subset. Our local filtered-report CSV and CTQRS workbook have the same respective headline counts, but equal counts do not prove identical version or membership. The base `Bug_meta_data.csv` normalizes to 196,633 unique bugs: a broader population, not a replacement for or proven exact superset of the paper's curated set. See [paper reconciliation](PAPER_DATASET_RECONCILIATION.md). The verified full 3A profile confirms that all 511,057 Part 1/3 comment rows have FIXED snapshot resolution. Broad metadata includes 37,275 NEW and 2,408 REOPENED source rows and numerous DUPLICATE/INVALID/INCOMPLETE outcomes; see PHASE03A_QC for full aggregate denominators. Keep those metadata bugs even if selected comments are absent. Phase 3B's canonical per-bug product/status/resolution counts and the Firefox sample strata are reported in `docs/PHASE03B_NORMALIZATION.md`.

## What F1–F6 can use from CSVs alone

| Family | CSV-only support | Missing evidence / boundary |
|---|---|---|
| F1 single-bug lookup | Snapshot product/component/status/resolution and selected metadata fields, with source row and bug ID. | State explicitly which export/snapshot is queried; do not present it as current live status. |
| F2 lifecycle/time | Creation time and latest-change time are present; neither is a status-transition sequence. | First-FIXED elapsed time, reopen sequence, and as-of state require `/history` or equivalent ordered events. `last_change_time` cannot substitute. |
| F3 aggregates | Exact counts over a frozen, deduplicated, explicitly scoped CSV population. | Selection bias and repeated exports can change the denominator; state snapshot, product, and dedup rule. |
| F4 relationships | Metadata has fields such as `blocks`, `depends_on`, `duplicates`, `see_also`, and `regressions`. | Only recorded edges are answerable. Historical edge validity or target status as of a past date requires history. |
| F5 explanation/synthesis | Dated comments can support a careful summary of explicitly stated reasons. | Full comment coverage/visibility must be verified; exclude private comments and minimize personal data. |
| F6 unanswerable/ambiguous | CSVs can establish that evidence is missing or a bug is outside a declared corpus. | Engineer-hours are not in these records; refuse rather than infer effort from elapsed calendar time or comments. |

Temporal v0/v1 must remain separate snapshots. This export supplies a snapshot and selected timestamps, not complete historical transitions. Roadmap-required `/history` evidence is needed for temporal lifecycle claims; a later v1 update cannot be inserted into v0 as if it were known then.

## Anonymized evidence chains

Labels are placeholders; no raw IDs, text, names, or emails are published.

1. **Observed aggregate-linked chain B-01:** the full audit found 50,764 unique comment bug IDs and all 50,764 join to metadata. A matched bug therefore has a metadata snapshot plus comment records; the schema has creation/last-change timestamps but no ordered event fields. Snapshot lookup (F1) may be supported; exact first-FIXED/reopen time (F2) is not. The label does not identify a chosen individual record.
2. **Observed aggregate-linked chain B-02:** 83,550 of 83,596 unique filtered-report bug IDs join to metadata. The report export has dated text and status/resolution fields, while metadata supplies product/component. This supports linked report/snapshot evidence for matched records, subject to record deduplication and privacy filtering; it does not prove the report text describes a later status change.
3. **Observed bounded row B-03:** one sampled metadata row had product `Core`, component `DOM: File`, status `RESOLVED`, resolution `INCOMPLETE`, and populated creation/last-change timestamps. It is a single observed example, not a population estimate; it demonstrates that resolved state does not mean fixed outcome.
4. **Hypothetical relationship chain B-04:** if a selected bug has a populated `blocks` or `depends_on` edge and the target bug exists in the chosen snapshot, F4 can report that recorded edge and snapshot status. A claim about whether the target was fixed by a historical cutoff remains unsupported without event history.

## Limitations, rights, and privacy

- The source populations are filtered, derived, and repeated; Part 1/2 are exact duplicate bytes; full 3A establishes metadata-all as a near-repeat and Part 3 as additional comment records. Do not add their row counts together.
- Several timestamp columns have ambiguous roles in merged exports (`creation_time_x`/`creation_time_y`). Phase 2 parse success measures syntax, not semantic correctness or timezone provenance.
- Current status/resolution plus `last_change_time` are not change events. Comments can be incomplete, private, or attached to duplicated export rows.
- Schemas expose reporter/creator/assignee names, email addresses, contributor IDs, comment text, and `is_private`. Keep content and identifiers out of tracked summaries; use only public/allowed comments, and minimize or pseudonymize identities.
- The PDF's publication-rights statement is not an explicit license to redistribute the dataset. Verify source/license terms before redistribution or publication; citation does not itself grant rights.
- Upstream scripts include network collection, rate-limited requests, pandas, MongoDB, and proxy-related utilities. They were inspected only; none was run or copied.

## Phase 3B selected sources and resource estimate

Verified source selection is `Bug_meta_data.csv` plus comment Parts 1 and 3: 2,004,058,330 bytes (about 1.87 GiB), unchanged in place. Metadata gives broad outcome coverage; comments contribute dated public evidence without requiring every bug to have comments. Exclude Part 2's duplicate bytes and metadata-all's problematic near-repeat. Filtered reports and steps export remain optional separate QUALITY records, not the base population. See [PHASE03B_NORMALIZATION.md](PHASE03B_NORMALIZATION.md) for schema and exact commands.

Reserve 5–10 GB for DuckDB, Parquet and spill; DuckDB budget defaults to 512 MB plus Python's bounded batch/current-record memory. These are estimates, not measured full-ingestion results. Target 3,000 Firefox-product bugs with component/year/status/resolution stratification and isolated seed; 2k–5k remains a planning range, smaller coverage is allowed. No T0/T1 or post-cutoff set is selected. Keep open/non-FIXED/reopened bugs, including those without comments.

## Local plots

Five standard-library SVG plots were generated under ignored `outputs/data_exploration/smoke-20261021/plots/`:

- `products_metadata.svg`: Core is the largest metadata product bucket; Firefox-product rows are a minority of the broad Mozilla snapshot.
- `products_comments_part_1.svg`: Core and Firefox have the most comment rows; this is row volume and includes repeated bug IDs.
- `bug_id_joins.svg`: metadata/report and metadata/comment ID coverage is high, but the join does not erase source selection bias.
- `timestamp_parse_rates.svg`: parse success is high in audited timestamp fields; parsing does not validate whether a field means creation or last update.
- `status_resolution_filtered_reports.svg`: a bounded-prefix view of current status and resolution values. It illustrates distinct fields and is not a population histogram yet.

The first four plots above use Phase 2's verified full-scan aggregates. `status_resolution_filtered_reports.svg` is explicitly a 12-row prefix plot from the bounded smoke, not a population distribution; the completed user full run has a separate regenerated plot set under its own run directory. Refer to PHASE03A_QC for reviewed exact counts rather than treating the old prefix plot as a corpus result. Repeated-key counts are reported in JSON and the audit summary. All plots are ignored machine outputs and can be regenerated.

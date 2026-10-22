# Phase 3A: verified terminal-run QC

Reviewed the user's completed `outputs/data_exploration/run-20261022T015655Z-1139511/profile.json` and checkpoint. Status is `full_profile`, limit is null, and selected sources have complete scans with exact row counts and whole-file SHA-256. This was a user-run profile; no corpus scan was launched by the Phase 3B agent.

| Source | Exact rows | Distinct bugs | Phase 3B disposition |
|---|---:|---:|---|
| `Bug_meta_data.csv` | 225,196 | 196,633 | Base metadata; deduplicate by bug ID and retain conflicting variants in provenance. |
| `comments_Dataset_Part_1.csv` | 500,000 | 50,764 | Base comments; 91,599 repeated comment-ID rows require composite deduplication. |
| `comments_Dataset_Part_2.csv` | 500,000 | 50,764 | Exclude: byte-identical to Part 1. |
| `comments_Dataset_Part_3.csv` | 11,057 | 1,480 | Base additional comments; zero shared profiled comment keys with Part 1. |
| `Bug_meta_data_230k_all.csv` | 225,207 | 196,631 | Exclude near-repeat: not byte-identical; 196,630 IDs shared with base metadata and malformed status values. |
| `CSV_100k_filtered_bug_reports.csv` | 120,047 | 83,596 | Optional QUALITY tier; 46 bug IDs outside base metadata, 462 malformed creation dates, and 19 `FALSE` statuses. |
| `CSV_Bug_reports_with_steps_to_reproduce (1).csv` | 12,614 | 8,522 | Optional QUALITY tier; all bug IDs join metadata; 4,092 repeated comment-ID rows. |

Part 1/3 union has **52,243 distinct bug IDs**, all present in metadata. One bug appears in both parts; Part 3 adds 1,479 bug IDs. Absence of shared profiled comment keys is evidence for including Part 3, while ingestion still checks a stricter content/time/parent composite key.

## Bias and semantics

- Metadata status row counts: ASSIGNED 1,918; NEW 37,275; REOPENED 2,408; RESOLVED 164,264; UNCONFIRMED 8,740; VERIFIED 10,591. These sum to 225,196 source rows, not distinct bugs.
- Metadata resolution row counts include FIXED 95,567; DUPLICATE 22,356; INVALID 16,308; INCOMPLETE 26,230; WORKSFORME 8,703; WONTFIX 4,579; INACTIVE 422; MOVED 690; remaining 50,341 blank. Broad metadata supplies negative/non-FIXED cases.
- **All 511,057 comment rows in Parts 1 and 3 have snapshot resolution FIXED.** Their comments are not representative of open/non-FIXED bugs. Sampling must not require available comments.
- All selected metadata creation/last-change and comment event values parsed in 3A; semantic roles still differ. In merged comments, `creation_time_x` is comment time; `creation_time_y` is joined bug creation. No selected file contains ordered history events.
- Phase 3A's relationship-field nonempty counts include serialized `[]`; they are not edge counts. Phase 3B parses explicit targets before reporting edges.
- Part 1 has 74 embedded NUL characters. Parser sanitation is transient and counted; original bytes remain untouched.
- Product metadata raw row counts are Firefox 29,919; Core 93,645; Toolkit 10,370; other 91,262. Phase 3B selected first-row canonicalization yields 25,025 distinct Firefox-product bugs; canonical counts by all product labels are in the run QC. Firefox-product is not all Firefox engineering.

## Frozen selected input hashes

| Source | Bytes | SHA-256 |
|---|---:|---|
| Metadata | 350,195,270 | `17457b6c451e8462c49c98678cba67debb8f0ea982267ced367ff2d2efef0df3` |
| Part 1 / identical Part 2 | 1,617,552,267 each | `2ae7f5e4d49f8c459920e9747f8cfc121ee33bba3296d12268be6f1f018b97b1` |
| Part 3 | 36,310,793 | `77c74ce85cc7361dd630efaf5aac31d66683c68ce533ebc26f6aeb55d767e616` |

QC generation time `2026-10-22T01:56:55Z` establishes a conservative local observation time, **not** the original export snapshot date. Copyright/redistribution permission remains unresolved; keep raw and normalized text local/ignored. No T0/T1 is selected.

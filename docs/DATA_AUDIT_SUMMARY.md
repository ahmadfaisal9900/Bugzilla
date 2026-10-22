# Phase 2 data audit summary

**Status:** Verified full user-run audit. Source report: ignored `outputs/audit/phase02/run-20261022T010528Z-1096580/audit_summary.json`; details: corresponding `audit_report.json`. Generated 2026-10-22 01:15 UTC. No raw IDs or text are included here.

| Source | Exact CSV rows | Columns | Unique bug IDs | Duplicate-key rows | Creation timestamp parse |
|---|---:|---:|---:|---:|---:|
| `Bug_meta_data.csv` | 225,196 | 299 | 196,633 | 28,563 | 225,196 / 225,196 |
| `CSV_100k_filtered_bug_reports.csv` | 120,047 | 9 | 83,596 | 36,451 | 119,585 / 120,047 (99.615%) |
| `comments_Dataset_Part_1.csv` | 500,000 | 315 | 50,764 | 91,599 | 500,000 / 500,000 |
| `comments_Dataset_Part_2.csv` | 500,000 | 315 | 50,764 | 91,599 | 500,000 / 500,000 |
| upstream `bugs-2025-02-23.csv` | 10,000 | 9 | 10,000 | 0 | 10,000 / 10,000 (`Updated`) |

The duplicate-key count uses the audit's selected record-key field; it is not the number of duplicate bug IDs for comment files. Parts 1 and 2 have identical size (1,617,552,267 bytes) and SHA-256 (`2ae7f5e4d49f8c459920e9747f8cfc121ee33bba3296d12268be6f1f018b97b1`). Their 408,401 shared record IDs are from the full files. Count the pair once. Each copy had 74 NUL characters removed only from the parser's in-memory input; the originals were not changed.

| Join | Shared unique bug IDs | Coverage of right-side IDs in left |
|---|---:|---:|
| Metadata ← filtered reports | 83,550 / 83,596 | 99.945% |
| Metadata ← comment Parts 1/2 union | 50,764 / 50,764 | 100% |
| Filtered reports ← comment Parts 1/2 union | 50,764 / 50,764 | 100% |

The metadata creation timestamp and comment `creation_time_x` parsed at 100%; the filtered-report `creation_time` field parsed at 99.615%. The saved audit found no explicit ordered change-event fields in the scanned headers. `last_change_time` is only a snapshot's latest-change timestamp and does not reconstruct status transitions.

The Phase 2 audit itself did not publish report status/resolution frequencies. Later full Phase 3A QC found the comment Parts 1/3 population entirely FIXED-selected while broad metadata contains open and non-FIXED cases; see `docs/PHASE03A_QC.md`. The saved license/redistribution question remains pending human review.

Phase 3A reused this verified summary and skipped a second Part 2 scan while current size and modification-time signatures matched. Its separate full user profile is verified in `docs/PHASE03A_QC.md`; Phase 3B normalization is verified in `docs/PHASE03B_NORMALIZATION.md`.

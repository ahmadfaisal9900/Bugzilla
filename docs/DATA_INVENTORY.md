# Data inventory

Inspected 2026-10-21 from the Project root. Only top-level Dataset filenames/sizes, CSV headers and bounded safe row samples were read, with the exact upstream sample path. No recursive CSV-directory enumeration or source modification occurred. Full Phase 2 counts/checksums are in [DATA_AUDIT_SUMMARY.md](DATA_AUDIT_SUMMARY.md); source interpretation and Phase 3A limits are in [DATA_EXPLORATION.md](DATA_EXPLORATION.md).

## Root `Dataset/` files

| File | Exact size (bytes) | Inspection note |
|---|---:|---|
| `0_Dataset_Info.pdf.pdf` | 263,303 | Readable three-page PDF; describes bug metadata, comments, contributors; copyright held by owner/author(s), publication rights licensed to ACM; no clear dataset reuse license stated. |
| `100k_filtered_raw_bug_reports.xlsx` | 34,268,503 | Workbook container inspected only; no sheet body loaded. |
| `Bug_meta_data.csv` | 350,195,270 | UTF-8 BOM; 299 columns; full Phase 2 audit completed. |
| `Bug_meta_data_230k_all.csv` | 350,150,509 | UTF-8 BOM; same 299-column header; full identity/overlap still pending. |
| `Bug_meta_data_230k_excel.xlsx` | 75,501,128 | Workbook container inspected only. |
| `CSV_100k_filtered_bug_reports.csv` | 151,977,568 | UTF-8 BOM; 9 columns; full Phase 2 audit completed. |
| `CSV_Bug_reports_with_steps_to_reproduce (1).csv` | 57,298,353 | 315 columns; header used Windows-1252/Latin-1 fallback; derived/merged role needs full profile. |
| `CSV_Contribution_information_dataset.csv` | 7,412,934 | 17 columns; contributor identifying fields present. |
| `CTQRS_Scoring_Code.py` | 23,862 | Not executed; not needed for the profiler. |
| `Contribution_information_dataset.xlsx` | 4,294,980 | Workbook container inspected only. |
| `Good_Bug_reports_with_S2r_AR_ER.xlsx` | 22,718,763 | Workbook dimensions indicate 12,614 data rows; body not loaded. |
| `Good_CTQRS_filtered_bug_report.xlsx` | 2,846,157 | Workbook dimensions indicate 10,351 data rows; body not loaded. |
| `comments_Dataset_Part_1.csv` | 1,617,552,267 | UTF-8 BOM; 315 columns; 500,000 rows in full audit. |
| `comments_Dataset_Part_2.csv` | 1,617,552,267 | Full SHA-256 matches Part 1; count once. |
| `comments_Dataset_Part_3.csv` | 36,310,793 | 315-column header; full count and overlap pending. |

## Upstream clone

- `Dataset/EASE_2025_Data_paper/` is the existing GindeLab clone at commit `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e`; it remains unchanged and inside ignored `Dataset/`.
- Exact sampled source: `Sample_Dataset/bugs-2025-02-23.csv`, 1,668,674 bytes; 9 columns; Phase 2 found 10,000 rows and IDs.
- README and selected `Meta_Data_Gather/` and `Comments_Data_Gather/` scripts were inspected. They reference requests, pandas, pymongo, rate-limited REST collection, and MongoDB; proxy-related utilities were not run. No dependency manifest or top-level license file was found in the inspected locations.
- No data files, upstream scripts, or upstream repository state were changed.

## Safe handling

Machine-local source mappings live in ignored `configs/data_paths.local.yaml`; `configs/data_paths.example.yaml` is the tracked template. The whole root-level `Dataset/`, including the upstream clone, remains ignored. Profiling output, indexes, logs, and plots are ignored under `outputs/data_exploration/`. No raw comment/report content, emails, reporter names, or raw IDs appear in tracked docs.

# Data inventory (metadata-only inspection)

Inspected on 2026-10-21. Paths below are under the root-level Git-ignored `Dataset/` and remain unchanged. Sizes are filesystem metadata. CSV column counts and selected names came from the first header record only; no data rows or checksums were read.

## Downloaded inputs: `Dataset/`

| File | Size (bytes) | Header/type notes |
|---|---:|---|
| `0_Dataset_Info.pdf.pdf` | 263,303 | PDF; content not read |
| `100k_filtered_raw_bug_reports.xlsx` | 34,268,503 | XLSX; sheet data not read |
| `Bug_meta_data.csv` | 350,195,270 | 299 columns; includes `id`, `product`, `component`, `creation_time`, `status`, `resolution`, `Contributor_email`, `Contributor_Id` |
| `Bug_meta_data_230k_all.csv` | 350,150,509 | 299 columns; same selected header fields as metadata CSV above |
| `Bug_meta_data_230k_excel.xlsx` | 75,501,128 | XLSX; sheet data not read |
| `CSV_100k_filtered_bug_reports.csv` | 151,977,568 | 9 columns; includes `bug_id`, `creation_time`, `text`, `status`, `resolution` |
| `CSV_Bug_reports_with_steps_to_reproduce (1).csv` | 57,298,353 | 315 columns; header parsed with Latin-1 fallback; includes `bug_id`, `text`, `is_private`, contributor fields |
| `CSV_Contribution_information_dataset.csv` | 7,412,934 | 17 columns; header parsed with Latin-1 fallback |
| `comments_Dataset_Part_1.csv` | 1,617,552,267 | 315 columns; includes comment text, `bug_id`, `is_private`, contributor fields |
| `comments_Dataset_Part_2.csv` | 1,617,552,267 | Same size/header count as Part 1; possible duplicate is unverified |
| `comments_Dataset_Part_3.csv` | 36,310,793 | 315 columns; includes comment text, `bug_id`, `is_private`, contributor fields |
| `CTQRS_Scoring_Code.py` | 23,862 | Present; not opened or executed |
| `Contribution_information_dataset.xlsx` | 4,294,980 | XLSX; sheet data not read |
| `Good_Bug_reports_with_S2r_AR_ER.xlsx` | 22,718,763 | XLSX; sheet data not read |
| `Good_CTQRS_filtered_bug_report.xlsx` | 2,846,157 | XLSX; sheet data not read |

## Upstream clone: `Dataset/EASE_2025_Data_paper/`

- Existing independent upstream Git root at commit `e0f44e6`; it remains inside ignored `Dataset/` and was not modified.
- README describes metadata/comment collection and analysis scripts, MongoDB use, and a sample CSV. Some README-mentioned scripts use proxies; do not run them.
- `Dataset/EASE_2025_Data_paper/Sample_Dataset/bugs-2025-02-23.csv`: 1,668,674 bytes, 9 header columns (`Bug ID`, `Type`, `Summary`, `Product`, `Component`, `Assignee`, `Status`, `Resolution`, `Updated`). No rows read.

## Audit cautions

- The two largest comments parts have equal byte sizes. The roadmap flags a possible duplicate checksum; equality is not established because full-file hashing was intentionally not run.
- Headers expose contributor identifiers/email fields and a private-comment flag. Later ingestion needs a privacy/minimization decision.
- These headers do not establish field completeness, license/redistribution rights, history-event coverage, or a valid Firefox-product sampling frame. Resolve those in Phase 1 before processing.

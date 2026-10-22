# Data inventory and bounded sample inspection

Inspected on 2026-10-21. Paths below are under the root-level Git-ignored `Dataset/` and remain unchanged. Sizes are filesystem metadata. Header inspection and a two-row deterministic sample per CSV were performed; sample review recorded only field presence/length and non-sensitive categories, not report/comment text or contributor values. No whole-file checksums were read.

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
- Upstream remote: `https://github.com/GindeLab/EASE_2025_Data_paper.git`; inspected commit: `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e`.
- README describes metadata/comment collection and analysis scripts, MongoDB use, and a sample CSV. Some README-mentioned scripts use proxies; do not run them.
- `Dataset/EASE_2025_Data_paper/Sample_Dataset/bugs-2025-02-23.csv`: 1,668,674 bytes, 9 header columns (`Bug ID`, `Type`, `Summary`, `Product`, `Component`, `Assignee`, `Status`, `Resolution`, `Updated`). Two deterministic rows were sampled with values suppressed as described above.
- The inspected metadata/comment scripts import requests, pandas, and pymongo; no requirements/pyproject/setup/environment manifest was found in the inspected upstream paths. The safe reusable idea is row-wise CSV reading and field naming from `Comments_Data_Gather/Bug_comment.py`; the audit independently implements its own `csv.DictReader` stream and does not reuse network, MongoDB, proxy, or DataFrame logic. Attribution: GindeLab, `EASE_2025_Data_paper`, commit `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e`.

## Audit cautions

- The two largest comments parts have equal byte sizes. The roadmap flags a possible duplicate checksum; equality is not established because full-file hashing was intentionally not run.
- Headers expose contributor identifiers/email fields and a private-comment flag. Later ingestion needs a privacy/minimization decision.
- These headers do not establish field completeness, license/redistribution rights, history-event coverage, or a valid Firefox-product sampling frame. Resolve those before corpus selection.
- Two-row sample inspection found initial metadata/report products including `Core`, and the upstream sample included both `Core` and `Firefox`; this is not a product distribution estimate. The comments Parts 1/2 sampled the same first two bug/comment IDs, which is only a potential overlap signal; no equality assumption is made.
- Local audit paths are mapped in ignored `configs/data_paths.local.yaml`; `configs/data_paths.example.yaml` is the tracked template. Full row counts, timestamp rates, join coverage, duplicate totals, and Parts 1/2 SHA-256 remain pending the manual run.

# BugsRepo paper and local data reconciliation

## Finding

The paper's broad description of BugsRepo as containing lifecycle information does not establish that the downloaded CSVs contain ordered Bugzilla field-change events. The locally inspected source headers, normalized Phase 3B schema, and upstream extraction scripts do not expose timestamped old/new status or resolution transitions. Phase 4's selective public `/history` extraction remains necessary for F2; its current smoke/API gate is unchanged.

## What the paper reports

Acharya and Ginde's EASE 2025 paper, version 1, reports a BugsRepo metadata-and-comments collection of **119,585 curated bug reports**, with collection coverage described as data gathered as of **October 2024**. It separately reports **10,351 structured, quality-selected reports** after report-structure and CTQRS filtering. It also describes lifecycle status updates in prose. These are the paper's dataset-population and coverage claims, not a field-level export manifest for every distributed file. [Paper, arXiv:2504.18806v1](https://arxiv.org/abs/2504.18806v1).

The paper's Table 1 lists `activity id`, `when`, `old value`, and `new value` for a *prior Zhu et al. dataset*. Its BugsRepo row instead lists bug metadata, contributor information, and comments. Those prior-work columns must not be attributed to the BugsRepo CSVs. The paper's general lifecycle wording is not evidence that a complete ordered change log was distributed.

## What is present locally

| Evidence | Bounded observation | Interpretation |
|---|---|---|
| Phase 3B base metadata | Verified run `run-20261022T023542Z-1182018`: 196,633 unique canonical bugs. `bugs` has snapshot status/resolution, creation and scalar latest-change timestamps; `snapshot_as_of_utc` is null for all rows. | Broader metadata population than the paper's 119,585 curated reports. It is neither a replacement for that population nor a proven exact superset by membership. |
| Normalized event table | `field_changes` contains 0 rows; all 196,633 `history_state` values are UNKNOWN. | No ordered source events or transition-derived first-FIXED values are available in the frozen base. |
| Downloaded CSV/XLSX headers | Root-level metadata, reports, comment, contributor, and workbook headers expose only scalar `last_change_time`, `Updated`, or `Last Activity` among change-related fields. No header exposes event/change sequence, field name, old value, or new value. Only headers were read in this check. | A latest-change timestamp or activity summary is not an ordered transition record. |
| Upstream extraction code | Clone commit `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e`. README describes metadata and comment extraction. `Get_meta_data.py` calls `/rest/bug/<id>`; `Bug_comment.py` calls `/rest/bug/<id>/comment`. Bounded code search found no `/history` call or old/new event adapter. The sample CSV has a scalar `Updated` column. | Existing extraction code does not supply the missing ordered history. No upstream crawler or database utility was run. [Inspected upstream commit](https://github.com/GindeLab/EASE_2025_Data_paper/tree/e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e). |

The published counts and our local populations are distinct: the paper reports 119,585 curated reports and 10,351 quality-selected reports, while the selected broad `Bug_meta_data.csv` source normalizes to 196,633 unique bug IDs. The local filtered-report CSV and CTQRS workbook have matching headline counts, but equal counts alone do not prove identical version or membership. Phase 3B did not import optional quality records into its base. Existing source selection and normalization remain appropriate; no evidence here justifies changing them.

## October 2024 and temporal validity

“As of October 2024” is recorded as the paper's reported collection coverage. It is **not** independently verified as the exact historical snapshot time of every CSV field or every comment. In our normalized data, `snapshot_as_of_utc` remains NULL; Phase 3A observation and Phase 3B ingestion occurred in October 2026. These later local clocks do not establish when the upstream export was captured or when a field value became true. Do not claim a 2024 status snapshot or use current metadata as historical state.

The Phase 4 design therefore remains a controlled evidence addition/refresh using separately timestamped API responses. Ordered `/history` events may support carefully validated event-time reconstruction, with later observation time kept distinct; they do not prove that our system had the information at an earlier cutoff. See [Temporal validity](TEMPORAL_VALIDITY.md) and [Phase 4 API enrichment](PHASE04_API_ENRICHMENT.md).

## Resulting action

Keep the frozen Phase 3B inputs and normalization decisions. Continue with the existing capped five-ID user-run API smoke, then the deterministic 50-bug pilot only after reviewing that smoke. `/history` remains the source for explicit status/resolution transitions; current `/bug/<id>` metadata remains a separate consistency refresh. No API requests were made during this reconciliation.

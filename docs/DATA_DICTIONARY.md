# BugsRepo data dictionary and source-field mapping

This dictionary records observed column semantics from headers, bounded safe samples, the source PDF, and the verified Phase 2 audit. A type marked “candidate” is inferred from examples, not a source guarantee. The user-run full Phase 3A report is verified in [PHASE03A_QC.md](PHASE03A_QC.md); canonical Phase 3B counts await its terminal run.

## Canonical entities

| Entity | Natural key | Candidate source columns | Use and caveat |
|---|---|---|---|
| Bug snapshot | numeric bug ID | Metadata: `id`; reports/comments: `bug_id`; upstream sample: `Bug ID` | Join key only after verifying the mapped field. `_id`/`_id_x`/`_id_y` are Mongo-style record identifiers and must not replace `id`/`bug_id` without evidence. |
| Comment/report record | comment or report record ID | Merged comment exports: `id`; filtered reports: repeated `bug_id` plus report marker/text | Repeated bug ID does not prove a duplicate comment. Phase 3B dedup uses `(bug_id, nullable comment_id, UTC timestamp, exact parser-visible text hash, privacy flag)`; differing content versions remain separate. Per-bug profile quantiles count source rows, so repeated record keys can inflate them. Never concatenate parts blindly. |
| Contributor | source-specific user ID | Contributor CSV: `User ID`; report/comment exports: author/creator/contributor columns | Identifying data. Do not join into QA answers by default; minimize and pseudonymize only after review. |
| Relationship edge | source-specific referenced bug ID | `blocks`, `depends_on`, `duplicates`, `dupe_of`, `see_also`, `regressions`, `regressed_by` | Presence in a snapshot indicates a recorded edge, not necessarily historical validity. |

## Field mapping by source

| Logical field | Observed column candidates | Candidate type | Semantic limit |
|---|---|---|---|
| Bug ID | `id`, `bug_id`, `Bug ID` | Integer/string-like identifier | Canonical positive decimal string; NaN/scientific/nonpositive forms rejected. Exact integer `.0` and leading zeroes normalize with original source hash/row lineage retained. |
| Comment/record ID | `id`, `Comment ID`, `comment_id` | String identifier | In comment exports `id` maps to the record/comment key; the adjacent `bug_id` maps to its parent bug. Validate across all rows. |
| Product / component | `product` / `Product`; `component` / `Component` | Categorical string | Product Firefox is narrower than all Firefox engineering work; component is meaningful only with its product/snapshot. |
| Status | `status`, `Status`, `Bug Status` | Categorical string | Snapshot workflow state. It is not a resolution and does not establish a prior state sequence. |
| Resolution | `resolution`, `Resolution` | Categorical string | Outcome/reason such as FIXED, DUPLICATE, INVALID, INCOMPLETE, WONTFIX. `RESOLVED` does not imply FIXED. |
| Bug creation time | `creation_time`, sometimes `creation_time_y` | Timestamp string | In merged files, suffix role requires source validation. Parse rate is not semantic validation. |
| Comment/report time | `creation_time_x`, `creation_time`, `Created On`, `Time` | Timestamp string | The Phase 2 comment mapping parsed `creation_time_x`; exact event meaning and timezone provenance should be checked before temporal use. |
| Latest change time | `last_change_time`, `Last Change Time`, sometimes `Updated` | Timestamp string | Latest update only; it is not an ordered history record or first-FIXED timestamp. |
| Report/comment text | `text`, `raw_text`, `Comment Text`, `Summary` | Free text | May contain private or identifying information. Never place raw values in tracked docs/logs. |
| Private flag | `is_private`, `Is Private`, `private` | Boolean-like string | Filter private comments before QA ingestion; missing/false-like values must not be conflated without checking source encoding. |
| Report quality flag | `contains_steps_to_reproduce`, quality/scoring columns | Boolean/category/score | Derived/selected signal; does not establish population coverage or factual correctness. |
| Relationship fields | names listed in canonical entity table | IDs/list-like strings | Parse only after inspecting source representation; don't assume JSON/list syntax from the header. |
| Commit/revision reference | names containing commit, changeset, revision, landed | string/URL-like | A source field can be an unverified textual reference; it does not prove code landed or fixed the bug. |
| Contributor identity | `author`, `creator`, `assigned_to`, email/name/detail fields, `author_id`, `Contributor_Id` | Sensitive string/identifier | Exclude from released benchmark evidence unless necessary, authorized, and pseudonymized. |

## Source schemas observed

- **Metadata (299 columns):** bug ID, summary/severity/priority, product/component, creation and latest-change times, current status/resolution, relationships, contributor/detail fields, and many product-specific tracking fields. Header inspection did not find an ordered history/event structure.
- **Filtered reports (9 columns):** author, creation time, bug ID, text, report marker, author ID, status, resolution, and steps-to-reproduce flag. It has no product field; join to metadata to attribute product.
- **Comment Parts 1–3 and merged quality export (315 columns):** comment/record key, bug ID, comment time/text, private flag, creator fields, and joined metadata. `creation_time_x` and `creation_time_y` occur in merged data; validate each suffix. Parts 1/2 are byte-identical; full 3A found zero shared profiled comment keys across Parts 1/3, which together cover 52,243 bugs, all joining metadata.
- **Contributor CSV (17 columns):** user identifiers/names, account activity/permissions, and contribution counts. Not needed for F1–F6 as scoped.
- **Upstream sample (9 columns):** Bug ID, type, summary, product, component, assignee, status, resolution, updated. It is a 2025-02-23 sample snapshot with separate provenance.

## Canonical answer evidence requirements

| Question fact | Minimum CSV evidence | Additional requirement |
|---|---|---|
| Current/snapshot product, component, status, resolution (F1) | Bug row, mapped bug ID, source/snapshot citation | State the file and snapshot; never call it live/current without a fetch. |
| Exact first FIXED time or reopen (F2) | Creation time plus ordered `changes` events with field, old/new values, and event time | CSV headers audited so far expose `last_change_time`, not this event sequence; fetch/validate `/history`. |
| Reproducible aggregate (F3) | Frozen input manifest, product/time filters, stable dedup rule, SQL/query | Report exact denominator, exclusions, and whether counts mean bugs, reports, or comments. |
| Dependency/duplicate relationship (F4) | Populated relationship field and target bug ID | Historical “as-of” relationship/status needs event history. |
| Explicit reason (F5) | Visible, dated comment with source/comment key | Exclude private comments and summarize only what the record says; minimize contributor identity. |
| Work hours (F6) | Not available in these CSV schemas | Mark unanswerable; elapsed time is not engineer effort. |

## Phase 3B physical canonical model

The implemented schemas, stable keys, privacy/temporal rules and column meanings are in [PHASE03B_NORMALIZATION.md](PHASE03B_NORMALIZATION.md) and `src/bugzilla_qa/data/normalize.py:SCHEMAS`. Canonical entities: `bugs`, `comments`, `field_changes`, `bug_links`, `documents`, `source_records`; separate optional `quality_records`, plus `provenance`, `run_manifest`, `ingestion_state`, and `sample_membership`.

All entity rows carry source dataset/row key/record ID/URL, event UTC, observed UTC, ingested UTC, text availability, raw-column mapping JSON and content hash. Event time is nullable; metadata creation is not an event date for its snapshot status. `snapshot_as_of_utc` is NULL and `history_state` UNKNOWN. Actual `field_changes` is empty until explicit history enrichment. `fix_metrics` never derives transitions from last-change timestamps.

`observed_at_utc` is conservative local QC observation time, not original publication date; `ingested_at_utc` is the new version start. A Bugzilla source URL identifies the bug, adding a comment anchor only if an explicit comment-count field exists. It does not prove this export equals the live page. `source_row_key` combines full audited file hash and logical CSV ordinal, including quoted multiline records; full imports verify that hash. Limited runs label it expected source identity without claiming a completed input checksum.

`source_records.disposition` is NORMALIZED, DUPLICATE, CONFLICT_VARIANT or QUARANTINED, allowing exact source-to-canonical accounting. Raw field **mapping** is retained; original field values remain in ignored read-only CSVs, except minimized normalized variant fields needed for inspection. Private/unknown-privacy text is withheld. Partitioned Parquet and DuckDB stay ignored/local.

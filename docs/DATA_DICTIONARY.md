# BugsRepo data dictionary and source-field mapping

This dictionary records observed column semantics from headers, bounded safe samples, the source PDF, and the verified Phase 2 audit. A type marked “candidate” is inferred from examples, not a source guarantee. Phase 3A's complete report adds sample-based dtype candidates and null/date measures without publishing cell values.

## Canonical entities

| Entity | Natural key | Candidate source columns | Use and caveat |
|---|---|---|---|
| Bug snapshot | numeric bug ID | Metadata: `id`; reports/comments: `bug_id`; upstream sample: `Bug ID` | Join key only after verifying the mapped field. `_id`/`_id_x`/`_id_y` are Mongo-style record identifiers and must not replace `id`/`bug_id` without evidence. |
| Comment/report record | comment or report record ID | Merged comment exports: `id`; filtered reports: repeated `bug_id` plus report marker/text | Repeated bug ID does not prove a duplicate comment. Prefer stable `comment_id`/`id`; fallback dedup uses `(bug_id, timestamp, SHA-256(text))` only when a comment ID is absent. Per-bug profile quantiles count source rows, so repeated record keys can inflate them. Never concatenate parts blindly. |
| Contributor | source-specific user ID | Contributor CSV: `User ID`; report/comment exports: author/creator/contributor columns | Identifying data. Do not join into QA answers by default; minimize and pseudonymize only after review. |
| Relationship edge | source-specific referenced bug ID | `blocks`, `depends_on`, `duplicates`, `dupe_of`, `see_also`, `regressions`, `regressed_by` | Presence in a snapshot indicates a recorded edge, not necessarily historical validity. |

## Field mapping by source

| Logical field | Observed column candidates | Candidate type | Semantic limit |
|---|---|---|---|
| Bug ID | `id`, `bug_id`, `Bug ID` | Integer/string-like identifier | Preserve as text during import; do not coerce malformed or leading-zero IDs silently. |
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
- **Comment Parts 1–3 and merged quality export (315 columns):** comment/record key, bug ID, comment time/text, private flag, creator fields, and joined metadata. `creation_time_x` and `creation_time_y` occur in merged data; validate each suffix. Parts 1/2 are byte-identical; Part 3 remains under full overlap review.
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

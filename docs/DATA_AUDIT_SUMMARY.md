# Phase 2 data audit summary

**Status:** The user's full run stopped while scanning comments Part 1 because Python's CSV reader rejected an embedded NUL. Metadata (225,196 rows) and filtered reports (120,047 rows) are checkpointed as complete. The tested parser fix strips and counts NUL characters; resume with `bash scripts/run_phase02_audit.sh --resume`. No full comment scan or Parts 1/2 checksum has completed.

After resuming, review the ignored `audit_summary.json` and `audit_report.json` under `outputs/audit/phase02/<run-id>/`, then replace this note with aggregate results only.

Record source row counts and schema sizes; timestamp parse rates; bug-ID join coverage; duplicate-key totals; product distribution; any NUL characters removed by the parser; Parts 1/2 SHA-256 equality and shared record-ID count; private/contributor field presence; history/event-field gaps; and unresolved license/privacy decisions. Do not include raw row text, email addresses, usernames, or raw IDs.

# Phase 2 data audit summary

**Status:** Pending the user's full terminal run. No full row scan or Parts 1/2 checksum has been executed in the agent session.

After running `bash scripts/run_phase02_audit.sh`, review the ignored `audit_summary.json` and `audit_report.json` under `outputs/audit/phase02/<run-id>/`, then replace this note with aggregate results only.

Record source row counts and schema sizes; timestamp parse rates; bug-ID join coverage; duplicate-key totals; product distribution; Parts 1/2 SHA-256 equality and shared record-ID count; private/contributor field presence; history/event-field gaps; and unresolved license/privacy decisions. Do not include raw row text, email addresses, usernames, or raw IDs.

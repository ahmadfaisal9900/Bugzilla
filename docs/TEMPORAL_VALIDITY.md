# Temporal validity and availability

## Decision

Use a **controlled evidence addition/refresh** as the primary temporal experiment: compare the frozen Phase 3B local corpus with a separately labeled, selectively fetched public Bugzilla API overlay. This measures the effect of adding refreshed evidence to the local corpus. It is not a genuine historical snapshot comparison, real-time update experiment, or concept-drift result. A narrow **RETROSPECTIVE REPLAY** of verified dated history events may be reported separately, with that exact label and a cutoff-availability caveat.

Do not claim a 2024 T0. The source-paper snapshot date does not establish the local export's as-of date. Phase 3A observation was `2026-10-22T01:56:55Z`; Phase 3B ingestion began `2026-10-22T02:35:42.410317Z` and completed `2026-10-22T02:44:22.980432Z`. These are local QC/ingestion clocks, not the source export date. The Phase 3B `snapshot_as_of_utc` remains NULL/UNKNOWN.

For a controlled comparison, label the frozen Phase 3B artifact as the **base corpus (locally available after its completed ingestion)**. Label each API row by its own `observed_at_utc` fetched time and `ingested_at_utc`; do not assign one earlier global timestamp to the refreshed corpus. API current metadata is eligible only as a newly observed refresh. It must never be copied backward into a historical state.

## Field-level eligibility

| Evidence | Event time | Observation/availability time | Eligible claims and exclusions |
|---|---|---|---|
| Phase 3B product/component/status/resolution | Archive's implicit snapshot time is UNKNOWN | Local normalized corpus observed/ingested in Oct 2026 | F1 may describe the **archive-recorded** value; not live/current Bugzilla and not a 2024 as-of value |
| Bug creation timestamp | `creation_time` is the bug's creation event when valid | Local CSV observation/ingestion is Oct 2026; source export date unknown | Can support age/creation facts; does not date the accompanying snapshot status |
| CSV comments | `creation_time_x` as mapped record time, subject to source semantics | Local archive observed in 2026; exact export availability unknown | Can cite a dated comment as recorded in the archive. Do not assert it was available to a system at a historical cutoff based on event date alone |
| Explicit `/history` changes | API event `when` | Per-response `fetched_at_utc`, then local `ingested_at_utc` | Can support dated state transitions and an explicitly labeled retrospective replay after ordering, timestamp and current-consistency QC |
| Current `/bug/<id>` refresh | Fields are current values at request time; `last_change_time` is not the transition time | Exact API `fetched_at_utc` and local `ingested_at_utc` | Use only in the API-refresh condition. Never treat current status/resolution as an old event or infer first FIXED |
| API comments | Comment `creation_time` is the event timestamp | Comment response fetch and local ingestion are later observations | Fetch only where the base CSV has no comments by default; retain only `is_private=false`, redact emails, and do not equate creation time with earlier system availability |
| API relationship changes | History event `when`, only when a configured explicit field change yields a target | History response fetch and overlay ingestion | May support the explicit change event; no initial edge, current edge, or direction is guessed |
| Engineer-hours | Not present | Not present | Unknowable from elapsed days, status changes, comments or current fields |

## Cutoff rules

`run_phase04_temporal_qc.sh` has two different modes:

- `--mode strict`: a change is eligible only if its event time, response observation time and local ingestion time are all valid and at or before the cutoff. This tests evidence availability by that cutoff for this overlay. The source archive status still has no verified historical snapshot date.
- `--mode retrospective-replay`: a substantiated event with `event_time_utc <= cutoff` may be replayed even when it was fetched later. The report labels it **RETROSPECTIVE REPLAY**. It does not prove the system or analyst possessed that evidence at the cutoff.

Missing/invalid dates remain excluded or UNKNOWN. A future event later than its recorded response observation time invalidates the parsed history for F2. Strict availability requires both observation and ingestion before the cutoff. Neither mode makes current metadata historically eligible. Status changes absent from `/history` are not reconstructed from present status, creation time or `last_change_time`.

## Phase 4 interpretation

The base/enriched comparison can support a controlled evidence-addition statement only, with the exact candidate list, endpoint success/denial counts, response and ingestion clocks, and request budget reported. History-derived answers may be temporally reconstructed from explicit events, but historical information availability remains unknown unless a trustworthy archived observation exists. No such independent dated v0/v1 source snapshot has been verified. Do not call results “concept drift,” “real-time freshness,” or “as-of 2024” on the current evidence.

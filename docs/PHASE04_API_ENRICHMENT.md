# Phase 4 — evidence gap and selective API enrichment

## State and gate

**USER PILOT VERIFIED as Phase 5 input; no 200-bug study run claimed.** Completed run `cohort-8bb3150d29a598d8` has 50/50 histories and metadata responses, 147 successful GET attempts, 884 changes, 13 first-FIXED cases and 37 UNKNOWN. Six small overlay hashes and 147 cached response hashes were checked offline; parsed histories, timestamps, current-metadata differences and event hashes match. There are 17 REOPENED entries, 7 retained source/current field differences, one same-time group and zero configured API link events. Source snapshot time remains UNKNOWN. See `docs/PHASE05_BENCHMARK.md` for the exact pinned identity and candidate exclusions. No new live request was made by the agent. Base run remains `run-20261022T023542Z-1182018`.

The BugsRepo paper/data reconciliation found no ordered field-change events in the selected CSV headers, normalized Phase 3B data, or bounded inspection of upstream extraction code at commit `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e`. The paper's October 2024 date is reported collection coverage, not a verified exact snapshot time for every local CSV field. Existing extraction and normalization choices stand; see [PAPER_DATASET_RECONCILIATION.md](PAPER_DATASET_RECONCILIATION.md).

## Original local evidence gap, measured on the frozen Phase 3B seed-317 sample

The planner read only the 3,000 sampled Firefox bug IDs and aggregate comment/link counts from the frozen Phase 3B DuckDB. It did not read or emit comment bodies.

| Local question evidence | Observed result | Supported answer scope |
|---|---:|---|
| F1 snapshot facts | 3,000/3,000 sampled rows have product, component, status, creation time, and summary | Local archive-recorded facts; not live status or a verified 2024 snapshot |
| F2 first FIXED/reopen history | 0 canonical field changes; 0 exact first-FIXED values | UNKNOWN pending validated `/history` responses |
| F3 reproducible aggregates | 3,000 sampled Firefox bugs; all 18 observed status/resolution groups represented in the base sample | Aggregate counts with frozen denominator, product and sample definition |
| F4 explicit links | 4,643 sampled source edges; 3,369 target IDs in the corpus; 1,274 outside it | Snapshot-recorded relationship only; historical edge validity is unknown |
| F5 dated reason text | Public CSV comments exist for some sample bugs, but source export availability time is unknown | Cite a visible comment and its record timestamp; no “available at T0” claim |
| F6 engineer-hours | No source field or validated method | Unanswerable; elapsed calendar duration is not work time |

Sample outcomes include 700 with resolution FIXED, 140 with status REOPENED, 617 in NEW/ASSIGNED/UNCONFIRMED, and 2,539 bugs with no comments. The candidate planner preserves these positive, negative, duplicate/incomplete and zero-comment cases. These counts overlap by definition where applicable and use the 3,000 sampled-bug denominator.

## Candidate and request plan

`python -m bugzilla_qa.data.phase04 plan` makes an ignored, deterministic manifest from the 3,000-bug seed-317 sample. The first 50 candidates form the pilot; a 100–300 study cohort can be selected after reviewing pilot signal and budget. Selection reserves every observed status/resolution stratum, then balances FIXED, REOPENED, NEW, DUPLICATE, INCOMPLETE, source links, comment presence, year, component and seeded tie order. The default 200-candidate plan is a target, not a required crawl.

The bounded call plan is:

| Cohort | Required endpoints | Missing-CSV-comment endpoint allowance | Expected calls | Worst case with 3 retries per request |
|---|---:|---:|---:|---:|
| Pilot (50) | 50 `/history` + 50 current `/bug/<id>` | 47 `/comment` | 147 | 588 |
| Study target (200) | 200 `/history` + 200 current `/bug/<id>` | 188 `/comment` | 588 | 2,352 |

Counts are GET attempts and include retry headroom; only bugs with zero CSV comments or at least one missing/empty CSV comment body need the optional comment endpoint by default. Because Bugzilla returns a bug's comment list, the overlay skips exact `(bug ID, comment ID, event time, text hash)` CSV matches, records when public API text fills an empty CSV row, and retains differing versions as source conflicts. `--max-requests` is an explicit cumulative cap across resumptions. Network code is unauthenticated public GET only, serial/paced, timed, response-size limited, and honors `Retry-After` on 429/5xx. 403/404/410 and malformed/inaccessible responses stay UNKNOWN. There is no key, proxy rotation, login, private-bug access, crawler, or API call in planning/dry-run.

Bugzilla documents history as `bugs[].history[]` with `when`, `who`, and `changes[]` entries containing `field_name`, `removed`, and `added`; the implementation validates this response shape and pseudonymizes actors. The user-run smoke is still required to verify the live response shape/version before interpreting the study. See the [Bugzilla REST Bug/History API](https://bugzilla.readthedocs.io/en/latest/api/core/v1/bug.html) and [REST Comment API](https://bugzilla.readthedocs.io/projects/harmony/en/latest/api/core/v1/comment.html). Comments enter the sidecar only when `is_private` is explicitly false; private or unknown-privacy bodies are withheld. Emails in public bodies are redacted. Raw compressed API envelopes can contain source PII and remain ignored under `outputs/phase04/api_cache/`.

## Outputs and quality checks

- `outputs/phase04/candidates/<plan-id>/candidate_manifest.json` and `evidence_gap_report.json`: deterministic IDs, sample seed, tags, identity and request estimates.
- `outputs/phase04/api_cache/<bug-id>/{history,bug,comment}.json.gz` and per-attempt `.attempt-NN.json.gz`: compressed raw-response envelopes with request URL, requested ID, fetch time, status, response shape/server version when present, SHA-256, visibility and error label.
- `outputs/phase04/enrichment/cohort-<manifest-hash>/checkpoint.json`: resumable endpoint-level state, no raw payloads; raw responses are reloaded from compressed cache.
- `field_changes.jsonl`, `field_changes_rejected.json`, `api_bug_refresh.json`, `api_link_changes.json`, `api_comments.json`, `api_enrichment.duckdb`, `summary.json`: separate API overlay; Phase 3B files are never overwritten. `field_changes` rows require stable source row key, source URL, explicit event UTC, observed/fetched UTC, ingested UTC, field mapping, content hash and text-availability flag. Invalid or future-timestamp rows are excluded from the queryable overlay and counted in the rejection report.
- `outputs/phase04/logs/`: script logs. All are ignored local artifacts.

History changes are sorted for inspection while original event/change sequence is retained. Reordered, malformed, same-time and repeated changes are flagged. No initial status is synthesized. A candidate first-FIXED is emitted only for an explicit `resolution` change to `FIXED`, after creation, in a fully parsed ordered history not later than its observed fetch time. A current FIXED resolution or `last_change_time` never creates F2 evidence. Reopens remain separate events; later DUPLICATE/INVALID outcomes are not FIXED transitions. Source-vs-current differences are retained as differences, not overwritten. Historical link changes are imported only for relationship field names explicitly confirmed after smoke and configured as `--link-field FIELD=RELATION`.

## User-run order

From the existing repository root, first make the deterministic local plan. Then perform the capped five-ID public smoke. Inspect `summary.json` and `checkpoint.json` without printing raw cache files. If the API shape is valid, continue the 50-ID pilot with the same manifest and checkpoint. `--max-requests` is cumulative; raise the cap on resume, never lower it below requests already made. Consider `--study --limit N` for 100–300 only after pilot quality, actual request count and privacy review support it.

```bash
PYTHONPATH=src python -m bugzilla_qa.data.phase04 plan --root . --study-size 200
bash scripts/phases/run_phase04_api_smoke.sh --limit 5 --max-requests 40
bash scripts/phases/run_phase04_enrich.sh --pilot --max-requests 588 --resume
```

The smoke uses only the two required endpoints. The user-run pilot may request `/comment` only where CSV comments are absent or have empty bodies; `--no-comments` disables that endpoint. Its 588 cap covers 100 required history/metadata + 47 comment calls, with up to 3 retries each; expected calls are 147. The default 200-bug plan expects 588 and has a 2,352 worst-case cap. Use `--dry-run` first. To increase the study after pilot review, resume the same planned manifest with `--study --limit 100` (or 200/300) and a cumulative cap based on that manifest's estimate. Do not run this automatically. Verify output state, endpoint counts, history parse rate, explicit FIXED count, valid F2 cases, conflicts, comment privacy, link coverage, hashes and timestamp eligibility before updating status. A smoke alone does not verify F2.

## Acceptance

The completed user pilot now passes the offline verification gate. A larger cohort still needs a separate reviewed run. API link-history coverage remains zero because no field adapter was configured. Preserve all counts, explicit event timestamps, source conflicts and privacy decisions in the pinned reports; only eligible conflict-free history cases can enter Phase 5. The source snapshot date remains UNKNOWN.


The completed user pilot passes the bounded offline prerequisite audit recorded in Phase 5. Pilot evidence is sufficient to implement reduced-coverage benchmark construction; it does not establish 30 valid F2 duration questions, historical snapshot availability, or a larger study cohort.

# Phase 3B: canonical local data foundation

**VERIFIED from the user full terminal run.** Run `run-20261022T023542Z-1182018`, manifest state COMPLETE, identity `0454ce48d6ed7a52973aea5474bee18304e33b65970c2c8c69dccdd0a630b663`. The agent reviewed the latest run aggregate JSON and made read-only aggregate queries against its DuckDB; no CSV reimport or raw-content inspection was performed. Phase 3A QC is documented in [PHASE03A_QC.md](PHASE03A_QC.md).

## Selected inputs

`configs/phase03b_sources.json` freezes base metadata + comments Parts 1 and 3. Broad metadata retains open, reopened, DUPLICATE, INVALID, and other non-FIXED outcomes. Comments are FIXED-selected, so their presence is never a sampling eligibility rule. Part 2 is proven identical; metadata-all is a problematic near-repeat, not extra independent evidence. Filtered reports and steps export are available only through `--include-quality`, in separate QUALITY tables/documents; they cannot replace base metadata/comments. Contributor and separately dated upstream sample are excluded.

Paths come from ignored `configs/data_paths.local.yaml`, whose tracked template remains `configs/data_paths.example.yaml`. Before any import, validate saved full QC, configured relative paths, exact input size/mtime signatures, schema mapping, and Part 2 exclusion proof. Full ingestion rechecks whole-file hashes and logical row counts while streaming; changed input stops finalization. Limited runs have prefix counts only and no verified input-hash claim.

## Canonical model

Every entity carries `source_record_id`, `source_dataset`, `source_row_key`, `source_url`, `event_time_utc`, `observed_at_utc`, `ingested_at_utc`, `text_availability`, JSON `raw_field_mapping`, and `content_hash`. Nullable timestamps and explicit UNKNOWN states represent absent evidence.

| Table | Stable key / purpose |
|---|---|
| `bugs` | Positive canonical decimal `bug_id`; product/component, summary, nullable description, opened time, snapshot status/resolution/assignee, last change, nullable snapshot date, history state. Assignee is deliberately NULL to minimize identity. |
| `comments` | SHA-256 of parent bug ID, comment ID (nullable), UTC event time, exact parser-visible text hash, and private flag. Different parents, comment IDs, times, or content versions survive; identical repeated exports deduplicate. |
| `field_changes` | `change_key`, bug ID, field/old/new values and event provenance. **Empty for these inputs**; no changes synthesized. Future enrichment needs a reviewed adapter. |
| `bug_links` | Hash of source bug, relation and target; parsed explicit numeric targets or URLs, target-in-corpus flag, historical validity UNKNOWN. Empty lists are not edges. |
| `documents` | Hash of entity kind/key; snapshot bug documents and dated comment documents, body, BASE/QUALITY tier, temporal availability state. Snapshot documents have unknown event validity. |
| `source_records` | Source label + full-file hash + padded logical CSV row number; parent ID, canonical entity key/hash, disposition, quarantine reason, minimal normalized field mapping. All logical rows are accounted for, including duplicates and invalid rows. No raw names/emails/comment bodies in this table. |
| `quality_records` | Separate optional records and quality flags; clean parent join required. Never augment base denominators silently. Unknown privacy means withheld text. |
| `provenance` / `run_manifest` | Relative source path, input hash/size/mtime, field map, tier and observation time; frozen code/QC/config/options identity. JSON manifest adds output hashes, versions and completion state. |
| `sample_membership` | Bug ID, isolated seed and component/year/status/resolution stratum; mirrored in `sample_manifest.json`. |

IDs reject NaN, scientific notation and nonpositive values. Exact integer forms such as `123.0` and leading zeroes normalize to canonical positive decimal IDs; raw byte hashes and row keys preserve source lineage. Product/component use Unicode NFC and collapsed whitespace; Firefox/Core/Toolkit product spelling is canonicalized. Original values remain in read-only ignored sources, identified by field mapping and file/row hash. Metadata winner is the first logical row per bug, **not** a claimed latest snapshot; identical rows are DUPLICATE, differing canonical variants are CONFLICT_VARIANT and remain inspectable in `source_records.normalized_fields`.

## Time, history and privacy

Timezone-aware ISO timestamps normalize to UTC; missing/malformed/naive event times remain unknown (invalid comment events are quarantined). DuckDB TIMESTAMPTZ stores instants; set `TimeZone='UTC'` in query sessions to display UTC. Metadata `opened_at_utc` is creation, not a timestamp for its current status. `last_change_at_utc` is retained but never treated as a transition. `snapshot_as_of_utc` is NULL because the source export date is not established. Three clocks are kept distinct: source event time comes from the mapped CSV event field (metadata creation or comment creation); verified 3A QC observation is `2026-10-22T01:56:55Z`; Phase 3B ingestion starts at `2026-10-22T02:35:42.410317Z` and finishes at `02:44:22.980432Z`. All 225,196 metadata creation fields and 511,057 comment event fields parsed as timezone-aware UTC instants. Original export/snapshot date is not established (`snapshot_as_of_utc` is NULL). Neither observed-at nor ingestion-at is backdated to the source event or file mtime.

`fix_metrics` and `fix_metrics_as_of(t)` calculate first FIXED elapsed calendar duration only from explicit resolution transitions to FIXED, after creation. Reopening does not reset the first FIXED time. DUPLICATE/INVALID are not fixes. No qualifying transition means UNKNOWN, including snapshot-FIXED bugs. Missing reopen events mean UNKNOWN, not false. Developer-hours are always UNKNOWN.

`documents_as_of(t)` requires dated public BASE text and both event and observation time <= cutoff. It excludes snapshot status documents and all QUALITY documents. `field_changes_as_of(t)` has the same dual-time guard; `fix_metrics_as_of(t)` also omits bugs created or first observed after the cutoff. These conservative helpers prevent invented historical evidence; they do not create v0/v1 snapshots or choose T0/T1. Sources first observed in 2026 cannot establish that this local system possessed them in 2024.

Private comments retain parent/key/provenance with body withheld. Missing/unrecognized privacy flags also withhold text. Public text may still contain personal information, so databases and Parquet remain ignored/local; no publication or redistribution is authorized by this phase. Dataset license review is still unresolved. No crawler, API, MongoDB, proxy utility or upstream code is executed/copied; Phase 3A upstream provenance remains `e0f44e656ab8fee2f93a0adbce881dca5bdc8c9e`.

**F2 gap:** all exact first-FIXED, reopen sequence and historical-state questions remain unsupported for the actual selected CSVs until validated `/history` enrichment; creation/latest-change values alone are available. **F4 gap:** only explicit recorded snapshot relationships are supported, including targets outside the corpus. Historical edge validity, omitted links, past target status and verified commit/fix attribution require API/history/explicit link evidence. Do not claim complete graph coverage.

## Sampling

Default target is 3,000 Firefox-product bugs, seed 317; 2k–5k is a planning range, not a coverage claim. Take fewer if eligible coverage is smaller. Reserve one bug per observed status/resolution outcome, then round-robin product/component/creation-year/outcome strata using SHA-256(seed:bug ID). The hash order is independent of global random state and CSV chunk size. If the target cannot cover all outcome groups, stop and ask for a larger target. Keep bugs with zero comments and non-FIXED/open outcomes. All products remain in canonical tables; `--product ALL` changes sampling only. Firefox-product-only excludes some Firefox engineering under Core/Toolkit. This is a reproducible coverage sample, not population-proportional estimation.

## Commands (user terminal only)

From the existing Project root, install the free local dependency in the interpreter used by the script:

```bash
python -m pip install duckdb==1.4.4
bash scripts/phases/run_phase03b_normalize.sh --dry-run
bash scripts/phases/run_phase03b_normalize.sh
```

The new project extra is also available via `pip install -e '.[data]'` on Python >=3.10; direct DuckDB installation avoids changing the existing Python 3.9 environment/project metadata. No PyArrow dependency or paid API is needed.

New invocations create a version under `outputs/normalization/phase03b/run-<UTC>-<pid>/` and update its ignored LATEST_RUN pointer. `--limit 20` makes a separate bounded smoke version. `--resume` reuses the latest version; repeat every original nondefault option. Identity includes input signatures, QC hash, code hash, seed, limit, library version and options; incompatible resumes fail and preserve previous outputs. Completed matching versions skip import/export and check artifact existence/sizes; SHA-256 hashes remain available for independent integrity checking.

Checkpoints commit canonical inserts, every source-row disposition and a logical-row watermark in one transaction every 2,000 rows (configurable). Interrupted sources restream/hash their prefix to reach the watermark without duplicate inserts; completed files skip. Finalized runs are reused; each fresh run/export uses a new version. Partial old exports are preserved after a failed finalization. Only newly created scratch batch files are removed. No raw file or prior run is deleted.

Reserve **5–10 GB** output/spill disk for approximately 2.0 GB of selected raw inputs. Full runtime is unmeasured; allow tens of minutes or longer, dependent on disk/CPU and indexing. DuckDB defaults to one thread and a 512 MB database budget (`--memory-limit`); Python additionally holds one CSV record plus a bounded 2,000-row normalized batch (`--chunk-size`). A single unusually large cell/record is not a strict RAM cap; reduce batch size if necessary. All memory/disk figures are planning estimates, not benchmark measurements.

## Outputs and acceptance

- `canonical.duckdb`: queryable local tables, provenance, sample and temporal helper macros.
- `exports/export-*/<table>/partition_source=*/...parquet`: source-partitioned ZSTD entity exports. Empty tables still get a schema-bearing Parquet file; small manifest/sample tables are unpartitioned.
- `manifest.json`: frozen identity, source hashes/mapping, completed state, versioned export path and SHA-256/size of database, every Parquet file and QC/example/sample artifacts.
- `qc_report.json`: per-source original/scanned counts and disjoint NORMALIZED/DUPLICATE/CONFLICT_VARIANT/QUARANTINED accounting, sanitization, invalid dates, orphan counts, parent joins, product/outcome counts, privacy, unknown history and sample coverage. Duplicate Part 2 rows are excluded explicitly in the manifest rather than imported.
- `anonymized_examples.json`: up to 20 deterministic manually inspectable structural examples (20 on the fixture), pseudonymous bug alias and facts, no raw ID/name/email/body. Fewer are reported honestly when fewer bugs exist.
- `sample_manifest.json`, `summary.json`, timestamped `terminal.log`, and transactional `ingestion_state` in DuckDB.

Example local query after reading `manifest.json` (substitute the actual run path):

```python
import duckdb
db = duckdb.connect("outputs/normalization/phase03b/<run>/canonical.duckdb", read_only=True)
db.execute("SET TimeZone='UTC'")
print(db.sql("SELECT product, count(*) AS bugs FROM bugs GROUP BY product").fetchall())
print(db.sql("SELECT fix_duration_state, count(*) FROM fix_metrics GROUP BY ALL").fetchall())
```

The full run has been checked against these acceptance gates; measured results follow. Fixture acceptance covers quoted multiline CSV, NaN IDs, explicit timezones, malformed timestamps, duplicate files/content versions, private text, rerun/resume, reopened/DUPLICATE/INVALID cases and future cutoffs. Tests inject explicit history only into a synthetic database to exercise rules; no such history is asserted for actual sources.

### Recorded agent validation

The complete tiny-fixture suite passed: 14 tests in approximately seven seconds; the five Phase 3B tests also pass separately. A retained **synthetic-only** report is at ignored `outputs/normalization/phase03b/synthetic-fixture-20261022T023408Z/run/`: 39 source rows -> 24 bugs, 7 comments, 4 links, 31 documents, zero actual transitions, and 20 anonymized examples. Fixture source hashes and all artifact hashes were checked; resume/re-import retained sample identities. These numbers are test data, not BugsRepo results. Actual source selection was validated using a no-scan script dry-run only.


## Verified full run `run-20261022T023542Z-1182018`

The latest pointer selects this run. Manifest identity is `0454ce48d6ed7a52973aea5474bee18304e33b65970c2c8c69dccdd0a630b663`; state COMPLETE; `limit=null`; base metadata + Parts 1/3 only; quality tier disabled. DuckDB 1.4.4 / 512 MB. All source rows are FULL_VERIFIED and row counts/hash values match Phase 3A: metadata 225,196 / 350,195,270 bytes / `17457b6c451e8462c49c98678cba67debb8f0ea982267ced367ff2d2efef0df3`; Part 1 500,000 / 1,617,552,267 bytes / `2ae7f5e4d49f8c459920e9747f8cfc121ee33bba3296d12268be6f1f018b97b1`; Part 3 11,057 / 36,310,793 bytes / `77c74ce85cc7361dd630efaf5aac31d66683c68ce533ebc26f6aeb55d767e616`. Part 2 (500,000 rows) is excluded by verified identical bytes; metadata-all near-repeat is excluded per the selection manifest.

Source accounting is exact (NORMALIZED / DUPLICATE / CONFLICT_VARIANT / QUARANTINED): metadata `196,633 / 28,533 / 30 / 0`; Part 1 `408,401 / 91,599 / 0 / 0`; Part 3 `11,057 / 0 / 0 / 0`. `source_records`=736,253, matching selected source row totals. Canonical unique bugs=196,633; comments=419,458; field changes=0; bug links=308,132; documents=616,091; quality records=0. Parts 1/3 yielded 52,243 distinct comment-parent bugs, all joined to metadata. Zero orphan source rows and zero canonical orphan comments. 28,533 metadata duplicate rows are 12.67% of source rows; 30 conflicting variants are 0.0133%; Part 1 duplicate rows are 91,599/500,000 (18.32%); all three sources have zero quarantine.

Parsed link counts by explicit relation: blocks 97,423; depends_on 86,615; duplicate_of 18,796; has_duplicate 17,348; regressed_by 15,518; regresses 12,991; see_also 59,441. Sum=308,132; 79,350 target references are outside the canonical bug corpus. These are recorded snapshot links; historical validity is UNKNOWN.

There are 25,025 distinct canonical Firefox-product bugs. Seed 317 sample contains exactly 3,000 unique Firefox bugs and represents all 18 of 18 eligible Firefox status/resolution combinations. The sample includes 757 NEW/ASSIGNED/UNCONFIRMED/REOPENED bugs (140 REOPENED) and 2,539 bugs with no canonical comment. This confirms negative/zero-comment cases are retained; it does not make Firefox-product equivalent to all Firefox engineering.

Canonical comments: 414,378 AVAILABLE bodies and 5,080 EMPTY; private-flag and unknown-privacy counts are both zero in imported comments. There are zero withheld-private/unknown-privacy search documents with bodies. Twenty anonymized examples were present with only pseudonymous alias, aggregates and snapshot labels; no raw comment, bug ID, email or reporter name appears. This checks privacy gating in the output, not legal redistribution rights.

The database reports zero field changes, 196,633 UNKNOWN first-FIXED durations, zero populated first-FIXED timestamps and zero inferred reopen observations. The JSON summary and DuckDB agree. Source event time is the mapped CSV creation/event field; observed-at is verified QC time `2026-10-22T01:56:55Z`; ingested-at is the 3B run start `2026-10-22T02:35:42.410317Z`. All source snapshot dates remain NULL. This output contains no fabricated first-FIXED duration or historical snapshot.

All 19 manifest-listed artifacts exist and match their recorded byte sizes; all have SHA-256 fields. DuckDB is 1,892,691,968 bytes; Parquet partitions and reports are under `exports/export-114543749fc4/`. Large DB/Parquet files were not rehashed during review. The small manifest's external SHA-256 at review was `3c924a3741c75230d3a307b7335814f7075108528eebc43a50e2f827bb5daccf`. The ignored summary, QC report and manifest agree. Output paths remain ignored and are not staged.

**Phase 4 is next.** F2 still needs validated `/history` to answer first-FIXED/reopen/as-of questions. F4 supports the 308,132 recorded snapshot link references only; 79,350 point outside this corpus, and historical link/target status cannot be established. Keep both gaps explicit in Phase 4.

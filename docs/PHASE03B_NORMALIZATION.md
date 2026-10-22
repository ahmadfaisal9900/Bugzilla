# Phase 3B: canonical local data foundation

**AWAITING_TERMINAL_RUN.** Implemented and tested with synthetic fixtures only. The saved full Phase 3A QC was reviewed; see [PHASE03A_QC.md](PHASE03A_QC.md). Actual CSVs were not ingested in the agent session. The authoritative root/remote and roadmap are unchanged.

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

Timezone-aware ISO timestamps normalize to UTC; missing/malformed/naive event times remain unknown (invalid comment events are quarantined). DuckDB TIMESTAMPTZ stores instants; set `TimeZone='UTC'` in query sessions to display UTC. Metadata `opened_at_utc` is creation, not a timestamp for its current status. `last_change_at_utc` is retained but never treated as a transition. `snapshot_as_of_utc` is NULL because the source export date is not established. Observation time is the verified 3A QC timestamp; ingestion time is frozen when a version starts. Neither is backdated to creation or file mtime.

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

Verify full hashes/counts/accounting, dedup/conflict rates, negative outcomes, zero canonical orphans, missing history and the 20 examples before accepting the terminal run. Exact normalized corpus/sample counts await that review. Fixture acceptance covers quoted multiline CSV, NaN IDs, explicit timezones, malformed timestamps, duplicate files/content versions, private text, rerun/resume, reopened/DUPLICATE/INVALID cases and future cutoffs. Tests inject explicit history only into a synthetic database to exercise rules; no such history is asserted for actual sources.

### Recorded agent validation

The complete tiny-fixture suite passed: 14 tests in approximately seven seconds; the five Phase 3B tests also pass separately. A retained **synthetic-only** report is at ignored `outputs/normalization/phase03b/synthetic-fixture-20261022T023408Z/run/`: 39 source rows -> 24 bugs, 7 comments, 4 links, 31 documents, zero actual transitions, and 20 anonymized examples. Fixture source hashes and all artifact hashes were checked; resume/re-import retained sample identities. These numbers are test data, not BugsRepo results. Actual source selection was validated using a no-scan script dry-run only.

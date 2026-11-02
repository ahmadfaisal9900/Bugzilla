# Sharing the frozen Firefox sample and 50-bug history pilot

The data lives outside Git on the project owner's machine. Do not download the full dataset or rerun normalization/API collection just to share this sample. Send the generated `.tar.gz` privately to your project partner using your usual file-sharing service. Source-text redistribution/license review is unresolved; this handoff is for the course team, and must not be published in GitHub or a public dataset.

## Owner: create the archive in your terminal

From the existing Project repository, activate the environment containing DuckDB 1.4.4 (for example `conda activate iqfm`), then:

```bash
bash scripts/run_phase05_share_sample.sh --dry-run
bash scripts/run_phase05_share_sample.sh --resume
```

The runner prints the exact archive path under ignored `outputs/share/firefox-sample-seed317-<version>.tar.gz`. Share that **one archive**. Its sibling directory contains `summary.json` with actual table counts, archive size and SHA-256, plus `checkpoint.json`; logs are timestamped under `outputs/share/logs/`. To choose an explicit new location use `--output outputs/share/my-sample-handoff --resume`. `--limit 2` makes a marked preview, not the requested complete sample. Do not share a preview as the full corpus.

The export reads existing databases only, makes no API requests, and never opens raw CSVs. It filters parent records using the exact frozen membership; it does not choose a new random sample. Each table is committed separately and reused on `--resume` for the same pinned sources/version. Changed inputs require a new output directory; old outputs are preserved. DuckDB uses two threads and a 512 MB memory limit by default (`--memory-limit` is configurable). Allow time for scanning selected tables in the 1.89-GB source and additional scratch disk; full-run timing and archive size have not been measured by the agent. Only small fixtures were executed in-session.

## What is in the archive

- `sample.duckdb`: exactly the **3,000 Firefox-product bugs, seed 317**, their `sample_membership`, and related canonical `comments`, `documents`, `bug_links`, `source_records`, `quality_records`, base `field_changes`, and materialized base `fix_metrics`. `provenance` and `run_manifest` retain the original full-source context.
- `api_enrichment.duckdb`: byte-identical separate overlay for the **50-bug pilot**, all belonging to the 3,000-bug sample. Its tables are `field_changes`, `api_bug_refresh`, `api_comments`, `api_link_changes`.
- `sample_manifest.json`: exact sample IDs and strata. `history_summary.json` and `history_response_manifest.json`: saved aggregate QC and per-history URL/fetch-time/response-hash provenance without raw API bodies or local absolute cache paths.
- `manifest.json`: actual exported counts, packaged-file SHA-256 values, source identities, cohort IDs, and whether this is a limited preview. The source base hash is explicitly recorded as previously verified, not newly rehashed. The small overlay hash is checked against the verified Phase 4 summary.

The verified pilot has 50 parsed histories and 884 field changes. Some histories may have zero events; do not confuse distinct event-parent counts with successful history-response counts. Original pilot QC reports 13 valid first-FIXED cases and 37 UNKNOWN; Phase 5 applies additional conflict/ambiguity eligibility restrictions. The pilot also contains selectively collected public API comments and refreshed metadata. Keep them separate from CSV snapshot records.

Links whose parent is sampled are retained even when their target is outside the sample; those target bugs are not silently added. `target_in_corpus` describes the **original 196,633-bug corpus**, not membership in this shared subset. Use a left join to `sample.bugs` to test whether a target is included here.

Private/unknown-privacy comment bodies remain withheld by the original normalization; the exporter additionally rejects a base comment body unless its flag is explicitly public. Public source text can still identify contributors. Raw source files, raw API envelopes, credentials, benchmark gold/review queues, and model artifacts are not included.

## Recipient: install and open DuckDB

No database server, API key or account is needed. Install Python 3.10+ and create an environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install duckdb==1.4.4
tar -xzf firefox-sample-seed317-<version>.tar.gz
cd firefox-sample-seed317-<version>
```

Replace `<version>` with the archive's actual name. On Windows, extract with your archive utility and activate `.venv\Scripts\Activate.ps1` in PowerShell instead. The two database files are already built: no import or reconstruction is required. Keep the archive/directory outside Git or under the repository's ignored `outputs/share/`.

Check the packaged hashes from the extracted folder:

```bash
python - <<'PY'
import hashlib, json
from pathlib import Path
m = json.loads(Path('manifest.json').read_text())
assert m['prefix_only'] is False, 'This is only a limited preview'
for name, expected in m['files'].items():
    h = hashlib.sha256()
    with Path(name).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    assert h.hexdigest() == expected['sha256'], name
print('Packaged hashes verified; table counts:', m['counts'])
PY
```

Then query both saved databases, without altering either:

```bash
python - <<'PY'
import duckdb
db = duckdb.connect(':memory:')
db.execute("ATTACH 'sample.duckdb' AS sample (READ_ONLY)")
db.execute("ATTACH 'api_enrichment.duckdb' AS api (READ_ONLY)")
print('Sampled bugs:', db.execute('SELECT count(*) FROM sample.bugs').fetchone()[0])
print('History changes:', db.execute('SELECT count(*) FROM api.field_changes').fetchone()[0])
print(db.execute('''
    SELECT snapshot_status, snapshot_resolution, count(*) AS bugs
    FROM sample.bugs GROUP BY ALL ORDER BY bugs DESC
''').fetchall())
print(db.execute('''
    SELECT bug_id, field_name, old_value, new_value, event_time_utc
    FROM api.field_changes
    ORDER BY bug_id, CAST(event_time_utc AS TIMESTAMPTZ), event_index, change_index
    LIMIT 5
''').fetchall())
db.close()
PY
```

## Scope and time semantics

This is Firefox-product Bugzilla data, not every Firefox engineering component. It preserves open/non-FIXED and zero-comment bugs. Comments are FIXED-selected, so explanatory coverage is biased. Source CSV snapshot time is UNKNOWN: event time, API fetch/observation time and ingestion time mean different things. The base `field_changes` stays empty and base `fix_metrics` remains UNKNOWN; the separate API overlay does not retroactively modify that snapshot. Do not compute first-FIXED from current status or last-change time, or infer developer-hours from elapsed days.

The subset database has a new file hash and fewer rows than the original full canonical database. It is a **data handoff**, not a replacement for pinned Phase 5/6 source artifacts or a new benchmark freeze. Full freeze/recomputation tools still need the original pinned source files and their complete manifests; do not edit immutable pins to bypass that check. See the repository's `docs/PHASE03B_NORMALIZATION.md`, `docs/PHASE04_API_ENRICHMENT.md` and `docs/TEMPORAL_VALIDITY.md` for source semantics.

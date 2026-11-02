#!/usr/bin/env python3
"""User-terminal export of the frozen sample; no API calls or raw CSV reads."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from datetime import datetime, timezone

VERSION = 1
FILTERED = ('bugs', 'comments', 'field_changes', 'bug_links', 'documents',
            'source_records', 'quality_records', 'fix_metrics')
UNFILTERED = ('provenance', 'run_manifest')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n')
    tmp.replace(path)


def log(message):
    print(f'[{datetime.now(timezone.utc).isoformat(timespec="seconds")}] {message}', flush=True)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def plan(args):
    root = args.root.resolve()
    pins = read(root / args.source_pins)
    base = root / pins['base_run']
    history = root / pins['phase04_run']
    bm, sm, hs = read(base / 'manifest.json'), read(base / 'sample_manifest.json'), read(history / 'summary.json')
    if bm['state'] != 'COMPLETE' or hs['state'] != 'COMPLETE':
        raise ValueError('Only completed verified source runs may be exported')
    if bm['identity_hash'] != pins['base_identity'] or sha(history / 'summary.json') != pins['phase04_summary_sha256']:
        raise ValueError('Pinned source identity/summary mismatch')
    ids = {str(x['bug_id']) for x in sm['members']}
    if len(ids) != pins['base_counts']['sample_membership'] or sm['seed'] != pins['sample_seed']:
        raise ValueError('Sample manifest does not match the pinned sample')
    history_ids = {str(x['bug_id']) for x in hs['api_response_manifest'] if x['endpoint'] == 'history'}
    if not history_ids <= ids or len(history_ids) != hs['candidate_count']:
        raise ValueError('History cohort is not contained in the full sampled population')
    for path, metadata in ((base / 'canonical.duckdb', bm['artifacts']['canonical.duckdb']),
                           (history / 'api_enrichment.duckdb', hs['artifacts']['api_enrichment.duckdb'])):
        if path.with_suffix(path.suffix + '.wal').exists():
            raise ValueError('Source database has an active WAL; close its writer first')
        if path.stat().st_size != metadata.get('bytes', metadata.get('size_bytes')):
            raise ValueError('Source database size no longer matches its verified manifest')
    identity = {'version': VERSION, 'exporter_sha256': sha(__file__), 'base_manifest_sha256': sha(base / 'manifest.json'),
                'sample_manifest_sha256': sha(base / 'sample_manifest.json'),
                'history_summary_sha256': sha(history / 'summary.json'), 'limit': args.limit,
                'source_database_mtime_ns': {p.name: p.stat().st_mtime_ns for p in (base / 'canonical.duckdb', history / 'api_enrichment.duckdb')}}
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    out = (args.output if args.output else root / 'outputs/share' / f'firefox-sample-seed{sm["seed"]}-{signature}').resolve()
    if out == root or any(p == out or p in out.parents for p in (base.resolve(), history.resolve(), root / 'Dataset')):
        raise ValueError('Choose a new output directory outside the source data/runs')
    return root, base, history, bm, sm, hs, ids, history_ids, identity, out


def export(args):
    root, base, history, bm, sm, hs, ids, history_ids, identity, out = plan(args)
    if args.dry_run:
        return {'state': 'DRY_RUN', 'output': str(out), 'selected_bugs': min(len(ids), args.limit or len(ids)),
                'history_cohort': len(history_ids), 'source_base_bytes': (base / 'canonical.duckdb').stat().st_size,
                'note': 'No rows scanned/copied. Full export is a user-terminal task; base GB hash is not recomputed.'}
    import duckdb
    if out.exists() and not args.resume:
        raise ValueError('Output exists; use --resume for the exact same input/version or choose a new --output')
    out.mkdir(parents=True, exist_ok=True)
    cp = out / 'checkpoint.json'
    if cp.exists():
        if read(cp)['identity'] != identity:
            raise ValueError('Changed export identity; choose a new output directory')
    elif any(out.iterdir()):
        raise ValueError('Output has files without an export checkpoint; choose a new directory')
    else:
        write(cp, {'state': 'STARTED', 'identity': identity})
    manifest_path = out / 'manifest.json'
    if manifest_path.exists():
        manifest = read(manifest_path)
        for name, entry in manifest['files'].items():
            if sha(out / name) != entry['sha256']:
                raise ValueError('Completed artifact changed: ' + name)
        log('Completed table export verified; reusing files')
    else:
        if sha(history / 'api_enrichment.duckdb') != hs['artifacts']['api_enrichment.duckdb']['sha256']:
            raise ValueError('History overlay hash no longer matches its verified summary')
        db = duckdb.connect(str(out / 'sample.duckdb'))
        try:
            db.execute("SET memory_limit=" + quote(args.memory_limit))
            db.execute('SET threads=2')
            db.execute("SET TimeZone='UTC'")
            db.execute('ATTACH ' + quote(base / 'canonical.duckdb') + ' AS source_base (READ_ONLY)')
            existing = {r[0] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog=current_database()").fetchall()}
            count_limit = '' if args.limit is None else ' LIMIT ' + str(args.limit)
            queries = {'sample_membership': 'SELECT * FROM source_base.main.sample_membership ORDER BY CAST(bug_id AS BIGINT)' + count_limit}
            queries.update({t: f'SELECT t.* FROM source_base.main.{t} t JOIN main.sample_membership s ON t.bug_id=s.bug_id' for t in FILTERED})
            queries.update({t: f'SELECT * FROM source_base.main.{t}' for t in UNFILTERED})
            counts = {}
            for table, sql in queries.items():
                if table not in existing:
                    db.execute(f'CREATE TABLE main.{table} AS {sql}')
                counts[table] = db.execute(f'SELECT count(*) FROM main.{table}').fetchone()[0]
                log(f'{table}: {counts[table]:,} rows (table checkpoint committed)')
            actual_ids = {r[0] for r in db.execute('SELECT bug_id FROM main.sample_membership').fetchall()}
            expected_ids = set(sorted(ids, key=int)[:args.limit]) if args.limit is not None else ids
            if actual_ids != expected_ids or counts['bugs'] != len(expected_ids):
                raise ValueError('Exported bug/sample membership differs from frozen manifest')
            if db.execute("SELECT count(*) FROM main.bugs WHERE product<>'Firefox' OR product IS NULL").fetchone()[0]:
                raise ValueError('Non-Firefox bug in frozen sample')
            privacy_bad = db.execute("SELECT count(*) FROM main.comments WHERE body IS NOT NULL AND private_flag IS DISTINCT FROM false").fetchone()[0]
            if privacy_bad:
                raise ValueError('Private/unknown-privacy comment body in source export')
            db.execute('CHECKPOINT')
        finally:
            db.close()
        shutil.copy2(history / 'api_enrichment.duckdb', out / 'api_enrichment.duckdb')
        if sha(out / 'api_enrichment.duckdb') != hs['artifacts']['api_enrichment.duckdb']['sha256']:
            raise ValueError('Copied history overlay checksum mismatch')
        write(out / 'sample_manifest.json', {**sm, 'members': [r for r in sm['members'] if str(r['bug_id']) in actual_ids],
                                              'shared_prefix_limit': args.limit})
        summary_keys = ('state', 'candidate_count', 'successful_histories', 'parseable_histories', 'field_change_rows',
                        'reopened_events', 'valid_f2_cases', 'unknown_or_insufficient_f2_cases', 'source_consistency_differences',
                        'same_time_history_event_groups', 'explicit_link_events', 'timestamp_semantics', 'source_snapshot_as_of_utc')
        write(out / 'history_summary.json', {k: hs[k] for k in summary_keys if k in hs})
        keys = ('bug_id', 'endpoint', 'url', 'fetched_at_utc', 'status_code', 'raw_sha256', 'source_visibility', 'error_label')
        write(out / 'history_response_manifest.json', [{k: r.get(k) for k in keys} for r in hs['api_response_manifest'] if r['endpoint'] == 'history'])
        shutil.copy2(root / 'docs/SAMPLE_DATA_HANDOFF.md', out / 'README.md')
        names = ('sample.duckdb', 'api_enrichment.duckdb', 'sample_manifest.json', 'history_summary.json', 'history_response_manifest.json', 'README.md')
        manifest = {'state': 'COMPLETE', 'identity': identity, 'sample_seed': sm['seed'], 'counts': counts,
                    'history_cohort_ids': sorted(history_ids, key=int), 'history_ids_in_shared_sample': len(history_ids & actual_ids),
                    'source_base_identity': bm['identity_hash'], 'source_base_sha256_declared_not_rehashed': bm['artifacts']['canonical.duckdb']['sha256'],
                    'source_base_hash_verification': 'Previously verified source manifest + current byte size; no new GB-file hash.',
                    'base_source_snapshot_as_of_utc': None, 'prefix_only': args.limit is not None,
                    'scope': 'Sample-parent rows only; link targets outside sample are references, not extra bug records. History overlay stays separate.',
                    'files': {n: {'bytes': (out / n).stat().st_size, 'sha256': sha(out / n)} for n in names}}
        write(manifest_path, manifest)
    archive = out.with_name(out.name + '.tar.gz')
    summary_path = out / 'summary.json'
    if archive.exists():
        if not summary_path.exists() or read(summary_path).get('archive_sha256') != sha(archive):
            # Recover a crash after archive rename but before summary commit.
            expected = {out.name + '/' + n: sha(out / n) for n in [*manifest['files'], 'manifest.json']}
            with tarfile.open(archive, 'r:gz') as tar:
                if {m.name for m in tar.getmembers()} != set(expected):
                    raise ValueError('Existing archive member list differs; preserve it and choose a new output')
                for member in tar.getmembers():
                    if not member.isfile():
                        raise ValueError('Unexpected non-file archive member')
                    h = hashlib.sha256()
                    with tar.extractfile(member) as f:
                        for block in iter(lambda: f.read(1024 * 1024), b''):
                            h.update(block)
                    if h.hexdigest() != expected[member.name]:
                        raise ValueError('Existing archive content differs; preserve it and choose a new output')
    else:
        partial = out.with_name(out.name + '.tar.gz.partial')
        if partial.exists():
            raise ValueError('Interrupted archive exists; preserve/rename the .partial file before --resume')
        with tarfile.open(partial, 'w:gz') as tar:
            for name in [*manifest['files'], 'manifest.json']:
                tar.add(out / name, arcname=out.name + '/' + name, recursive=False)
        partial.rename(archive)
    result = {'state': 'COMPLETE', 'output': str(out), 'archive': str(archive), 'archive_sha256': sha(archive),
              'archive_bytes': archive.stat().st_size, 'counts': manifest['counts'], 'prefix_only': manifest['prefix_only']}
    write(summary_path, result)
    write(cp, {'state': 'COMPLETE', 'identity': identity})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--source-pins', type=Path, default=Path('configs/phase05_sources.json'))
    p.add_argument('--output', type=Path, help='New ignored directory; default is versioned under outputs/share/')
    p.add_argument('--memory-limit', default='512MB')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--limit', type=int, help='Preview prefix only; omit to export the full 3,000-bug sample')
    p.add_argument('--resume', action='store_true', help='Reuse completed tables/files for identical source identity')
    args = p.parse_args()
    if args.limit is not None and args.limit < 1:
        p.error('--limit must be positive')
    print(json.dumps(export(args), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

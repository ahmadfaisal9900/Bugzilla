"""Build a source-only lexical corpus. Long jobs are run by the project owner."""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from bugzilla_qa.eval_extension.retrieval import build_lexical, digest, lexical_search, make_chunks

ROOT = Path(__file__).resolve().parents[3]


def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def records(config, limit):
    import duckdb
    from tqdm import tqdm
    base = duckdb.connect(str(ROOT / config['canonical_db']), read_only=True)
    overlay = duckdb.connect(str(ROOT / config['history_db']), read_only=True)
    try:
        base.execute("SET memory_limit='512MB'")
        selection = 'SELECT bug_id FROM sample_membership WHERE seed = ? ORDER BY bug_id'
        parameters = [config['sample_seed']]
        if limit:
            selection += ' LIMIT ?'
            parameters.append(limit)
        ids = [r[0] for r in base.execute(selection, parameters).fetchall()]
        for start in tqdm(range(0, len(ids), 200),desc='Corpus batches',unit='batch'):
            group = ids[start:start + 200]
            rows = base.execute('''SELECT bug_id,product,component,snapshot_status,snapshot_resolution,
                opened_at_utc,summary,source_record_id,source_url,content_hash,observed_at_utc,ingested_at_utc,source_dataset FROM bugs
                WHERE bug_id IN (SELECT unnest(?)) ORDER BY bug_id''', [group]).fetchall()
            for bug, product, component, status, resolution, opened, summary, rid, url, sha, observed, ingested, dataset in rows:
                text = 'Bug %s. Product %s. Component %s. Status %s. Resolution %s. Opened %s. Summary %s.' % (
                    bug, product, component, status, resolution, opened, summary or '')
                yield dict(record_id=rid, bug_id=bug, kind='metadata', text=text, url=url,
                           source_hash=sha, visibility='public', event_time_utc=str(opened) if opened else None,
                           observed_at_utc=str(observed) if observed else None, ingested_at_utc=str(ingested) if ingested else None,
                           source_dataset=dataset, snapshot_as_of_utc=None)
            cursor = base.execute('''SELECT bug_id,comment_key,body,source_url,content_hash,event_time_utc,observed_at_utc,ingested_at_utc,source_dataset FROM comments
                WHERE bug_id IN (SELECT unnest(?)) AND private_flag=false
                AND text_availability='AVAILABLE' AND body IS NOT NULL ORDER BY comment_key''', [group])
            while True:
                batch = cursor.fetchmany(128)
                if not batch:
                    break
                for bug, rid, body, url, sha, event, observed, ingested, dataset in batch:
                    yield dict(record_id=rid, bug_id=bug, kind='comment', text=body, url=url,
                               source_hash=sha, visibility='public', event_time_utc=str(event) if event else None,
                               observed_at_utc=str(observed) if observed else None, ingested_at_utc=str(ingested) if ingested else None,
                               source_dataset=dataset, snapshot_as_of_utc=None)
            links = base.execute('''SELECT bug_id,link_key,relation,target_bug_id,source_url,content_hash,observed_at_utc,ingested_at_utc,source_dataset
                FROM bug_links WHERE bug_id IN (SELECT unnest(?)) ORDER BY link_key''', [group]).fetchall()
            for bug, rid, relation, target, url, sha, observed, ingested, dataset in links:
                yield dict(record_id=rid, bug_id=bug, kind='link',
                           text='Bug %s recorded relation %s to bug %s.' % (bug, relation, target),
                           url=url, source_hash=sha, visibility='public', event_time_utc=None,
                           observed_at_utc=str(observed) if observed else None, ingested_at_utc=str(ingested) if ingested else None,
                           source_dataset=dataset, snapshot_as_of_utc=None)
            histories = overlay.execute('''SELECT bug_id,source_row_key,event_time_utc,field_name,old_value,
                new_value,source_url,content_sha256,observed_at_utc,ingested_at_utc,source_dataset FROM field_changes WHERE history_state='PARSED'
                AND field_name IN ('status', 'resolution')
                AND CAST(bug_id AS VARCHAR) IN (SELECT unnest(?)) ORDER BY bug_id,event_time_utc,event_index,change_index''', [group]).fetchall()
            for bug, rid, when, field, old, new, url, sha, observed, ingested, dataset in histories:
                yield dict(record_id=rid, bug_id=str(bug), kind='history',
                           text='Bug %s event %s: %s changed from %s to %s.' % (bug, when, field, old, new),
                           url=url, source_hash=sha, visibility='public', event_time_utc=when,
                           observed_at_utc=observed, ingested_at_utc=ingested, source_dataset=dataset, snapshot_as_of_utc=None)
            print('source bugs processed %d/%d' % (min(start + 200, len(ids)), len(ids)), file=sys.stderr, flush=True)
    finally:
        base.close()
        overlay.close()


def verify_source_manifests(config):
    base_path = ROOT / config['canonical_db']
    history_path = ROOT / config['history_db']
    base = json.loads((base_path.parent / 'manifest.json').read_text())
    history = json.loads((history_path.parent / 'summary.json').read_text())
    if base['state'] != 'COMPLETE' or base['identity_hash'] != config['base_identity']:
        raise RuntimeError('canonical manifest does not match pinned identity')
    if history['state'] != 'COMPLETE' or history['candidate_manifest_sha256'] != config['history_identity']:
        raise RuntimeError('history manifest does not match pinned identity')
    if base_path.stat().st_size != base['artifacts']['canonical.duckdb']['bytes']:
        raise RuntimeError('canonical database size mismatch')
    expected = history['artifacts']['api_enrichment.duckdb']
    if history_path.stat().st_size != expected['size_bytes'] or file_hash(history_path) != expected['sha256']:
        raise RuntimeError('history database hash mismatch')
    # Avoid hashing the 1.9GB canonical database in the interactive agent session;
    # the identity is based on its verified manifest and size, not a fresh byte audit.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['preflight', 'corpus', 'lexical', 'search'], default='preflight')
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/eval_extension.json')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'outputs/eval_extension')
    parser.add_argument('--seed', type=int, default=317)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--query', default='')
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error('--limit must be positive')
    config = json.loads(args.config.read_text())
    if args.seed != config['sample_seed']:
        parser.error('seed must match the frozen sample')
    identity = digest({'config': config, 'limit': args.limit, 'code': file_hash(Path(__file__)),
                       'retrieval_code': file_hash(Path(__file__).with_name('retrieval.py'))})
    plan = {'state': 'PLANNED', 'stage': args.stage, 'identity': identity, 'limit': args.limit,
            'output_root': str(args.output_root), 'network_calls': 0}
    if args.dry_run or args.stage == 'preflight':
        print(json.dumps(plan, indent=2))
        return
    verify_source_manifests(config)
    out = args.output_root / identity[:16]
    out.mkdir(parents=True, exist_ok=True)
    corpus, meta, index = out / 'corpus.jsonl', out / 'corpus_manifest.json', out / 'lexical.sqlite'
    if args.stage == 'corpus':
        if args.resume and meta.exists() and corpus.exists():
            m = json.loads(meta.read_text())
            if m['identity'] != identity or m['sha256'] != file_hash(corpus):
                raise RuntimeError('existing corpus identity/hash mismatch')
            print(json.dumps(m)); return
        if corpus.exists() or meta.exists():
            raise RuntimeError('existing output: use --resume or a separate output root')
        temp = out / 'corpus.jsonl.incomplete'
        count = 0
        with temp.open('w', encoding='utf-8') as f:
            for record in records(config, args.limit):
                for chunk in make_chunks(record, config['chunk_words'], config['overlap_words']):
                    from bugzilla_qa.eval_extension.contracts import validate
                    validate('Chunk',chunk)
                    f.write(json.dumps(chunk, ensure_ascii=False, sort_keys=True) + '\n')
                    count += 1
        os.replace(str(temp), str(corpus))
        m = {'state': 'COMPLETE', 'identity': identity, 'chunks': count, 'sha256': file_hash(corpus),
             'base_identity': config['base_identity'], 'history_identity': config['history_identity'],
             'sample_seed': args.seed, 'limit': args.limit, 'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        meta.write_text(json.dumps(m, indent=2) + '\n')
        print(json.dumps(m))
    elif args.stage == 'lexical':
        m = json.loads(meta.read_text())
        if m['identity'] != identity or m['sha256'] != file_hash(corpus):
            raise RuntimeError('corpus identity/hash mismatch')
        index_manifest = out / 'lexical_manifest.json'
        if args.resume and index.exists() and index_manifest.exists():
            saved = json.loads(index_manifest.read_text())
            if saved['identity'] != identity or saved['sha256'] != file_hash(index):
                raise RuntimeError('index identity/hash mismatch')
            print(json.dumps(saved)); return
        if index.exists():
            raise RuntimeError('existing index: use --resume or a separate output root')
        with corpus.open(encoding='utf-8') as f:
            count = build_lexical(index, (json.loads(line) for line in f), identity)
        result = {'state': 'COMPLETE', 'identity': identity, 'chunks': count, 'sha256': file_hash(index)}
        index_manifest.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
    else:
        if not args.query:
            parser.error('--query is required for search')
        saved = json.loads((out / 'lexical_manifest.json').read_text())
        if saved['identity'] != identity or saved['sha256'] != file_hash(index):
            raise RuntimeError('index identity/hash mismatch')
        print(json.dumps(lexical_search(index, args.query, config['top_k']), indent=2))


if __name__ == '__main__':
    main()

"""Re-evaluate the development M3 parser without overwriting existing results."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from bugzilla_qa.eval_extension import cli, m3_adapter
from bugzilla_qa.eval_extension.pipeline import read_jsonl, save, verify_bank
from bugzilla_qa.evaluation.scoring import score, summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank', type=Path, default=cli.ROOT / 'outputs/eval_extension/bank-dacb7ca0ceb7e0ef')
    parser.add_argument('--config', type=Path, default=cli.ROOT / 'configs/eval_extension.json')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    verify_bank(args.bank)
    config = json.loads(args.config.read_text())
    identity = {'bank_manifest_sha256': cli.file_hash(args.bank / 'bank_manifest.json'),
                'selected_sha256': cli.file_hash(args.bank / 'selected.jsonl'),
                'config_sha256': cli.file_hash(args.config),
                'adapter_sha256': cli.file_hash(Path(m3_adapter.__file__)),
                'runner_sha256': cli.file_hash(Path(__file__)),
                'limit': args.limit, 'split': 'dev'}
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    out = args.bank / 'm3_repair' / run_id
    if args.dry_run:
        print(json.dumps({'state': 'DRY_RUN', 'output': str(out), 'identity': identity}, indent=2))
        return
    cli.verify_source_manifests(config)
    questions = [q for q in read_jsonl(args.bank / 'selected.jsonl') if q['split'] == 'dev']
    if args.limit:
        questions = questions[:args.limit]
    by_id = {q['qid']: q for q in questions}
    if len(by_id) != len(questions):
        raise RuntimeError('duplicate development question IDs')
    out.mkdir(parents=True, exist_ok=True)
    identity_path = out / 'identity.json'
    if identity_path.exists():
        if not args.resume or json.loads(identity_path.read_text()) != identity:
            raise RuntimeError('output exists or identity changed; use --resume only with matching inputs')
    else:
        save(identity_path, identity)
    path = out / 'predictions.jsonl'
    rows = read_jsonl(path) if path.exists() else []
    completed = {r['qid'] for r in rows}
    if len(completed) != len(rows) or not completed <= by_id.keys():
        raise RuntimeError('checkpoint has duplicate or unexpected question IDs')
    store = m3_adapter.Store(cli.ROOT / config['canonical_db'], cli.ROOT / config['history_db'], config['sample_seed'])
    try:
        with path.open('a', encoding='utf-8') as handle:
            for question in questions:
                if question['qid'] in completed:
                    continue
                public = {key: question[key] for key in ('qid', 'question', 'scope')}
                prediction = m3_adapter.answer(store, public)
                handle.write(json.dumps(prediction, sort_keys=True) + '\n')
                handle.flush()
                rows.append(prediction)
                if len(rows) % 25 == 0:
                    print('M3 development: %d/%d questions' % (len(rows), len(questions)), flush=True)
    finally:
        store.close()
    scored = [score(by_id[row['qid']], row) for row in rows]
    summary = {'state': 'COMPLETE' if len(rows) == len(questions) else 'PARTIAL',
               'scope': 'development only', 'questions': len(questions),
               'status_counts': dict(Counter(row['status'] for row in rows)),
               'per_family': summarize(scored), 'predictions_sha256': cli.file_hash(path),
               'identity': identity, 'note': 'Parser repair; original predictions remain unchanged.'}
    save(out / 'summary.json', summary)
    print(json.dumps({'state': summary['state'], 'output': str(out),
                      'questions': len(rows), 'status_counts': summary['status_counts']}, indent=2))


if __name__ == '__main__':
    main()

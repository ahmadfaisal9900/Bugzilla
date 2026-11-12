"""Read-only independent v3 SQL/evidence recheck; no generator or API requests."""
import argparse
import fcntl
import json
from pathlib import Path

from bugzilla_qa.llm.provider import ROOT
from .v3_source import Source, configured_exclusions, file_hash, latest_run, read_jsonl, verify_exports, write_json
from .v3_verify import verify_candidate
from .v3_rules import cluster_split


def validate_run(run, root=ROOT, limit=None):
    run=Path(run)
    if not (run/'config_snapshot.json').is_file():raise RuntimeError('Not a v3 draft run')
    if (run/'FROZEN').exists():raise RuntimeError('Run is frozen; use the freeze --resume checksum check')
    with (run/'.run.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another process is using this v3 run') from None
        if (run/'.running.json').exists():raise RuntimeError('Resume interrupted generation before validation')
        return _validate_run(run,root,limit)


def _validate_run(run, root=ROOT, limit=None):
    run, root = Path(run), Path(root)
    snapshot = json.loads((run / 'config_snapshot.json').read_text())
    config = snapshot['dataset']
    verify_exports(config, root)
    excluded,_ = configured_exclusions(config,root)
    source = Source(config, root)
    failures, checked = [], []
    qids, clusters = set(), {}
    try:
        oracles = list(read_jsonl(run / 'oracles.jsonl'))
        oracle_by_id = {r['qid']: {k:v for k,v in r.items() if k != 'qid'} for r in oracles}
        if len(oracles) != len(oracle_by_id): raise RuntimeError('Duplicate oracle IDs')
        for split in ('dev','test'):
            questions = list(read_jsonl(run / (split + '.questions.jsonl')))
            gs = list(read_jsonl(run / (split + '.gold.jsonl')))
            rs = list(read_jsonl(run / ('qrels_v3_' + split + '.jsonl')))
            gold, qrels = {g['qid']:g for g in gs}, {r['qid']:r for r in rs}
            expected = {q['qid'] for q in questions}
            if len(expected) != len(questions) or len(gold)!=len(gs) or len(qrels)!=len(rs) or expected!=gold.keys() or expected!=qrels.keys():
                raise RuntimeError('Duplicate or mismatched question/gold/qrel IDs')
            for q in questions:
                if q['qid'] in qids: raise RuntimeError('Split overlap')
                qids.add(q['qid'])
                previous = clusters.setdefault(q['cluster_id'], split)
                if previous != split or q['split'] != split or cluster_split(config['seed'],q['cluster_id']) != split:
                    raise RuntimeError('Cluster/split rule violated')
            for q in questions[:limit] if limit else questions:
                try:
                    g = gold[q['qid']]
                    oracle = oracle_by_id[q['qid']]
                    checked.append(verify_candidate(source, {'question':q,'gold':g,'oracle':oracle}, excluded))
                    if set(qrels[q['qid']]['known_evidence_ids']) != set(g['evidence_record_ids']):
                        raise ValueError('Qrel evidence differs from gold evidence')
                    if set(qrels[q['qid']]['indexed_evidence_ids']) != set(g['evidence_record_ids']):
                        raise ValueError('Qrel index coverage differs from evidence')
                except (ValueError, KeyError) as error:
                    failures.append({'qid':q['qid'],'reason':str(error)})
        if qids != set(oracle_by_id): raise RuntimeError('Oracle/question IDs differ')
    finally:
        source.close()
    report={'state':'FAIL' if failures else 'LIMITED_PASS' if limit else 'PASS',
            'independent_gold_checked':not failures and limit is None,
            'checked':len(checked),'mismatches':failures,'limit':limit,
            'limitations':'Numeric and source provenance checks do not replace human review of KI wording.'}
    names = [split + '.' + kind + '.jsonl' for split in ('dev','test') for kind in ('questions','gold')]
    names += ['qrels_v3_dev.jsonl','qrels_v3_test.jsonl','oracles.jsonl','config_snapshot.json']
    report['sha256'] = {name:file_hash(run/name) for name in names}
    report['verification_code_sha256'] = {name:file_hash(Path(__file__).with_name(name)) for name in
                                        ('v3_validate.py','v3_verify.py','v3_source.py')}
    write_json(run / ('validation_recheck_limited.json' if limit else 'validation_recheck.json'),report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    locations=parser.add_mutually_exclusive_group(required=True)
    locations.add_argument('--run',type=Path)
    locations.add_argument('--latest',action='store_true')
    parser.add_argument('--config',type=Path,default=ROOT/'configs/benchmark_v3.yaml')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Recheck the existing draft; no gold is changed')
    args=parser.parse_args()
    if args.latest:args.run=latest_run(args.config,ROOT)
    if args.limit is not None and args.limit<1: parser.error('--limit must be positive')
    if args.dry_run:
        print(json.dumps({'state':'DRY_RUN','run':str(args.run),'network_calls':0,'limit':args.limit}));return
    report=validate_run(args.run,limit=args.limit)
    print(json.dumps({k:v for k,v in report.items() if k!='mismatches'},indent=2))
    if report['state']=='FAIL':raise SystemExit(1)


if __name__=='__main__':main()

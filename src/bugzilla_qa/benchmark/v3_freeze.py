"""Freeze an independently validated v3 draft after real human spot checks."""
import argparse
import collections
import csv
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from bugzilla_qa.llm.provider import ROOT
from .v3_source import latest_run
from .v3_rules import FAMILIES


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    with path.open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def freeze(run, dry_run=False, resume=False):
    run=Path(run)
    if dry_run:return _freeze(run,True,resume)
    if not (run/'manifest.json').is_file() or json.loads((run/'manifest.json').read_text()).get('state') != 'DRAFT_READY_FOR_SPOTCHECK':
        raise RuntimeError('Only a complete v3 draft root can be frozen')
    with (run/'.run.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another process is using this v3 run') from None
        if (run/'.running.json').exists():raise RuntimeError('Interrupted generation must be resumed before freezing')
        return _freeze(run,False,resume)


def _freeze(run, dry_run=False, resume=False):
    run = Path(run)
    required = ['dev.questions.jsonl', 'dev.gold.jsonl', 'test.questions.jsonl', 'test.gold.jsonl',
                'qrels_v3_dev.jsonl', 'qrels_v3_test.jsonl', 'review/spotcheck_v3.csv',
                'validation_report.json', 'config_snapshot.json', 'validation_recheck.json', 'oracles.jsonl', 'summary.json',
                'manifest.json', 'inputs_verified.json']
    if dry_run:
        return {'state': 'DRY_RUN', 'required_inputs': required, 'output': str(run)}
    pointer = run / 'FROZEN'
    if pointer.exists():
        if not resume:
            raise RuntimeError('Existing freeze preserved; use --resume to verify it')
        name = pointer.read_text().strip()
        if Path(name).name != name or not name.startswith('frozen-'):
            raise RuntimeError('Invalid freeze pointer')
        dest = run / name
        manifest = json.loads((dest / 'manifest.json').read_text())
        if manifest.get('status') != 'FROZEN_HUMAN_SPOTCHECKED':
            raise RuntimeError('Invalid frozen manifest state')
        manifest_data = dict(manifest)
        freeze_id = manifest_data.pop('freeze_id', None)
        expected_id = hashlib.sha256(json.dumps(manifest_data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
        if freeze_id != expected_id or name != 'frozen-' + expected_id:
            raise RuntimeError('Frozen manifest identity mismatch')
        if any(Path(n).is_absolute() or '..' in Path(n).parts or sha(dest / n) != h for n,h in manifest['sha256'].items()):
            raise RuntimeError('Frozen artifact hash mismatch')
        if any(sha(run / n) != h for n,h in manifest['source_sha256'].items()):
            raise RuntimeError('Original inputs changed after freeze')
        return {'state': 'ALREADY_FROZEN_VERIFIED', 'output': str(dest), 'freeze_id': manifest['freeze_id']}
    for name in required:
        if not (run / name).is_file():
            raise RuntimeError('Missing required input: ' + name)
    initial_hashes={name:sha(run/name) for name in required}
    validation = json.loads((run / 'validation_report.json').read_text())
    if validation.get('state') != 'PASS' or not validation.get('independent_gold_checked'):
        raise RuntimeError('Independent gold verification has not passed')
    if validation.get('limited') is not False or validation.get('generation_complete') is not True:
        raise RuntimeError('Incomplete or limited generation cannot be frozen')
    summary = json.loads((run/'summary.json').read_text())
    if summary.get('state') != 'DRAFT_READY_FOR_SPOTCHECK' or summary.get('limited'):
        raise RuntimeError('Draft is not a complete unlimited generation')
    recheck = json.loads((run/'validation_recheck.json').read_text())
    if recheck.get('state') != 'PASS' or not recheck.get('independent_gold_checked'):
        raise RuntimeError('Independent validation recheck has not passed')
    for name in required[:6] + ['oracles.jsonl','config_snapshot.json']:
        if recheck.get('sha256',{}).get(name) != sha(run/name):
            raise RuntimeError('Independent recheck input hash changed: '+name)
    pinned = validation.get('sha256', {})
    for name in required[:6]:
        if pinned.get(name) != sha(run / name):
            raise RuntimeError('Validation hash missing or changed: ' + name)
    questions, gold, qrels = {}, {}, {}
    for split in ('dev', 'test'):
        questions[split] = rows(run / (split + '.questions.jsonl'))
        gold[split] = rows(run / (split + '.gold.jsonl'))
        qrels[split] = rows(run / ('qrels_v3_' + split + '.jsonl'))
        qids = [q['qid'] for q in questions[split]]
        if len(qids) != len(set(qids)):
            raise RuntimeError('Duplicate question ID in ' + split)
        if set(qids) != {q['qid'] for q in gold[split]} or set(qids) != {q['qid'] for q in qrels[split]}:
            raise RuntimeError('Question, gold and qrel IDs do not match in ' + split)
    if {q['qid'] for q in questions['dev']} & {q['qid'] for q in questions['test']}:
        raise RuntimeError('Question IDs overlap across splits')
    if {q['cluster_id'] for q in questions['dev']} & {q['cluster_id'] for q in questions['test']}:
        raise RuntimeError('Clusters overlap across splits')
    allq = {q['qid']: q for split in questions for q in questions[split]}
    with (run / 'review/spotcheck_v3.csv').open(newline='', encoding='utf-8') as handle:
        review = list(csv.DictReader(handle))
    try:
        immutable = [{k:r[k] for k in ('qid','question','gold','source_summary')} for r in review]
    except KeyError:
        raise RuntimeError('Spot-check sheet is missing immutable columns') from None
    if hashlib.sha256(json.dumps(immutable,sort_keys=True).encode()).hexdigest() != validation.get('review_immutable_sha256'):
        raise RuntimeError('Spot-check question, gold or source summary changed')
    verdicts = {}
    for row in review:
        qid, verdict = row.get('qid'), row.get('verdict', '').strip().upper()
        if qid not in allq or qid in verdicts or verdict not in {'OK', 'AMBIGUOUS', 'WRONG', 'LEAK'}:
            raise RuntimeError('Spot check has a missing, duplicate or invalid decision')
        verdicts[qid] = verdict
    for family, target in (('KI', 30), ('MH', 15), ('F6H', 10)):
        available = sum(q['family'] == family for q in allq.values())
        reviewed = sum(allq[qid]['family'] == family for qid in verdicts)
        if available == 0:
            raise RuntimeError('No eligible questions for ' + family)
        if reviewed < min(target, available):
            raise RuntimeError('Insufficient spot checks for ' + family)
    excluded = {qid for qid, verdict in verdicts.items() if verdict != 'OK'}
    # Both KI forms share a generated description. A rejected description cannot
    # remain in an unreviewed sibling question.
    bad_ki_clusters = {allq[qid]['cluster_id'] for qid in excluded if allq[qid]['family']=='KI'}
    excluded.update(qid for qid,q in allq.items() if q['family']=='KI' and q['cluster_id'] in bad_ki_clusters)
    counts = collections.Counter()
    files = {}
    for split in ('dev', 'test'):
        kept = {q['qid'] for q in questions[split]} - excluded
        for q in questions[split]:
            if q['qid'] in kept:
                counts[split + ':' + q['family']] += 1
        for name, content in ((split + '.questions.jsonl', questions[split]),
                              (split + '.gold.jsonl', gold[split]),
                              ('qrels_v3_' + split + '.jsonl', qrels[split])):
            files[name] = ''.join(json.dumps(r, sort_keys=True, ensure_ascii=False) + '\n' for r in content if r['qid'] in kept).encode()
    counts = {split+':'+family:counts[split+':'+family] for split in ('dev','test') for family in FAMILIES}
    for name in ('config_snapshot.json','validation_report.json','validation_recheck.json','inputs_verified.json','review/spotcheck_v3.csv'):
        files[name] = (run/name).read_bytes()
    files['draft_summary.json'] = (run/'summary.json').read_bytes()
    files['draft_manifest.json'] = (run/'manifest.json').read_bytes()
    files['summary.json'] = (json.dumps({'status':'FROZEN_HUMAN_SPOTCHECKED','counts':dict(counts),
        'retained':sum(counts.values()),'rejected_or_linked_variants':len(excluded),
        'reviewed_items':len(verdicts),'scope':'Human spot checks, not exhaustive human verification.'},
        sort_keys=True,indent=2)+'\n').encode()
    files['oracles.jsonl'] = ''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows(run/'oracles.jsonl') if r['qid'] not in excluded).encode()
    ki = [qid for qid in verdicts if allq[qid]['family'] == 'KI']
    ki_bad = sum(verdicts[qid] != 'OK' for qid in ki)
    manifest = {'status': 'FROZEN_HUMAN_SPOTCHECKED', 'counts': dict(counts),
                'clusters_by_split':{split:len({q['cluster_id'] for q in questions[split] if q['qid'] not in excluded}) for split in ('dev','test')},
                'source_sha256': initial_hashes,
                'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                'spotcheck_total': len(verdicts), 'excluded_qids': sorted(excluded),
                'ki_rejection_policy': 'Drop both forms sharing a rejected KI description.',
                'ki_rejected_fraction': ki_bad / len(ki) if ki else None,
                'warning': 'Recommend KI regeneration: more than 15% of reviewed KI were non-OK' if ki and ki_bad / len(ki) > .15 else None}
    try:
        manifest['git_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError('Cannot determine Git commit') from None
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    manifest['freeze_id'] = digest[:16]
    if initial_hashes != {name:sha(run/name) for name in required}:
        raise RuntimeError('Draft or review inputs changed during freeze')
    dest = run / ('frozen-' + manifest['freeze_id'])
    if dest.exists() and resume and not pointer.exists():
        # Recover a crash between atomic directory promotion and pointer write.
        saved = json.loads((dest/'manifest.json').read_text())
        if saved != manifest or any(sha(dest/name) != h for name,h in manifest['sha256'].items()):
            raise RuntimeError('Unpointed freeze differs; preserve it for inspection')
        pointer.write_text(dest.name+'\n',encoding='utf-8')
        return {'state':'ALREADY_FROZEN_VERIFIED','output':str(dest),'freeze_id':manifest['freeze_id']}
    if dest.exists() or (run / 'FROZEN').exists():
        raise RuntimeError('Existing freeze preserved; do not overwrite')
    temp = Path(tempfile.mkdtemp(prefix='.freeze-', dir=str(run)))
    try:
        for name, data in files.items():
            (temp/name).parent.mkdir(parents=True,exist_ok=True)
            (temp / name).write_bytes(data)
        (temp / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.rename(str(temp), str(dest))
        (run / 'FROZEN').write_text(dest.name + '\n', encoding='utf-8')
    finally:
        if temp.exists(): shutil.rmtree(temp)
    return {'state': manifest['status'], 'output': str(dest), 'freeze_id': manifest['freeze_id'],
            'counts': manifest['counts'], 'warning': manifest['warning']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    locations=parser.add_mutually_exclusive_group(required=True)
    locations.add_argument('--run',type=Path)
    locations.add_argument('--latest',action='store_true')
    parser.add_argument('--config',type=Path,default=ROOT/'configs/benchmark_v3.yaml')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.latest:args.run=latest_run(args.config,ROOT)
    print(json.dumps(freeze(args.run, args.dry_run, args.resume), indent=2))


if __name__ == '__main__': main()

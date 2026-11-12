"""Load evaluation labels separately; retrievers receive question text only."""
import re
from collections import Counter
from pathlib import Path
from .common import file_hash, read_jsonl, read_config

NA_FAMILIES = {'F3', 'F6', 'F6H'}


def checked_file(directory, manifest, name):
    if name not in manifest['sha256'] or file_hash(directory/name) != manifest['sha256'][name]:
        raise RuntimeError('Frozen input mismatch: '+str(directory/name))
    return directory/name


def load_datasets(config, root, split='dev', confirm=False, datasets=None, limit=None):
    if split == 'test' and not confirm:
        raise RuntimeError('Locked test requires --confirm-locked-test')
    root = Path(root); results=[]; pins={}; coverage={}
    for dataset in datasets or config['datasets']:
        if dataset in ('phase05','v3'):
            directory=root/config[dataset+'_dir']; manifest=read_config(directory/'manifest.json')
            state=manifest.get('status',manifest.get('state'))
            if state not in ('FROZEN_HUMAN_SIGNED','FROZEN_HUMAN_SPOTCHECKED'):
                raise RuntimeError('Dataset is not frozen')
            if manifest.get('freeze_id',manifest.get('id')) != config[dataset+'_freeze_id']:
                raise RuntimeError('Wrong freeze identity')
            qfile=checked_file(directory,manifest,split+'.questions.jsonl')
            gfile=checked_file(directory,manifest,split+'.gold.jsonl')
            questions=list(read_jsonl(qfile)); gold={g['qid']:g for g in read_jsonl(gfile)}
            qrels=None
            if dataset=='v3':
                names=[n for n in manifest['sha256'] if n=='qrels_v3_'+split+'.jsonl']
                if len(names)!=1: raise RuntimeError('Missing/ambiguous frozen qrels')
                rfile=checked_file(directory,manifest,names[0])
                qrels={r['qid']:r for r in read_jsonl(rfile)}
                pins[str(rfile.relative_to(root))]=file_hash(rfile)
            for path in (qfile,gfile,directory/'manifest.json'):
                pins[str(path.relative_to(root))]=file_hash(path)
            rows=[]
            for q in questions:
                g=gold[q['qid']]; family=g.get('family',q.get('family'))
                refs=g.get('evidence_record_ids',[e['id'] for e in g.get('evidence',[])])
                if qrels is not None:
                    r=qrels[q['qid']]
                    if set(refs)!=set(r['known_evidence_ids']): raise RuntimeError('Gold/qrels mismatch')
                bugs=g.get('acceptable_bug_ids',g.get('bug_ids',[]))
                root_bug=q.get('provenance',{}).get('root_bug_id')
                cluster=q.get('cluster_id') or root_bug or g.get('cluster_id')
                if not cluster:
                    cluster='bug:'+str(bugs[0]) if bugs and family!='F3' else 'aggregate:'+str(g.get('scope',{}).get('partition',split))
                rows.append(dict(qid=q['qid'],family=family,question=q['question'],
                    cluster_id=str(cluster).removeprefix('bug:'),relevant=sorted(set(refs)),
                    acceptable_bug_ids=sorted(set(str(b) for b in bugs))))
        elif dataset=='natural':
            path=root/config['natural_questions']; manifest=read_config(root/config['natural_manifest'])
            if file_hash(path)!=manifest['sha256']: raise RuntimeError('Natural approvals hash mismatch')
            pins[config['natural_questions']]=file_hash(path)
            pins[config['natural_manifest']]=file_hash(root/config['natural_manifest'])
            rows=[]
            for q in read_jsonl(path):
                if q['split']!=split: continue
                if q.get('human_review_state')!='HUMAN_APPROVED_WORDING': raise RuntimeError('Unapproved rewrite')
                rows.append(dict(qid=q['qid'],question=q['question'],family=q['family'],
                    cluster_id=str(q['cluster_id']).removeprefix('bug:'),
                    relevant=sorted({e['id'] for e in q['evidence']}),
                    acceptable_bug_ids=sorted({str(b) for b in q.get('bug_ids',[])})))
        else: raise ValueError('Unknown dataset '+dataset)
        if len({r['qid'] for r in rows})!=len(rows): raise RuntimeError('Duplicate qids')
        coverage[dataset]=dict(Counter(r['family'] for r in rows))
        rows=sorted(rows,key=lambda r:r['qid'])
        if limit: rows=rows[:limit]
        results.extend(dict(r,dataset=dataset,split=split) for r in rows)
    return results,pins,coverage

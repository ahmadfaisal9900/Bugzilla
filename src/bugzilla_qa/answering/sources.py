"""Question-only loading. Gold may enter only the diagnostic ORACLE loader."""
from pathlib import Path
from bugzilla_qa.retrieval_v3.common import read_config, read_jsonl, file_hash
from bugzilla_qa.retrieval_v3.datasets import checked_file


def questions(config, root, dataset, split, confirm=False):
    if split == 'test' and not confirm: raise RuntimeError('Locked test requires --confirm-locked-test')
    rc=read_config(root/config['retrieval_config']); pins={}
    if dataset in ('v3','phase05'):
        directory=root/rc[dataset+'_dir']; manifest=read_config(directory/'manifest.json')
        if manifest.get('freeze_id')!=rc[dataset+'_freeze_id']:
            raise RuntimeError('Wrong frozen dataset identity')
        if manifest.get('status',manifest.get('state')) not in ('FROZEN_HUMAN_SIGNED','FROZEN_HUMAN_SPOTCHECKED'):
            raise RuntimeError('Dataset is not frozen')
        path=checked_file(directory,manifest,split+'.questions.jsonl')
        rows=list(read_jsonl(path)); families={}
        if dataset=='phase05':
            # Its question file omits family. Isolate metadata extraction here;
            # no typed answer, SQL, rubric or evidence is returned to the graph.
            gp=checked_file(directory,manifest,split+'.gold.jsonl')
            families={g['qid']:g['family'] for g in read_jsonl(gp)}
            pins[str(gp.relative_to(root))]=file_hash(gp)
        freeze=manifest['freeze_id']; pins[str((directory/'manifest.json').relative_to(root))]=file_hash(directory/'manifest.json')
    elif dataset=='natural':
        manifest=read_config(root/rc['natural_manifest']); path=root/rc['natural_questions']
        if file_hash(path)!=manifest['sha256']: raise RuntimeError('Natural dataset hash mismatch')
        rows=[q for q in read_jsonl(path) if q['split']==split]
        if any(q.get('human_review_state')!='HUMAN_APPROVED_WORDING' for q in rows):
            raise RuntimeError('Unapproved rewrite')
        freeze=manifest['sha256']; families={}
        pins[rc['natural_manifest']]=file_hash(root/rc['natural_manifest'])
    else: raise ValueError('Unknown dataset')
    pins[str(path.relative_to(root))]=file_hash(path)
    result=[]
    for q in rows:
        scope=dict(q.get('scope',q.get('provenance',{}).get('original_scope',{})))
        if scope.get('partition') in ('dev','test'):
            scope['partition_scheme']='phase05' if dataset=='phase05' else 'expanded-v2'
        result.append(dict(qid=q['qid'],question=q['question'],family=q.get('family',families.get(q['qid'],'UNKNOWN')),
                           scope=scope,dataset=dataset,split=split,freeze_id=freeze))
    if len({r['qid'] for r in result})!=len(result): raise RuntimeError('Duplicate question IDs')
    return sorted(result,key=lambda q:q['qid']),pins


def oracle_references(config, root, dataset, split, confirm=False):
    if split=='test' and not confirm: raise RuntimeError('Locked ORACLE requires --confirm-locked-test')
    rc=read_config(root/config['retrieval_config'])
    if dataset=='natural':
        return {q['qid']:[e['id'] for e in q['evidence']] for q in read_jsonl(root/rc['natural_questions']) if q['split']==split}
    directory=root/rc[dataset+'_dir']; m=read_config(directory/'manifest.json')
    name='qrels_v3_'+split+'.jsonl' if dataset=='v3' else split+'.gold.jsonl'
    rows=read_jsonl(checked_file(directory,m,name))
    return {q['qid']:q.get('known_evidence_ids',q.get('evidence_record_ids',[e['id'] for e in q.get('evidence',[])])) for q in rows}

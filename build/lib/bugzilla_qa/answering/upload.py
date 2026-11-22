"""Opt-in LangSmith reference dataset upload; never invokes an evaluator."""
import uuid
from pathlib import Path
from langsmith.utils import LangSmithNotFoundError, LangSmithConflictError
from .runner import trace_client
from .sources import questions
from .contracts import clean
from bugzilla_qa.retrieval_v3.common import (read_config,read_jsonl,write_json,file_hash,digest,append,now,locked)
from bugzilla_qa.retrieval_v3.datasets import checked_file


def upload(config,root,enable=False,max_requests=1,limit=None,resume=False):
    rc=read_config(root/config['retrieval_config']);inputs=[];pins={}
    for dataset in ('v3','natural'):
        qs,p=questions(config,root,dataset,'dev');pins.update(p)
        if dataset=='v3':
            directory=root/rc['v3_dir'];manifest=read_config(directory/'manifest.json')
            path=checked_file(directory,manifest,'dev.gold.jsonl');refs={g['qid']:g for g in read_jsonl(path)}
            pins[str(path.relative_to(root))]=file_hash(path)
        else:refs={g['qid']:g for g in read_jsonl(root/rc['natural_questions']) if g['split']=='dev'}
        for q in qs[:limit] if limit else qs:
            # Reference outputs only; never sent to an answering system.
            g=refs[q['qid']]
            gold={k:g[k] for k in ('answer','gold','evidence_record_ids','evidence','acceptable_bug_ids') if k in g}
            inputs.append((dataset,q,gold))
    version=digest(pins)[:16];out=root/config['output_root']/'langsmith-upload'/version
    result=dict(state='DRY_RUN',examples=len(inputs),datasets=2,estimated_requests_upper_bound=len(inputs)+4,
                actual_requests=0,output=str(out.relative_to(root)),evaluators_run=0)
    if not enable:return result
    result['state']='PARTIAL'
    client=trace_client(config,root,True)
    with locked(out):
        cp=read_config(out/'checkpoint.json') if (out/'checkpoint.json').exists() else {'datasets':{},'examples':[]}
        if cp['examples'] and not resume:raise RuntimeError('Upload checkpoint exists; use --resume')
        def call(purpose,fn):
            if result['actual_requests']>=max_requests:raise RuntimeError('Upload request cap reached; resume')
            result['actual_requests']+=1
            append(out/'requests.jsonl',{'ts':now(),'purpose':purpose,'status':'STARTED'})
            try:value=fn()
            except Exception as exc:
                append(out/'requests.jsonl',{'ts':now(),'purpose':purpose,'status':'ERROR','error_class':type(exc).__name__})
                raise
            append(out/'requests.jsonl',{'ts':now(),'purpose':purpose,'status':'SUCCESS'})
            return value
        try:
            from tqdm import tqdm
            for dataset,q,gold in tqdm(inputs,desc='LangSmith dev references',unit='question'):
                if dataset not in cp['datasets']:
                    name='ensf621-'+dataset+'-dev-'+version
                    try:d=call('read_dataset',lambda:client.read_dataset(dataset_name=name))
                    except LangSmithNotFoundError:d=call('create_dataset',lambda:client.create_dataset(name,description='Frozen dev references only; no evaluators.'))
                    cp['datasets'][dataset]=str(d.id);write_json(out/'checkpoint.json',cp)
                eid=str(uuid.uuid5(uuid.NAMESPACE_URL,version+dataset+q['qid']+digest(gold)))
                if eid in cp['examples']:continue
                payload=clean({'inputs':{'qid':q['qid'],'question':q['question']},'outputs':gold},root)
                try:call('create_example',lambda:client.create_example(dataset_id=cp['datasets'][dataset],
                    example_id=eid,inputs=payload['inputs'],outputs=payload['outputs'],
                    metadata={'family':q['family'],'freeze_id':q['freeze_id'],'split':'dev'}))
                except LangSmithConflictError:pass # Content-addressed ID handles success-before-checkpoint crashes.
                cp['examples'].append(eid);write_json(out/'checkpoint.json',cp)
            result['state']='COMPLETE'
        except Exception as exc:result.update(state='PARTIAL',blocker=clean(str(exc),root))
        finally:
            write_json(out/'summary.json',result)
            write_json(out/'manifest.json',{'state':result['state'],'input_sha256':pins,'sha256':{
                p.name:file_hash(p) for p in out.iterdir() if p.is_file() and p.name not in ('manifest.json','.lock')}})
            client.flush()
    return result

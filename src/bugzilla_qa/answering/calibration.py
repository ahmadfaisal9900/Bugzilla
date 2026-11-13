"""Dev score distribution only: a documented tau suggestion, no answer scoring."""
import json
import math
import sqlite3
from bugzilla_qa.retrieval_v3.common import read_config,write_json,file_hash,now


def suggest(config,root,write=False,quantile=.1):
    if not 0<=quantile<=1:raise ValueError('quantile must be in [0,1]')
    selected=read_config(root/config['selection']);corpus=selected['selected']['corpus'];scores={};sources={}
    for path in config['retrieval_runs']:
        manifest=root/path/'manifest.json'
        if not manifest.exists():continue
        identity=read_config(root/path/'identity.json');m=read_config(manifest)
        if identity['split']!='dev' or m.get('state')!='COMPLETE':continue
        if identity.get('compatibility')!=selected['compatibility']:continue
        sources[str(manifest.relative_to(root))]=file_hash(manifest)
        with sqlite3.connect('file:'+str(root/path/'retrieval_cache.sqlite')+'?mode=ro',uri=True) as db:
            for dataset,qid,payload in db.execute('SELECT dataset,qid,payload FROM results WHERE corpus=? AND retriever=?',[corpus,'R5']):
                hits=json.loads(payload)['hits']
                if hits:scores[dataset,qid]=float(hits[0]['score'])
    values=sorted(scores.values())
    if not values:raise RuntimeError('No completed dev R5 scores for selected corpus')
    q=lambda p:values[int(p*(len(values)-1))]
    result=dict(state='SUGGESTED_DEV_SCORE_QUANTILE_NOT_OPTIMIZED',split='dev',corpus=corpus,method='R5',
        n=len(values),quantile=quantile,tau=q(quantile),distribution={'min':values[0],'p10':q(.1),'p50':q(.5),'p90':q(.9),'max':values[-1]},
        selection_sha256=file_hash(root/config['selection']),input_sha256=sources,at_utc=now(),
        note='No answer scoring. Threshold is scale-specific and must remain fixed before locked test.')
    if write:
        path=root/config['corrective_calibration']
        if path.exists():
            old=read_config(path)
            if old['selection_sha256']!=result['selection_sha256'] or old['tau']!=result['tau']:
                raise RuntimeError('Existing calibration differs; choose a new versioned calibration path')
        else:write_json(path,result)
    return dict(result,dry_run=not write,output=config['corrective_calibration'])


def with_calibration(config,root):
    if config.get('corrective_tau') is not None:return dict(config)
    path=root/config['corrective_calibration']
    if not path.exists():return dict(config)
    result=read_config(path)
    if result['split']!='dev' or result['selection_sha256']!=file_hash(root/config['selection']):
        raise RuntimeError('Stale/non-dev S4 calibration')
    return dict(config,corrective_tau=result['tau'],calibration_sha256=file_hash(path))

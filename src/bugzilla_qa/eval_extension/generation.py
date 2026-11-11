"""Opt-in local Ollama inference and deterministic Phase 6 scoring."""
import hashlib
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from bugzilla_qa.eval_extension.pipeline import frozen_original, read_jsonl, save, write_jsonl
from bugzilla_qa.eval_extension.cli import file_hash
from bugzilla_qa.methods.generation import answer_question
from bugzilla_qa.methods.local_model import OllamaClient, RequestLimit
from bugzilla_qa.evaluation.scoring import score, summarize


class FixedIndex:
    def __init__(self, hits): self.hits = hits
    def search(self, question, top_k): return self.hits[:top_k]


def infer(out, corpus_dir, items, split, model, max_requests, resume, suffix=''):
    if split=='test' and (not frozen_original() or not (out/'BANK_FROZEN.json').exists()):
        raise RuntimeError('test inference requires both frozen benchmark gates')
    selected={q['qid']:q for q in items if q['split']==split}
    label=split+suffix
    ranked=read_jsonl(out/('retrieval_'+label+'.jsonl'))
    corpus={d['chunk_id']:d for d in read_jsonl(corpus_dir/'corpus.jsonl')}
    output=out/('predictions_'+label+'.jsonl')
    identity={'model':model,'split':split,'corpus_sha256':file_hash(corpus_dir/'corpus.jsonl'),
              'retrieval_sha256':file_hash(out/('retrieval_'+label+'.jsonl')),
              'generator':'phase06-generation-v1','evidence_chars':12000,'top_k':5}
    manifest=out/('inference_'+label+'_identity.json')
    if manifest.exists() and json.loads(manifest.read_text()) != identity:
        raise RuntimeError('inference identity differs; use a new output root')
    if not manifest.exists(): save(manifest,identity)
    done=read_jsonl(output) if output.exists() and resume else []
    if output.exists() and not resume: raise RuntimeError('predictions exist; use --resume')
    existing={(r['qid'],r['method']) for r in done}
    client=OllamaClient(model=model,max_requests=max_requests)
    work=[]
    for q in selected.values(): work.append((q['qid'],'M0',[]))
    for row in ranked: work.append((row['qid'],row['method'],row['hits']))
    remaining=[x for x in work if (x[0],x[1]) not in existing]
    print('Local model plan: %d pending predictions; max %d requests this invocation' % (len(remaining),max_requests),flush=True)
    with output.open('a',encoding='utf-8') as handle:
        for qid, method, hits in remaining:
            if client.calls >= max_requests: break
            q=selected[qid]
            public_question={'qid':qid,'question':q['question'],'scope':q['scope']}
            index=None
            if method!='M0':
                evidence=[]
                for hit in hits:
                    d=corpus[hit['chunk_id']]
                    if d['visibility']!='public': raise ValueError('non-public context')
                    text='\n'.join(line for line in d['text'].splitlines() if not re.search(
                        r'(?i)\b(ignore (all |the |previous |prior )?instructions|system prompt|reveal (the )?secret)\b',line))
                    evidence.append({'doc_id':d['chunk_id'],'record_id':d['record_id'],'bug_id':d['bug_id'],
                                     'url':d['url'],'text':text,'rank':hit['rank'],'score':hit['score']})
                index=FixedIndex(evidence)
            try: result=answer_question(public_question,client,method='M0' if method=='M0' else 'M1',index=index)
            except RequestLimit: break
            result['method']=method
            handle.write(json.dumps(result,ensure_ascii=False,sort_keys=True)+'\n');handle.flush()
            done.append(result)
    summary={'state':'COMPLETE' if len(done)>=len(work) else 'PARTIAL',
             'predictions':len(done),'planned':len(work),'requests_this_invocation':client.calls,
             'model':model,'split':split,'api':'local Ollama'}
    save(out/('inference_'+label+'_summary.json'),summary)
    return summary


def score_predictions(out, items, split, suffix=''):
    label=split+suffix
    path=out/('predictions_'+label+'.jsonl')
    sql_path=out/'m3_dev_predictions.jsonl'
    if not path.exists() and not (split=='dev' and not suffix and sql_path.exists()): return {'state':'SKIPPED','reason':'no predictions'}
    gold={q['qid']:q for q in items if q['split']==split}
    predictions=read_jsonl(path) if path.exists() else []
    if split=='dev' and not suffix and sql_path.exists(): predictions += read_jsonl(sql_path)
    results=[score(gold[p['qid']],p) for p in predictions if p['qid'] in gold]
    write_jsonl(out/('scores_'+label+'.jsonl'),results)
    table=summarize(results);methods=defaultdict(list)
    for cell in table:
        if cell['accuracy'] is not None: methods[cell['method']].append(cell['accuracy'])
    coverage={}
    for method in sorted({p['method'] for p in predictions}):
        rows=[p for p in predictions if p['method']==method]
        lat=sorted(p.get('trace',{}).get('latency_seconds') for p in rows if p.get('trace',{}).get('latency_seconds') is not None)
        coverage[method]={'predictions':len(rows),'no_intent':sum(p['status']=='NO_INTENT' for p in rows),
            'successful':sum(p['status']=='OK' for p in rows),
            'input_tokens_recorded':sum((p.get('trace',{}).get('generation',{}).get('prompt_tokens') or 0) for p in rows),
            'output_tokens_recorded':sum((p.get('trace',{}).get('generation',{}).get('output_tokens') or 0) for p in rows),
            'latency_p50':lat[int((len(lat)-1)*.5)] if lat else None,
            'latency_p95':lat[int((len(lat)-1)*.95)] if lat else None,
            'macro_family_accuracy':sum(methods[method])/len(methods[method]) if methods[method] else None,
            'macro_families':len(methods[method]),'citation_support':'PENDING_HUMAN_JUDGMENT'}
    result={'state':'COMPLETE','results':table,'coverage':coverage,
            'limitations':'F5 and citation support require human review; macro covers scored families only; no cross-model comparability asserted'}
    save(out/('scores_'+label+'_summary.json'),result)
    return result


def oracle_diagnostic(out, corpus_dir, items, split, model, max_requests, resume):
    """Non-deployable diagnostic; known gold evidence selects context, never a ranked method."""
    if split=='test' and (not frozen_original() or not (out/'BANK_FROZEN.json').exists()):
        raise RuntimeError('test oracle diagnostic requires both frozen benchmark gates')
    selected=[q for q in items if q['split']==split and q['family'] not in ('F3','F6')]
    by_record={}
    for d in read_jsonl(corpus_dir/'corpus.jsonl'):
        if d['visibility'] != 'public': raise ValueError('non-public corpus record')
        by_record.setdefault(d['record_id'],[]).append(d)
    path=out/('oracle_'+split+'.jsonl')
    identity={'model':model,'split':split,'corpus_sha256':file_hash(corpus_dir/'corpus.jsonl'),
              'bank_sha256':file_hash(out/'selected.jsonl'),'diagnostic_only':True}
    identity_path=out/('oracle_'+split+'_identity.json')
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise RuntimeError('oracle identity changed; use a new output root')
    if not identity_path.exists(): save(identity_path,identity)
    if path.exists() and not resume: raise RuntimeError('oracle output exists; use --resume')
    done=read_jsonl(path) if path.exists() else []; completed={r['qid'] for r in done}
    client=OllamaClient(model=model,max_requests=max_requests)
    print('Oracle diagnostic plan: %d pending; max %d local requests' % (len(selected)-len(completed),max_requests),flush=True)
    with path.open('a',encoding='utf-8') as f:
        for q in selected:
            if q['qid'] in completed or client.calls>=max_requests: continue
            docs=[]
            for ev in q['evidence']:
                for d in by_record.get(ev['id'],[]):
                    text='\n'.join(line for line in d['text'].splitlines() if not re.search(
                        r'(?i)\b(ignore (all |the |previous |prior )?instructions|system prompt|reveal (the )?secret)\b',line))
                    docs.append({'doc_id':d['chunk_id'],'record_id':d['record_id'],'bug_id':d['bug_id'],
                                 'url':d['url'],'text':text,'rank':len(docs)+1,'score':1.0})
            if not docs: continue
            public={k:q[k] for k in ('qid','question','scope')}
            result=answer_question(public,client,method='M1',index=FixedIndex(docs))
            result['method']='ORACLE_NON_DEPLOYABLE';result['diagnostic_only']=True
            f.write(json.dumps(result,sort_keys=True)+'\n');f.flush();done.append(result)
    return {'state':'PARTIAL' if len(done)<len(selected) else 'COMPLETE','predictions':len(done),
            'eligible':len(selected),'requests_this_invocation':client.calls,'diagnostic_only':True}

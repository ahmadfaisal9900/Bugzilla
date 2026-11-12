"""Owner-run retrieval experiments with per-query caches and resumable records."""
import json
import os
import sqlite3
import time
from pathlib import Path
from .common import (ROOT, append, checkpoint, code_hashes, digest, file_hash, git_commit,
                     locked, now, read_config, read_jsonl, receipt, verify_artifacts, write_json)
from .datasets import load_datasets, NA_FAMILIES
from .metrics import ASSUMPTION, comparisons, markdown, score, summarize
from .registry import Engine, REGISTRY, explicit_bug_id, get_retriever, jaccard
from .transforms import QueryTransforms


def tracing_off():
    # Must precede any model/provider imports. Bulk evaluation never starts tracing.
    for key in ('LANGSMITH_TRACING','LANGCHAIN_TRACING','LANGCHAIN_TRACING_V2'):
        os.environ[key]='false'


def open_cache(path):
    db=sqlite3.connect(str(path))
    db.execute('''CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY, payload TEXT NOT NULL,
        corpus TEXT NOT NULL, retriever TEXT NOT NULL, dataset TEXT NOT NULL,
        qid TEXT NOT NULL, query_sha256 TEXT NOT NULL, UNIQUE(corpus,retriever,dataset,qid))''')
    return db


def load_cached_hits(directory,corpus,retriever,dataset,qid,k=50):
    """Read-only interface for later answering stages; no benchmark gold is loaded."""
    if not 1<=k<=50: raise ValueError('Cached retrieval supports k=1..50')
    path=Path(directory)/'retrieval_cache.sqlite'
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT payload FROM results WHERE corpus=? AND retriever=? AND dataset=? AND qid=?',
                       [corpus,retriever,dataset,qid]).fetchone()
    if row is None: raise KeyError('Retrieval cache entry is absent')
    return json.loads(row[0])['hits'][:k]


def load_engine(directory,config,models,transforms):
    from bugzilla_qa.eval_extension.dense import DenseSearcher
    docs=list(read_jsonl(directory/'corpus.jsonl'))
    if any(d.get('visibility')!='public' for d in docs):
        raise RuntimeError('Index corpus has non-public or unknown visibility')
    dm=read_config(directory/'dense_manifest.json')
    if dm['revision']!=config['embedding_revision']: raise RuntimeError('Embedding revision mismatch')
    dense=DenseSearcher(directory/'corpus.jsonl',directory,config['embedding_model'],config['device'],model=models[0])
    return Engine(docs,directory/'lexical.sqlite',dense,models[1],
                  json.loads((directory.parent/'graph.json').read_text()),config,transforms)


def load_models(config):
    from sentence_transformers import SentenceTransformer, CrossEncoder
    embed=SentenceTransformer(config['embedding_model'],revision=config['embedding_revision'],device=config['device'])
    cross=CrossEncoder(config['reranker_model'],revision=config['reranker_revision'],device=config['device'])
    if getattr(embed[0].auto_model.config,'_commit_hash',None)!=config['embedding_revision']:
        raise RuntimeError('Loaded embedding revision mismatch')
    if getattr(cross.model.config,'_commit_hash',None)!=config['reranker_revision']:
        raise RuntimeError('Loaded reranker revision mismatch')
    return embed,cross


def run(config,root=ROOT,*,split='dev',confirm=False,methods=None,corpora=None,datasets=None,
        limit=None,resume=False,dry_run=False,enable_llm=False,max_requests=1,index_run=None,
        tag='',reuse_run=None):
    tracing_off(); root=Path(root)
    methods=methods or config['offline_retrievers']; corpora=corpora or config['corpora']
    datasets=datasets or config['datasets']
    if any(m not in REGISTRY for m in methods): raise ValueError('Unknown retriever')
    if any(c not in config['corpora'] for c in corpora): raise ValueError('Unknown corpus')
    methods=set(methods)
    if 'R4' in methods: methods.add('R3')
    r7=bool(methods & {'R7a','R7b'})
    if r7: methods.update(('R1','R5'))
    methods=[m for m in REGISTRY if m in methods]
    questions,pins,coverage=load_datasets(config,root,split,confirm,datasets,limit)
    if not questions: raise RuntimeError('No questions selected')
    calls=len({q['question'] for q in questions})*len(set(methods)&{'R7a','R7b'})
    plan={'state':'DRY_RUN','split':split,'methods':methods,'corpora':corpora,
          'datasets':datasets,'questions':len(questions),'planned_transform_calls_upper_bound':calls,
          'max_http_attempts_this_invocation':max_requests if enable_llm and r7 else 0,
          'actual_api_calls':0,'tracing':False,'limit_per_dataset':limit,'coverage':coverage}
    if dry_run or (r7 and not enable_llm): return plan
    if index_run is None:
        pointer=read_config(root/config['index_root']/'LATEST_BUILD.json')
        name=pointer['run']
        if Path(name).name!=name: raise RuntimeError('Unsafe index pointer')
        index_run=root/config['index_root']/name
    else: index_run=root/index_run
    build=read_config(index_run/'manifest.json')
    if build['state']!='COMPLETE' or not set(corpora)<=set(build['variants']):
        raise RuntimeError('Requested corpus variants are not built')
    for c in corpora: verify_artifacts(index_run/c,read_config(index_run/c/'manifest.json'))
    config_snapshot=dict(config)
    transforms=None; provider=None
    if r7:
        from bugzilla_qa.llm.provider import create_provider, resolved_config
        effective=resolved_config(read_config(root/config['llm_config']),root)
        config_snapshot['effective_llm_config']=effective
        provider=create_provider(effective,'generator',enable_llm=enable_llm,max_requests=max_requests,
                                 root=root,resolve_env=False)
        transforms=QueryTransforms(provider)
    protocol=root/'docs/RETRIEVER_SELECTION.md'
    compatibility=digest({'config':config,'code':code_hashes(),'inputs':pins,
                          'index_manifest':file_hash(index_run/'manifest.json'),
                          'questions':[(q['dataset'],q['qid'],q['question']) for q in questions]})
    identity={'compatibility':compatibility,'methods':methods,'corpora':corpora,
              'config':config_snapshot,'split':split,'limit':limit,'test_confirmed':confirm,
              'selection_protocol_sha256':file_hash(protocol),'git_commit':git_commit(),'tag':tag}
    out=root/config['output_root']/('run-'+digest(identity)[:16])
    if split=='test' and out.exists(): raise RuntimeError('Existing locked-test run: refusing overwrite/resume; choose a new --run-tag')
    with locked(out):
        if (out/'manifest.json').exists():
            m=read_config(out/'manifest.json')
            if m['state']=='COMPLETE':
                if not resume: raise RuntimeError('Completed run exists; use --resume for verification')
                verify_artifacts(out,m)
                return dict(plan,state='ALREADY_COMPLETE_VERIFIED',output=str(out))
        if (out/'identity.json').exists():
            if not resume: raise RuntimeError('Run exists; use --resume')
            if read_config(out/'identity.json')!=identity: raise RuntimeError('Run identity mismatch')
        write_json(out/'identity.json',identity); write_json(out/'config_snapshot.json',config_snapshot)
        if split=='test':
            write_json(out/'LOCKED_TEST_ACCESS.json',{'confirmed':True,'accessed_at_utc':now(),
                        'git_commit':git_commit(),'input_hashes':pins,'tuning_forbidden':True})
        # Baseline cache reuse avoids rerunning R1/R5 for the R7 experiment.
        reuse=None
        if r7 and reuse_run is None and (root/config['output_root']/'LATEST_OFFLINE.json').exists():
            reuse_run=root/config['output_root']/read_config(root/config['output_root']/'LATEST_OFFLINE.json')['run']
        if reuse_run:
            base=root/reuse_run
            previous=read_config(base/'identity.json')
            if previous['compatibility']!=compatibility: raise RuntimeError('Reuse run has different source/question/index identity')
            m=read_config(base/'manifest.json')
            if m['state']!='COMPLETE': raise RuntimeError('Cannot reuse partial retrieval run')
            verify_artifacts(base,m)
            reuse=sqlite3.connect('file:'+str(base/'retrieval_cache.sqlite')+'?mode=ro',uri=True)
        cache=open_cache(out/'retrieval_cache.sqlite')
        rows=checkpoint(out/'per_question.jsonl')
        keys={(r['dataset'],r['qid'],r['retriever'],r['corpus']) for r in rows}
        if len(keys)!=len(rows): raise RuntimeError('Duplicate checkpoint entries')
        valid={(q['dataset'],q['qid'],m,c) for q in questions for m in methods for c in corpora}
        if not keys<=valid: raise RuntimeError('Checkpoint contains unexpected questions/methods')
        blocker=None
        try:
            if len(keys)<len(valid):
                models=load_models(config)
                from tqdm import tqdm
                for c in tqdm(corpora,desc='Corpora',unit='corpus'):
                    if all((q['dataset'],q['qid'],m,c) in keys for q in questions for m in methods): continue
                    engine=load_engine(index_run/c,config,models,transforms)
                    record_ids={d['record_id'] for d in engine.docs}
                    for q in tqdm(questions,desc=c+' questions',unit='question',leave=False):
                        for method in methods:
                            key=(q['dataset'],q['qid'],method,c)
                            if key in keys: continue
                            cache_key=digest([compatibility,key,q['question'],
                                              config_snapshot.get('effective_llm_config') if method.startswith('R7') else None])
                            cached=cache.execute('SELECT payload FROM results WHERE key=?',[cache_key]).fetchone()
                            from_reuse=False
                            if not cached and reuse:
                                cached=reuse.execute('SELECT payload FROM results WHERE key=?',[cache_key]).fetchone()
                                from_reuse=bool(cached)
                            if cached: payload=json.loads(cached[0])
                            else:
                                started=time.perf_counter()
                                hits=get_retriever(method,engine).retrieve(q['question'],config['candidate_k'])
                                elapsed=(time.perf_counter()-started)*1000
                                info=transforms.info(method,q['question']) if transforms and method.startswith('R7') else {}
                                # Cached transforms retain the cost of their original generation for fair eligibility.
                                adjusted=elapsed+max(0,info.get('original_latency_ms',0)-info.get('reuse_latency_ms',0))
                                payload={'hits':hits,'latency_ms':adjusted,'measured_reuse_latency_ms':elapsed,
                                         'query_transform':info}
                            cache.execute('INSERT OR IGNORE INTO results VALUES (?,?,?,?,?,?,?)',
                                          [cache_key,json.dumps(payload,sort_keys=True),c,method,q['dataset'],q['qid'],digest(q['question'])])
                            cache.commit()
                            hits=payload['hits']
                            row=dict(dataset=q['dataset'],qid=q['qid'],family=q['family'],split=split,
                                     cluster_id=q['cluster_id'],retriever=method,corpus=c,
                                     latency_ms=payload['latency_ms'],retrieval_cache_hit=bool(cached),
                                     reused_previous_run=from_reuse,query_transform=payload['query_transform'],
                                     known_evidence_n=len(q['relevant']),unindexed_known_evidence_n=len(set(q['relevant'])-record_ids),
                                     hits=[{k:h[k] for k in ('chunk_id','record_id','bug_id','chunk_type','score','rank','graph_expansion','unmatched_fallback') if k in h}
                                           for h in hits],
                                     metrics=score(hits,q['relevant'],q['family'],q['acceptable_bug_ids']))
                            if method=='R4':
                                row['r4_mode']='EXACT_ID' if explicit_bug_id(q['question']) else 'PARENT_DISCOVERY'
                                row['r4_parent_bug_ids']=hits[0].get('stage1_bug_ids',[]) if hits else []
                                base=next((r['hits'] for r in reversed(rows) if r['dataset']==q['dataset']
                                            and r['qid']==q['qid'] and r['corpus']==c and r['retriever']=='R3'),[])
                                row['r4_r3_jaccard_top10']=jaccard(hits,base)
                            append(out/'per_question.jsonl',row);rows.append(row);keys.add(key)
        except RuntimeError as exc:
            blocker=str(exc) # Shared provider already redacts credentials from surfaced errors.
        finally:
            cache.close()
            if reuse: reuse.close()
        state='COMPLETE' if keys==valid else 'PARTIAL'
        roster={}
        for q in questions:
            if q['dataset'] in ('v3','natural') and q['family'] not in NA_FAMILIES and q['relevant']:
                roster.setdefault(q['dataset']+':'+q['family'],[]).append(q['qid'])
        eligible={k:sorted(v) for k,v in roster.items() if len(v)>=config['selection_min_n']}
        selection_obs=[{k:r[k] for k in ('dataset','family','qid','retriever','corpus','latency_ms')} |
                       {'recall_at_10':r['metrics']['recall_at_10']} for r in rows
                       if r['dataset']+':'+r['family'] in eligible]
        result=dict(plan,state=state,output=str(out),blocker=blocker,actual_api_calls=provider.calls if provider else 0,
                    input_sha256=pins,index_build=str(index_run.relative_to(root)),compatibility=compatibility,
                    limited=bool(limit or build.get('limit_bugs')),locked_test_used=split=='test',
                    assumptions=ASSUMPTION,cells=summarize(rows,datasets,config['families'],methods,corpora,coverage),
                    bootstrap=comparisons(rows,config),selection_roster=eligible,selection_observations=selection_obs,
                    completed_rows=len(rows),expected_rows=len(valid),selection_protocol_sha256=file_hash(protocol))
        write_json(out/'summary.json',result); (out/'summary.md').write_text(markdown(result),encoding='utf-8')
        receipt(out,state=state,identity=digest(identity),input_sha256=pins,config=config_snapshot,
                models={k:config[k] for k in ('embedding_model','embedding_revision','reranker_model','reranker_revision')},
                counts={'questions':len(questions),'result_rows':len(rows)},locked_test_used=split=='test')
        if state=='COMPLETE' and split=='dev':
            write_json(root/config['output_root']/('LATEST_R7.json' if r7 else 'LATEST_OFFLINE.json'),{'run':out.name})
        return {k:v for k,v in result.items() if k not in ('cells','bootstrap','selection_observations','input_sha256','selection_roster')}

"""Versioned prediction ledgers, request planning and opt-in sampled tracing."""
import contextlib
import json
import math
import os
import sqlite3
import time
import datetime as dt
from pathlib import Path
from collections import Counter,defaultdict
from langsmith import Client, trace, tracing_context
from urllib3.util.retry import Retry
from bugzilla_qa.llm.provider import create_provider, resolved_config, env_values, PACIFIC
from bugzilla_qa.retrieval_v3.common import (ROOT,read_config,read_jsonl,write_json,
    file_hash,digest,git_commit,now,append,checkpoint,locked)
from .backend import Backend
from .contracts import clean, ANSWER_SCHEMA,pack
from .graph import AnswerGraph, SYSTEMS,rule_route
from .sources import questions,oracle_references
from .tools import Tools


class AccountingProvider:
    """Observe the existing provider, including calls made inside retrievers."""
    def __init__(self,provider):self.provider=provider;self.events=[]
    def __getattr__(self,name):return getattr(self.provider,name)
    def _call(self,name,*args,**kwargs):
        response=getattr(self.provider,name)(*args,**kwargs)
        self.events.append({k:v for k,v in response.items() if k!='value'})
        return response
    def generate_json(self,*args,**kwargs):return self._call('generate_json',*args,**kwargs)
    def generate_tools(self,*args,**kwargs):return self._call('generate_tools',*args,**kwargs)


def trace_client(config,root,enabled):
    if not enabled:return None
    env=env_values(root/'.env');key=os.environ.get('LANGSMITH_API_KEY') or os.environ.get('LANGSMITH_KEY') or env.get('LANGSMITH_API_KEY') or env.get('LANGSMITH_KEY')
    if not key:raise RuntimeError('--trace requires LANGSMITH_API_KEY or LANGSMITH_KEY')
    # Map aliases in memory; no dotenv export or secret-bearing config snapshot.
    endpoint=os.environ.get('LANGSMITH_ENDPOINT') or env.get('LANGSMITH_ENDPOINT','https://api.smith.langchain.com')
    return Client(api_key=key,api_url=endpoint,auto_batch_tracing=False,
                  retry_config=Retry(total=0,connect=0,read=0,status=0),timeout_ms=30000)


def sampled(q,system,rate):
    return int(digest([system,q['qid']])[:12],16)/float(16**12)<rate


def prepare(config,root,dataset,split,confirm=False,tag=''):
    rows,pins=questions(config,root,dataset,split,confirm)
    llm=resolved_config(read_config(root/config['llm_config']),root)
    if llm.get('temperature')!=0:raise RuntimeError('Matched systems require temperature=0')
    selection=read_config(root/config['selection'])
    source=read_config(root/config['source_config'])
    base=read_config((root/source['canonical_db']).parent/'manifest.json')
    history=read_config((root/source['history_db']).parent/'summary.json')
    if base.get('state')!='COMPLETE' or base.get('identity_hash')!=source['base_identity']:
        raise RuntimeError('Canonical source manifest identity mismatch')
    if history.get('state')!='COMPLETE' or history.get('candidate_manifest_sha256')!=source['history_identity']:
        raise RuntimeError('Verified Phase 4 source identity mismatch')
    if (root/source['canonical_db']).stat().st_size!=base['artifacts']['canonical.duckdb']['bytes']:
        raise RuntimeError('Canonical source size mismatch; never rehash the GB database here')
    for path in [config['selection'],config['prompt'],config['retrieval_config'],config['source_config'],
                 config['history_checkpoint'],str(Path(source['canonical_db']).parent/'manifest.json'),
                 str(Path(source['history_db']).parent/'summary.json')]+[
                     str(Path(p)/'manifest.json') for p in config['retrieval_runs'] if (root/p/'manifest.json').exists()]:
        pins[path]=file_hash(root/path)
    code=list(Path(__file__).parent.glob('*.py'))+[ROOT/'src/bugzilla_qa/llm/provider.py']
    identity=dict(config=config,llm=llm,inputs=pins,code={str(p.relative_to(ROOT)):file_hash(p) for p in code},
                  dataset=dataset,split=split,tag=tag,freeze_id=rows[0]['freeze_id'] if rows else None,
                  selected=selection['selected'],index_manifest_sha256=file_hash(root/selection['index_build']/'manifest.json'))
    config_hash=digest(identity);directory=root/config['output_root']/dataset/split/('run-'+config_hash[:16])
    if not directory.resolve().is_relative_to((root/'outputs/predictions').resolve()):
        raise RuntimeError('Prediction output must remain under outputs/predictions, outside frozen/source directories')
    return rows,pins,llm,identity,config_hash,directory


def pending(rows,directory,system,resume,limit=None,per_family=None,family=None):
    path=directory/(system+'.jsonl');done=set()
    if path.exists():
        if not resume:raise RuntimeError('Ledger exists; use --resume')
        done={r['qid'] for r in read_jsonl(path) if r['status']=='ok'}
    selected=[];counts=Counter()
    for q in rows:
        if family and q['family'] not in family:continue
        if per_family and counts[q['family']]>=per_family:continue
        counts[q['family']]+=1
        if q['qid'] in done:continue
        selected.append(q)
        if limit and len(selected)>=limit:break
    return selected,len(done)


def cached_generation_key(llm,prompt,system_prompt,schema,version):
    backend=llm.get('provider','gemini')
    return digest(([backend] if backend!='gemini' else [])+[llm['models']['generator']['id'],version,system_prompt,prompt,schema])


def plan(config,root,*,dataset='v3',split='dev',confirm=False,systems=None,resume=False,limit=None,per_family=None,family=None,tag='',**unused):
    rows,pins,llm,identity,ch,directory=prepare(config,root,dataset,split,confirm,tag)
    systems=systems or config['systems']; model=llm['models']['generator'];safe_daily=int(model['rpd']*llm['daily_fraction'])
    result=dict(state='DRY_RUN',actual_api_calls=0,output=str(directory.relative_to(root)),model=model['id'],
                provider=llm.get('provider'),trace=False,split=split,dataset=dataset,systems={},
                note='Expected/upper counts include missing transforms, repair and tool turns; HTTP retries consume the same max-requests budget. S7/ambiguous routing cannot be predicted exactly.')
    provider=create_provider(llm,'generator',enable_llm=False,max_requests=1,root=root,resolve_env=False)
    backend=Backend(config,root,provider)
    response_cache=root/llm['cache'];cache=None
    if response_cache.exists():cache=sqlite3.connect('file:'+str(response_cache)+'?mode=ro',uri=True)
    prompt_text=(root/config['prompt']).read_text();rc=backend.rc
    try:
        for system in systems:
            subset,done=pending(rows,directory,system,resume,limit,per_family,family)
            expected=upper=cache_hits=transform_upper=0
            for q in subset:
                route=system;route_extra=0
                if system=='S8':
                    route,_=rule_route(q['question'])
                    if route is None:
                        expected+=3;upper+=11;continue # Classification may select the multi-turn S7 arm.
                expected+=route_extra;upper+=route_extra
                if route=='S7':expected+=2;upper+=10;continue
                if route=='S4':expected+=1;upper+=2;continue
                retrieved=[];ready=True
                if route=='S5':
                    # Dossier fallback may invoke the selected R7 method.
                    from bugzilla_qa.retrieval_v3.registry import explicit_bug_id
                    if explicit_bug_id(q['question']):retrieved=backend.dossier(q)
                    else:ready=False;transform_upper+=1
                elif route not in ('S0','ORACLE'):
                    method={'S1':'R1','S2':backend.selected,'S3':config['query_transform'],'S6':'R6'}[route]
                    # Inspect cached rows directly, with no model loading/live retrieval.
                    found=False
                    try:
                        retrieved,_=backend.retrieve(q,method,cached_only=True);found=True
                    except KeyError:pass
                    ready=found
                    if not found and method.startswith('R7'):transform_upper+=1
                elif route=='ORACLE':ready=False
                hit=False
                if ready and cache:
                    payload={'question':q['question']}
                    if route!='S0':
                        context,mapping=pack(retrieved,config['dossier_tokens'] if route=='S5' else config['context_tokens'])
                        payload.update(declared_scope=q.get('scope',{}),evidence=context,citation_map=mapping)
                    key=cached_generation_key(llm,json.dumps(payload),prompt_text,ANSWER_SCHEMA,config['prompt_version'])
                    hit=bool(cache.execute('SELECT 1 FROM responses WHERE key=?',[key]).fetchone())
                cache_hits+=int(hit);expected+=int(not hit);upper+=2*int(not hit)
            expected+=transform_upper;upper+=transform_upper
            result['systems'][system]=dict(pending_questions=len(subset),already_ok=done,
                families=dict(Counter(q['family'] for q in subset)),known_answer_cache_hits=cache_hits,
                estimated_model_calls=expected,model_calls_upper_bound=upper,
                missing_transform_calls_upper_bound=transform_upper,
                max_http_attempts_with_retries=upper*(llm['max_retries']+1),
                input_tokens_upper_estimate=len(subset)*(len(prompt_text.encode())+config['context_tokens']+1000),
                output_tokens_upper_estimate=upper*llm['max_output_tokens'],
                days_at_safe_rpd=math.ceil(expected/safe_daily) if expected else 0,
                minutes_at_effective_rpm=round(expected/max(1,model['rpm']-1),1))
    finally:
        if cache:cache.close()
    result['estimated_model_calls']=sum(s['estimated_model_calls'] for s in result['systems'].values())
    result['days_at_safe_rpd']=math.ceil(result['estimated_model_calls']/safe_daily)
    today=dt.datetime.now(dt.timezone.utc).astimezone(PACIFIC).date();used=0
    ledger=root/llm['ledger']
    if ledger.exists():
        for row in read_jsonl(ledger):
            if (row.get('status')=='REQUEST_STARTED' and row.get('model')==model['id']
                and row.get('provider','gemini')==llm.get('provider','gemini')
                and dt.datetime.fromisoformat(row['ts'].replace('Z','+00:00')).astimezone(PACIFIC).date()==today):used+=1
    result['safe_rpd']=safe_daily;result['requests_today']=used;result['remaining_safe_requests_today']=max(0,safe_daily-used)
    return result


def run(config,root,*,dataset='v3',split='dev',confirm=False,systems=None,resume=False,limit=None,per_family=None,family=None,
        tag='',enable_llm=False,max_requests=1,trace_enabled=False,trace_sample=None,dry_run=False):
    if dry_run or not enable_llm:
        return plan(config,root,dataset=dataset,split=split,confirm=confirm,systems=systems,resume=resume,
                    limit=limit,per_family=per_family,family=family,tag=tag)
    rows,pins,llm,identity,ch,directory=prepare(config,root,dataset,split,confirm,tag)
    systems=systems or config['systems']
    # S0 always precedes contextual arms; calls remain stateless provider requests.
    systems=sorted(systems,key=lambda x:list(SYSTEMS).index(x))
    provider=AccountingProvider(create_provider(llm,'generator',enable_llm=True,max_requests=max_requests,root=root,resolve_env=False))
    backend=Backend(config,root,provider);tools=Tools(config,root,backend)
    client=trace_client(config,root,trace_enabled)
    rate=config['trace_sample'] if trace_sample is None else trace_sample
    if not 0<=rate<=1:raise ValueError('trace-sample must be in [0,1]')
    result=dict(state='PARTIAL',output=str(directory.relative_to(root)),systems={},actual_api_calls=0,blocker=None)
    oracle=oracle_references(config,root,dataset,split,confirm) if 'ORACLE' in systems else {}
    with locked(directory):
        if (directory/'identity.json').exists() and read_config(directory/'identity.json')!=identity:
            raise RuntimeError('Prediction identity mismatch')
        write_json(directory/'identity.json',identity);write_json(directory/'config_snapshot.json',dict(config,effective_llm=llm))
        if split=='test':write_json(directory/'LOCKED_TEST_ACCESS.json',dict(confirmed=True,at_utc=now(),freeze_id=identity['freeze_id'],tuning_forbidden=True))
        try:
            from tqdm import tqdm
            for system in tqdm(systems,desc='Answer systems',unit='system'):
                # Repair only an incomplete final append; preserve its backup.
                checkpoint(directory/(system+'.jsonl'))
                subset,done=pending(rows,directory,system,resume,limit,per_family,family)
                current=[]
                def persist(s):
                    usage=provider.events[usage_start:];charged=[u for u in usage if u.get('state')!='CACHE_HIT']
                    row=dict(qid=s['qid'],system_id=system,dataset=dataset,split=split,
                        family=s['family'],freeze_id=s['freeze_id'],status=s['status'],at_utc=now(),config_hash=ch,
                        model=llm['models']['generator']['id'],provider=llm.get('provider'),prompt_version=config['prompt_version'],
                        route=s['route'],route_rule=s['route_rule'],answer=s['answer'],raw_output=s['raw_output'],
                        retrieved_chunk_ids=[d['chunk_id'] for d in s['retrieved']],context_chunk_ids=s['context_ids'],
                        context_map=s['context_map'],context_token_counter=config['token_counter'],
                        errors=s['errors'],call_count=s['call_count'],cache_hit=s['cache_hit'],
                        tokens={'input':sum(u.get('input_tokens') or 0 for u in charged),
                                'output':sum(u.get('output_tokens') or 0 for u in charged),
                                'cached_input':sum(u.get('input_tokens') or 0 for u in usage if u.get('state')=='CACHE_HIT'),
                                'cached_output':sum(u.get('output_tokens') or 0 for u in usage if u.get('state')=='CACHE_HIT'),
                                'usage_missing':bool(s['errors']) or any(u.get('input_tokens') is None for u in usage)},
                        latency_ms=round((time.perf_counter()-s['started_at'])*1000),
                        tools=s['tool_log'],diagnostic_only=system=='ORACLE',
                        oracle_coverage=({'requested_record_ids':s.get('oracle_refs',[]),
                            'available_record_ids':sorted({d['record_id'] for d in s['retrieved']}),
                            'packed_chunk_ids':s['context_ids']} if system=='ORACLE' else None))
                    row=clean(row,root);append(directory/(system+'.jsonl'),row);current.append(row)
                graph=AnswerGraph(config,provider,backend,tools,(root/config['prompt']).read_text(),persist,confirm)
                for q in tqdm(subset,desc=system+' '+dataset,unit='question'):
                    usage_start=len(provider.events)
                    if provider.calls>=max_requests:
                        result['blocker']='Invocation request budget reached; resume the same command';break
                    if system=='ORACLE':q=dict(q,oracle_refs=oracle.get(q['qid'],[]))
                    enabled=trace_enabled and sampled(q,system,rate)
                    metadata=dict(system_id=system,qid=q['qid'],family=q['family'],split=split,dataset=dataset,
                        freeze_id=q['freeze_id'],model=llm['models']['generator']['id'],prompt_version=config['prompt_version'],
                        config_hash=ch,route=system,cache_hit=False)
                    with tracing_context(enabled=enabled,client=client,project_name=config['trace_projects'][split]):
                        context=trace(system+':'+q['qid'],inputs=clean({'question':q['question']}),metadata=metadata,client=client,
                                      project_name=config['trace_projects'][split]) if enabled else contextlib.nullcontext(None)
                        with context as root_run:
                            state=graph.invoke(q,system,ch)
                            if root_run:
                                root_run.add_metadata(clean(dict(route=state['route'],route_rule=state['route_rule'],cache_hit=state['cache_hit'])))
                                root_run.end(outputs=clean({'answer':state['answer'],'errors':state['errors']}))
                    if state['status']!='ok':
                        result['blocker']={'qid':q['qid'],'errors':state['errors'],'next':'Inspect redacted ledger and resume'};break
                result['systems'][system]=dict(already_ok=done,written=len(current),ok=sum(r['status']=='ok' for r in current),requested=len(subset))
                if result['blocker']:break
            result['state']='COMPLETE_SELECTED_BATCH' if not result['blocker'] else 'PARTIAL'
        except (RuntimeError,ValueError) as exc:
            result.update(state='PARTIAL',blocker=clean(str(exc),root))
        finally:
            tools.close()
            if client:client.flush()
            result['actual_api_calls']=provider.calls
            result['remaining_by_system']={}
            for system in systems:
                path=directory/(system+'.jsonl')
                done={r['qid'] for r in read_jsonl(path) if r['status']=='ok'} if path.exists() else set()
                result['remaining_by_system'][system]=sum(q['qid'] not in done for q in rows
                    if not family or q['family'] in family)
            if not result['blocker'] and not any(result['remaining_by_system'].values()):result['state']='COMPLETE'
            write_json(directory/'summary.json',result)
            files=[p for p in directory.iterdir() if p.is_file() and p.name not in ('manifest.json','.lock')]
            write_json(directory/'manifest.json',dict(state=result['state'],created_at_utc=now(),git_commit=git_commit(),
                freeze_id=identity['freeze_id'],config_hash=ch,input_sha256=pins,config_snapshot=identity,
                locked_test_used=split=='test',counts=result['systems'],sha256={p.name:file_hash(p) for p in files}))
    return result

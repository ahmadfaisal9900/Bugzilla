"""Owner-terminal CLI. Every network operation is explicitly opt-in."""
import argparse
import json
import os
# Ignore inherited tracing defaults; tracing_context enables only sampled calls.
for key in ('LANGSMITH_TRACING','LANGCHAIN_TRACING','LANGCHAIN_TRACING_V2'):
    os.environ[key]='false'
from bugzilla_qa.retrieval_v3.common import ROOT,read_config
from .graph import SYSTEMS
from .runner import plan,run
from .calibration import suggest,with_calibration
from .contracts import clean


def main(argv=None):
    p=argparse.ArgumentParser(description='Phase 10: prediction ledgers only; no scoring. Network off unless explicitly enabled.')
    p.add_argument('command',choices=['plan','run','suggest-tau','upload-dev'])
    p.add_argument('--config',default='configs/answering.yaml')
    p.add_argument('--dataset',choices=['v3','phase05','natural'],default='v3')
    p.add_argument('--split',choices=['dev','test'],default='dev')
    group=p.add_mutually_exclusive_group()
    group.add_argument('--system',choices=list(SYSTEMS))
    group.add_argument('--systems',nargs='+',choices=list(SYSTEMS))
    p.add_argument('--family',nargs='+');p.add_argument('--limit',type=int)
    p.add_argument('--qid',nargs='+',help='Fixed question IDs; resume never advances beyond them. Use for a minimal live smoke.')
    p.add_argument('--limit-per-family',type=int)
    p.add_argument('--confirm-locked-test',action='store_true')
    p.add_argument('--enable-llm',action='store_true')
    p.add_argument('--max-requests',type=int,default=1,help='Hard cap on HTTP attempts through shared LLM provider; includes transforms, retries and repairs.')
    p.add_argument('--trace',action='store_true');p.add_argument('--trace-sample',type=float)
    p.add_argument('--resume',action='store_true');p.add_argument('--dry-run',action='store_true')
    p.add_argument('--run-tag',default='')
    p.add_argument('--write',action='store_true',help='Write offline dev tau suggestion.')
    p.add_argument('--enable-upload',action='store_true',help='Explicit LangSmith dev reference upload; no evaluators.')
    p.add_argument('--quantile',type=float,default=.1)
    a=p.parse_args(argv)
    if a.max_requests<1 or a.limit is not None and a.limit<1 or a.limit_per_family is not None and a.limit_per_family<1:
        p.error('limits must be positive')
    if a.trace_sample is not None and not 0<=a.trace_sample<=1:p.error('trace-sample must be in [0,1]')
    config=with_calibration(read_config(ROOT/a.config),ROOT)
    try:
        if a.command=='suggest-tau':
            if a.split!='dev':p.error('tau calibration is dev-only')
            result=suggest(config,ROOT,write=a.write and not a.dry_run,quantile=a.quantile)
        elif a.command=='upload-dev':
            if a.split!='dev':p.error('reference upload is dev-only')
            from .upload import upload
            result=upload(config,ROOT,enable=a.enable_upload and not a.dry_run,
                          max_requests=a.max_requests,limit=a.limit,resume=a.resume)
        else:
            kwargs=dict(dataset=a.dataset,split=a.split,confirm=a.confirm_locked_test,
                systems=[a.system] if a.system else a.systems,resume=a.resume,limit=a.limit,
                per_family=a.limit_per_family,family=a.family,tag=a.run_tag,qids=a.qid)
            if a.command=='plan':result=plan(config,ROOT,**kwargs)
            else:result=run(config,ROOT,**kwargs,enable_llm=a.enable_llm,max_requests=a.max_requests,
                trace_enabled=a.trace,trace_sample=a.trace_sample,dry_run=a.dry_run)
        print(json.dumps(result,indent=2,sort_keys=True))
        return 2 if result.get('state')=='PARTIAL' else 0
    except (RuntimeError,ValueError) as exc:
        print(json.dumps({'state':'BLOCKED','error':clean(str(exc))}));return 2

if __name__=='__main__':raise SystemExit(main())

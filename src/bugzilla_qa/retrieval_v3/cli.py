"""Versioned corpus build, retrieval evaluation and preregistered selection."""
import argparse
import json
from pathlib import Path
from .common import ROOT, read_config


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','eval','select'])
    p.add_argument('--config',type=Path,default=ROOT/'configs/retrieval_v3.yaml')
    p.add_argument('--dry-run',action='store_true',help='Plan only; no models or API requests')
    p.add_argument('--limit',type=int,help='Build: first N bugs. Eval: first N qids per dataset; never eligible for selection')
    p.add_argument('--resume',action='store_true',help='Skip verified completed work; locked-test runs cannot resume')
    p.add_argument('--corpora',nargs='+',choices=['C0','C1','C2'])
    p.add_argument('--retrievers',nargs='+',choices=['R1','R2','R3','R4','R5','R6','R7a','R7b'])
    p.add_argument('--datasets',nargs='+',choices=['phase05','natural','v3'])
    p.add_argument('--split',choices=['dev','test'],default='dev')
    p.add_argument('--confirm-locked-test',action='store_true')
    p.add_argument('--enable-llm',action='store_true',help='Opt in to shared provider calls for R7 only')
    p.add_argument('--max-requests',type=int,default=1,help='Total provider HTTP attempt cap per invocation, including retries')
    p.add_argument('--index-run',type=Path,help='Existing versioned build; default LATEST_BUILD.json')
    p.add_argument('--reuse-run',type=Path,help='Verified compatible offline run cache; R7 defaults to latest offline run')
    p.add_argument('--run-tag',default='',help='Explicit new run identity (required to repeat a locked-test experiment)')
    p.add_argument('--summaries',nargs='+',type=Path,help='Selection: offline summary first, optional R7 summary second')
    p.add_argument('--latest',action='store_true',help='Selection: use latest completed offline and R7 dev pointers')
    p.add_argument('--output',type=Path,help='Selection YAML path; refuses overwrite')
    return p


def main(argv=None):
    p=parser(); a=p.parse_args(argv); config=read_config(a.config)
    if a.limit is not None and a.limit<1: p.error('--limit must be positive')
    if a.max_requests<1: p.error('--max-requests must be positive')
    if a.split=='test' and not a.confirm_locked_test: p.error('--split test requires --confirm-locked-test')
    if a.enable_llm and a.command!='eval': p.error('--enable-llm is only valid for eval')
    if a.command=='build':
        from .corpus import build
        result=build(config,ROOT,dry_run=a.dry_run,limit=a.limit,resume=a.resume,variants=a.corpora)
    elif a.command=='eval':
        from .runner import run
        result=run(config,ROOT,split=a.split,confirm=a.confirm_locked_test,methods=a.retrievers,
                   corpora=a.corpora,datasets=a.datasets,limit=a.limit,resume=a.resume,dry_run=a.dry_run,
                   enable_llm=a.enable_llm,max_requests=a.max_requests,index_run=a.index_run,
                   tag=a.run_tag,reuse_run=a.reuse_run)
    else:
        from .selection import select
        paths=a.summaries or []
        if a.latest:
            for name in ('LATEST_OFFLINE.json','LATEST_R7.json'):
                marker=ROOT/config['output_root']/name
                if marker.exists():
                    run=read_config(marker)['run']
                    if Path(run).name!=run: raise RuntimeError('Unsafe evaluation pointer')
                    paths.append(Path(config['output_root'])/run/'summary.json')
        if not paths: p.error('select requires --summaries or --latest')
        result=select(config,paths,ROOT,a.output,a.dry_run)
    print(json.dumps(result,sort_keys=True,indent=2))
    return 2 if result['state']=='PARTIAL' else 0


if __name__=='__main__': raise SystemExit(main())

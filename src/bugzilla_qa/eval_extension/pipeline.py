"""Resumable, local-only retrieval pipeline. Run large stages in the user's terminal."""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from bugzilla_qa.data.normalize import digest
from bugzilla_qa.eval_extension import cli
from bugzilla_qa.eval_extension.bank import build_bank, ordered, make_item
from bugzilla_qa.eval_extension.dense import DenseSearcher, build_dense, hierarchical, rerank
from bugzilla_qa.eval_extension.metrics import score_ranked, summarize, subset_summary, paired_cluster_interval
from bugzilla_qa.eval_extension.retrieval import BUG_ID, lexical_search, rrf

ROOT = cli.ROOT
STAGES = ('preflight','bank','natural','corpus','audit','lexical','dense','retrieval','tune','m3-dev','inference','score')


def save(path, obj):
    path = Path(path); tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str)+'\n')
    os.replace(str(tmp), str(path))


def write_jsonl(path, rows):
    tmp = Path(str(path)+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False,sort_keys=True,default=str)+'\n')
    os.replace(str(tmp),str(path))


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def frozen_original():
    root = ROOT / 'outputs/benchmark/phase05/run-65c5be3381f66811'
    pointer = root / 'FROZEN'
    if not pointer.is_file(): return False
    name = pointer.read_text().strip()
    if Path(name).name != name: raise ValueError('invalid freeze pointer')
    dest = root / name
    manifest = json.loads((dest/'manifest.json').read_text())
    if manifest.get('state') != 'FROZEN_HUMAN_SIGNED': return False
    for n,h in manifest['sha256'].items():
        if Path(n).name != n or cli.file_hash(dest/n) != h: raise ValueError('original freeze hash mismatch')
    return True


def lexical_identity(config, limit):
    return digest({'config':config, 'limit':limit, 'code':cli.file_hash(Path(cli.__file__)),
                   'retrieval_code':cli.file_hash(Path(cli.__file__).with_name('retrieval.py'))})


def verify_bank(out, sealed=False):
    path = out/'bank_manifest.json'
    manifest=json.loads(path.read_text())
    for name,expected in manifest['hashes'].items():
        if Path(name).name != name or cli.file_hash(out/name) != expected:
            raise RuntimeError('bank content hash mismatch: '+name)
    if sealed:
        receipt=json.loads((out/'BANK_FROZEN.json').read_text())
        if receipt['bank_manifest_hash'] != cli.file_hash(path):
            raise RuntimeError('sealed bank manifest has changed')
        if receipt['tuning_sha256'] != cli.file_hash(out/'tuning_dev.json'):
            raise RuntimeError('sealed tuning selection has changed')
    return manifest


def tune_dev(out):
    rows=read_jsonl(out/'retrieval_dev.jsonl')
    qrels={r['qid']:r for r in read_jsonl(out/'qrels_dev.jsonl')}
    grouped={}
    for row in rows:
        if row['method'] in ('bm25','dense'):
            grouped.setdefault(row['qid'],{})[row['method']]=row
    scores=[]
    for k in (30,60,90):
        votes=[]
        for qid,methods in grouped.items():
            if set(methods) != {'bm25','dense'}: continue
            qr=qrels[qid]
            if qr['family'] in ('F3','F6') or not qr['indexed_evidence_ids']: continue
            hits=rrf({name:methods[name]['hits'] for name in ('bm25','dense')},5,k)
            votes.append(score_ranked(hits,qr['indexed_evidence_ids'],qr['family'])['hit_at_5'])
        if votes: scores.append({'rrf_k':k,'hit_at_5':sum(votes)/len(votes),'questions':len(votes)})
    if not scores: raise RuntimeError('tuning needs paired dense and lexical dev results with indexed evidence')
    best=sorted(scores,key=lambda x:(-x['hit_at_5'],abs(x['rrf_k']-60),x['rrf_k']))[0]
    result={'state':'DEV_ONLY_SELECTED','grid':scores,'selected_rrf_k':best['rrf_k'],
            'metric':'known-citation Hit@5 proxy','no_test_gold_used':True,
            'retrieval_dev_sha256':cli.file_hash(out/'retrieval_dev.jsonl')}
    save(out/'tuning_dev.json',result);return result


def generate_natural(items, destination, seed):
    # This is a review queue, not approved paraphrase gold.
    chosen = []
    seen = set()
    for item in sorted((q for q in items if q['family'] in ('F1','F2','F3','F4','F6')), key=lambda x: ordered(seed,x['qid'])):
        if item['cluster_id'] in seen: continue
        seen.add(item['cluster_id']); chosen.append(item)
        if len(chosen) == 100: break
    rows = []
    for item in chosen:
        question=item['question']
        forms=(question.replace('what is its recorded ', 'what does the archive record as its ')
                       .replace('how many distinct bugs have recorded ', 'what is the number of distinct bugs with recorded ')
                       .replace('Which target bug IDs are explicitly recorded', 'What target bug IDs are explicitly recorded'),
               question.replace('Firefox bug ', 'Firefox issue ').replace('how many calendar hours elapsed', 'what was the elapsed calendar time in hours')
                       .replace('how many distinct bugs', 'what number of distinct bugs'))
        for variant, text in enumerate(forms,1):
            rows.append({'parent_qid':item['qid'],'cluster_id':item['cluster_id'],'split':item['split'],
                         'variant':variant,'original':item['question'],'proposed_question':text,
                         'shared_context':'Use the specified broad metadata archive and verified event overlay; snapshot date is unknown.',
                         'decision':'PENDING','reviewer':'','reviewed_at_utc':'','note':''})
    with destination.open('w',encoding='utf-8',newline='') as f:
        cols=['parent_qid','cluster_id','split','variant','original','proposed_question','shared_context','decision','reviewer','reviewed_at_utc','note']
        writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader();writer.writerows(rows)
    ambiguous=[]
    for item in chosen[:5]:
        ambiguous.append({'parent_qid':item['qid'],'cluster_id':item['cluster_id'],'split':item['split'],
                          'question':'What was the outcome of that bug?',
                          'expected_behavior':'request clarification about the bug and evidence scope',
                          'human_review_state':'PENDING_HUMAN_REVIEW'})
    save(destination.with_name('ambiguous_candidates.json'),ambiguous)
    return {'state':'PENDING_HUMAN_REVIEW','parents':len(chosen),'variants':len(rows)}


def export_approved_natural(out):
    """Import only genuine human signoffs; unreviewed variants are not evaluated."""
    parents={q['qid']:q for q in read_jsonl(out/'selected.jsonl')}
    approved=[]; counts=Counter()
    with (out/'natural_review.csv').open(newline='',encoding='utf-8') as f:
        for row in csv.DictReader(f):
            decision=row['decision'].strip().upper();counts[decision]+=1
            if decision not in ('PENDING','APPROVE','REJECT'):
                raise ValueError('natural decisions must be PENDING, APPROVE or REJECT')
            if decision!='APPROVE': continue
            parent=parents.get(row['parent_qid'])
            if not parent or row['original'] != parent['question'] or row['split'] != parent['split'] or row['cluster_id'] != parent['cluster_id']:
                raise ValueError('natural parent or split mismatch')
            if not row['reviewer'].strip() or not row['proposed_question'].strip():
                raise ValueError('approved natural variant needs a real reviewer and question')
            try:
                timestamp=datetime.fromisoformat(row['reviewed_at_utc'].replace('Z','+00:00'))
                if timestamp.utcoffset() is None: raise ValueError()
            except ValueError:
                raise ValueError('approved natural variant needs a timezone-aware review timestamp')
            item=dict(parent)
            item['question']=row['shared_context'].strip()+' '+row['proposed_question'].strip()
            item['parent_qid']=parent['qid']
            item['qid']='natural_'+digest([parent['qid'],row['variant'],item['question']])[:20]
            item['human_review_state']='HUMAN_APPROVED_WORDING'
            approved.append(item)
    dest=out/'natural_approved.jsonl'
    if not approved: raise RuntimeError('no human-approved natural variants to export')
    if dest.exists(): raise RuntimeError('approved export exists; preserve it and create a new run for changes')
    write_jsonl(dest,approved)
    result={'state':'EXPORTED_HUMAN_APPROVALS','decisions':dict(counts),'approved':len(approved),
            'sha256':cli.file_hash(dest),'review_sheet_sha256':cli.file_hash(out/'natural_review.csv')}
    save(out/'natural_approved_manifest.json',result)
    return result


def export_approved_f5(out, seed):
    packets={p['comment_id']:p for p in read_jsonl(out/'f5_review_packets.jsonl')}
    selected=[]; counts=Counter()
    with (out/'f5_review.csv').open(newline='',encoding='utf-8') as f:
        for row in csv.DictReader(f):
            decision=row['decision'].strip().upper();counts[decision]+=1
            if decision not in ('PENDING','APPROVE','INSUFFICIENT','REJECT'):
                raise ValueError('F5 decision must be PENDING, APPROVE, INSUFFICIENT or REJECT')
            if decision in ('PENDING','REJECT'): continue
            p=packets.get(row['comment_id'])
            if not p or row['content_hash']!=p['content_hash'] or row['bug_id']!=p['bug_id'] or row['source_url']!=p['source_url']:
                raise ValueError('F5 evidence changed')
            try:
                dt=datetime.fromisoformat(row['reviewed_at_utc'].replace('Z','+00:00'))
                if dt.utcoffset() is None: raise ValueError()
            except ValueError: raise ValueError('F5 approval needs a timezone-aware timestamp')
            if not row['reviewer'].strip() or row['source_checked'].upper()!='YES':
                raise ValueError('F5 approval needs a real source-checking reviewer')
            if decision=='APPROVE':
                if not row['suggested_gold'].strip(): raise ValueError('supported F5 requires a source-checked explanation')
                gold={'type':'supported_explanation','claims':[{'text':row['suggested_gold'].strip(),'evidence_id':p['comment_id']}]}
            else:
                gold={'type':'unanswerable','value':'cannot be established from the specified evidence'}
            evidence=[{'id':p['comment_id'],'bug_id':p['bug_id'],'source_url':p['source_url'],'content_hash':p['content_hash']}]
            question=('In the FIXED-selected archived comment %s for Firefox bug %s, what reason or constraint, if any, is explicitly stated?'
                      % (p['comment_id'],p['bug_id']))
            item=make_item('F5',question,gold,p['bug_id'],evidence,seed,{'subpopulation':'FIXED-selected CSV comments'})
            item['human_review_state']='SIGNED_SOURCE_REVIEW';item['validator']='human-checked public comment and fixed source hash'
            selected.append(item)
    if not selected: raise RuntimeError('no human-reviewed F5 packets to export')
    dest=out/'f5_approved.jsonl'
    if dest.exists(): raise RuntimeError('F5 approved export exists; preserve it')
    write_jsonl(dest,selected)
    report={'state':'EXPORTED_HUMAN_APPROVALS','decisions':dict(counts),'approved':len(selected),
            'sha256':cli.file_hash(dest),'review_sheet_sha256':cli.file_hash(out/'f5_review.csv')}
    save(out/'f5_approved_manifest.json',report)
    return report


def run_retrieval(out, corpus, index, selected, config, split, limit, device, resume=False, suffix=''):
    from tqdm import tqdm
    if split == 'test' and not frozen_original():
        raise RuntimeError('test is locked: original Phase 5 has not passed human-signed freeze')
    if split == 'test' and not (out/'BANK_FROZEN.json').exists():
        raise RuntimeError('test is locked: expanded bank has not been sealed')
    verify_bank(out, sealed=split == 'test')
    index_manifest=json.loads((index.parent/'lexical_manifest.json').read_text())
    if index_manifest['sha256'] != cli.file_hash(index):
        raise RuntimeError('lexical index hash mismatch')
    docs = read_jsonl(corpus)
    by_record = {}
    for d in docs: by_record.setdefault(d['record_id'], []).append(d['chunk_id'])
    wanted = [q for q in selected if q['split']==split]
    if limit: wanted = wanted[:limit]
    label=split+suffix
    checkpoint=out/('retrieval_'+label+'.jsonl')
    identity={'corpus_sha256':cli.file_hash(corpus),'index_sha256':cli.file_hash(index),
              'question_sha256':digest([(q['qid'],q['question']) for q in wanted]),
              'dense_model':config['dense_model'],'reranker_model':config['reranker_model'],
              'metrics_sha256':cli.file_hash(Path(__file__).with_name('metrics.py')),
              'retrieval_sha256':cli.file_hash(Path(__file__).with_name('retrieval.py')),
              'rrf_k':config['rrf_k'],'candidate_limit':30,'evaluation_limit':10}
    identity_path=out/('retrieval_'+label+'_identity.json')
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise RuntimeError('retrieval identity mismatch; use a new output root')
    if checkpoint.exists() and not resume: raise RuntimeError('retrieval output exists; use --resume')
    if not identity_path.exists(): save(identity_path,identity)
    rows=read_jsonl(checkpoint) if checkpoint.exists() else []
    completed={(row['qid'],row['method']) for row in rows}
    qrels=[]
    for q in wanted:
        evidence={e['id'] for e in q['evidence']}
        qrels.append({'qid':q['qid'],'family':q['family'],'known_evidence_ids':sorted(evidence),
                      'indexed_evidence_ids':sorted(evidence & set(by_record)),
                      'state':'NOT_APPLICABLE' if q['family'] in ('F3','F6') else 'INCOMPLETE_RELEVANCE_LABELS'})
    write_jsonl(out/('qrels_'+label+'.jsonl'),qrels)
    dense_error = None
    try:
        dense = DenseSearcher(corpus, out, config['dense_model'],device)
        dense_identity={'manifest_sha256':cli.file_hash(out/'dense_manifest.json'),
                        'index_sha256':cli.file_hash(out/'dense.faiss')}
        dense_pin=out/'retrieval_dense_identity.json'
        if dense_pin.exists() and json.loads(dense_pin.read_text()) != dense_identity:
            raise ValueError('dense index changed since retrieval began')
        if not dense_pin.exists(): save(dense_pin,dense_identity)
    except (ImportError, OSError, RuntimeError) as exc:
        dense=None; dense_error=str(exc)
    try:
        if dense is None: raise RuntimeError('reranking requires the dense index')
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder(config['reranker_model'],device=device)
        revision = getattr(reranker.model.config,'_commit_hash',None)
        if not revision: raise RuntimeError('reranker model revision is unavailable')
        reranker_pin=out/'reranker_identity.json'
        reranker_identity={'model':config['reranker_model'],'revision':revision}
        if reranker_pin.exists() and json.loads(reranker_pin.read_text()) != reranker_identity:
            raise RuntimeError('reranker revision changed; choose a new output root')
        if not reranker_pin.exists(): save(reranker_pin,reranker_identity)
        reranker_error = None
    except (ImportError, OSError, RuntimeError) as exc:
        if 'reranker revision changed' in str(exc): raise
        reranker = None; revision = None; reranker_error = str(exc)
    for q in tqdm(wanted,desc='Retrieval questions',unit='question'):
        methods={'bm25'}
        if dense is not None: methods.update(('dense','hybrid','hierarchical'))
        if reranker is not None: methods.add('reranked_hybrid')
        if all((q['qid'],method) in completed for method in methods): continue
        # No family, template, gold or evidence is passed into retrieval algorithms.
        query = q['question']
        start=time.perf_counter(); lex=lexical_search(index,query,30); lex_time=time.perf_counter()-start
        outputs={'bm25':(lex,lex_time)}
        if dense is not None:
            start=time.perf_counter(); den=dense.search(query,30); den_time=time.perf_counter()-start
            hybrid=rrf({'lexical':lex,'dense':den},30,config['rrf_k'])
            outputs.update({'dense':(den,den_time),'hybrid':(hybrid,lex_time+den_time)})
            start=time.perf_counter(); hier=hierarchical(query,hybrid,lex,k=10)
            outputs['hierarchical']=(hier,lex_time+den_time+time.perf_counter()-start)
        if reranker is not None:
            start=time.perf_counter(); reranked=rerank(query,hybrid,reranker,10)
            outputs['reranked_hybrid']=(reranked,lex_time+den_time+time.perf_counter()-start)
        relevant = {e['id'] for e in q['evidence'] if e['id'] in by_record}
        for method,(hits,elapsed) in outputs.items():
            if (q['qid'],method) in completed: continue
            ranked=[{k:h[k] for k in ('chunk_id','record_id','bug_id','url','rank','score','source_hash','components') if k in h} for h in hits[:30]]
            row={'qid':q['qid'],'family':q['family'],'cluster_id':q['cluster_id'], 'method':method,
                         'explicit_bug_id':bool(BUG_ID.search(query)), 'hits':ranked,
                         'elapsed_seconds':elapsed,'metrics':score_ranked(ranked,relevant,q['family']),
                         'known_evidence_total':len({e['id'] for e in q['evidence']}),
                         'known_evidence_indexed':len(relevant),
                         'stage1_bug_recall': (int(q['bug_ids'][0] in hits[0]['stage1_bug_ids']) if hits else 0)
                            if method=='hierarchical' and q['family'] not in ('F3','F6') else None}
            with checkpoint.open('a',encoding='utf-8') as f:
                f.write(json.dumps(row,sort_keys=True)+'\n'); f.flush()
            rows.append(row);completed.add((q['qid'],method))
    summary={'state':'COMPLETE' if reranker and dense else 'PARTIAL','split':split,'questions':len(wanted),
             'dense_error':dense_error,'reranker_revision':revision,'reranker_error':reranker_error,'results':summarize(rows),
             'query_subsets':subset_summary(rows),
             'hybrid_vs_bm25_cluster_bootstrap':paired_cluster_interval(rows,'hybrid','bm25'),
             'relevance':'known citations only, incomplete labels; F3/F6 not applicable'}
    save(out/('retrieval_'+label+'_summary.json'),summary)
    misses=[{'qid':r['qid'],'family':r['family'],'method':r['method'],
             'known_evidence_indexed':r['known_evidence_indexed'],
             'retrieved_record_ids':[h['record_id'] for h in r['hits'][:5]]}
            for r in rows if r['metrics'].get('state')=='KNOWN_CITATION_PROXY' and not r['metrics']['hit_at_5']]
    write_jsonl(out/('retrieval_'+label+'_known_citation_misses.jsonl'),misses)
    csv_path=out/('retrieval_'+label+'_summary.csv')
    if summary['results']:
        with csv_path.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(summary['results'][0]));writer.writeheader();writer.writerows(summary['results'])
        from bugzilla_qa.eval_extension.plots import retrieval_chart
        retrieval_chart(summary['results'],out/('retrieval_'+label+'_hit5.svg'))
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=('all','seal','track-seal','track-inference','track-score','explanations','explanations-approved','explanations-retrieval','natural-approved','natural-retrieval','oracle')+STAGES,default='all')
    parser.add_argument('--config',type=Path,default=ROOT/'configs/eval_extension.json')
    parser.add_argument('--output-root',type=Path,default=ROOT/'outputs/eval_extension')
    parser.add_argument('--limit',type=int);parser.add_argument('--seed',type=int,default=317)
    parser.add_argument('--resume',action='store_true');parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--split',choices=('dev','test'),default='dev')
    parser.add_argument('--track',choices=('natural','f5'),default='natural')
    parser.add_argument('--device',choices=('cpu','cuda'),default='cpu')
    parser.add_argument('--target',type=int,default=3000);parser.add_argument('--evaluated',type=int,default=750)
    parser.add_argument('--enable-llm',action='store_true');parser.add_argument('--model')
    parser.add_argument('--max-requests',type=int,default=5)
    args=parser.parse_args()
    if args.limit is not None and args.limit<1 or args.target<1 or args.evaluated<1 or args.max_requests<1:
        parser.error('limits and targets must be positive')
    config=json.loads(args.config.read_text())
    if args.seed != config['sample_seed']: parser.error('seed must match the sample')
    identity=lexical_identity(config,args.limit)
    corpus_dir=args.output_root/identity[:16]
    bank_id=digest([identity,args.target,args.evaluated,cli.file_hash(Path(__file__)),
                    cli.file_hash(Path(__file__).with_name('bank.py'))])[:16]
    out=args.output_root/('bank-'+bank_id)
    plan={'stage':args.stage,'out':str(out),'corpus_dir':str(corpus_dir),'split':args.split,
          'limit':args.limit,'llm_enabled':args.enable_llm,'max_requests':args.max_requests,
          'network_model_downloads':'dense and reranker may download local model weights',
          'test_gate': 'original human-signed freeze and expanded-bank seal'}
    if args.dry_run:
        print(json.dumps(plan,indent=2));return
    out.mkdir(parents=True,exist_ok=True)
    summaries={}; stage_list=STAGES if args.stage=='all' else (args.stage,)
    for stage in stage_list:
        print('[%s] %s' % (time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),stage),flush=True)
        try:
            if stage=='preflight':
                cli.verify_source_manifests(config)
                summaries[stage]={'state':'PASS','original_frozen':frozen_original()}
            elif stage=='bank':
                manifest=out/'bank_manifest.json'
                if args.resume and manifest.exists():
                    m=json.loads(manifest.read_text())
                    for n,h in m['hashes'].items():
                        if cli.file_hash(out/n)!=h: raise RuntimeError('bank hash mismatch')
                    summaries[stage]=m
                else:
                    if manifest.exists(): raise RuntimeError('bank exists; use --resume')
                    bank,selected,report=build_bank(config,args.limit,args.target,args.evaluated)
                    write_jsonl(out/'candidates.jsonl',bank);write_jsonl(out/'selected.jsonl',selected)
                    report['hashes']={n:cli.file_hash(out/n) for n in ('candidates.jsonl','selected.jsonl')}
                    save(manifest,report);summaries[stage]=report
            elif stage=='natural':
                dest=out/'natural_review.csv'
                if dest.exists() and args.resume:
                    summaries[stage]={'state':'EXISTS_REVIEW_PRESERVED'}
                elif dest.exists(): raise RuntimeError('review queue exists; use --resume')
                else: summaries[stage]=generate_natural(read_jsonl(out/'selected.jsonl'),dest,args.seed)
            elif stage=='natural-approved':
                verify_bank(out)
                summaries[stage]=export_approved_natural(out)
            elif stage=='natural-retrieval':
                approved=out/'natural_approved.jsonl'
                receipt=json.loads((out/'natural_approved_manifest.json').read_text())
                if receipt['sha256']!=cli.file_hash(approved): raise RuntimeError('approved natural file changed')
                retrieval_config=dict(config)
                if args.split=='test':
                    seal=json.loads((out/'natural_track_seal.json').read_text())
                    base_seal=json.loads((out/'BANK_FROZEN.json').read_text())
                    if (seal['approved_sha256']!=cli.file_hash(approved) or seal['bank_seal_sha256']!=cli.file_hash(out/'BANK_FROZEN.json')
                            or base_seal['config_sha256']!=cli.file_hash(args.config) or base_seal['corpus_sha256']!=cli.file_hash(corpus_dir/'corpus.jsonl')):
                        raise RuntimeError('natural test seal mismatch')
                    retrieval_config['rrf_k']=json.loads((out/'tuning_dev.json').read_text())['selected_rrf_k']
                summaries[stage]=run_retrieval(out,corpus_dir/'corpus.jsonl',corpus_dir/'lexical.sqlite',
                    read_jsonl(approved),retrieval_config,args.split,args.limit,args.device,args.resume,'_natural')
            elif stage in ('corpus','lexical'):
                command=[sys.executable,'-m','bugzilla_qa.eval_extension.cli','--stage',stage,'--config',str(args.config),'--output-root',str(args.output_root),'--seed',str(args.seed)]
                if args.limit: command+=['--limit',str(args.limit)]
                if args.resume: command+=['--resume']
                subprocess.run(command,check=True);summaries[stage]={'state':'COMPLETE'}
            elif stage=='dense':
                summaries[stage]=build_dense(corpus_dir/'corpus.jsonl',out,config['dense_model'],device=args.device,resume=args.resume)
            elif stage=='audit':
                from bugzilla_qa.eval_extension.audit import audit_corpus
                summaries[stage]=audit_corpus(corpus_dir/'corpus.jsonl')
                save(corpus_dir/'audit_summary.json',summaries[stage])
            elif stage=='explanations':
                from bugzilla_qa.eval_extension.audit import explanation_packets
                path=out/'f5_review_packets.jsonl'
                if path.exists(): raise RuntimeError('F5 review packets already exist; preserve human review data')
                packets=explanation_packets(config,min(args.limit or 60,60))
                write_jsonl(path,packets)
                review_path=out/'f5_review.csv'
                with review_path.open('w',encoding='utf-8',newline='') as f:
                    columns=['qid','bug_id','question','comment_id','source_url','content_hash','suggested_gold','decision','reviewer','reviewed_at_utc','source_checked','note']
                    writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
                    for packet in packets:
                        writer.writerow({'qid':'f5_'+digest([packet['bug_id'],packet['comment_id']])[:20],
                                         'bug_id':packet['bug_id'],'question':packet['question'],
                                         'comment_id':packet['comment_id'],'source_url':packet['source_url'],
                                         'content_hash':packet['content_hash'],'suggested_gold':'',
                                         'decision':'PENDING','reviewer':'','reviewed_at_utc':'','source_checked':'','note':''})
                summaries[stage]={'state':'PENDING_HUMAN_REVIEW','packets':len(packets)}
            elif stage=='explanations-approved':
                verify_bank(out)
                summaries[stage]=export_approved_f5(out,args.seed)
            elif stage=='explanations-retrieval':
                approved=out/'f5_approved.jsonl';receipt=json.loads((out/'f5_approved_manifest.json').read_text())
                if receipt['sha256']!=cli.file_hash(approved): raise RuntimeError('approved F5 file changed')
                retrieval_config=dict(config)
                if args.split=='test':
                    seal=json.loads((out/'f5_track_seal.json').read_text())
                    base_seal=json.loads((out/'BANK_FROZEN.json').read_text())
                    if (seal['approved_sha256']!=cli.file_hash(approved) or seal['bank_seal_sha256']!=cli.file_hash(out/'BANK_FROZEN.json')
                            or base_seal['config_sha256']!=cli.file_hash(args.config) or base_seal['corpus_sha256']!=cli.file_hash(corpus_dir/'corpus.jsonl')):
                        raise RuntimeError('F5 test seal mismatch')
                    retrieval_config['rrf_k']=json.loads((out/'tuning_dev.json').read_text())['selected_rrf_k']
                summaries[stage]=run_retrieval(out,corpus_dir/'corpus.jsonl',corpus_dir/'lexical.sqlite',
                    read_jsonl(approved),retrieval_config,args.split,args.limit,args.device,args.resume,'_f5')
            elif stage=='track-seal':
                if args.limit or not frozen_original(): raise RuntimeError('track seal requires full run and original human-signed freeze')
                verify_bank(out,sealed=True)
                approved=out/(args.track+'_approved.jsonl')
                receipt=json.loads((out/(args.track+'_approved_manifest.json')).read_text())
                if receipt['sha256']!=cli.file_hash(approved): raise RuntimeError('approved track changed')
                path=out/(args.track+'_track_seal.json')
                if path.exists(): raise RuntimeError('track is already sealed; do not overwrite')
                summaries[stage]={'state':'SEALED_HUMAN_REVIEWED_TRACK','approved_sha256':cli.file_hash(approved),
                                  'bank_seal_sha256':cli.file_hash(out/'BANK_FROZEN.json')}
                save(path,summaries[stage])
            elif stage in ('track-inference','track-score'):
                from bugzilla_qa.eval_extension.generation import infer, score_predictions
                verify_bank(out,sealed=args.split=='test')
                approved=out/(args.track+'_approved.jsonl')
                receipt=json.loads((out/(args.track+'_approved_manifest.json')).read_text())
                if receipt['sha256']!=cli.file_hash(approved): raise RuntimeError('approved track changed')
                if args.split=='test':
                    if not frozen_original(): raise RuntimeError('test track requires original benchmark freeze')
                    track_seal=json.loads((out/(args.track+'_track_seal.json')).read_text())
                    if track_seal['approved_sha256']!=cli.file_hash(approved): raise RuntimeError('track seal mismatch')
                items=read_jsonl(approved); suffix='_'+args.track
                if stage=='track-inference':
                    if not args.enable_llm or not args.model: raise RuntimeError('track inference requires --enable-llm and --model')
                    summaries[stage]=infer(out,corpus_dir,items,args.split,args.model,args.max_requests,args.resume,suffix)
                else: summaries[stage]=score_predictions(out,items,args.split,suffix)
            elif stage=='m3-dev':
                from bugzilla_qa.methods import m3_sql
                if args.split != 'dev':
                    summaries[stage]={'state':'SKIPPED','reason':'existing M3 parser is development-only'}
                    continue
                verify_bank(out)
                questions=[q for q in read_jsonl(out/'selected.jsonl') if q['split']=='dev']
                dest=out/'m3_dev_predictions.jsonl'
                if dest.exists() and args.resume:
                    summaries[stage]={'state':'COMPLETE','questions':len(read_jsonl(dest)),'note':'existing predictions preserved'}
                    continue
                if dest.exists(): raise RuntimeError('M3 predictions exist; use --resume')
                store=m3_sql.SqlStore(ROOT/config['canonical_db'], ROOT/config['history_db'],args.seed)
                try:
                    predictions=[m3_sql.answer_question(store,{k:q[k] for k in ('qid','question','scope')}) for q in questions]
                finally: store.close()
                write_jsonl(dest,predictions)
                summaries[stage]={'state':'COMPLETE','questions':len(predictions),
                                  'note':'existing development wording parser; unsupported wording remains unsupported'}
            elif stage=='oracle':
                from bugzilla_qa.eval_extension.generation import oracle_diagnostic
                if not args.enable_llm or not args.model: raise RuntimeError('oracle requires --enable-llm and --model')
                verify_bank(out,sealed=args.split=='test')
                summaries[stage]=oracle_diagnostic(out,corpus_dir,read_jsonl(out/'selected.jsonl'),
                                                   args.split,args.model,args.max_requests,args.resume)
            elif stage=='seal':
                if args.limit: raise RuntimeError('a limited bank cannot be sealed')
                if not frozen_original(): raise RuntimeError('original Phase 5 freeze required')
                if (out/'BANK_FROZEN.json').exists():
                    verify_bank(out, sealed=True)
                    summaries[stage]={'state':'ALREADY_SEALED'}
                    continue
                manifest=json.loads((out/'bank_manifest.json').read_text())
                for n,h in manifest['hashes'].items():
                    if cli.file_hash(out/n)!=h: raise RuntimeError('bank hash mismatch')
                sealed={'state':'SEALED_AUTOMATIC_FACTUAL_BANK','bank_manifest_hash':cli.file_hash(out/'bank_manifest.json'),
                        'tuning_sha256':cli.file_hash(out/'tuning_dev.json'),
                        'config_sha256':cli.file_hash(args.config),
                        'corpus_sha256':cli.file_hash(corpus_dir/'corpus.jsonl'),
                        'lexical_sha256':cli.file_hash(corpus_dir/'lexical.sqlite'),
                        'dense_sha256':cli.file_hash(out/'dense.faiss'),
                        'dense_manifest_sha256':cli.file_hash(out/'dense_manifest.json'),
                        'reranker_identity_sha256':cli.file_hash(out/'reranker_identity.json'),
                        'note':'automatic factual bank; natural and F5 tracks require separate human approval'}
                save(out/'BANK_FROZEN.json',sealed);summaries[stage]=sealed
            elif stage=='retrieval':
                verify_bank(out, sealed=args.split == 'test')
                retrieval_config=dict(config)
                if args.split=='test':
                    sealed=json.loads((out/'BANK_FROZEN.json').read_text())
                    if sealed['config_sha256'] != cli.file_hash(args.config) or sealed['corpus_sha256'] != cli.file_hash(corpus_dir/'corpus.jsonl'):
                        raise RuntimeError('sealed corpus/config changed')
                    if (sealed['lexical_sha256'] != cli.file_hash(corpus_dir/'lexical.sqlite')
                            or sealed['dense_sha256'] != cli.file_hash(out/'dense.faiss')
                            or sealed['dense_manifest_sha256'] != cli.file_hash(out/'dense_manifest.json')
                            or sealed['reranker_identity_sha256'] != cli.file_hash(out/'reranker_identity.json')):
                        raise RuntimeError('sealed index or model revision changed')
                    retrieval_config['rrf_k']=json.loads((out/'tuning_dev.json').read_text())['selected_rrf_k']
                summaries[stage]=run_retrieval(out,corpus_dir/'corpus.jsonl',corpus_dir/'lexical.sqlite',
                                               read_jsonl(out/'selected.jsonl'),retrieval_config,args.split,args.limit,args.device,args.resume)
            elif stage=='tune':
                if args.split != 'dev': raise RuntimeError('tuning is restricted to dev questions')
                if (out/'BANK_FROZEN.json').exists(): raise RuntimeError('do not retune a sealed bank')
                summaries[stage]=tune_dev(out)
            elif stage in ('inference','score'):
                from bugzilla_qa.eval_extension.generation import infer, score_predictions
                verify_bank(out, sealed=args.split == 'test')
                if args.split == 'test' and not frozen_original():
                    raise RuntimeError('test scoring requires the original human-signed freeze')
                if stage=='inference':
                    if not args.enable_llm: summaries[stage]={'state':'SKIPPED','reason':'requires --enable-llm'}
                    elif not args.model: raise RuntimeError('--model must identify an installed local Ollama model')
                    else: summaries[stage]=infer(out,corpus_dir,read_jsonl(out/'selected.jsonl'),args.split,args.model,args.max_requests,args.resume)
                else:
                    summaries[stage]=score_predictions(out,read_jsonl(out/'selected.jsonl'),args.split)
            save(out/'pipeline_summary.json',{'stages':summaries,'identity':identity,'bank_id':bank_id})
        except (Exception, subprocess.CalledProcessError) as exc:
            summaries[stage]={'state':'BLOCKED','error':str(exc)}
            save(out/'pipeline_summary.json',{'stages':summaries,'identity':identity,'bank_id':bank_id})
            print('BLOCKED %s: %s' % (stage,exc),file=sys.stderr)
            if args.stage!='all': raise
    print(json.dumps({'output':str(out),'stages':{k:v['state'] for k,v in summaries.items()}},indent=2))
    blocked=[k for k,v in summaries.items() if v['state']=='BLOCKED']
    if blocked:
        print('Resume after resolving the reported blockers: bash scripts/run_eval_extension.sh --resume',file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__': main()

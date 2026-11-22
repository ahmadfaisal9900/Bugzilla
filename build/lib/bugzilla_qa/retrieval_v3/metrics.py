"""Record-level known-citation metrics and reproducible paired cluster inference."""
import math
from collections import defaultdict
import numpy as np
from .datasets import NA_FAMILIES

MEASURES=('hit_at_1','hit_at_5','hit_at_10','recall_at_5','recall_at_10',
          'mrr_at_10','ndcg_at_10','bug_hit_at_5','mh_full_evidence_at_10')
ASSUMPTION='INCOMPLETE_RELEVANCE_LABELS: binary known-citation relevance; unlabeled chunks and repeated records score zero. Recall retains all known citations, including unindexed records.'


def score(hits,relevant,family,acceptable_bugs=()):
    result={m:None for m in MEASURES}
    if family in NA_FAMILIES: return dict(result,state='N/A')
    relevant=set(relevant)
    if not relevant: return dict(result,state='UNKNOWN',reason='No passage qrels supplied')
    seen=set(); flags=[]
    for hit in hits[:10]:
        rid=hit['record_id']; flags.append(int(rid in relevant and rid not in seen)); seen.add(rid)
    for k in (1,5,10): result['hit_at_'+str(k)]=int(any(flags[:k]))
    for k in (5,10): result['recall_at_'+str(k)]=sum(flags[:k])/len(relevant)
    first=next((i for i,v in enumerate(flags,1) if v),None)
    result['mrr_at_10']=1/first if first else 0.0
    dcg=sum(v/math.log2(i+1) for i,v in enumerate(flags,1))
    ideal=sum(1/math.log2(i+1) for i in range(1,min(len(relevant),10)+1))
    result['ndcg_at_10']=dcg/ideal
    if acceptable_bugs:
        result['bug_hit_at_5']=int(bool({str(h['bug_id']) for h in hits[:5]} & set(acceptable_bugs)))
    if family=='MH': result['mh_full_evidence_at_10']=int(relevant<=seen)
    return dict(result,state='KNOWN_CITATION_PROXY')


def percentile(values,q): return float(np.quantile(values,q)) if values else None


def summarize(rows,datasets,families,methods,corpora,coverage):
    groups=defaultdict(list)
    for r in rows: groups[r['dataset'],r['family'],r['retriever'],r['corpus']].append(r)
    cells=[]
    for ds in datasets:
        for fam in families:
            for method in methods:
                for corpus in corpora:
                    values=groups[ds,fam,method,corpus]
                    applicable=[r for r in values if r['metrics']['state']=='KNOWN_CITATION_PROXY']
                    state=('not in dataset' if not coverage.get(ds,{}).get(fam,0) else
                           'N/A' if fam in NA_FAMILIES else 'NOT_EVALUATED' if not values else
                           'KNOWN_CITATION_PROXY' if applicable else 'UNKNOWN')
                    cell={'dataset':ds,'family':fam,'retriever':method,'corpus':corpus,'n':len(values),
                          'dataset_n':coverage.get(ds,{}).get(fam,0),'n_qrels':len(applicable),'state':state}
                    for measure in MEASURES:
                        nums=[r['metrics'][measure] for r in applicable if r['metrics'][measure] is not None]
                        cell[measure]={'value':float(np.mean(nums)) if nums else None,'n':len(nums)}
                    cell['latency_p50_ms']=percentile([r['latency_ms'] for r in values],.5)
                    cell['latency_p95_ms']=percentile([r['latency_ms'] for r in values],.95)
                    overlaps=[r['r4_r3_jaccard_top10'] for r in values if r.get('r4_r3_jaccard_top10') is not None]
                    cell['r4_r3_jaccard_top10']={'value':float(np.mean(overlaps)) if overlaps else None,'n':len(overlaps)}
                    cells.append(cell)
    return cells


def paired_bootstrap(pairs,seed=317,resamples=10000):
    groups=defaultdict(list)
    for cluster,delta in pairs: groups[str(cluster)].append(delta)
    if len(groups)<2:
        return {'n':len(pairs),'clusters':len(groups),'difference':float(np.mean([d for _,d in pairs])) if pairs else None,
                'ci95':None,'p_value':None,'state':'INSUFFICIENT_CLUSTERS'}
    values=[groups[k] for k in sorted(groups)]
    totals=np.array([sum(g) for g in values]); sizes=np.array([len(g) for g in values])
    observed=float(totals.sum()/sizes.sum()); rng=np.random.default_rng(seed); samples=[]
    for start in range(0,resamples,512):
        ids=rng.integers(0,len(values),size=(min(512,resamples-start),len(values)))
        samples.extend((totals[ids].sum(axis=1)/sizes[ids].sum(axis=1)).tolist())
    null=np.asarray(samples)-observed
    p=(1+int(np.sum(np.abs(null)>=abs(observed)-1e-12)))/(resamples+1)
    return {'n':len(pairs),'clusters':len(groups),'difference':observed,
            'ci95':[percentile(samples,.025),percentile(samples,.975)],'p_value':p,
            'resamples':resamples,'seed':seed,'state':'CLUSTER_BOOTSTRAP'}


def comparisons(rows,config):
    groups=defaultdict(dict)
    for r in rows:
        if r['metrics']['state']=='KNOWN_CITATION_PROXY':
            groups[r['dataset'],r['family'],r['corpus'],r['qid']][r['retriever']]=r
    pairs=defaultdict(list)
    for (ds,fam,corpus,qid),methods in sorted(groups.items()):
        if 'R1' not in methods: continue
        for method,r in sorted(methods.items()):
            if method=='R1': continue
            for measure in ('hit_at_5','recall_at_10'):
                pairs[ds,fam,corpus,method,measure].append((r['cluster_id'],r['metrics'][measure]-methods['R1']['metrics'][measure]))
    output=[]
    for (ds,fam,corpus,method,measure),vals in sorted(pairs.items()):
        output.append(dict(dataset=ds,family=fam,corpus=corpus,retriever=method,baseline='R1',metric=measure,
                           **paired_bootstrap(vals,config['seed'],config['bootstrap_resamples'])))
    eligible=sorted((r for r in output if r['p_value'] is not None),key=lambda r:r['p_value'])
    previous=0
    for i,r in enumerate(eligible):
        previous=max(previous,min(1.0,r['p_value']*(len(eligible)-i)))
        r['holm_p_value']=previous
    return output


def markdown(summary):
    lines=['# Retrieval v3 evaluation', '', 'State: '+summary['state'], '', ASSUMPTION, '',
           'Coverage: v3 has no F2/F5 and no test F3. Natural dev has no F5; Phase 5 dev supplies F5.', '',
           '| Dataset | Family | Method/corpus | Hit@1 | Hit@5 | Hit@10 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |',
           '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for c in summary['cells']:
        def fmt(name):
            v=c[name]; label=c['state'] if v['value'] is None else '%.3f'%v['value']
            return '%s (n=%d)'%(label,v['n'] if v['value'] is not None else c['n'])
        lines.append('| %s | %s | %s/%s (n=%d) | %s |'%(
            c['dataset'],c['family'],c['retriever'],c['corpus'],c['n'],
            ' | '.join(fmt(name) for name in MEASURES[:7])))
    lines+=['','| Dataset | Family | Method/corpus | Bug Hit@5 | MH full evidence@10 | p50 ms | p95 ms | R4/R3 Jaccard@10 |',
            '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for c in summary['cells']:
        vals=[]
        for name in ('bug_hit_at_5','mh_full_evidence_at_10','r4_r3_jaccard_top10'):
            v=c[name]
            label='%.3f'%v['value'] if v['value'] is not None else (c['state'] if c['state']!='KNOWN_CITATION_PROXY' else 'N/A')
            vals.append('%s (n=%d)'%(label,v['n']))
        times=['%.1f (n=%d)'%(c[name],c['n']) if c[name] is not None else c['state']+' (n=0)'
               for name in ('latency_p50_ms','latency_p95_ms')]
        lines.append('| %s | %s | %s/%s (n=%d) | %s | %s | %s | %s | %s |'%(
            c['dataset'],c['family'],c['retriever'],c['corpus'],c['n'],vals[0],vals[1],times[0],times[1],vals[2]))
    lines+=['','All metrics, per-metric denominators, graph/hierarchy diagnostics and paired bootstrap/Holm comparisons are in summary.json.',
            'Test labels are evaluator-only. These are incomplete-citation retrieval scores, not final answer correctness.']
    return '\n'.join(lines)+'\n'

"""Compare approved variants with parents, resampling parent clusters."""
import json
import random
from collections import defaultdict
from pathlib import Path


def compare(out, split, seed=317, rounds=1000):
    out=Path(out)
    def lines(name):
        with (out/name).open(encoding='utf-8') as f: return [json.loads(x) for x in f if x.strip()]
    parents={(r['qid'],r['method']):r for r in lines('scores_'+split+'.jsonl')}
    variants={r['qid']:r for r in lines('natural_approved.jsonl') if r['split']==split}
    grouped=defaultdict(list)
    for row in lines('scores_'+split+'_natural.jsonl'):
        v=variants.get(row['qid'])
        if not v or v['family']=='F6' and v['gold']['value']=='request clarification': continue
        p=parents.get((v['parent_qid'],row['method']))
        if not p or p['verdict']=='NEEDS_HUMAN' or row['verdict']=='NEEDS_HUMAN': continue
        grouped[row['method'],v['cluster_id']].append((p['verdict']=='CORRECT',row['verdict']=='CORRECT'))
    methods={}
    for method in sorted({k[0] for k in grouped}):
        clusters=[v for (m,_),v in grouped.items() if m==method]
        values=[sum(int(b)-int(a) for a,b in group)/len(group) for group in clusters]
        rng=random.Random(seed);boot=sorted(sum(rng.choices(values,k=len(values)))/len(values) for _ in range(rounds)) if len(values)>1 else []
        methods[method]={'parent_clusters':len(clusters),'variant_pairs':sum(len(c) for c in clusters),
          'mean_accuracy_difference':sum(values)/len(values) if values else None,
          'cluster_bootstrap_95':[boot[int(.025*rounds)],boot[int(.975*rounds)-1]] if boot else None,
          'consistency':sum(a==b for c in clusters for a,b in c)/sum(len(c) for c in clusters)}
    return {'state':'COMPLETE' if methods else 'NO_PAIRED_SCORES','methods':methods,
            'ambiguity':'separate clarification task; not scored as paraphrase equivalence'}

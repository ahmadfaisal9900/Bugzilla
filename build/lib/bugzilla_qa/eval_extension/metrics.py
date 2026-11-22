"""Metrics over known citations; incomplete relevance is never called exhaustive truth."""
import math
import random
from collections import defaultdict


def score_ranked(hits, relevant, family):
    relevant = set(relevant)
    if family in ('F3', 'F6'):
        return {'state':'NOT_APPLICABLE', 'reason':'not a passage-enumeration task'}
    if not relevant:
        return {'state':'NOT_RETRIEVABLE', 'reason':'no indexed known evidence'}
    seen = set(); flags = []
    for hit in hits[:10]:
        rid = hit['record_id']
        flags.append(int(rid in relevant and rid not in seen))
        seen.add(rid)
    first = next((i for i,v in enumerate(flags,1) if v),None)
    dcg = sum(v / math.log2(i+1) for i,v in enumerate(flags,1))
    idcg = sum(1 / math.log2(i+1) for i in range(1, min(len(relevant),10)+1))
    return {'state':'KNOWN_CITATION_PROXY', 'hit_at_5':int(any(flags[:5])),
            'recall_at_5':sum(flags[:5])/len(relevant), 'recall_at_10':sum(flags)/len(relevant),
            'mrr_at_10':1/first if first else 0, 'precision_at_5':sum(flags[:5])/5,
            'ndcg_at_10':dcg/idcg if idcg else None,
            'all_known_evidence_at_10':sum(flags) == len(relevant)}


def summarize(rows):
    cells = defaultdict(list)
    for r in rows:
        cells[r['method'],r['family']].append(r)
    out = []
    for (method, family), values in sorted(cells.items()):
        eligible = [r for r in values if r['metrics']['state'] == 'KNOWN_CITATION_PROXY']
        row = {'method':method,'family':family,'questions':len(values),'retrievable':len(eligible),
               'not_applicable':sum(r['metrics']['state']=='NOT_APPLICABLE' for r in values),
               'unretrievable':sum(r['metrics']['state']=='NOT_RETRIEVABLE' for r in values)}
        for name in ('hit_at_5','recall_at_5','recall_at_10','mrr_at_10','precision_at_5','ndcg_at_10'):
            row[name] = sum(r['metrics'][name] for r in eligible)/len(eligible) if eligible else None
        latency = sorted(r['elapsed_seconds'] for r in values)
        for name, q in [('p50_seconds',.50),('p95_seconds',.95)]:
            row[name] = latency[min(len(latency)-1,int((len(latency)-1)*q))] if latency else None
        out.append(row)
    return out


def subset_summary(rows):
    result = []
    for label, subset in [('explicit_bug_id',[r for r in rows if r['explicit_bug_id']]),
                          ('no_explicit_bug_id',[r for r in rows if not r['explicit_bug_id']])]:
        for row in summarize(subset):
            result.append(dict(row, query_subset=label))
    return result


def paired_cluster_interval(rows, method_a, method_b, seed=317, rounds=1000):
    groups=defaultdict(dict)
    for row in rows:
        if row['method'] in (method_a,method_b) and row['metrics']['state']=='KNOWN_CITATION_PROXY':
            groups[row['qid']][row['method']]=row
    pairs=[]
    for values in groups.values():
        if method_a in values and method_b in values:
            a,b=values[method_a],values[method_b]
            pairs.append((a['cluster_id'],a['metrics']['hit_at_5']-b['metrics']['hit_at_5']))
    clusters=defaultdict(list)
    for cluster,delta in pairs: clusters[cluster].append(delta)
    if len(clusters)<2: return None
    vals=[sum(v)/len(v) for v in clusters.values()]; rng=random.Random(seed)
    samples=sorted(sum(rng.choices(vals,k=len(vals)))/len(vals) for _ in range(rounds))
    return {'cluster_count':len(vals),'paired_questions':len(pairs),'difference':sum(vals)/len(vals),
            'bootstrap_95':[samples[int(.025*rounds)],samples[int(.975*rounds)-1]],
            'measure':'mean per-cluster known-citation Hit@5 difference'}

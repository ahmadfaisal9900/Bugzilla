"""Aggregate-only diagnosis of the saved v1 run; never emits questions or answers."""
import collections
import csv
import json
from pathlib import Path

from bugzilla_qa.eval_extension.cli import ROOT, file_hash


def main():
    run=ROOT/'outputs/eval_extension/bank-a34d7d0a4b66911d'
    corpus=ROOT/'outputs/eval_extension/a143adf5fc34b524'
    manifest=json.loads((run/'bank_manifest.json').read_text())
    for name,sha in manifest['hashes'].items():
        if file_hash(run/name)!=sha: raise RuntimeError('v1 bank hash mismatch')
    selected=[json.loads(x) for x in (run/'selected.jsonl').open()]
    preds=[json.loads(x) for x in (run/'m3_dev_predictions.jsonl').open()]
    ranks=collections.defaultdict(dict)
    for line in (run/'retrieval_dev.jsonl').open():
        row=json.loads(line)
        ranks[row['qid']][row['method']]=[h['record_id'] for h in row['hits'][:5]]
    paired=[r for r in ranks.values() if 'hybrid' in r and 'hierarchical' in r]
    with (run/'natural_review.csv').open(newline='') as f: variants=list(csv.DictReader(f))
    dense=json.loads((run/'dense_manifest.json').read_text())
    audit=json.loads((corpus/'audit_summary.json').read_text())
    report={'state':'OBSERVED_V1_DIAGNOSIS', 'original_frozen':(ROOT/'outputs/benchmark/phase05/run-65c5be3381f66811/FROZEN').exists(),
            'v1_manifest_sha256':file_hash(run/'bank_manifest.json'), 'selected':len(selected),
            'family_split':{f'{f}:{s}':n for (f,s),n in collections.Counter((q['family'],q['split']) for q in selected).items()},
            'constant_product_questions':sum(q['family']=='F1' and 'recorded product?' in q['question'] for q in selected),
            'm3_status':dict(collections.Counter(p['status'] for p in preds)),
            'hierarchical_identical_top5':sum(p['hierarchical']==p['hybrid'] for p in paired), 'paired_queries':len(paired),
            'natural_variants':len(variants),'natural_pending':sum(v['decision']=='PENDING' for v in variants),
            'chunks':audit['chunks'],'truncated_chunks':dense['truncated_chunks'],
            'inference':'SKIPPED','snapshot_as_of_utc':None,
            'severity':{'constant_product':'HIGH','m3_parser':'HIGH','truncation':'HIGH',
                        'redundant_hierarchy':'MEDIUM','natural_wording':'MEDIUM'}}
    dest=ROOT/'outputs/eval_extension/diagnosis_v1.json'
    dest.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()

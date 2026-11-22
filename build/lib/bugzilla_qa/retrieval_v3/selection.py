"""Apply the preregistered development-only selection rule without test access."""
from pathlib import Path
from .common import ROOT, file_hash, read_config, write_json, git_commit, now
from .metrics import percentile


def select(config,paths,root=ROOT,output=None,dry_run=False):
    root=Path(root); output=root/(output or config['selection_output'])
    summaries=[read_config(root/p) for p in paths]
    if not summaries: raise RuntimeError('No summaries provided')
    first=summaries[0]; rows={}; sources=[]
    if file_hash(root/'docs/RETRIEVER_SELECTION.md')!=first['selection_protocol_sha256']:
        raise RuntimeError('Preregistered selection protocol changed since evaluation')
    for path,s in zip(paths,summaries):
        if s['split']!='dev' or s.get('locked_test_used'):
            raise RuntimeError('Locked-test results are forbidden for selection')
        if s['state']!='COMPLETE' or s.get('limited'): raise RuntimeError('Selection needs complete unlimited dev runs')
        for key in ('compatibility','selection_roster','selection_protocol_sha256'):
            if s[key]!=first[key]: raise RuntimeError('Summary inputs/rosters/protocol differ')
        # Validate against recorded artifacts rather than accepting an edited summary.
        path=root/path; manifest=read_config(path.parent/'manifest.json')
        if manifest['sha256'].get(path.name)!=file_hash(path): raise RuntimeError('Summary hash mismatch')
        sources.append({'path':str(path.relative_to(root)),'sha256':file_hash(path)})
        for r in s['selection_observations']:
            key=(r['dataset'],r['family'],r['qid'],r['retriever'],r['corpus'])
            if key in rows and rows[key]['recall_at_10']!=r['recall_at_10']:
                raise RuntimeError('Repeated method has conflicting retrieval results')
            # Input order breaks duplicate measurements; commands list the original offline run first.
            rows.setdefault(key,r)
    roster=first['selection_roster']
    if not roster: raise RuntimeError('No cells meet preregistered minimum n')
    if any(len(set(qids))!=len(qids) or len(qids)<10 for qids in roster.values()):
        raise RuntimeError('Selection roster violates preregistered minimum n')
    candidates={}; pairs=sorted({(r['retriever'],r['corpus']) for r in rows.values()})
    for method,corpus in pairs:
        cells=[]; times=[]; eligible=True
        for cell,qids in roster.items():
            ds,fam=cell.split(':'); chosen=[rows.get((ds,fam,q,method,corpus)) for q in qids]
            if not all(r and r['recall_at_10'] is not None for r in chosen): eligible=False; break
            cells.append(sum(r['recall_at_10'] for r in chosen)/len(chosen))
            times.extend(r['latency_ms'] for r in chosen)
        if eligible:
            candidates[method,corpus]={'retriever':method,'corpus':corpus,'macro_recall_at_10':sum(cells)/len(cells),
                  'p95_latency_ms':percentile(times,.95),'cells_n':len(cells),'questions_n':len(times)}
    excluded=[]
    for pair,c in list(candidates.items()):
        if pair[0] in ('R7a','R7b'):
            base=candidates.get(('R5',pair[1]))
            if base is None or c['macro_recall_at_10']-base['macro_recall_at_10']<=config['r7_min_gain']:
                excluded.append(dict(c,reason='R7 did not beat same-corpus R5 by more than 0.02'))
                del candidates[pair]
    if not candidates: raise RuntimeError('No complete eligible candidate')
    best=max(c['macro_recall_at_10'] for c in candidates.values())
    tied=[c for c in candidates.values() if best-c['macro_recall_at_10']<=config['selection_tie']+1e-12]
    winner=min(tied,key=lambda c:(c['p95_latency_ms'],c['retriever'],c['corpus']))
    result={'state':'DRY_RUN' if dry_run else 'SELECTED_DEV_ONLY','selected':winner,
            'eligible_cells':{k:len(v) for k,v in roster.items()},'candidates':list(candidates.values()),
            'excluded_r7':excluded,'sources':sources,'compatibility':first['compatibility'],
            'selection_protocol_sha256':first['selection_protocol_sha256'],'git_commit':git_commit(),
            'index_build':first['index_build'],
            'created_at_utc':now(),'test_used':False,'output':str(output)}
    if not dry_run:
        if output.exists(): raise RuntimeError('Selection output exists; use a new --output path')
        write_json(output,result) # JSON is also valid YAML; no new YAML dependency.
    return result

"""Verify official development questions against the shared source and prepared index."""
import itertools
import json
import math
from .systems import digest, file_hash, read, rows, write


def official(root, dry_run=False):
    import types
    from bugzilla_qa.answering.sources import questions as inference_questions
    from bugzilla_qa.answering.tools import Tools
    from bugzilla_qa.benchmark.phase05 import partition
    from bugzilla_qa.data.normalize import digest as source_digest
    from bugzilla_qa.eval_extension.bank import partition as expanded_partition
    from .systems import load_items
    prepared = root / 'outputs/evaluation/phase11/sample_bundle/all_partitions/answering.json'
    config = read(prepared)
    runtime = root / config['sample_bundle']
    ready = read(runtime / 'READY.json')
    for path, sha in ready['sha256'].items():
        if file_hash(root / path) != sha:
            raise ValueError('Prepared source runtime changed: ' + path)
    source_dir = root / 'data/firefox-sample-seed317-20261102'
    delivery = read(source_dir / 'manifest.json')
    for name, metadata in delivery['files'].items():
        if file_hash(source_dir / name) != metadata['sha256']:
            raise ValueError('Shared database package changed: ' + name)
    rc = read(root / 'configs/retrieval_v3.yaml')
    old_rc = read(root / config['retrieval_config'])
    rc.update({k:old_rc[k] for k in ('canonical_db','source_config','batch_size')})
    records = {r['record_id']:r for r in rows(root / 'outputs/evaluation/phase11/sample_bundle/corpus.jsonl')}
    from bugzilla_qa.eval_extension.cli import records as source_records
    from bugzilla_qa.eval_extension.retrieval import safe_text
    actual = {r['record_id']:r for r in source_records(read(root / config['source_config']), None)}
    actual = {k:dict(r,text=safe_text(r['text'])) for k,r in actual.items()}
    fields = ('record_id','bug_id','kind','text','source_hash','visibility','url','snapshot_as_of_utc')
    if records.keys()!=actual.keys() or any(any(records[k].get(f)!=actual[k].get(f) for f in fields) for k in actual):
        raise ValueError('Saved public corpus differs from the read-only databases')
    index = root / read(root/config['selection'])['index_build']
    chunks = rows(index/'C1/corpus.jsonl')
    if actual.keys()-{d['record_id'] for d in chunks}:
        raise ValueError('Public source records are missing from the reconstructed index')
    for d in chunks:
        record = actual[d['record_id']]
        if d['source_hash']!=record['source_hash'] or d['text']!=record['text'][d['source_char_start']:d['source_char_end']]:
            raise ValueError('Index text or provenance differs from sanitized public source')
    for field in ('embedding_model','embedding_revision','reranker_model','reranker_revision'):
        if rc[field]!=old_rc[field]:
            raise ValueError('Reconstructed retrieval model differs: '+field)
    reconstructed_checkpoint = history_checkpoint(root,root/old_rc['canonical_db'],source_dir/'api_enrichment.duckdb',None)
    history = reconstructed_checkpoint['candidate_results']
    tools = Tools(config, root, types.SimpleNamespace(docs=[]))
    tools._history = history
    failures, counts, pins = [], {}, {}
    try:
        from bugzilla_qa.data.phase04 import classify_first_fixed
        filing = {str(b):str(t) for b,t in tools.db.execute('SELECT bug_id,opened_at_utc FROM bugs').fetchall()}
        reconstructed = dict(parseable_histories=sum(v['history']['state']=='PARSED' for v in history.values()),
                             field_change_rows=sum(len(v['history']['changes']) for v in history.values()),
                             reopened_events=sum(v['history']['reopened_count'] for v in history.values()),
                             same_time_history_event_groups=sum(v['history']['same_time_groups'] for v in history.values()),
                             source_consistency_differences=sum(len(v['source_consistency_differences']) for v in history.values()),
                             valid_f2_cases=sum(classify_first_fixed(v['history'],filing[b])['state']=='VALID_EVENT_TIME' for b,v in history.items()))
        original_history = read(source_dir/'history_summary.json')
        if any(original_history[k]!=v for k,v in reconstructed.items()):
            raise ValueError('Reconstructed history disagrees with the original history summary')
        ids = sorted(str(r[0]) for r in tools.db.execute("SELECT bug_id FROM bugs WHERE NOT EXISTS (SELECT 1 FROM source_records v WHERE v.bug_id=bugs.bug_id AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT')").fetchall())
        population = source_digest({sp:[b for b in ids if partition(317,b)==sp] for sp in ('dev','test')})
        for dataset in ('phase05','natural','v3'):
            items, dataset_pins = load_items(root, rc, dataset)
            pins.update(dataset_pins)
            counts[dataset] = len(items)
            qconfig = dict(config,retrieval_config='configs/retrieval_v3.yaml')
            inference, _ = inference_questions(qconfig,root,dataset,'dev')
            scopes = {q['qid']:q for q in inference}
            if dataset == 'v3':
                raw = rows(root / rc['v3_dir'] / 'dev.questions.jsonl')
                for q in raw:
                    for record, sha in q.get('provenance',{}).get('evidence_source_hashes',{}).items():
                        if actual.get(record,{}).get('source_hash') != sha:
                            failures.append([dataset,q['qid'],'source_hash'])
            for item in items:
                for evidence in item['evidence']:
                    record = evidence if isinstance(evidence,str) else evidence.get('id')
                    sha = None if isinstance(evidence,str) else evidence.get('content_hash')
                    if record.startswith('history:'):
                        valid = history.get(record.split(':')[1],{}).get('history_fetch',{}).get('raw_sha256') == sha
                    elif record.startswith('population:'):
                        expected = population if dataset=='phase05' else source_digest([b for b in ids if expanded_partition(317,b)=='dev'])
                        valid = record.split(':')[1] == expected
                    else:
                        valid = record in actual and (not sha or actual[record]['source_hash']==sha)
                    if not valid:
                        failures.append([dataset,item['qid'],'evidence'])
                if item['family']=='F3':
                    question = scopes[item['qid']]
                    filters = question['scope'].get('filter',{})
                    args = dict(scope='cohort')
                    for field, value in filters.items():
                        if field in ('year','creation_year'):
                            args.update(created_from=str(value)+'-01-01T00:00:00Z',created_to=str(int(value)+1)+'-01-01T00:00:00Z')
                        elif field in ('component','status','resolution'):
                            args[field]=value
                        else:
                            raise ValueError('Unsupported aggregate audit filter: '+field)
                    if not filters or tools.count(args,question)['count'] != item['expected']:
                        failures.append([dataset,item['qid'],'aggregate'])
                elif item['family']=='F2':
                    value = tools.lifecycle(item['acceptable_bug_ids'][0])
                    got = value.get('first_fixed_hours') if item['kind']=='calendar_duration' else value.get('reopened_count')
                    valid = value.get('known') and (not value.get('first_fixed_known') if item['kind']=='unknown' else got is not None and abs(got-item['expected'])<1/3600)
                    if not valid:
                        failures.append([dataset,item['qid'],'lifecycle'])
    finally:
        tools.close()
    audit = dict(state='BLOCKED' if failures else 'VERIFIED_SHARED_DEV_RUNTIME',questions=counts,failures=failures,
                 history=reconstructed,index_chunks=len(chunks),public_records=len(actual),
                 source_sha256={str((source_dir/name).relative_to(root)):m['sha256'] for name,m in delivery['files'].items()},
                 benchmark_sha256=pins,index_manifest_sha256=file_hash(root/read(root/config['selection'])['index_build']/'manifest.json'),
                 note='Official development questions; verified shared source export and reconstructed index/history, not the original owner runtime. No test questions or test gold opened.')
    destination = root / 'outputs/evaluation/phase11/official_runtime'
    if not dry_run:
        write(destination/'audit.json',audit)
    if failures:
        raise ValueError('Shared-source compatibility failed; see official_runtime/audit.json: '+str(failures[:3]))
    if dry_run:
        return audit
    selection = read(root/config['selection'])
    selection.update(state='RECONSTRUCTED_DEV_RUNTIME',source_selection_sha256=file_hash(root/'configs/selected_retriever.yaml'))
    write(destination/'selection.json',selection)
    write(destination/'retrieval.json',rc)
    write(destination/'history_checkpoint.json',reconstructed_checkpoint)
    calibration = destination/'calibration.json'
    question_hash = digest(pins)
    calibrated = read(calibration) if calibration.exists() else dict(questions_sha256=question_hash,index_sha256=audit['index_manifest_sha256'])
    if calibration.exists():
        if calibrated['questions_sha256']!=question_hash or calibrated['index_sha256']!=audit['index_manifest_sha256']:
            raise ValueError('Official calibration inputs changed; use a new runtime version')
    if calibrated.get('state')!='COMPLETE':
        import torch
        from bugzilla_qa.retrieval_v3.runner import load_engine,load_models
        torch.set_num_threads(2)
        print('Loading pinned local retrieval models for development calibration',flush=True)
        engine = load_engine(index/'C1',rc,load_models(rc),None)
        scores = calibrated.get('scores',{})
        print('Resuming official calibration at',len(scores),'/350',flush=True)
        for dataset in counts:
            dataset_items,_ = load_items(root,rc,dataset)
            for item in dataset_items:
                key=dataset+':'+item['qid']
                if key in scores:
                    continue
                hits = engine.run('R5',item['question'],10)
                if hits and math.isfinite(hits[0]['score']):
                    scores[key]=hits[0]['score']
                if len(scores)%5==0:
                    write(calibration,dict(calibrated,state='PARTIAL',scores=scores,n=len(scores)))
                    print('Official development calibration:',len(scores),'/350',flush=True)
        if len(scores)!=sum(counts.values()):
            raise ValueError('Not every development question has a finite calibration score')
        values=sorted(scores.values())
        calibrated = dict(state='COMPLETE',split='dev',quantile=.1,n=len(values),tau=values[int(.1*(len(values)-1))],scores=scores,
                          questions_sha256=question_hash,index_sha256=audit['index_manifest_sha256'])
        write(calibration,calibrated)
    config.pop('sample_bundle')
    config.update(runtime_manifest=str((destination/'audit.json').relative_to(root)),
                  history_checkpoint=str((destination/'history_checkpoint.json').relative_to(root)),
                  selection=str((destination/'selection.json').relative_to(root)),
                  retrieval_config=str((destination/'retrieval.json').relative_to(root)),
                  corrective_tau=calibrated['tau'],corrective_calibration=str(calibration.relative_to(root)))
    write(destination/'answering.json',config)
    return destination/'answering.json'


def history_checkpoint(root, base, overlay, destination):
    import duckdb
    from bugzilla_qa.data.phase04 import parse_api_history, consistency_differences, iso_utc
    folder = overlay.parent
    fetches = [r for r in read(folder / 'history_response_manifest.json') if r['endpoint'] == 'history' and r['status_code'] == 200]
    db = duckdb.connect(str(base), read_only=True)
    db.execute("SET TimeZone='UTC'")
    history = duckdb.connect(str(overlay), read_only=True)
    result = {}
    try:
        snapshots = {str(r[0]): dict(zip(['snapshot_status', 'snapshot_resolution', 'product', 'component', 'opened_at_utc'], r[1:]))
                     for r in db.execute('SELECT bug_id,snapshot_status,snapshot_resolution,product,component,opened_at_utc FROM bugs').fetchall()}
        current = {str(r['bug_id']): r for r in (json.loads(x[0]) for x in history.execute('SELECT row_json FROM api_bug_refresh').fetchall())}
        for row in current.values():
            if row.get('creation_time'):
                row['creation_time']=iso_utc(row['creation_time'])
        for fetched in fetches:
            bug = str(fetched['bug_id'])
            if bug not in snapshots:
                continue
            entries = history.execute('SELECT event_index,event_time_utc,field_name,old_value,new_value FROM field_changes WHERE bug_id=? ORDER BY event_index,change_index', [int(bug)]).fetchall()
            events = []
            for _, group in itertools.groupby(entries, key=lambda r: r[0]):
                changes = list(group)
                def decoded(value):
                    try:
                        return json.loads(value)
                    except (ValueError, TypeError):
                        return value
                events.append(dict(when=changes[0][1], changes=[dict(field_name=r[2], removed=decoded(r[3]), added=decoded(r[4])) for r in changes]))
            parsed = parse_api_history({'bugs': [{'id': int(bug), 'history': events}]}, bug,
                                       str(snapshots[bug]['opened_at_utc']), fetched['fetched_at_utc'])
            result[bug] = dict(history=parsed, history_fetch=fetched,
                               source_consistency_differences=consistency_differences(snapshots[bug], current.get(bug, {})),
                               reconstruction='Verified normalized overlay grouped by original event/change indexes; no new API collection')
    finally:
        db.close()
        history.close()
    checkpoint = dict(candidate_results=result, reconstruction=True)
    if destination is not None:
        write(destination,checkpoint)
    return checkpoint

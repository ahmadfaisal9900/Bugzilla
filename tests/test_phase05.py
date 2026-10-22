"""Tiny synthetic end-to-end benchmark/review/freeze tests; no network or corpus jobs."""
import copy
import csv
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bugzilla_qa.benchmark import phase05 as b
from bugzilla_qa.data import normalize as n, phase04 as p4

OBS = '2026-10-22T01:00:00+00:00'
ING = '2026-10-22T02:00:00+00:00'
FETCH = '2026-10-22T03:00:00+00:00'
API_ING = '2026-10-22T04:00:00+00:00'


def insert(db, table, row):
    cols = list(n.SCHEMAS[table])
    values = [json.dumps(row.get(k), sort_keys=True) if n.SCHEMAS[table][k] == 'JSON' else row.get(k) for k in cols]
    db.execute('INSERT OR IGNORE INTO ' + table + ' VALUES (' + ','.join('?' for _ in cols) + ')', values)


def fixture(root):
    base = root / 'outputs/base'; overlay = root / 'outputs/phase04/enrichment/pilot'
    base.mkdir(parents=True); overlay.mkdir(parents=True)
    db = duckdb.connect(str(base / 'canonical.duckdb')); n.init_db(db)
    db.execute('CREATE TABLE sample_membership(bug_id VARCHAR PRIMARY KEY, seed BIGINT, stratum VARCHAR)')
    spec = {'name': 'metadata', 'sha256': 'a' * 64, 'observed_at_utc': OBS,
            'mapping': {'bug_id': 'id', 'created_at': 'creation_time', 'status': 'status',
                        'resolution': 'resolution', 'product': 'product', 'component': 'component', 'last_change_at': 'last_change_time'}}
    results, metadata, events = {}, [], []
    for i in range(1, 21):
        bug = str(i)
        siblings = [str(j) for j in range(1, 21) if j != i and b.partition(317, str(j)) == b.partition(317, bug)]
        row = {'id': bug, 'creation_time': '2024-01-01T00:00:00+00:00', 'last_change_time': '2024-02-01T00:00:00+00:00',
               'status': 'RESOLVED' if i % 2 else 'NEW', 'resolution': 'FIXED' if i % 2 else '',
               'product': 'Firefox', 'component': 'component-' + str(i), 'summary': 'Synthetic fixture',
               'blocks': json.dumps([siblings[0]]) if siblings else '[]'}
        normalized = n.normalize_row(spec, row, i, ING)
        for table, rows in normalized.items():
            for r in rows:
                if table == 'source_records': r['disposition'] = 'NORMALIZED'
                insert(db, table, r)
        if i == 20:
            conflict = copy.deepcopy(normalized['source_records'][0]); conflict['record_key'] = 'conflict'; conflict['source_record_id'] = 'conflict'; conflict['disposition'] = 'CONFLICT_VARIANT'
            insert(db, 'source_records', conflict)
        db.execute('INSERT INTO sample_membership VALUES (?,317,?)', [bug, 'fixture'])
        if i % 2:
            cs = {'name': 'comments_part_1', 'tier': 'BASE', 'sha256': 'c' * 64, 'observed_at_utc': OBS,
                  'mapping': {'bug_id': 'bug_id', 'created_at': 'creation_time', 'comment_id': 'id',
                              'comment_text': 'text', 'private_flag': 'is_private'}}
            cr = {'bug_id': bug, 'id': str(100 + i), 'creation_time': '2024-01-04T00:00:00+00:00',
                  'is_private': 'true' if i == 3 else 'false', 'text': 'The delay occurred because contact fixture@example.test was unavailable.' if i == 1 else 'The delay occurred because a deterministic test was failing.'}
            for table, rows in n.normalize_row(cs, cr, i, ING).items():
                for r in rows:
                    if table == 'source_records': r['disposition'] = 'NORMALIZED'
                    insert(db, table, r)
        changes = [{'field_name': 'resolution', 'removed': '', 'added': 'FIXED'}] if i % 3 else [{'field_name': 'status', 'removed': 'RESOLVED', 'added': 'REOPENED'}]
        if i == 6: changes.append({'field_name': 'status', 'removed': 'REOPENED', 'added': 'REOPENED'})  # no-op is not another reopening
        payload = {'bugs': [{'id': i, 'history': [{'when': '2024-01-03T00:00:00Z', 'who': 'fixture', 'changes': changes}]}]}
        body = json.dumps(payload); raw_hash = hashlib.sha256(body.encode()).hexdigest()
        cache = root / 'outputs/phase04/api_cache' / bug / 'history.json.gz'; cache.parent.mkdir(parents=True)
        url = p4.BASE_URL + '/bug/' + bug + '/history'
        env = {'url': url, 'requested_bug_id': i, 'endpoint': 'history', 'fetched_at_utc': FETCH,
               'status_code': 200, 'source_visibility': 'public_response', 'body_sha256': raw_hash, 'body_utf8': body}
        with gzip.open(cache, 'wt') as f: json.dump(env, f)
        meta = {**{k: env[k] for k in ('url', 'fetched_at_utc', 'status_code')}, 'bug_id': i, 'endpoint': 'history', 'cache_path': str(cache), 'raw_sha256': raw_hash}
        metadata.append(meta)
        hist = p4.parse_api_history(payload, i, row['creation_time'], FETCH)
        metric = p4.classify_first_fixed(hist, row['creation_time'])
        results[bug] = {'bug_id': i, 'changes': hist['changes'], 'history': {k:v for k,v in hist.items() if k != 'changes'},
                        'fix_metric': metric, 'history_fetch': meta, 'source_consistency_differences': []}
        for x in hist['changes']:
            e = {'bug_id': i, 'source_dataset': 'bugzilla_rest_history', 'source_row_key': n.digest(x), 'source_url': url,
                 'event_time_utc': x['event_time_utc'], 'observed_at_utc': FETCH, 'ingested_at_utc': API_ING,
                 'text_available': False, 'raw_field_mapping': {'when': 'event_time_utc'}, 'content_sha256': p4.digest(x),
                 'history_state': 'PARSED', **{k:x[k] for k in ('field_name','old_value','new_value','actor_pseudonym','event_index','change_index')}}
            events.append(e)
    db.close()
    n.write_json(base / 'manifest.json', {'state':'COMPLETE','identity_hash':'fixture', 'identity':{'options':{'limit':None}},
       'artifacts':{'canonical.duckdb':{'bytes':(base/'canonical.duckdb').stat().st_size,'sha256':n.file_hash(base/'canonical.duckdb')}}})
    n.write_json(base / 'sample_manifest.json', {'identity_hash':'fixture','seed':317}); n.write_json(base / 'qc_report.json', {'fixture':True})
    cp={'state':'COMPLETE','candidate_manifest_sha256':'fixture-pilot', 'updated_at_utc':API_ING,'candidate_results':results}
    n.write_json(overlay/'checkpoint.json',cp)
    p4._write_overlay_duckdb(overlay/'api_enrichment.duckdb',events,[],[],[])
    for name in ('api_bug_refresh.json','api_comments.json','api_link_changes.json','field_changes_rejected.json'):
        n.write_json(overlay/name,[])
    b.jsonl(overlay/'field_changes.jsonl',events)
    summary={'state':'COMPLETE','baseline_run_id':'base','candidate_manifest_sha256':'fixture-pilot',
             'candidate_count':20,'candidate_count_requested':20,'api_response_manifest':metadata,
             'successful_histories':20,'parseable_histories':20,'valid_f2_cases':sum(r['fix_metric']['state']=='VALID_EVENT_TIME' for r in results.values()),
             'field_change_rows':len(events),
             'artifacts':{p.name:{'path':p.name,'size_bytes':p.stat().st_size,'sha256':n.file_hash(p)} for p in overlay.iterdir() if p.name!='checkpoint.json'}}
    n.write_json(overlay/'summary.json',summary)
    return {'base_run':str(base.relative_to(root)),'phase04_run':str(overlay.relative_to(root)), 'base_identity':'fixture',
            'sample_seed':317,'candidate_identity':'fixture-pilot','phase04_summary_sha256':n.file_hash(overlay/'summary.json'),
            'base_counts':{'bugs':20,'comments':10,'sample_membership':20,'field_changes':0}}


def args(root, **kw):
    return SimpleNamespace(output=root/'outputs/benchmark/phase05',run=None,seed=317,per_family=5,
                           f5_target=5,limit=kw.get('limit'),dry_run=False,resume=kw.get('resume',False))


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.pins=fixture(self.root)
    def tearDown(self): self.temp.cleanup()

    def test_sources_templates_independent_gold_and_partition(self):
        v=b.verify_inputs(self.root,self.pins); self.assertEqual(v['histories'],20)
        qs,chs=b.complete_candidates(self.root,self.pins,per_family=5,f5_target=5)
        self.assertEqual(set(q['family'] for q in qs),set(b.FAMILIES))
        self.assertTrue(all('20' not in q['bug_ids'] for q in qs))  # conflicted metadata parent
        self.assertFalse({i for q in qs if q['split']=='dev' for i in q['bug_ids']} & {i for q in qs if q['split']=='test' for i in q['bug_ids']})
        self.assertTrue(all(q['gold']['hours']==48 for q in qs if q['gold']['type']=='calendar_duration'))
        self.assertTrue(all(q['gold']['value'] for q in qs if q['family']=='F4'))
        self.assertTrue(all(q['gold']['value']==1 for q in qs if q['family']=='F2' and q['gold']['type']=='integer'))
        self.assertTrue(all(q['source_coverage']['parent_snapshot_resolution']=='FIXED' for q in qs if q['family']=='F5'))
        self.assertTrue(all(q['source_coverage']['subpopulation']=='FIXED_SELECTED_CSV_ONLY' for q in qs if q['family']=='F5'))
        self.assertTrue(all(q['evidence'][0]['fields']['private_flag'] is False and '@' not in json.dumps(q['gold']) for q in qs if q['family']=='F5'))
        self.assertTrue(all('3' not in q['bug_ids'] for q in qs if q['family']=='F5'))
        self.assertEqual(qs,b.complete_candidates(self.root,self.pins,per_family=5,f5_target=5)[0])
        self.assertTrue(all(c['question'] != next(q['question'] for q in qs if q['qid']==c['variant_of']) for c in chs))

    def test_future_context_and_target_tampering_rejected(self):
        q=b.complete_candidates(self.root,self.pins,per_family=5,f5_target=5)[0][0]
        bad=copy.deepcopy(q);bad['as_of']='2020-01-01T00:00:00Z'
        with self.assertRaises(AssertionError): b.check_item(bad)
        bad=copy.deepcopy(q);bad['evidence'][0]['event_time_utc']='2099-01-01T00:00:00Z'
        with self.assertRaises(AssertionError): b.check_item(bad)
        p=self.root/self.pins['phase04_run']/'api_link_changes.json';p.write_text('[1]')
        with self.assertRaises(AssertionError): b.verify_inputs(self.root,self.pins)

    def test_review_freeze_resume_and_no_inference_gold(self):
        a=args(self.root);b.generate(a,self.root,self.pins)
        with self.assertRaises(AssertionError): b.generate(a,self.root,self.pins)
        a.resume=True;b.generate(a,self.root,self.pins);b.prepare_review(a)
        run,_,qs,ch=b.load_run(a)
        with self.assertRaises(AssertionError): b.validate_freeze(a,self.root,self.pins)
        path=run/'review_queue.csv'
        saved_queue=path.read_bytes();a.limit=1
        with self.assertRaises(AssertionError): b.prepare_review(a)
        self.assertEqual(saved_queue,path.read_bytes());a.limit=None
        with path.open() as handle: rows=list(csv.DictReader(handle))
        for r in rows:
            r.update(decision='APPROVE',reviewer='fixture-rater',reviewed_at_utc=API_ING,source_checked='YES',rationale_present='YES')
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        b.prepare_review(a)  # review edits must survive resume
        self.assertTrue(all(r['decision']=='APPROVE' for r in b.queue_read(path).values()))
        n.write_json(run/'review_signoff.json',{'approve_freeze':True,'acknowledge_actual_reduced_coverage':True,'reviewer':'fixture-rater','reviewed_at_utc':API_ING})
        frozen=b.validate_freeze(a,self.root,self.pins);dest=run/('frozen-'+frozen['id'])
        for split in ('dev','test','challenge'):
            for line in (dest/(split+'.questions.jsonl')).read_text().splitlines():
                self.assertEqual(set(json.loads(line)),{'qid','question','scope'})
        self.assertEqual(frozen,b.validate_freeze(a,self.root,self.pins))
        original=path.read_bytes();path.write_bytes(original+b'\n')
        with self.assertRaises(AssertionError): b.validate_freeze(a,self.root,self.pins)
        path.write_bytes(original)
        (dest/'test.questions.jsonl').write_text('tampered')
        with self.assertRaises(AssertionError): b.validate_freeze(a,self.root,self.pins)

    def test_duplicate_candidate_and_answer_hint_are_rejected(self):
        a=args(self.root);b.generate(a,self.root,self.pins)
        run,_,qs,_=b.load_run(a)
        bad=copy.deepcopy(qs[0]);bad['question'] += ' The answer is 48.'
        with self.assertRaises(AssertionError): b.check_item(bad)
        b.write_json(run/'candidates.json',qs + [qs[0]])
        with self.assertRaises(AssertionError): b.load_run(a)

    def test_limited_prefix_cannot_freeze_and_f5_needs_real_review(self):
        a=args(self.root,limit=2);b.generate(a,self.root,self.pins);a.resume=True;b.prepare_review(a)
        with self.assertRaises(AssertionError): b.validate_freeze(a,self.root,self.pins)
        qs,_=b.complete_candidates(self.root,self.pins,per_family=5,f5_target=5)
        f5=next(q for q in qs if q['family']=='F5')
        with self.assertRaises(AssertionError): b.approved_gold(f5,{'decision':'APPROVE','reviewer':'r','source_checked':'YES','reviewed_at_utc':API_ING,'rationale_present':'NO'})


if __name__ == '__main__': unittest.main()

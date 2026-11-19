"""Check S scoring, provenance, human review and shared generation budgets offline."""
import csv
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from bugzilla_qa.evaluation import experiment, systems as s, review


def item(kind='string', expected='FIXED', family='F1', qid='q1'):
    return dict(qid=qid, question='Recorded value?', kind=kind, expected=expected, family=family,
                dataset='v3', split='dev', freeze_id='frozen', cluster_id=qid, evidence=[], scope={},
                acceptable_bug_ids=['101', '102'], tolerance_hours=1.0)


def prediction(value='FIXED', q=None, system='S1', status='ok'):
    q = q or item()
    return dict(qid=q['qid'], system_id=system, dataset=q['dataset'], family=q['family'], split='dev',
                freeze_id=q['freeze_id'], config_hash='config', model='mock', provider='fixture',
                prompt_version='test', status=status, context_chunk_ids=['c1'],
                answer=dict(abstain=value is None, answer=value, answer_type=q['kind'],
                            bug_ids=[int(value)] if q['kind'] == 'bug_id' and str(value).isdigit() else [101],
                            citations=['c1'], rationale='Fixture answer.'),
                tokens={'input': 10, 'output': 2, 'usage_missing': False}, call_count=1, latency_ms=20)


def save_run(path, values):
    path.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for system, entries in values.items():
        target = path / (system + '.jsonl')
        target.write_text(''.join(json.dumps(r) + '\n' for r in entries), encoding='utf-8')
        hashes[target.name] = s.file_hash(target)
    s.write(path / 'manifest.json', dict(config_hash='config', sha256=hashes))


class ScoringTests(unittest.TestCase):
    def review_entry(self, required=True):
        row={k:'' for k in review.FIELDS}
        row.update(review_id='review1',dataset='phase05',question_type='Explanations',
                   review_needed='Answer and evidence' if required else 'Evidence only',current_result='Needs your grading',
                   question='Why?',model_answer='A public reason',reference_answer='A public reason',
                   model_evidence='Public source',needs_answer=required,needs_evidence=True,
                   family='F5',method='S1',question_id='q1',scope='dev')
        return row

    def test_review_import_rejects_changed_answers_duplicates_and_invalid_decisions(self):
        entry=self.review_entry();row=review.csv_row(entry)
        row.update(answer_verdict='CORRECT',grounding_verdict='SUPPORTED',reviewer='AB',note='Checked the comment.')
        self.assertEqual(review.validate_reviews([row],[entry])['review1']['answer_verdict'],'CORRECT')
        for changed in [dict(row,model_answer='Changed'),dict(row,reviewer=''),dict(row,grounding_verdict='NOT_APPLICABLE')]:
            with self.assertRaises(ValueError):review.validate_reviews([changed],[entry])
        with self.assertRaises(ValueError):review.validate_reviews([row,row],[entry])
        with self.assertRaises(ValueError):review.validate_reviews([row],[dict(entry,needs_answer=False)])
        self.assertEqual(review.validate_reviews([dict(row,current_result='Old displayed status')],[entry])['review1']['answer_verdict'],'CORRECT')

    def test_review_page_escapes_source_text_and_preserves_csv_edits(self):
        entry=self.review_entry();entry['model_answer']='</script><script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(review,'collect',return_value=([entry],[],{})):
                result=review.build(root,root)
                page=(root/'START_HERE.html').read_text(encoding='utf-8')
                self.assertEqual(page.count('</script>'),2)
                self.assertIn('\\u003c/script\\u003e',page)
                self.assertEqual(result['answer_decisions'],1)
                with (root/'REVIEW.csv').open(encoding='utf-8-sig',newline='') as handle:rows=list(csv.DictReader(handle))
                rows[0].update(answer_verdict='INCORRECT',grounding_verdict='UNSUPPORTED',reviewer='AB',note='Checked the source.')
                s.write_csv(root/'REVIEW.csv',rows,review.FIELDS)
                review.build(root,root)
                with (root/'REVIEW.csv').open(encoding='utf-8-sig',newline='') as handle:saved=list(csv.DictReader(handle))
                self.assertEqual(saved[0]['answer_verdict'],'INCORRECT')
                self.assertEqual(len(list(root.glob('REVIEW.saved-*.csv'))),1)

    def test_review_plain_fields_and_spreadsheet_formula_protection(self):
        self.assertEqual(review.plain({'claims':[{'text':'Public reason','evidence_id':'hash'}]}),'Public reason')
        self.assertEqual(review.sheet_value('=1+1'),"'=1+1")
        self.assertEqual(review.sheet_value('Ordinary answer'),'Ordinary answer')

    def test_review_import_updates_scores_and_preserves_previous_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);report=root/'report';report.mkdir()
            entry=self.review_entry();q=item('supported_explanation',{'claims':[{'text':'Public reason'}]},'F5')
            p=prediction('Public reason',q);selected={'S1':{'q1':p}};attempts={'S1':[p]}
            first=s.evaluate([q],selected,attempts,report,['S1'],{})
            with (report/'review_queue.csv').open(newline='',encoding='utf-8') as handle:queue={r['review_id']:r for r in csv.DictReader(handle)}
            entry['review_id']=next(iter(queue))
            row=review.csv_row(entry);row.update(answer_verdict='CORRECT',grounding_verdict='SUPPORTED',reviewer='AB',note='Checked the comment.')
            s.write_csv(root/'completed.csv',[row],review.FIELDS)
            s.write(root/'latest.json',{'evaluations':{'phase05':{'output':str(report),'state':'NEEDS_REVIEW'}}})
            collection=dict(folder=report,items=[q],selected=selected,attempts=attempts,summary=first,pins={},config={},documents={},queue=queue)
            with patch.object(review,'collect',return_value=([entry],[],{'phase05':collection})),patch.object(review,'build',return_value={}):
                review.apply(root,root,root/'completed.csv')
            self.assertEqual(s.read(report/'summary.json')['comparison'][0]['correct'],1)
            self.assertEqual(s.read(root/'latest.json')['state'],'REVIEWED')
            self.assertEqual(len(list(report.glob('review_queue.before-*.csv'))),1)

    def test_fixed_pilot_keeps_original_questions_and_covers_nine_families(self):
        original = [item(qid='original'+str(i), family='F'+str(i%6+1)) for i in range(34)]
        natural = [item(qid='natural'+str(i), family='F'+str(i%6+1)) for i in range(51)]
        expanded = [item(qid=family+str(i), family=family) for family in ('KI','MH','F6H') for i in range(20)]
        datasets = {'phase05':(original,{}), 'natural':(natural,{}), 'v3':(expanded,{})}
        selected = experiment.pilot_selection(datasets)
        self.assertEqual([len(selected[d]) for d in datasets], [34,10,36])
        self.assertEqual(set(selected['phase05']), {q['qid'] for q in original})
        self.assertEqual(selected, experiment.pilot_selection({d:(list(reversed(q)),p) for d,(q,p) in datasets.items()}))
        self.assertEqual({f:sum(q.startswith(f) for q in selected['v3']) for f in ('KI','MH','F6H')}, {'KI':17,'MH':8,'F6H':11})

    def test_pool_rotates_accounts_preserves_cache_and_enforces_total_budget(self):
        import os
        from bugzilla_qa.llm.provider import ProviderRateLimitError, InvalidJSONResponse
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'.env').write_text('GROQ_API_KEY=key1\nGROQ_API_KEY_2=key2\nGROQ_API_KEY_3=key3\nGROQ_API_KEY_4=key4\n')
            configs, used = [], []
            class Provider:
                calls = 0
                def generate_json(self, *args, **kwargs):
                    self.calls += 1
                    used.append(os.environ['GROQ_API_KEY'])
                    return {'state':'SUCCESS'}
            def factory(config, role, **kwargs):
                configs.append(config)
                return Provider()
            config = {'ledger':'llm/ledger.jsonl','cache':'llm/cache.sqlite','env_file':'.env'}
            (root/'llm').mkdir()
            (root/'llm/ledger.jsonl').write_text('{"status":"REQUEST_STARTED"}\n')
            names = ['GROQ_API_KEY']+['GROQ_API_KEY_'+str(i) for i in (2,3,4)]
            with patch.dict(os.environ,{},clear=True):
                pool = experiment.CredentialPool(factory,config,'generator',names,root=root,max_requests=5)
                for _ in range(5):pool.generate_json('question',{})
                self.assertEqual(used,['key1','key2','key3','key4','key1'])
                self.assertNotIn('GROQ_API_KEY',os.environ)
                with self.assertRaisesRegex(RuntimeError,'budget exhausted'):pool.generate_json('q',{})
                self.assertEqual(pool.calls,5)
                self.assertEqual(len({c['ledger'] for c in configs}),4)
                self.assertTrue(all(c['cache']==config['cache'] for c in configs))
                self.assertEqual((root/configs[1]['ledger']).read_text(),(root/config['ledger']).read_text())
                self.assertFalse((root/configs[0]['ledger']).exists())

    def test_pool_fails_over_quota_but_never_retries_invalid_model_answers(self):
        import os
        from bugzilla_qa.llm.provider import ProviderRateLimitError, InvalidJSONResponse
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'.env').write_text('GROQ_API_KEY_3=key3\nGROQ_API_KEY_4=key4\n')
            class Provider:
                calls=0
                def generate_json(self,*args,**kwargs):
                    self.calls+=1
                    if os.environ['GROQ_API_KEY']=='key3':
                        raise ProviderRateLimitError({'model':'mock','quota':'TPD'})
                    return {'state':'SUCCESS'}
            names=['GROQ_API_KEY_3','GROQ_API_KEY_4']
            config={'ledger':'llm/ledger.jsonl','cache':'llm/cache.sqlite','env_file':'.env'}
            with patch.dict(os.environ,{},clear=True):
                pool=experiment.CredentialPool(lambda *a,**k:Provider(),config,'generator',names,root=root,max_requests=5)
                self.assertEqual(pool.generate_json('q',{})['state'],'SUCCESS')
                self.assertEqual(pool.calls,2)
                self.assertEqual(pool.disabled,{0})
                def invalid(*args,**kwargs):raise InvalidJSONResponse('bad output')
                pool.providers[1].generate_json=invalid
                with self.assertRaises(InvalidJSONResponse):pool.generate_json('q',{})

    def test_second_credential_is_inherited_without_changing_or_printing_env_file(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            content='GROQ_API_KEY=fixture_primary\nGROQ_API_KEY_2=fixture_secondary\n'
            (root/'.env').write_text(content)
            output=io.StringIO()
            def verified(*args):
                self.assertNotIn('GROQ_API_KEY',os.environ)
                self.assertEqual(experiment.configured_keys(root,['GROQ_API_KEY_2']),['GROQ_API_KEY_2'])
                return dict(state='VERIFIED')
            with patch.object(experiment,'ROOT',root),patch.dict(os.environ,{},clear=True),\
                 patch('bugzilla_qa.evaluation.shared_source.official',side_effect=verified),patch('sys.stdout',output):
                self.assertEqual(experiment.main(['--shared-source','--dry-run','--api-key-env','GROQ_API_KEY_2']),0)
            self.assertEqual((root/'.env').read_text(),content)
            self.assertNotIn('fixture_secondary',output.getvalue())
            self.assertNotIn('fixture_primary',output.getvalue())

    def test_keys_are_discovered_from_env_without_duplicate_credentials(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'.env').write_text('GROQ_API_KEY=first\nGROQ_API_KEY_2=second\nGROQ_API_KEY_3=third\nGROQ_API_KEY_4=first\n')
            with patch.dict(os.environ,{},clear=True):
                self.assertEqual(experiment.configured_keys(root),experiment.KEY_NAMES[:3])
                self.assertEqual(experiment.configured_keys(root,['GROQ_API_KEY_2']),['GROQ_API_KEY_2'])
                with self.assertRaisesRegex(ValueError,'distinct'):
                    experiment.configured_keys(root,['GROQ_API_KEY','GROQ_API_KEY_4'])
                (root/'.env').write_text('GROQ_API_KEY_3=third\n')
                self.assertEqual(experiment.configured_keys(root),['GROQ_API_KEY_3'])
                with self.assertRaisesRegex(ValueError,'missing'):
                    experiment.configured_keys(root,['GROQ_API_KEY_2'])

    def test_default_includes_every_s_system(self):
        self.assertEqual(s.SYSTEMS, ['S' + str(i) for i in range(9)])

    def test_macro_uses_the_same_reviewed_families_for_every_method(self):
        first=item(qid='q1')
        duration=item('calendar_duration',24,'F2',qid='q2')
        pending=prediction(24,duration,system='S1')
        pending['answer']['answer_type']='number'
        selected={'S0':{'q1':prediction(q=first,system='S0'),'q2':prediction(None,duration,system='S0')},
                  'S1':{'q1':prediction(q=first), 'q2':pending}}
        with tempfile.TemporaryDirectory() as folder:
            result=s.evaluate([first,duration],selected,{k:list(v.values()) for k,v in selected.items()},Path(folder),['S0','S1'],{})
            self.assertTrue(all(r['macro_families']=='F1' for r in result['comparison']))
            self.assertTrue(all(r['macro_accuracy']==1 for r in result['comparison']))

    def test_partial_collection_does_not_publish_macro_accuracy(self):
        first,second=item(qid='q1'),item(qid='q2')
        selected={'S0':{'q1':prediction(q=first,system='S0')},
                  'S1':{'q1':prediction(q=first),'q2':prediction(q=second)}}
        with tempfile.TemporaryDirectory() as folder:
            result=s.evaluate([first,second],selected,{k:list(v.values()) for k,v in selected.items()},Path(folder),['S0','S1'],{})
            self.assertTrue(all(r['macro_accuracy'] is None for r in result['comparison']))

    def test_sample_history_decodes_overlay_values(self):
        import duckdb
        from bugzilla_qa.evaluation.shared_source import history_checkpoint
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base, overlay = root / 'sample.duckdb', root / 'api_enrichment.duckdb'
            db = duckdb.connect(str(base))
            db.execute('CREATE TABLE bugs (bug_id VARCHAR,snapshot_status VARCHAR,snapshot_resolution VARCHAR,product VARCHAR,component VARCHAR,opened_at_utc TIMESTAMPTZ)')
            db.execute("INSERT INTO bugs VALUES ('101','RESOLVED','FIXED','Firefox','Layout','2022-01-03T00:00:00Z')")
            db.close()
            db = duckdb.connect(str(overlay))
            db.execute('CREATE TABLE field_changes (bug_id BIGINT,event_index INTEGER,event_time_utc VARCHAR,field_name VARCHAR,old_value VARCHAR,new_value VARCHAR,change_index INTEGER)')
            db.executemany('INSERT INTO field_changes VALUES (101,0,?,?,?,?,?)', [
                ['2022-01-04T02:00:00Z','status','"NEW"','"RESOLVED"',0],
                ['2022-01-04T02:00:00Z','resolution','""','"FIXED"',1]])
            db.execute('CREATE TABLE api_bug_refresh (row_json JSON)')
            db.execute('INSERT INTO api_bug_refresh VALUES (?)', [json.dumps(dict(bug_id='101',creation_time='2022-01-03T00:00:00Z'))])
            db.close()
            s.write(root / 'history_response_manifest.json', [dict(endpoint='history',status_code=200,bug_id=101,fetched_at_utc='2026-01-01T00:00:00Z')])
            history_checkpoint(root, base, overlay, root / 'checkpoint.json')
            record = s.read(root / 'checkpoint.json')['candidate_results']['101']
            history = record['history']
            self.assertEqual(record['source_consistency_differences'], [])
            self.assertEqual(history['state'], 'PARSED')
            self.assertEqual(history['first_fixed_at_utc'], '2022-01-04T02:00:00.000000Z')
            self.assertEqual(history['reopened_count'], 0)

    def test_sample_loader_preserves_count_scope_and_strips_gold(self):
        from bugzilla_qa.answering.sources import questions
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / 'bundle'
            bundle.mkdir()
            q = dict(qid='sample1', question='How many?', family='F3', split='dev',
                     scope=dict(partition='dev', partition_scheme='phase05'), gold={'value': 999})
            (bundle / 'questions.jsonl').write_text(json.dumps(q)+'\n')
            (root / 'source.txt').write_text('source')
            s.write(bundle / 'manifest.json', dict(state='SOURCE_VERIFIED_DEV_SAMPLE', sample_id='sample',
                                                   source_sha256={'source.txt':s.file_hash(root/'source.txt')},
                                                   sha256={'questions.jsonl':s.file_hash(bundle/'questions.jsonl')}))
            s.write(root / 'retrieval.json', {})
            loaded, _ = questions(dict(sample_bundle='bundle',retrieval_config='retrieval.json'),root,'sample','dev')
            self.assertEqual(loaded[0]['scope']['partition_scheme'],'phase05')
            self.assertNotIn('gold',loaded[0])

    def test_backend_reads_windows_manifest_paths(self):
        from bugzilla_qa.answering.backend import Backend
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            variant = root / 'index/C1'
            variant.mkdir(parents=True)
            (variant / 'corpus.jsonl').write_text(json.dumps(dict(chunk_id='c1',record_id='r1',bug_id='101',
                                                                visibility='public',kind='metadata',text='FIXED'))+'\n')
            s.write(variant / 'manifest.json',dict(state='COMPLETE',sha256={'corpus.jsonl':s.file_hash(variant/'corpus.jsonl')}))
            s.write(root / 'index/manifest.json',dict(state='COMPLETE',sha256={'C1\\manifest.json':s.file_hash(variant/'manifest.json')}))
            s.write(root / 'selection.json',dict(state='SOURCE_VERIFIED_DEV_SAMPLE',selected={'retriever':'R7b','corpus':'C1'},index_build='index'))
            s.write(root / 'retrieval.json',{})
            backend = Backend(dict(sample_bundle='bundle',retrieval_config='retrieval.json',selection='selection.json',retrieval_runs=[]),root,None)
            self.assertEqual(backend.by_id['c1']['text'],'FIXED')
            backend.config['retrieval_k']=10
            retriever=types.SimpleNamespace(retrieve=lambda q,k:[dict(chunk_id='c1',score=1)])
            with patch.object(backend,'_engine',return_value=None), patch('bugzilla_qa.answering.backend.get_retriever',return_value=retriever) as get:
                first=backend.retrieve(dict(question='Value?'),'R7b')
                second=backend.retrieve(dict(question='Value?'),'R7b',k=1)
                self.assertFalse(first[1])
                self.assertTrue(second[1])
                self.assertEqual(get.call_count,1)

    def test_portable_lock_excludes_another_handle(self):
        from bugzilla_qa import file_lock
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'run.lock'
            with path.open('a+') as first, path.open('a+') as second:
                file_lock.flock(first, file_lock.LOCK_EX | file_lock.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    file_lock.flock(second, file_lock.LOCK_EX | file_lock.LOCK_NB)
            with path.open('a+') as third:
                file_lock.flock(third, file_lock.LOCK_EX | file_lock.LOCK_NB)

    def test_terminal_failure_counts_without_blocking_finished_collection(self):
        with tempfile.TemporaryDirectory() as folder:
            p = dict(prediction(status='error'), terminal_error=True)
            result = s.evaluate([item()], {'S1': {'q1': p}}, {'S1': [p]}, Path(folder), ['S1'], {})
            self.assertEqual(result['state'], 'REVIEWED')
            self.assertEqual(result['table'][0]['accuracy'], 0.0)
            self.assertEqual(result['reliability'][0]['selected_errors'], 1)

    def test_holm_adjustment_covers_reported_comparisons(self):
        scores = []
        for system in ['S0', 'S1', 'S2']:
            for index in range(10):
                q = item(qid=str(index))
                scores.append(dict(s.grade(q, prediction('FIXED' if system == 'S1' else 'INVALID', q)), system_id=system))
        comparisons = s.paired(scores, ['S0', 'S1', 'S2'])
        self.assertEqual(len(comparisons), 3)
        self.assertTrue(all(1 >= r['holm_p'] >= r['permutation_p'] for r in comparisons))

    def test_small_cells_are_descriptive_without_significance_tests(self):
        scores=[]
        for system in ['S0','S1']:
            for index in range(4):
                q=item(qid=str(index))
                scores.append(dict(s.grade(q,prediction(q=q)),system_id=system))
        comparison=s.paired(scores,['S0','S1'])[0]
        self.assertIsNone(comparison['permutation_p'])
        self.assertNotIn('holm_p',comparison)

    def test_family_rules(self):
        cases = [('string', ' FIXED ', 'fixed', 'F1', True),
                 ('integer', 3, '3', 'F3', True), ('integer', 3, 3.1, 'F3', False),
                 ('integer', 1, True, 'F3', False), ('integer', 1, 'nan', 'F3', False),
                 ('calendar_hours', 24, 25, 'F2', True), ('calendar_hours', 24, 25.1, 'F2', False),
                 ('id_set', ['101', '102'], [102, 101], 'F4', True),
                 ('id_set', ['101', '102'], [101], 'F4', False),
                 ('id_set', [], [], 'F4', True), ('bug_id', '101', 102, 'KI', True),
                 ('bug_id', '101', 999, 'KI', False), ('abstain', 'ABSTAIN', None, 'F6H', True),
                 ('abstain', 'ABSTAIN', 'critical', 'F6H', False)]
        for kind, expected, value, family, correct in cases:
            with self.subTest(kind=kind, value=value):
                q = item(kind, expected, family)
                self.assertEqual(s.grade(q, prediction(value, q))['verdict'], 'CORRECT' if correct else 'INCORRECT')

    def test_failure_is_not_abstention(self):
        q = item('unknown', None, 'F6')
        self.assertEqual(s.grade(q, prediction(None, q, status='error'))['reason'], 'execution_failure')
        self.assertEqual(s.grade(q, None)['reason'], 'missing_prediction')

    def test_bad_contract_and_citation(self):
        p = prediction()
        p['answer']['abstain'] = True
        self.assertEqual(s.grade(item(), p)['reason'], 'invalid_answer_contract')
        p = prediction()
        p['answer']['citations'] = ['invented']
        self.assertEqual(s.grade(item(), p)['reason'], 'invalid_citation_id')

    def test_explanations_and_units_need_review(self):
        q = item('supported_explanation', {}, 'F5')
        self.assertEqual(s.grade(q, prediction(None, q))['verdict'], 'NEEDS_HUMAN')
        q = item('calendar_hours', 24, 'F2')
        p = prediction(1, q)
        p['answer']['answer_type'] = 'days'
        self.assertEqual(s.grade(q, p)['verdict'], 'CORRECT')
        p['answer']['answer_type'] = 'duration'
        self.assertEqual(s.grade(q, p)['verdict'], 'NEEDS_HUMAN')

    def test_ki_field_needs_bug_identity(self):
        q = item('string', 'Layout', 'KI')
        p = prediction('Layout', q)
        self.assertEqual(s.grade(q, p)['verdict'], 'CORRECT')
        p['answer']['bug_ids'] = [999]
        self.assertEqual(s.grade(q, p)['verdict'], 'INCORRECT')

    def test_ki_identifier_location_and_ambiguity(self):
        q = item('bug_id', '101', 'KI')
        p = prediction('Identified report', q)
        self.assertEqual(s.grade(q, p)['verdict'], 'CORRECT')
        p['answer']['bug_ids'] = [101, 102]
        self.assertEqual(s.grade(q, p)['verdict'], 'INCORRECT')
        p = prediction(101, q)
        p['answer']['bug_ids'] = [102]
        self.assertEqual(s.grade(q, p)['verdict'], 'INCORRECT')

    def test_structured_json_string_and_partial(self):
        q = item('structured', {'depends_on': ['101', '102'], 'resolved_fixed': ['101']}, 'MH')
        p = prediction('{"depends_on":[102,101],"resolved_fixed":[101]}', q)
        self.assertEqual(s.grade(q, p)['verdict'], 'CORRECT')
        p['answer']['answer'] = '{"depends_on":[101],"resolved_fixed":[101]}'
        result = s.grade(q, p)
        self.assertEqual(result['verdict'], 'INCORRECT')
        self.assertEqual(result['parts_correct'], 1)

    def test_attempts_are_not_independent_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            save_run(path, {'S1': [prediction(status='error'), prediction()]})
            selected, attempts, _ = s.select_predictions(path, [item()], ['S1', 'S2'])
            self.assertEqual(selected['S1']['q1']['status'], 'ok')
            self.assertEqual(len(attempts['S1']), 2)
            self.assertEqual(selected['S2'], {})
            result = s.evaluate([item()], selected, attempts, path / 'evaluation', ['S1', 'S2'], {})
            self.assertEqual(result['state'], 'PARTIAL')
            self.assertEqual(result['reliability'][0]['http_attempts'], 2)
            self.assertEqual(result['reliability'][0]['failed_attempts'], 1)

    def test_mixed_runs_and_conflicting_success_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for key, bad in [('config_hash', 'other'), ('freeze_id', 'other'), ('qid', 'other'), ('family', 'F2')]:
                with self.subTest(key=key):
                    p = prediction()
                    p[key] = bad
                    save_run(path, {'S1': [p]})
                    with self.assertRaises(ValueError):
                        s.select_predictions(path, [item()], ['S1'])
            save_run(path, {'S1': [prediction(), prediction('INVALID')]})
            with self.assertRaises(ValueError):
                s.select_predictions(path, [item()], ['S1'])
            save_run(path, {'S1': [prediction(), prediction()]})
            with self.assertRaises(ValueError):
                s.select_predictions(path, [item()], ['S1'])

    def test_terminal_failure_cannot_be_replaced_with_a_later_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            save_run(path,{'S1':[dict(prediction(status='error'),terminal_error=True),prediction()]})
            with self.assertRaisesRegex(ValueError,'Multiple terminal attempts'):
                s.select_predictions(path,[item()],['S1'])

    def test_blinded_tool_evidence_preserves_the_requested_filter(self):
        entry=dict(name='count_bugs',arguments=dict(scope='cohort',component='Search'),
                   result=dict(count=17,sql_template='canonical_distinct_bug_count_v1',parameters=dict(component='Search')))
        visible=s.visible_evidence(dict(route='S7',tools=[entry]),{'context_tokens':3000},{})
        self.assertNotIn('count_bugs',visible)
        self.assertNotIn('sql_template',visible)
        record=json.loads(visible)[0]
        self.assertEqual(record['request']['component'],'Search')
        self.assertEqual(record['result']['count'],17)

    def test_test_predictions_need_access_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            q = dict(item(), split='test')
            p = dict(prediction(), split='test')
            save_run(path, {'S1': [p]})
            with self.assertRaises(FileNotFoundError):
                s.select_predictions(path, [q], ['S1'])
            s.write(path / 'LOCKED_TEST_ACCESS.json', {'confirmed': True, 'freeze_id': 'frozen'})
            manifest = s.read(path / 'manifest.json')
            manifest['sha256']['LOCKED_TEST_ACCESS.json'] = s.file_hash(path / 'LOCKED_TEST_ACCESS.json')
            s.write(path / 'manifest.json', manifest)
            selected, _, _ = s.select_predictions(path, [q], ['S1'])
            self.assertEqual(selected['S1']['q1']['split'], 'test')

    def test_prediction_checksum_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            save_run(path, {'S1': [prediction()]})
            with (path / 'S1.jsonl').open('a') as handle:
                handle.write('\n')
            with self.assertRaises(ValueError):
                s.select_predictions(path, [item()], ['S1'])

    def test_frozen_loaders_and_test_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for dataset in ['phase05', 'v3']:
                directory = root / dataset
                directory.mkdir()
                question = dict(qid='q1', question='Value?', split='dev')
                gold = dict(qid='q1', family='F1', bug_ids=['101'], gold={'type': 'string', 'value': 'FIXED'})
                if dataset == 'v3':
                    question.update(family='KI', answer_type='bug_id', cluster_id='101')
                    gold = dict(qid='q1', answer='101', acceptable_bug_ids=['101'], evidence_record_ids=['r1'])
                for name, row in [('questions', question), ('gold', gold)]:
                    (directory / ('dev.' + name + '.jsonl')).write_text(json.dumps(row) + '\n')
                hashes = {p.name: s.file_hash(p) for p in directory.glob('*.jsonl')}
                s.write(directory / 'manifest.json', dict(status='FROZEN_HUMAN_SIGNED', freeze_id='f', sha256=hashes))
                config = {dataset + '_dir': dataset, dataset + '_freeze_id': 'f'}
                loaded, _ = s.load_items(root, config, dataset)
                self.assertEqual(loaded[0]['expected'], '101' if dataset == 'v3' else 'FIXED')
                with self.assertRaises(ValueError):
                    s.load_items(root, config, dataset, 'test')
                with (directory / 'dev.questions.jsonl').open('a') as handle:
                    handle.write('\n')
                with self.assertRaises(ValueError):
                    s.load_items(root, config, dataset)

    def test_natural_loader(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            q = dict(qid='n1', question='Value?', split='dev', family='F1', cluster_id='101',
                     human_review_state='HUMAN_APPROVED_WORDING', gold={'type': 'string', 'value': 'FIXED'})
            (root / 'natural.jsonl').write_text(json.dumps(q) + '\n')
            s.write(root / 'manifest.json', {'sha256': s.file_hash(root / 'natural.jsonl')})
            loaded, _ = s.load_items(root, {'natural_questions': 'natural.jsonl', 'natural_manifest': 'manifest.json'}, 'natural')
            self.assertEqual(loaded[0]['expected'], 'FIXED')

    def test_human_review_is_blinded_and_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            q = item('supported_explanation', 'Reason', 'F5')
            p = prediction('Reason', q)
            first = s.evaluate([q], {'S1': {'q1': p}}, {'S1': [p]}, path, ['S1'], {})
            self.assertEqual(first['state'], 'NEEDS_REVIEW')
            queue = path / 'review_queue.csv'
            with queue.open(newline='') as handle:
                entries = list(csv.DictReader(handle))
            self.assertNotIn('system_id', entries[0])
            entries[0].update(answer_verdict='CORRECT', grounding_verdict='SUPPORTED', reviewer='Reviewer A', note='Checked the source comment.')
            s.write_csv(queue, entries, list(entries[0]))
            second = s.evaluate([q], {'S1': {'q1': p}}, {'S1': [p]}, path, ['S1'], {})
            self.assertEqual(second['state'], 'REVIEWED')
            self.assertEqual(second['table'][0]['correct'], 1)

    def test_cluster_intervals_and_pending_comparisons(self):
        self.assertIsNone(s.bootstrap({'one': [1, 0, 1]}))
        self.assertEqual(s.bootstrap({'a': [1], 'b': [1]}), [1.0, 1.0])
        q = item('supported_explanation', {}, 'F5')
        a = dict(s.grade(q, prediction(None, q)), system_id='S1')
        b = dict(a, system_id='S2')
        self.assertEqual(s.paired([a, b], ['S1', 'S2']), [])

    def test_full_synthetic_workflow_and_rerun(self):
        with tempfile.TemporaryDirectory() as folder:
            first = experiment.demo(Path(folder))
            second = experiment.demo(Path(folder))
            self.assertTrue(first['simulated'])
            self.assertEqual(first['questions'], 12)
            self.assertEqual(first['table'], second['table'])
            self.assertTrue((Path(folder) / 'fixture/report.md').is_file())
            self.assertEqual(sum(r['needs_human'] for r in first['table']), 5)
            self.assertTrue(first['always_abstain'])

    def test_shared_budget_across_datasets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            s.write(root / 'config.json', {'retrieval_config': 'retrieval.json'})
            s.write(root / 'retrieval.json', {})
            args = types.SimpleNamespace(config='config.json', datasets=['phase05', 'v3'], split='dev',
                                         systems=['S0'], limit=None, confirm_locked_test=False, dry_run=False, max_requests=3)
            budgets = []
            def prepared(config, root, dataset, *rest):
                return [dict(qid='q1', family='F1')], None, None, None, None, root / dataset
            def run(command, **kwargs):
                dataset = command[command.index('--dataset') + 1]
                budget = int(command[command.index('--max-requests') + 1])
                budgets.append(budget)
                s.write(root / dataset / 'summary.json', {'actual_api_calls': 2 if dataset == 'phase05' else 1, 'state': 'COMPLETE'})
                return types.SimpleNamespace(returncode=0)
            modules = {'bugzilla_qa.answering.calibration': types.SimpleNamespace(with_calibration=lambda c, r: c),
                       'bugzilla_qa.answering.runner': types.SimpleNamespace(plan=lambda *a, **k: {}, prepare=prepared)}
            with patch.dict('sys.modules', modules), patch.object(experiment, 'ROOT', root), patch.object(experiment.sys, 'platform', 'linux'), patch.object(experiment.subprocess, 'run', run), patch('sys.stdout', io.StringIO()):
                experiment.generate(args)
            self.assertEqual(budgets, [3, 1])

    def test_score_only_cli_on_real_bundle_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            frozen = root / 'frozen'
            frozen.mkdir()
            question = dict(qid='q1', question='Recorded resolution?', split='dev', family='F1',
                            answer_type='string', cluster_id='101')
            gold = dict(qid='q1', answer='FIXED', acceptable_bug_ids=[], evidence_record_ids=['r1'])
            for name, value in [('questions', question), ('gold', gold)]:
                (frozen / ('dev.' + name + '.jsonl')).write_text(json.dumps(value) + '\n')
            hashes = {p.name: s.file_hash(p) for p in frozen.iterdir()}
            s.write(frozen / 'manifest.json', dict(status='FROZEN_HUMAN_SPOTCHECKED', freeze_id='frozen', sha256=hashes))
            s.write(root / 'retrieval.json', {'v3_dir': 'frozen', 'v3_freeze_id': 'frozen'})
            s.write(root / 'answering.json', {'retrieval_config': 'retrieval.json', 'selection':'selection.json'})
            save_run(root / 'predictions', {'S1': [prediction()]})
            arguments = ['--score-only', '--datasets', 'v3', '--systems', 'S1', '--config', 'answering.json',
                         '--prediction-run', 'v3=predictions']
            with patch.object(experiment, 'ROOT', root), patch('sys.stdout', io.StringIO()), \
                 patch.object(review,'build',return_value={'page':'START_HERE.html'}) as build:
                self.assertEqual(experiment.main(arguments), 0)
                build.assert_called_once_with(root,root/'outputs/evaluation/phase11')
            latest = s.read(root / 'outputs/evaluation/phase11/latest.json')
            report = Path(latest['evaluations']['v3']['output'])
            self.assertEqual(s.read(report / 'summary.json')['table'][0]['correct'], 1)
            self.assertTrue((report / 'review_queue.csv').exists())
            self.assertEqual(latest['review_files']['page'],'START_HERE.html')


if __name__ == '__main__':
    unittest.main()

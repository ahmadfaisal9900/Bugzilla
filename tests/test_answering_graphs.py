"""Bounded offline acceptance: three questions, real LangGraph, mock provider."""
import copy
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from jsonschema import validate,ValidationError
import duckdb
from langsmith import Client,trace,tracing_context
from bugzilla_qa.llm.provider import MockProvider,GroqProvider,GeminiProvider,tool_turn_schema
from bugzilla_qa.answering.contracts import ANSWER_SCHEMA,check_answer,clean,pack,public_chunk
from bugzilla_qa.answering.graph import AnswerGraph,SYSTEMS,rule_route
from bugzilla_qa.answering.tools import Tools,TOOLS
from bugzilla_qa.answering import runner

ANSWER=dict(abstain=False,answer='Firefox',answer_type='string',bug_ids=[101],citations=[],rationale='The recorded product is Firefox.')


def respond(prompt):
    p=json.loads(prompt)
    if p.get('instruction'):
        if not p.get('evidence'):
            return {'calls':[{'name':'get_bug_fields','arguments_json':json.dumps({'bug_id':101,'fields':['product']})}]}
        return {'calls':[{'name':'submit_answer','arguments_json':json.dumps(ANSWER)}]}
    return copy.deepcopy(ANSWER)


class FakeBackend:
    def __init__(self,*args):
        self.selected='R7b';self.corpus='C1';self.low=False;self.rc={};self.cache_manifests={}
        self.docs=[dict(chunk_id='m101',record_id='r101',bug_id='101',text='Public product Firefox.',
                       visibility='public',kind='metadata',score=2,rank=1)]
    def retrieve(self,q,method,k=None,use_cache=True):return [dict(self.docs[0],score=-3 if self.low else 2)],True
    def dossier(self,q):return self.docs
    def oracle(self,refs):return [d for d in self.docs if d['record_id'] in refs]
    def corrective(self,q,h):return self.retrieve(q,'R5')[0],[q['question']]
    def score_top(self,h):return h[0]['score'] if h else float('-inf')


class AnsweringTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=dict(context_tokens=3000,dossier_tokens=12000,tool_steps=4,seed=317,
            prompt_version='answer-v1',query_transform='R7b',corrective_tau=0,source_config='source.json',
            history_checkpoint='history.json',duckdb_memory='64MB',prompt='prompt.txt',token_counter='utf8_byte_upper_bound',
            trace_sample=1,trace_projects={'dev':'ensf621-dev','test':'ensf621-test'},systems=list(SYSTEMS))
        (self.root/'source.json').write_text(json.dumps({'canonical_db':'base.duckdb'}))
        (self.root/'prompt.txt').write_text('If unsupported, abstain.')
        db=duckdb.connect(str(self.root/'base.duckdb'))
        db.execute('CREATE TABLE bugs(bug_id VARCHAR,product VARCHAR,component VARCHAR,snapshot_status VARCHAR,snapshot_resolution VARCHAR,opened_at_utc TIMESTAMPTZ,snapshot_as_of_utc TIMESTAMPTZ,source_record_id VARCHAR)')
        db.execute("INSERT INTO bugs VALUES ('101','Firefox','UI','NEW','','2020-01-01T00:00:00Z',NULL,'r101'),('102','Firefox','UI','RESOLVED','DUPLICATE','2020-01-02T00:00:00Z',NULL,'r102')")
        db.execute('CREATE TABLE sample_membership(bug_id VARCHAR,seed INTEGER)');db.execute("INSERT INTO sample_membership VALUES ('101',317),('102',317)")
        db.execute('CREATE TABLE source_records(source_record_id VARCHAR,disposition VARCHAR,normalized_fields JSON,bug_id VARCHAR,source_dataset VARCHAR)')
        db.execute('CREATE TABLE bug_links(bug_id VARCHAR,target_bug_id VARCHAR,link_key VARCHAR,relation VARCHAR)')
        db.execute("INSERT INTO bug_links VALUES ('101','102','l101','depends_on')");db.close()
        record={'history':{'state':'PARSED','chronology_ok':True,'same_time_groups':[],
            'first_fixed_at_utc':'2020-01-03T00:00:00Z','reopened_count':1},'source_consistency_differences':[]}
        (self.root/'history.json').write_text(json.dumps({'candidate_results':{'101':record}}))
        self.backend=FakeBackend();self.tools=Tools(self.config,self.root,self.backend)
        self.questions=[dict(qid='q'+str(i),question=t,family=f,split='dev',dataset='v3',freeze_id='fixture',scope={})
            for i,(t,f) in enumerate([('What product was bug 101 filed under?','F1'),
                                    ('Why was bug 101 changed?','F5'),('Which report concerns a public UI issue?','KI')])]
    def tearDown(self):self.tools.close();self.tmp.cleanup()
    def graph(self,provider=None,records=None,confirm=False):
        if records is None:records=[]
        return AnswerGraph(self.config,provider or MockProvider(respond),self.backend,self.tools,'Shared prompt',records.append,confirm)

    def test_all_systems_three_questions_real_graph(self):
        with tracing_context(enabled=False):
            for system in SYSTEMS:
                p=MockProvider(respond);rows=[];g=self.graph(p,rows)
                for q in self.questions:
                    q=dict(q,oracle_refs=['r101'])
                    state=g.invoke(q,system,'fixture-config')
                    self.assertEqual(state['status'],'ok',(system,state['errors']))
                    validate(state['answer'],ANSWER_SCHEMA)
                self.assertEqual(len(rows),3)
                self.assertTrue(all(r['call_count']>=1 for r in rows))

    def test_locked_test_gate(self):
        with self.assertRaisesRegex(RuntimeError,'confirm-locked-test'):
            self.graph().invoke(dict(self.questions[0],split='test'),'S0','fixture')

    def test_s4_low_abstains_without_provider_call(self):
        p=MockProvider(respond);self.backend.low=True
        state=self.graph(p).invoke(self.questions[0],'S4','fixture')
        self.assertEqual(p.calls,0);self.assertEqual(state['call_count'],0)
        self.assertTrue(state['answer']['abstain']);self.assertEqual(state['route'],'abstain_low_evidence')

    def test_parameterized_tools_and_read_only(self):
        q=self.questions[0]
        for args in ({'bug_id':101,'fields':['summary; DROP TABLE bugs']},
                     {'bug_id':'101 OR 1=1','fields':['product']}):
            with self.assertRaises(ValidationError):self.tools.execute('get_bug_fields',args,q)
        with self.assertRaises(ValueError):self.tools.execute('count_bugs',{'component':"UI'; DROP TABLE bugs;--",'scope':'cohort'},q)
        with self.assertRaises(ValueError):self.tools.execute('execute_sql',{'sql':'SELECT * FROM bugs'},q)
        self.assertEqual(self.tools.execute('count_bugs',{'scope':'cohort'},q)['count'],2)
        self.assertEqual(self.tools.execute('get_links',{'bug_id':101,'link_type':'depends_on'},q)['targets'],['102'])
        with self.assertRaises(Exception):self.tools.db.execute('DELETE FROM bugs')

    def test_separate_history_unknown_and_conflict(self):
        self.assertFalse(self.tools.lifecycle(999)['known'])
        r=self.tools.lifecycle(101);self.assertTrue(r['first_fixed_known'])
        self.assertEqual(r['fix_metric']['elapsed_calendar_days'],2)
        self.assertEqual(r['reopened_count'],1)
        asof=dict(self.questions[0],scope={'as_of':'2019-01-01T00:00:00Z'})
        self.assertFalse(self.tools.execute('get_lifecycle',{'bug_id':101},asof)['known'])
        self.tools._history['101']['source_consistency_differences']=['conflict']
        self.assertFalse(self.tools.lifecycle(101)['known'])

    def test_router_rules(self):
        for text,route in [('How many bugs exist?','S7'),('Why bug 101?','S5'),('Bug 101 blocks which issue?','S7'),('An ID-free symptom','S2'),('What status has bug 101?','S7')]:
            self.assertEqual(rule_route(text)[0],route)

    def test_json_repair_once_and_citation_gate(self):
        calls=[]
        def value(prompt):
            calls.append(prompt)
            return dict(ANSWER,abstain=True) if len(calls)==1 else ANSWER
        p=MockProvider(value);state=self.graph(p).invoke(self.questions[0],'S1','fixture')
        self.assertEqual(p.calls,2);self.assertEqual(state['repair_count'],1);self.assertEqual(state['status'],'ok')
        with self.assertRaises(ValueError):check_answer(dict(ANSWER,citations=['unseen']),['m101'])

    def test_exact_context_label_resolution_preserves_raw_output(self):
        for label in ('C1','[C1]'):
            p=MockProvider(dict(ANSWER,citations=[label]))
            state=self.graph(p).invoke(self.questions[0],'S1','fixture')
            self.assertEqual(state['status'],'ok');self.assertEqual(p.calls,1)
            self.assertEqual(state['answer']['citations'],['m101'])
            self.assertEqual(state['raw_output']['citations'],[label])
            self.assertEqual(state['citation_normalization'],[{'label':label,'chunk_id':'m101'}])
        for system,label in [('S1','C99'),('S0','C1')]:
            p=MockProvider(dict(ANSWER,citations=[label]))
            state=self.graph(p).invoke(self.questions[0],system,'fixture')
            self.assertEqual(state['status'],'error');self.assertEqual(p.calls,2)

    def test_closed_book_rejected_browser_call_gets_one_counted_repair(self):
        class RejectedTool(Exception):
            status_code=400
            body={'error':{'code':'tool_use_failed','failed_generation':'browser.run MUST_NOT_EXECUTE'}}
        cfg={'provider':'groq','models':{'generator':{'id':'mock','rpm':1000,'rpd':1000}},
             'max_retries':0,'daily_fraction':.9,'env_file':'.env','ledger':'repair.jsonl',
             'cache':'repair.sqlite','temperature':0,'max_output_tokens':100}
        p=GroqProvider(cfg,'generator',enable_llm=True,max_requests=2,root=self.root,client=object())
        with patch.object(p,'_request',side_effect=[RejectedTool(),(ANSWER,10,10)]) as request,\
             patch.object(self.tools,'execute',side_effect=AssertionError('No tools in S0')):
            state=self.graph(p).invoke(self.questions[0],'S0','fixture')
        self.assertEqual(state['status'],'ok');self.assertEqual(state['repair_count'],1)
        self.assertEqual(state['call_count'],2);self.assertEqual(request.call_count,2)
        self.assertIn('No tools or browser',request.call_args_list[1][0][0])
        self.assertNotIn('MUST_NOT_EXECUTE',(self.root/'repair.jsonl').read_text())

    def test_rejected_tool_recovery_respects_http_cap(self):
        class RejectedTool(Exception):
            status_code=400
            body={'code':'tool_use_failed'}
        cfg={'provider':'groq','models':{'generator':{'id':'mock','rpm':1000,'rpd':1000}},
             'max_retries':0,'daily_fraction':.9,'env_file':'.env','ledger':'cap.jsonl',
             'cache':'cap.sqlite','temperature':0,'max_output_tokens':100}
        p=GroqProvider(cfg,'generator',enable_llm=True,max_requests=1,root=self.root,client=object())
        with patch.object(p,'_request',side_effect=RejectedTool()) as request:
            state=self.graph(p).invoke(self.questions[0],'S0','fixture')
        self.assertEqual(p.calls,1);self.assertEqual(request.call_count,1)
        self.assertEqual(state['status'],'error');self.assertEqual(state['repair_count'],1)

    def test_pack_privacy_unicode_and_budget(self):
        chunks=[dict(self.backend.docs[0],text='界'*3000)]
        context,mapping=pack(chunks,3000)
        self.assertLessEqual(len(context.encode()),3000);self.assertEqual(mapping,{'C1':'m101'})
        for visibility in ('private','unknown',None):
            with self.assertRaises(ValueError):public_chunk(dict(chunks[0],visibility=visibility))

    def test_resume_no_duplicate_calls_and_frozen_untouched(self):
        p=MockProvider(respond);out=self.root/'predictions';pins={}
        # Frozen fixture directory is a sentinel outside the output run.
        frozen=self.root/'frozen';frozen.mkdir();(frozen/'dev.gold.jsonl').write_text('immutable test gold\n')
        before=(frozen/'dev.gold.jsonl').read_bytes()
        prep=(self.questions,pins,{'models':{'generator':{'id':'mock'}},'provider':'groq'},
              {'freeze_id':'fixture'},'fixture-config',out)
        with patch.object(runner,'prepare',return_value=prep),patch.object(runner,'create_provider',return_value=p),patch.object(runner,'Backend',return_value=self.backend):
            result=runner.run(self.config,self.root,systems=['S0'],enable_llm=True,max_requests=10)
            self.assertEqual(result['state'],'COMPLETE');self.assertEqual(p.calls,3)
            result=runner.run(self.config,self.root,systems=['S0'],enable_llm=True,max_requests=10,resume=True)
            self.assertEqual(p.calls,3)
        lines=(out/'S0.jsonl').read_text().splitlines();self.assertEqual(len(lines),3)
        self.assertEqual((frozen/'dev.gold.jsonl').read_bytes(),before)

    def test_all_systems_write_prediction_ledgers(self):
        p=MockProvider(respond);out=self.root/'all-ledgers'
        prep=(self.questions,{}, {'models':{'generator':{'id':'mock'}},'provider':'groq'},
              {'freeze_id':'fixture'},'fixture-config',out)
        with patch.object(runner,'prepare',return_value=prep),patch.object(runner,'create_provider',return_value=p),\
             patch.object(runner,'Backend',return_value=self.backend),\
             patch.object(runner,'oracle_references',return_value={q['qid']:['r101'] for q in self.questions}):
            result=runner.run(self.config,self.root,systems=list(SYSTEMS),enable_llm=True,max_requests=100)
        self.assertEqual(result['state'],'COMPLETE')
        for system in SYSTEMS:
            rows=[json.loads(line) for line in (out/(system+'.jsonl')).read_text().splitlines()]
            self.assertEqual(len(rows),3)
            for row in rows:
                validate(row['answer'],ANSWER_SCHEMA)
                self.assertEqual(row['config_hash'],'fixture-config');self.assertEqual(row['status'],'ok')

    def test_question_loader_strips_natural_gold_and_pins_scope(self):
        from bugzilla_qa.answering.sources import questions
        from bugzilla_qa.retrieval_v3.common import file_hash
        record=dict(self.questions[0],gold={'answer':'SECRET_TEST_GOLD_SENTINEL'},human_review_state='HUMAN_APPROVED_WORDING',
                    scope={'partition':'dev','corpus':'sampled Firefox'})
        (self.root/'natural.jsonl').write_text(json.dumps(record)+'\n')
        (self.root/'natural_manifest.json').write_text(json.dumps({'sha256':file_hash(self.root/'natural.jsonl')}))
        (self.root/'retrieval.json').write_text(json.dumps({'natural_questions':'natural.jsonl','natural_manifest':'natural_manifest.json'}))
        config={'retrieval_config':'retrieval.json'}
        rows,_=questions(config,self.root,'natural','dev')
        self.assertNotIn('SECRET_TEST_GOLD_SENTINEL',json.dumps(rows))
        self.assertEqual(rows[0]['scope']['partition_scheme'],'expanded-v2')
        with self.assertRaisesRegex(RuntimeError,'confirm-locked-test'):
            questions(config,self.root,'natural','test')

    def test_reference_upload_dry_run_cap_and_resume_mock_only(self):
        from bugzilla_qa.answering import upload
        config=dict(self.config,retrieval_config='retrieval.json',output_root='outputs/predictions')
        (self.root/'retrieval.json').write_text(json.dumps({'v3_dir':'frozen-v3','natural_questions':'natural.jsonl'}))
        frozen=self.root/'frozen-v3';frozen.mkdir()
        gold=[{'qid':q['qid'],'answer':'reference only','split':'dev'} for q in self.questions]
        (frozen/'dev.gold.jsonl').write_text(''.join(json.dumps(g)+'\n' for g in gold))
        (frozen/'manifest.json').write_text('{}')
        (self.root/'natural.jsonl').write_text(''.join(json.dumps(g)+'\n' for g in gold))
        fake=MagicMock(spec=Client);fake.read_dataset.return_value=types.SimpleNamespace(id='dataset-id')
        with patch.object(upload,'questions',return_value=(self.questions,{'fixture':'fixed-hash'})),\
             patch.object(upload,'checked_file',return_value=frozen/'dev.gold.jsonl'),\
             patch.object(upload,'trace_client',return_value=fake):
            dry=upload.upload(config,self.root)
            self.assertEqual(dry['actual_requests'],0);self.assertFalse(fake.create_example.called)
            partial=upload.upload(config,self.root,enable=True,max_requests=2,resume=True)
            self.assertEqual(partial['state'],'PARTIAL');self.assertEqual(partial['actual_requests'],2)
            done=upload.upload(config,self.root,enable=True,max_requests=20,resume=True)
            self.assertEqual(done['state'],'COMPLETE')
            again=upload.upload(config,self.root,enable=True,max_requests=20,resume=True)
            self.assertEqual(again['actual_requests'],0)
        self.assertEqual(fake.create_example.call_count,6)

    def test_pilot_resume_keeps_fixed_first_per_family(self):
        out=self.root/'pilot';out.mkdir()
        qs=[dict(self.questions[0],qid='q'+str(i)) for i in range(5)]
        (out/'S0.jsonl').write_text(json.dumps({'qid':'q0','status':'ok'})+'\n')
        rows,_=runner.pending(qs,out,'S0',True,per_family=3)
        self.assertEqual([q['qid'] for q in rows],['q1','q2'])
        rows,_=runner.pending(qs,out,'S0',True,limit=2)
        self.assertEqual([q['qid'] for q in rows],['q1','q2'])

    def test_one_fixed_question_all_systems_budget_and_resume(self):
        p=MockProvider(respond);out=self.root/'one-question'
        prep=(self.questions,{}, {'models':{'generator':{'id':'mock'}},'provider':'groq'},
              {'freeze_id':'fixture'},'fixture-config',out)
        with patch.object(runner,'prepare',return_value=prep),patch.object(runner,'create_provider',return_value=p),\
             patch.object(runner,'Backend',return_value=self.backend):
            result=runner.run(self.config,self.root,systems=list(SYSTEMS)[:9],qids=['q0'],
                              enable_llm=True,max_requests=12,resume=True)
            self.assertEqual(result['state'],'COMPLETE_SELECTED_BATCH')
            self.assertEqual(result['selection']['question_count'],1)
            self.assertLessEqual(p.calls,12);before=p.calls
            again=runner.run(self.config,self.root,systems=list(SYSTEMS)[:9],qids=['q0'],
                              enable_llm=True,max_requests=12,resume=True)
            self.assertEqual(p.calls,before)
        for path in out.glob('S*.jsonl'):
            rows=[json.loads(line) for line in path.open()]
            self.assertEqual([r['qid'] for r in rows],['q0'])
        with self.assertRaises(ValueError):runner.fixed_questions(self.questions,['not-a-dev-qid'])

    def test_plan_zero_calls_and_known_response_cache_hits(self):
        import sqlite3
        llm={'provider':'groq','models':{'generator':{'id':'mock','rpm':3,'rpd':1000}},
             'cache':'responses.sqlite','env_file':'.env','ledger':'calls.jsonl','max_retries':0,
             'daily_fraction':.9,'temperature':0,'max_output_tokens':100}
        prep=(self.questions,{},llm,{},'fixture-config',self.root/'plan')
        p=MockProvider(respond)
        with patch.object(runner,'prepare',return_value=prep),patch.object(runner,'Backend',return_value=self.backend),patch.object(runner,'create_provider',return_value=p):
            first=runner.plan(self.config,self.root,systems=['S0'])
            self.assertEqual(first['estimated_model_calls'],3);self.assertEqual(p.calls,0)
            with sqlite3.connect(str(self.root/'responses.sqlite')) as db:
                db.execute('CREATE TABLE responses(key VARCHAR)')
                key=runner.cached_generation_key(llm,json.dumps({'question':self.questions[0]['question']}),
                    (self.root/'prompt.txt').read_text(),ANSWER_SCHEMA,self.config['prompt_version'])
                db.execute('INSERT INTO responses VALUES (?)',[key]);db.commit()
            second=runner.plan(self.config,self.root,systems=['S0'])
            self.assertEqual(second['systems']['S0']['known_answer_cache_hits'],1)
            self.assertEqual(second['estimated_model_calls'],2);self.assertEqual(p.calls,0)

    def test_tool_step_cap_and_different_partition_rules(self):
        def repeat(prompt):
            if json.loads(prompt).get('instruction'):
                return {'calls':[{'name':'get_bug_fields','arguments_json':json.dumps({'bug_id':101,'fields':['product']})}]}
            return ANSWER
        p=MockProvider(repeat);s=self.graph(p).invoke(self.questions[0],'S7','fixture')
        self.assertEqual(s['tool_step'],4);self.assertEqual(p.calls,5);self.assertEqual(len(s['tool_log']),4)
        from bugzilla_qa.benchmark.phase05 import partition as p5
        from bugzilla_qa.eval_extension.bank import partition as p2
        for name,fn in [('phase05',p5),('expanded-v2',p2)]:
            q=dict(self.questions[0],scope={'partition':'dev','partition_scheme':name})
            count=self.tools.execute('count_bugs',{'scope':'cohort'},q)['count']
            self.assertEqual(count,sum(fn(317,b)=='dev' for b in ('101','102')))

    def test_secret_free_ledgers_and_trace_payloads(self):
        key='FAKE_SECRET_DO_NOT_SERIALIZE_12345'
        fake=MagicMock(spec=Client)
        with patch.dict(os.environ,{'GROQ_API_KEY':key,'LANGSMITH_API_KEY':key}):
            value=clean({'question':key,'text':'public@example.org','self':self})
            self.assertNotIn(key,json.dumps(value));self.assertNotIn('public@example.org',json.dumps(value))
            with tracing_context(enabled=True,client=fake,project_name='offline-mock'):
                rule_route('What status for bug 101 '+key)
            serialized=str(fake.create_run.call_args_list)+str(fake.update_run.call_args_list)
            self.assertNotIn(key,serialized)
            self.assertTrue(fake.create_run.called)

    def test_native_groq_tools_share_provider_cache_and_ledger(self):
        captured=[]
        def create(**kwargs):
            captured.append(kwargs)
            call=types.SimpleNamespace(function=types.SimpleNamespace(name='submit_answer',arguments=json.dumps(ANSWER)))
            return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason='tool_calls',message=types.SimpleNamespace(tool_calls=[call]))],usage=None)
        client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        cfg={'provider':'groq','models':{'generator':{'id':'mock-model','rpm':1000,'rpd':1000}},'max_retries':0,
             'daily_fraction':.9,'env_file':'.env','ledger':'ledger.jsonl','cache':'cache.sqlite','temperature':0,'max_output_tokens':100}
        p=GroqProvider(cfg,'generator',enable_llm=True,max_requests=2,root=self.root,client=client)
        p.generate_tools('public question',TOOLS);p.generate_tools('public question',TOOLS)
        self.assertEqual(p.calls,1);self.assertEqual(len(captured),1)
        self.assertIn('tools',captured[0]);self.assertNotIn('response_format',captured[0])
        self.assertEqual(len((self.root/'ledger.jsonl').read_text().splitlines()),3)

    def test_native_gemini_adapter_mock_only(self):
        capture=[]
        def create(**kwargs):
            capture.append(kwargs)
            return types.SimpleNamespace(function_calls=[types.SimpleNamespace(name='submit_answer',args=ANSWER)],usage_metadata=None)
        client=types.SimpleNamespace(models=types.SimpleNamespace(generate_content=create))
        cfg={'provider':'gemini','models':{'generator':{'id':'mock-model','rpm':1000,'rpd':1000}},'max_retries':0,
             'daily_fraction':.9,'env_file':'.env','ledger':'ledger.jsonl','cache':'cache.sqlite','temperature':0,'max_output_tokens':100}
        p=GeminiProvider(cfg,'generator',enable_llm=True,max_requests=1,root=self.root,client=client)
        result=p.generate_tools('public question',TOOLS)
        self.assertEqual(result['value']['calls'][0]['name'],'submit_answer')
        self.assertIn('function_declarations',capture[0]['config']['tools'][0])
        self.assertEqual(p.calls,1)

    def test_tau_suggestion_dev_only_idempotent_and_stale_rejected(self):
        import sqlite3
        from bugzilla_qa.answering.calibration import suggest,with_calibration
        folder=self.root/'retrieval';folder.mkdir()
        (self.root/'selection.json').write_text(json.dumps({'selected':{'corpus':'C1'},'compatibility':'fixture'}))
        (folder/'identity.json').write_text(json.dumps({'split':'dev','compatibility':'fixture'}))
        (folder/'manifest.json').write_text(json.dumps({'state':'COMPLETE'}))
        with sqlite3.connect(str(folder/'retrieval_cache.sqlite')) as db:
            db.execute('CREATE TABLE results(dataset TEXT,qid TEXT,payload TEXT,corpus TEXT,retriever TEXT)')
            for i,score in enumerate((-2,0,3)):
                db.execute('INSERT INTO results VALUES (?,?,?,?,?)',['v3',str(i),json.dumps({'hits':[{'score':score}]}),'C1','R5'])
        config=dict(self.config,selection='selection.json',retrieval_runs=['retrieval'],corrective_tau=None,corrective_calibration='tau.json')
        dry=suggest(config,self.root);self.assertEqual(dry['n'],3);self.assertFalse((self.root/'tau.json').exists())
        written=suggest(config,self.root,write=True)
        self.assertEqual(with_calibration(config,self.root)['corrective_tau'],written['tau'])
        suggest(config,self.root,write=True)
        (self.root/'selection.json').write_text('{}')
        with self.assertRaises(RuntimeError):with_calibration(config,self.root)

if __name__=='__main__':unittest.main()

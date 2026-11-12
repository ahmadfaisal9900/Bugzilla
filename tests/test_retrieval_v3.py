"""Offline, 50-chunk fixture: no model download, embeddings job or HTTP."""
import json
import re
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

from bugzilla_qa.llm.provider import MockProvider, GroqProvider
from bugzilla_qa.eval_extension.retrieval import build_lexical
from bugzilla_qa.retrieval_v3 import corpus, datasets, metrics, runner, selection
from bugzilla_qa.retrieval_v3.common import file_hash, read_config, receipt, write_json, write_jsonl
from bugzilla_qa.retrieval_v3.registry import Engine, REGISTRY, get_retriever, jaccard
from bugzilla_qa.retrieval_v3.transforms import QueryTransforms


class Tokenizer:
    is_fast=True
    def __call__(self,text,add_special_tokens=True,**kwargs):
        spans=[m.span() for m in re.finditer(r'\w+|[^\w\s]',text)]
        return {'input_ids':list(range(len(spans)+(2 if add_special_tokens else 0))),
                'offset_mapping':spans}


class Dense:
    def __init__(self,docs): self.docs=docs
    def search(self,query,k,filter_bug=True,allowed_bug_ids=None):
        terms=set(query.lower().split())
        docs=[d for d in self.docs if allowed_bug_ids is None or d['bug_id'] in allowed_bug_ids]
        hits=[dict(d,score=float(len(terms & set(d['text'].lower().split())))) for d in docs]
        return sorted(hits,key=lambda d:(-d['score'],d['chunk_id']))[:k]


class Cross:
    def predict(self,pairs,**kwargs):
        return [len(set(q.lower().split()) & set(t.lower().split())) for q,t in pairs]


def fixture_docs():
    return [dict(chunk_id='chunk-%02d'%i,record_id='record-%02d'%i,bug_id=str(100000+i//10),
                 kind='metadata' if i%10==0 else 'history' if i%10==2 else 'comment',
                 text='Bug %d browser tab focus keyboard issue record %d'%(100000+i//10,i),
                 visibility='public',source_hash='sha-'+str(i),url='https://example.invalid/bug/'+str(100000+i//10))
            for i in range(50)]


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.config=read_config(Path(__file__).parents[1]/'configs/retrieval_v3.yaml')
        self.docs=fixture_docs();self.lexical=self.root/'lexical.sqlite'
        build_lexical(self.lexical,self.docs,'fixture')
        self.edges=[{'source':str(100000+i),'target':str(100000+(i+1)%5)} for i in range(5)]
        self.provider=MockProvider(lambda prompt:{'queries':['browser keyboard focus']*3})
        # HyDE and multi-query have different exact response shapes.
        def response(prompt): return {'queries':['browser keyboard focus']}
        self.transforms=QueryTransforms(MockProvider(response))
        self.engine=Engine(self.docs,self.lexical,Dense(self.docs),Cross(),self.edges,self.config,self.transforms)
    def tearDown(self): self.temp.cleanup()

    def test_all_registry_adapters_return_schema_and_k(self):
        for method in REGISTRY:
            n=1 if method=='R7a' else 3
            self.engine.transforms=QueryTransforms(MockProvider({'queries':['browser keyboard focus']*n}))
            hits=get_retriever(method,self.engine).retrieve('browser keyboard focus',10)
            self.assertEqual(len(hits),10,method)
            self.assertEqual(len({h['chunk_id'] for h in hits}),10)
            for i,h in enumerate(hits,1):
                self.assertTrue({'chunk_id','record_id','bug_id','chunk_type','score','rank','text'}<=h.keys())
                self.assertEqual(h['rank'],i)

    def test_r4_exact_id_and_hierarchy_overlap_diagnostic(self):
        r4=get_retriever('R4',self.engine).retrieve('Bug #100003 browser tab',10)
        self.assertEqual({h['bug_id'] for h in r4},{'100003'})
        bare=get_retriever('R4',self.engine).retrieve('What component for 100003?',10)
        self.assertEqual({h['bug_id'] for h in bare},{'100003'})
        r3=get_retriever('R3',self.engine).retrieve('Bug #100003 browser tab',10)
        self.assertLess(jaccard(r4,r3),1)
        h=get_retriever('R4',self.engine).retrieve('keyboard focus',10)
        self.assertEqual(len({d['bug_id'] for d in h}),1)

    def test_graph_slots_and_prefix_stability(self):
        large=get_retriever('R6',self.engine).retrieve('keyboard focus',50)
        small=get_retriever('R6',self.engine).retrieve('keyboard focus',10)
        self.assertEqual([h['chunk_id'] for h in small],[h['chunk_id'] for h in large[:10]])
        expansion=[h for h in small if h.get('graph_expansion')]
        self.assertTrue(expansion);self.assertLessEqual(len(expansion),3)
        self.assertTrue(all(h['kind']=='metadata' for h in expansion))

    def test_token_budget_overlap_prefix_and_source_record_ids(self):
        docs=fixture_docs();docs[1]['text']=' '.join('token%d'%i for i in range(470))
        meta={d['bug_id']:{'component':'Tabs','summary':' '.join(['symptom']*70)} for d in docs}
        for variant in ('C1','C2'):
            chunks=list(corpus.variant_rows(variant,docs,docs,meta,Tokenizer(),self.config))
            self.assertTrue(all(corpus.token_length(Tokenizer(),d['text'])<=256 for d in chunks))
            self.assertEqual({d['record_id'] for d in chunks},{d['record_id'] for d in docs})
            pieces=[c for c in chunks if c['record_id']==docs[1]['record_id']]
            self.assertGreater(len(pieces),1)
            self.assertTrue(all(c['source_char_start']<c['source_char_end'] for c in pieces))
            if variant=='C1':
                a=pieces[0]['text'].split();b=pieces[1]['text'].split()
                self.assertEqual(a[-40:],b[:40])
                self.assertTrue(all(len(c['text'].split())<=200 for c in pieces))
            else:
                self.assertTrue(all(c['text'].startswith('Bug '+c['bug_id']+' | Tabs | ') for c in chunks))
            self.assertIn('token469',pieces[-1]['text'])
        docs[1]['visibility']='unknown'
        with self.assertRaisesRegex(RuntimeError,'visibility'):
            list(corpus.variant_rows('C1',docs,docs,meta,Tokenizer(),self.config))

    def test_record_qrels_metrics_no_double_credit_and_na(self):
        hits=[dict(self.docs[0],record_id='r1'),dict(self.docs[1],record_id='r1'),dict(self.docs[2],record_id='r2')]
        s=metrics.score(hits,{'r1','r2','unindexed'},'MH',['100000'])
        self.assertEqual(s['hit_at_1'],1);self.assertAlmostEqual(s['recall_at_10'],2/3)
        self.assertEqual(s['mh_full_evidence_at_10'],0)
        self.assertEqual(s['bug_hit_at_5'],1)
        for family in ('F3','F6','F6H'):
            s=metrics.score(hits,{'r1'},family)
            self.assertEqual(s['state'],'N/A');self.assertIsNone(s['recall_at_10'])
        cells=metrics.summarize([],['v3'],['F2','F6'],['R1'],['C0'],{'v3':{'F6':2}})
        self.assertEqual([c['state'] for c in cells],['not in dataset','N/A'])
        self.assertEqual(metrics.score([],[],'F2')['state'],'UNKNOWN')

    def test_cluster_bootstrap_reproducible_weighting_and_holm(self):
        pairs=[('a',1),('a',1),('b',0),('c',0)]
        a=metrics.paired_bootstrap(pairs,resamples=10000)
        self.assertEqual(a,metrics.paired_bootstrap(pairs,resamples=10000))
        self.assertEqual(a['difference'],.5);self.assertEqual(a['clusters'],3)
        rows=[]
        for i,(cluster,delta) in enumerate(pairs):
            for method,value in [('R1',0),('R2',delta),('R3',delta)]:
                rows.append(dict(qid=str(i),dataset='v3',family='KI',corpus='C0',retriever=method,
                                 cluster_id=cluster,metrics={'state':'KNOWN_CITATION_PROXY','hit_at_5':value,'recall_at_10':value}))
        stats=metrics.comparisons(rows,dict(self.config,bootstrap_resamples=30))
        self.assertTrue(all(r['holm_p_value']>=r['p_value'] for r in stats))

    def make_datasets(self):
        c=dict(self.config,phase05_dir='phase05',v3_dir='v3',natural_questions='natural.jsonl',
               natural_manifest='natural_manifest.json',index_root='indexes',output_root='results',
               selection_output='selected.yaml',bootstrap_resamples=30)
        for ds in ('phase05','v3'):
            out=self.root/ds;out.mkdir()
            questions=[];gold=[];qrels=[]
            for i in range(12):
                family='F6' if i==11 else 'F3' if i==10 else 'F1'
                qid=ds+str(i)
                questions.append(dict(qid=qid,question='What component is recorded for bug '+str(100000+i%5)+'?',
                                      family=family,cluster_id=str(100000+i%5)))
                gold.append(dict(qid=qid,family=family,bug_ids=[str(100000+i%5)],acceptable_bug_ids=[str(100000+i%5)],
                                 evidence=[{'id':'record-%02d'%((i%5)*10)}],evidence_record_ids=['record-%02d'%((i%5)*10)]))
                qrels.append(dict(qid=qid,known_evidence_ids=['record-%02d'%((i%5)*10)]))
            write_jsonl(out/'dev.questions.jsonl',questions);write_jsonl(out/'dev.gold.jsonl',gold)
            if ds=='v3':write_jsonl(out/'qrels_v3_dev.jsonl',qrels)
            receipt(out,state='FROZEN_HUMAN_SIGNED',status='FROZEN_HUMAN_SPOTCHECKED',
                    id=c[ds+'_freeze_id'],freeze_id=c[ds+'_freeze_id'])
        rows=[]
        for i in range(10):
            rows.append(dict(qid='n'+str(i),question='bug '+str(100000+i%5)+' tab focus',family='F1',split='dev',
                             cluster_id='bug:'+str(100000+i%5),bug_ids=[str(100000+i%5)],
                             evidence=[{'id':'record-%02d'%((i%5)*10)}],human_review_state='HUMAN_APPROVED_WORDING'))
        write_jsonl(self.root/'natural.jsonl',rows)
        write_json(self.root/'natural_manifest.json',{'sha256':file_hash(self.root/'natural.jsonl')})
        (self.root/'docs').mkdir();(self.root/'docs/RETRIEVER_SELECTION.md').write_text('fixture protocol')
        idx=self.root/'indexes/build-fixture';(idx/'C0').mkdir(parents=True)
        write_jsonl(idx/'C0/corpus.jsonl',self.docs)
        build_lexical(idx/'C0/lexical.sqlite',self.docs,'fixture')
        receipt(idx/'C0',state='COMPLETE')
        receipt(idx,state='COMPLETE',variants=['C0'],limit_bugs=None)
        write_json(self.root/'indexes/LATEST_BUILD.json',{'run':idx.name})
        return c

    def test_test_split_blocked_before_opening_labels(self):
        with self.assertRaisesRegex(RuntimeError,'Locked test'):
            datasets.load_datasets(self.config,self.root,'test')

    def test_build_variants_pin_models_reuse_c0_and_resume(self):
        config=dict(self.config,source_corpus='source/corpus.jsonl',source_corpus_manifest='source/manifest.json',
                    source_config='source/config.json',source_dense_dir='source',canonical_db='base/canonical.duckdb',
                    index_root='indexes')
        write_jsonl(self.root/'source/corpus.jsonl',self.docs)
        write_json(self.root/'source/manifest.json',{'chunks':50,'sha256':file_hash(self.root/'source/corpus.jsonl')})
        write_json(self.root/'source/config.json',{'canonical_db':config['canonical_db'],
            'history_db':'overlay/api_enrichment.duckdb','sample_seed':317})
        write_json(self.root/'base/manifest.json',{'state':'COMPLETE'})
        write_json(self.root/'overlay/summary.json',{'state':'COMPLETE'})
        (self.root/'source/dense.faiss').write_bytes(b'fixture-index')
        write_json(self.root/'source/dense_manifest.json',{'model':config['embedding_model'],
            'revision':config['embedding_revision'],'corpus_sha256':file_hash(self.root/'source/corpus.jsonl'),
            'index_sha256':file_hash(self.root/'source/dense.faiss'),'truncated_chunks':0})
        metadata={d['bug_id']:{'component':'Tabs','summary':'Keyboard focus'} for d in self.docs}
        built=[]
        def build_dense(path,out,model,batch,device,resume,revision):
            built.append(out.name);self.assertEqual(revision,config['embedding_revision'])
            (out/'dense.faiss').write_bytes(b'fixture-variant-index')
            write_json(out/'dense_manifest.json',{'model':model,'revision':revision,'truncated_chunks':0,
                'index_sha256':file_hash(out/'dense.faiss'),'corpus_sha256':file_hash(path)})
        transformer=types.SimpleNamespace(AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda *a,**kw:Tokenizer()))
        with patch.object(corpus,'source_metadata',return_value=(metadata,self.edges)),\
             patch.object(corpus,'verify_source_manifests'),patch.object(corpus,'records',return_value=iter(self.docs)),\
             patch.object(corpus,'build_dense',side_effect=build_dense),patch.dict('sys.modules',{'transformers':transformer}):
            result=corpus.build(config,self.root,resume=True)
            self.assertEqual(result['state'],'COMPLETE')
            self.assertEqual(built,['C1','C2'])
            again=corpus.build(config,self.root,resume=True)
            self.assertEqual(again['state'],'ALREADY_BUILT_VERIFIED')
        out=Path(result['output'])
        self.assertEqual(file_hash(out/'C0/corpus.jsonl'),file_hash(self.root/'source/corpus.jsonl'))
        for variant in ('C1','C2'):
            self.assertEqual(read_config(out/variant/'manifest.json')['truncated_chunks'],0)

    def test_r7_zero_call_plan_resume_cached_results_and_frozen_immutability(self):
        config=self.make_datasets(); before={str(p):file_hash(p) for ds in ('phase05','v3') for p in (self.root/ds).glob('*')}
        plan=runner.run(config,self.root,methods=['R7a','R7b'],corpora=['C0'],limit=2)
        self.assertEqual(plan['state'],'DRY_RUN');self.assertEqual(plan['actual_api_calls'],0)
        self.assertEqual(plan['planned_transform_calls_upper_bound'],2*len({q['question'] for q in datasets.load_datasets(config,self.root,limit=2)[0]}))
        def engine(directory,c,models,transforms):
            return Engine(self.docs,self.lexical,Dense(self.docs),Cross(),self.edges,c,transforms)
        with patch.object(runner,'load_models',return_value=(None,None)),patch.object(runner,'load_engine',side_effect=engine):
            result=runner.run(config,self.root,methods=['R1','R3','R4','R5'],corpora=['C0'],limit=2,resume=True)
            self.assertEqual(result['state'],'COMPLETE')
            again=runner.run(config,self.root,methods=['R1','R3','R4','R5'],corpora=['C0'],limit=2,resume=True)
            self.assertEqual(again['state'],'ALREADY_COMPLETE_VERIFIED')
        after={str(p):file_hash(Path(p)) for p in before};self.assertEqual(before,after)
        output=Path(result['output']); rows=list(runner.read_jsonl(output/'per_question.jsonl'))
        self.assertEqual(len(rows),len({(r['dataset'],r['qid'],r['retriever'],r['corpus']) for r in rows}))
        self.assertTrue(all('text' not in h for r in rows for h in r['hits']))
        sample=rows[0]
        cached=runner.load_cached_hits(output,sample['corpus'],sample['retriever'],sample['dataset'],sample['qid'])
        self.assertEqual(len(cached),50);self.assertTrue(all('text' in h and 'gold' not in h for h in cached))
        self.assertTrue(all(r.get('r4_r3_jaccard_top10') is not None for r in rows if r['retriever']=='R4'))
        with self.assertRaisesRegex(RuntimeError,'unlimited'):
            selection.select(config,[output/'summary.json'],self.root)

    def test_real_engine_loader_reads_edge_list_and_rejects_unknown_visibility(self):
        config=self.make_datasets();directory=self.root/'indexes/build-fixture/C0'
        write_json(directory.parent/'graph.json',self.edges)
        write_json(directory/'dense_manifest.json',{'revision':config['embedding_revision']})
        with patch('bugzilla_qa.eval_extension.dense.DenseSearcher',return_value=Dense(self.docs)):
            engine=runner.load_engine(directory,config,(None,Cross()),None)
            self.assertTrue(engine.neighbours)
            self.assertEqual(len(get_retriever('R6',engine).retrieve('keyboard focus',10)),10)
            private=dict(self.docs[0],visibility='unknown')
            write_jsonl(directory/'corpus.jsonl',[private])
            with self.assertRaisesRegex(RuntimeError,'visibility'):
                runner.load_engine(directory,config,(None,Cross()),None)

    def test_r7_transform_resume_provider_cache_and_latency(self):
        provider=MockProvider({'queries':['keyboard focus']});t=QueryTransforms(provider)
        t.get('R7a','question');t.get('R7a','question')
        self.assertEqual(provider.calls,1);self.assertTrue(t.info('R7a','question')['cache_hit'])
        self.assertEqual(t.info('R7a','question')['reuse_latency_ms'],0)
        get_retriever('R7a',self.engine).retrieve('keyboard focus',10)
        get_retriever('R7a',self.engine).retrieve('keyboard focus',10)
        self.assertEqual(self.transforms.provider.calls,1)

    def test_r7_interrupted_run_durable_provider_cache_and_no_secret_leak(self):
        config=self.make_datasets()
        llm=read_config(Path(__file__).parents[1]/'configs/llm.yaml')
        for model in llm['models'].values(): model.update(rpm=1000,rpd=1000)
        llm.update(max_retries=0,ledger='llm/ledger.jsonl',cache='llm/cache.sqlite')
        write_json(self.root/'configs/llm.yaml',llm)
        (self.root/'.env').write_text('GROQ_API_KEY=dummy-fixture-credential\n')
        calls=[]
        def request(**kwargs):
            calls.append(kwargs)
            count=kwargs['response_format']['json_schema']['schema']['properties']['queries']['minItems']
            return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason='stop',
                message=types.SimpleNamespace(content=json.dumps({'queries':['keyboard focus']*count})))],usage=None)
        client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=request)))
        def factory(c,role,**kwargs): return GroqProvider(c,role,client=client,**kwargs)
        def engine(directory,c,models,transforms):
            return Engine(self.docs,self.lexical,Dense(self.docs),Cross(),self.edges,c,transforms)
        with patch.object(runner,'load_models',return_value=(None,None)),patch.object(runner,'load_engine',side_effect=engine),\
             patch('bugzilla_qa.llm.provider.create_provider',side_effect=factory):
            offline=runner.run(config,self.root,methods=['R1','R5'],corpora=['C0'],limit=1,resume=True)
            first=runner.run(config,self.root,methods=['R7a','R7b'],corpora=['C0'],limit=1,
                             resume=True,enable_llm=True,max_requests=1)
            self.assertEqual(first['state'],'PARTIAL');self.assertEqual(len(calls),1)
            second=runner.run(config,self.root,methods=['R7a','R7b'],corpora=['C0'],limit=1,
                              resume=True,enable_llm=True,max_requests=20)
            self.assertEqual(second['state'],'COMPLETE')
        questions=datasets.load_datasets(config,self.root,limit=1)[0]
        self.assertEqual(len(calls),2*len({q['question'] for q in questions}))
        rows=list(runner.read_jsonl(Path(second['output'])/'per_question.jsonl'))
        self.assertEqual(len(rows),len({(r['dataset'],r['qid'],r['retriever'],r['corpus']) for r in rows}))
        self.assertTrue(all(r['reused_previous_run'] for r in rows if r['retriever'] in ('R1','R5')))
        for base in ('llm','results'):
            for p in (self.root/base).rglob('*'):
                if p.is_file(): self.assertNotIn(b'dummy-fixture-credential',p.read_bytes())

    def test_locked_test_run_refuses_existing_even_with_resume(self):
        config=self.make_datasets()
        for ds in ('phase05','v3'):
            directory=self.root/ds
            for kind in ('questions','gold'):
                (directory/('test.'+kind+'.jsonl')).write_bytes((directory/('dev.'+kind+'.jsonl')).read_bytes())
            if ds=='v3':
                (directory/'qrels_v3_test.jsonl').write_bytes((directory/'qrels_v3_dev.jsonl').read_bytes())
            receipt(directory,state='FROZEN_HUMAN_SIGNED',status='FROZEN_HUMAN_SPOTCHECKED',
                    id=config[ds+'_freeze_id'],freeze_id=config[ds+'_freeze_id'])
        def engine(directory,c,models,transforms):
            return Engine(self.docs,self.lexical,Dense(self.docs),Cross(),self.edges,c,transforms)
        with patch.object(runner,'load_models',return_value=(None,None)),patch.object(runner,'load_engine',side_effect=engine):
            first=runner.run(config,self.root,split='test',confirm=True,methods=['R1'],corpora=['C0'],
                             datasets=['v3'],limit=1)
            self.assertTrue((Path(first['output'])/'LOCKED_TEST_ACCESS.json').exists())
            with self.assertRaisesRegex(RuntimeError,'refusing overwrite/resume'):
                runner.run(config,self.root,split='test',confirm=True,methods=['R1'],corpora=['C0'],
                           datasets=['v3'],limit=1,resume=True)

    def test_selection_n_threshold_tie_and_r7_gain(self):
        roster={'v3:KI':['q'+str(i) for i in range(10)],'natural:F1':['n'+str(i) for i in range(10)]}
        obs=[]
        for method,value,latency in [('R1',.8,20),('R5',.9,100),('R6',.895,70),('R7a',.915,150)]:
            for cell,qids in roster.items():
                ds,fam=cell.split(':')
                obs.extend(dict(dataset=ds,family=fam,qid=q,retriever=method,corpus='C0',
                                recall_at_10=value,latency_ms=latency) for q in qids)
        out=self.root/'experiment';out.mkdir()
        (self.root/'docs').mkdir();(self.root/'docs/RETRIEVER_SELECTION.md').write_text('fixture protocol')
        summary=dict(split='dev',locked_test_used=False,state='COMPLETE',limited=False,compatibility='fixture',
                     selection_roster=roster,selection_protocol_sha256=file_hash(self.root/'docs/RETRIEVER_SELECTION.md'),
                     selection_observations=obs,index_build='indexes/build-fixture')
        write_json(out/'summary.json',summary);receipt(out,state='COMPLETE')
        result=selection.select(self.config,[out/'summary.json'],self.root,output='selected.yaml')
        self.assertEqual(result['selected']['retriever'],'R6')
        self.assertEqual(len(result['excluded_r7']),1)
        self.assertEqual(result['selected']['cells_n'],2)
        with self.assertRaisesRegex(RuntimeError,'exists'):
            selection.select(self.config,[out/'summary.json'],self.root,output='selected.yaml')
        summary['split']='test';write_json(out/'summary.json',summary)
        with self.assertRaisesRegex(RuntimeError,'Locked-test'):
            selection.select(self.config,[out/'summary.json'],self.root,output='other.yaml')


if __name__=='__main__':unittest.main()

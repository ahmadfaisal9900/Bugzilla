import csv
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from bugzilla_qa.eval_extension.bank import make_item, partition
from bugzilla_qa.eval_extension.dense import hierarchical, rerank, build_dense
from bugzilla_qa.eval_extension.metrics import score_ranked, summarize
from bugzilla_qa.eval_extension.pipeline import generate_natural, verify_bank, run_retrieval, tune_dev, export_approved_f5
from bugzilla_qa.eval_extension.cli import file_hash
from bugzilla_qa.eval_extension.contracts import validate, jsonl_to_parquet
from bugzilla_qa.eval_extension.generation import FixedIndex, infer, score_predictions
from bugzilla_qa.eval_extension.retrieval import build_lexical, make_chunks


class PipelineTests(unittest.TestCase):
    def test_partition_and_no_gold_in_question(self):
        evidence=[{'id':'r1','bug_id':'123','source_url':'https://example.org','content_hash':'abc'}]
        q=make_item('F1','What was the recorded status of bug 123?',{'type':'string','value':'OPEN'},'123',evidence,317)
        self.assertEqual(q['split'],partition(317,'123'))
        self.assertNotIn('OPEN',q['question'])
        self.assertEqual(q['cluster_id'],'bug:123')

    def test_family_denominators(self):
        hits=[{'record_id':'a'},{'record_id':'a'},{'record_id':'b'}]
        result=score_ranked(hits,{'a','b'},'F4')
        self.assertEqual(result['recall_at_5'],1)
        self.assertAlmostEqual(result['precision_at_5'],.4)
        self.assertEqual(score_ranked(hits,{'a'},'F3')['state'],'NOT_APPLICABLE')
        self.assertEqual(score_ranked(hits,set(),'F1')['state'],'NOT_RETRIEVABLE')

    def test_reranker_and_hierarchy(self):
        class Fake:
            def predict(self,pairs,show_progress_bar=False): return [0.2,0.8]
        hits=[{'chunk_id':'a','kind':'metadata','bug_id':'1','text':'one','score':1},
              {'chunk_id':'b','kind':'comment','bug_id':'1','text':'two','score':.5}]
        self.assertEqual(rerank('query',hits,Fake())[0]['chunk_id'],'b')
        self.assertEqual(len(hierarchical('query',hits,hits)),2)
        self.assertEqual(hierarchical('query',[hits[1]],[hits[1]]),[])

    def test_natural_review_is_pending(self):
        evidence=[{'id':'r','bug_id':'1','source_url':'x','content_hash':'a'}]
        q=make_item('F1','In the broad metadata archive for Firefox bug 1 (snapshot date unknown), what is its recorded status?',
                    {'type':'string','value':'OPEN'},'1',evidence,317)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'review.csv';report=generate_natural([q],p,317)
            with p.open(newline='') as f: rows=list(csv.DictReader(f))
            self.assertEqual(report['state'],'PENDING_HUMAN_REVIEW')
            self.assertTrue(all(r['decision']=='PENDING' for r in rows))
            self.assertNotIn('OPEN',p.read_text())

    def test_changed_bank_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'selected.jsonl').write_text('{}\n')
            (p/'bank_manifest.json').write_text(json.dumps({'hashes':{'selected.jsonl':file_hash(p/'selected.jsonl')}}))
            verify_bank(p)
            (p/'selected.jsonl').write_text('changed')
            with self.assertRaises(RuntimeError): verify_bank(p)

    def test_contract_and_parquet(self):
        q={'qid':'q','family':'F1','question':'question','split':'dev','scope':{},'cluster_id':'bug:1'}
        validate('Question',q)
        with self.assertRaises(ValueError): validate('Question',dict(q,split='training'))
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'q.jsonl';target=Path(temp)/'q.parquet'
            source.write_text(json.dumps(q)+'\n')
            jsonl_to_parquet(source,target,'Question')
            self.assertTrue(target.exists())

    def test_fixed_index_respects_top_k(self):
        self.assertEqual(FixedIndex([{'x':1},{'x':2}]).search('ignored',1),[{'x':1}])

    def test_retrieval_resume_with_fake_models(self):
        doc={'record_id':'r1','bug_id':'123','kind':'metadata','text':'Bug 123 printing',
             'url':'https://example.org','source_hash':'abc','visibility':'public'}
        doc=next(make_chunks(doc))
        evidence=[{'id':'r1','bug_id':'123','source_url':'https://example.org','content_hash':'abc'}]
        q=make_item('F1','What is recorded for bug 123?',{'type':'string','value':'OPEN'},'123',evidence,317)
        q['split']='dev';q['validator']='fixture'
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp); corpus=out/'corpus.jsonl'; index=out/'lexical.sqlite'
            corpus.write_text(json.dumps(doc)+'\n'); build_lexical(index,[doc],'identity')
            (out/'lexical_manifest.json').write_text(json.dumps({'sha256':file_hash(index)}))
            selected=out/'selected.jsonl';selected.write_text(json.dumps(q)+'\n')
            (out/'bank_manifest.json').write_text(json.dumps({'hashes':{'selected.jsonl':file_hash(selected)}}))
            (out/'dense_manifest.json').write_text('{}');(out/'dense.faiss').write_text('fixture')
            class Dense:
                def __init__(self,*args): pass
                def search(self,query,k): return [dict(doc,rank=1,score=.8)]
            class Cross:
                def __init__(self,*args,**kwargs): self.model=types.SimpleNamespace(config=types.SimpleNamespace(_commit_hash='abc'))
                def predict(self,pairs,show_progress_bar=False): return [1.0]*len(pairs)
            config={'dense_model':'fake','reranker_model':'fake','rrf_k':60}
            with patch('bugzilla_qa.eval_extension.pipeline.DenseSearcher',Dense), patch.dict('sys.modules',{'sentence_transformers':types.SimpleNamespace(CrossEncoder=Cross)}):
                first=run_retrieval(out,corpus,index,[q],config,'dev',None,'cpu')
                second=run_retrieval(out,corpus,index,[q],config,'dev',None,'cpu',True)
            rows=(out/'retrieval_dev.jsonl').read_text().splitlines()
            self.assertEqual(first['state'],'COMPLETE');self.assertEqual(second['state'],'COMPLETE')
            self.assertEqual(len(rows),5)
            self.assertIn(tune_dev(out)['selected_rrf_k'],(30,60,90))

    def test_fake_generation_has_no_gold_and_resumes(self):
        evidence=[{'id':'r1','bug_id':'123','source_url':'https://example.org','content_hash':'abc'}]
        q=make_item('F1','What is recorded for bug 123?',{'type':'string','value':'OPEN'},'123',evidence,317)
        q['split']='dev';q['validator']='fixture'
        doc=next(make_chunks({'record_id':'r1','bug_id':'123','kind':'metadata','text':'status open',
                              'url':'https://example.org','source_hash':'abc','visibility':'public'}))
        messages=[]
        class Client:
            def __init__(self,model,max_requests): self.calls=0
            def chat(self,request):
                self.calls+=1;messages.extend(request)
                return {'content':json.dumps({'answer':'Open','value':'OPEN','abstained':False,'evidence':[]})}
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'corpus.jsonl').write_text(json.dumps(doc)+'\n')
            row={'qid':q['qid'],'method':'bm25','hits':[dict(doc,rank=1,score=1)]}
            (p/'retrieval_dev.jsonl').write_text(json.dumps(row)+'\n')
            with patch('bugzilla_qa.eval_extension.generation.OllamaClient',Client):
                first=infer(p,p,[q],'dev','fixture',2,False)
                second=infer(p,p,[q],'dev','fixture',2,True)
            self.assertEqual(first['requests_this_invocation'],2)
            self.assertEqual(second['requests_this_invocation'],0)
            self.assertNotIn(q['qid'],json.dumps(messages))
            self.assertNotIn('"gold"',json.dumps(messages))
            self.assertEqual(score_predictions(p,[q],'dev')['state'],'COMPLETE')

    def test_dense_shards_resume_with_fake_encoder(self):
        import numpy as np
        class Index:
            def __init__(self,dimension): self.rows=[]
            def add(self,v): self.rows.extend(v.tolist())
        class Faiss:
            IndexFlatIP=Index
            @staticmethod
            def write_index(index,path): Path(path).write_text(json.dumps(index.rows))
        class Encoder:
            def __init__(self,name,device):
                self.max_seq_length=8
                self.tokenizer=lambda texts,**kwargs:{'length':[len(t.split()) for t in texts]}
            def __getitem__(self,index): return types.SimpleNamespace(auto_model=types.SimpleNamespace(config=types.SimpleNamespace(_commit_hash='rev1')))
            def get_sentence_embedding_dimension(self): return 2
            def encode(self,texts,**kwargs): return np.array([[1.,0.] for _ in texts],dtype='float32')
        def progress(items,**kwargs): return items
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);corpus=out/'corpus.jsonl'
            corpus.write_text('\n'.join(json.dumps({'text':'one two'}) for _ in range(3))+'\n')
            with patch('bugzilla_qa.eval_extension.dense._deps',return_value=(Faiss,np,Encoder,progress)):
                first=build_dense(corpus,out,'fixture',batch_size=2)
                second=build_dense(corpus,out,'fixture',batch_size=2,resume=True)
            self.assertEqual(first['count'],3);self.assertEqual(first,second)

    def test_f5_requires_real_review_fields(self):
        packet={'bug_id':'123','comment_id':'c1','source_url':'https://example.org',
                'content_hash':'sha','public_comment_sanitized':'The change is needed because it prevents an error.'}
        columns=['qid','bug_id','question','comment_id','source_url','content_hash','suggested_gold',
                 'decision','reviewer','reviewed_at_utc','source_checked','note']
        row={'qid':'fixture','bug_id':'123','question':'why','comment_id':'c1','source_url':'https://example.org',
             'content_hash':'sha','suggested_gold':'It prevents an error.','decision':'APPROVE','reviewer':'reviewer',
             'reviewed_at_utc':'2026-11-10T00:00:00Z','source_checked':'YES','note':''}
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);(out/'f5_review_packets.jsonl').write_text(json.dumps(packet)+'\n')
            with (out/'f5_review.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerow(row)
            self.assertEqual(export_approved_f5(out,317)['approved'],1)


if __name__=='__main__': unittest.main()

"""Twenty-bug offline fixture: no real dataset, model weights, or HTTP client."""
import csv
import json
import io
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
import numpy as np

from bugzilla_qa.benchmark.v3 import generate
from bugzilla_qa.benchmark import v3
from bugzilla_qa.benchmark.v3_rules import cluster_split
from bugzilla_qa.benchmark.v3_source import file_hash, write_json, write_jsonl, Source
from bugzilla_qa.benchmark.v3_verify import verify_candidate
from bugzilla_qa.benchmark.v3_freeze import freeze
from bugzilla_qa.benchmark.v3_validate import validate_run
from bugzilla_qa.data.normalize import digest
from bugzilla_qa.eval_extension.bank import partition
from bugzilla_qa.llm.provider import read_config, ROOT, MockProvider


class Encoder:
    def encode(self, texts, **kwargs):
        return np.eye(len(texts), dtype='float32')


class DescriptionProvider(MockProvider):
    def __init__(self, budget=100):
        self.prompts = []
        super().__init__(self.describe, max_requests=budget)

    def describe(self, prompt):
        self.prompts.append(prompt)
        word = json.loads(prompt)['summary'].split()[1]
        return {'description': word + ' has an unexpected problem during print preview.'}


def fixture(root):
    words = 'alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango'.split()
    config = read_config(ROOT / 'configs/benchmark_v3.yaml')
    config.update(canonical_db='base.duckdb', history_db='api.duckdb', history_checkpoint='checkpoint.json',
                  phase05_dir='phase05/frozen-original', natural_approved='natural.jsonl',
                  expanded_selected='selected.jsonl', corpus='corpus.jsonl', output_root='outputs/benchmark/v3',
                  ki_target=8, ki_parent_target=4, multi_hop_target=6, hard_abstention_target=6,
                  f1_cap=4,expected_cohort_size=20)
    config.update(canonical_manifest='base_manifest.json',history_summary='api_summary.json',
                  corpus_manifest='corpus_manifest.json',llm_config='llm.json')
    config.update(phase05_freeze_id='original',natural_manifest='natural_manifest.json',expanded_manifest='expanded_manifest.json')
    db = duckdb.connect(str(root / 'base.duckdb'))
    db.execute("""CREATE TABLE bugs (bug_id VARCHAR,summary VARCHAR,product VARCHAR,component VARCHAR,
       snapshot_status VARCHAR,snapshot_resolution VARCHAR,opened_at_utc TIMESTAMPTZ,
       source_record_id VARCHAR,content_hash VARCHAR,source_url VARCHAR,snapshot_assignee VARCHAR)""")
    db.execute('CREATE TABLE sample_membership (bug_id VARCHAR,seed INTEGER)')
    db.execute('CREATE TABLE source_records (bug_id VARCHAR,source_dataset VARCHAR,disposition VARCHAR)')
    db.execute("""CREATE TABLE comments (bug_id VARCHAR,comment_key VARCHAR,body VARCHAR,content_hash VARCHAR,
       private_flag BOOLEAN,text_availability VARCHAR,event_time_utc TIMESTAMPTZ)""")
    db.execute("""CREATE TABLE bug_links (bug_id VARCHAR,relation VARCHAR,target_bug_id VARCHAR,link_key VARCHAR,content_hash VARCHAR)""")
    corpus = []
    for i, word in enumerate(words, 1):
        bug = str(i); status = 'RESOLVED' if i % 2 == 0 else 'NEW'; resolution = 'FIXED' if i % 2 == 0 else None
        db.execute("INSERT INTO bugs VALUES (?,?, 'Firefox','Printing',?,?,'2020-01-01T00:00:00Z',?,?,?,'fixture@example.org')",
                   [bug, 'Session ' + word + ' fails while printing', status, resolution, 'm'+bug, 'mh'+bug, 'https://example.org/'+bug])
        db.execute('INSERT INTO sample_membership VALUES (?,317)', [bug])
        private = True if i == 3 else None if i == 4 else False
        body = ('PRIVATE_BODY_SHOULD_NEVER_LEAVE' if i in (3,4) else 'Public printing report ' + word + ' fixture@example.org TOKEN_fixture_493')
        db.execute("INSERT INTO comments VALUES (?,?,?,?,?,'AVAILABLE','2020-01-02T00:00:00Z')", [bug, 'c'+bug, body, 'ch'+bug, private])
        corpus.append({'record_id': 'm'+bug, 'chunk_id': 'mc'+bug, 'source_hash': 'mh'+bug, 'bug_id': bug, 'kind': 'metadata', 'url': 'https://example.org/'+bug, 'visibility': 'public'})
        if private is False:
            corpus.append({'record_id': 'c'+bug, 'chunk_id': 'cc'+bug, 'source_hash': 'ch'+bug, 'bug_id': bug, 'kind': 'comment', 'url': 'https://example.org/'+bug, 'visibility': 'public'})
    db.execute("INSERT INTO source_records VALUES ('5','metadata','CONFLICT_VARIANT')")
    same = [str(i) for i in range(6,21) if cluster_split(317,str(i)) == 'dev']
    if len(same) < 3:
        same = [str(i) for i in range(6,21) if cluster_split(317,str(i)) == 'test']
    a,b,c = same[:3]
    edges = [(a, 'depends_on', b), (a,'depends_on',c), (b,'duplicate_of',c), (c,'blocks',a)]
    for i,(s,r,t) in enumerate(edges):
        key = 'l'+str(i)
        db.execute('INSERT INTO bug_links VALUES (?,?,?,?,?)', [s,r,t,key,'hash'+key])
        corpus.append({'record_id': key, 'chunk_id': key+'c', 'source_hash': 'hash'+key, 'bug_id': s, 'kind': 'link', 'url': 'https://example.org/'+s, 'visibility':'public'})
    api = duckdb.connect(str(root / 'api.duckdb'))
    api.execute("""CREATE TABLE field_changes (bug_id BIGINT,event_time_utc VARCHAR,source_row_key VARCHAR,content_sha256 VARCHAR,
      field_name VARCHAR,new_value VARCHAR,old_value VARCHAR,history_state VARCHAR,event_index INTEGER,change_index INTEGER)""")
    api.execute("""INSERT INTO field_changes VALUES (7,'2020-01-02T00:00:00Z','h7','hashh7','resolution','"FIXED"','""','PARSED',0,0)""")
    api.close()
    corpus.append({'record_id':'h7','chunk_id':'hc7','source_hash':'hashh7','bug_id':'7','kind':'history','url':'https://example.org/7','visibility':'public'})
    write_json(root / 'checkpoint.json', {'candidate_results': {'7': {'history': {'state':'PARSED','malformed_count':0,'same_time_groups':0,
        'future_event_after_observed_at':False,'chronology_ok':True},
        'source_consistency_differences': [], 'fix_metric': {'state':'VALID_EVENT_TIME','elapsed_calendar_days':1}}}})
    write_jsonl(root / 'corpus.jsonl', corpus)
    original = root / config['phase05_dir']; original.mkdir(parents=True)
    for split in ('dev','test','challenge'):
        write_jsonl(original / (split+'.questions.jsonl'), [{'qid':'original','question':'Recorded status of bug 1?', 'scope':{}}] if split == 'dev' else [])
        write_jsonl(original / (split+'.gold.jsonl'), [{'qid':'original','secret_gold':'not used'}])
    (original.parent/'review_queue.csv').write_text('fixture immutable source reviews\n')
    write_json(original / 'manifest.json', {'state':'FROZEN_HUMAN_SIGNED','id':'original',
        'sha256': {p.name:file_hash(p) for p in original.glob('*.jsonl')}})
    write_jsonl(root / 'natural.jsonl', [{'qid':'natural','question':'Recorded status of bug 2?', 'bug_ids':['2']}])
    representative = next(str(i) for i in range(6,21) if str(i) != '7')
    old = [{'qid':'old-field','family':'F1','question':'In the metadata archive, what is the recorded status for bug '+representative+'?',
            'bug_ids':[representative], 'gold':{'type':'string','value':db.execute('select snapshot_status from bugs where bug_id=?',[representative]).fetchone()[0]},
            'evidence':[{'id':'m'+representative}], 'scope':{}}]
    universe = sorted(str(i) for i in range(1,21) if str(i)!='5' and partition(317,str(i))=='dev')
    old.append({'qid':'old-count','family':'F3','question':'Within the original dev population, how many printing bugs were recorded?',
        'bug_ids':[representative], 'gold':{'type':'integer','value':len(universe)}, 'evidence':[],
        'scope':{'partition':'dev','population_hash':digest(universe),'denominator':len(universe),'filter':{'component':'Printing'}}})
    old.append({'qid':'old-duration','family':'F2','question':'Using verified API history for bug 7, how many calendar hours elapsed before its first recorded FIXED transition?',
        'bug_ids':['7'],'gold':{'type':'calendar_duration','seconds':86400,'hours':24},'evidence':[{'id':'m7'},{'id':'h7'}],'scope':{}})
    write_jsonl(root / 'selected.jsonl', old)
    write_json(root/'expanded_manifest.json',{'hashes':{'selected.jsonl':file_hash(root/'selected.jsonl')}})
    write_json(root/'natural_manifest.json',{'sha256':file_hash(root/'natural.jsonl')})
    db.close()
    (root / '.env').write_text('LLM_API_KEY=TOKEN_fixture_493\n')
    write_json(root/'base_manifest.json',{'state':'COMPLETE','artifacts':{'canonical.duckdb':{'sha256':file_hash(root/'base.duckdb')}}})
    write_json(root/'api_summary.json',{'state':'COMPLETE','artifacts':{'api_enrichment.duckdb':{'sha256':file_hash(root/'api.duckdb')}}})
    write_json(root/'corpus_manifest.json',{'state':'COMPLETE','sha256':file_hash(root/'corpus.jsonl')})
    write_json(root/'llm.json',read_config(ROOT/'configs/llm.yaml'))
    write_json(root/'config.json',config)
    return config


class GenerationTests(unittest.TestCase):
    def test_real_cli_plan_prepare_budget_resume_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); fixture(root)
            actual_embeddings=v3.embeddings
            calls=[]
            def provider(*args,**kwargs):
                p=DescriptionProvider(kwargs['max_requests']);calls.append(p);return p
            def embed(source,out,embedder=None):
                return actual_embeddings(source,out,Encoder())
            base=['v3','--config',str(root/'config.json'),'--resume']
            with patch.object(v3,'ROOT',root), patch.object(v3.subprocess,'check_output',return_value='fixture-code\n'), \
                 patch.object(v3,'create_provider',side_effect=provider),patch.object(v3,'embeddings',side_effect=embed), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                with patch('sys.argv',base+['--dry-run']):
                    v3.main()
                self.assertIn('"network_calls": 0',output.getvalue())
                self.assertEqual(calls,[])
                with patch('sys.argv',base+['--prepare']):
                    v3.main()
                with patch('sys.argv',base+['--enable-llm','--max-requests','2']):
                    with self.assertRaises(SystemExit) as exit:
                        v3.main()
                    self.assertEqual(exit.exception.code,2)
                # A crash marker and partial final JSON record simulate interruption.
                latest=json.loads((root/'outputs/benchmark/v3/LATEST_RUN.json').read_text())
                run=root/'outputs/benchmark/v3'/latest['run']
                manifest=json.loads((run/'manifest.json').read_text())
                write_json(run/'.running.json',{'identity_hash':run.name.removeprefix('run-')})
                with (run/'descriptions.jsonl').open('ab') as handle:handle.write(b'{"unfinished":')
                with patch('sys.argv',base+['--enable-llm','--max-requests','10']):
                    v3.main()
                self.assertEqual(sum(p.calls for p in calls),4)
                self.assertEqual(json.loads((run/'summary.json').read_text())['state'],'DRAFT_READY_FOR_SPOTCHECK')
                self.assertFalse((run/'.running.json').exists())

    def test_generation_resume_validation_privacy_and_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = fixture(root); llm = read_config(ROOT / 'configs/llm.yaml')
            original = (root / config['phase05_dir']).parent
            before = {str(p):file_hash(p) for p in original.rglob('*') if p.is_file()}
            out = root / config['output_root'] / 'fixture'
            first = DescriptionProvider(budget=2)
            partial = generate(config,llm,root,out,provider=first,embedder=Encoder())
            self.assertEqual(partial['state'], 'PARTIAL')
            second = DescriptionProvider()
            done = generate(config,llm,root,out,provider=second,resume=True,embedder=Encoder())
            self.assertEqual(done['state'], 'DRAFT_READY_FOR_SPOTCHECK')
            self.assertEqual(first.calls + second.calls, 4)
            again = DescriptionProvider()
            generate(config,llm,root,out,provider=again,resume=True,embedder=Encoder())
            self.assertEqual(again.calls, 0)
            self.assertNotIn('PRIVATE_BODY_SHOULD_NEVER_LEAVE', ''.join(first.prompts + second.prompts))
            self.assertNotIn('TOKEN_fixture_493', ''.join(first.prompts + second.prompts))
            for path in out.rglob('*'):
                if path.is_file(): self.assertNotIn(b'TOKEN_fixture_493', path.read_bytes())
            self.assertEqual(before, {str(p):file_hash(p) for p in original.rglob('*') if p.is_file()})
            # Explicitly synthetic decisions belong only to this temporary fixture.
            review = out/'review/spotcheck_v3.csv'
            with review.open(newline='') as handle:
                reader=csv.DictReader(handle); fields=reader.fieldnames; values=list(reader)
            families = {q['family'] for split in ('dev','test') for q in (json.loads(x) for x in (out/(split+'.questions.jsonl')).read_text().splitlines())}
            self.assertTrue({'KI','MH','F6H'} <= families)
            with review.open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
                writer.writerows(dict(v,verdict='OK') for v in values)
            write_json(out/'config_snapshot.json', {'dataset':config})
            write_json(out/'manifest.json',{'state':'DRAFT_READY_FOR_SPOTCHECK','identity':{'fixture':True}})
            write_json(out/'inputs_verified.json',{'base.duckdb':file_hash(root/'base.duckdb')})
            self.assertEqual(validate_run(out,root)['state'],'PASS')
            sealed=freeze(out)
            self.assertEqual(sealed['state'],'FROZEN_HUMAN_SPOTCHECKED')
            self.assertEqual(before, {str(p):file_hash(p) for p in original.rglob('*') if p.is_file()})

    def test_independent_gold_and_evidence_tampering_are_rejected(self):
        from bugzilla_qa.benchmark.v3 import candidate, copy_v2
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root);source=Source(config,root)
            try:
                root_id='9'
                value=source.field(root_id,'status')
                item=candidate(source,'F1','Recorded status?', 'string',value,root_id,['m9'],
                               {'kind':'field','root':root_id,'field':'status'})
                verify_candidate(source,item,set())
                item['gold']['answer']='MADE_UP'
                with self.assertRaises(ValueError):verify_candidate(source,item,set())
                item['gold']['answer']=value
                item['gold']['evidence_record_ids']=['m11']
                item['question']['provenance']['evidence_source_hashes']={'m11':'mh11'}
                with self.assertRaises(ValueError):verify_candidate(source,item,set())
                item['gold']['evidence_record_ids']=['c3']  # Private comment never entered the corpus.
                with self.assertRaises(ValueError):verify_candidate(source,item,set())
                self.assertEqual(source.f2('7')['seconds'],86400)
                source.history['7']['history']['future_event_after_observed_at']=True
                self.assertIsNone(source.f2('7'))
                imported,_=copy_v2(source,set())
                count=next(x for x in imported if x['question']['family']=='F3')
                verify_candidate(source,count,set())
                count['oracle']['scope']['denominator']+=1
                with self.assertRaises(ValueError):verify_candidate(source,count,set())
            finally:source.close()

    def test_overlength_summary_roots_do_not_consume_api_budget(self):
        class ShortEncoder(Encoder):
            max_seq_length=3
            @staticmethod
            def tokenizer(texts,**kwargs):return {'length':[len(t.split())+2 for t in texts]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root);llm=read_config(ROOT/'configs/llm.yaml')
            provider=DescriptionProvider()
            report=generate(config,llm,root,root/config['output_root']/'short',provider=provider,embedder=ShortEncoder())
            self.assertEqual(provider.calls,0)
            self.assertEqual(report['KI_summary_overlong_excluded'],20)
            self.assertEqual(report['shortfalls']['KI'],8)


if __name__ == '__main__': unittest.main()

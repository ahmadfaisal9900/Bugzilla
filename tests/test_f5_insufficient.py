"""Small synthetic tests for human-reviewed F5 insufficient-evidence answers."""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811'
sys.path.insert(0, str(ROOT / 'src'))
from bugzilla_qa.benchmark import phase05
from bugzilla_qa.evaluation import scoring
from bugzilla_qa.methods.contract import make_answer

spec = importlib.util.spec_from_file_location('review_server_fixture', UI / 'review_server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def absence():
    return {'type': 'unanswerable', 'value': phase05.UNKNOWN,
            'missing_evidence': phase05.F5_MISSING_RATIONALE, 'evidence_ids': ['comment-1']}


def item():
    return {'qid':'fixture', 'family':'F5', 'evidence':[{'id':'comment-1'}],
            'gold':{'type':'supported_explanation','claims':[{'evidence_id':'comment-1','text':'candidate'}]}}


def review(gold=None):
    return {'decision':'CORRECT','reviewer':'Fixture reviewer','reviewed_at_utc':'2026-11-02T00:00:00Z',
            'source_checked':'YES','rationale_present':'NO','corrected_gold_json':json.dumps(gold or absence())}


class F5InsufficientTests(unittest.TestCase):
    def test_existing_run_compatibility_requires_unchanged_generation_source(self):
        m={'identity':{'version':phase05.VERSION,'code_hash':'a1499fcc8a624186b1e6e712777fb322419e9ca55d4a09d21303a21803287b83'}}
        run=Path('run-65c5be3381f66811')
        self.assertTrue(phase05._is_compatible_review_amendment(m,run))
        self.assertFalse(phase05._is_compatible_review_amendment(m,Path('different-run')))
        source=Path(phase05.__file__).read_text()
        before='FAMILIES = tuple("F" + str(i) for i in range(1, 7))'
        self.assertIn(before,source)
        with tempfile.TemporaryDirectory(prefix='phase05-code-check-') as tmp:
            path=Path(tmp)/'changed_phase05.py';path.write_text(source.replace(before,before.replace('1, 7','1, 6'),1))
            changed_spec=importlib.util.spec_from_file_location('changed_phase05_fixture',path)
            changed=importlib.util.module_from_spec(changed_spec);changed_spec.loader.exec_module(changed)
            self.assertFalse(changed._is_compatible_review_amendment(m,run))
            changed_review=source.replace('row.get("rationale_present") == "NO"', 'row.get("rationale_present") == "YES"', 1)
            self.assertNotEqual(changed_review,source)
            path.write_text(changed_review)
            changed_spec=importlib.util.spec_from_file_location('changed_review_fixture',path)
            changed=importlib.util.module_from_spec(changed_spec);changed_spec.loader.exec_module(changed)
            self.assertFalse(changed._is_compatible_review_amendment(m,run))

    def test_freeze_gold_requires_explicit_source_review_and_exact_evidence(self):
        self.assertEqual(phase05.approved_gold(item(),review()),absence())
        for key,value in [('source_checked','NO'),('rationale_present','YES'),('reviewer',''),('decision','APPROVE')]:
            r=review();r[key]=value
            with self.assertRaises(AssertionError):phase05.approved_gold(item(),r)
        for key,value in [('evidence_ids',['wrong']),('evidence_ids',[]),('value','no answer exists anywhere'),('missing_evidence','')]:
            g=absence();g[key]=value
            with self.assertRaises(AssertionError):phase05.approved_gold(item(),review(g))
        r=review();r['corrected_gold_json']=json.dumps({'type':'supported_explanation','claims':[{'evidence_id':'comment-1','text':'supported reason'}]});r['rationale_present']='YES'
        self.assertEqual(phase05.approved_gold(item(),r)['type'],'supported_explanation')

    def test_f5_abstention_needs_human_context_check(self):
        q={'qid':'fixture','family':'F5','gold':absence()}
        ans=make_answer('fixture','fixture-method','Cannot establish it, but perhaps an invented cause.',abstained=True,value=None)
        self.assertEqual(scoring.score(q,ans)['verdict'],scoring.NEEDS_HUMAN)
        self.assertEqual(scoring.score(q,make_answer('fixture','fixture-method','A cause',value='A cause'))['verdict'],scoring.INCORRECT)
        q['family']='F6'
        self.assertEqual(scoring.score(q,ans)['verdict'],scoring.CORRECT)

    def test_review_server_requires_explicit_absence_confirmation(self):
        fields=['qid','decision','required','family','typed_candidate_gold_json','source_evidence_compact_json']+sorted(server.MUTABLE-{'decision'})
        row={k:'' for k in fields};row.update({'qid':'fixture','decision':'PENDING','required':'YES','family':'F5',
             'typed_candidate_gold_json':json.dumps(item()['gold']),
             'source_evidence_compact_json':json.dumps([{'evidence_id':'comment-1'}])})
        payload={'qid':'fixture','decision':'CORRECT','reviewer':'Fixture reviewer','source_checked':True,
                 'rationale_present':False,'absence_confirmed':True,'corrected_gold_json':json.dumps(absence())}
        with tempfile.TemporaryDirectory(prefix='f5-insufficient-') as tmp:
            path=Path(tmp)/'signoff_queue.csv'
            with path.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerow(row)
            for changes in ({'absence_confirmed':False},{'source_checked':False},{'rationale_present':True},
                            {'corrected_gold_json':json.dumps({**absence(),'evidence_ids':['wrong']})}):
                with self.assertRaises(ValueError): server.update(path,{**payload,**changes})
            updated,done,total=server.update(path,payload)
            self.assertEqual((done,total),(1,1));self.assertEqual(updated['rationale_present'],'NO')
            self.assertEqual(updated['typed_candidate_gold_json'],row['typed_candidate_gold_json'])
            self.assertTrue((Path(tmp)/'signoff_queue.before_review.csv').exists())
            shutil.copy2(UI/'review_server.py',Path(tmp)/'review_server.py')
            (Path(tmp)/'signoff.html').write_text('fixture')
            check=subprocess.run([sys.executable,str(Path(tmp)/'review_server.py'),'--check'],text=True,capture_output=True)
            self.assertEqual(check.returncode,0,check.stderr)
            self.assertIn('Review-field consistency: passed',check.stdout)

    @unittest.skipUnless(shutil.which('node'),'Node is needed only for this browser behavior fixture')
    def test_browser_explicit_absence_acceptance_and_existing_paths(self):
        html=(UI/'signoff.html').read_text();js=html.split('<script>',1)[1].split('</script>',1)[0]
        stub=r'''const assert=require('assert');const nodes={};function elem(){return {value:'',checked:false,disabled:false,textContent:'',style:{},children:[],classList:{add(){},remove(){},toggle(){}},addEventListener(){},replaceChildren(){this.children=[]},append(x){this.children.push(x)},click(){}}};global.document={getElementById(id){return nodes[id]||(nodes[id]=elem())},createElement(){return elem()}};global.window={addEventListener(){}};global.localStorage={getItem(){return ''},setItem(){}};global.location={protocol:'file:'};nodes.filter=elem();nodes.filter.value='pending';'''
        checks=r'''const r={qid:'fixture',family:'F5',decision:'PENDING',required:'YES',record_kind:'BENCHMARK_CANDIDATE',question:'Firefox issue 1',typed_candidate_gold_json:JSON.stringify({type:'supported_explanation',claims:[{evidence_id:'comment-1',text:'original fragment'}]}),packet_sha256:'p1',source_evidence_compact_json:JSON.stringify([{evidence_id:'comment-1'}])};const s={status:'ESCALATE',answer:null,reason:'Review the complete comment.',evidence_id:'comment-1',packet_sha256:'p1'};setData({fields:[],rows:[r],suggestions:{fixture:s}},true);assert.equal(nodes.approve.disabled,false);assert(nodes.answer.textContent.includes('cannot be established'));assert(nodes.rationaleLabel.textContent.includes('complete cited comment'));nodes.reviewer.value='Fixture reviewer';assert.throws(()=>makePayload('APPROVE'),/source/);nodes.checked.checked=true;assert.throws(()=>makePayload('APPROVE'),/complete cited comment/);nodes.rationale.checked=true;const p=makePayload('APPROVE');assert.equal(p.decision,'CORRECT');assert.equal(p.rationale_present,false);assert.equal(p.absence_confirmed,true);assert.equal(JSON.parse(p.corrected_gold_json).type,'unanswerable');assert.deepEqual(JSON.parse(p.corrected_gold_json).evidence_ids,['comment-1']);assert.equal(r.decision,'PENDING');nodes.correct.onclick();assert.equal(nodes.rationale.checked,false);assert(nodes.rationaleLabel.textContent.includes('supports this explanation'));s.status='CORRECT';s.answer='A supported rewrite.';render();nodes.checked.checked=true;nodes.rationale.checked=true;const c=makePayload('APPROVE');assert.equal(c.decision,'CORRECT');assert.equal(c.rationale_present,true);assert.equal(JSON.parse(c.corrected_gold_json).claims[0].text,'A supported rewrite.');r.decision='CORRECT';r.corrected_gold_json=p.corrected_gold_json;r.source_checked='YES';r.rationale_present='NO';render();assert(nodes.approve.disabled);assert(nodes.rationale.checked);assert(nodes.rationaleLabel.textContent.includes('complete cited comment'));assert.throws(()=>makePayload('APPROVE'),/already saved/);'''
        with tempfile.TemporaryDirectory(prefix='f5-browser-') as tmp:
            path=Path(tmp)/'check.js';path.write_text(stub+'\n'+js+'\n'+checks)
            result=subprocess.run(['node',str(path)],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__': unittest.main()

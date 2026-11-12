import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bugzilla_qa.benchmark.v3_freeze import freeze, sha


class FreezeTests(unittest.TestCase):
    def test_requires_review_and_drops_rejected_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / 'review').mkdir()
            qs = [{'qid': family, 'family': family, 'cluster_id': family} for family in ('KI', 'MH', 'F6H')]
            for split in ('dev', 'test'):
                content = qs if split == 'dev' else []
                for name, data in ((split + '.questions.jsonl', content),
                                   (split + '.gold.jsonl', [{'qid': x['qid']} for x in content]),
                                   ('qrels_v3_' + split + '.jsonl', [{'qid': x['qid']} for x in content])):
                    (run / name).write_text(''.join(json.dumps(x) + '\n' for x in data))
            (run / 'config_snapshot.json').write_text('{}')
            (run / 'oracles.jsonl').write_text('')
            (run / 'summary.json').write_text(json.dumps({'state':'DRAFT_READY_FOR_SPOTCHECK','limited':False}))
            (run / 'manifest.json').write_text(json.dumps({'state':'DRAFT_READY_FOR_SPOTCHECK','identity':{'fixture':True}}))
            (run / 'inputs_verified.json').write_text('{}')
            names = [split + '.' + kind + '.jsonl' for split in ('dev', 'test') for kind in ('questions', 'gold')]
            names += ['qrels_v3_dev.jsonl', 'qrels_v3_test.jsonl']
            (run / 'validation_report.json').write_text(json.dumps({'state': 'PASS', 'independent_gold_checked': True, 'limited': False, 'generation_complete': True,
                'sha256': {n: sha(run / n) for n in names}}))
            (run / 'validation_recheck.json').write_text(json.dumps({'state':'PASS','independent_gold_checked':True,
                'sha256':{n:sha(run/n) for n in names+['oracles.jsonl','config_snapshot.json']}}))
            review = run / 'review/spotcheck_v3.csv'
            def write(decision):
                with review.open('w', newline='') as handle:
                    writer = csv.DictWriter(handle, fieldnames=['qid','question','gold','source_summary','verdict']); writer.writeheader()
                    for q in qs: writer.writerow({'qid': q['qid'], 'question':q['qid'], 'gold':'{}', 'source_summary':'fixture', 'verdict': decision if q['qid'] == 'KI' else 'OK'})
            write('')
            immutable = [{'qid':q['qid'],'question':q['qid'],'gold':'{}','source_summary':'fixture'} for q in qs]
            report=json.loads((run/'validation_report.json').read_text())
            report['review_immutable_sha256']=hashlib.sha256(json.dumps(immutable,sort_keys=True).encode()).hexdigest()
            (run/'validation_report.json').write_text(json.dumps(report))
            with self.assertRaises(RuntimeError): freeze(run)
            write('WRONG')
            original=review.read_text()
            review.write_text(original.replace('fixture','tampered'))
            with self.assertRaisesRegex(RuntimeError,'source summary changed'):freeze(run)
            review.write_text(original)
            result = freeze(run)
            self.assertTrue(result['warning'])
            saved = (Path(result['output']) / 'dev.questions.jsonl').read_text()
            self.assertNotIn('"KI"', saved)
            with self.assertRaises(RuntimeError): freeze(run)
            self.assertEqual(freeze(run, resume=True)['state'], 'ALREADY_FROZEN_VERIFIED')
            (run/'FROZEN').unlink()  # Interrupted after promotion, before pointer write.
            self.assertEqual(freeze(run,resume=True)['state'],'ALREADY_FROZEN_VERIFIED')
            (run / 'config_snapshot.json').write_text('{"changed": true}')
            with self.assertRaises(RuntimeError): freeze(run, resume=True)


if __name__ == '__main__': unittest.main()

import csv
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
            names = [split + '.' + kind + '.jsonl' for split in ('dev', 'test') for kind in ('questions', 'gold')]
            names += ['qrels_v3_dev.jsonl', 'qrels_v3_test.jsonl']
            (run / 'validation_report.json').write_text(json.dumps({'state': 'PASS', 'independent_gold_checked': True,
                'sha256': {n: sha(run / n) for n in names}}))
            review = run / 'review/spotcheck_v3.csv'
            def write(decision):
                with review.open('w', newline='') as handle:
                    writer = csv.DictWriter(handle, fieldnames=['qid', 'verdict']); writer.writeheader()
                    for q in qs: writer.writerow({'qid': q['qid'], 'verdict': decision if q['qid'] == 'KI' else 'OK'})
            write('')
            with self.assertRaises(RuntimeError): freeze(run)
            write('WRONG')
            result = freeze(run)
            self.assertTrue(result['warning'])
            saved = (Path(result['output']) / 'dev.questions.jsonl').read_text()
            self.assertNotIn('"KI"', saved)
            with self.assertRaises(RuntimeError): freeze(run)
            self.assertEqual(freeze(run, resume=True)['state'], 'ALREADY_FROZEN_VERIFIED')
            (run / 'config_snapshot.json').write_text('{"changed": true}')
            with self.assertRaises(RuntimeError): freeze(run, resume=True)


if __name__ == '__main__': unittest.main()

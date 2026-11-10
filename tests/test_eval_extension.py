import json
import tempfile
import unittest
from pathlib import Path

from bugzilla_qa.eval_extension.retrieval import (build_lexical, chunks, lexical_search,
                                                   make_chunks, retrieval_metrics, rrf)


class RetrievalExtensionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index = Path(self.tmp.name) / 'index.sqlite'
        self.records = [dict(record_id='r1', bug_id='123', kind='metadata', text='Bug 123 printing failure',
                             url='https://example.org/123', source_hash='abc', visibility='public'),
                        dict(record_id='r2', bug_id='456', kind='comment', text='Bug 456 printing failure',
                             url='https://example.org/456', source_hash='def', visibility='public')]

    def tearDown(self):
        self.tmp.cleanup()

    def test_privacy_and_redaction(self):
        record = dict(self.records[0], text='user@example.org @user', visibility='unknown')
        with self.assertRaises(ValueError):
            list(make_chunks(record))
        record['visibility'] = 'public'
        self.assertNotIn('user@example.org', list(make_chunks(record))[0]['text'])

    def test_chunks_preserve_tail(self):
        self.assertEqual(list(chunks('a b c d e', 3, 1)), ['a b c', 'c d e'])

    def test_lexical_filter_and_no_match(self):
        docs = [c for r in self.records for c in make_chunks(r)]
        self.assertEqual(build_lexical(self.index, docs, 'test'), 2)
        hits = lexical_search(self.index, 'bug 123 printing', 5)
        self.assertEqual([x['bug_id'] for x in hits], ['123'])
        self.assertEqual(lexical_search(self.index, 'zzznomatch'), [])

    def test_rrf_and_metrics(self):
        docs = [next(make_chunks(r)) for r in self.records]
        a, b = dict(docs[0], score=1), dict(docs[1], score=2)
        self.assertEqual(rrf({'lexical': [a, b], 'dense': [b, a]})[0]['chunk_id'], 'r1:0')
        self.assertEqual(retrieval_metrics([a], {'r1'}, 'F1')['known_citation_recall'], 1)
        self.assertEqual(retrieval_metrics([a], {'r1'}, 'F3')['state'], 'NOT_APPLICABLE')


if __name__ == '__main__':
    unittest.main()

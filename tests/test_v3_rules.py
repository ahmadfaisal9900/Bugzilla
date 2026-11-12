import unittest

import duckdb
from bugzilla_qa.benchmark.v3_rules import ambiguity_set, cluster_split, valid_description


class V3RulesTests(unittest.TestCase):
    def test_20_bug_fixture_split_exclusions_and_similarity(self):
        db = duckdb.connect(':memory:')
        try:
            db.execute('CREATE TABLE bugs (bug_id VARCHAR, product VARCHAR)')
            db.executemany('INSERT INTO bugs VALUES (?, ?)', [(str(i), 'Firefox') for i in range(20)])
            ids = [r[0] for r in db.execute('SELECT bug_id FROM bugs ORDER BY CAST(bug_id AS INTEGER)').fetchall()]
            excluded = {'1', '2'}
            assigned = {bug: cluster_split(317, bug) for bug in ids if bug not in excluded}
            self.assertEqual(len(assigned), 18)
            self.assertEqual(assigned, {bug: cluster_split(317, bug) for bug in ids if bug not in excluded})
            self.assertEqual(set(assigned.values()), {'dev', 'test'})
        finally:
            db.close()
        vectors = {'1': [1.0, 0.0], '2': [0.0, 1.0], '3': [0.99, 0.01], '4': [-1.0, 0.0]}
        self.assertEqual(ambiguity_set('1', [('2', '1')], vectors), ['1', '2', '3'])
        self.assertIsNone(ambiguity_set('1', [('2', '1'), ('1', '4')], vectors, max_alternates=2))

    def test_copy_and_bug_id_filters(self):
        summary = 'Tabs unexpectedly crash when a user prints a page'
        self.assertFalse(valid_description('A user reports that tabs unexpectedly crash when a user prints a page', summary))
        self.assertFalse(valid_description('I found issue #123', summary))
        self.assertTrue(valid_description('Printing a page makes the browser exit unexpectedly', summary))


if __name__ == '__main__': unittest.main()

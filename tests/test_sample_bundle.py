"""Tiny offline handoff fixtures; never open the real corpus."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

import duckdb

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/export_sample_bundle.py'
spec = importlib.util.spec_from_file_location('sample_bundle', SCRIPT)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class SampleBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sample-bundle-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'docs').mkdir()
        shutil.copy2(SCRIPT.parents[1] / 'docs/SAMPLE_DATA_HANDOFF.md', self.root / 'docs/SAMPLE_DATA_HANDOFF.md')
        base, api = self.root / 'base', self.root / 'api'
        base.mkdir(); api.mkdir()
        db = duckdb.connect(str(base / 'canonical.duckdb'))
        db.execute("CREATE TABLE sample_membership AS SELECT * FROM (VALUES ('1',317,'a'),('2',317,'b')) t(bug_id,seed,stratum)")
        db.execute("CREATE TABLE bugs AS SELECT * FROM (VALUES ('1','Firefox'),('2','Firefox'),('3','Firefox')) t(bug_id,product)")
        db.execute("CREATE TABLE comments AS SELECT * FROM (VALUES ('1','public fixture',false),('1',NULL,NULL),('3','outside sample',false)) t(bug_id,body,private_flag)")
        db.execute("CREATE TABLE bug_links AS SELECT '1' AS bug_id, '3' AS target_bug_id, true AS target_in_corpus")
        for table in ('field_changes','quality_records'):
            db.execute(f"CREATE TABLE {table} AS SELECT '1'::VARCHAR AS bug_id WHERE false")
        for table in ('documents','source_records','fix_metrics'):
            db.execute(f'CREATE TABLE {table} AS SELECT bug_id FROM bugs')
        for table in ('provenance','run_manifest'):
            db.execute(f"CREATE TABLE {table} AS SELECT 'fixture provenance' AS info")
        db.close()
        adb = duckdb.connect(str(api / 'api_enrichment.duckdb'))
        adb.execute("CREATE TABLE field_changes AS SELECT * FROM (VALUES (1,'status','NEW','RESOLVED'),(1,'resolution','','FIXED')) t(bug_id,field_name,old_value,new_value)")
        for table in ('api_comments','api_bug_refresh','api_link_changes'):
            adb.execute(f'CREATE TABLE {table} (row_json JSON)')
        adb.close()
        bundle.write(base / 'manifest.json', {'state':'COMPLETE','identity_hash':'fixture-base',
          'artifacts':{'canonical.duckdb':{'bytes':(base/'canonical.duckdb').stat().st_size,'sha256':bundle.sha(base/'canonical.duckdb')}}})
        bundle.write(base / 'sample_manifest.json', {'seed':317,'product':'Firefox','members':[{'bug_id':'1'},{'bug_id':'2'}]})
        bundle.write(api / 'summary.json', {'state':'COMPLETE','candidate_count':1,'successful_histories':1,'field_change_rows':2,
          'api_response_manifest':[{'bug_id':1,'endpoint':'history','url':'https://example.invalid/history','cache_path':'PRIVATE-PATH-NOT-FOR-EXPORT'}],
          'artifacts':{'api_enrichment.duckdb':{'size_bytes':(api/'api_enrichment.duckdb').stat().st_size,'sha256':bundle.sha(api/'api_enrichment.duckdb')}}})
        bundle.write(self.root / 'pins.json', {'base_run':'base','phase04_run':'api','base_identity':'fixture-base',
          'base_counts':{'sample_membership':2},'sample_seed':317,'phase04_summary_sha256':bundle.sha(api/'summary.json')})
        self.args = SimpleNamespace(root=self.root,source_pins=Path('pins.json'),output=self.root/'out',limit=None,resume=False,dry_run=False,memory_limit='128MB')

    def export(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return bundle.export(self.args)

    def test_subset_and_byte_identical_overlay_and_resume(self):
        base_hash = bundle.sha(self.root/'base/canonical.duckdb')
        result = self.export()
        self.assertEqual(result['counts']['bugs'],2)
        self.assertEqual(result['counts']['comments'],2)
        db = duckdb.connect(str(self.args.output/'sample.duckdb'),read_only=True)
        self.assertEqual(db.execute('SELECT target_bug_id FROM bug_links').fetchall(),[('3',)])
        self.assertEqual(db.execute("SELECT count(*) FROM bugs WHERE bug_id='3'").fetchone()[0],0)
        self.assertEqual(db.execute("SELECT count(*) FROM bugs WHERE bug_id='2'").fetchone()[0],1)
        self.assertEqual(db.execute("SELECT count(*) FROM comments WHERE bug_id='2'").fetchone()[0],0)
        db.close()
        self.assertEqual(bundle.sha(self.root/'api/api_enrichment.duckdb'),bundle.sha(self.args.output/'api_enrichment.duckdb'))
        self.assertNotIn('PRIVATE-PATH', (self.args.output/'history_response_manifest.json').read_text())
        with tarfile.open(result['archive']) as tar:
            self.assertEqual(len(tar.getmembers()),7)
        self.args.resume = True
        self.assertEqual(result['archive_sha256'],self.export()['archive_sha256'])
        self.assertEqual(base_hash,bundle.sha(self.root/'base/canonical.duckdb'))
        # Crash after archive creation but before summary commit also resumes.
        (self.args.output/'summary.json').unlink()
        self.assertEqual(result['archive_sha256'],self.export()['archive_sha256'])

    def test_dry_run_creates_no_output_and_prefix_is_labeled(self):
        self.args.dry_run=True
        self.assertEqual(self.export()['state'],'DRY_RUN')
        self.assertFalse(self.args.output.exists())
        self.args.dry_run=False; self.args.limit=1
        result=self.export()
        self.assertTrue(result['prefix_only'])
        self.assertEqual(result['counts']['bugs'],1)

    def test_changed_identity_and_private_body_stop_export(self):
        # Complete subset cannot be silently reused with another limit.
        self.export(); self.args.resume=True; self.args.limit=1
        with self.assertRaisesRegex(ValueError,'identity'):self.export()
        # Bad privacy in an included comment blocks a new archive.
        self.args.output=self.root/'unsafe'; self.args.limit=None
        db=duckdb.connect(str(self.root/'base/canonical.duckdb'))
        db.execute("UPDATE comments SET private_flag=NULL WHERE bug_id='1'"); db.close()
        # Keep this fixture's declared size accurate; production source runs are immutable.
        m=bundle.read(self.root/'base/manifest.json')
        m['artifacts']['canonical.duckdb']['bytes']=(self.root/'base/canonical.duckdb').stat().st_size
        bundle.write(self.root/'base/manifest.json',m)
        with self.assertRaisesRegex(ValueError,'privacy'):self.export()
        self.assertFalse(self.args.output.with_suffix('.tar.gz').exists())

    def test_partial_table_checkpoint_resume(self):
        self.args.output.mkdir()
        identity=bundle.plan(self.args)[8]
        bundle.write(self.args.output/'checkpoint.json', {'state':'STARTED','identity':identity})
        db=duckdb.connect(str(self.args.output/'sample.duckdb'))
        db.execute("CREATE TABLE sample_membership AS SELECT * FROM (VALUES ('1',317,'a'),('2',317,'b')) t(bug_id,seed,stratum)")
        db.close(); self.args.resume=True
        self.assertEqual(self.export()['counts']['bugs'],2)


if __name__ == '__main__':
    unittest.main()

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from bugzilla_qa.llm.provider import GeminiProvider, MockProvider, read_config, ROOT

SCHEMA = {'type': 'object', 'properties': {'description': {'type': 'string'}}, 'required': ['description'], 'additionalProperties': False}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = read_config(ROOT / 'configs/llm.yaml')

    def test_dry_run_is_zero_calls_and_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p = GeminiProvider(self.config, root=d)
            self.assertEqual(p.generate_json('hello', SCHEMA)['state'], 'DRY_RUN')
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_mock_validation(self):
        p = MockProvider({'description': 'A display problem'})
        self.assertEqual(p.generate_json('unused', SCHEMA)['value']['description'], 'A display problem')
        self.assertEqual(p.calls, 1)

    def test_durable_cache_and_redacted_ledger(self):
        class Models:
            calls = 0
            def generate_content(self, **kwargs):
                self.calls += 1
                return types.SimpleNamespace(text='{"description":"A display problem"}', usage_metadata=None)
        models = Models()
        with tempfile.TemporaryDirectory() as d:
            client = types.SimpleNamespace(models=models)
            p = GeminiProvider(self.config, root=d, enable_llm=True, max_requests=1, client=client)
            self.assertEqual(p.generate_json('sensitive prompt', SCHEMA)['state'], 'SUCCESS')
            q = GeminiProvider(self.config, root=d, enable_llm=True, max_requests=1, client=client)
            self.assertEqual(q.generate_json('sensitive prompt', SCHEMA)['state'], 'CACHE_HIT')
            self.assertEqual(models.calls, 1)
            ledger = (Path(d) / self.config['ledger']).read_text()
            self.assertNotIn('sensitive prompt', ledger)
            self.assertEqual(len([x for x in ledger.splitlines() if json.loads(x)['status'] == 'REQUEST_STARTED']), 1)

    def test_retry_consumes_request_budget_and_hides_exception(self):
        class RateLimited(Exception):
            code = 429
        class Models:
            calls = 0
            def generate_content(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RateLimited('do not record this secret')
                return types.SimpleNamespace(text='{"description":"Recovered"}', usage_metadata=None)
        with tempfile.TemporaryDirectory() as d:
            models = Models()
            p = GeminiProvider(self.config, root=d, enable_llm=True, max_requests=2,
                               client=types.SimpleNamespace(models=models), sleep=lambda seconds: None)
            self.assertEqual(p.generate_json('prompt', SCHEMA)['value']['description'], 'Recovered')
            ledger = (Path(d) / self.config['ledger']).read_text()
            self.assertEqual(models.calls, 2)
            self.assertNotIn('do not record this secret', ledger)
            self.assertEqual(sum(json.loads(x)['status'] == 'REQUEST_STARTED' for x in ledger.splitlines()), 2)

    def test_env_secret_stays_out_of_outputs(self):
        secret = 'fixture_private_token_75c3'
        class Client:
            def __init__(self, api_key):
                self.assert_key = api_key
                self.models = self
            def generate_content(self, **kwargs):
                assert self.assert_key == secret
                return types.SimpleNamespace(text='{"description":"Safe"}', usage_metadata=None)
        with tempfile.TemporaryDirectory() as d:
            Path(d, '.env').write_text('LLM_API_KEY=' + secret + '\n')
            fake_google = types.ModuleType('google')
            fake_google.genai = types.SimpleNamespace(Client=Client)
            with patch.dict('sys.modules', {'google': fake_google}), patch.dict('os.environ', {}, clear=True):
                GeminiProvider(self.config, root=d, enable_llm=True).generate_json('safe prompt', SCHEMA)
            for file in Path(d, 'outputs').rglob('*'):
                if file.is_file():
                    self.assertNotIn(secret.encode(), file.read_bytes())


if __name__ == '__main__': unittest.main()

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from bugzilla_qa.llm.provider import create_provider, resolved_config, read_config, ROOT

SCHEMA={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}

class GroqTests(unittest.TestCase):
    def test_key_sdk_schema_cache_and_legacy_environment_isolation(self):
        calls=[]
        class Client:
            def __init__(self,**kwargs):
                self.chat=types.SimpleNamespace(completions=self)
                self.models=self
                assert kwargs['api_key']=='gsk_fixture_932'
                assert kwargs['max_retries']==0
            def create(self,**kwargs):
                calls.append(kwargs)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason='stop',message=types.SimpleNamespace(content='{"ok":true}'))],usage=types.SimpleNamespace(prompt_tokens=12,completion_tokens=5))
            def list(self):return types.SimpleNamespace(data=[types.SimpleNamespace(id='openai/gpt-oss-20b')])
        config=read_config(ROOT/'configs/llm.yaml')
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'GEMINI_AUX_MODEL':'stale-gemini'},clear=True),patch.dict('sys.modules',{'groq':types.SimpleNamespace(Groq=Client)}):
            Path(tmp,'.env').write_text('GROQ_API_KEY=gsk_fixture_932\nGROQ_AUX_MODEL=openai/gpt-oss-20b\nGEMINI_MODEL=old\n')
            self.assertEqual(resolved_config(config,tmp)['models']['aux']['id'],'openai/gpt-oss-20b')
            dry=create_provider(config,root=tmp)
            self.assertEqual(dry.generate_json('hello',SCHEMA)['state'],'DRY_RUN')
            self.assertFalse(Path(tmp,'outputs').exists())
            p=create_provider(config,root=tmp,enable_llm=True,max_requests=1)
            result=p.generate_json('hello',SCHEMA)
            self.assertEqual(result['input_tokens'],12)
            self.assertEqual(result['output_tokens'],5)
            self.assertTrue(calls[0]['response_format']['json_schema']['strict'])
            self.assertEqual(calls[0]['response_format']['json_schema']['schema'],SCHEMA)
            q=create_provider(config,root=tmp,enable_llm=True,max_requests=1)
            self.assertEqual(q.generate_json('hello',SCHEMA)['state'],'CACHE_HIT')
            self.assertEqual(len(calls),1)
            self.assertEqual(q.list_models()['value']['models'],['openai/gpt-oss-20b'])
            for f in Path(tmp,'outputs').rglob('*'):
                if f.is_file():self.assertNotIn(b'gsk_fixture_932',f.read_bytes())

    def test_retry_after_and_request_cap(self):
        class RateLimit(Exception):
            status_code=429
            code='rate_limit_exceeded'
            response=types.SimpleNamespace(headers={'retry-after':'9'})
        config=read_config(ROOT/'configs/llm.yaml')
        with tempfile.TemporaryDirectory() as tmp:
            p=create_provider(config,root=tmp,enable_llm=True,max_requests=2,client=object(),sleep=lambda t:waits.append(t))
            waits=[]
            with patch.object(p,'_request',side_effect=[RateLimit(),({'ok':True},1,1)]):
                self.assertTrue(p.generate_json('hello',SCHEMA)['value']['ok'])
            self.assertEqual(p.calls,2)
            self.assertEqual(waits,[9.0])

    def test_secret_prompt_refused_without_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'.env').write_text('GROQ_API_KEY=gsk_fixture_932\n')
            p=create_provider(read_config(ROOT/'configs/llm.yaml'),root=tmp,enable_llm=True)
            with self.assertRaisesRegex(RuntimeError,'credential'):p.generate_json('gsk_fixture_932',SCHEMA)
            self.assertEqual(p.calls,0)

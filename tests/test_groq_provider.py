import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from bugzilla_qa.llm.provider import (create_provider, resolved_config, read_config, ROOT,
    ProviderRateLimitError,rate_limit_details)

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
            self.assertEqual(calls[0]['tool_choice'],'none')
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

    def test_daily_token_limit_details_and_persistent_cooldown_allow_cache(self):
        class RateLimit(Exception):
            status_code=429
            body={'error':{'message':'Rate limit on tokens per day (TPD): Limit 200000, Used 194000, Requested 8000. Please try again in 1h2m3s. raw-secret-must-not-persist'}}
            response=types.SimpleNamespace(headers={'retry-after':'3723','x-ratelimit-remaining-tokens':'6000',
                'authorization':'Bearer do-not-record','x-ratelimit-reset-tokens':'1h2m3s'})
        config=read_config(ROOT/'configs/llm.yaml')
        for model in config['models'].values():model['rpm']=1000
        with tempfile.TemporaryDirectory() as tmp:
            p=create_provider(config,root=tmp,enable_llm=True,max_requests=3,client=object())
            with patch.object(p,'_request',side_effect=[({'ok':True},12,5),RateLimit()]) as request:
                p.generate_json('cached-success',SCHEMA)
                with self.assertRaises(ProviderRateLimitError) as caught:p.generate_json('fresh',SCHEMA)
                self.assertEqual(request.call_count,2)
            details=caught.exception.details
            self.assertEqual(details['quota'],'TPD');self.assertEqual(details['retry_after_seconds'],3723)
            self.assertEqual(details['requested'],8000);self.assertIn('resume_after_utc',details)
            q=create_provider(config,root=tmp,enable_llm=True,max_requests=1,client=object())
            with patch.object(q,'_request',side_effect=AssertionError('Cooldown must make zero calls')):
                self.assertEqual(q.generate_json('cached-success',SCHEMA)['state'],'CACHE_HIT')
                with self.assertRaises(ProviderRateLimitError):q.generate_json('fresh',SCHEMA)
            self.assertEqual(q.calls,0)
            for f in Path(tmp,'outputs').rglob('*.json*'):
                text=f.read_text()
                self.assertNotIn('raw-secret-must-not-persist',text);self.assertNotIn('Bearer do-not-record',text)

    def test_retry_after_message_and_http_date_parsing(self):
        import datetime as dt
        from email.utils import format_datetime
        exc=types.SimpleNamespace(body={'message':'Tokens per minute (TPM): Limit 8000, Used 7900, Requested 2000. Please try again in 2m3.5s.'},response=None)
        parsed=rate_limit_details(exc,'mock')
        self.assertEqual(parsed['quota'],'TPM');self.assertEqual(parsed['retry_after_seconds'],123.5)
        future=dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=900)
        exc.response=types.SimpleNamespace(headers={'retry-after':format_datetime(future,usegmt=True)})
        parsed=rate_limit_details(exc,'mock')
        self.assertTrue(898<parsed['retry_after_seconds']<=900)

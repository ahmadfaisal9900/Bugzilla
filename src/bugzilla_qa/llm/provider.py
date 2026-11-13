"""Opt-in Gemini/Groq JSON providers with durable budget, cache, and audit ledger.

The shared file lock serializes cooperating local processes. A provider response
can be charged before a crash and before caching; exact-once billing is impossible.
"""
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import random
import re
import shlex
import sqlite3
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jsonschema import validate, ValidationError

ROOT = Path(__file__).resolve().parents[3]
PACIFIC = ZoneInfo('America/Los_Angeles')
SECRET_KEYS = ('LLM_API_KEY', 'GROQ_API_KEY', 'LANGSMITH_API_KEY', 'LANGSMITH_KEY')


class InvalidJSONResponse(RuntimeError):
    """Allows the answering graph's single repair without retrying transport errors."""


class ProviderRateLimitError(RuntimeError):
    def __init__(self, details):
        self.details=details
        fields=['Provider rate limit', 'model='+details['model'], 'quota='+details.get('quota','UNKNOWN')]
        for key in ('retry_after_seconds','resume_after_utc','limit','used','requested'):
            if key in details:fields.append(key+'='+str(details[key]))
        super().__init__('; '.join(fields))


def rate_limit_details(exc, model, secrets=()):
    """Retain only quota metadata, never raw responses, failed text or auth headers."""
    now=dt.datetime.now(dt.timezone.utc)
    headers=getattr(getattr(exc,'response',None),'headers',{}) or {}
    allowed=['retry-after']+['x-ratelimit-'+k for k in (
        'limit-requests','remaining-requests','reset-requests',
        'limit-tokens','remaining-tokens','reset-tokens')]
    safe={}
    for key in allowed:
        value=str(headers.get(key,''))[:160]
        for secret in secrets:
            if secret:value=value.replace(secret,'[redacted]')
        if value:safe[key]=value
    result={'model':model,'http_status':429,'observed_at_utc':now.isoformat(),'quota':'UNKNOWN','headers':safe}
    raw=getattr(exc,'body',{})
    if isinstance(raw,dict):raw=raw.get('error',raw)
    message=raw.get('message','') if isinstance(raw,dict) else ''
    if not message:message=getattr(exc,'message','')
    if not isinstance(message,str):message=''
    for quota,phrase in [('TPD','tokens per day'),('TPM','tokens per minute'),
                         ('RPD','requests per day'),('RPM','requests per minute')]:
        if phrase in message.lower() or re.search(r'\b'+quota+r'\b',message):
            result['quota']=quota;break
    for key in ('limit','used','requested'):
        match=re.search(r'\b'+key+r'\s*[:=]?\s*([\d,]+(?:\.\d+)?)',message,re.I)
        if match:result[key]=float(match.group(1).replace(',',''))
    seconds=None
    retry=safe.get('retry-after')
    if retry:
        try:seconds=float(retry)
        except ValueError:
            try:
                when=parsedate_to_datetime(retry)
                if when.tzinfo is not None:seconds=(when-now).total_seconds()
            except (ValueError,TypeError,OverflowError):pass
    if seconds is None:
        match=re.search(r'try again in\s+((?:[\d.]+[hms]\s*)+)',message,re.I)
        if match:seconds=sum(float(n)*{'h':3600,'m':60,'s':1}[u.lower()]
            for n,u in re.findall(r'([\d.]+)([hms])',match.group(1),re.I))
    if seconds is not None and math.isfinite(seconds) and seconds>=0:
        result['retry_after_seconds']=round(seconds,3)
        result['resume_after_utc']=(now+dt.timedelta(seconds=seconds)).isoformat()
    return result


def rejected_unavailable_tool(exc, schema):
    """Recognize a model-output violation; never execute failed_generation."""
    if 'x-native-tools' in schema or getattr(exc, 'status_code', None) != 400:
        return False
    body = getattr(exc, 'body', None)
    if isinstance(body, dict):
        error = body.get('error', body)
        if isinstance(error, dict) and error.get('code') == 'tool_use_failed':
            return True
    message = getattr(exc, 'message', '')
    return isinstance(message, str) and 'Tool choice is none, but model called a tool' in message


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def read_config(path):
    text = Path(path).read_text(encoding='utf-8')
    try: result = json.loads(text)
    except json.JSONDecodeError:
        import yaml
        result = yaml.safe_load(text)
    if not isinstance(result,dict): raise ValueError('Configuration must be a mapping')
    return result


def env_values(path):
    """Read assignments without interpolation, execution, or exporting secrets."""
    result = {}
    if Path(path).is_file():
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('export '): line = line[7:]
            key, sep, value = line.partition('=')
            if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key.strip()): continue
            try: parts = shlex.split(value, comments=True)
            except ValueError: raise RuntimeError('Malformed .env assignment; check quoting') from None
            result[key.strip()] = ' '.join(parts)
    return result


def resolved_config(config, root=ROOT):
    result = json.loads(json.dumps(config))
    values = env_values(Path(root) / config['env_file'])
    backend = result.get('provider', 'gemini')
    if backend not in ('gemini', 'groq'): raise ValueError('Unknown LLM provider')
    prefix = 'GROQ' if backend == 'groq' else 'GEMINI'
    for role, item in result['models'].items():
        key = prefix + ('_AUX_MODEL' if role == 'aux' else '_MODEL')
        name = os.environ.get(key) or values.get(key) or os.environ.get(prefix+'_MODEL') or values.get(prefix+'_MODEL') or item['id']
        if any(name == (os.environ.get(k) or values.get(k)) for k in SECRET_KEYS):
            raise ValueError('A credential cannot be used as a model identifier')
        if not re.fullmatch(r'[A-Za-z0-9._/-]+', name): raise ValueError('Invalid model identifier')
        item['id'] = name.removeprefix('models/')
    for item in result['models'].values():
        peers = [v for v in result['models'].values() if v['id'] == item['id']]
        for key in ('rpm', 'rpd'): item[key] = min(v[key] for v in peers)
    return result


def _secret(path):
    value = os.environ.get('LLM_API_KEY')
    if value:
        return value
    value = env_values(path).get('LLM_API_KEY')
    if value:
        return value
    raise RuntimeError('LLM_API_KEY is missing')


def _safe_error_detail(exc, secrets):
    """Expose the server's APIError message without printing credentials/URLs."""
    detail = getattr(exc, 'message', None)
    if not isinstance(detail, str):
        payload = getattr(exc, 'response_json', None)
        detail = payload.get('error', {}).get('message') if isinstance(payload, dict) else None
    if not isinstance(detail, str):
        return None
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, '[redacted]')
    detail = re.sub(r'(?i)([?&](?:key|api[_-]?key)=)[^&\s]+', r'\1[redacted]', detail)
    detail = re.sub(r'(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+', r'\1[redacted]', detail)
    detail = re.sub(r'AIza[0-9A-Za-z_-]{20,}', '[redacted-key]', detail)
    detail = ' '.join(detail.split())[:500]
    return detail or None


class GeminiProvider:
    backend = 'gemini'
    def __init__(self, config, role='aux', *, enable_llm=False, max_requests=1, root=ROOT, client=None, sleep=time.sleep, resolve_env=True):
        if role not in config['models'] or type(max_requests) is not int or max_requests < 1:
            raise ValueError('A configured model and positive request budget are required')
        self.config = resolved_config(dict(config, provider=self.backend), root) if resolve_env else json.loads(json.dumps(config))
        self.model = self.config['models'][role]
        for key in ('rpm','rpd'):
            if type(self.model[key]) is not int or self.model[key] < 1: raise ValueError('Quotas must be positive integers')
        retries, fraction = self.config['max_retries'], self.config['daily_fraction']
        if type(retries) is not int or not 0 <= retries <= 5: raise ValueError('At most five retries are permitted')
        if not isinstance(fraction,(float,int)) or not math.isfinite(fraction) or not 0 < fraction <= .9:
            raise ValueError('Daily safety fraction must be positive and at most 90%')
        if int(self.model['rpd']*fraction) < 1: raise ValueError('Daily safety budget is below one request')
        self.root, self.enabled, self.max_requests = Path(root), enable_llm, max_requests
        self.client, self.sleep, self.calls = client, sleep, 0
        self.ledger = self.root / config['ledger']
        self.cache = self.root / config['cache']
        self.last_rate_limit = None

    def _cooldown(self, details=None, clear=False):
        path=self.ledger.parent/'rate_limit_cooldowns.json'
        values=json.loads(path.read_text()) if path.exists() else {}
        key=digest([self.backend,self.model['id']])
        if clear:
            if key not in values:return
            values.pop(key)
        elif details is not None:
            if 'resume_after_utc' not in details:return
            values[key]=details
        else:
            entry=values.get(key)
            if entry and dt.datetime.fromisoformat(entry['resume_after_utc'])>dt.datetime.now(dt.timezone.utc):
                self.last_rate_limit=entry
                raise ProviderRateLimitError(entry)
            return
        temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(values,sort_keys=True));temp.replace(path)

    def _log(self, **values):
        values.setdefault('provider', self.backend)
        values.setdefault('ts', dt.datetime.now(dt.timezone.utc).isoformat())
        with self.ledger.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(values, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def generate_tools(self, prompt, tools, **kwargs):
        """Native function calls through the same quotas, cache and ledger.

        Transport metadata is part of the cache key, never a response-schema
        extension sent to the provider. The caller validates tool arguments.
        """
        return self.generate_json(prompt, tool_turn_schema(tools), **kwargs)

    def generate_json(self, prompt, schema, *, system_prompt='', prompt_version='v1', purpose='unspecified', _list_models=False):
        values = env_values(self.root / self.config['env_file'])
        secrets = [os.environ.get(k) or values.get(k) for k in SECRET_KEYS]
        if any(s and s in prompt + system_prompt for s in secrets):
            raise RuntimeError('Prompt contains a credential; refused')
        if self.enabled and self.client is None:
            key_name = 'GROQ_API_KEY' if self.backend == 'groq' else 'LLM_API_KEY'
            if not (os.environ.get(key_name) or values.get(key_name)):
                raise RuntimeError(key_name + ' is missing')
        key = digest(([self.backend] if self.backend != 'gemini' else []) + [self.model['id'], prompt_version, system_prompt, prompt, schema])
        if not self.enabled:
            return {'state': 'DRY_RUN', 'prompt_hash': key, 'model': self.model['id']}
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        with (self.ledger.parent / 'provider.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with sqlite3.connect(str(self.cache)) as db:
                db.execute('CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, response TEXT NOT NULL, metadata TEXT NOT NULL)')
                cached = db.execute('SELECT response,metadata FROM responses WHERE key=?', (key,)).fetchone()
                if cached:
                    if any(s and s in cached[0] for s in secrets):
                        raise RuntimeError('Cached response contains a credential; refused')
                    value = json.loads(cached[0]); validate(value, schema)
                    meta = json.loads(cached[1])
                    self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=True,
                              status='CACHE_HIT', input_tokens=meta.get('input_tokens'), output_tokens=meta.get('output_tokens'), latency_ms=0, error_class=None)
                    return {'state': 'CACHE_HIT', 'value': value, 'prompt_hash': key, **meta}
                self._cooldown() # Successful cached responses remain usable during a cooldown.
                for attempt in range(self.config['max_retries'] + 1):
                    if self.calls >= self.max_requests:
                        raise RuntimeError('Invocation request budget exhausted')
                    events = []
                    if self.ledger.exists():
                        with self.ledger.open(encoding='utf-8') as f:
                            for line in f:
                                try: event = json.loads(line)
                                except json.JSONDecodeError: raise RuntimeError('Malformed ledger; preserve and repair before resuming')
                                if event.get('provider','gemini') == self.backend and event.get('model') == self.model['id'] and event.get('status') == 'REQUEST_STARTED':
                                    events.append(dt.datetime.fromisoformat(event['ts'].replace('Z', '+00:00')))
                    now = dt.datetime.now(dt.timezone.utc)
                    daily = sum(t.astimezone(PACIFIC).date() == now.astimezone(PACIFIC).date() for t in events)
                    if daily >= int(self.model['rpd'] * self.config['daily_fraction']):
                        raise RuntimeError('Pacific daily request budget exhausted')
                    # Reconstruct the token bucket under the shared lock so all
                    # cooperating processes and restarted invocations share it.
                    capacity = max(1, self.model['rpm'] - 1)
                    rate = capacity / 60.0
                    recent = sorted(t for t in events if 0 <= (now-t).total_seconds() < 60)
                    tokens, previous = float(capacity), (recent[0] if recent else now)
                    for event_time in recent:
                        tokens = min(capacity, tokens + (event_time-previous).total_seconds() * rate)
                        tokens = max(0.0, tokens - 1.0)
                        previous = event_time
                    tokens = min(capacity, tokens + (now-previous).total_seconds() * rate)
                    if tokens < 1:
                        self.sleep((1-tokens)/rate + 0.01)
                    if len(recent) >= capacity:
                        self.sleep(max(0.0, 60 - (dt.datetime.now(dt.timezone.utc)-recent[-capacity]).total_seconds()) + 0.01)
                    # A durable reservation is logged before the call: crashes consume budget.
                    self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=False,
                              status='REQUEST_STARTED', input_tokens=None, output_tokens=None, latency_ms=0, error_class=None)
                    self.calls += 1; start = time.monotonic()
                    try:
                        value, input_tokens, output_tokens = self._request(prompt, system_prompt, schema, _list_models, secrets)
                        validate(value, schema)
                        if any(s and s in json.dumps(value) for s in secrets):
                            raise RuntimeError('Response contains a credential; refused')
                        meta = {'model': self.model['id'], 'input_tokens': input_tokens,
                                'output_tokens': output_tokens,
                                'latency_ms': round((time.monotonic()-start)*1000)}
                        db.execute('INSERT INTO responses VALUES (?,?,?)', (key, json.dumps(value), json.dumps(meta))); db.commit()
                        self._cooldown(clear=True);self.last_rate_limit=None
                        self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=False,
                                  status='SUCCESS', input_tokens=meta['input_tokens'], output_tokens=meta['output_tokens'], latency_ms=meta['latency_ms'], error_class=None)
                        return {'state': 'SUCCESS', 'value': value, 'prompt_hash': key, **meta}
                    except Exception as exc:
                        code = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
                        code = code if type(code) is int and 100 <= code <= 599 else None
                        rate=rate_limit_details(exc,self.model['id'],secrets) if code==429 else None
                        if rate:
                            self.last_rate_limit=rate;self._cooldown(rate)
                        self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=False,
                                  status='ERROR', input_tokens=None, output_tokens=None, latency_ms=round((time.monotonic()-start)*1000), error_class=type(exc).__name__, http_status=code,
                                  **({'rate_limit':rate} if rate else {}))
                        if rejected_unavailable_tool(exc, schema):
                            raise InvalidJSONResponse('Model attempted an unavailable tool; return answer JSON without tool calls') from None
                        if isinstance(exc, (json.JSONDecodeError, ValidationError)):
                            raise InvalidJSONResponse('Provider output did not match the requested JSON schema') from None
                        if code not in (429, 500, 502, 503, 504) or attempt >= self.config['max_retries'] or self.calls >= self.max_requests:
                            if rate:raise ProviderRateLimitError(rate) from None
                            hint = {400: 'check model and structured-output settings', 401: 'check credentials', 403: 'check key permissions', 404: 'check model availability', 429: 'quota or rate limit reached'}.get(code, 'check provider availability')
                            detail = _safe_error_detail(exc, secrets)
                            detail = '; Provider message: ' + detail if detail else ''
                            raise RuntimeError('%s request for model %s failed: %s%s; %s%s' %
                                (self.backend.title(), self.model['id'], type(exc).__name__, ' HTTP %s' % code if code else '', hint, detail)) from None
                        delay = min(60, 2 ** attempt) + random.random()
                        headers = getattr(getattr(exc, 'response', None), 'headers', {})
                        try: delay = max(delay, float(headers.get('retry-after', 0)))
                        except (TypeError, ValueError): pass
                        if rate:delay=max(delay,rate.get('retry_after_seconds',0))
                        if delay > 300:
                            if rate:raise ProviderRateLimitError(rate) from None
                            raise RuntimeError('Provider requests Retry-After of %.1f seconds; resume later'%delay) from None
                        self.sleep(delay)


    def _request(self, prompt, system_prompt, schema, _list_models, secrets):
        if self.client is None:
            from google import genai
            self.client = genai.Client(api_key=_secret(self.root / self.config['env_file']), vertexai=False,
                http_options={'timeout': self.config.get('timeout_ms', 60000),
                              'retry_options': {'attempts': 1}})
        if 'x-native-tools' in schema:
            response = self.client.models.generate_content(model=self.model['id'], contents=prompt,
                config={'system_instruction': system_prompt, 'temperature': self.config['temperature'],
                        'max_output_tokens': self.config['max_output_tokens'],
                        'tools': [{'function_declarations': schema['x-native-tools']}],
                        'tool_config': {'function_calling_config': {'mode': 'ANY'}}})
            calls = [{'name': c.name, 'arguments_json': json.dumps(dict(c.args or {}))}
                     for c in (response.function_calls or [])]
            if not calls: raise ValueError('Expected native function call')
            usage = getattr(response, 'usage_metadata', None)
            return {'calls': calls}, getattr(usage, 'prompt_token_count', None), getattr(usage, 'candidates_token_count', None)
        options = {'system_instruction': system_prompt, 'temperature': self.config['temperature'],
                   'max_output_tokens': self.config['max_output_tokens'],
                   'response_mime_type': 'application/json', 'response_json_schema': schema}
        if self.config.get('thinking_budget') is not None:
            options['thinking_config'] = {'thinking_budget': self.config['thinking_budget']}
        if _list_models:
            response = self.client.models.list(config={'page_size': 100})
            value = {'models': sorted(m.name for m in response.page
                      if re.fullmatch(r'[A-Za-z0-9._/-]+', m.name or '')
                      and 'generateContent' in (getattr(m, 'supported_actions', None) or [])),
                     'more_pages': bool(getattr(response, 'config', {}).get('page_token'))}
            usage = None
        else:
            response = self.client.models.generate_content(model=self.model['id'], contents=prompt, config=options)
            if any(s and s in response.text for s in secrets):
                raise RuntimeError('Response contains a credential; refused')
            value = json.loads(response.text)
            usage = getattr(response, 'usage_metadata', None)
        return value, getattr(usage, 'prompt_token_count', None), getattr(usage, 'candidates_token_count', None)

    def list_models(self):
        schema = {'type': 'object', 'properties': {'models': {'type': 'array', 'items': {'type': 'string'}},
                  'more_pages': {'type': 'boolean'}}, 'required': ['models', 'more_pages'], 'additionalProperties': False}
        return self.generate_json('List model identifiers only.', schema, purpose='list-models',
                                  prompt_version='model-list-' + dt.datetime.now(dt.timezone.utc).isoformat(), _list_models=True)


class GroqProvider(GeminiProvider):
    backend = 'groq'

    def _request(self, prompt, system_prompt, schema, _list_models, secrets):
        if self.client is None:
            from groq import Groq
            values = env_values(self.root / self.config['env_file'])
            key = os.environ.get('GROQ_API_KEY') or values.get('GROQ_API_KEY')
            if not key: raise RuntimeError('GROQ_API_KEY is missing')
            self.client = Groq(api_key=key, max_retries=0,
                               timeout=self.config.get('timeout_ms',60000)/1000)
        if _list_models:
            response = self.client.models.list()
            return {'models':sorted(m.id for m in response.data), 'more_pages':False}, None, None
        if 'x-native-tools' in schema:
            response = self.client.chat.completions.create(
                model=self.model['id'], temperature=self.config['temperature'],
                max_completion_tokens=self.config['max_output_tokens'],
                reasoning_effort=self.config.get('reasoning_effort','low'),
                messages=[{'role':'system','content':system_prompt}, {'role':'user','content':prompt}],
                tools=[{'type':'function','function':t} for t in schema['x-native-tools']],
                tool_choice='required', parallel_tool_calls=False)
            if response.choices[0].finish_reason not in ('tool_calls','stop'):
                raise RuntimeError('Incomplete native tool response')
            calls=[{'name':c.function.name,'arguments_json':c.function.arguments}
                   for c in (response.choices[0].message.tool_calls or [])]
            if not calls: raise ValueError('Expected native function call')
            usage=response.usage
            return {'calls':calls},getattr(usage,'prompt_tokens',None),getattr(usage,'completion_tokens',None)
        response = self.client.chat.completions.create(
            model=self.model['id'], temperature=self.config['temperature'],
            max_completion_tokens=self.config['max_output_tokens'],
            reasoning_effort=self.config.get('reasoning_effort','low'),
            tool_choice='none',
            messages=[{'role':'system','content':system_prompt}, {'role':'user','content':prompt}],
            response_format={'type':'json_schema','json_schema':{
                'name':'study_response','strict':True,'schema':schema}})
        if not response.choices or response.choices[0].finish_reason != 'stop':
            raise RuntimeError('Incomplete Groq JSON response; check output token budget')
        content=response.choices[0].message.content
        if not content or any(secret and secret in content for secret in secrets):
            raise RuntimeError('Empty or unsafe response; refused')
        usage=response.usage
        return json.loads(content), getattr(usage,'prompt_tokens',None), getattr(usage,'completion_tokens',None)


def create_provider(config, role='aux', **kwargs):
    backend=config.get('provider','gemini')
    if backend not in ('gemini','groq'): raise ValueError('Unknown LLM provider')
    return (GroqProvider if backend=='groq' else GeminiProvider)(config,role,**kwargs)


class MockProvider:
    def __init__(self, value, max_requests=100000):
        self.value, self.calls, self.max_requests = value, 0, max_requests
    def generate_json(self, prompt, schema, **kwargs):
        if self.calls >= self.max_requests: raise RuntimeError('Invocation request budget exhausted')
        self.calls += 1
        value = self.value(prompt) if callable(self.value) else self.value
        validate(value, schema)
        return {'state': 'MOCK', 'value': value, 'model': 'mock',
                'prompt_hash': digest(['mock',kwargs.get('prompt_version'),kwargs.get('system_prompt'),prompt,schema]),
                'input_tokens': None, 'output_tokens': None, 'latency_ms': 0}

    def generate_tools(self, prompt, tools, **kwargs):
        return self.generate_json(prompt, tool_turn_schema(tools), **kwargs)


def tool_turn_schema(tools):
    return {'type':'object','properties':{'calls':{'type':'array','minItems':1,
        'items':{'type':'object','properties':{'name':{'type':'string'},
            'arguments_json':{'type':'string'}},'required':['name','arguments_json'],
            'additionalProperties':False}}},'required':['calls'],'additionalProperties':False,
        'x-native-tools':tools}

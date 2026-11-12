"""Opt-in Gemini JSON provider with durable budget, cache, and audit ledger.

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
from pathlib import Path
from zoneinfo import ZoneInfo

from jsonschema import validate

ROOT = Path(__file__).resolve().parents[3]
PACIFIC = ZoneInfo('America/Los_Angeles')


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
    for role, item in result['models'].items():
        key = 'GEMINI_AUX_MODEL' if role == 'aux' else 'GEMINI_MODEL'
        name = os.environ.get(key) or values.get(key) or os.environ.get('GEMINI_MODEL') or values.get('GEMINI_MODEL') or item['id']
        if any(name == (os.environ.get(k) or values.get(k)) for k in ('LLM_API_KEY','LANGSMITH_API_KEY','LANGSMITH_KEY')):
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
    def __init__(self, config, role='aux', *, enable_llm=False, max_requests=1, root=ROOT, client=None, sleep=time.sleep, resolve_env=True):
        if role not in config['models'] or type(max_requests) is not int or max_requests < 1:
            raise ValueError('A configured model and positive request budget are required')
        self.config = resolved_config(config, root) if resolve_env else json.loads(json.dumps(config))
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

    def _log(self, **values):
        values.setdefault('ts', dt.datetime.now(dt.timezone.utc).isoformat())
        with self.ledger.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(values, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def generate_json(self, prompt, schema, *, system_prompt='', prompt_version='v1', purpose='unspecified', _list_models=False):
        values = env_values(self.root / self.config['env_file'])
        secrets = [os.environ.get(k) or values.get(k) for k in ('LLM_API_KEY', 'LANGSMITH_API_KEY', 'LANGSMITH_KEY')]
        if any(s and s in prompt + system_prompt for s in secrets):
            raise RuntimeError('Prompt contains a credential; refused')
        key = digest([self.model['id'], prompt_version, system_prompt, prompt, schema])
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
                for attempt in range(self.config['max_retries'] + 1):
                    if self.calls >= self.max_requests:
                        raise RuntimeError('Invocation request budget exhausted')
                    events = []
                    if self.ledger.exists():
                        with self.ledger.open(encoding='utf-8') as f:
                            for line in f:
                                try: event = json.loads(line)
                                except json.JSONDecodeError: raise RuntimeError('Malformed ledger; preserve and repair before resuming')
                                if event.get('model') == self.model['id'] and event.get('status') == 'REQUEST_STARTED':
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
                        if self.client is None:
                            from google import genai
                            self.client = genai.Client(api_key=_secret(self.root / self.config['env_file']), vertexai=False,
                                http_options={'timeout': self.config.get('timeout_ms', 60000),
                                              'retry_options': {'attempts': 1}})
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
                        validate(value, schema)
                        if any(s and s in json.dumps(value) for s in secrets):
                            raise RuntimeError('Response contains a credential; refused')
                        meta = {'model': self.model['id'], 'input_tokens': getattr(usage, 'prompt_token_count', None),
                                'output_tokens': getattr(usage, 'candidates_token_count', None),
                                'latency_ms': round((time.monotonic()-start)*1000)}
                        db.execute('INSERT INTO responses VALUES (?,?,?)', (key, json.dumps(value), json.dumps(meta))); db.commit()
                        self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=False,
                                  status='SUCCESS', input_tokens=meta['input_tokens'], output_tokens=meta['output_tokens'], latency_ms=meta['latency_ms'], error_class=None)
                        return {'state': 'SUCCESS', 'value': value, 'prompt_hash': key, **meta}
                    except Exception as exc:
                        code = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
                        code = code if type(code) is int and 100 <= code <= 599 else None
                        self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=False,
                                  status='ERROR', input_tokens=None, output_tokens=None, latency_ms=round((time.monotonic()-start)*1000), error_class=type(exc).__name__, http_status=code)
                        if code not in (429, 500, 502, 503, 504) or attempt >= self.config['max_retries'] or self.calls >= self.max_requests:
                            hint = {400: 'check model and structured-output settings', 401: 'check credentials', 403: 'check key permissions', 404: 'check model availability', 429: 'quota or rate limit reached'}.get(code, 'check provider availability')
                            detail = _safe_error_detail(exc, secrets)
                            detail = '; Google message: ' + detail if detail else ''
                            raise RuntimeError('Gemini request for model %s failed: %s%s; %s%s' %
                                (self.model['id'], type(exc).__name__, ' HTTP %s' % code if code else '', hint, detail)) from None
                        self.sleep(min(60, 2 ** attempt) + random.random())


    def list_models(self):
        schema = {'type': 'object', 'properties': {'models': {'type': 'array', 'items': {'type': 'string'}},
                  'more_pages': {'type': 'boolean'}}, 'required': ['models', 'more_pages'], 'additionalProperties': False}
        return self.generate_json('List model identifiers only.', schema, purpose='list-models',
                                  prompt_version='model-list-' + dt.datetime.now(dt.timezone.utc).isoformat(), _list_models=True)


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

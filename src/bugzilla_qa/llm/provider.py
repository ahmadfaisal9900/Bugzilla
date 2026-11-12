"""Opt-in Gemini JSON provider with durable budget, cache, and audit ledger.

The shared file lock serializes cooperating local processes. A provider response
can be charged before a crash and before caching; exact-once billing is impossible.
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
import random
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
    # JSON is a YAML subset and avoids a YAML dependency.
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _secret(path):
    value = os.environ.get('LLM_API_KEY')
    if value:
        return value
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            key, sep, val = line.partition('=')
            if sep and key.strip() == 'LLM_API_KEY':
                return val.strip().strip('"\'')
    raise RuntimeError('LLM_API_KEY is missing')


class GeminiProvider:
    def __init__(self, config, role='aux', *, enable_llm=False, max_requests=1, root=ROOT, client=None, sleep=time.sleep):
        if role not in config['models'] or max_requests < 1:
            raise ValueError('A configured model and positive request budget are required')
        self.config, self.model = config, config['models'][role]
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

    def generate_json(self, prompt, schema, *, system_prompt='', prompt_version='v1', purpose='unspecified'):
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
                    value = json.loads(cached[0]); validate(value, schema)
                    meta = json.loads(cached[1])
                    self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=True,
                              status='CACHE_HIT', input_tokens=meta.get('input_tokens'), output_tokens=meta.get('output_tokens'), latency_ms=0, error_class=None)
                    return {'state': 'CACHE_HIT', 'value': value, **meta}
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
                    # A durable reservation is logged before the call: crashes consume budget.
                    self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=False,
                              status='REQUEST_STARTED', input_tokens=None, output_tokens=None, latency_ms=0, error_class=None)
                    self.calls += 1; start = time.monotonic()
                    try:
                        if self.client is None:
                            from google import genai
                            self.client = genai.Client(api_key=_secret(self.root / self.config['env_file']))
                        options = {'system_instruction': system_prompt, 'temperature': self.config['temperature'],
                                   'max_output_tokens': self.config['max_output_tokens'],
                                   'response_mime_type': 'application/json', 'response_json_schema': schema}
                        if self.config.get('thinking_budget') is not None:
                            options['thinking_config'] = {'thinking_budget': self.config['thinking_budget']}
                        response = self.client.models.generate_content(model=self.model['id'], contents=prompt, config=options)
                        value = json.loads(response.text); validate(value, schema)
                        usage = getattr(response, 'usage_metadata', None)
                        meta = {'model': self.model['id'], 'input_tokens': getattr(usage, 'prompt_token_count', None),
                                'output_tokens': getattr(usage, 'candidates_token_count', None),
                                'latency_ms': round((time.monotonic()-start)*1000)}
                        db.execute('INSERT INTO responses VALUES (?,?,?)', (key, json.dumps(value), json.dumps(meta))); db.commit()
                        self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=False,
                                  status='SUCCESS', input_tokens=meta['input_tokens'], output_tokens=meta['output_tokens'], latency_ms=meta['latency_ms'], error_class=None)
                        return {'state': 'SUCCESS', 'value': value, **meta}
                    except Exception as exc:
                        code = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
                        code = code if type(code) is int and 100 <= code <= 599 else None
                        self._log(model=self.model['id'], purpose=purpose, prompt_hash=key, cache_hit=False,
                                  status='ERROR', input_tokens=None, output_tokens=None, latency_ms=round((time.monotonic()-start)*1000), error_class=type(exc).__name__, http_status=code)
                        if code not in (429, 500, 502, 503, 504) or attempt >= self.config['max_retries']:
                            hint = {400: 'check model and structured-output settings', 401: 'check credentials', 403: 'check key permissions', 404: 'check model availability', 429: 'quota or rate limit reached'}.get(code, 'check provider availability')
                            raise RuntimeError('Gemini request failed: %s%s; %s' % (type(exc).__name__, ' HTTP %s' % code if code else '', hint)) from None
                        self.sleep(min(60, 2 ** attempt) + random.random())


class MockProvider:
    def __init__(self, value): self.value, self.calls = value, 0
    def generate_json(self, prompt, schema, **kwargs):
        self.calls += 1
        validate(self.value, schema)
        return {'state': 'MOCK', 'value': self.value, 'model': 'mock', 'input_tokens': None, 'output_tokens': None, 'latency_ms': 0}

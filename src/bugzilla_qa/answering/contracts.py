"""Common answer contract, conservative context packing and safe serialization."""
import re
from typing import TypedDict
from jsonschema import validate
from bugzilla_qa.eval_extension.retrieval import safe_text
from bugzilla_qa.llm.provider import SECRET_KEYS, env_values, ROOT
import os

ANSWER_SCHEMA = {
    'type': 'object', 'properties': {
        'abstain': {'type': 'boolean'},
        'answer': {'type': ['string', 'number', 'array', 'null'],
                   'items': {'type': ['string','number','boolean','null']}},
        'answer_type': {'type': 'string'},
        'bug_ids': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1}},
        'citations': {'type': 'array', 'items': {'type': 'string'}},
        'rationale': {'type': 'string', 'maxLength': 1000}},
    'required': ['abstain', 'answer', 'answer_type', 'bug_ids', 'citations', 'rationale'],
    'additionalProperties': False}


class AnswerState(TypedDict, total=False):
    qid: str
    question: str
    split: str
    system_id: str
    route: str
    retrieved: list
    context: str
    raw_output: dict
    answer: dict
    errors: list
    call_count: int
    family: str
    dataset: str
    scope: dict
    freeze_id: str
    tool_log: list
    tool_step: int
    repair_count: int
    usage: list
    status: str
    route_rule: str
    context_ids: list
    context_map: dict
    started_at: float
    config_hash: str
    oracle_refs: list
    cache_hit: bool
    citation_normalization: list
    retrieval_cache_hit: bool


def clean(value, root=ROOT):
    """Used by both ledger writes and LangSmith process_inputs/process_outputs."""
    env = env_values(root / '.env')
    secrets = [os.environ.get(k) or env.get(k) for k in SECRET_KEYS]
    def walk(v):
        if isinstance(v, dict):
            return {str(k): walk(x) for k, x in v.items()
                    if k not in ('self', 'gold', 'corrected_gold', 'raw_field_mapping')}
        if isinstance(v, (list, tuple)): return [walk(x) for x in v]
        if isinstance(v, str):
            for secret in secrets:
                if secret: v = v.replace(secret, '[redacted]')
            return safe_text(v)
        if v is None or isinstance(v, (bool, int, float)): return v
        return '<' + type(v).__name__ + '>'
    return walk(value)


def public_chunk(row):
    if row.get('visibility') != 'public':
        raise ValueError('Refusing private/unknown-visibility evidence')
    return dict(row, text=safe_text(row['text']))


def pack(chunks, budget):
    """Conservative UTF-8 byte upper bound; includes labels/IDs and newlines.

    No generator tokenizer is distributed by the configured hosted model. This
    may pack fewer than 3,000 actual tokens and is recorded in every run.
    """
    if budget < 1: raise ValueError('Context budget must be positive')
    parts=[]; mapping={}; used=0
    for row in chunks:
        row=public_chunk(row)
        label='C'+str(len(mapping)+1)
        header='[%s] chunk_id=%s\n' % (label, row['chunk_id'])
        available=budget-used-len((header+'\n').encode('utf-8'))
        if available <= 0: break
        text=row['text'].encode('utf-8')[:available].decode('utf-8', errors='ignore')
        if not text: break
        part=header+text+'\n'; parts.append(part)
        mapping[label]=row['chunk_id']; used+=len(part.encode('utf-8'))
        if len(text.encode('utf-8')) < len(row['text'].encode('utf-8')): break
    return ''.join(parts), mapping


def abstention(reason):
    return dict(abstain=True, answer=None, answer_type='unknown', bug_ids=[],
                citations=[], rationale=reason)


def check_answer(answer, ids):
    validate(answer, ANSWER_SCHEMA)
    if answer['abstain'] != (answer['answer'] is None):
        raise ValueError('Abstention and null answer must agree')
    if not set(answer['citations']) <= set(ids): raise ValueError('Citation not in supplied context/tools')
    sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z])', answer['rationale'].strip())
    if len(sentences)>2: raise ValueError('Rationale exceeds two sentences')
    return answer


def normalize_citations(answer, mapping):
    """Resolve only explicit context labels; never guess a source or alter claims."""
    if not isinstance(answer,dict) or not isinstance(answer.get('citations'),list):
        return answer,[]
    result=dict(answer);citations=[];changes=[]
    for citation in answer['citations']:
        key=citation
        if isinstance(key,str) and re.fullmatch(r'\[C[1-9]\d*\]',key):key=key[1:-1]
        resolved=mapping.get(key,citation) if isinstance(key,str) else citation
        if resolved!=citation:changes.append({'label':citation,'chunk_id':resolved})
        citations.append(resolved)
    result['citations']=citations
    return result,changes

"""Shared, explicit configuration accepted by both interfaces."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[3]
SYSTEM_IDS = ('R0', *(f'S{i}' for i in range(9)), 'ORACLE')
RETRIEVERS = ('R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7a', 'R7b')
FIXED_RETRIEVERS = {'S0': 'R1', 'S1': 'R1', 'S4': 'R5', 'S6': 'R6', 'ORACLE': 'R1'}


def load_spec(path: str | Path = ROOT / 'configs/serving.yaml') -> dict:
    with Path(path).open(encoding='utf-8') as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict) or not {'models', 'hyperparameters'} <= value.keys():
        raise ValueError('spec: models and hyperparameters are required')
    return value


class RunConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True, allow_inf_nan=False)

    system_id: Literal['R0', 'S0', 'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'ORACLE'] = 'S2'
    retriever: Literal['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7a', 'R7b'] = 'R7b'
    corpus: Literal['C0', 'C1', 'C2'] = 'C1'
    provider: Literal['groq', 'mock'] = 'groq'
    model: str = 'openai/gpt-oss-20b'
    top_k: int = Field(default=5, ge=1, le=50)
    temperature: float = Field(default=0.0, ge=0, le=1)
    context_budget_tokens: int = Field(default=3000, ge=128)
    prompt_version: Literal['answer-v1', 'answer-v2-compact'] = 'answer-v1'
    s4_tau: float | None = None
    s5_dossier_budget: int | None = Field(default=None, ge=128)
    s7_max_tool_steps: int | None = Field(default=None, ge=1, le=4)
    rrf_k: int | None = Field(default=None, ge=1, le=200)
    query_transform: Literal['R7a', 'R7b'] | None = None

    @model_validator(mode='before')
    @classmethod
    def fixed_defaults(cls, data):
        if isinstance(data, dict) and 'retriever' not in data:
            system = data.get('system_id', 'S2')
            if system == 'R0':
                data = {**data, 'retriever': 'R5'}
            if system == 'S3' and data.get('query_transform'):
                data = {**data, 'retriever': data['query_transform']}
            if system in FIXED_RETRIEVERS:
                data = {**data, 'retriever': FIXED_RETRIEVERS[system]}
        return data

    def validate_against(self, spec: dict | None = None) -> 'RunConfig':
        spec = spec if spec is not None else load_spec()
        errors = []
        knobs = spec['hyperparameters']
        for name, value in self.model_dump().items():
            if value is None:
                continue
            if name not in knobs:
                errors.append(f'{name}: missing hyperparameter specification')
                continue
            knob = knobs[name]
            if self.system_id not in knob['applies_to']:
                if value != type(self).model_fields[name].default:
                    errors.append(f'{name}: does not apply to {self.system_id}')
            if 'choices' in knob and value not in knob['choices']:
                errors.append(f'{name}: must be one of {knob["choices"]}')
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not math.isfinite(value):
                    errors.append(f'{name}: must be finite')
                if value < knob.get('min', -math.inf) or value > knob.get('max', math.inf):
                    errors.append(f'{name}: outside [{knob.get("min")}, {knob.get("max")}]')
        models = [m for m in spec['models'].values() if m['model_id'] == self.model]
        if not models:
            errors.append('model: unknown model')
        else:
            model = models[0]
            if self.provider not in (model['provider'], 'mock'):
                errors.append('provider: incompatible with model')
            cap = model['max_context_tokens']
            for name in ('context_budget_tokens', 's5_dossier_budget'):
                value = getattr(self, name)
                if value is not None and value > cap:
                    errors.append(f'{name}: exceeds model cap {cap}')
        fixed = FIXED_RETRIEVERS.get(self.system_id)
        if fixed and self.retriever != fixed:
            errors.append(f'retriever: {self.system_id} uses fixed {fixed}')
        if self.system_id == 'R0' and self.retriever in ('R7a', 'R7b'):
            errors.append('retriever: R0 cannot call an LLM query transform')
        if self.system_id == 'S3':
            if self.retriever not in ('R7a', 'R7b'):
                errors.append('retriever: S3 requires R7a or R7b')
            if self.query_transform and self.query_transform != self.retriever:
                errors.append('query_transform: must match the S3 retriever')
        if self.rrf_k is not None and self.retriever in ('R1', 'R2'):
            errors.append('rrf_k: not consumed by R1/R2')
        if errors:
            raise ValueError('; '.join(errors))
        return self


def config_hash(cfg: RunConfig) -> str:
    payload = json.dumps(cfg.model_dump(mode='json'), sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]

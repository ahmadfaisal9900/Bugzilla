"""HTTP shapes; the Phase 0 app supplies schemas and 501 responses only."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .records import AnswerRecord, ContractModel, ErrorData
from .run_config import RunConfig


class StatusResponse(ContractModel):
    status: str


class Preset(ContractModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    label: str
    description: str
    config: RunConfig
    is_champion: bool


class ModelOption(ContractModel):
    provider: str
    model_id: str
    label: str
    rpm: int = Field(gt=0)
    rpd: int = Field(gt=0)
    tpm: int = Field(gt=0)
    tpd: int = Field(gt=0)
    max_context_tokens: int = Field(gt=0)


class OptionsResponse(ContractModel):
    models: dict[str, ModelOption]
    hyperparameters: dict[str, dict[str, Any]]
    presets: list[Preset]


class ChatRequest(ContractModel):
    session_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=6000)
    preset_slug: str | None = None
    overrides: dict[str, Any] | None = None


class AskResponse(ContractModel):
    request_id: str
    record: AnswerRecord
    langsmith_run_id: str | None = None


class FeedbackRequest(ContractModel):
    request_id: str
    score: Literal[0, 1]
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(ContractModel):
    status: str


class ModelQuota(ContractModel):
    model: str
    used_requests: int = Field(ge=0)
    limit_requests: int = Field(gt=0)
    used_tokens: int = Field(ge=0)
    limit_tokens: int = Field(gt=0)
    degraded_now: bool


class QuotaResponse(ContractModel):
    models: list[ModelQuota]


class ErrorResponse(ErrorData):
    pass


PresetsResponse = list[Preset]
ExamplesResponse = list[str]

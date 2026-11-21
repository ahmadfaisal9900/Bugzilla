"""Public answer and event payloads shared by serving and experiment clients."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Answer(ContractModel):
    abstain: bool
    answer: Union[str, int, float, list[Union[str, int, float, bool, None]], None]
    answer_type: str
    bug_ids: list[int] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    rationale: str = Field(max_length=1000)

    @model_validator(mode="after")
    def consistent(self):
        if self.abstain != (self.answer is None):
            raise ValueError("answer: null must agree with abstain")
        if any(b < 1 for b in self.bug_ids):
            raise ValueError("bug_ids: IDs must be positive")
        if len(re.split(r"(?<=[.!?])\s+(?=[A-Z])", self.rationale.strip())) > 2:
            raise ValueError("rationale: at most two sentences")
        return self


class EvidenceItem(ContractModel):
    chunk_id: str
    bug_id: str
    snippet: str
    score: float
    url: str


class AnswerRecord(ContractModel):
    answer: Answer
    route: str
    route_rule: str
    evidence: list[EvidenceItem]
    tokens: dict[str, Any]
    llm_calls: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    degraded: bool
    errors: list[str]
    config_hash: str = Field(pattern=r"^[a-f0-9]{12}$")


class StatusData(ContractModel):
    stage: Literal["retrieving", "retrieved", "generating", "done"]
    detail: str


class EvidenceData(ContractModel):
    items: list[EvidenceItem]


class ErrorData(ContractModel):
    code: Literal["invalid_config", "rate_limited", "internal"]
    message: str
    retry_after: int | None = Field(default=None, ge=0)


class DoneData(ContractModel):
    request_id: str
    langsmith_run_id: str | None = None


class StatusEvent(ContractModel):
    event: Literal["status"] = "status"
    data: StatusData


class EvidenceEvent(ContractModel):
    event: Literal["evidence"] = "evidence"
    data: EvidenceData


class AnswerEvent(ContractModel):
    event: Literal["answer"] = "answer"
    data: AnswerRecord


class ErrorEvent(ContractModel):
    event: Literal["error"] = "error"
    data: ErrorData


class DoneEvent(ContractModel):
    event: Literal["done"] = "done"
    data: DoneData


SSEEvent = Annotated[
    Union[StatusEvent, EvidenceEvent, AnswerEvent, ErrorEvent, DoneEvent],
    Field(discriminator="event"),
]

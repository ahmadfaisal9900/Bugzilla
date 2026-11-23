"""HTTP client for the serving API (/v1). No Streamlit imports, so it is easy to test."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings
from .models import AnswerRecord, Catalog, Preset, QuotaStatus, Setting


class ApiError(Exception):
    """A failed call, normalised to the API's error shape {code, message, retry_after}."""

    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after

    @property
    def field(self) -> str | None:
        """For invalid_config errors like "top_k: outside [1, 50]", the setting name."""
        name, sep, _ = self.message.partition(":")
        return name.strip() if sep and self.code == "invalid_config" else None

    @classmethod
    def from_response(cls, response: httpx.Response) -> ApiError:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict) and isinstance(body.get("detail"), list):
            # FastAPI request validation (pydantic) errors.
            first = body["detail"][0] if body["detail"] else {}
            where = ".".join(str(p) for p in first.get("loc", [])[1:])
            body = {"code": "invalid_config", "message": f"{where}: {first.get('msg', 'invalid')}"}
        if not isinstance(body, dict):
            body = {}
        retry = body.get("retry_after") or response.headers.get("Retry-After")
        return cls(
            status=response.status_code,
            code=str(body.get("code", "internal")),
            message=str(body.get("message", response.reason_phrase or "Request failed")),
            retry_after=int(float(retry)) if retry not in (None, "") else None,
        )


class ApiUnavailable(ApiError):
    def __init__(self, message: str = "The bug archive service could not be reached."):
        super().__init__(503, "unavailable", message)


@dataclass(frozen=True)
class StreamEvent:
    name: str  # status | evidence | answer | error | done
    data: dict[str, Any]


def parse_sse(lines: Iterable[str]) -> Iterator[StreamEvent]:
    """Minimal Server-Sent Events parser (event/data fields, comments, multi-line data)."""
    name, data = "message", []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                yield StreamEvent(name, json.loads("\n".join(data)))
            name, data = "message", []
        elif line.startswith(":"):
            continue
        else:
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if key == "event":
                name = value
            elif key == "data":
                data.append(value)
    if data:
        yield StreamEvent(name, json.loads("\n".join(data)))


class ApiClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._settings = settings
        self._http = httpx.Client(
            base_url=settings.api_url,
            headers={"X-API-Key": settings.api_key},
            timeout=httpx.Timeout(settings.request_timeout_s, connect=5.0),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    # -- low level ---------------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise ApiUnavailable() from error
        if response.is_error:
            raise ApiError.from_response(response)
        return response.json()

    # -- endpoints -----------------------------------------------------------------------------
    def is_ready(self) -> bool:
        try:
            return self._request("GET", "/v1/ready").get("status") == "ok"
        except ApiError:
            return False

    def options(self) -> dict[str, Any]:
        """GET /v1/options: models, hyperparameter specs and presets."""
        return self._request("GET", "/v1/options")

    def presets(self) -> list[Preset]:
        """GET /v1/presets: the answer modes."""
        return [Preset.from_json(p) for p in self._request("GET", "/v1/presets")]

    def examples(self) -> list[str]:
        """GET /v1/examples: starter questions for the empty chat."""
        return [str(q) for q in self._request("GET", "/v1/examples")]

    def quota(self) -> QuotaStatus:
        return QuotaStatus.from_json(self._request("GET", "/v1/quota"))

    def catalog(self) -> Catalog:
        """Everything the page needs before the first question, in one typed object."""
        options = self.options()
        presets = [Preset.from_json(p) for p in options.get("presets") or []] or self.presets()
        if not presets:
            raise ApiError(503, "no_presets", "The API returned no answer modes.")
        return Catalog(
            presets=presets,
            settings=[
                Setting.from_json(k, v) for k, v in (options.get("hyperparameters") or {}).items()
            ],
            model_labels={
                m["model_id"]: m.get("label", m["model_id"])
                for m in (options.get("models") or {}).values()
            },
            examples=self.examples(),
        )

    @staticmethod
    def chat_body(
        session_id: str, message: str, preset_slug: str | None, overrides: dict[str, Any] | None
    ) -> dict[str, Any]:
        """A ChatRequest. Each question is sent on its own; earlier turns are never included."""
        return {
            "session_id": session_id,
            "message": message,
            "preset_slug": preset_slug,
            "overrides": overrides or None,
        }

    def ask(self, body: dict[str, Any]) -> tuple[str, AnswerRecord]:
        """POST /v1/ask (no streaming). Returns (request_id, record)."""
        data = self._request("POST", "/v1/ask", json=body)
        return str(data.get("request_id", "")), AnswerRecord.from_json(data.get("record") or {})

    def stream(self, body: dict[str, Any]) -> Iterator[StreamEvent]:
        """POST /v1/chat/stream and yield its SSE events. Raises ApiError before the first event."""
        timeout = httpx.Timeout(self._settings.stream_timeout_s, connect=5.0)
        try:
            with self._http.stream(
                "POST", "/v1/chat/stream", json=body, timeout=timeout
            ) as response:
                if response.is_error:
                    response.read()
                    raise ApiError.from_response(response)
                yield from parse_sse(response.iter_lines())
        except httpx.HTTPError as error:
            raise ApiUnavailable(
                "The connection dropped while the answer was being written."
            ) from error

    def feedback(self, request_id: str, score: int, comment: str | None = None) -> None:
        """POST /v1/feedback: 1 = helpful, 0 = not helpful, with an optional comment."""
        payload = {"request_id": request_id, "score": score, "comment": comment or None}
        self._request("POST", "/v1/feedback", json=payload)

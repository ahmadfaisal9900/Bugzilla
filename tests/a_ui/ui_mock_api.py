"""Offline stand-in for the serving API, for UI work and tests. Standard library only.

    python tests/a_ui/ui_mock_api.py   # serves http://127.0.0.1:8000, key "dev-key"

Every answer is DEMO DATA: the bug numbers and text are made up and do not describe real bugs.
The responses follow the real contract (src/bugzilla_serving/contracts);
tests/a_ui/test_ui_contract.py checks that. Special questions trigger the other UI states:
    contains "quota"     -> sources-only fallback
    contains "unknown"   -> the assistant abstains
    contains "slow down" -> 429 rate limited
    contains "broken"    -> error event mid-stream
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

API_KEY = os.environ.get("SERVING_API_KEY", "dev-key")
CONFIG_HASH = "0123456789ab"

_BASE_CONFIG = {
    "retriever": "R7b",
    "corpus": "C1",
    "provider": "mock",
    "model": "openai/gpt-oss-20b",
    "top_k": 5,
    "temperature": 0.0,
    "context_budget_tokens": 3000,
    "prompt_version": "answer-v1",
    # The real API sends every RunConfig field; unset ones are null.
    "s4_tau": None,
    "s5_dossier_budget": None,
    "s7_max_tool_steps": None,
    "rrf_k": None,
    "query_transform": None,
}
PRESETS = [
    {
        "slug": "recommended",
        "label": "Recommended",
        "is_champion": True,
        "description": "Picks the best method for each question.",
        "config": {**_BASE_CONFIG, "system_id": "S8"},
    },
    {
        "slug": "fast",
        "label": "Fast",
        "is_champion": False,
        "description": "A quick keyword search. Good for simple lookups.",
        "config": {**_BASE_CONFIG, "system_id": "S1", "retriever": "R1"},
    },
    {
        "slug": "deep",
        "label": "Deep read",
        "is_champion": False,
        "description": "Reads a bug's full history before answering. Slower.",
        "config": {**_BASE_CONFIG, "system_id": "S5"},
    },
]
_ALL = ["R0", "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "ORACLE"]
HYPERPARAMETERS = {
    "system_id": {
        "type": "choice",
        "default": "S2",
        "label": "Answering method",
        "help": "",
        "applies_to": _ALL,
        "advanced": False,
        "choices": _ALL,
    },
    "top_k": {
        "type": "integer",
        "default": 5,
        "label": "Sources to retrieve",
        "min": 1,
        "max": 50,
        "help": "How many search results the assistant reads first.",
        "advanced": True,
        "applies_to": ["R0", "S1", "S2", "S3", "S4", "S5", "S6", "S8"],
    },
    "temperature": {
        "type": "number",
        "default": 0.0,
        "label": "Answer variability",
        "min": 0.0,
        "max": 1.0,
        "help": "Zero gives the most repeatable answers.",
        "advanced": True,
        "applies_to": _ALL[1:],
    },
    "context_budget_tokens": {
        "type": "integer",
        "default": 3000,
        "label": "Evidence budget",
        "min": 128,
        "max": 4096,
        "help": "How much evidence text the model may read.",
        "advanced": True,
        "applies_to": _ALL[1:],
    },
    "s7_max_tool_steps": {
        "type": "integer",
        "default": 4,
        "label": "Tool steps",
        "min": 1,
        "max": 4,
        "help": "Maximum lookups before answering.",
        "advanced": True,
        "applies_to": ["S7", "S8"],
    },
    "rrf_k": {
        "type": "integer",
        "default": 60,
        "label": "Rank fusion constant",
        "min": 1,
        "max": 200,
        "help": "Controls fusion for hybrid and transformed searches.",
        "advanced": True,
        "applies_to": ["R0", "S2", "S3", "S4", "S5", "S6", "S7", "S8"],
    },
}
MODELS = {
    "gpt-oss-20b": {
        "provider": "groq",
        "model_id": "openai/gpt-oss-20b",
        "label": "GPT OSS 20B",
        "rpm": 30,
        "rpd": 1000,
        "tpm": 8000,
        "tpd": 200000,
        "max_context_tokens": 4096,
    }
}
EXAMPLES = [
    "Which component is bug 1000001 filed under?",
    "How many bugs in the sample concern Session Restore?",
    "Which bugs does bug 1000002 depend on?",
    # The real bundle's examples read like benchmark prompts; the UI rewrites this one.
    "Using the specified frozen evidence, what resolution is recorded for Firefox bug 1000003? "
    "The source snapshot date is UNKNOWN.",
]


def _evidence(bug_id: int, text: str, score: float) -> dict[str, Any]:
    return {
        "chunk_id": f"C1:demo{bug_id}:0",
        "bug_id": str(bug_id),
        "snippet": f"[demo data] {text}",
        "score": score,
        "url": f"https://bugzilla.mozilla.org/show_bug.cgi?id={bug_id}",
    }


def answer_record(question: str) -> dict[str, Any]:
    """A contract-shaped AnswerRecord for any question."""
    evidence = [
        _evidence(
            1000001, "Component: Session Restore. Tabs are not restored after an update.", 0.91
        ),
        _evidence(
            1000002, "Depends on 1000004. Crash in the session store writer on shutdown.", 0.84
        ),
        _evidence(
            1000003, "Resolved DUPLICATE of 1000001. Same restore failure after update.", 0.77
        ),
    ]
    abstain = "unknown" in question.lower()
    degraded = "quota" in question.lower()
    answer = {
        "abstain": abstain or degraded,
        "answer": None,
        "answer_type": "string",
        "bug_ids": [],
        "citations": [],
        "rationale": "Not enough evidence in the archive.",
    }
    if degraded:
        answer["rationale"] = (
            "Free quota exhausted; showing sources without generating answer text."
        )
    elif not abstain:
        answer = {
            "abstain": False,
            "answer_type": "string",
            "bug_ids": [1000001, 1000003],
            "citations": [evidence[0]["chunk_id"], evidence[2]["chunk_id"]],
            "answer": "This is a demo answer. Bug 1000001 is filed under Session Restore, and "
            "bug 1000003 was closed as a duplicate of it.",
            "rationale": "Both reports describe tabs not being restored after an update.",
        }
    return {
        "answer": answer,
        "route": "R0" if degraded else "S2",
        "route_rule": "demo",
        "evidence": evidence,
        "tokens": {"input": 0, "output": 0},
        "llm_calls": 0 if degraded else 1,
        "cache_hits": 0,
        "latency_ms": 1840.0,
        "degraded": degraded,
        "errors": [],
        "config_hash": CONFIG_HASH,
    }


@dataclass
class Response:
    status: int
    body: Any = None  # JSON-serialisable, or an iterator of SSE strings when streaming
    headers: dict[str, str] = field(default_factory=dict)
    stream: bool = False


class MockBackend:
    """Pure request -> Response logic, shared by the HTTP server and the test transport."""

    def __init__(self, delay_s: float = 0.0, ready: bool = True):
        self.delay_s = delay_s
        self.ready = ready
        self.feedback: dict[str, dict[str, Any]] = {}
        self.requests: list[dict[str, Any]] = []

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes) -> Response:
        if path == "/v1/health":
            return Response(200, {"status": "ok"})
        if headers.get("x-api-key") != API_KEY:
            return _error(401, "internal", "Missing or invalid API key")
        if not self.ready:
            return _error(503, "internal", "API is not ready")
        payload = json.loads(body or b"{}")
        routes = {
            ("GET", "/v1/ready"): lambda: Response(200, {"status": "ok"}),
            ("GET", "/v1/presets"): lambda: Response(200, PRESETS),
            ("GET", "/v1/options"): lambda: Response(
                200, {"models": MODELS, "hyperparameters": HYPERPARAMETERS, "presets": PRESETS}
            ),
            ("GET", "/v1/examples"): lambda: Response(200, EXAMPLES),
            ("GET", "/v1/quota"): lambda: Response(
                200,
                {
                    "models": [
                        {
                            "model": "openai/gpt-oss-20b",
                            "used_requests": 12,
                            "limit_requests": 900,
                            "used_tokens": 9000,
                            "limit_tokens": 180000,
                            "degraded_now": False,
                        }
                    ]
                },
            ),
            ("POST", "/v1/ask"): lambda: self._ask(payload),
            ("POST", "/v1/chat/stream"): lambda: self._stream(payload),
            ("POST", "/v1/feedback"): lambda: self._feedback(payload),
        }
        route = routes.get((method, path))
        return route() if route else _error(404, "internal", "Not found")

    def _stream(self, payload: dict[str, Any]) -> Response:
        self.requests.append(payload)
        overrides = payload.get("overrides") or {}
        if "top_k" in overrides and not 1 <= overrides["top_k"] <= 20:
            return _error(422, "invalid_config", "top_k: outside [1, 20] for this demo")
        question = str(payload.get("message", ""))
        if "slow down" in question.lower():
            return _error(
                429, "rate_limited", "Six questions per session are allowed per minute", 30
            )
        return Response(
            200, self._events(question), {"Content-Type": "text/event-stream"}, stream=True
        )

    def _ask(self, payload: dict[str, Any]) -> Response:
        """Non-streaming answer: the same record the stream ends with."""
        self.requests.append(payload)
        request_id = str(uuid4())
        self.feedback.setdefault(request_id, {})
        record = answer_record(str(payload.get("message", "")))
        return Response(200, {"request_id": request_id, "record": record, "langsmith_run_id": None})

    def _events(self, question: str) -> Iterator[str]:
        request_id = str(uuid4())
        steps = [
            ("retrieving", "Searching public evidence"),
            ("retrieved", "Found 3 sources"),
            ("generating", "Preparing answer from supplied evidence"),
        ]
        for stage, detail in steps:
            time.sleep(self.delay_s)
            yield _sse("status", {"stage": stage, "detail": detail})
        if "broken" in question.lower():
            yield _sse(
                "error",
                {"code": "internal", "message": "Answer generation failed", "retry_after": None},
            )
        else:
            record = answer_record(question)
            yield _sse("evidence", {"items": record["evidence"]})
            yield _sse("answer", record)
            self.feedback.setdefault(request_id, {})
        yield _sse("done", {"request_id": request_id, "langsmith_run_id": None})

    def _feedback(self, payload: dict[str, Any]) -> Response:
        if payload.get("request_id") not in self.feedback:
            return _error(404, "invalid_config", "request_id: unknown request")
        self.feedback[payload["request_id"]] = payload
        return Response(200, {"status": "ok"})


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _error(status: int, code: str, message: str, retry_after: int | None = None) -> Response:
    headers = {"Retry-After": str(retry_after)} if retry_after else {}
    return Response(status, {"code": code, "message": message, "retry_after": retry_after}, headers)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    backend = MockBackend(delay_s=0.6)

    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            headers = {k.lower(): v for k, v in self.headers.items()}
            response = backend.handle(method, self.path, headers, self.rfile.read(length))
            self.send_response(response.status)
            for key, value in response.headers.items():
                self.send_header(key, value)
            if response.stream:
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for chunk in response.body:
                    self.wfile.write(chunk.encode())
                    self.wfile.flush()
                return
            data = json.dumps(response.body).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def log_message(self, *args: Any) -> None:
            pass

    print(f"Mock API (demo data) on http://{host}:{port}  key={API_KEY!r}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve(port=int(os.environ.get("MOCK_PORT", "8000")))

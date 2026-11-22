"""Serve authenticated questions, streamed answers, presets and local feedback."""

import asyncio
import hmac
import json
import os
import queue
import sqlite3
from collections import OrderedDict
from contextlib import asynccontextmanager, closing
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from bugzilla_qa.llm.provider import env_values
from bugzilla_serving.bundle import load_bundle
from bugzilla_serving.contracts.api_models import (
    AskResponse,
    ChatRequest,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    OptionsResponse,
    Preset,
    QuotaResponse,
    StatusResponse,
)
from bugzilla_serving.contracts.records import DoneEvent, ErrorEvent, EvidenceEvent
from bugzilla_serving.contracts.run_config import ROOT, RunConfig, config_hash, load_spec
from bugzilla_serving.engine import build_runner

from .presets import PresetStore


def fail(status, code, message, retry_after=None):
    raise HTTPException(
        status, detail={"code": code, "message": message, "retry_after": retry_after}
    )


def save_request(path, request_id):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO requests(request_id) VALUES (?)", (request_id,))


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        values = env_values(ROOT / ".env")
        for key, value in values.items():
            if key in (
                "BUNDLE_DIR",
                "SERVING_API_KEY",
                "LLM_PROVIDER",
                "GROQ_API_KEY",
                "MLFLOW_TRACKING_URI",
                "MLFLOW_TRACKING_USERNAME",
                "MLFLOW_TRACKING_PASSWORD",
            ):
                os.environ.setdefault(key, value)
        if not os.environ.get("SERVING_API_KEY"):
            raise RuntimeError("SERVING_API_KEY must be configured")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "3")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
        app.state.ready = False
        app.state.api_key = os.environ["SERVING_API_KEY"]
        app.state.spec = load_spec()
        app.state.presets = PresetStore()
        app.state.runners = OrderedDict()
        app.state.runner_lock = asyncio.Lock()
        app.state.jobs = set()
        app.state.bundle = await run_in_threadpool(load_bundle, os.environ["BUNDLE_DIR"])
        folder = Path(os.environ.get("SERVING_STATE_DIR", ROOT / "outputs/serving"))
        folder.mkdir(parents=True, exist_ok=True)
        app.state.feedback_db = folder / "feedback.sqlite"
        try:
            with closing(sqlite3.connect(app.state.feedback_db)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY)")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS feedback(request_id TEXT PRIMARY KEY, "
                    "score INTEGER NOT NULL, comment TEXT, "
                    "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
                )
            await run_in_threadpool(app.state.presets.get)
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            if app.state.jobs:
                await asyncio.gather(*app.state.jobs, return_exceptions=True)
            for runner in app.state.runners.values():
                runner.close()
            app.state.bundle.close()

    app = FastAPI(title="Bugzilla QA", version="1.0.0", lifespan=lifespan)
    app.state.ready = False
    errors = {501: {"model": ErrorResponse}}

    def authorize(request: Request):
        supplied = request.headers.get("X-API-Key", "")
        expected = getattr(app.state, "api_key", "")
        if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
            fail(401, "internal", "Missing or invalid API key")

    protected = [Depends(authorize)]

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        content = (
            error.detail
            if isinstance(error.detail, dict)
            else {
                "code": "internal",
                "message": str(error.detail),
            }
        )
        headers = {"Retry-After": str(content["retry_after"])} if content.get("retry_after") else {}
        return JSONResponse(status_code=error.status_code, content=content, headers=headers)

    def quota_status():
        from bugzilla_qa.answering.runner import quota_report

        report = quota_report({"llm_config": "configs/llm.yaml"}, ROOT)
        models = []
        for option in app.state.spec["models"].values():
            known = option["model_id"] == report["model"]
            requests = report["local_guard_day_requests"] if known else 0
            tokens = report["local_guard_day_reported_success_tokens"] if known else 0
            models.append(
                dict(
                    model=option["model_id"],
                    used_requests=requests,
                    limit_requests=option["rpd"],
                    used_tokens=tokens,
                    limit_tokens=option["tpd"],
                    degraded_now=bool(
                        requests >= int(option["rpd"] * 0.9)
                        or known
                        and report["known_cooldown_active"]
                    ),
                )
            )
        return QuotaResponse(models=models)

    def quota_check(config):
        if config.provider == "mock" or config.system_id == "R0":
            return
        current = next(m for m in quota_status().models if m.model == config.model)
        if current.degraded_now:
            fail(429, "rate_limited", "Local provider request guard or cooldown is active", 60)

    app.state.quota_check = quota_check

    def configuration(body):
        presets = app.state.presets.get()
        slug = body.preset_slug
        if slug is None:
            preset = next((p for p in presets if p.is_champion), presets[0])
        else:
            preset = next((p for p in presets if p.slug == slug), None)
            if preset is None:
                fail(422, "invalid_config", "preset_slug: unknown preset")
        merged = preset.config.model_dump()
        merged["provider"] = os.environ.get("LLM_PROVIDER", merged["provider"])
        merged.update(body.overrides or {})
        try:
            config = RunConfig(**merged).validate_against(app.state.spec)
            corpora = app.state.bundle.manifest.get("available_corpora", ["C0", "C1", "C2"])
            if config.corpus not in corpora:
                raise ValueError("corpus: not included in this bundle")
            return config
        except ValidationError as error:
            fields = ", ".join(".".join(map(str, e["loc"])) for e in error.errors())
            fail(422, "invalid_config", fields + ": invalid value")
        except ValueError as error:
            fail(422, "invalid_config", str(error))

    def run(config, message, on_event):
        key = config_hash(config)
        runners = app.state.runners
        if key not in runners:
            if len(runners) >= 4:
                _, old = runners.popitem(last=False)
                old.close()
            runners[key] = build_runner(config)
        runners.move_to_end(key)
        runner = runners[key]
        if hasattr(runner.provider, "max_requests"):
            runner.provider.max_requests = runner.provider.calls + 32
        record = runner.run(message, on_event=on_event)
        if record.errors:
            raise RuntimeError("Runner did not complete successfully")
        return record

    async def prepare(body):
        if not app.state.ready:
            fail(503, "internal", "API is not ready")
        if not body.message.strip():
            fail(422, "invalid_config", "message: must not be blank")
        return await run_in_threadpool(configuration, body)

    @app.get("/v1/health", response_model=StatusResponse)
    def health():
        return StatusResponse(status="ok")

    @app.get(
        "/v1/ready",
        name="unavailable",
        response_model=StatusResponse,
        responses=errors,
        dependencies=protected,
    )
    def ready():
        if not app.state.ready:
            fail(503, "internal", "API is not ready")
        return StatusResponse(status="ok")

    @app.get(
        "/v1/options",
        name="unavailable",
        response_model=OptionsResponse,
        responses=errors,
        dependencies=protected,
    )
    def options():
        return OptionsResponse(
            models=app.state.spec["models"],
            hyperparameters=app.state.spec["hyperparameters"],
            presets=app.state.presets.get(),
        )

    @app.get(
        "/v1/presets",
        name="unavailable",
        response_model=list[Preset],
        responses=errors,
        dependencies=protected,
    )
    def presets():
        return app.state.presets.get()

    @app.get(
        "/v1/examples",
        name="unavailable",
        response_model=list[str],
        responses=errors,
        dependencies=protected,
    )
    def examples():
        return app.state.bundle.examples()

    @app.get(
        "/v1/quota",
        name="unavailable",
        response_model=QuotaResponse,
        responses=errors,
        dependencies=protected,
    )
    def quota():
        return quota_status()

    @app.post("/v1/ask", response_model=AskResponse, responses=errors, dependencies=protected)
    async def ask(body: ChatRequest):
        config = await prepare(body)
        request_id = str(uuid4())
        async with app.state.runner_lock:
            await run_in_threadpool(app.state.quota_check, config)
            try:
                record = await run_in_threadpool(run, config, body.message, None)
                await run_in_threadpool(save_request, app.state.feedback_db, request_id)
            except Exception:
                fail(500, "internal", "Answer generation failed")
        return AskResponse(request_id=request_id, record=record, langsmith_run_id=None)

    @app.post(
        "/v1/chat/stream",
        responses={
            **errors,
            200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}},
        },
        dependencies=protected,
    )
    async def stream(body: ChatRequest):
        config = await prepare(body)
        request_id = str(uuid4())
        events = queue.Queue()

        async def work():
            async with app.state.runner_lock:
                try:
                    await run_in_threadpool(app.state.quota_check, config)
                    record = await run_in_threadpool(run, config, body.message, events.put)
                    await run_in_threadpool(save_request, app.state.feedback_db, request_id)
                    events.put(
                        EvidenceEvent(data={"items": record.evidence}).model_dump(mode="json")
                    )
                    events.put({"event": "answer", "data": record.model_dump(mode="json")})
                except HTTPException as error:
                    events.put(ErrorEvent(data=error.detail).model_dump(mode="json"))
                except Exception:
                    events.put(
                        ErrorEvent(
                            data={"code": "internal", "message": "Answer generation failed"}
                        ).model_dump(mode="json")
                    )
                finally:
                    events.put(DoneEvent(data={"request_id": request_id}).model_dump(mode="json"))
                    events.put(None)

        async def content():
            job = asyncio.create_task(work())
            app.state.jobs.add(job)
            job.add_done_callback(app.state.jobs.discard)
            while True:
                try:
                    event = events.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue
                if event is None:
                    break
                yield "event: " + event["event"] + "\ndata: " + json.dumps(event["data"]) + "\n\n"

        return StreamingResponse(
            content(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post(
        "/v1/feedback", response_model=FeedbackResponse, responses=errors, dependencies=protected
    )
    def feedback(body: FeedbackRequest):
        with closing(sqlite3.connect(app.state.feedback_db)) as db, db:
            if not db.execute(
                "SELECT 1 FROM requests WHERE request_id=?", (body.request_id,)
            ).fetchone():
                fail(404, "invalid_config", "request_id: unknown request")
            db.execute(
                "INSERT INTO feedback(request_id,score,comment) VALUES (?,?,?) "
                "ON CONFLICT(request_id) DO UPDATE SET score=excluded.score, "
                "comment=excluded.comment, updated_at=CURRENT_TIMESTAMP",
                (body.request_id, body.score, body.comment),
            )
        return FeedbackResponse(status="ok")

    return app


app = create_app()

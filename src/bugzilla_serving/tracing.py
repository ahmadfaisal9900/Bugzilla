"""Sample sanitized serving traces, cap daily attempts and attach optional remote feedback."""

import hashlib
import logging
import os
import re
import sqlite3
from contextlib import ExitStack, closing
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from langsmith import Client, trace, tracing_context
from urllib3.util.retry import Retry

from bugzilla_qa.answering.contracts import clean
from bugzilla_qa.llm.provider import env_values
from bugzilla_serving.contracts.names import (
    FEEDBACK_KEY,
    LANGSMITH_PROJECTS,
    TRACE_METADATA_KEYS,
    validate_trace_metadata,
)
from bugzilla_serving.contracts.records import AnswerRecord
from bugzilla_serving.contracts.run_config import ROOT, config_hash

PROJECT = LANGSMITH_PROJECTS[0]
_ACTIVE = ContextVar("serving_trace_active", default=False)


def _redact(value):
    secrets = sorted(
        {
            v
            for source in (env_values(ROOT / ".env"), os.environ)
            for k, v in source.items()
            if v and re.search(r"(?:^|_)(?:KEY|TOKEN|PASSWORD|SECRET)(?:_|$)", k.upper())
        },
        key=len,
        reverse=True,
    )

    def walk(item):
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[redacted]")
        elif isinstance(item, dict):
            item = {k: walk(v) for k, v in item.items()}
        elif isinstance(item, (list, tuple)):
            item = type(item)(walk(v) for v in item)
        return item

    return walk(value)


def sanitize(value):
    return _redact(clean(value))


class SafeClient(Client):
    def create_run(self, *args, **kwargs):
        return super().create_run(*_redact(args), **_redact(kwargs))

    def update_run(self, *args, **kwargs):
        return super().update_run(*_redact(args), **_redact(kwargs))


class SecretFilter(logging.Filter):
    def filter(self, record):
        record.msg = _redact(record.getMessage())
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


def client():
    values = env_values(ROOT / ".env")
    key = os.environ.get("LANGSMITH_API_KEY") or values.get("LANGSMITH_API_KEY")
    if not key or key == "replace_locally":
        return None
    for name in ("langsmith.client", "langsmith.run_helpers", "langsmith.run_trees"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, SecretFilter) for f in logger.filters):
            logger.addFilter(SecretFilter())
    try:
        return SafeClient(
            api_key=key,
            api_url=os.environ.get("LANGSMITH_ENDPOINT")
            or values.get("LANGSMITH_ENDPOINT")
            or "https://api.smith.langchain.com",
            auto_batch_tracing=False,
            retry_config=Retry(total=0),
            timeout_ms=5000,
        )
    except Exception:
        return None


def active():
    return _ACTIVE.get()


def should_trace(request_id, *, sample=0.2, daily_cap=150, db_path=None, day=None):
    if not 0 <= sample <= 1 or daily_cap < 0:
        raise ValueError("Invalid tracing sample or daily cap")
    fraction = int(hashlib.sha256(request_id.encode()).hexdigest()[:16], 16) / 2**64
    if fraction >= sample or daily_cap == 0:
        return False
    path = Path(db_path or ROOT / "outputs/serving/feedback.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    day = day or datetime.now(timezone.utc).date().isoformat()
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS trace_budget(request_id TEXT PRIMARY KEY, day TEXT)")
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM trace_budget WHERE request_id=?", (request_id,)).fetchone():
            return False
        if (
            db.execute("SELECT count(*) FROM trace_budget WHERE day=?", (day,)).fetchone()[0]
            >= daily_cap
        ):
            return False
        db.execute("INSERT INTO trace_budget VALUES (?,?)", (request_id, day))
    return True


def root_metadata(config, preset_slug, request_id, session_id, *, route=None, degraded=False):
    metadata = sanitize(
        dict(
            config_hash=config_hash(config),
            preset_slug=preset_slug or "custom",
            system_id=config.system_id,
            model=config.model,
            retriever=config.retriever,
            corpus=config.corpus,
            route=route or config.system_id,
            degraded=degraded,
            request_id=request_id,
            session_id=session_id,
        )
    )
    assert set(metadata) == TRACE_METADATA_KEYS
    validate_trace_metadata(metadata)
    return metadata


class Tracer:
    def __init__(self, db_path, *, sample=0.2, daily_cap=150):
        if not 0 <= sample <= 1 or daily_cap < 0:
            raise ValueError("Invalid tracing sample or daily cap")
        self.db_path, self.sample, self.daily_cap = db_path, sample, daily_cap
        self.client = client() if sample > 0 else None

    def run(self, config, message, preset_slug, request_id, session_id, invoke):
        stack, root, run_id = ExitStack(), None, None
        try:
            enabled = self.client is not None and should_trace(
                request_id,
                sample=self.sample,
                daily_cap=self.daily_cap,
                db_path=self.db_path,
            )
            stack.enter_context(
                tracing_context(enabled=enabled, client=self.client, project_name=PROJECT)
            )
            if enabled:
                metadata = root_metadata(
                    config, preset_slug, request_id, session_id, degraded=config.system_id == "R0"
                )
                root = stack.enter_context(
                    trace(
                        "Bugzilla chat",
                        inputs=sanitize({"question": message}),
                        metadata=metadata,
                        client=self.client,
                        project_name=PROJECT,
                    )
                )
        except Exception:
            try:
                stack.close()
            except Exception:
                pass
            stack, root = ExitStack(), None
            stack.enter_context(tracing_context(enabled=False))
        token = _ACTIVE.set(root is not None)
        try:
            record = invoke()
            record = AnswerRecord.model_validate(sanitize(record.model_dump(mode="json")))
            if root:
                try:
                    root.add_metadata(
                        root_metadata(
                            config,
                            preset_slug,
                            request_id,
                            session_id,
                            route=record.route,
                            degraded=record.degraded,
                        )
                    )
                    root.end(outputs=sanitize(record.model_dump(mode="json")))
                    run_id = str(root.id)
                except Exception:
                    pass
            return record, run_id
        except Exception as error:
            if root:
                try:
                    root.end(error=type(error).__name__)
                except Exception:
                    pass
            raise
        finally:
            _ACTIVE.reset(token)
            try:
                stack.close()
            except Exception:
                pass

    def feedback(self, run_id, score, comment):
        if not run_id:
            return False
        target = self.client or client()
        if target is None:
            return False
        try:
            target.create_feedback(run_id, key=FEEDBACK_KEY, score=score, comment=sanitize(comment))
            return True
        except Exception:
            return False

    def close(self):
        self.client = None

"""Exactly one marked synthetic trace and one feedback, without an LLM call."""

import datetime as dt
import time
import uuid

from bugzilla_serving.contracts.names import (
    FEEDBACK_KEY,
    LANGSMITH_PROJECTS,
    TRACE_METADATA_KEYS,
    validate_trace_metadata,
)
from bugzilla_serving.contracts.run_config import RunConfig, config_hash


def smoke(client, cfg=None):
    cfg = cfg or RunConfig(provider="mock")
    run_id = uuid.uuid4()
    now = dt.datetime.now(dt.timezone.utc)
    metadata = dict(
        config_hash=config_hash(cfg),
        preset_slug="recommended",
        system_id=cfg.system_id,
        model=cfg.model,
        retriever=cfg.retriever,
        corpus=cfg.corpus,
        route=cfg.system_id,
        degraded=False,
        request_id=str(run_id),
        session_id="stream-b-smoke",
        smoke=True,
    )
    validate_trace_metadata(metadata)
    assert TRACE_METADATA_KEYS <= metadata.keys()
    client.create_run(
        id=run_id,
        name="Stream B integration smoke",
        run_type="chain",
        project_name=LANGSMITH_PROJECTS[0],
        inputs={},
        start_time=now,
        extra={"metadata": metadata},
    )
    client.update_run(
        run_id,
        end_time=dt.datetime.now(dt.timezone.utc),
        outputs={"record": {"answer": {"abstain": True}}},
    )
    client.create_feedback(run_id, FEEDBACK_KEY, score=1, comment="Synthetic integration smoke")
    # Accepted writes may not be immediately visible in the read index.
    from langsmith.utils import LangSmithNotFoundError

    for attempt in range(6):
        try:
            saved = client.read_run(run_id)
            break
        except LangSmithNotFoundError:
            if attempt == 5:
                raise
            time.sleep(1)
    return dict(
        run_id=str(run_id),
        url=client.get_run_url(run=saved, project_name=LANGSMITH_PROJECTS[0]),
        smoke=True,
        llm_calls=0,
    )

"""Read-only config resolution and bounded engine/API parity comparisons."""

from __future__ import annotations

import json

from bugzilla_serving.contracts.api_models import AskResponse
from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.experiments.data import load_eval_set


def resolve_config(source="champion", tracking_uri=None):
    from bugzilla_serving.tracking.registry import Registry

    registry = Registry(tracking_uri)
    if source == "champion":
        version = registry.get_champion()
        if version is None:
            raise ValueError("No registry champion; YAML fallback is deliberately not used")
        return registry.get_config(version.version)
    if not source.startswith("run:") or not source[4:]:
        raise ValueError("config-source must be champion or run:ID")
    run = registry.client.get_run(source[4:])
    if run.data.tags.get("split") != "dev":
        raise ValueError("Only a dev run can supply config")
    values = {}
    for key in RunConfig.model_fields:
        value = run.data.params[key]
        try:
            values[key] = json.loads(value)
        except (TypeError, ValueError):
            values[key] = value
    return RunConfig(**values).validate_against()


def comparable(record):
    return dict(
        answer=json.dumps(record.answer.answer, ensure_ascii=False, sort_keys=True),
        abstained=record.answer.abstain,
        cited_bug_ids=sorted(
            {str(b) for b in record.answer.bug_ids}
            | {e.bug_id for e in record.evidence if e.chunk_id in record.answer.citations}
        ),
        config_hash=record.config_hash,
    )


def check(cfg, items, api_url, *, client=None, build=None, provider="mock", max_requests=8):
    import httpx
    from langsmith import tracing_context

    from bugzilla_serving.engine import _mock_provider, build_runner
    from bugzilla_serving.experiments.runner import live_provider

    cfg = cfg.model_copy(update={"provider": provider}).validate_against()
    selected = _mock_provider() if provider == "mock" else live_provider(cfg, max_requests, ROOT)
    owned = client is None
    client = client or httpx.Client(timeout=120)
    result = []
    try:
        with (
            tracing_context(enabled=False),
            (build or build_runner)(cfg, provider=selected) as engine,
        ):
            for item in items:
                local = comparable(engine.run(item["question"]))
                try:
                    response = client.post(
                        api_url.rstrip("/") + "/v1/ask",
                        json=dict(
                            session_id="parity-smoke",
                            message=item["question"],
                            overrides=cfg.model_dump(mode="json"),
                        ),
                    )
                    if response.status_code != 200:
                        result.append(
                            dict(
                                question=item["qid"],
                                match=False,
                                error=f"API HTTP {response.status_code}",
                                **{k: False for k in local},
                            )
                        )
                        continue
                    remote = comparable(AskResponse.model_validate(response.json()).record)
                    equal = {key: local[key] == remote[key] for key in local}
                    result.append(
                        dict(question=item["qid"], match=all(equal.values()), error="", **equal)
                    )
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    result.append(
                        dict(
                            question=item["qid"],
                            match=False,
                            error=f"API {type(exc).__name__}",
                            **{k: False for k in local},
                        )
                    )
    finally:
        if owned:
            client.close()
    return result


def questions(n):
    if not 1 <= n <= 5:
        raise ValueError("n must be between 1 and 5 (smoke-5 only)")
    return load_eval_set("smoke-5", n)[0]

"""Preview or verify one real LangSmith trace and feedback using a mock answer."""

import argparse
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from bugzilla_qa.llm.provider import env_values
from bugzilla_serving.contracts.names import FEEDBACK_KEY, TRACE_METADATA_KEYS
from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.tracing import PROJECT, client, sanitize


def check(url):
    values = {**env_values(ROOT / ".env"), **os.environ}
    key = values.get("SERVING_API_KEY")
    if not key:
        raise ValueError("Set SERVING_API_KEY in .env first")
    ls = client()
    if ls is None:
        raise ValueError("Set LANGSMITH_API_KEY in .env first")
    if float(values.get("TRACE_SAMPLE", "0.2")) != 1:
        raise ValueError("Set TRACE_SAMPLE=1 and restart the API for this one check")
    with httpx.Client(base_url=url, headers={"X-API-Key": key}, timeout=60) as api:
        api.get("/v1/ready").raise_for_status()
        response = api.post(
            "/v1/ask",
            json={
                "session_id": "live-check-" + str(uuid4()),
                "message": "What component is bug 1701902 in?",
                "preset_slug": "fast",
                "overrides": {"provider": "mock"},
            },
        )
        response.raise_for_status()
        answer = response.json()
        run_id = answer["langsmith_run_id"]
        if not run_id:
            raise ValueError(
                "No trace ID returned; check the API sample setting, key and daily cap"
            )
        api.post(
            "/v1/feedback",
            json={
                "request_id": answer["request_id"],
                "score": 1,
                "comment": "Manual serving trace check",
            },
        ).raise_for_status()
    run = ls.read_run(run_id)
    metadata = (run.extra or {}).get("metadata", {})
    if not TRACE_METADATA_KEYS <= metadata.keys() or metadata["request_id"] != answer["request_id"]:
        raise ValueError("Remote trace metadata does not match the request")
    project = ls.read_project(project_id=str(run.session_id))
    if project.name != PROJECT:
        raise ValueError("Trace was not saved to the agreed serving project")
    feedback = list(ls.list_feedback(run_ids=[run_id], feedback_key=[FEEDBACK_KEY]))
    if not any(f.score == 1 for f in feedback):
        raise ValueError("Thumbs-up feedback was not found on the remote trace")
    result = dict(
        state="COMPLETE",
        verified_at_utc=datetime.now(timezone.utc).isoformat(),
        project=PROJECT,
        request_id=answer["request_id"],
        langsmith_run_id=run_id,
        run_url=ls.get_run_url(run=run),
        metadata=sanitize(metadata),
        feedback_score=1,
        llm_calls=answer["record"]["llm_calls"],
        provider="mock",
    )
    path = ROOT / "outputs/serving/a4_live_check.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print(
            json.dumps(
                {
                    "state": "DRY_RUN",
                    "url": args.url,
                    "project": PROJECT,
                    "actions": [
                        "one mock answer",
                        "one thumbs-up",
                        "read remote trace and feedback",
                    ],
                    "groq_calls": 0,
                }
            )
        )
        return
    try:
        print(json.dumps(check(args.url), indent=2))
    except Exception as error:
        parser.exit(1, sanitize(str(error)) + "\n")


if __name__ == "__main__":
    main()

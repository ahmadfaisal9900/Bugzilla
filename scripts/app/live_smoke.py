#!/usr/bin/env python3
"""Owner-run four-question dev smoke; refuses unsupported champions before inference."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from bugzilla_serving.contracts.run_config import ROOT, RunConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enable-llm", action="store_true")
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument(
        "--max-requests", type=int, default=4, help="API ask requests, not model calls"
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--feedback-score", type=int, choices=[0, 1])
    parser.add_argument("--bundle", type=Path, default=ROOT / "serving_bundle")
    parser.add_argument("--bug-id", default="")
    parser.add_argument("--comment-ref", default="")
    parser.add_argument("--search-question", default="Which report describes scrolling corruption?")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/serving/live-smoke")
    args = parser.parse_args()
    if not 1 <= args.limit <= 4 or not 1 <= args.max_requests <= 4:
        parser.error("--limit and --max-requests must be in 1..4")
    questions = [
        ("database path", f"What component is recorded for bug {args.bug_id}?", "S7v2"),
        (
            "dossier with cited comment",
            f"What reason is in cited comment {args.comment_ref} for bug {args.bug_id}?",
            "S5",
        ),
        ("Smart search", args.search_question, "S2"),
        ("abstention", f"How many engineer-hours were spent fixing bug {args.bug_id}?", None),
    ][: args.limit]
    if args.dry_run or not args.enable_llm:
        print(json.dumps(dict(state="DRY_RUN", actual_api_calls=0, questions=questions), indent=2))
        return 0
    if not args.bug_id.isdigit() or not args.comment_ref:
        parser.error("Supply a public dev --bug-id and --comment-ref from the verified bundle")
    from bugzilla_qa.llm.provider import env_values
    from bugzilla_serving.bundle import load_bundle

    values = env_values(ROOT / ".env")
    key = os.environ.get("SERVING_API_KEY") or values.get("SERVING_API_KEY")
    if not key:
        parser.error("Set SERVING_API_KEY locally")
    args.out.mkdir(parents=True, exist_ok=True)
    summary = dict(
        state="REFUSED",
        started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        actual_api_calls=0,
        actual_llm_calls=0,
        checks=[],
    )
    checkpoint = args.out / "summary.json"
    log = args.out / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".log")

    def save():
        summary["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(summary, indent=2) + "\n")
        temporary.replace(checkpoint)
        log.write_text(json.dumps(summary, indent=2) + "\n")

    try:
        import httpx

        with load_bundle(args.bundle) as bundle:
            if bundle.manifest.get("synthetic") is not False:
                raise ValueError("Live smoke requires a real dev bundle")
        url = os.environ.get("API_URL") or values.get("API_URL", "http://127.0.0.1:8000")
        with httpx.Client(base_url=url, headers={"X-API-Key": key}, timeout=180) as client:
            options = client.get("/v1/options")
            options.raise_for_status()
            champion = next((p for p in options.json()["presets"] if p["is_champion"]), None)
            if champion is None or champion["config"]["system_id"] != "S8v2":
                raise ValueError("No executable evaluated Auto-router champion; no ask sent")
            cfg = RunConfig(**champion["config"]).validate_against(mode="execute")
            if cfg.provider != "groq":
                raise ValueError("Live smoke requires the champion's Groq configuration")
            identity = hashlib.sha256(
                json.dumps([champion, questions, bundle.manifest], sort_keys=True).encode()
            ).hexdigest()
            if args.resume and checkpoint.exists():
                old = json.loads(checkpoint.read_text())
                if old.get("identity") != identity:
                    raise ValueError("Checkpoint inputs changed; use a different --out")
                summary = old
            summary.update(identity=identity, state="PARTIAL")
            save()
            completed = {row["probe"] for row in summary["checks"] if row["passed"]}
            for label, question, route in questions:
                if label in completed:
                    continue
                if summary["actual_api_calls"] >= args.max_requests:
                    break
                # Reserve before sending: crashes consume the request budget.
                summary["actual_api_calls"] += 1
                save()
                response = client.post(
                    "/v1/ask",
                    json=dict(
                        session_id="owner-live-smoke",
                        message=question,
                        preset_slug=champion["slug"],
                    ),
                )
                response.raise_for_status()
                value = response.json()
                record = value["record"]
                if args.feedback_score is not None:
                    feedback = client.post(
                        "/v1/feedback",
                        json=dict(
                            request_id=value["request_id"],
                            score=args.feedback_score,
                            comment="Owner live smoke feedback",
                        ),
                    )
                    feedback.raise_for_status()
                passed = (
                    not record["errors"]
                    and not record["degraded"]
                    and (record["route"] == route if route else record["answer"]["abstain"])
                )
                summary["actual_llm_calls"] += record["llm_calls"]
                summary["checks"].append(
                    dict(
                        probe=label,
                        passed=passed,
                        route=record["route"],
                        request_id=value["request_id"],
                        langsmith_run_id=value["langsmith_run_id"],
                        config_hash=record["config_hash"],
                        abstain=record["answer"]["abstain"],
                    )
                )
                save()
                if not passed:
                    break
            if len({r["probe"] for r in summary["checks"] if r["passed"]}) == len(questions):
                summary["state"] = "COMPLETE"
    except Exception as error:
        # Never serialize exception text, credentials, requests or response bodies.
        summary.update(state="REFUSED", error_class=type(error).__name__)
    save()
    print(json.dumps(summary, indent=2))
    print(f"Summary: {checkpoint}; log: {log}")
    return 0 if summary["state"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())

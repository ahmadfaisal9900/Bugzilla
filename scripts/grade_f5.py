#!/usr/bin/env python3
"""Plan by default; explicitly grade six existing dev F5 questions when enabled."""

import argparse
import json
from pathlib import Path

from bugzilla_serving.experiments.f5_grade import run
from bugzilla_serving.tracking.f5_gold import DEFAULT_VERDICTS


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path("outputs/evaluation/phase11/pilot125"))
    p.add_argument("--output", type=Path, default=DEFAULT_VERDICTS)
    p.add_argument("--max-requests", type=int, default=6)
    p.add_argument("--limit", type=int, default=6)
    p.add_argument("--enable-llm", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.dry_run and a.enable_llm:
        p.error("--dry-run and --enable-llm are mutually exclusive")
    import fcntl

    from bugzilla_serving.tracking.client import assert_no_secrets

    try:
        if a.enable_llm:
            a.output.parent.mkdir(parents=True, exist_ok=True)
            with a.output.with_suffix(".lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = run(
                    a.source, a.output, enable_llm=True, max_requests=a.max_requests, limit=a.limit
                )
        else:
            result = run(a.source, a.output, max_requests=a.max_requests, limit=a.limit)
    except Exception as exc:
        message = str(exc)
        try:
            assert_no_secrets(message)
        except ValueError:
            message = "Sensitive error details withheld"
        print(
            json.dumps(
                {
                    "state": "FAILED",
                    "error_type": type(exc).__name__,
                    "error": message,
                    "verdict_path": str(a.output),
                }
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(result, indent=2))
    if result["state"] == "PARTIAL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

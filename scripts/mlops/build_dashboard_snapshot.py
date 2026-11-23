#!/usr/bin/env python3
"""Fetch a dashboard snapshot explicitly; no inference or trace writes."""

import argparse
import json
import os

from bugzilla_serving.dashboard.data.mlflow_source import uri
from bugzilla_serving.dashboard.data.snapshot import build_snapshot, directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-uri")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--max-requests",
        type=int,
        default=1000,
        help="SDK-call cap; repeat to resume immutable artifact checkpoints",
    )
    parser.add_argument(
        "--profile-pages",
        action="store_true",
        help="Measure full Streamlit reruns after building the snapshot",
    )
    args = parser.parse_args()
    if args.max_requests < 1:
        parser.error("--max-requests must be positive")
    tracking = args.tracking_uri or uri()
    if args.dry_run:
        print(
            json.dumps(
                {"state": "DRY_RUN", "cache_dir": str(directory(tracking)), "inference_calls": 0}
            )
        )
        return
    from bugzilla_serving.dashboard.profiling import request_budget

    request_budget(args.max_requests)
    result = build_snapshot(tracking)
    report = {
        "state": "PARTIAL" if result["errors"] else "COMPLETE",
        **result["meta"],
        "errors": result["errors"],
    }
    if args.profile_pages:
        report["pages"] = profile_pages()
    print(json.dumps(report, indent=2))
    if result["errors"]:
        raise SystemExit(1)
    if os.environ.get("LANGSMITH_SOURCE") == "live":
        from bugzilla_serving.dashboard.data.langsmith_source import _production

        _production("live")


def profile_pages():
    import time

    from streamlit.testing.v1 import AppTest

    from bugzilla_serving.contracts.run_config import ROOT
    from bugzilla_serving.dashboard.profiling import events

    os.environ["DASHBOARD_PROFILE"] = "1"
    app = AppTest.from_file(
        str(ROOT / "src/bugzilla_serving/dashboard/app.py"), default_timeout=300
    )
    pages = [
        "overview",
        "answer_eval",
        "retrieval_eval",
        "cost_latency",
        "error_analysis",
        "experiment_lab",
        "compare_runs",
        "production",
    ]
    if os.environ.get("DASHBOARD_LAB_ENABLED") == "true":
        pages.insert(-1, "presets_page")
    app.run()  # warm imports and lazy details are measured on first visit below
    result = []
    for page in pages:
        app.switch_page("pages/" + page + ".py").run()
        offset = len(events())
        start = time.perf_counter()
        app.run()
        calls = events()[offset:]
        result.append(
            {
                "page": page,
                "total_seconds": round(time.perf_counter() - start, 4),
                "slowest_calls": sorted(
                    [r for r in calls if not r["call"].startswith("page.")],
                    key=lambda r: r["seconds"],
                    reverse=True,
                )[:3],
                "errors": [e.message for e in app.exception],
            }
        )
    return result


if __name__ == "__main__":
    main()

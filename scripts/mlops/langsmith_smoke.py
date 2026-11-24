#!/usr/bin/env python3
"""Write one explicitly marked LangSmith smoke trace and one rating; no model call."""

import json

from langsmith import Client

from bugzilla_serving.tracking.langsmith_smoke import smoke

if __name__ == "__main__":
    print(
        json.dumps(
            smoke(Client(auto_batch_tracing=False, timeout_ms=10000, tracing_sampling_rate=1.0)),
            indent=2,
        )
    )

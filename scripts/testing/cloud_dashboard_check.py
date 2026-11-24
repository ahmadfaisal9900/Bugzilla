#!/usr/bin/env python3
"""Render the cloud entrypoint offline; report peak RSS and reject engine/model imports."""

import argparse
import json
import os
import resource
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for key in (
        "MLFLOW_TRACKING_URI",
        "MLFLOW_TRACKING_USERNAME",
        "MLFLOW_TRACKING_PASSWORD",
        "DASHBOARD_PASSWORD",
        "DAGSHUB_REPO_URL",
        "LANGSMITH_PROJECT_URL",
    ):
        os.environ.pop(key, None)
    os.environ.update(DASHBOARD_LAB_ENABLED="false", DASHBOARD_ADVANCED="false")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "dashboard/streamlit_app.py"), default_timeout=15).run()
    if app.exception:
        raise AssertionError("Cloud dashboard AppTest failed")
    assert [t.label for t in app.tabs] == ["Results", "Compare", "How it works & links"]
    forbidden = (
        "torch",
        "sentence_transformers",
        "bugzilla_serving.engine",
        "bugzilla_serving.dashboard.lab",
    )
    assert not any(k in sys.modules for k in forbidden), "Engine/model import detected"
    peak_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    assert peak_bytes < 700 * 1024 * 1024, "Peak RSS exceeds the conservative dashboard budget"
    result = dict(
        state="PASS",
        peak_rss_bytes=peak_bytes,
        peak_rss_mib=round(peak_bytes / 2**20, 2),
        checked="AppTest render and no engine/torch imports",
        clean_venv=False,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

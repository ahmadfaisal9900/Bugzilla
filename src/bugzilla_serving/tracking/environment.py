"""Explicit local settings-file loading; no shell expansion and no secret output."""

import os
import re
import shlex
from pathlib import Path


def load_settings(path):
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key):
            raise ValueError(f"Invalid settings syntax at line {number}")
        # Dashboard/MLflow commands never need model-provider API keys.
        if not (
            key.startswith(("MLFLOW_", "DASHBOARD_"))
            or key
            in (
                "DAGSHUB_REPO_URL",
                "LANGSMITH_PROJECT_URL",
                "LANGSMITH_SOURCE",
                "LANGSMITH_TRACING",
                "BUNDLE_DIR",
            )
        ):
            continue
        value = value.strip()
        if value.startswith(('"', "'")):
            try:
                tokens = shlex.split(value, comments=True, posix=True)
            except ValueError:
                raise ValueError(f"Invalid quoted setting at line {number}") from None
            if len(tokens) != 1:
                raise ValueError(f"Invalid quoted setting at line {number}")
            value = tokens[0]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        os.environ.setdefault(key, value)

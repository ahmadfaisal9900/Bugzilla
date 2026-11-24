#!/usr/bin/env python3
"""Launch the dashboard with optional explicit settings and a compatible watcher setting."""

import argparse
import os
import sys
from pathlib import Path

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.tracking.environment import load_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    args, flags = parser.parse_known_args()
    if args.env_file:
        load_settings(args.env_file)
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT / "src/bugzilla_serving/dashboard/app.py"),
        "--server.port=8502",
        "--server.fileWatcherType=none",
        *flags,
    ]
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()

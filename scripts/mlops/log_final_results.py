#!/usr/bin/env python3
"""Preview final-result MLflow publication; --apply explicitly enables writes."""

import argparse
import json
from pathlib import Path

from bugzilla_serving.dashboard.results_source import PACK
from bugzilla_serving.tracking.final_results import publish


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=PACK)
    parser.add_argument("--tracking-uri")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("--env-file does not exist")
        from bugzilla_serving.tracking.environment import load_settings

        load_settings(args.env_file)
    result = publish(args.results_dir, args.tracking_uri, args.apply)
    print(result["computation"])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

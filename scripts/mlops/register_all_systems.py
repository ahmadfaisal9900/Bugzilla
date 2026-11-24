#!/usr/bin/env python3
"""Preview nine config registrations; --apply enables writes, champion has a separate gate."""

import argparse
import json
from pathlib import Path

from bugzilla_serving.dashboard.results_source import PACK
from bugzilla_serving.tracking.final_registry import register


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=PACK)
    parser.add_argument("--tracking-uri")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--move-champion", action="store_true")
    parser.add_argument(
        "--serving-demo", action="store_true", help="Prepare capped S8v2 and Deep read only"
    )
    parser.add_argument("--rollback-version", help="Explicit S2 version; requires --serving-demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("Choose --dry-run or --apply")
    if args.rollback_version and not args.serving_demo:
        parser.error("--rollback-version requires --serving-demo")
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("--env-file does not exist")
        from bugzilla_serving.tracking.environment import load_settings

        load_settings(args.env_file)
    if args.serving_demo:
        from bugzilla_serving.tracking.demo_registry import promote

        result = promote(
            args.tracking_uri, apply=args.apply, rollback_version=args.rollback_version
        )
    else:
        result = register(args.results_dir, args.tracking_uri, args.apply, args.move_champion)
    print(json.dumps(result, indent=2))
    if result["state"] == "REFUSED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

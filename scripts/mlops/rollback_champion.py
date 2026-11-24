#!/usr/bin/env python3
"""Preview champion rollback; mutation requires --apply and --reason."""

import argparse
import json

from bugzilla_serving.tracking.registry import Registry
from bugzilla_serving.tracking.rollback import rollback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to-version", type=int)
    parser.add_argument("--reason", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tracking-uri")
    args = parser.parse_args()
    if args.apply and not args.reason.strip():
        parser.error("--reason is required with --apply")
    try:
        result = rollback(Registry(args.tracking_uri), args.to_version, args.reason, args.apply)
    except ValueError as exc:
        print(json.dumps({"state": "REFUSED", "reason": str(exc)}, indent=2))
        raise SystemExit(1) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

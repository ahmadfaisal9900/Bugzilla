#!/usr/bin/env python3
"""Verify an accepted dev bundle without loading models or contacting services."""

import argparse
import json

from bugzilla_serving.experiments.bundle_verify import verify_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--rehash", action="store_true")
    args = parser.parse_args()
    result = verify_bundle(args.bundle, rehash=args.rehash)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Verified ✓" if result["ok"] else "Verified ✗")
        print("Available: " + ", ".join(result["available_corpora"]))
        print("Missing: " + ", ".join(result["missing_corpora"]))
        for error in result["errors"]:
            print(error)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

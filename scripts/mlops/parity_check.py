#!/usr/bin/env python3
"""Compare the same bounded dev questions through the Lab engine and an API."""

import argparse
import os
from pathlib import Path

from bugzilla_serving.experiments.parity import check, questions, resolve_config
from bugzilla_serving.experiments.preflight import bundle_preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--config-source", default="champion")
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--provider", choices=["mock", "groq"], default="mock")
    parser.add_argument("--tracking-uri")
    parser.add_argument("--bundle", type=Path, default=Path("serving_bundle"))
    parser.add_argument("--max-requests", type=int, default=8)
    args = parser.parse_args()
    cfg = resolve_config(args.config_source, args.tracking_uri)
    os.environ["BUNDLE_DIR"] = str(args.bundle.resolve())
    bundle_preflight(cfg, args.bundle)
    result = check(
        cfg, questions(args.n), args.api_url, provider=args.provider, max_requests=args.max_requests
    )
    print("Question | Answer | Abstained | Cited bugs | Config | Result")
    for row in result:
        flags = [
            "OK" if row.get(k) else "DIFF"
            for k in ("answer", "abstained", "cited_bug_ids", "config_hash")
        ]
        print(
            " | ".join(
                [
                    row["question"],
                    *flags,
                    row["error"] or ("MATCH" if row["match"] else "DIFFERENT"),
                ]
            )
        )
    return 0 if result and all(r["match"] for r in result) else 1


if __name__ == "__main__":
    raise SystemExit(main())

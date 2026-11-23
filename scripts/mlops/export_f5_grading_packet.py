#!/usr/bin/env python3
"""Export all sixty F5 answers as a blind, public-only offline judging packet."""

import argparse
import json
from pathlib import Path

from bugzilla_serving.experiments.f5_packet import export

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(export(bundle=args.bundle, ledger=args.ledger, output=args.output_dir), indent=2)
    )

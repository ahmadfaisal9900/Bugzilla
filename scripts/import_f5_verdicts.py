#!/usr/bin/env python3
"""Validate complete blind external judgments and bind them to source answers."""

import argparse
import json
from pathlib import Path

from bugzilla_serving.experiments.f5_packet import import_verdicts

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verdicts", type=Path, required=True)
    parser.add_argument("--judge", required=True)
    parser.add_argument("--packet-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            import_verdicts(args.verdicts, args.judge, args.packet_dir, args.output), indent=2
        )
    )

#!/usr/bin/env python3
"""Generate deterministic qid-only DEV sets; never opens locked test files."""

import argparse
from pathlib import Path

import yaml

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.experiments.data import catalog, make_sets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "configs/eval_sets.yaml")
    parser.add_argument("--seed", type=int, default=317)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    items, _ = catalog()
    spec = make_sets(items, args.seed)
    if not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(yaml.safe_dump(spec, sort_keys=False))
    print(
        yaml.safe_dump(
            {
                "state": "DRY_RUN" if args.dry_run else "WRITTEN",
                "sets": {k: len(v) for k, v in spec["sets"].items()},
            }
        )
    )


if __name__ == "__main__":
    main()

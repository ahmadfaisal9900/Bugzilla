#!/usr/bin/env python3
"""Extend the saved B8 pack with route-weighted system_cost.csv, without model calls."""

import argparse
import json
from pathlib import Path

from bugzilla_serving.dashboard.results_source import PACK
from bugzilla_serving.tracking.final_results import write_cost


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=PACK)
    args = parser.parse_args()
    if not (args.results_dir / "final_scores.csv").exists():
        builder = PACK / "build_results_pack.py"
        if args.results_dir.resolve() == PACK.resolve() and builder.is_file():
            import runpy

            runpy.run_path(str(builder), run_name="__main__")
        else:
            raise SystemExit(
                "B8 inputs missing. Restore the saved results pack or set "
                "MLFLOW_TRACKING_URI for the dashboard artifact fallback. "
                "The original B8 builder and saved development ledgers are required "
                "to regenerate accuracy without model calls."
            )
    calculation = write_cost(args.results_dir)
    print(calculation)
    print(
        json.dumps(
            dict(
                state="COMPLETE",
                actual_llm_calls=0,
                output=str(args.results_dir / "system_cost.csv"),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

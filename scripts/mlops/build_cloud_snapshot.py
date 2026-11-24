#!/usr/bin/env python3
"""Bounded dev-results snapshot: aggregate allowlists and qid-only verdict rows."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import yaml

from bugzilla_serving.contracts.run_config import ROOT
from bugzilla_serving.dashboard.results_source import HEADERS, PACK, read_pack


def build(source, output, dry_run=False):
    # Fixed B8/B9 export only. Never discover or ingest raw questions, gold or test files.
    source, output = Path(source), Path(output)
    manifest = dict(
        eval_set="dev-pilot-122",
        split="dev",
        question_text=False,
        gold=False,
        test_data=False,
        files={},
        dev_roster_sha256=hashlib.sha256(
            (ROOT / "configs/eval_sets.yaml").read_bytes()
        ).hexdigest(),
    )
    for name, allowed in HEADERS.items():
        path = source / name
        if path.stat().st_size > 500_000:
            raise ValueError("Snapshot source is unexpectedly large")
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            columns = [c for c in reader.fieldnames if c in allowed]
            if set(columns) != allowed:
                raise ValueError("Missing allowlisted headers: " + name)
            rows = list(reader)
        if len(rows) > 2000:
            raise ValueError("Too many rows for a bounded dev snapshot")
        if name == "per_question_scores.csv":
            rows = [r for r in rows if r["System"] != "Auto-router"]
            roster = yaml.safe_load((ROOT / "configs/eval_sets.yaml").read_text())["sets"][
                "pilot122-v2"
            ]
            allowed_qids = {(r["dataset"], r["qid"]) for r in roster}
            sources = {"Phase 5": "phase05", "Natural rewrites": "natural", "Benchmark v3": "v3"}
            if any((sources.get(r["Source"]), r["qid"]) not in allowed_qids for r in rows):
                raise ValueError("Snapshot contains a question outside the fixed dev roster")
        if name == "per_question_scores.csv" and len(rows) != 9 * 122:
            raise ValueError("Expected 122 dev questions across nine systems")
        manifest["files"][name] = dict(
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            rows=len(rows),
            columns=columns,
        )
        if not dry_run:
            output.mkdir(parents=True, exist_ok=True)
            with (output / name).open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
    if not dry_run:
        # Exercise all derived-cost and paired-verdict invariants before declaring success.
        read_pack(output)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return dict(
        state="DRY_RUN" if dry_run else "COMPLETE",
        files=len(manifest["files"]),
        rows=sum(f["rows"] for f in manifest["files"].values()),
        split="dev",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PACK)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "src/bugzilla_serving/dashboard/snapshot"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.dry_run)))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Plan dev experiments by default; explicit --mock or --enable-llm executes."""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.experiments.data import load_eval_set
from bugzilla_serving.experiments.preflight import estimate
from bugzilla_serving.experiments.runner import cancel, job_status, run_experiment
from bugzilla_serving.experiments.sweep import plan_sweep, run_sweep
from bugzilla_serving.tracking.backfill import read
from bugzilla_serving.tracking.client import TrackingClient


def resolve_config(args):
    if args.config:
        value = read(args.config)
    elif args.run_id:
        tracker = TrackingClient(args.tracking_uri)
        run = tracker.client.get_run(args.run_id)
        if run.data.tags.get("split") != "dev":
            raise ValueError("Only dev MLflow runs can supply configs")
        value = {k: yaml.safe_load(run.data.params[k]) for k in RunConfig.model_fields}
    else:
        slug = args.preset or "recommended"
        presets = read(ROOT / "configs/presets.yaml")["presets"]
        if args.registry_presets:
            from bugzilla_serving.tracking.registry import Registry

            presets = Registry(args.tracking_uri).list_presets()
        matches = [p["config"] for p in presets if p["slug"] == slug]
        if len(matches) != 1:
            raise ValueError("Unknown or ambiguous preset")
        value = matches[0]
    for override in args.set:
        if "=" not in override:
            raise ValueError("--set requires knob=value")
        key, raw = override.split("=", 1)
        value[key] = yaml.safe_load(raw)
    return RunConfig(**value).validate_against()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--config", type=Path)
    source.add_argument("--preset")
    source.add_argument("--run-id")
    parser.add_argument(
        "--registry-presets",
        action="store_true",
        help="Explicitly read presets from MLflow; otherwise use local fallback",
    )
    parser.add_argument("--set", action="append", default=[])
    parser.add_argument("--eval-set", default="smoke-5")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--label", default="")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--mock", action="store_true", help="Execute locally with MockProvider")
    mode.add_argument("--enable-llm", action="store_true")
    parser.add_argument("--bundle", type=Path, help="Verify this real dev bundle before planning")
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--sweep", action="append", default=[])
    parser.add_argument("--tracking-uri")
    parser.add_argument(
        "--fixture-bundle", type=Path, help="Explicit synthetic retrieval demo; requires --mock"
    )
    parser.add_argument("--status", metavar="JOB_ID")
    parser.add_argument("--cancel", metavar="JOB_ID")
    args = parser.parse_args()
    if args.max_requests < 1:
        parser.error("--max-requests must be positive")
    fixture_kwargs = {}
    if args.fixture_bundle:
        if not args.mock:
            parser.error("--fixture-bundle requires --mock; never usable with live LLM")
        from bugzilla_serving.experiments.fixtures import build_fixture_runner

        os.environ["BUNDLE_DIR"] = str(args.fixture_bundle.resolve())
        fixture_kwargs["build"] = build_fixture_runner

    def progress(state):
        print(
            json.dumps({k: state[k] for k in ("id", "state", "done", "total", "started", "eta")}),
            file=sys.stderr,
            flush=True,
        )

    if args.status or args.cancel:
        result = cancel(args.cancel) if args.cancel else job_status(args.status)
    else:
        cfg = resolve_config(args)
        bundle_report = None
        if args.bundle:
            from bugzilla_serving.experiments.preflight import bundle_preflight

            os.environ["BUNDLE_DIR"] = str(args.bundle.resolve())
            bundle_report = bundle_preflight(cfg, args.bundle)
        if args.sweep:
            grid = {}
            for entry in args.sweep:
                key, raw = entry.split("=", 1)
                grid[key] = [yaml.safe_load(v) for v in raw.split(",")]
            _, plan = plan_sweep(cfg, grid, args.eval_set, args.limit)
            result = (
                plan
                if not (args.mock or args.enable_llm)
                else run_sweep(
                    cfg,
                    grid,
                    args.eval_set,
                    args.limit,
                    label=args.label,
                    enable_llm=args.enable_llm,
                    max_requests=args.max_requests,
                    tracking_uri=args.tracking_uri,
                    on_progress=progress,
                    **fixture_kwargs,
                )
            )
        elif not (args.mock or args.enable_llm):
            items, _ = load_eval_set(args.eval_set, args.limit)
            plan = estimate(cfg, items, max_requests=args.max_requests)
            result = dict(
                config=cfg.model_dump(),
                eval_set=args.eval_set,
                **plan,
                bundle=bundle_report,
                fits_request_cap=plan["est_calls"] <= args.max_requests,
                max_requests=args.max_requests,
                actual_api_calls=0,
                preset_source="registry"
                if args.registry_presets
                else "local YAML fallback (not a champion claim)",
            )
        else:
            result = run_experiment(
                cfg,
                args.eval_set,
                args.limit,
                args.label,
                enable_llm=args.enable_llm,
                max_requests=args.max_requests,
                tracking_uri=args.tracking_uri,
                on_progress=progress,
                **fixture_kwargs,
            )
    print(json.dumps(result, indent=2))
    if result.get("state") in ("FAILED", "REFUSED"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()

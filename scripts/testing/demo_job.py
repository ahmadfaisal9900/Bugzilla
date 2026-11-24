#!/usr/bin/env python3
"""Owner-run stages with logs, timestamps, code identity and resumable stage checkpoints."""

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=["checks", "routes", "mock", "live", "resources", "cloud"], required=True
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-requests", type=int, default=5)
    parser.add_argument("--case")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if args.run and args.dry_run:
        parser.error("Choose --run or --dry-run")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = args.run_dir or ROOT / "results/demo_jobs" / (now + "-" + args.stage)
    py = sys.executable
    commands = {
        "checks": [
            [py, "-m", "pytest", "-m", "not live and not integration", "-q"],
            [py, "-m", "ruff", "check"],
            [py, "-m", "ruff", "format", "--check"],
            ["actionlint", ".github/workflows/ci.yml"],
        ],
        "routes": [
            [
                py,
                "scripts/testing/demo_route_diff.py",
                "--limit",
                str(args.limit or 122),
                "--output",
                str(folder / "route_diff.json"),
            ]
        ],
        "mock": [
            [
                py,
                "scripts/testing/demo_check.py",
                "--mock",
                "--limit",
                str(args.limit or 4),
                "--output",
                str(folder / "demo_check.json"),
            ]
        ],
        "live": [
            [
                py,
                "scripts/testing/demo_check.py",
                "--live",
                "--limit",
                str(args.limit or 24),
                "--max-requests",
                str(args.max_requests),
                "--output",
                str(folder / "demo_check.json"),
            ]
        ],
        "resources": [["bash", "scripts/testing/demo_resources.sh", str(folder)]],
        "cloud": [["bash", "scripts/testing/check_cloud_dashboard.sh", str(folder)]],
    }[args.stage]
    if args.case and args.stage == "live":
        commands[0] += ["--case", args.case]
    identity_commands = [list(c) for c in commands]
    if args.resume and args.stage in ("mock", "live") and (folder / "demo_check.json").is_file():
        commands[0] += ["--resume", str(folder / "demo_check.json")]
    version = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    diff = subprocess.check_output(
        [
            "git",
            "diff",
            "HEAD",
            "--",
            "src",
            "scripts",
            "configs",
            "tests",
            "dashboard",
            "pyproject.toml",
        ]
    )
    identity = hashlib.sha256(
        json.dumps(
            [version, hashlib.sha256(diff).hexdigest(), identity_commands], sort_keys=True
        ).encode()
    ).hexdigest()
    state = dict(
        state="DRY_RUN",
        utc=now,
        stage=args.stage,
        identity=identity,
        run_dir=str(folder),
        commands=commands,
        completed=[],
    )
    if not args.run:
        print(json.dumps(state, indent=2))
        return
    if args.resume:
        previous = json.loads((folder / "summary.json").read_text())
        if previous["identity"] != identity:
            raise ValueError("Code or command identity changed; use a new run directory")
        state["completed"] = previous["completed"]
    folder.mkdir(parents=True, exist_ok=True)
    summary = folder / "summary.json"
    state["state"] = "RUNNING"

    def save():
        temporary = summary.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(summary)

    save()
    env = dict(
        os.environ, PYTHONPATH=str(ROOT / "src"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1"
    )
    if args.stage == "checks":
        env.update(LLM_PROVIDER="mock", LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
    for index, command in enumerate(commands):
        if any(r["index"] == index and r["exit_code"] == 0 for r in state["completed"]):
            continue
        log = folder / f"{index:02d}.log"
        print(f"{dt.datetime.now(dt.timezone.utc).isoformat()} -> {log}", flush=True)
        try:
            with log.open("w") as stream:
                result = subprocess.run(
                    command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT
                )
                code = result.returncode
        except OSError as exc:
            log.write_text(type(exc).__name__ + ": executable unavailable\n")
            code = 127
        state["completed"] = [r for r in state["completed"] if r["index"] != index]
        state["completed"].append(
            dict(
                index=index,
                exit_code=code,
                log=str(log),
                finished=dt.datetime.now(dt.timezone.utc).isoformat(),
            )
        )
        state["state"] = "FAILED" if code else "RUNNING"
        save()
        if code:
            raise SystemExit(code)
    state["state"] = "COMPLETE"
    save()
    print(summary)


if __name__ == "__main__":
    main()

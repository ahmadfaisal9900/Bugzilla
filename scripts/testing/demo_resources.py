#!/usr/bin/env python3
"""Image bytes and Docker working-set memory, idle and after one database question."""

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path


def command(args):
    return subprocess.check_output(args, text=True, timeout=20).strip()


def main():
    folder = Path(sys.argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    compose = ["docker", "compose", "-f", os.environ.get("DEMO_COMPOSE_FILE", "compose.yaml")]
    services = {}
    for service in ("api", "chat", "dashboard"):
        container = command(compose + ["ps", "-q", service])
        if not container:
            raise ValueError(f"{service} is not running")
        image = command(["docker", "inspect", "--format", "{{.Image}}", container])
        services[service] = dict(
            container=container,
            image=image,
            image_bytes=int(
                command(["docker", "image", "inspect", "--format", "{{.Size}}", image])
            ),
        )

    def stats():
        rows = command(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
            + [v["container"] for v in services.values()]
        )
        return [json.loads(line) for line in rows.splitlines()]

    result = dict(
        utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        services=services,
        idle=stats(),
        measurement="Docker MemUsage: working set, not process peak RSS",
    )
    # Script refuses an unpromoted champion before sending this zero-call field query.
    subprocess.run(
        [
            sys.executable,
            "scripts/testing/demo_check.py",
            "--live",
            "--case",
            "field",
            "--max-requests",
            "0",
            "--output",
            str(folder / "question.json"),
        ],
        check=True,
    )
    result["after_database_question"] = stats()
    path = folder / "resources.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()

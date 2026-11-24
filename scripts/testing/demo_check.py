#!/usr/bin/env python3
"""Check a running API. Mock checks wiring; live checks all case assertions."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MOCK_CASES = [
    dict(
        id="mock-database",
        question="What component is recorded for bug 100000?",
        mode="recommended",
        expected_route="S7v2",
        must_abstain=False,
        max_seconds=30,
    ),
    dict(
        id="mock-dossier",
        question="Why was bug 100000 filed?",
        mode="recommended",
        expected_route="S5",
        must_abstain=False,
        must_cite_bug="100000",
        max_seconds=30,
    ),
    dict(
        id="mock-search",
        question="Which report mentions an imaginary keyboard widget?",
        mode="recommended",
        expected_route="S2",
        must_abstain=False,
        max_seconds=30,
    ),
    dict(
        id="mock-decline",
        question="Tell me about bug 1000000",
        mode="recommended",
        expected_route="outside_archive",
        must_abstain=True,
        max_seconds=30,
    ),
]


def selected(args):
    if args.mock:
        cases = MOCK_CASES
    else:
        import yaml

        cases = yaml.safe_load(args.cases.read_text())["cases"]
    if args.case:
        names = set(args.case.split(","))
        if names - {c["id"] for c in cases}:
            raise ValueError("Unknown case ID")
        cases = [c for c in cases if c["id"] in names]
    return cases[: args.limit] if args.limit else cases


def call_ceiling(case):
    route = case["expected_route"]
    if route == "outside_archive":
        return 0
    if route == "S7v2":
        from bugzilla_qa.answering_v2.json_tools import preparse
        from bugzilla_serving.routing import tool_question

        parsed = preparse({"question": tool_question(case["question"])})
        if parsed["complete"] and parsed["facts"].get("mode") not in ("text", None):
            return 0
        return 5  # plan + repair + answer + possible dossier fallback/repair
    if route in ("S5", "S1"):
        return 2 if re.search(r"\b(?:bug|issue)\s+\d+", case["question"], re.I) else 3
    return 3  # query transform, answer and one answer repair


def http_client(base, key):
    def send(path, body=None):
        request = Request(
            base.rstrip("/") + path,
            data=json.dumps(body).encode() if body else None,
            headers={"X-API-Key": key, "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=120) as response:
            return json.load(response)

    return send


def run(args, send=None):
    cases = selected(args)
    estimated = sum(call_ceiling(c) for c in cases) if args.live else 0
    print(f"{len(cases)} cases; estimated Groq-call upper bound: {estimated}", flush=True)
    if args.live and (args.max_requests is None or args.max_requests < estimated):
        raise ValueError(f"--max-requests must be at least {estimated}; no requests sent")
    if args.dry_run:
        return dict(state="DRY_RUN", estimated_calls=estimated, cases=[c["id"] for c in cases])
    if not send:
        key = os.environ.get("SERVING_API_KEY")
        if not key:
            raise ValueError("Set SERVING_API_KEY")
        send = http_client(args.api_url, key)
    presets = send("/v1/presets")
    available = {p["slug"]: p for p in presets}
    if any(c["mode"] not in available for c in cases):
        raise ValueError("Required preset is unpublished; promote/restart first")
    if args.live:
        expected = {"recommended": "S8v2", "fast": "S1", "deep": "S5"}
        for case in cases:
            preset = available[case["mode"]]
            if preset["config"]["system_id"] != expected[case["mode"]]:
                raise ValueError("Unexpected preset system; no model requests sent")
            if case["mode"] == "recommended" and not preset.get("is_champion"):
                raise ValueError("Recommended is a fallback, not the registry champion")
    identity = hashlib.sha256(
        json.dumps(dict(cases=cases, presets=presets, live=args.live), sort_keys=True).encode()
    ).hexdigest()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output or ROOT / "results/demo_check" / (stamp + ".json")
    result = dict(
        state="RUNNING",
        utc=stamp,
        identity=identity,
        estimated_calls=estimated,
        actual_calls=0,
        mode="live" if args.live else "mock",
        rows=[],
    )
    if args.resume:
        result = json.loads(args.resume.read_text())
        if result["identity"] != identity:
            raise ValueError("Resume cases/configs differ")
        output = args.resume
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temp = output.with_suffix(".tmp")
        temp.write_text(json.dumps(result, indent=2) + "\n")
        temp.replace(output)

    done = {r["case"] for r in result["rows"]}
    print("case | route | abstained | cited | latency_s | PASS/FAIL | reason", flush=True)
    for case in cases:
        if case["id"] in done:
            continue
        if args.live and result["actual_calls"] + call_ceiling(case) > args.max_requests:
            raise ValueError("Remaining cap is insufficient; checkpoint saved")
        start = time.monotonic()
        try:
            overrides = {"provider": "groq" if args.live else "mock"}
            if args.mock:
                overrides.update(
                    system_id="S8v2", retriever="R1", serving_bug_scope=True, s5_dossier_budget=4096
                )
            value = send(
                "/v1/ask",
                dict(
                    session_id="demo-" + stamp,
                    message=case["question"],
                    preset_slug=case["mode"],
                    overrides=overrides,
                ),
            )["record"]
            elapsed = time.monotonic() - start
            errors = []
            if value["route"] != case["expected_route"]:
                errors.append("route mismatch")
            if value["errors"]:
                errors.append("engine errors")
            if elapsed > case["max_seconds"]:
                errors.append("latency exceeded")
            answer = value["answer"]
            target = case.get("must_cite_bug")
            evidence = {e["chunk_id"]: str(e["bug_id"]) for e in value["evidence"]}
            cited = not target or any(evidence.get(i) == target for i in answer["citations"])
            if target and target not in evidence.values():
                errors.append("target evidence missing")
            if args.live:
                if answer["abstain"] != case["must_abstain"]:
                    errors.append("abstention mismatch")
                if target and not case["must_abstain"] and not cited:
                    errors.append("target citation missing")
                if case.get("answer_regex") and not re.search(
                    case["answer_regex"], str(answer["answer"])
                ):
                    errors.append("answer regex mismatch")
            elif value["route"] == "outside_archive" and not answer["abstain"]:
                errors.append("outside archive must decline")
            if value["route"] == "outside_archive" and value["llm_calls"]:
                errors.append("outside archive called provider")
            result["actual_calls"] += value["llm_calls"] if args.live else 0
            if args.live and result["actual_calls"] > args.max_requests:
                errors.append("observed calls exceed cap")
            row = dict(
                case=case["id"],
                route=value["route"],
                abstained=answer["abstain"],
                cited=cited if args.live else "not checked (mock)",
                latency_s=round(elapsed, 3),
                passed=not errors,
                reason="; ".join(errors)
                or ("live assertions" if args.live else "wiring/evidence only"),
                record=value,
            )
        except Exception as exc:
            row = dict(
                case=case["id"],
                route="ERROR",
                abstained=None,
                cited=False,
                latency_s=round(time.monotonic() - start, 3),
                passed=False,
                reason=type(exc).__name__,
            )
        result["rows"].append(row)
        save()
        print(
            " | ".join(str(row[k]) for k in ("case", "route", "abstained", "cited", "latency_s"))
            + " | "
            + ("PASS" if row["passed"] else "FAIL")
            + " | "
            + row["reason"],
            flush=True,
        )
        if not row["passed"]:
            break  # Fail fast saves quota; resume never repeats completed cases.
    result["state"] = (
        "PASS"
        if (len(result["rows"]) == len(cases) and all(r["passed"] for r in result["rows"]))
        else "FAIL"
    )
    save()
    print(f"{result['state']}: {output}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/demo/demo_cases.yaml")
    parser.add_argument("--case", help="Comma-separated case IDs")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    try:
        result = run(args)
    except ValueError as exc:
        parser.exit(2, str(exc) + "\n")
    if result["state"] == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()

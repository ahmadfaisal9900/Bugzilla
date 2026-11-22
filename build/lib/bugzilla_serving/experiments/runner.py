"""Single-job, resumable dev experiments using the shared engine and B1 tracking."""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path

from bugzilla_serving.contracts.run_config import ROOT, config_hash
from bugzilla_serving.experiments.data import digest, load_eval_set
from bugzilla_serving.experiments.preflight import estimate, model_limits
from bugzilla_serving.experiments.scoring import prediction, score_predictions
from bugzilla_serving.tracking.backfill import csv_text, git_sha, read
from bugzilla_serving.tracking.client import (
    TrackingClient,
    assert_no_secrets,
    config_artifact,
    params_for,
)


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, value):
    text = json.dumps(value, sort_keys=True, indent=2)
    assert_no_secrets(text)
    temp = path.with_suffix(".tmp")
    temp.write_text(text + "\n")
    temp.replace(path)


def job_folder(job_id, jobs=None):
    if len(job_id) != 20 or any(c not in "0123456789abcdef" for c in job_id):
        raise ValueError("Invalid job ID")
    return Path(jobs or ROOT / "outputs/mlops/jobs") / job_id


def job_status(job_id, jobs=None):
    return read(job_folder(job_id, jobs) / "status.json")


def cancel(job_id, jobs=None):
    folder = job_folder(job_id, jobs)
    if not (folder / "status.json").exists():
        raise ValueError("Unknown job")
    (folder / "cancel.flag").touch()
    return {"id": job_id, "cancel_requested": True}


@contextlib.contextmanager
def job_lock(jobs):
    jobs.mkdir(parents=True, exist_ok=True)
    with (jobs / "active.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another experiment job is active") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class PacedProvider:
    """Apply token/min pacing to the existing budget/cache/ledger provider."""

    def __init__(self, provider, tpm, max_tokens, sleep=time.sleep):
        self.provider, self.tpm, self.max_tokens, self.sleep = provider, tpm, max_tokens, sleep
        self.events, self.reservations = [], []

    @property
    def calls(self):
        return self.provider.calls

    def invoke(self, method, prompt, *args, **kwargs):
        # Actual request payload may exceed the planning estimate. Reject rather than burst.
        cost = (
            len(json.dumps(args, ensure_ascii=False).encode())
            + len(prompt.encode())
            + len(kwargs.get("system_prompt", "").encode())
        ) + self.max_tokens
        if cost > 0.9 * self.tpm:
            raise RuntimeError("Request exceeds conservative experiment TPM allowance")
        while True:
            now = time.monotonic()
            self.reservations = [(t, n) for t, n in self.reservations if now - t < 60]
            if sum(n for _, n in self.reservations) + cost <= 0.9 * self.tpm:
                break
            self.sleep(max(0.01, 60 - (now - self.reservations[0][0])))
        self.reservations.append((time.monotonic(), cost))
        response = getattr(self.provider, method)(prompt, *args, **kwargs)
        self.events.append({k: v for k, v in response.items() if k != "value"})
        return response

    def generate_json(self, prompt, *args, **kwargs):
        return self.invoke("generate_json", prompt, *args, **kwargs)

    def generate_tools(self, prompt, *args, **kwargs):
        return self.invoke("generate_tools", prompt, *args, **kwargs)


def live_provider(cfg, max_requests, root):
    from bugzilla_qa.llm.provider import create_provider

    config = read(root / "configs/llm.yaml")
    limits = model_limits(cfg)
    config.update(provider=cfg.provider, temperature=cfg.temperature, max_retries=0)
    config["cache"] = f"outputs/llm/experiments/{config_hash(cfg)}/cache.sqlite"
    config["models"]["generator"].update(
        id=cfg.model,
        rpm=min(limits["rpm"], config["models"]["generator"]["rpm"]),
        rpd=limits["rpd"],
    )
    provider = create_provider(
        config,
        "generator",
        enable_llm=True,
        max_requests=max_requests,
        root=root,
        resolve_env=False,
    )
    return PacedProvider(provider, limits["tpm"], config["max_output_tokens"])


def run_experiment(
    cfg,
    eval_set,
    limit=None,
    label="",
    enable_llm=False,
    max_requests=100,
    sweep_id=None,
    on_progress=None,
    *,
    root=ROOT,
    sets_path=None,
    jobs_dir=None,
    tracking_uri=None,
    provider=None,
    build=None,
):
    from bugzilla_serving.engine import _mock_provider, build_runner, redact

    cfg.validate_against()
    if type(max_requests) is not int or max_requests < 1:
        raise ValueError("max_requests must be positive")
    root = Path(root)
    items, pins = load_eval_set(eval_set, limit, root=root, sets_path=sets_path)
    mode = "live" if enable_llm else "mock"
    if enable_llm and cfg.provider == "mock":
        raise ValueError("Live execution requires a live provider config")
    bundle_manifest = (
        Path(os.environ.get("BUNDLE_DIR", "serving_bundle")).resolve() / "manifest.json"
    )
    from bugzilla_serving.tracking.backfill import sha

    code = list(Path(__file__).parent.glob("*.py")) + [
        ROOT / "src/bugzilla_serving/engine.py",
        ROOT / "src/bugzilla_qa/llm/provider.py",
        ROOT / "src/bugzilla_qa/evaluation/systems.py",
        ROOT / "src/bugzilla_qa/evaluation/scoring.py",
        ROOT / "configs/serving.yaml",
        root / "configs/llm.yaml",
        ROOT
        / "prompts"
        / (
            "answer_v2_compact.txt"
            if cfg.prompt_version == "answer-v2-compact"
            else "answer_v1.txt"
        ),
    ]

    identity = dict(
        config_hash=config_hash(cfg),
        eval_set=eval_set,
        mode=mode,
        pins=pins,
        code_sha256={
            str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else "external/" + p.name: sha(p)
            for p in code
        },
        bundle_manifest_sha256=sha(bundle_manifest) if bundle_manifest.exists() else None,
    )

    job_id = digest(identity)[:20]
    jobs = Path(jobs_dir or root / "outputs/mlops/jobs")
    folder = job_folder(job_id, jobs)
    with job_lock(jobs):
        folder.mkdir(parents=True, exist_ok=True)
        ledger = folder / "predictions.jsonl"
        completed = {}
        if ledger.exists():
            raw = ledger.read_bytes()
            if raw and not raw.endswith(b"\n"):
                # A complete newline is the commit marker; preserve interrupted bytes first.
                backup = folder / ("predictions.interrupted-" + str(time.time_ns()) + ".jsonl")
                assert_no_secrets(raw)
                backup.write_bytes(raw)
                boundary = raw.rfind(b"\n") + 1
                with ledger.open("r+b") as stream:
                    stream.truncate(boundary)
            old_manifest = folder / "manifest.json"
            if old_manifest.exists():
                expected = read(old_manifest).get("output_sha256", {}).get("predictions.jsonl")
                if expected and sha(ledger) != expected:
                    raise ValueError("Completed prediction ledger checksum mismatch")
            for line in ledger.read_text().splitlines():
                row = json.loads(line)
                if row["config_hash"] != config_hash(cfg) or row.get("split") != "dev":
                    raise ValueError("Invalid resume identity/split")
                key = (row["dataset"], row["qid"])
                if key in completed:
                    raise ValueError("Duplicate resume record")
                completed[key] = row
        keys = {(i["dataset"], i["qid"]) for i in items}
        if set(completed) - keys:
            raise ValueError("Resume ledger contains out-of-scope qids")
        pending = [i for i in items if (i["dataset"], i["qid"]) not in completed]
        plan = estimate(cfg, pending, root=root)
        state = dict(
            id=job_id,
            state="PREFLIGHT",
            done=len(completed),
            total=len(items),
            started=utc(),
            eta=None,
            mlflow_run_id=None,
            error=None,
            mode=mode,
            actual_requests=0,
        )

        def update(**values):
            state.update(values)
            write(folder / "status.json", state)
            if on_progress:
                on_progress(dict(state))

        update()
        write(folder / "manifest.json", dict(identity=identity, preflight=plan))
        if (folder / "cancel.flag").exists():
            update(state="CANCELLED")
            return state
        if not plan["fits"]:
            update(state="REFUSED", error=plan["reason"])
            return state
        if not bundle_manifest.exists():
            update(
                state="REFUSED",
                error="Missing serving bundle; supply Stream A bundle or explicit mock fixture",
            )
            return state
        if enable_llm and read(bundle_manifest).get("synthetic"):
            update(state="REFUSED", error="Live experiment refuses a synthetic serving bundle")
            return state
        if enable_llm and plan["est_calls"] > max_requests:
            update(
                state="REFUSED", error="Increase --max-requests or reduce --limit to fit preflight"
            )
            return state
        if not enable_llm and tracking_uri and not tracking_uri.startswith("file:"):
            update(state="FAILED", error="Mock jobs must use a local file: MLflow store")
            raise ValueError("Mock jobs must use a local file: MLflow store")
        # Default mock execution is strictly local even if DagsHub env vars are exported.
        uri = tracking_uri or (None if enable_llm else (root / "outputs/mlops/mlflow").as_uri())
        try:
            tracking = TrackingClient(uri)
            selected_provider = provider or (
                live_provider(cfg, max_requests, root) if enable_llm else _mock_provider()
            )
        except Exception as exc:
            update(state="FAILED", error=f"{type(exc).__name__}: {redact(str(exc))}")
            raise
        if not enable_llm:
            from bugzilla_qa.llm.provider import MockProvider

            if not isinstance(selected_provider, MockProvider):
                update(state="FAILED", error="Offline execution requires MockProvider")
                raise ValueError("Offline execution requires MockProvider")
        build = build or build_runner
        try:
            update(state="RUNNING")
            initial_calls = selected_provider.calls
            initial_done = len(completed)
            start = time.monotonic()
            if pending:
                from langsmith import tracing_context

                with (
                    tracing_context(enabled=False),
                    build(cfg, provider=selected_provider) as engine,
                ):
                    for item in pending:
                        if (folder / "cancel.flag").exists():
                            update(state="CANCELLED")
                            return state
                        record = engine.run(item["question"])
                        row = redact(prediction(item, record, cfg.system_id))
                        row["simulated"] = not enable_llm
                        assert_no_secrets(json.dumps(row))
                        with ledger.open("a") as stream:
                            stream.write(json.dumps(row, sort_keys=True) + "\n")
                            stream.flush()
                            os.fsync(stream.fileno())
                        completed[(item["dataset"], item["qid"])] = row
                        elapsed = time.monotonic() - start
                        done = len(completed)
                        update(
                            done=done,
                            actual_requests=(
                                selected_provider.calls - initial_calls if enable_llm else 0
                            ),
                            eta=round(elapsed / (done - initial_done) * (len(items) - done), 1),
                        )
                        if row["status"] != "ok":
                            # Error rows remain auditable; explicit errors are not silently retried.
                            update(error="Engine returned an error; inspect sanitized predictions")
            if (folder / "cancel.flag").exists():
                update(state="CANCELLED")
                return state
            update(state="SCORING")
            results, families, metrics = score_predictions(items, completed)
            rows = list(completed.values())
            if enable_llm:
                metrics["cost.llm_calls"] = sum(r["llm_calls"] for r in rows)
                if all(not r["tokens"].get("usage_missing") for r in rows):
                    metrics["cost.tokens_in"] = sum(r["tokens"].get("input", 0) for r in rows)
                    metrics["cost.tokens_out"] = sum(r["tokens"].get("output", 0) for r in rows)
            latencies = sorted(r["latency_ms"] for r in rows)
            metrics.update(
                {
                    "latency.p50_ms": latencies[len(rows) // 2],
                    "latency.p95_ms": latencies[min(len(rows) - 1, int(0.95 * len(rows)))],
                }
            )
            tags = dict(
                source="lab",
                eval_set=f"{eval_set}@{job_id}:{mode}",
                eval_set_name=eval_set,
                datasets=",".join(sorted({i["dataset"] for i in items})),
                split="dev",
                scorer=",".join(sorted({r["scorer"] for r in results})),
                git_sha=git_sha(ROOT),
                simulated=str(not enable_llm).lower(),
                actual_provider=cfg.provider if enable_llm else "mock",
                label=label,
                job_id=job_id,
                pending_n=str(sum(f["pending_n"] for f in families)),
            )
            if sweep_id:
                tags["sweep_id"] = sweep_id
            for family in families:
                tags[f"scorer.{family['family']}"] = family["scorer"]
            score_text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in results)
            assert_no_secrets(score_text)
            (folder / "scores.jsonl").write_text(score_text)
            config_text = config_artifact(cfg)
            family_text = csv_text(families, list(families[0]))
            write(
                folder / "manifest.json",
                dict(
                    identity=identity,
                    preflight=plan,
                    output_sha256={
                        "predictions.jsonl": sha(ledger),
                        "config.yaml": hashlib.sha256(config_text.encode()).hexdigest(),
                        "per_family.csv": hashlib.sha256(family_text.encode()).hexdigest(),
                    },
                ),
            )
            artifacts = {
                "config.yaml": config_text,
                "per_family.csv": family_text,
                "predictions.jsonl": ledger.read_text(),
                "manifest.json": (folder / "manifest.json").read_text(),
                "scores.jsonl": score_text,
            }
            rid = tracking.log_run("playground", params_for(cfg), tags, metrics, artifacts)
            update(state="COMPLETED", mlflow_run_id=rid, eta=0)
            return state
        except Exception as exc:
            update(state="FAILED", error=f"{type(exc).__name__}: {redact(str(exc))}")
            raise

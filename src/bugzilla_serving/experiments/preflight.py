"""Offline per-model quota estimates. Provider headers remain authoritative."""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from bugzilla_serving.contracts.run_config import ROOT, load_spec
from bugzilla_serving.tracking.backfill import read

PACIFIC = ZoneInfo("America/Los_Angeles")


def model_limits(cfg):
    return next(m for m in load_spec()["models"].values() if m["model_id"] == cfg.model)


def usage(cfg, llm, root=ROOT, now=None):
    import json

    now = now or dt.datetime.now(dt.timezone.utc)
    from collections import defaultdict, deque

    from bugzilla_serving.experiments.token_budget import measured_parents, unknown_call_estimate

    path = Path(root) / llm["ledger"]
    events = []
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("provider", "gemini") == cfg.provider and row.get("model") == cfg.model:
                events.append(row)
    parents = measured_parents(Path(root))
    pending = defaultdict(deque)
    calls, reported, unknown, reserve = 0, 0, 0, 0
    for row in events:
        stamp = dt.datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Quota ledger timestamp must have timezone")
        key = (row.get("prompt_hash"), row.get("purpose"))
        current = stamp.astimezone(PACIFIC).date() == now.astimezone(PACIFIC).date()
        if row["status"] == "REQUEST_STARTED":
            pending[key].append((row, current))
            calls += int(current)
        elif row["status"] in ("SUCCESS", "ERROR"):
            start, charge = pending[key].popleft() if pending[key] else (row, current)
            if not charge:
                continue
            if all(type(row.get(k)) is int for k in ("input_tokens", "output_tokens")):
                reported += row["input_tokens"] + row["output_tokens"]
            else:
                unknown += 1
                reserve += unknown_call_estimate(start, parents, events, cfg, llm)
    for queue in pending.values():
        for start, charge in queue:
            if charge:
                unknown += 1
                reserve += unknown_call_estimate(start, parents, events, cfg, llm)
    limits = model_limits(cfg)
    fraction = min(0.9, llm.get("daily_fraction", 0.9))
    return dict(
        requests=max(0, int(limits["rpd"] * fraction) - calls),
        tokens=max(0, int(limits["tpd"] * fraction) - reported - reserve),
        used_requests=calls,
        reported_tokens=reported,
        unknown_usage_calls=unknown,
        unknown_token_reserve=reserve,
        used_tokens=reported + reserve,
        reserve_policy="reported historical mean +50%",
        date=now.astimezone(PACIFIC).date().isoformat(),
        timezone=str(PACIFIC),
        limits=limits,
    )


def estimate(cfg, items, *, root=ROOT, now=None, history=None, max_requests=None):
    cfg.validate_against()
    llm = read(Path(root) / "configs/llm.yaml")
    remaining = usage(cfg, llm, root, now)
    limits = remaining["limits"]
    defaults = load_spec()["hyperparameters"]
    steps = cfg.s7_max_tool_steps or defaults["s7_max_tool_steps"]["default"]
    transform = int(cfg.retriever in ("R7a", "R7b"))
    # Includes one answer repair, optional router repair, tool turns and one transform.
    per_question = {
        "R0": 0,
        "S0": 2,
        "S1": 2,
        "S2": 2 + transform,
        "S3": 3,
        "S4": 2,
        "S5": 2 + transform,
        "S6": 2,
        "S7": steps + 3 + steps * transform,
        "S8": steps + 5 + (steps + 1) * transform,
        "S8v2": 8,
        "ORACLE": 2,
    }[cfg.system_id]
    context = cfg.context_budget_tokens
    if cfg.system_id in ("S5", "S8", "S8v2"):
        context = max(context, cfg.s5_dossier_budget or defaults["s5_dossier_budget"]["default"])
    prompt = (
        Path(root)
        / "prompts"
        / (
            "answer_v2_compact.txt"
            if cfg.prompt_version == "answer-v2-compact"
            else "answer_v1.txt"
        )
    )
    prompt_bytes = prompt.stat().st_size
    # Stored graph context budgets are UTF-8 bytes, despite the contract knob name.
    overhead = max((len(i["question"].encode()) for i in items), default=0) + prompt_bytes + 2048
    from bugzilla_serving.experiments.token_budget import historical_input, historical_total

    measured = historical_input(cfg, Path(root), history)
    input_tokens = (
        math.ceil(measured) if measured is not None else math.ceil((context + overhead) / 3)
    )
    if cfg.system_id == "S0":
        input_tokens = math.ceil(measured) if measured is not None else math.ceil(overhead / 3)
    planned_trim = False
    if (
        cfg.system_id in ("S5", "S8", "S8v2")
        and input_tokens + llm["max_output_tokens"] > 0.9 * limits["tpm"]
        and math.ceil(overhead / 3) + llm["max_output_tokens"] <= 0.9 * limits["tpm"]
    ):
        input_tokens = math.floor(0.9 * limits["tpm"]) - llm["max_output_tokens"]
        planned_trim = True
    per_call = input_tokens + llm["max_output_tokens"]
    calls = len(items) * per_question
    if cfg.system_id == "S1" and max_requests is not None:
        # One normal answer/question; reserve only the repairs the explicit cap permits.
        base = len(items)
        calls = base + min(base, max(0, max_requests - base))
    gate_per_call = per_call
    measured_total = historical_total(cfg, Path(root), history)
    if measured_total is not None:
        per_call = measured_total
    tokens = calls * per_call
    reasons = []
    if max_requests is not None and calls > max_requests:
        reasons.append("request cap cannot cover the planned base calls")
    if calls > remaining["requests"]:
        reasons.append("estimated calls exceed safe remaining daily requests")
    if tokens > remaining["tokens"]:
        reasons.append("estimated tokens exceed safe remaining daily tokens")
    if calls and gate_per_call > 0.9 * limits["tpm"]:
        reasons.append("one estimated request exceeds safe tokens/minute")
    return dict(
        will_trim_evidence=planned_trim,
        input_tokens_per_call=input_tokens,
        input_estimate_source="historical complete usage"
        if measured is not None
        else "UTF-8 bytes / 3",
        fits=not reasons,
        est_calls=calls,
        est_tokens=tokens,
        remaining=remaining,
        reason="; ".join(reasons) or "estimated budget fits; provider accounting may differ",
        calls_per_question=per_question,
        tokens_per_call=per_call,
        request_gate_tokens=gate_per_call,
        token_estimate_source="reported ledger mean +50%"
        if measured_total is not None
        else "request ceiling",
        estimated_min_minutes=round(tokens / (0.9 * limits["tpm"]), 2),
        assumptions="No cache discount; logical-call upper estimate, not HTTP retry guarantee; "
        "history mean or bytes/3 estimate; S1 reserves repairs within the request cap; "
        "SDK retries disabled for experiments; "
        "failed usage conservatively reserved; other clients may consume quota.",
    )


def bundle_preflight(cfg, bundle=None, *, allow_synthetic=False):
    from bugzilla_serving.experiments.bundle_verify import prepare_bundle

    return prepare_bundle(cfg, bundle, allow_synthetic=allow_synthetic)

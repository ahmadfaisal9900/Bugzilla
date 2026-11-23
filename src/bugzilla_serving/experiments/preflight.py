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
    starts, tokens, unknown = [], 0, 0
    successes = 0
    path = Path(root) / llm["ledger"]
    if path.exists():
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                if row.get("provider", "gemini") != cfg.provider or row.get("model") != cfg.model:
                    continue
                stamp = dt.datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("Quota ledger timestamp must have timezone")
                if stamp.astimezone(PACIFIC).date() != now.astimezone(PACIFIC).date():
                    continue
                if row["status"] == "REQUEST_STARTED":
                    starts.append(stamp)
                elif row["status"] == "SUCCESS":
                    successes += 1
                    if all(type(row.get(k)) is int for k in ("input_tokens", "output_tokens")):
                        tokens += row["input_tokens"] + row["output_tokens"]
                    else:
                        unknown += 1
    # Failed/interrupted reservations have unknown token usage: reserve a model-cap allowance.
    unknown += max(0, len(starts) - successes)
    limits = model_limits(cfg)
    reserve = unknown * (limits["max_context_tokens"] + llm["max_output_tokens"])
    fraction = min(0.9, llm.get("daily_fraction", 0.9))
    return dict(
        requests=max(0, int(limits["rpd"] * fraction) - len(starts)),
        tokens=max(0, int(limits["tpd"] * fraction) - tokens - reserve),
        used_requests=len(starts),
        reported_tokens=tokens,
        unknown_usage_calls=unknown,
        unknown_token_reserve=reserve,
        date=now.astimezone(PACIFIC).date().isoformat(),
        timezone=str(PACIFIC),
        limits=limits,
    )


def estimate(cfg, items, *, root=ROOT, now=None):
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
        "ORACLE": 2,
    }[cfg.system_id]
    context = cfg.context_budget_tokens
    if cfg.system_id in ("S5", "S8"):
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
    input_tokens = math.ceil((context + overhead) / 4)
    if cfg.system_id == "S0":
        input_tokens = math.ceil(overhead / 4)
    per_call = input_tokens + llm["max_output_tokens"]
    calls = len(items) * per_question
    tokens = calls * per_call
    reasons = []
    if calls > remaining["requests"]:
        reasons.append("estimated calls exceed safe remaining daily requests")
    if tokens > remaining["tokens"]:
        reasons.append("estimated tokens exceed safe remaining daily tokens")
    if calls and per_call > 0.9 * limits["tpm"]:
        reasons.append("one estimated request exceeds safe tokens/minute")
    return dict(
        fits=not reasons,
        est_calls=calls,
        est_tokens=tokens,
        remaining=remaining,
        reason="; ".join(reasons) or "estimated budget fits; provider accounting may differ",
        calls_per_question=per_question,
        tokens_per_call=per_call,
        estimated_min_minutes=round(tokens / (0.9 * limits["tpm"]), 2),
        assumptions="No cache discount; logical-call upper estimate, not HTTP retry guarantee; "
        "bytes/4 estimate, one repair; SDK retries disabled for experiments; "
        "failed usage conservatively reserved; other clients may consume quota.",
    )


def bundle_preflight(cfg, bundle=None, *, allow_synthetic=False):
    from bugzilla_serving.experiments.bundle_verify import prepare_bundle

    return prepare_bundle(cfg, bundle, allow_synthetic=allow_synthetic)

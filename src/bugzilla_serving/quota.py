"""Check local provider usage and session rates, and choose a source-only fallback."""

import json
import math
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from bugzilla_qa.answering.runner import quota_report
from bugzilla_qa.llm.provider import read_config, resolved_config
from bugzilla_serving.contracts.api_models import ModelQuota, QuotaResponse
from bugzilla_serving.contracts.run_config import ROOT, RunConfig, load_spec


class Decision(NamedTuple):
    action: str
    reason: str = ""


class SessionRateLimit(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__("Session question limit reached")


class SessionLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.sessions = {}
        self.lock = threading.Lock()

    def admit(self, session_id):
        now = self.clock()
        with self.lock:
            for key in list(self.sessions):
                if self.sessions[key][-1] <= now - 60:
                    del self.sessions[key]
            times = self.sessions.setdefault(session_id, deque())
            while times and times[0] <= now - 60:
                times.popleft()
            if len(times) >= 6:
                raise SessionRateLimit(max(1, math.ceil(60 - (now - times[0]))))
            times.append(now)


class QuotaGuard:
    def __init__(self, spec=None, root=ROOT, llm_config="configs/llm.yaml", clock=None):
        self.spec = spec or load_spec()
        self.root = Path(root)
        self.llm_config = llm_config
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.models = {m["model_id"]: m for m in self.spec["models"].values()}

    def usage(self, model):
        daily = quota_report({"llm_config": self.llm_config}, self.root)
        if daily["model"] != model:
            raise ValueError("Model usage is unavailable in the configured provider report")
        config = resolved_config(read_config(self.root / self.llm_config), self.root)
        ledger = self.root / config["ledger"]
        now = self.clock()
        requests, tokens, unknown = 0, 0, False
        pending = Counter()
        if ledger.exists():
            with ledger.open(encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    if (
                        row.get("provider", "gemini") != config["provider"]
                        or row.get("model") != model
                    ):
                        continue
                    when = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
                    if not 0 <= (now - when).total_seconds() < 60:
                        continue
                    key = row.get("prompt_hash", "")
                    if row["status"] == "REQUEST_STARTED":
                        requests += 1
                        pending[key] += 1
                    elif row["status"] == "SUCCESS":
                        if pending[key]:
                            pending[key] -= 1
                        if row.get("input_tokens") is None or row.get("output_tokens") is None:
                            unknown = True
                        tokens += (row.get("input_tokens") or 0) + (row.get("output_tokens") or 0)
        return dict(
            requests=daily["local_guard_day_requests"],
            tokens=daily["local_guard_day_reported_success_tokens"],
            minute_requests=requests,
            minute_tokens=tokens,
            unknown_minute=unknown or any(pending.values()),
            cooldown=daily["known_cooldown_active"],
        )

    def decision(self, model, usage, estimated_tokens):
        limits = self.models[model]
        if usage["cooldown"]:
            return Decision("degrade", "The provider cooldown is active")
        if usage["requests"] >= limits["rpd"] * 0.9:
            return Decision("degrade", "The daily request budget is near its limit")
        if usage["tokens"] >= limits["tpd"] * 0.9:
            return Decision("degrade", "The daily token budget is near its limit")
        if usage["unknown_minute"]:
            return Decision("degrade", "Recent provider token usage is not yet known")
        if usage["minute_requests"] >= limits["rpm"]:
            return Decision("degrade", "The request budget for this minute is full")
        if usage["minute_tokens"] + estimated_tokens > limits["tpm"]:
            return Decision(
                "degrade", "This question would exceed the token budget for this minute"
            )
        return Decision("ok")

    def check(self, config, estimated_tokens):
        if config.provider == "mock" or config.system_id == "R0":
            return Decision("ok")
        try:
            return self.decision(config.model, self.usage(config.model), estimated_tokens)
        except (ValueError, KeyError, TypeError, OSError):
            return Decision("degrade", "The local provider usage could not be verified")

    def status(self):
        models = []
        for model, limits in self.models.items():
            usage = self.usage(model)
            models.append(
                ModelQuota(
                    model=model,
                    used_requests=usage["requests"],
                    limit_requests=limits["rpd"],
                    used_tokens=usage["tokens"],
                    limit_tokens=limits["tpd"],
                    degraded_now=self.decision(
                        model,
                        usage,
                        self.spec["hyperparameters"]["context_budget_tokens"]["default"] + 800,
                    ).action
                    == "degrade",
                )
            )
        return QuotaResponse(models=models)


def degraded_config(config):
    values = config.model_dump()
    retriever = (
        config.retriever if config.retriever in ("R1", "R2", "R3", "R4", "R5", "R6") else "R1"
    )
    values.update(
        system_id="R0",
        retriever=retriever,
        query_transform=None,
        s4_tau=None,
        s5_dossier_budget=None,
        s7_max_tool_steps=None,
        router_rules_version=None,
        tool_route_version=None,
    )
    if retriever in ("R1", "R2"):
        values["rrf_k"] = None
    return RunConfig(**values).validate_against()

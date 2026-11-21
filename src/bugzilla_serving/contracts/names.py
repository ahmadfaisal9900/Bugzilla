"""The exact tracking and trace vocabulary from OVERVIEW sections 4.5 and 4.6."""
from __future__ import annotations

import math
import re

from .run_config import RunConfig, config_hash

EXPERIMENTS = ("research-answer-eval", "research-retrieval-eval", "playground")
REQUIRED_TAGS = frozenset({"source", "eval_set", "datasets", "split", "scorer", "git_sha"})
REGISTRY_MODEL_NAME = "bugzilla-qa-config"
CHAMPION_ALIAS = "champion"
PRESET_TAG_KEYS = ("preset_slug", "preset_label", "preset_description", "published")
LANGSMITH_PROJECTS = ("ensf621-serving", "ensf621-dev")
TRACE_METADATA_KEYS = frozenset({
    "config_hash", "preset_slug", "system_id", "model", "retriever", "corpus", "route",
    "degraded", "request_id", "session_id",
})
FEEDBACK_KEY = "user_rating"
FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6", "KI", "MH", "F6H")
RETRIEVAL_METRICS = (
    "hit_at_1", "hit_at_5", "hit_at_10", "recall_at_5", "recall_at_10", "mrr_at_10",
    "ndcg_at_10", "bug_hit_at_5", "mh_full_evidence_at_10", "latency_p50_ms", "latency_p95_ms",
    "n", "r4_r3_jaccard_top10",
)
COMMON_METRICS = frozenset({
    "answer.macro", "abstain.correct_rate", "abstain.false_rate", "fail.rate",
    "cost.llm_calls", "cost.tokens_in", "cost.tokens_out", "latency.p50_ms", "latency.p95_ms",
})


def answer_metric(family: str, measure: str = "score") -> str:
    if family not in FAMILIES or measure not in ("score", "n"):
        raise ValueError("metric: unknown answer family/measure")
    return f"answer.{family}.{measure}"


def retrieval_metric(dataset: str, family: str, metric: str) -> str:
    if dataset not in ("v3", "phase05", "natural"):
        raise ValueError("metric: unknown dataset")
    if family not in FAMILIES or metric not in RETRIEVAL_METRICS:
        raise ValueError("metric: unknown retrieval family/measure")
    return f"retr.{dataset}.{family}.{metric}"


def validate_mlflow_run(params: dict, tags: dict, metrics: dict) -> None:
    expected = set(RunConfig.model_fields) | {"config_hash"}
    if set(params) != expected:
        raise ValueError("params: expected every RunConfig field and config_hash")
    # MLflow params are strings, including JSON null for unused optional knobs.
    import json

    values = {}
    for k, v in params.items():
        if k == "config_hash":
            continue
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (ValueError, TypeError):
                pass
        values[k] = v
    cfg = RunConfig.model_validate(values).validate_against()
    if params["config_hash"] != config_hash(cfg):
        raise ValueError("config_hash: does not match canonical RunConfig")
    if not REQUIRED_TAGS <= tags.keys():
        raise ValueError("tags: missing required tracking tags")
    if tags["source"] not in ("backfill", "lab", "ci"):
        raise ValueError("source: invalid")
    if tags["split"] not in ("dev", "test-aggregate"):
        raise ValueError("split: only dev or test-aggregate")
    if any(not str(tags[k]).strip() for k in REQUIRED_TAGS):
        raise ValueError("tags: values cannot be empty")
    allowed = set(COMMON_METRICS)
    allowed.update(answer_metric(f, m) for f in FAMILIES for m in ("score", "n"))
    allowed.update(
        retrieval_metric(d, f, m)
        for d in ("v3", "phase05", "natural")
        for f in FAMILIES for m in RETRIEVAL_METRICS
    )
    for k, v in metrics.items():
        if k not in allowed or isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"metric: invalid name/type {k}")
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"metric: invalid value {k}")
        if k.endswith((".score", "_rate", ".rate")) or k == "answer.macro":
            if v > 1:
                raise ValueError(f"metric: rate outside [0,1] {k}")
        if k.endswith(".n") and int(v) != v:
            raise ValueError(f"metric: n must be an integer {k}")


def validate_trace_metadata(md: dict) -> None:
    if not TRACE_METADATA_KEYS <= md.keys():
        raise ValueError("metadata: missing required LangSmith keys")
    if not re.fullmatch(r"[a-f0-9]{12}", str(md["config_hash"])):
        raise ValueError("config_hash: expected 12 lowercase hex digits")
    if md["system_id"] not in ("R0", *(f"S{i}" for i in range(9)), "ORACLE"):
        raise ValueError("system_id: unknown")
    if md["retriever"] not in ("R1", "R2", "R3", "R4", "R5", "R6", "R7a", "R7b"):
        raise ValueError("retriever: unknown")
    if md["corpus"] not in ("C0", "C1", "C2") or type(md["degraded"]) is not bool:
        raise ValueError("metadata: invalid corpus/degraded")
    for key in ("preset_slug", "model", "route", "request_id", "session_id"):
        if not isinstance(md[key], str) or not md[key].strip():
            raise ValueError(f"{key}: required nonempty string")

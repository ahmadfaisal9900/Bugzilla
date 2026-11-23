"""Estimated-token gates: history for planning, actual payload bytes/3 at send time."""

from __future__ import annotations

import json
import math
import re


def input_estimate(prompt, args=(), system_prompt=""):
    # Include response schemas/tools and role framing in the estimated input.
    raw = json.dumps(args, ensure_ascii=False) + prompt + system_prompt
    return math.ceil(len(raw.encode("utf-8")) / 3) + 32


def trim_request(prompt, args, system_prompt, max_output, tpm):
    ceiling = math.floor(0.9 * tpm) - max_output
    original = input_estimate(prompt, args, system_prompt)
    if original <= ceiling:
        return prompt, original, False
    try:
        payload = json.loads(prompt)
    except ValueError:
        raise ValueError("Estimated request exceeds TPM; no dossier evidence to trim") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("evidence"), str):
        raise ValueError("Estimated request exceeds TPM; no dossier evidence to trim")
    evidence = payload["evidence"]
    # Binary search a bounded UTF-8-safe prefix. Never trim instructions/question.
    low, high = 0, len(evidence)

    def encoded(length):
        clipped = {**payload, "evidence": evidence[:length]}
        if isinstance(clipped.get("citation_map"), dict):
            visible = set(re.findall(r"\[(C\d+)\]", clipped["evidence"]))
            clipped["citation_map"] = {
                k: v for k, v in clipped["citation_map"].items() if k in visible
            }
        return json.dumps(clipped, ensure_ascii=False, separators=(",", ":"))

    if input_estimate(encoded(0), args, system_prompt) > ceiling:
        raise ValueError("Fixed request overhead exceeds TPM even with empty evidence")
    while low < high:
        mid = (low + high + 1) // 2
        if input_estimate(encoded(mid), args, system_prompt) <= ceiling:
            low = mid
        else:
            high = mid - 1
    trimmed = encoded(low)
    estimate = input_estimate(trimmed, args, system_prompt)
    assert estimate + max_output <= 0.9 * tpm
    return trimmed, estimate, True


def historical_input(cfg, root, history=None):
    if history is None:
        # Never contact the ambient DagsHub URI during offline preflight.
        from bugzilla_serving.tracking.client import TrackingClient

        path = root / "outputs/mlflow/b1-ledgers"
        if not path.is_dir():
            return None
        records = TrackingClient(path.resolve().as_uri()).runs("research-answer-eval")
        history = [
            dict(params=r.data.params, metrics=r.data.metrics, started=r.info.start_time or 0)
            for r in records
        ]
    for row in sorted(history, key=lambda r: r.get("started", 0), reverse=True):
        m, p = row["metrics"], row["params"]
        if (
            p.get("system_id") == cfg.system_id
            and p.get("model") == cfg.model
            and m.get("cost.usage_missing_n") == 0
            and m.get("cost.llm_calls", 0) > 0
            and m.get("cost.tokens_in") is not None
        ):
            return m["cost.tokens_in"] / m["cost.llm_calls"]
    return None


def measured_usage(rows):
    """Mean total tokens per reported call; incomplete aggregate rows are excluded.

    A prediction ledger aggregates calls. If any usage is missing we cannot
    assign its tokens to individual calls, so neither tokens nor calls from that
    row enter the mean. Missing usage is never treated as zero.
    """
    tokens = calls = skipped = 0
    for row in rows:
        usage = row.get("tokens", {})
        n = row.get("call_count", 0)
        if row.get("carried_forward") or not n:
            continue
        if usage.get("usage_missing", True) or any(
            type(usage.get(k)) is not int for k in ("input", "output")
        ):
            skipped += n
            continue
        tokens += usage["input"] + usage["output"]
        calls += n
    return dict(
        reported_tokens=tokens,
        reported_calls=calls,
        skipped_calls=skipped,
        mean_tokens=tokens / calls if calls else None,
        tokens_with_margin=math.ceil(1.5 * tokens / calls) if calls else 3072,
    )


def measured_parents(root):
    """Read only exact historical prediction ledgers; no tracking calls."""
    from bugzilla_qa.evaluation.systems import select_predictions
    from bugzilla_serving.tracking.backfill import discover_ledgers, load_dev_items, read

    rows = {f"S{i}": [] for i in range(9)}
    source = root / "outputs/evaluation/phase11/pilot125"
    if source.exists():
        for dataset, folder in discover_ledgers(source, root).items():
            items, _ = load_dev_items(root, read(root / "configs/retrieval_v3.yaml"), dataset)
            selected, _, _ = select_predictions(folder, items, list(rows))
            for system, predictions in selected.items():
                rows[system].extend(predictions.values())
    result = {s: measured_usage(values) for s, values in rows.items()}
    # Prefer this variant's own history as soon as measured calls exist.
    own = []
    for path in (root / "outputs/predictions/v2/dev").glob("run-*/S7v2.jsonl"):
        own.extend(json.loads(line) for line in path.read_text().splitlines())
    own_stats = measured_usage(own)
    result["S7v2"] = own_stats if own_stats["reported_calls"] else result["S7"]
    for route, parent in (("S7v2", "S7v2"), ("S2", "S2"), ("S5", "S5")):
        own = []
        for path in (root / "outputs/predictions/v2/dev").glob("run-*/S8v2.jsonl"):
            own.extend(
                r for r in map(json.loads, path.read_text().splitlines()) if r.get("route") == route
            )
        stats = measured_usage(own)
        result["S8v2:" + route] = stats if stats["reported_calls"] else result[parent]
    return result


def route_usage(history, system, route):
    parent = "S7v2" if route == "S7v2" else route or "S7v2"
    return history.get(system + ":" + parent, history[parent])


def historical_total(cfg, root, history=None):
    if history is not None:
        for row in sorted(history, key=lambda r: r.get("started", 0), reverse=True):
            m, p = row["metrics"], row["params"]
            if (
                p.get("system_id") == cfg.system_id
                and p.get("model") == cfg.model
                and m.get("cost.usage_missing_n") == 0
                and m.get("cost.llm_calls", 0) > 0
                and all(m.get("cost." + k) is not None for k in ("tokens_in", "tokens_out"))
            ):
                return math.ceil(
                    1.5 * (m["cost.tokens_in"] + m["cost.tokens_out"]) / m["cost.llm_calls"]
                )
        return None
    stats = measured_parents(root).get(cfg.system_id, {})
    return stats.get("tokens_with_margin") if stats.get("reported_calls") else None


def unknown_call_estimate(event, parents, events, cfg, llm):
    """Reported historical cost +50%, never a default full-TPM reservation."""
    purpose = event.get("purpose", "")
    matched = [
        e["input_tokens"] + e["output_tokens"]
        for e in events
        if e.get("purpose") == purpose
        and e.get("status") in ("SUCCESS", "ERROR")
        and all(type(e.get(k)) is int for k in ("input_tokens", "output_tokens"))
    ]
    if matched:
        return math.ceil(1.5 * sum(matched) / len(matched))
    parent = (
        ("S8v2:S7v2" if cfg.system_id == "S8" else "S7v2")
        if "tool" in purpose or "json-plan" in purpose
        else cfg.system_id
    )
    if parent not in parents:
        parent = "S7" if "tool" in purpose or "json-plan" in purpose else cfg.system_id
    stats = parents.get(parent, {})
    if stats.get("reported_calls"):
        return stats["tokens_with_margin"]
    values = [
        e["input_tokens"] + e["output_tokens"]
        for e in events
        if e.get("status") in ("SUCCESS", "ERROR")
        and all(type(e.get(k)) is int for k in ("input_tokens", "output_tokens"))
    ]
    if values:
        return math.ceil(1.5 * sum(values) / len(values))
    # Cold-start fixtures/no historical usage: explicit output-based estimate,
    # separate from the unchanged per-request input+max-output gate.
    return math.ceil(1.5 * llm.get("max_output_tokens", 2048))

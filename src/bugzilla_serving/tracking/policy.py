"""Predeclared dev-only promotion gate; no registry mutation."""

from bugzilla_serving.contracts.names import FAMILIES


def assess(candidate, peers, policy):
    metrics, tags = candidate.data.metrics, candidate.data.tags
    errors = []
    if tags.get("split") != "dev" or tags.get("eval_set") != policy["eval_set"]:
        errors.append("requires dev results in configured eval_set")
    coverage = {f for f in FAMILIES if f"answer.{f}.score" in metrics}
    if not coverage:
        errors.append("no scored families")
    for family in sorted(coverage):
        if metrics[f"answer.{family}.score"] < policy["min_family_score"]:
            errors.append(f"{family}: below minimum score")
        if metrics.get(f"answer.{family}.n", 0) < policy["minimum_family_n"]:
            errors.append(f"{family}: insufficient n")
    for key, cap in [
        ("abstain.false_rate", policy["max_false_abstain_rate"]),
        ("fail.rate", policy["max_fail_rate"]),
    ]:
        if key not in metrics or metrics[key] > cap:
            errors.append(f"{key}: missing or above limit")
    if "latency.p95_ms" not in metrics or "answer.macro" not in metrics:
        errors.append("missing macro or p95 latency")
    if int(tags.get("pending_n", "0")):
        errors.append("ungraded source rows remain")
    eligible = []
    for peer in peers:
        m, t = peer.data.metrics, peer.data.tags
        other = {f for f in FAMILIES if f"answer.{f}.score" in m}
        if t.get("split") != "dev" or t.get("eval_set") != policy["eval_set"]:
            continue
        if other != coverage:
            errors.append("peer family coverage differs; comparable evaluation required")
            continue
        if (
            other
            and "answer.macro" in m
            and "latency.p95_ms" in m
            and m.get("abstain.false_rate", 2) <= policy["max_false_abstain_rate"]
            and m.get("fail.rate", 2) <= policy["max_fail_rate"]
            and not int(t.get("pending_n", "0"))
            and all(
                m[f"answer.{f}.score"] >= policy["min_family_score"]
                and m.get(f"answer.{f}.n", 0) >= policy["minimum_family_n"]
                for f in other
            )
        ):
            eligible.append(peer)
    if eligible:
        best = max(r.data.metrics["answer.macro"] for r in eligible)
        tied = [
            r for r in eligible if best - r.data.metrics["answer.macro"] <= policy["tie_margin"]
        ]
        winner = min(tied, key=lambda r: (r.data.metrics["latency.p95_ms"], r.info.run_id))
        if candidate.info.run_id != winner.info.run_id:
            errors.append("not the eligible winner under macro/latency rule")
    return dict(allowed=not errors, reasons=sorted(set(errors)), families=sorted(coverage))

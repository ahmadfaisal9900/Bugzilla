#!/usr/bin/env python3
"""Inspect or explicitly publish a deployable configuration; never silently select champion."""

import argparse
import json

from bugzilla_serving.contracts.names import REGISTRY_MODEL_NAME
from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.tracking.client import assert_no_secrets
from bugzilla_serving.tracking.policy import assess
from bugzilla_serving.tracking.registry import Registry, executable


def publish(
    registry,
    run_id,
    slug,
    label,
    description,
    champion=False,
    apply=False,
    override_policy=None,
    policy=None,
):
    from bugzilla_serving.tracking.backfill import read

    run = registry.client.get_run(run_id)
    if run.data.tags.get("split") != "dev":
        raise ValueError("Only dev configurations may be published")
    values = {}
    for k in RunConfig.model_fields:
        raw = run.data.params[k]
        try:
            values[k] = json.loads(raw)
        except (TypeError, ValueError):
            values[k] = raw
    # Never bypass execution validation, even with a policy override.
    cfg = executable(values)
    policy = policy or read(ROOT / "configs/promotion.yaml")
    peers = registry.tracking.runs("research-answer-eval")
    result = assess(run, peers, policy)
    old = registry.get_champion()
    current = registry.client.get_run(old.tags.get("source_run_id", old.run_id)) if old else None
    comparison = []
    for family in result["families"]:
        key = f"answer.{family}"
        comparison.append(
            dict(
                family=family,
                candidate_score=run.data.metrics.get(key + ".score"),
                candidate_n=run.data.metrics.get(key + ".n"),
                champion_score=current.data.metrics.get(key + ".score") if current else None,
                champion_n=current.data.metrics.get(key + ".n") if current else None,
            )
        )
    if apply:
        if champion and not result["allowed"] and not override_policy:
            raise ValueError("Promotion policy failed: " + "; ".join(result["reasons"]))
        tags = dict(source_run_id=run_id, git_sha=run.data.tags["git_sha"])
        if override_policy:
            if not override_policy.strip():
                raise ValueError("Override reason must not be blank")
            assert_no_secrets(override_policy)
            tags["policy_override"] = override_policy
        version = registry.register_config_version(cfg, tags)
        # Reused model versions must retain current decision provenance as well.
        for key, value in tags.items():
            registry.client.set_model_version_tag(REGISTRY_MODEL_NAME, str(version), key, value)
        registry.publish_preset(version, slug, label, description)
        if champion:
            registry.set_champion(version)
    else:
        version = None
    return dict(
        state="APPLIED" if apply else "DRY_RUN",
        policy=result,
        comparison=comparison,
        version=version,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--label")
    parser.add_argument("--description")
    parser.add_argument("--champion", action="store_true")
    parser.add_argument("--unpublish", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--override-policy")
    parser.add_argument("--tracking-uri")
    args = parser.parse_args()
    registry = Registry(args.tracking_uri)
    if args.unpublish:
        if args.apply:
            registry.unpublish(args.slug)
        print(json.dumps(dict(state="APPLIED" if args.apply else "DRY_RUN", unpublish=args.slug)))
        return
    if not all((args.run_id, args.label, args.description)):
        parser.error("--run-id, --label and --description are required for publication")
    result = publish(
        registry,
        args.run_id,
        args.slug,
        args.label,
        args.description,
        args.champion,
        args.apply,
        args.override_policy,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

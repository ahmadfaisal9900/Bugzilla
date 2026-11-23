"""Explicit champion alias rollback; no preset publication or config mutation."""

import datetime as dt

from bugzilla_serving.contracts.names import REGISTRY_MODEL_NAME
from bugzilla_serving.tracking.client import assert_no_secrets


def rollback(registry, to_version=None, reason="", apply=False):
    old = registry.get_champion()
    if old is None:
        raise ValueError("No current champion")
    versions = registry.versions()
    target = (
        str(to_version)
        if to_version is not None
        else str(
            max((int(v.version) for v in versions if int(v.version) < int(old.version)), default=0)
        )
    )
    if target == str(old.version):
        if apply:
            raise ValueError("Target is already champion")
        return dict(
            state="DRY_RUN",
            before=str(old.version),
            after=target,
            reason="Target is already champion",
            would_change=False,
        )
    if target not in {str(v.version) for v in versions}:
        raise ValueError("No previous/target version exists; specify --to-version")
    registry.get_config(target)  # Revalidate target before any alias mutation.
    if apply:
        if not reason.strip():
            raise ValueError("--reason is required with --apply")
        assert_no_secrets(reason)
        tags = dict(
            rollback_reason=reason,
            rolled_back_from=str(old.version),
            rolled_back_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        for key, value in tags.items():
            registry.client.set_model_version_tag(REGISTRY_MODEL_NAME, target, key, value)
        registry.set_champion(target)
    return dict(
        state="APPLIED" if apply else "DRY_RUN",
        before=str(old.version),
        after=target,
        reason=reason,
    )

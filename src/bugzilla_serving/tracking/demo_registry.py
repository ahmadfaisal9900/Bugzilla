"""Small serving-cap promotion, independent of immutable historical B9 configs."""

from bugzilla_serving.contracts.names import REGISTRY_MODEL_NAME
from bugzilla_serving.contracts.run_config import ROOT, RunConfig, config_hash

DESCRIPTION = (
    "Best on our evaluation (92.5%): routes each question to the database, "
    "the bug dossier or smart search"
)


def configs():
    import yaml

    return {
        p["slug"]: RunConfig(**p["config"]).validate_against()
        for p in yaml.safe_load((ROOT / "configs/presets.yaml").read_text())["presets"]
    }


def promote(tracking_uri=None, *, apply=False, rollback_version=None, registry=None):
    from bugzilla_serving.tracking.registry import Registry

    registry = registry or Registry(tracking_uri)
    client = registry.client
    old = registry.get_champion()
    # Fail before any write unless the rollback destination and fast identity are known.
    fast = client.get_model_version_by_alias(REGISTRY_MODEL_NAME, "fast")
    if registry.get_config(fast.version).system_id != "S1":
        raise ValueError("fast alias must identify S1; no changes made")
    if rollback_version is not None:
        target = registry.get_config(str(rollback_version))
        if target.system_id != "S2":
            raise ValueError("Rollback requires an explicit S2 version")
        if apply:
            registry.set_champion(str(rollback_version))
        return dict(
            state="APPLIED" if apply else "DRY_RUN",
            action="rollback",
            champion=str(rollback_version),
            fast_unchanged=str(fast.version),
            llm_calls=0,
        )
    if old is None:
        raise ValueError("Expected an existing champion; no changes made")
    previous = registry.get_config(old.version)
    if previous.system_id not in ("S2", "S8v2"):
        raise ValueError("Expected S2 or the previously promoted S8v2 champion")
    desired = configs()
    if desired["recommended"].system_id != "S8v2":
        raise ValueError("Recommended fallback must be S8v2")
    result = dict(
        state="APPLIED" if apply else "DRY_RUN",
        action="promote",
        previous_champion=str(old.version),
        previous_system=previous.system_id,
        fast_unchanged=str(fast.version),
        configs={
            k: dict(config=v.model_dump(), config_hash=config_hash(v))
            for k, v in desired.items()
            if k in ("recommended", "deep")
        },
        llm_calls=0,
    )
    if apply:
        versions = {}
        for slug, label, description in [
            ("recommended", "Recommended", DESCRIPTION),
            ("deep", "Deep read", "Full bug dossier capped at 4,096 bytes"),
        ]:
            cfg = desired[slug]
            version = registry.register_config_version(
                cfg,
                dict(
                    system_id=cfg.system_id,
                    source="serving-demo",
                    evaluation_note="92.5% is historical dev composite; serving cap differs",
                ),
            )
            registry.publish_preset(version, slug, label, description)
            versions[slug] = str(version)
        # Reload the artifact through the shared execution gate before moving the alias.
        if registry.get_config(versions["recommended"]) != desired["recommended"]:
            raise ValueError("Registered config differs; champion unchanged")
        registry.set_champion(versions["recommended"])
        result["versions"] = versions
    return result

"""Promotion previews have no writes; rollback validates S2; fast is untouched."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bugzilla_serving.contracts.run_config import RunConfig
from bugzilla_serving.tracking.demo_registry import configs, promote


def registry():
    value = Mock()
    value.get_champion.return_value = SimpleNamespace(version="2")
    value.client.get_model_version_by_alias.return_value = SimpleNamespace(version="1")
    desired = configs()
    value.get_config.side_effect = lambda v: {
        "1": RunConfig(system_id="S1"),
        "2": RunConfig(system_id="S2"),
        "3": desired["recommended"],
        "4": desired["deep"],
    }[str(v)]
    value.register_config_version.side_effect = ["3", "4"]
    return value


def test_preview_and_apply():
    value = registry()
    result = promote(registry=value)
    assert result["state"] == "DRY_RUN" and result["previous_champion"] == "2"
    value.register_config_version.assert_not_called()
    value.set_champion.assert_not_called()
    result = promote(registry=value, apply=True)
    assert result["versions"] == {"recommended": "3", "deep": "4"}
    value.set_champion.assert_called_once_with("3")
    value.client.set_registered_model_alias.assert_not_called()


def test_rollback():
    value = registry()
    promote(registry=value, rollback_version="2")
    value.set_champion.assert_not_called()
    promote(registry=value, rollback_version="2", apply=True)
    value.set_champion.assert_called_once_with("2")
    with pytest.raises(ValueError, match="S2"):
        promote(registry=value, rollback_version="1", apply=True)

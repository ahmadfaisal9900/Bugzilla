"""Approved archival validation amendment; execution remains strict."""

import pytest

from bugzilla_serving.contracts.names import CONFIG_ORIGIN_TAG, validate_mlflow_run
from bugzilla_serving.contracts.run_config import RunConfig
from bugzilla_serving.tracking.client import params_for


@pytest.mark.contract
@pytest.mark.parametrize(
    "values",
    [
        {"system_id": "S5", "s5_dossier_budget": 12000},
        {"top_k": 100, "temperature": 2.0, "s7_max_tool_steps": 20},
        {"model": "historical-model"},
    ],
)
def test_record_not_execute(values):
    cfg = RunConfig(**values).validate_against(mode="record")
    with pytest.raises(ValueError):
        cfg.validate_against()
    tags = dict(
        source="backfill",
        eval_set="synthetic",
        datasets="synthetic",
        split="dev",
        scorer="synthetic",
        git_sha="synthetic",
        config_origin="historical",
    )
    validate_mlflow_run(params_for(cfg), tags, {})
    tags["source"] = "lab"
    with pytest.raises(ValueError, match=CONFIG_ORIGIN_TAG):
        validate_mlflow_run(params_for(cfg), tags, {})


@pytest.mark.contract
def test_record_still_checks_fields_types_and_mode():
    for values in ({"extra": 1}, {"top_k": "10"}, {"top_k": True}, {"retriever": "R99"}):
        with pytest.raises(ValueError):
            RunConfig(**values).validate_against(mode="record")
    with pytest.raises(ValueError, match="mode"):
        RunConfig().validate_against(mode="typo")
    with pytest.raises(ValueError):
        RunConfig.model_construct(top_k="10").validate_against(mode="record")

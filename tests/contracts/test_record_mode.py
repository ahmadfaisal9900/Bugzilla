"""Approved archival validation amendment; execution remains strict."""

import pytest

from bugzilla_serving.contracts.names import CONFIG_ORIGIN_TAG, answer_metric, validate_mlflow_run
from bugzilla_serving.contracts.run_config import RunConfig
from bugzilla_serving.tracking.client import params_for


def test_pending_metric_is_an_explicit_nonnegative_integer_count():
    assert answer_metric("F5", "pending") == "answer.F5.pending"
    tags = dict(
        source="ci",
        eval_set="synthetic",
        datasets="synthetic",
        split="dev",
        scorer="synthetic",
        git_sha="synthetic",
    )
    params = params_for(RunConfig())
    validate_mlflow_run(params, tags, {"answer.F5.n": 0, "answer.F5.pending": 6})
    for bad in (-1, 0.5, True):
        with pytest.raises(ValueError):
            validate_mlflow_run(params, tags, {"answer.F5.pending": bad})


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
    # An invalid enum exercises model_construct revalidation without passing a
    # string to an integer serializer (which itself correctly emits a warning).
    with pytest.raises(ValueError):
        RunConfig.model_construct(retriever="R99").validate_against(mode="record")

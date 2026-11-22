"""Small sequential grids, refused before execution if the combined budget does not fit."""

from itertools import product

from bugzilla_serving.contracts.run_config import ROOT, RunConfig
from bugzilla_serving.experiments.data import digest, load_eval_set
from bugzilla_serving.experiments.preflight import estimate
from bugzilla_serving.experiments.runner import run_experiment


def plan_sweep(base_cfg, grid, eval_set, limit=None, *, root=ROOT, sets_path=None):
    if not grid or len(grid) > 2 or any(not values for values in grid.values()):
        raise ValueError("Sweep needs one or two nonempty knobs")
    if any(k not in RunConfig.model_fields for k in grid):
        raise ValueError("Unknown sweep knob")
    values = list(product(*grid.values()))
    if len(values) > 16:
        raise ValueError("Course-project sweeps are limited to 16 points")
    configs = [
        RunConfig(**{**base_cfg.model_dump(), **dict(zip(grid, v))}).validate_against()
        for v in values
    ]
    if len({digest(c.model_dump()) for c in configs}) != len(configs):
        raise ValueError("Duplicate sweep configurations")
    items, pins = load_eval_set(eval_set, limit, root=root, sets_path=sets_path)
    plans = [estimate(cfg, items, root=root) for cfg in configs]
    # Grids may contain different models; each model gets its own combined budget.
    totals = {}
    for cfg, plan in zip(configs, plans):
        total = totals.setdefault(cfg.model, dict(calls=0, tokens=0, remaining=plan["remaining"]))
        total["calls"] += plan["est_calls"]
        total["tokens"] += plan["est_tokens"]
    fits = all(p["fits"] for p in plans) and all(
        t["calls"] <= t["remaining"]["requests"] and t["tokens"] <= t["remaining"]["tokens"]
        for t in totals.values()
    )
    sid = digest(dict(grid=grid, base=base_cfg.model_dump(), eval_set=eval_set, pins=pins))[:20]
    return configs, dict(
        fits=fits,
        sweep_id=sid,
        points=len(configs),
        totals=totals,
        reason="combined grid fits" if fits else "combined grid exceeds quota",
    )


def run_sweep(base_cfg, grid, eval_set, limit=None, **kwargs):
    configs, plan = plan_sweep(
        base_cfg,
        grid,
        eval_set,
        limit,
        root=kwargs.get("root", ROOT),
        sets_path=kwargs.get("sets_path"),
    )
    if not plan["fits"]:
        raise ValueError(plan["reason"])
    if kwargs.get("enable_llm") and sum(t["calls"] for t in plan["totals"].values()) > kwargs.get(
        "max_requests", 100
    ):
        raise ValueError("Total sweep exceeds --max-requests")
    # Hold a separate sweep lock; each point still acquires the shared active-job lock.
    from pathlib import Path

    from bugzilla_serving.experiments.runner import job_lock

    jobs = Path(kwargs.get("jobs_dir") or kwargs.get("root", ROOT) / "outputs/mlops/jobs")
    results, used = [], 0
    with job_lock(jobs / "sweeps"):
        for cfg in configs:
            point_kwargs = {**kwargs}
            if kwargs.get("enable_llm"):
                point_kwargs["max_requests"] = kwargs.get("max_requests", 100) - used
            state = run_experiment(cfg, eval_set, limit, sweep_id=plan["sweep_id"], **point_kwargs)
            results.append(state)
            used += state.get("actual_requests", 0)
            if state["state"] != "COMPLETED":
                break
    return dict(plan=plan, jobs=results)

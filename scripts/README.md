# Scripts

Run every script from the repository root, e.g. `python scripts/app/fetch_models.py`.

| Folder | What's in it |
| --- | --- |
| `app/` | Run and package the app: `run_local.ps1` (API + chat + dashboard), `fetch_models.py`, `build_serving_bundle.py`, `verify_bundle.py`, `export_sample_bundle.py`, `check_serving_tracing.py`, `llm_ping.py` |
| `testing/` | Tests and fixtures: `test_coverage.ps1` / `test_coverage.sh` (offline tests + coverage, like CI), `smoke.sh` (checks a running stack), `check_structure.sh`, `build_fixture_bundle.py`, `seed_mlflow_fixture.py` |
| `mlops/` | MLflow, LangSmith and promotion tools: experiments, backfills, presets, champion rollback, dashboard snapshot, F5 grading |
| `phases/` | One runner per research phase (`run_phaseNN_*.sh` / `.ps1`) and `run_eval_extension.sh` |

Test and coverage reports go to `results/coverage/` (ignored by git).

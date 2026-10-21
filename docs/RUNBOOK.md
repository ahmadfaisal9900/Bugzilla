# Runbook

## Environment setup

Phase 0 adds no runtime dependencies. From the repository root, create an isolated environment when beginning implementation:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Install only dependencies required by the active phase. Copy `.env.example` to `.env` only if a later phase requires credentials; never commit `.env`.

## Phase 0 smoke checks

```bash
bash scripts/smoke/check_structure.sh
PYTHONPATH=src python -c 'import bugzilla_qa, bugzilla_qa.data, bugzilla_qa.benchmark, bugzilla_qa.retrieval, bugzilla_qa.methods, bugzilla_qa.evaluation, bugzilla_qa.app'
```

There are no functional tests yet because no data or QA behavior is implemented.

## Running phase scripts

Each future phase script should be executable Bash, accept documented configuration/paths, write restartable logs under `logs/`, and avoid processing data without an explicit user-run command. Run it from the repository root using the exact command documented for that phase. Do not run large extraction, embedding, or evaluation jobs in an interactive agent session.

## Logs and result validation

Execution logs belong under `logs/`; generated indexes, tables, predictions, and other artifacts belong under `outputs/`. Both are Git-ignored. Before reporting a result, inspect the run log and output files, verify the recorded configuration, snapshot, and seed, and update `docs/EXPERIMENT_REGISTRY.md` and `docs/RESEARCH_STATUS.md` with the observed state.

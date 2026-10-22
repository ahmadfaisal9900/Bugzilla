# Runbook

## Environment setup

The project root is `/home/ict317/master's/ENSF 621/Project/`. Phase 0 adds no runtime dependencies. From this root, create an isolated environment when beginning implementation:

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

The bounded scaffold test uses only the Python standard library:

```bash
python3 -m unittest discover -s tests -v
```

## Running phase scripts

Each future long-running phase job should be an executable `scripts/run_phaseNN_*.sh` with `--dry-run`, applicable limits, resumable checkpoints, timestamps, logs, and a summary JSON. Give the exact terminal command; the user runs jobs in their own terminal. Do not run large extraction, imports, embeddings, or evaluations in an interactive agent session.

## Data and GitHub

The local inputs are under root-level `Dataset/`; the entire directory is Git-ignored. Do not alter/copy it or run the upstream scripts. The existing `origin` is `https://github.com/ahmadfaisal9900/Bugzilla.git`. Do not create another repository or change this remote.

Before committing, run the relevant bounded tests, inspect `git diff`, and review exact staged filenames. Stage named code/docs/small manifests only; preserve unrelated existing edits.

## Logs and result validation

Execution logs belong under `logs/`; generated indexes, tables, predictions, and other artifacts belong under `outputs/`. Both are Git-ignored. Before reporting a result, inspect the run log and output files, verify the recorded configuration, snapshot, and seed, and update `docs/EXPERIMENT_REGISTRY.md` and `docs/RESEARCH_STATUS.md` with the observed state.

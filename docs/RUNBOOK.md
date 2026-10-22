# Runbook

## Environment setup

The project root is `/home/ict317/master's/ENSF 621/Project/`. Phase 3A adds no runtime dependencies or install step; its wrapper sets `PYTHONPATH=src`. For a direct module invocation, use `PYTHONPATH=src python -m bugzilla_qa.data.profile`. Create an isolated environment only when a later phase adds required packages and a matching dependency manifest:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

No editable install manifest currently exists. Install only dependencies required by the active phase. Copy `.env.example` to `.env` only if a later phase requires credentials; never commit `.env`.

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

Each future long-running phase job should be an executable script under `scripts/` with `--dry-run`, applicable limits, resumable checkpoints, timestamps, logs, and a summary JSON. Give the exact terminal command; the user runs jobs in their own terminal. Do not run large extraction, imports, embeddings, or evaluations in an interactive agent session.

### Phase 2 dataset audit

The completed full audit is summarized in `docs/DATA_AUDIT_SUMMARY.md`. Its ignored reports are under `outputs/audit/phase02/`; do not rerun Phase 2 unless an input changes and a new audit is needed.

### Phase 3A BugsRepo profile

Confirm repository-relative input paths in ignored `configs/data_paths.local.yaml`; the tracked template lists the inspected sources. Full profile command (user terminal only):

```bash
bash scripts/phases/run_phase03a_explore.sh
```

For a non-dry-run bounded smoke profile, add `--limit 20`; for a path/size-only plan, use `--dry-run --limit 20`. Resume completed source checkpoints after interruption with `--resume`. The profiler stores `profile.json`, small `summary.json`, `checkpoint.json`, `profile_index.sqlite3`, logs, and five SVG plots under `outputs/data_exploration/<run-id>/`. It reuses the verified Part 1/2 full SHA only while both current file size and modification-time signatures match; otherwise full mode computes hashes while streaming. Limited sources have prefix-only counts and no whole-file checksum claim. Do not commit these machine outputs.

After the user's full run, inspect the machine report and update `docs/DATA_EXPLORATION.md`, `docs/DATA_AUDIT_SUMMARY.md`, and `docs/RESEARCH_STATUS.md` with sanitized aggregates only. Do not select T0/T1 or begin ingestion before reviewing duplicate populations, selection bias, source rights, and privacy.

Previous Phase 2 invocation was:

```bash
bash scripts/run_phase02_audit.sh
```

Its completed-source checkpoint behavior and output layout are retained for reproducibility; its results are already reviewed in the summary linked above.

## Data and GitHub

The local inputs are under root-level `Dataset/`; the entire directory is Git-ignored. Do not alter/copy it or run the upstream scripts. The existing `origin` is `https://github.com/ahmadfaisal9900/Bugzilla.git`. Do not create another repository or change this remote.

Before committing, run the relevant bounded tests, inspect `git diff`, and review exact staged filenames. Stage named code/docs/small manifests only; preserve unrelated existing edits.

## Logs and result validation

Execution logs may live under `logs/` or beside a phase's outputs; generated indexes, tables, predictions, and other artifacts belong under `outputs/`. Both are Git-ignored. Before reporting a result, inspect the run log and output files, verify the recorded configuration, snapshot, and seed, and update the relevant phase docs with the observed state.

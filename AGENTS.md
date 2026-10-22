# Project agent instructions

- The authoritative repository root is the existing `Project/` directory, and its GitHub remote is [https://github.com/ahmadfaisal9900/Bugzilla.git](https://github.com/ahmadfaisal9900/Bugzilla.git). Never create another repository, initialize nested Git projects, or change remotes without explicit user approval.
- Before starting a phase, read `docs/RESEARCH_STATUS.md` and `docs/reference/research_roadmap.tex`.
- Implement one phase at a time and keep solutions proportional to a course project.
- Prefer deterministic, free, local methods. Minimize tokens by inspecting only relevant files and summarizing large outputs.
- Do not delegate or fan out to subagents. Avoid extensive review workflows unless requested.
- Never run long dataset processing, bulk API collection, bulk CSV imports, embedding generation, or large evaluations in an interactive agent session. Implement and run only bounded tests with tiny fixtures (about 30 seconds or less).
- For future data/API/evaluation jobs, write an executable `scripts/run_phaseNN_*.sh` with `--dry-run`, applicable `--limit`/`--max-requests`, resumable checkpoints, timestamps, log paths, and a summary JSON. Give the exact command; jobs run only when the user invokes them in their own terminal.
- Require a working minimal test before committing. After each phase, run targeted checks, update research documentation, inspect the diff and exact staged filenames, and commit/push verified code and documentation.
- Never commit raw data, model artifacts, credentials, or large logs. Never claim an experiment succeeded before reviewing its results.
- Report blockers explicitly and distinguish implemented, smoke-tested, executed, and validated states.
- Preserve existing edits. Stage named files only; never use `git add -A` or unrestricted `git add .`, force-push, or rewrite history.

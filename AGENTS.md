# Project agent instructions

- Before starting a phase, read `docs/RESEARCH_STATUS.md` and `docs/reference/research_roadmap.tex`.
- Implement one phase at a time and keep solutions proportional to a course project.
- Prefer deterministic, free, local methods. Minimize tokens by inspecting only relevant files and summarizing large outputs.
- Do not invoke unnecessary subagents or extensive review workflows.
- Never run long dataset processing, API collection, embedding generation, or large evaluations in an interactive agent session. Write a fully executable Bash script with clear logging and restart behavior, and give the exact terminal command for the user to run.
- Run only bounded smoke checks during implementation. After each phase, run the requested checks, update research documentation, and commit/push verified code and documentation.
- Never commit raw data, model artifacts, credentials, or large logs. Never claim an experiment succeeded before reviewing its results.
- Report blockers explicitly and distinguish implemented, smoke-tested, executed, and validated states.

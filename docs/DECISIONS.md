# Decisions

| ID | Decision | Rationale / status |
|---|---|---|
| D-001 | Use a `src/bugzilla_qa/` Python package with separate data, benchmark, retrieval, methods, evaluation, and app subpackages. | Matches the planned research components while keeping Phase 0 free of system implementation. |
| D-002 | Ignore the complete root-level `Dataset/` directory, including the nested `EASE_2025_Data_paper` clone. | Protects downloaded data and upstream source from accidental staging or commits. |
| D-003 | Keep generated results and logs in `outputs/` and `logs/`, and ignore their contents. | Keeps reproducible source/configuration in Git while excluding local artifacts. |
| D-004 | Add no runtime dependencies in Phase 0. | Dependencies will be selected only when needed for a bounded, reproducible phase. |
| D-005 | Treat `docs/reference/research_roadmap.tex` as the authoritative scientific plan. | It defines scope, methods, benchmark, and temporal protocol; no results are implied by it. |

These decisions establish workspace structure only; they do not select a dataset snapshot or implement an experiment.

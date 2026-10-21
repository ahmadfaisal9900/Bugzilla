# Research status

## Current phase

Phase 0 — project structure, Git safety, and research workspace.

## Completed steps

- Inspected the working tree, branch, configured remote, tracked files, and existing project files.
- Read the research roadmap and recorded its SHA-256 before setup: `1b2b2ec9fade96437eda58a1e6e3d026dc7b1999a4fd25fffc21bf7d0debd971`.
- Created the source-package skeleton, experiment/documentation directories, initial configuration, and Git safety rules.
- The initial repository commit inspected before Phase 0 was `9353e1119b5e8831c774ba3b7767dc7cf4215aa1`; Phase 0 changes are pending their requested commit at initial documentation time.
- The package imports and structure/ignore smoke checks passed.
- The roadmap still matches its recorded SHA-256. No dataset was modified, copied, or processed. No model or QA system was implemented.

## Pending steps

- Commit and push the validated Phase 0 scaffold; record the resulting commit and push status.
- Phase 1: perform the roadmap's bounded literature and data-source audit; choose a data snapshot only after measuring available fields and history coverage.
- Later: build the audited data pipeline and benchmark before implementing the QA methods.

## Repository and dataset locations

- Repository: `/home/ict317/master's/ENSF 621/Project/`
- Existing dataset bundle and upstream preprocessing source: `/home/ict317/master's/ENSF 621/Project/Dataset/` (must remain local and Git-ignored)
- Authoritative roadmap: `docs/reference/research_roadmap.tex`

## Current scientific scope

Compare M0 closed-book, M1 BM25 RAG, M2 hybrid RAG, and M3 structured SQL for questions about Mozilla Firefox-product Bugzilla history. The planned benchmark has 180 candidate questions across six families (F1–F6), with temporal evaluation and optional graph retrieval later. These are roadmap targets, not implemented systems or experimental results. No corpus snapshot or benchmark items have been selected or generated.

## Last verified commit

Baseline commit inspected at Phase 0 start: `9353e1119b5e8831c774ba3b7767dc7cf4215aa`. The validated Phase 0 changes are awaiting commit and push.

## Next action

Complete the Phase 0 commit and push. Then begin Phase 1 by rereading this status and the roadmap and planning a bounded source audit; do not run large data processing or API collection interactively.

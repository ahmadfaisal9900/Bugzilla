#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

required_paths=(
  "src/bugzilla_qa/data/__init__.py"
  "src/bugzilla_qa/benchmark/__init__.py"
  "src/bugzilla_qa/retrieval/__init__.py"
  "src/bugzilla_qa/methods/__init__.py"
  "src/bugzilla_qa/evaluation/__init__.py"
  "src/bugzilla_qa/app/__init__.py"
  "configs"
  "scripts/phases"
  "scripts/smoke"
  "tests"
  "outputs"
  "logs"
  "docs/RESEARCH_STATUS.md"
  "docs/PHASE_LOG.md"
  "docs/DECISIONS.md"
  "docs/EXPERIMENT_REGISTRY.md"
  "docs/RUNBOOK.md"
  "docs/reference/research_roadmap.tex"
)

for path in "${required_paths[@]}"; do
  if [[ ! -e "$path" ]]; then
    printf 'Missing required path: %s\n' "$path" >&2
    exit 1
  fi
done

PYTHONPATH=src python -c 'import bugzilla_qa, bugzilla_qa.data, bugzilla_qa.benchmark, bugzilla_qa.retrieval, bugzilla_qa.methods, bugzilla_qa.evaluation, bugzilla_qa.app'
git check-ignore -q Dataset/EASE_2025_Data_paper/README.md
git check-ignore -q outputs/phase0-smoke-artifact
git check-ignore -q logs/phase0-smoke.log

printf 'Phase 0 structure, imports, and ignore smoke checks passed.\n'

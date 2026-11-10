# Retrieval extension runbook

The extension is incomplete. Do not use it for study comparisons or an overnight end-to-end run yet. Use the existing project Python environment with `duckdb==1.4.4`; SQLite must have FTS5. No new package or API key is needed for the implemented lexical stages.

Inspect the interface and dry run:

```bash
bash scripts/run_eval_extension.sh --help
bash scripts/run_eval_extension.sh --stage preflight --dry-run
```

For a tiny terminal-only local demonstration, use the same limit on each stage:

```bash
bash scripts/run_eval_extension.sh --stage corpus --limit 1 --resume
bash scripts/run_eval_extension.sh --stage lexical --limit 1 --resume
bash scripts/run_eval_extension.sh --stage search --limit 1 --query 'bug 123 printing'
```

Run outputs are ignored in `outputs/eval_extension/<identity-prefix>/`. `corpus.jsonl` contains local source text, `corpus_manifest.json` records its identity and hash, and `lexical.sqlite` plus `lexical_manifest.json` record the index and hash. The `--limit` value is part of the identity. `--resume` verifies completed-stage hashes and skips those stages; a partially written corpus is rebuilt, not resumed within a file. Index creation is transactional. `--stage all` currently ends with a nonzero status and a clear message because the remaining stages do not exist. Do not interpret its lexical output as a complete experiment.

The generated review UI and original Phase 5 queue are separate. Follow `docs/PHASE05_ASSISTED_REVIEW_PROTOCOL.md` and `docs/RUNBOOK.md` to audit genuine signed decisions, transfer them without impersonation, and complete global signoff. Only then run:

```bash
bash scripts/run_phase05_validate_freeze.sh --run outputs/benchmark/phase05/run-65c5be3381f66811 --seed 317 --resume
```

Do not use the original test split for tuning, and do not create a test report until the actual freeze is verified. No full dataset or embedding job has been run for this extension.

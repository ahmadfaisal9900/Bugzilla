# Retrieval extension runbook

All large stages run in the user's terminal. The following assumes the existing `iqfm` environment and verified local Phase 3B/4 files. No API key is required for retrieval. Check dependency changes before installing; model packages can require substantial disk space and may add or change dependencies:

```bash
conda activate iqfm
python -m pip install --dry-run -r requirements-eval-extension.txt
python -m pip install -r requirements-eval-extension.txt
```

The first dense and reranking run may download `sentence-transformers/all-MiniLM-L6-v2` and `cross-encoder/ms-marco-MiniLM-L-6-v2` from Hugging Face. The resolved model revision is recorded. CPU is the default; `--device cuda` is optional. Time and disk are unmeasured: allow several hours and multiple GB for first-time Python/torch/model installation on CPU; the actual corpus and model cache determine space. No model was downloaded during implementation.

Inspect, then run the development pipeline (no LLM calls):

```bash
bash scripts/run_eval_extension.sh --help
bash scripts/run_eval_extension.sh --dry-run --resume
bash scripts/run_eval_extension.sh --resume
```

Stages continue where independent work is possible and report `BLOCKED`/`PARTIAL`; the shell exits nonzero if a stage is blocked. Install missing dependencies or provide missing files and repeat the same command. Per-batch vector shards and per-question retrieval outputs are resumed and identity-checked. An interrupted corpus export is rebuilt, not resumed mid-file. Changing code, seed, limits, source config or bank targets creates a different run identity; avoid changing them between commands. `--limit 3` is a tiny smoke run with separate identities and cannot be sealed as a full bank.

Useful individual stages use the same defaults and output identity:

```bash
bash scripts/run_eval_extension.sh --stage natural --resume
bash scripts/run_eval_extension.sh --stage natural-approved --resume
bash scripts/run_eval_extension.sh --stage natural-retrieval --resume
bash scripts/run_eval_extension.sh --stage explanations --resume
bash scripts/run_eval_extension.sh --stage explanations-approved --resume
bash scripts/run_eval_extension.sh --stage explanations-retrieval --resume
bash scripts/run_eval_extension.sh --stage retrieval --resume
bash scripts/run_eval_extension.sh --stage m3-dev --resume
bash scripts/run_eval_extension.sh --stage inference --enable-llm --model YOUR_INSTALLED_OLLAMA_MODEL --max-requests 5 --resume
bash scripts/run_eval_extension.sh --stage oracle --enable-llm --model YOUR_INSTALLED_OLLAMA_MODEL --max-requests 5 --resume
bash scripts/run_eval_extension.sh --stage score --resume
```

Run `natural-approved` only after a human records `APPROVE`, their name, and a timezone-aware `reviewed_at_utc` in the natural review sheet. For F5, review the complete packet source, fill the explanation only when supported, and record `APPROVE` or `INSUFFICIENT`, reviewer, timestamp and `source_checked=YES` before running `explanations-approved`. Both exporters include genuine approvals only. After the original and expanded factual benchmark freezes, seal each human-reviewed track with `--stage track-seal --track natural` or `--track f5` before requesting its retrieval with `--split test`. After retrieval, `--stage track-inference --track natural --enable-llm --model YOUR_INSTALLED_OLLAMA_MODEL --max-requests 5 --resume` and `--stage track-score --track natural` process the selected track; use `--track f5` for reviewed F5 and human-judge its outputs. The optional generator uses the existing local Ollama adapter only. It prints the planned number of predictions and caps attempts per invocation. Repeated calls with `--resume` continue, with model, corpus and retrieval identity checked. There is no Gemini adapter or external API call. The local model must already be installed and served; `YOUR_INSTALLED_OLLAMA_MODEL` is a placeholder, not a selected model. M3 uses its existing development wording parser and must not be called a final general SQL method.

Outputs are ignored under `outputs/eval_extension/bank-<identity>/` and `outputs/eval_extension/<corpus-identity>/`; logs are in `outputs/eval_extension/logs/`. Inspect `pipeline_summary.json`, `bank_manifest.json`, `natural_review.csv`, `corpus_manifest.json`, `audit_summary.json`, `dense_manifest.json`, `retrieval_dev_summary.json`/`.csv`, `retrieval_dev_hit5.svg`, and `tuning_dev.json`. `f5_review_packets.jsonl` contains local public comment text and should not be shared in Git. Send back sanitized aggregate summaries and blocked-stage messages, not comment text, raw predictions, or gold.

## Human and test gates

Review the existing original Phase 5 bundle, audit/transfer genuine decisions to its original queue, complete its global signoff, and run the existing Phase 5 freeze validator as documented in `docs/RUNBOOK.md`. Do not treat generated or Codex-suggested answers as human approval. Natural and F5 review files are separate; the code does not promote them automatically to verified gold.

After a valid original freeze **and** a successful `tuning_dev.json` exist, seal the new factual bank and fixed corpus/config, then request test retrieval:

```bash
bash scripts/run_eval_extension.sh --stage seal --resume
bash scripts/run_eval_extension.sh --stage retrieval --split test --resume
```

Seal checks hashes; test checks the seal and uses the dev-selected RRF constant. No `--limit` bank can be sealed. The test stage is inaccessible until both gates pass. Keep test results out of tuning. This is a controlled evidence-addition study, not a verified historical snapshot or concept-drift experiment.

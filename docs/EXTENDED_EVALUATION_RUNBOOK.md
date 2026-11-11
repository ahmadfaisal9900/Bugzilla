# Extended evaluation: repair and execution

## What the saved v1 run shows

The old run `outputs/eval_extension/bank-a34d7d0a4b66911d/` is preserved. Its manifest and selected-file checksums were verified. It selected 750 items: F1 675, F2 4, F3 14, F4 45, F6 12; 192 F1 questions ask the constant Firefox product. Its F2 development count is zero and F4 development count is two. The quota code favored F1 strata; its output is unsuitable for a balanced comparison. `outputs/eval_extension/diagnosis_v1.json` is an ignored machine-readable aggregate diagnosis.

All 349 M3 development outputs were `NO_INTENT`: the phase-6 development parser expected different wording. This is an integration failure, not an M3 accuracy conclusion. The old hierarchical top five matched hybrid on 341/349 queries because it filtered the existing hybrid list; the new version actually searches metadata first and then searches the chosen bugs' passages. The old corpus contained 12,828 chunks, 564 exceeding the embedding tokenizer limit. V2 uses tokenizer offsets and measures remaining truncation. These are implementation repairs awaiting full user-run validation.

The old F1 known-citation Hit@5 on 338 retrievable dev questions was BM25 0.932, dense 0.950, hybrid 0.956, hierarchical 0.956 and reranked 1.000. These are incomplete-label citation proxies, not end-to-end accuracy or a universal ranking. Explicit bug IDs and a known metadata citation can make lookup easy. F3/F6 passage recall is not applicable. No LLM inference ran. Snapshot as-of remains unknown.

V2 excludes constant product questions, uses a new deterministic bug partition, predeclared family/split and F1 field quotas, records shortfalls, excludes v1 selected test parents from new single-bug test candidates and keeps aggregate population overlap explicit. V1 and the original 169 Phase 5 candidates plus six supplemental challenges remain untouched. The original review sheet has 64 recorded decisions but the original `FROZEN` marker and validator-produced freeze are absent. Do not report signed-review or test results as frozen until the owner transfers and verifies genuine signoffs.

## User-terminal commands

From the existing project root, in the environment where the model and FAISS were installed:

```bash
cd "/home/ict317/master's/ENSF 621/Project"
conda activate iqfm
bash scripts/run_eval_extension.sh --dry-run --resume
bash scripts/run_eval_extension.sh --resume
```

The second command is a long development-only v2 job: draft bank, proposed natural review, tokenizer-aware corpus, lexical and dense indexes, retrieval, dev tuning and M3 dev. It makes no LLM calls. Its progress and `pipeline_summary.json` report stage outcomes. It uses a new identity; it does not overwrite v1. Input corpus/seed/changed code each affect identity. `--resume` verifies saved hashes and resumes embedding shards/retrieval rows; an interrupted corpus export restarts that stage. Model weights may download on first use. No runtime or disk guarantee is available; budget multiple GB and potentially hours on CPU.

To open the localhost wording review after bank generation:

```bash
bash scripts/run_phase07_natural_review.sh --resume
```

Open `http://127.0.0.1:8766/`. Approvals are human records, not automated labels. The server modifies only the ignored review CSV. The `AMBIGUOUS_NEEDS_CLARIFICATION` track contains no bug referent in model-facing text. To export actual approvals and run their development retrieval:

```bash
bash scripts/run_eval_extension.sh --stage natural-approved --resume
bash scripts/run_eval_extension.sh --stage natural-retrieval --resume
```

For a limited, explicit opt-in local Ollama smoke **after retrieval**, replace the model placeholder with an already installed model. The request budget counts attempts, including failures; no external provider is used:

```bash
bash scripts/run_eval_extension.sh --stage inference --enable-llm --model YOUR_INSTALLED_MODEL --max-requests 5 --resume
bash scripts/run_eval_extension.sh --stage score --resume
```

Each invocation permits at most five local model calls; repeat only if desired. Full development inference requires approximately one call per pending question per included generator method plus M0, up to six per question where all five retrievers returned results; failed calls also consume the cap. It is resumable. No amount of retrieval quality alone establishes answer quality.

## Gates and output

Inspect the printed bank and corpus directories under `outputs/eval_extension/`, particularly `bank_manifest.json`, `corpus_manifest.json`, `dense_manifest.json` (`truncated_chunks` must be checked), `retrieval_dev_summary.json`, `retrieval_dev_blind_review.csv`, `tuning_dev.json`, and `pipeline_summary.json`. Report only sanitized aggregate summaries. `--stage seal` requires the original validator-produced Phase 5 freeze, full unlimited v2 bank, dev tuning, and matching corpus/index/model/config hashes. Test runs remain blocked until that gate. Human-reviewed natural/F5 tracks have separate track seals. Existing F5 remains a separate human-reviewed track; F5 model response judgments and citation support require human review. No real historical as-of result is authorized.

The v2 clean split reduces reuse of v1 test parents but cannot turn the same underlying source corpus into independent external data. Natural meaning, ambiguous-question handling, quantitative response/citation quality, full QA comparison and all full-run numerical results remain unverified until real reviews and results are available. There is no M4 implementation in the inspected repository. Existing M0 is local Ollama closed-book; M3 is structured read-only SQL with either an explicit development parser or an existing local-model intent parser (`m3-llm`).

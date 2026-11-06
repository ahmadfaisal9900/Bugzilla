# Phase 6 model-free groundwork (2026-11-01)

**State: model-free groundwork and M0/M1 generation are implemented and fixture-tested. Not executed with a real model or real data. No study result exists.** The M3 intent parser is also fixture-tested. The benchmark freeze and real-model runs are pending.

## What exists

| File | Purpose | State |
|---|---|---|
| `methods/contract.py` | One answer shape, and a strict model-reply parser. A failed reply is never an abstention | Fixture-tested |
| `evaluation/scoring.py` | Deterministic scoring per gold type, Wilson intervals, paired question-level bootstrap | Fixture-tested; also run on every real gold shape in the queue |
| `methods/m3_sql.py` | Intent allowlist and read-only parameterized SQL for F1–F4 | Fixture-tested |
| `retrieval/bm25.py` | Standard-library BM25, the shared text corpus, Recall@k and Precision@k | Fixture-tested |
| `methods/local_model.py`, `methods/generation.py` | Local Ollama connection; M0 without records and M1 using bounded BM25 evidence | Fake-model and fixture-tested; no real model call |
| `methods/m3_intent.py` | Local model classifies the question into a validated JSON intent for the SQL store | Fake-model and fixture-tested |
| `evaluation/phase06.py`, `scripts/run_phase06_baselines.sh` | Development-only runner for M0/M1/M3/BM25 and the study M3 path with checkpoints and a summary JSON | Fixture-tested; real-input dry-run reports `BLOCKED` here |

## Scoring rules

- F1–F4 and F6 are computed. F5 is `NEEDS_HUMAN`, stays out of the accuracy denominator, and is counted separately.
- A `NO_INTENT` or `PARSE_ERROR` answer is incorrect everywhere, including on F6 and UNKNOWN gold.
- Abstaining on answerable gold is a false abstention. Answering unanswerable gold is incorrect.
- A duration is correct within 1 hour, the roadmap's tolerance for rounded answers. `exact` also records the gold's 1-second tolerance, so both can be reported. The shortest real gold duration is about 10 hours.
- An ID set is correct only when complete. Precision, recall and F1 are kept as partial credit.

## Corpus rules for M1 and M2

- Documents come from source records, never from gold or review sheets.
- Each sampled bug gets one text document of its structured fields and recorded links, and each pilot bug gets one of its verified history. Without these, M3 would win F1, F2 and F4 only because it alone could see the facts (D-045).
- Comments are chunked, sanitized, and exclude private or unavailable bodies. Actor fields stay out.
- The comment key is in the text because F5 questions cite it. So F5 recall is a pointer lookup and is no evidence about a retriever (D-043).

## What the tests show, and what they do not

Executed on 2026-11-01 in the agent session:

- 23 tests pass on the synthetic Phase 5 fixture. M3 reproduces the generator's independently built gold for every F1–F4 and F6 item, on 20 synthetic bugs.
- 22 of 22 deliberately injected defects are caught, run on a scratch copy. The first pass caught 16; the 6 that survived exposed weak tests, which were then tightened.
- On the tracked real queue: the parser handles 34 of 34 development questions with the expected template and bug, and parses 0 of 141 held-out questions. The scorer marks truthful answers right, damaged answers wrong, and failed answers wrong for all 175 rows, with F5 going to a human.
- The run identity still reproduces as `run-65c5be3381f66811`.

Not shown: nothing has run against the real database, so real M3 accuracy and BM25 recall are unknown. Comment text and F3 counts are still unchecked. Fixture recall of 1.0 comes from 47 tiny documents and predicts nothing about the real corpus.

## The parser limit

`parse_dev_wording` is built from development wording only, and test wording deliberately returns `NO_INTENT`. Using it on test questions would score about zero and measure nothing. Use `m3-llm` for the study's M3. The model receives only the question text and returns a typed intent. The SQL store validates the intent, binds its parameters, and computes the answer with read-only connections. Tune it on development questions only.

## Next, in order

1. Choose the shared model (see Blockers).
2. Run the smoke commands below on the data machine and review the output. They need no freeze because they only use development questions.
3. Smoke-test M0 and `m3-llm` with the same installed local model on development questions.
4. After the freeze, run every arm once on the locked test. This needs a deliberate new option; today's runner has no way to select test.

```bash
bash scripts/run_phase06_baselines.sh m3 --unfrozen-dev-smoke --dry-run
bash scripts/run_phase06_baselines.sh m3 --unfrozen-dev-smoke
bash scripts/run_phase06_baselines.sh bm25 --unfrozen-dev-smoke
```

Expected from the M3 smoke: every F1–F4 and F6 development row correct, and all six F5 rows false abstentions. Any other F1–F4 or F6 result is a defect to investigate, not a finding. Results marked `UNFROZEN_DEV_SMOKE` are never study results.

## Blockers

- **Model choice (team decision).** The roadmap names the Gemini free tier and local Ollama. Gemini's free tier may use submitted content to improve Google's products, and bug text can hold personal data with redistribution rights unresolved. **Recommendation: local Ollama, if the data machine can run a suitable model at an acceptable speed.** Use the same model for every arm.
- **Freeze.** All 64 required rows have recorded decisions in Ahmad's tracked sheet. Transfer the decisions into the generation queue, complete owner signoff, and validate the freeze on the data machine.
- **Data.** The database and overlay are only on the data machine.

## M0/M1 development step (2026-11-02)

The user authorized treating the remaining 31 answers as provisionally valid to continue development. This uses the existing `--unfrozen-dev-smoke` path; it creates no human decisions, owner signature or freeze. Scores under that flag are code checks against provisional answers, never study findings. The official queue remains unchanged.

- `local_model.py` uses Ollama's documented local `/api/chat` API with non-streaming JSON, temperature 0, a fixed seed, timeout, output cap and a request cap. It refuses external hosts, proxies and redirects, and never downloads a model. `--model` must name an already installed model explicitly. No model or weight version has been selected or validated yet.
- M0 receives only the question, factual scope and fixed response instructions. M1 receives the same fields plus source documents from the shared BM25 index. Neither accepts benchmark gold or reviewer fields.
- M1 defaults to top 5 documents and 12,000 characters of serialized evidence, including source IDs and URLs. This is a character limit, not a tokenizer-based budget. The same budget must be used for M2 later.
- Logs record prompt hashes, retrieved and supplied document IDs, model-reported token counts, requested/returned model names, response status and latency. Citation-provenance flags identify citations outside supplied documents; they do **not** establish whether a cited source supports a claim.
- Failed calls and malformed JSON are failures, not correct UNKNOWN responses. Failed attempts count toward the request cap. Checkpoints prevent repeating completed questions; changing the model, prompt/adapter code or generation settings changes the output identity.
- The runner is still development-only. M0 does not need a database, but needs the matching candidate or frozen development question files. M1 needs the canonical database and separate API history database. These files are absent here.

After installing and starting a suitable model on the data machine, substitute its exact installed name for `YOUR_INSTALLED_MODEL`. Run M0 before M1. These are user-terminal commands, not commands run by the agent:

```bash
bash scripts/run_phase06_baselines.sh m0 --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5 --dry-run
bash scripts/run_phase06_baselines.sh m0 --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5
bash scripts/run_phase06_baselines.sh m1 --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5 --dry-run
bash scripts/run_phase06_baselines.sh m1 --model YOUR_INSTALLED_MODEL --unfrozen-dev-smoke --limit 5 --max-requests 5
```

Inspect `outputs/phase06/logs/` and the run's `summary.json`, `predictions.jsonl` and `scores.jsonl`. M1 constructs its source index before answering; `--limit` limits questions, not index size. Resume the same settings with `--resume`; the default is at most five new model calls per invocation. No real inference, embedding generation or full evaluation was executed here.

API references: [Ollama chat](https://docs.ollama.com/api/chat), [JSON outputs](https://docs.ollama.com/capabilities/structured-outputs).

Verification on 2026-11-02: all 34 targeted tests pass (23 existing method/scoring tests plus 11 generation tests), and 15 Phase 4/5/scaffold regression tests pass. New tests exercise request caps, error handling, no-evidence M0, bounded-evidence M1, citation provenance, checkpoint resume, configuration isolation and provisional labels. The model calls in these tests are fake. Real-input M0/M1 dry-runs both report `BLOCKED` with zero model calls because their saved input files are absent.

## M0 and M3 handoff

On the data machine, use the original generation run, the pinned canonical database
and history overlay, and an already installed Ollama model. Set `MODEL` to the exact
installed model name and use it for both methods. Run the dry-runs first, then repeat
the commands with `--dry-run` removed.

```bash
bash scripts/run_phase06_baselines.sh m0 --model "$MODEL" --unfrozen-dev-smoke --limit 5 --max-requests 5 --dry-run
bash scripts/run_phase06_baselines.sh m3-llm --model "$MODEL" --unfrozen-dev-smoke --limit 5 --max-requests 5 --dry-run
```

Use `--resume` for the same configuration and raise `--limit` to progress beyond the
first five answers. Inspect each run's predictions, scores, and summary. The provisional
smoke reads candidate gold. After freeze, omit `--unfrozen-dev-smoke` to score against
reviewed development gold. The runner accepts development questions only.

Fixture checks cover intent validation, rejected raw SQL and malformed responses,
the question-only prompt, computed gold, and capped checkpoint resume. M0 and
`m3-llm` use no document index or embeddings. Existing M1/BM25 commands are inherited
from main. M2 was excluded from this handoff.


## Run locally with the shared sample

The exported sample and the tracked partner review sheet can drive a separate
development smoke run. This path verifies the sample and history file hashes,
checks the source pins and bug population, uses saved corrections for signed rows,
and uses candidate gold for optional unreviewed rows. It selects only development
benchmark questions. The results carry the `SHARED_DEV_SMOKE` label and belong in
development diagnostics. The benchmark freeze still uses the original pinned
generation and canonical files.

Run from the root of `feature/m0-m3` in Git Bash with the Python environment active.
Set `SAMPLE` to your extracted sample folder. These commands use the verified
local Windows location as an example.

```bash
SAMPLE='/c/Courses/ENSF 621/BUGZILLA/Bugzilla/data/firefox-sample-seed317-20261102'
REVIEW='outputs/benchmark/phase05/agent_review/signoff/run-65c5be3381f66811'
bash scripts/run_phase06_baselines.sh m3 --sample-bundle "$SAMPLE" --limit 5 --dry-run
bash scripts/run_phase06_baselines.sh m3 --sample-bundle "$SAMPLE" --limit 5
```

The SQL-only check uses the development wording parser. After a local Ollama
model is available, set `MODEL` to its installed name and run both study methods
on the same five development questions.

```bash
bash scripts/run_phase06_baselines.sh m0 --review-bundle "$REVIEW" --model "$MODEL" --limit 5 --max-requests 5
bash scripts/run_phase06_baselines.sh m3-llm --sample-bundle "$SAMPLE" --model "$MODEL" --limit 5 --max-requests 5
```

Use `--resume` to continue the same output. Inspect the logged path and the
run's predictions, scores, and summary. The local dry run verified the two
packaged database hashes, the population checksum, and 34 development questions.
The local Ollama endpoint did not respond during the availability check.

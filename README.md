# Bugzilla — ENSF 621 evaluation handoff

## 1. What this project is

**Memorize, retrieve, or query?** This course project asks which approach best answers questions about Firefox bugs: a closed-book language model, retrieval over archived evidence, or structured queries. Questions cover recorded fields, lifecycle events, counts, relationships, explanations, and information the evidence cannot establish. Correctness, evidence support, abstention, latency, and API usage are separate concerns. The primary scientific plan is [the roadmap](docs/reference/research_roadmap.tex).

First compare the individual methods on fixed development and locked test sets, then consider turning the best supported method into an application. The current deliverable is a research pipeline, not a production app. This README hands the prediction artifacts to the partner implementing **answer evaluation**; it does not announce a winning answering system.

## 2. Project status at a glance

Status checked against local code and saved reports on **2026-11-13**. Older phase documents contain historical “pending” statements; use the current manifests and this distinction between implementation, execution, and validation.

| Component | Status | Evidence / remaining work |
| --- | --- | --- |
| Canonical DuckDB + Parquet | Done | Verified normalization; 196,633 canonical bugs; 3,000-bug Firefox study cohort |
| Selective public history enrichment | Done | Verified 50-bug pilot; not complete history for the cohort |
| Phase 5 benchmark | Done | Frozen, human-signed; 169 questions plus 6 supplemental challenges |
| Natural rewrites | Done | 110 approved: 51 dev / 59 test |
| Expanded bank v2 | Partial | 693 selected; draft, not frozen |
| Dataset v3 | Done | Frozen after human spot-checking; 265 dev / 370 test |
| C0/C1/C2 indexes and development retrieval | Done | Saved complete runs and dev-only selection: R7b/C1 |
| S0–S8 answering implementation | Done | Offline fixtures; one exact-ID F1 question completed across all nine systems |
| Full development answering run | Partial | **NOT finished**; earlier batches stopped on free-tier API limits |
| New S0–S8 answer scoring | Not started | **Partner's next implementation task**; old scorer code is not this evaluation |
| F5 response judging / grounding audit | Not started | Gold source review is complete; generated-answer judging is different |
| Final answering statistics and locked test | Not started | Finalize methods and scoring on dev first |
| Temporal refresh comparison / production app | Not started | No answering comparison or genuine historical snapshot experiment verified |

**Provider correction:** the active backend is **Groq**, model `openai/gpt-oss-20b`, not Gemini. Gemini remains a legacy option. Current quota interruptions must not be described as Gemini failures. The one-question smoke validated wiring and one answer, not every family or branch.

## 3. Setup

Use Git, Bash, and **Python 3.10+**; Python 3.11 is recommended by the package requirement in `pyproject.toml`. The owner's existing Python 3.9 environment has run the fixture tests, but editable installation officially requires 3.10+. Do not create a nested Git repository.

```bash
# Clone once, create an environment, and install the answering stack; expect installed dependencies and an editable package.
git clone https://github.com/ahmadfaisal9900/Bugzilla.git
cd Bugzilla
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-answering.txt
python -m pip install -e .
```

`requirements-answering.txt` includes `requirements-v3.txt`, which includes the base data, LLM, and retrieval requirements. These provide DuckDB, pytz, Groq, jsonschema, PyYAML, sentence-transformers, FAISS, NumPy and tqdm, plus pinned LangGraph and LangSmith. `requirements.txt` alone installs only the data tools. Model weights must already be available locally for the answering runner, which enables Hugging Face offline mode. Obtain matching caches from the owner or provision the pinned models separately before running predictions.

Create an ignored `.env` using this **example only**; do not commit real credentials:

```dotenv
# Placeholder configuration; the current Groq backend needs GROQ_API_KEY.
GROQ_API_KEY=replace_with_your_groq_key
LLM_API_KEY=replace_only_if_using_legacy_gemini
LANGSMITH_KEY=replace_only_if_enabling_traces_or_uploads
```

The provider reads assignments without executing the file. `LLM_API_KEY` is the legacy Gemini key; it does not authenticate Groq. `LANGSMITH_KEY` is mapped to the LangSmith client in memory; `LANGSMITH_API_KEY` is also supported. Leave tracing off unless intentionally sending sanitized public evidence to LangSmith. Never print `.env` or include it in reports.

A clone does **not** contain the local evidence stack. Request the matching canonical DuckDB/Parquet, Phase 4 evidence, frozen benchmarks, approved rewrites, public corpora, indexes, model caches and retrieval caches from the owner. Keep the relative paths specified by `configs/answering.yaml`, `configs/retrieval_v3.yaml`, `configs/benchmark_v3.yaml` and `configs/eval_extension.json`. Do not regenerate sources to work around missing artifacts. See [sample-data handoff](docs/SAMPLE_DATA_HANDOFF.md); that bundle covers the sampled data/history, not every evaluation artifact.

Canonical databases and Parquet live under `outputs/normalization/phase03b/`; the separate history overlay is under `outputs/phase04/enrichment/`. Current indexes live under `outputs/indexes/retrieval_v3/`. These are ignored local artifacts, not files that `git pull` restores.

```bash
# Offline setup smoke using temporary fixtures; expect 25 passing tests, no API requests.
PYTHONPATH=src python -m unittest discover -s tests -p test_answering_graphs.py -q
```

## 4. Repository map

```text
README.md                         Partner setup and evaluation handoff
AGENTS.md                         Repository safety and bounded-job rules
pyproject.toml                    Package metadata; src-layout installation
requirements*.txt                 Data, retrieval, provider and answering dependency stacks
configs/                          Source paths, provider limits, dataset and method settings
  answering.yaml                  Answering arms, prompts, budgets and history/cache paths
  selected_retriever.yaml          Dev-selected retriever and its selection provenance
  retrieval_v3.yaml                Corpus/retriever settings and frozen dataset paths
  benchmark_v3.yaml                v3 generation and source settings
prompts/                          Shared answer prompts; optional compact profile
src/bugzilla_qa/
  data/                           Profiling, normalization and selective history enrichment
  benchmark/                      Generation, review, validation and freeze gates
  retrieval_v3/                   Corpus variants, registry, evaluation and selection
  llm/provider.py                 Shared Groq/legacy Gemini cache, budgets and ledger
  answering/                      LangGraph systems, read-only tools and prediction CLI
  eval_extension/                 Earlier expanded-bank/retrieval pipeline
  evaluation/                     Legacy evaluation code, not the new S0–S8 scorer
scripts/                          Terminal runners; complete catalog below
scripts/phases/                   Data preparation and history runners
scripts/smoke/                    Lightweight structure/import check
tests/                            Offline unit tests and tiny fixtures
docs/                             Roadmap, protocols, decisions and historical phase records
Dataset/                          Ignored original downloads; read-only
outputs/                          Mostly ignored datasets, indexes, runs and reports
logs/                             Ignored local logs
```

A small historical partner-review bundle is explicitly tracked under `outputs/`; most outputs remain ignored. Do not publish databases, source bodies, response caches, test gold, credentials or large logs.

## 5. Data and datasets

### Evidence corpus

The normalized base has 196,633 bugs, 419,458 comments and 308,132 explicit recorded links. The study uses **3,000 Firefox-product bugs**, seed 317; this does not represent all Firefox engineering. The separate 50-bug API pilot contains 884 changes and 13 initially eligible first-FIXED cases; benchmark eligibility narrows further after source-consistency/ambiguity checks.

Canonical tables include `bugs`, `comments`, `bug_links`, `documents`, `source_records`, `sample_membership` and `field_changes`. **Base `field_changes` is empty: do not use it for lifecycle answers.** Use the verified separate Phase 4 checkpoint/overlay. Archive snapshot time is UNKNOWN; ingestion time is not the source snapshot date. Public text only is eligible; private/unknown-visibility comment bodies are withheld.

The older corpus had 12,828 chunks: 3,000 metadata, 5,011 comment, 4,643 relationship and 174 history. The current retrieval build uses **C0: 14,443; C1: 14,195; C2: 14,666** chunks, with zero reported truncations in the saved build. Do not label those counts as the older corpus.

### Question families

Examples below are excerpts from **frozen Phase 5 development questions**, with long scope clauses omitted for readability. F5's source-record identifier is omitted here; the actual question retains it. Evaluate the full original scope, not these excerpts.

| Family | Meaning | Real dev question excerpt |
| --- | --- | --- |
| F1 | Recorded archive field | “what component is recorded for Firefox bug 1770351?” |
| F2 | Verified lifecycle or UNKNOWN | “how many calendar hours elapsed from filing to the FIRST evidenced FIXED transition for Firefox bug 1812245?” |
| F3 | Scoped distinct-bug count | “how many distinct Firefox bug IDs have component=Messaging System in the dev partition?” |
| F4 | Explicit recorded relation set | “which target bug IDs are explicitly recorded for duplicate_of from Firefox bug 1862065?” |
| F5 | Contributor-stated reason/constraint | “what reason or constraint is explicitly stated in cited comment … for Firefox bug 1708248?” |
| F6 | Evidence-scoped unanswerable | “what exact UTC export timestamp establishes the archived fields for Firefox bug 1707396?” |

KI is ID-free known-item identification or a field lookup based on symptoms. MH combines explicit relations and target metadata. F6H adds harder abstention cases: absent IDs, missing fields or unsupported lifecycle duration.

### Dataset locations and roles

| Dataset | Location / layout | Intended role |
| --- | --- | --- |
| Phase 5 original | Frozen directory configured by `phase05_dir` in `configs/retrieval_v3.yaml`; under `outputs/benchmark/phase05/`. Separate `dev.questions.jsonl`, `dev.gold.jsonl`, test equivalents and challenge equivalents; `quality_report.json`, `manifest.json` | Human-reviewed original benchmark; 169 questions, 6 supplemental paraphrases, not 175 independent benchmark questions |
| Natural rewrites | Configured `natural_questions`, under `outputs/eval_extension/bank-*/natural_approved.jsonl`; adjacent approval manifest | 110 approved wording variants, not an independent population. This legacy file contains gold inline; inference loaders strip it |
| Expanded bank v2 | Configured `expanded_selected` in `configs/benchmark_v3.yaml`; `selected.jsonl` plus `bank_manifest.json` | 693 draft selected items out of 2,489 candidates, not the 3,000/750 targets; legacy rows contain gold inline. Not frozen or an added Phase 9 dataset |
| v3 | Configured `v3_dir` in `configs/retrieval_v3.yaml`; under `outputs/benchmark/v3/`. Separate questions/gold by split; `qrels_v3_dev.jsonl`, `qrels_v3_test.jsonl`, manifest and review artifacts | Frozen, human-spotchecked harder retrieval benchmark, including capped older-bank items; not individually human-reviewed in full |

Counts are observed artifact counts, not generation targets. Phase 5's manifest pins its quality report (which gives family totals and split totals); dev metadata supplies the family breakdown, and test counts are the remainder. Natural/expanded manifests lack family-by-split counts; the table uses only row family/split metadata from their approved/selected exports, without inspecting test answers.

| Family | Phase 5 dev n | Phase 5 test n | Natural dev n | Natural test n | Expanded v2 dev n | Expanded v2 test n | v3 dev n | v3 test n |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| F1 | 6 | 24 | 22 | 42 | 112 | 263 | 64 | 86 |
| F2 | 4 | 15 | 4 | 8 | 2 | 4 | 0 | 0 |
| F3 | 6 | 24 | 2 | 2 | 31 | 71 | 89 | 0 |
| F4 | 6 | 24 | 23 | 7 | 40 | 95 | 29 | 54 |
| F5 | 6 | 24 | 0 | 0 | 0 | 0 | 0 | 0 |
| F6 | 6 | 24 | 0 | 0 | 22 | 53 | 22 | 34 |
| KI | 0 | 0 | 0 | 0 | 0 | 0 | 42 | 123 |
| MH | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 47 |
| F6H | 0 | 0 | 0 | 0 | 0 | 0 | 11 | 26 |
| **Total** | **34** | **135** | **51** | **59** | **207** | **486** | **265** | **370** |

**Accepted v3 gaps:** no F2, no F5 and no test F3. F2/F5 retrieval therefore uses the older development sets where present; natural has no F5. Phase 5's 180 target has an 11-question F2 shortfall and zero historical as-of questions. Its retained F5 includes 27 supported explanations and 3 human-confirmed insufficient-evidence cases, all from a FIXED-selected comment population.

Frozen files are never edited or regenerated. Dev and locked test gold stay separate from inference prompts, retrieval text and normal traces. Test access requires `--confirm-locked-test` in the new harnesses; do not execute test commands until configurations and scoring are finalized. Natural variants retain parent grouping; six challenges are supplemental, not six extra independent observations.

```bash
# Resolve the frozen directories from tracked configuration; expect local paths, not a regenerated dataset.
python - <<'PY'
import json
c = json.load(open('configs/retrieval_v3.yaml'))
for key in ('phase05_dir', 'v3_dir', 'natural_questions'):
    print(key, c[key])
PY
```

## 6. Retrieval

### Corpus variants and registry

| Corpus | Construction |
| --- | --- |
| C0 | Current source corpus copied as-is; reusable indexes are verified |
| C1 | Complete eligible comments/history re-chunked to at most 200 embedder tokens, overlap 40; metadata/links retained |
| C2 | C1 plus deterministic `Bug {bug_id} | {component} | {summary} | {chunk_type}: ` prefix, further split to fit the embedding limit |

C1/C2 require zero truncations. Embedder: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, 256-token maximum. Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`. Full pinned revisions live in `configs/retrieval_v3.yaml` and manifests.

All adapters are registered in `src/bugzilla_qa/retrieval_v3/registry.py` and expose `retrieve(query, k)` returning `chunk_id`, `record_id`, `bug_id`, `chunk_type`, `score`, `rank`, `text`.

| Registry name | Method |
| --- | --- |
| R1 | BM25 using SQLite FTS5; deterministic zero-score fills are marked |
| R2 | Dense FAISS search |
| R3 | BM25/dense reciprocal-rank fusion, k=60 |
| R4 | Hierarchical: exact bug ID restricts directly; otherwise discover the parent then rank its chunks; logs top-10 Jaccard against R3 |
| R5 | R3 top-50 candidates reranked by cross-encoder |
| R6 | R5 plus explicit one-hop neighbour metadata from the top-three bugs, at most three result slots |
| R7a | Cached LLM-generated hypothetical report (HyDE), then R5 |
| R7b | Cached three-query transformation, RRF-fused R5 results |

### Terminal workflow

Existing builds and development retrieval are complete. These are reproduction commands, **not required setup steps for a partner receiving matching artifacts**. Indexing is substantial; R7 consumes API quota. Run only in your own terminal. Selection refuses to overwrite its existing config; do not rerun the final selection merely to inspect it.

```bash
# Inspect build/evaluation plans without loading models or making calls; expect DRY_RUN.
bash scripts/run_phase09_retrieval_v3.sh build --dry-run
bash scripts/run_phase09_retrieval_v3.sh eval --dry-run
bash scripts/run_phase09_retrieval_v3.sh eval --retrievers R7a R7b --dry-run
```

```bash
# Optional deliberate reproduction: build new indexes and evaluate offline R1–R6; expect COMPLETE or a resumable error.
bash scripts/run_phase09_retrieval_v3.sh build --resume
bash scripts/run_phase09_retrieval_v3.sh eval --resume
```

```bash
# Uses API quota: up to 750 HTTP attempts, including retries; cached transforms are reused.
bash scripts/run_phase09_retrieval_v3.sh eval --retrievers R7a R7b --enable-llm --max-requests 750 --resume
```

```bash
# Inspect the preregistered selection without writing; expect the dev-only selected pair.
bash scripts/run_phase09_retrieval_v3.sh select --latest --dry-run
```

```bash
# Optional deliberate new selection file; expect SELECTED_DEV_ONLY, refusing an existing destination.
bash scripts/run_phase09_retrieval_v3.sh select --latest --output configs/selected_retriever_reproduction.yaml
```

Saved outputs live in `outputs/retrieval/v3/run-*/`: `per_question.jsonl`, `summary.json`, `summary.md`, `retrieval_cache.sqlite` (top-50 public results), identity/config and manifest. Index builds are under `outputs/indexes/retrieval_v3/build-*/C0|C1|C2/`. Rough CPU planning only: builds 10–40 minutes; offline evaluation 30 minutes–3 hours; uncached R7 can take hours and span quota days. Do not treat these as measured runtimes.

### Metrics and selection

| Implemented retrieval metric | Definition |
| --- | --- |
| Hit@1/5/10 | Any known cited evidence record appears within the first k results |
| Known-citation Recall@5/10 | Fraction of distinct supplied evidence record IDs retrieved; missing/unindexed supplied IDs remain in the denominator |
| MRR@10 | Reciprocal rank of the first known relevant result within ten |
| nDCG@10 | Binary discounted gain normalized to supplied relevance; repeated records do not gain repeated credit |
| Bug-level Hit@5 | Any top-five chunk belongs to an acceptable bug ID, where those labels exist |
| MH full-evidence coverage@10 | All required evidence record IDs are present within ten |
| Latency p50/p95 | Median and 95th-percentile query computation time, with cache provenance |

Qrels are **incomplete known-citation labels**, not exhaustive relevance judgments. nDCG treats unlabeled material as non-relevant; a semantically useful uncited result can therefore score poorly. Metrics are not answer accuracy. F3/F6/F6H passage metrics are **N/A**, never zero; **not in dataset** means the family is absent; missing applicable evidence labels are UNKNOWN. Every reported metric carries its applicable **n**.

Statistics use paired cluster bootstrap by parent/`cluster_id`, 10,000 resamples, seed 317, comparing against same-corpus R1 for Hit@5 and Recall@10; percentile intervals and Holm-adjusted bootstrap tests are reported. See [selection protocol](docs/RETRIEVER_SELECTION.md): maximize macro known-citation Recall@10 across v3/natural dev cells with at least 10 qrel-bearing questions, break ties within one percentage point by p95 latency, and admit R7 only above its same-corpus R5 base by more than two points. Current `configs/selected_retriever.yaml` selects **R7b/C1**. Smaller F2/F5/MH cells remain descriptive, not selection evidence.

## 7. Answering systems

Entry point: `src/bugzilla_qa/answering/cli.py`, wrapped by `scripts/run_phase10_answering.sh`. These systems produce **predictions only**.

Call counts below describe uncached successful logical requests before transport retries. A repair adds at most one request; cache hits can reduce actual calls to zero, and retrieval transforms also consume the shared cap.

| System | Behavior | LLM requests per question |
| --- | --- | --- |
| S0 | Closed-book, question only | 1 answer |
| S1 | R1 on selected C1 | 1 answer |
| S2 | Selected R7b/C1 | 1 answer + up to 1 missing transform |
| S3 | Configured query-transform RAG, currently also R7b/C1 | Same as S2; **not a distinct retrieval treatment currently** |
| S4 | R5 score gate, one deterministic local multi-query retry; abstain if still below tau | 0 on low-evidence abstention, otherwise 1 answer |
| S5 | All public chunks for explicit bug IDs, or S2 top-one parent; dossier budget 12,000 | 1 answer; ID-free fallback may add 1 transform |
| S6 | R6 graph-expansion RAG | 1 answer |
| S7 | Native provider function calling, at most four executed tool steps | Up to 5 generation turns; repair/search transforms can add requests |
| S8 | Rule router to S7 for counts/relations/field lookups, S5 for reasons with ID, S2 without ID | Chosen arm's calls; ambiguous-ID classification adds 1 |
| ORACLE | Gold-evidence diagnostic, never a deployable competitor | 1 answer; separate diagnostic ledger, explicit system selection |

S7 uses read-only parameterized DuckDB and allowlisted `get_bug_fields`, `get_links`, `count_bugs`, `get_lifecycle`, `search_text`; arbitrary model SQL is forbidden. Missing lifecycle evidence returns unknown, not zero events. S4 tau comes from a dev-score distribution suggestion, not a calibrated correctness probability. The old M3 intent parser is deprecated for this comparison; S7 is a new arm, not a repair claimed as old M3 success.

Shared structured answer contract (`answering/contracts.py`):

```json
{
  "abstain": false,
  "answer": "FIXED",
  "answer_type": "string",
  "bug_ids": [1767855],
  "citations": ["source-chunk-id"],
  "rationale": "The archived metadata records resolution FIXED."
}
```

`answer` can be a string, number, scalar list or null; abstention must agree with null. Citations must be supplied context/tool IDs. Exact `Cn`/`[Cn]` labels are mapped locally, with mappings logged. The rationale is limited to two sentences and 1,000 characters. This contract validates format and citation membership, **not factual support**.

All arms share `prompts/answer_v1.txt`, temperature zero and one generator model. Unsupported evidence requires abstention. The optional `--compact-prompts` profile uses `prompts/answer_v2_compact.txt` and creates a different run/cache identity; its live quality is not established. Do not mix prompt versions in a comparison. Normal context budget is 3,000; counting conservatively uses UTF-8 bytes, not an exact hosted-model tokenizer.

The shared provider is `src/bugzilla_qa/llm/provider.py`, configured by `configs/llm.yaml`. It supports Groq and legacy Gemini, structured JSON and native tools, a SQLite response cache, append-only request ledger, RPM pacing, retry/backoff, a 90%-of-RPD local guard and persisted server cooldowns. Config currently uses 3 RPM / 1,000 RPD; actual token quotas can stop earlier. Cache identity includes model, prompt version, prompts and schema. Requests require `--enable-llm` and a request cap; otherwise use dry-run/plan. API keys never enter manifests or traces.

LangGraph nodes: `load_question → router → retrieve → pack_context → generate → validate → persist`, with a bounded tool loop and one JSON repair. State includes question/scope, qid/family/dataset/split/system, route/rule, retrieved public evidence/context, raw output/answer/errors, tool/repair counts, usage/cache flags, configuration identity and timing.

## 8. Entry points

All examples below are **help/inspection commands**, not instructions to rerun finished phases. Each prints usage, except the structure smoke and PowerShell parameter inspection. Key flags are shown for finding the appropriate workflow; phase docs describe prerequisites. This catalog covers every file currently under `scripts/`.

| Script | Purpose | Key flags | Safe example command |
| --- | --- | --- | --- |
| `run_phase02_audit.sh` | Streaming CSV audit | `--dry-run`, `--limit`, `--resume` | `bash scripts/run_phase02_audit.sh --help` |
| `phases/run_phase03a_explore.sh` | Data profile/plots | `--dry-run`, `--limit`, `--resume` | `bash scripts/phases/run_phase03a_explore.sh --help` |
| `phases/run_phase03b_normalize.sh` | Canonical normalization | `--dry-run`, `--limit`, `--resume` | `bash scripts/phases/run_phase03b_normalize.sh --help` |
| `phases/run_phase04_api_smoke.sh` | Bounded public history smoke | `--dry-run`, `--limit`, `--max-requests` | `bash scripts/phases/run_phase04_api_smoke.sh --help` |
| `phases/run_phase04_enrich.sh` | Selective API overlay | `--dry-run`, `--resume`, `--max-requests` | `bash scripts/phases/run_phase04_enrich.sh --help` |
| `phases/run_phase04_temporal_qc.sh` | Offline temporal eligibility | `--run-dir`, `--cutoff` | `bash scripts/phases/run_phase04_temporal_qc.sh --help` |
| `run_phase05_generate_benchmark.sh` | Original generation | `--dry-run`, `--seed`, `--resume` | `bash scripts/run_phase05_generate_benchmark.sh --help` |
| `run_phase05_prepare_review.sh` | Original review export | `--run`, `--dry-run`, `--seed` | `bash scripts/run_phase05_prepare_review.sh --help` |
| `run_phase05_agent_review_prep.sh` | Deterministic checks/public packets | `--dry-run`, `--limit`, `--batch`, `--resume` | `bash scripts/run_phase05_agent_review_prep.sh --help` |
| `run_phase05_validate_freeze.sh` | Human-gated original freeze | `--run`, `--dry-run`, `--resume` | `bash scripts/run_phase05_validate_freeze.sh --help` |
| `run_phase05_dev_supplement.sh` | Legacy dev supplement | `--run`, `--dry-run` | `bash scripts/run_phase05_dev_supplement.sh --help` |
| `run_phase05_share_sample.sh` | Private sample/history export | `--dry-run`, `--limit`, `--resume` | `bash scripts/run_phase05_share_sample.sh --help` |
| `export_sample_bundle.py` | Underlying sample exporter | `--output`, `--memory-limit`, `--dry-run` | `python scripts/export_sample_bundle.py --help` |
| `run_phase06_baselines.sh` | Legacy M0/M1/M3 tooling | method subcommand, `--dry-run` | `bash scripts/run_phase06_baselines.sh --help` |
| `run_phase06_verify.ps1` | Legacy Windows verification | `-DryRun`, `-Limit`, `-PythonExecutable` | `Get-Content scripts/run_phase06_verify.ps1 -TotalCount 14` (PowerShell: inspect parameters without running) |
| `run_eval_extension.sh` | Legacy bank/index/retrieval pipeline | `--stage`, `--dry-run`, `--resume` | `bash scripts/run_eval_extension.sh --help` |
| `run_phase07_m3_repair.sh` | Legacy parser repair | `--dry-run`, `--limit`, `--resume` | `bash scripts/run_phase07_m3_repair.sh --help` |
| `run_phase07_natural_review.sh` | Prepare natural review UI | `--dry-run`, `--resume` | `bash scripts/run_phase07_natural_review.sh --help` |
| `review_natural_v2.py` | Browser CSV reviewer | positional CSV, `--port` (8766) | `python scripts/review_natural_v2.py --help` |
| `run_phase08_v3_generate.sh` | v3 preparation/generation | `--dry-run`, `--prepare`, `--enable-llm`, `--max-requests`, `--resume` | `bash scripts/run_phase08_v3_generate.sh --help` |
| `run_phase08_v3_validate.sh` | Independent v3 gold validation | `--latest`/`--run`, `--dry-run`, `--limit` | `bash scripts/run_phase08_v3_validate.sh --help` |
| `run_phase08_v3_freeze.sh` | Spot-check-gated v3 freeze | `--latest`/`--run`, `--dry-run`, `--resume` | `bash scripts/run_phase08_v3_freeze.sh --help` |
| `run_phase09_retrieval_v3.sh` | Index build, retrieval eval, selector | `build`/`eval`/`select`, `--dry-run`, `--retrievers` | `bash scripts/run_phase09_retrieval_v3.sh --help` |
| `run_phase10_answering.sh` | Prediction plans/runs, quota, tau, uploads | `plan`/`run`/`quota`/`suggest-tau`/`upload-dev` | `bash scripts/run_phase10_answering.sh --help` |
| `llm_ping.py` | One-request provider check | `--dry-run`, `--role`, `--model`, `--list-models`, `--max-requests 1` | `python scripts/llm_ping.py --help` |
| `smoke/check_structure.sh` | Structure/import smoke | No flags; expects local folders | `bash scripts/smoke/check_structure.sh` |

Tests use `python -m unittest discover`; bounded commands appear below. Package CLIs are available through `python -m bugzilla_qa.answering.cli` and `python -m bugzilla_qa.retrieval_v3.cli` with the same arguments as their wrappers. No answering scorer entry point exists yet.

## 9. Observability

Tracing is off by default and bulk retrieval explicitly disables it. Answering enables it with `--trace`; `--trace-sample 0..1` controls deterministic sampling. Projects are `ensf621-dev` and `ensf621-test`. One root run per system/question is named `system:qid`; metadata includes system, qid, family, split, dataset, freeze identity, model, prompt version, configuration identity, route and cache flag. Retrieval, packing, router and tools are traced.

Opted-in traces include sanitized **public** retrieved text, scores, tool results and outputs. Private/unknown-visibility bodies, known secrets and gold are excluded from normal traces. ORACLE is explicitly diagnostic. The optional LangSmith dev-reference upload deliberately supplies gold as reference outputs, outside inference; no evaluators run automatically.

Authoritative local records are prediction JSONL and manifests, `outputs/predictions/logs/`, the provider ledger configured in `configs/llm.yaml` (currently `outputs/llm/groq/ledger.jsonl`) and retrieval reports/caches. A UI trace is not the sole record of execution or an accuracy result. Successful cache reuse is distinct from a new paid/quota-consuming call; inspect `retrieval_cache_hit`, `llm_cache_hit`, `call_count` and token fields separately.

```bash
# Plan the optional dev-reference upload; expect DRY_RUN and zero remote writes.
bash scripts/run_phase10_answering.sh upload-dev --dry-run
```

```bash
# Optional LangSmith upload, not an LLM evaluation; at most 100 API operations, resumable.
bash scripts/run_phase10_answering.sh upload-dev --enable-upload --max-requests 100 --resume
```

## 10. Smoke tests, in order

These commands are dev-only. Start offline; matching local inputs are needed for plans, but not the tiny fixture test. Do not rerun an expensive pilot just to check startup.

```bash
# 1. Offline fixture tests; expect 25 passing tests, no API calls.
PYTHONPATH=src python -m unittest discover -s tests -p test_answering_graphs.py -q
```

```bash
# 2. Offline provider and retrieval fixtures; expect passing tests without downloads or live calls.
PYTHONPATH=src python -m unittest discover -s tests -p test_groq_provider.py -q
PYTHONPATH=src python -m unittest discover -s tests -p test_retrieval_v3.py -q
```

```bash
# 3. Zero-cost CLI/provider checks and batch planning; expect help, DRY_RUN and offline quota diagnostics.
python scripts/llm_ping.py --dry-run
bash scripts/run_phase10_answering.sh quota
bash scripts/run_phase10_answering.sh plan --dataset v3 --limit 25 --resume
```

```bash
# 4. Optional live check — USES API QUOTA: exactly one attempted ping, or a reported provider/budget failure.
python scripts/llm_ping.py --role generator --enable-llm --max-requests 1
```

```bash
# 5. Resolve one already-smoked dev QID from its public question metadata; expect one QID in the shell variable.
smoke_qid="$(python - <<'PY'
import json
from pathlib import Path
c = json.load(open('configs/retrieval_v3.yaml'))
for line in (Path(c['v3_dir']) / 'dev.questions.jsonl').read_text().splitlines():
    row = json.loads(line)
    if 'bug 1767855 ' in row['question'] and 'recorded resolution' in row['question']:
        print(row['qid'])
        break
else:
    raise SystemExit('Previously verified smoke question is missing; inspect inputs')
PY
)"
```

```bash
# 6. Inspect the fixed one-question plan; expect zero actual calls and the selected QID only.
bash scripts/run_phase10_answering.sh plan --dataset v3 --qid "$smoke_qid" --run-tag smoke-one --resume
```

```bash
# 7. Optional live wiring smoke — USES API QUOTA: at most 12 HTTP attempts total across S0–S8; cache hits can make it zero.
bash scripts/run_phase10_answering.sh run --dataset v3 --qid "$smoke_qid" \
  --run-tag smoke-one --enable-llm --max-requests 12 --trace --resume
```

The saved owner smoke completed all nine systems with four new requests: S0 abstained, S1–S8 answered FIXED, matching the canonical archive; S7 used the field tool and S8 routed to S7. Schema/citation checks and saved output checksums passed. This establishes one F1 lookup path only. `COMPLETE_SELECTED_BATCH` does not mean full dataset completion. Repeating a fixed `--qid` never advances to new questions. No live commands above were run while preparing this README.

## 11. Resuming unfinished development answering

The full development run is **not complete**. The command below is the intended advancing batch, not a statement that it has finished. Run one model job at a time to respect shared free-tier limits.

```bash
# Estimate pending work and quota days with zero API calls; expect DRY_RUN with per-system call/token estimates.
bash scripts/run_phase10_answering.sh plan --dataset v3 --limit 25 --resume
```

```bash
# USES API QUOTA: process up to 25 pending questions per system, with at most 200 HTTP attempts for the entire invocation.
bash scripts/run_phase10_answering.sh run --dataset v3 --limit 25 \
  --enable-llm --max-requests 200 --resume
```

`--limit 25` limits each requested system's pending selection, not total requests or a fixed pilot. `--max-requests 200` caps actual provider HTTP attempts including retries, transformations, repairs and tool turns; it does **not** guarantee enough token quota. `--resume` skips successful `(system, qid, configuration)` entries, retaining failed attempts. Repeating the advancing command selects further pending questions. Use the same declared model/prompt/settings throughout a comparison; code/config/input changes create another versioned run, even when provider response caches can be reused.

Repeat for `--dataset phase05` and `--dataset natural` once budget permits. The old large pilot need not be completed for basic wiring; do not restart it merely to consume more quota. Lowering a request cap is safe. Full success requires `COMPLETE` and zero remaining work for **all systems on the full dataset**, not only a selected QID or limited family.

```bash
# Inspect saved batch status without displaying answers or gold; expect state and remaining counts per local run.
python - <<'PY'
import json
from pathlib import Path
for p in sorted(Path('outputs/predictions').glob('*/dev/run-*/summary.json')):
    r = json.loads(p.read_text())
    print(p.parent, r.get('state'), r.get('remaining_by_system'))
PY
```

```bash
# Check local usage/cooldowns with zero calls, then estimate the full pending dev workload and days.
bash scripts/run_phase10_answering.sh quota
bash scripts/run_phase10_answering.sh plan --dataset v3 --resume
```

The local guard's date resets at **midnight America/Los_Angeles**. This was the Gemini daily convention and is the implemented local accounting window; **do not assume Groq's server token quota resets then**. Groq response headers/cooldowns and the active-model dashboard are authoritative. Planner days are request-budget estimates, not promises under token limits; there is no configured token/day guard. Wait for an indicated cooldown instead of repeatedly spending requests on 429s.

## 12. HANDOFF FOR EVALUATION

### A. Prediction artifacts and exact row fields

Read `outputs/predictions/<dataset>/<split>/run-*/S0.jsonl` through `S8.jsonl`, plus optional `ORACLE.jsonl`. Each version has `identity.json`, `config_snapshot.json`, `summary.json`, `manifest.json` and, for confirmed test access, a receipt. Do not combine incompatible versions or count repeated failed attempts as independent answers. Select the matching successful row per system/qid/configuration; preserve failures in reliability reporting rather than silently removing them.

Every persisted field from `answering/runner.py`:

| Fields | Meaning |
| --- | --- |
| `qid`, `system_id`, `dataset`, `split`, `family` | Question and method identity; family is supplied by the loader |
| `freeze_id`, `config_hash`, `model`, `provider`, `prompt_version` | Dataset, code/config/input and generation provenance |
| `status`, `at_utc` | Contract/execution outcome and UTC write time; `ok` is not an accuracy label |
| `route`, `route_rule` | Effective method and selected routing rule |
| `answer` | Validated structured object: `abstain`, `answer`, `answer_type`, `bug_ids`, `citations`, `rationale` |
| `raw_output` | Sanitized original model JSON/function result before citation normalization; not guaranteed to be a final-answer object on failure |
| `retrieved_chunk_ids`, `context_chunk_ids` | Retrieved versus actually packed/tool-visible evidence |
| `context_map`, `context_token_counter` | C-label mapping and recorded byte-based budget policy |
| `citation_normalization` | Each resolved label and canonical chunk ID |
| `errors` | Contract, tool or provider failures; may retain a repaired intermediate error |
| `call_count` | Actual new provider HTTP attempts attributed to this question, including transforms/retries |
| `cache_hit` | Legacy combined reuse flag; do not equate it to model response reuse |
| `retrieval_cache_hit`, `llm_cache_hit` | Separate retrieval/model-cache indicators; the latter may include cached transforms |
| `tokens` | `input`, `output` for uncached events; `cached_input`, `cached_output` separately; `usage_missing` marks uncertainty |
| `latency_ms` | Measured graph time for this invocation, including waits/cache behavior, not an uncached counterfactual |
| `tools` | Executed/rejected tool records: `name`, `arguments`, `result`; also local corrective-retrieval audit entries |
| `diagnostic_only` | True for ORACLE |
| `oracle_coverage` | Null normally; ORACLE records requested/available record IDs and packed chunk IDs |

A provider-failure fallback can have `abstain=true` but `status=error`: **not a successful evidence-based abstention**. Missing usage is not zero cost. Cache-hit latency is not directly comparable to fresh API latency without stratification. Join gold locally by qid only in a separate scorer; never add it to generation logs or normal trace inputs.

### B. What is not built for this comparison

No new S0–S8 answer scorer, F5 LLM judge, semantic grounding checker, abstention evaluation, final paired answer statistics or locked-test answering comparison has been implemented. Legacy `evaluation/` and `eval_extension/` contain scoring utilities and old reports; they do not constitute this study's new answer evaluation. A separate blinded LLM judge is optional, requires explicit quota safeguards and human auditing, and must never be the sole evidence for F5 correctness.

### C. Planned scoring — not implemented

| Family / measure | Planned evaluation |
| --- | --- |
| F1 | Exact normalized field value within the stated archive scope |
| F2 | Reopen/count accuracy; first-FIXED duration absolute error/MAE in declared hours/days; UNKNOWN assessed separately, never converted to zero |
| F3 | Exact distinct-bug count and absolute count error over the declared partition/denominator |
| F4 | Complete target-set precision, recall and F1; explicit direction/type and snapshot qualifiers retained |
| F5 | Human source-supported reason rubric: every material causal/constraint claim must be supported and address the question; distinguish insufficient-evidence gold |
| F6 / F6H | Correct abstention on evidence-unanswerable items; separately false abstention on answerable items |
| KI | Bug-ID match against acceptable alternates; field-form questions also require the typed field answer |
| MH | Complete compound/set/count answer from all required relation/target evidence, with partial evidence coverage reported separately |
| Reliability | Citation support/precision, contradicted or unverifiable atomic claims, fraction of answers with unsupported claims, parse/provider/tool failure rates |
| Cost/performance | New versus cached tokens and requests, missing usage, latency p50/p95; separate local retrieval/build and API waits |

Use the roadmap's predefined numerical tolerances where appropriate; do not choose them after observing locked-test performance. Distinguish unsupported answers from wrong citations, unavailable evidence and genuinely unanswerable questions. Existing schema validation only checks citation membership, not that a cited sentence supports a claim.

### D. Required evaluation rules

- Report **per family**, dataset and system; never use a pooled F1-dominated score as the main result. Show **n in every cell**, with exclusions/failures explicit.
- Keep “not in dataset”, passage-metric “N/A”, unknown evidence and actual zero scores distinct.
- Use identical eligible questions for paired method comparisons. Bootstrap parent/`cluster_id` groups together; natural rewrites and close variants are not independent. Plan answer-statistics multiplicity controls before results.
- Tune prompts, routes, tau, tools, selection and scorer rules **on dev only**. Keep test gold out of inference. Run test once per finalized configuration and record access.
- Retain all source-scope qualifiers, acceptable KI alternates and evidence availability. Use separate Phase 4 histories; never query the empty base event table for lifecycle gold.
- Keep ORACLE diagnostic, and disclose S2/S3's identical current retrieval treatment. Gold review does not imply generated answers have been reviewed.

### E. Next steps, in order

1. Receive the exact ignored data/freeze/index/cache/prediction bundle; check its manifests and environment offline.
2. Inventory compatible dev prediction versions and failures; finish resumable dev batches within quota. Do not merge versions merely to fill cells.
3. Implement deterministic family scorers and tiny fixture tests; fix scope, normalization, units and failure accounting before test access.
4. Prepare blinded F5/grounding review and a human-audited subset; predeclare any optional judge protocol and budget.
5. Produce dev per-family tables, denominators, latency/cost and error analysis; finalize the genuinely distinct comparison arms.
6. Freeze method/scorer configuration; obtain explicit locked-test authorization, then run the finalized test predictions once and score separately.
7. Report paired cluster-aware uncertainty, source limitations and temporal gaps; only then choose an application candidate.

## 13. Known limitations and caveats

- Older questions often contain a bug ID and can saturate retrieval metrics; high citation retrieval is not proof of answer quality.
- Qrels are incomplete. Passage retrieval is inappropriate for some aggregates/abstentions; labels and applicability must remain visible.
- The cohort is Firefox-product only. The broad metadata population is **not** the paper's 119,585 curated reports or 10,351 quality-selected reports. Expanded v2 remains F1-heavy; v3 reduces but does not remove all biases.
- Selected CSV comments are FIXED-biased. F5 cannot support conclusions about explanations for unresolved bugs. “Resolved” is not synonymous with “FIXED”.
- Base snapshot date and historical availability are unknown. Ordered API history can support retrospective event answers, but current API metadata cannot be projected backward. No measured RQ3 stale-versus-refreshed answering comparison or genuine separately observed historical snapshots exist.
- The old M3's initial 349/349 `NO_INTENT` outputs reflect a parser failure, not evidence that SQL is an ineffective method. Later legacy runs have their own outstanding repair history; use the new S7 arm transparently.
- Current S2 and S3 share R7b/C1; count them as duplicate treatments unless a dev-only, separately versioned change is declared.
- Free-tier request and token limits make completion intermittent. Cache reuse conserves quota but changes observed latency. Hosted model behavior can change even under the same model name.
- The shared evidence-abstention prompt led S0 to abstain on all 21 questions in an earlier partial dev pilot. Its schema-valid completion is not evidence of useful closed-book accuracy; evaluate this behavior explicitly rather than treating it as an infrastructure failure or silently changing only S0's prompt.
- Dossier and normal evidence budgets differ by design. Byte-based budget counting is conservative; compact prompts have not received the same live validation as the default profile.
- Source redistribution/license approval remains unresolved. Even public text can contain personal data; privately transfer necessary evidence, preserve privacy gates and do not publish raw bodies.

## 14. Troubleshooting

| Symptom | Check / remedy |
| --- | --- |
| Missing provider key | Current backend requires `GROQ_API_KEY` in ignored `.env`; legacy `LLM_API_KEY` alone is insufficient. Never paste a key into a command or issue |
| 404 / unavailable Gemini model | Legacy Gemini configuration is not the current setup. Inspect provider/model config; do not randomly switch the study's generator mid-run |
| 429, long Retry-After, PARTIAL | Inspect offline `quota`, preserved cooldown and active-model dashboard. Wait, then resume; request caps do not reserve tokens |
| Test split blocked | Intentional safety gate. Do not bypass during development; finalize methods/scoring before explicitly authorized test access |
| Missing corpus/index/cache | Receive the matching local artifact bundle and check configured paths. No large assets come with a normal clone; don't rebuild finished data casually |
| DuckDB path/identity error | Check `canonical_db` and manifests in tracked configs, restore matching relative layout; never replace with a different database under the same identity |
| Missing model weights/offline load failure | Answering sets offline model flags. Provision pinned weights separately; no silent live downloads during answer runs |
| S4 requires tau | Use the dev-only `suggest-tau --dry-run` inspection; write a deliberate suggestion with `--write` only when establishing a new declared configuration |
| Invalid JSON/citation | One repair is allowed; inspect `errors`, `raw_output`, `context_map`, normalized citations and status. Do not alter gold to fit outputs |
| Resume starts a different directory | Input/config/code/prompt identity changed. Preserve both versions; inspect their snapshots rather than renaming or concatenating ledgers |
| Selection destination exists | Expected overwrite protection; inspect existing selection, or use a deliberate new `--output` path for a new experiment |
| Import error / Python version mismatch | Activate the correct environment and install `requirements-answering.txt`; use package installation or `PYTHONPATH=src` for fixture commands |
| LangSmith absent despite successful run | Tracing needs credentials plus `--trace`; remote delivery is separate from local prediction success. Local ledgers remain authoritative |

## 15. Deeper documentation

- [Scientific roadmap](docs/reference/research_roadmap.tex): primary research questions, rubric and fairness controls.
- [Research status](docs/RESEARCH_STATUS.md), [phase log](docs/PHASE_LOG.md), [decisions](docs/DECISIONS.md), [experiment registry](docs/EXPERIMENT_REGISTRY.md), [runbook](docs/RUNBOOK.md): historical state and operating record; reconcile older pending notes with current manifests.
- [Data dictionary](docs/DATA_DICTIONARY.md), [data exploration](docs/DATA_EXPLORATION.md), [normalization](docs/PHASE03B_NORMALIZATION.md): canonical tables, populations and QC.
- [Paper/dataset reconciliation](docs/PAPER_DATASET_RECONCILIATION.md), [temporal validity](docs/TEMPORAL_VALIDITY.md): source populations and permissible time claims.
- [Phase 4 enrichment](docs/PHASE04_API_ENRICHMENT.md): selective public history and provenance.
- [Original benchmark](docs/PHASE05_BENCHMARK.md), [assisted review protocol](docs/PHASE05_ASSISTED_REVIEW_PROTOCOL.md): gold review and freeze rules.
- [Sample-data handoff](docs/SAMPLE_DATA_HANDOFF.md): private cohort/history transfer.
- [v3 benchmark](docs/BENCHMARK_V3.md), [retrieval harness](docs/RETRIEVAL_V3.md), [retriever selection](docs/RETRIEVER_SELECTION.md): generation, retrieval metrics and preregistration.
- [Answering systems](docs/ANSWERING_SYSTEMS.md): graph/tool behavior, command history and quota diagnostics; older pilot-pending notes precede the later successful minimal smoke.
- [Earlier evaluation extension](docs/EXTENDED_EVALUATION_RUNBOOK.md), [legacy metrics](docs/EVAL_EXTENSION_METRICS.md), [agent notes](docs/AGENT_NOTES.md): prior pipeline and implementation adaptations.
- [Existing project brief](docs/bugzilla_project_brief.pdf). The owner plans to add **Project Report.pdf** to `docs/`; it is not currently present, so it is not linked as an available file.

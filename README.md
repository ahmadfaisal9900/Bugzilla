# Bugzilla — ENSF 621 evaluation handoff

## 1. What this project is

**Memorize, retrieve, or query?** We compare closed-book LLMs, retrieval and structured tools for Firefox bug-history QA. The [roadmap](docs/reference/research_roadmap.tex) defines the research plan. Compare methods on development and locked test sets first; turn the best supported method into an application afterward. The partner's immediate task is **answer evaluation**, separate from retrieval quality.

## 2. Project status at a glance

| Component | Current status |
| --- | --- |
| v3 dataset | Frozen: 265 dev / 370 test |
| Phase 5 benchmark | Frozen: 34 dev / 135 test; 6 supplemental challenges |
| Natural rewrites | Approved: 51 dev / 59 test |
| Retrieval variants and selected retriever | Done, dev-only selection: R7b/C1 |
| S0–S8 + ORACLE answering systems | Implemented; offline fixture tests pass |
| Dev answering run | Partial, quota-limited |
| Answer scoring, F5 judging, locked test | Not started; partner's next work |

### First 30 minutes for the partner

1. Install the environment and dependencies in section 3.
2. Create the ignored `.env` with your Groq key; add LangSmith credentials only if needed.
3. Run the three offline unit-test commands in section 10.
4. Run `quota` and `plan` from section 11; these make zero API calls.
5. Open `outputs/predictions/<dataset>/dev/run-*/` and read the prediction-field table in section 12 before implementing scoring.

## 3. Setup

Use Git, Bash and **Python 3.10+** (3.11 recommended). The backend is **Groq**, configured as `openai/gpt-oss-20b`. Work in the existing clone; never initialize a nested repository.

```bash
# Fresh clone: install the complete answering stack and editable package.
git clone https://github.com/ahmadfaisal9900/Bugzilla.git
cd Bugzilla
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-answering.txt
python -m pip install -e .
```

`requirements-answering.txt` includes the data, Groq, retrieval, LangGraph and LangSmith stacks. `requirements.txt` alone installs only data tooling.

Create an ignored `.env` with placeholder values replaced locally:

```dotenv
GROQ_API_KEY=replace_with_your_groq_key
LANGSMITH_KEY=replace_only_if_enabling_traces_or_uploads
```

Obtain the **data bundle**: DuckDB/Parquet, verified history, frozen datasets, public corpora, indexes, model weights and retrieval caches. Ignored artifacts are not restored by `git pull`; preserve configured relative paths. LangSmith credentials are optional without tracing/upload. Never commit credentials.

Canonical data is under `outputs/normalization/phase03b/`, history under `outputs/phase04/enrichment/`, and indexes under `outputs/indexes/retrieval_v3/`. Answering loads model weights offline; provision the pinned models before predictions. The first fixture command in section 10 verifies setup without data or API access.

## 4. Repository map

```text
configs/                     Data paths, provider limits, method settings and selection
prompts/                     Shared answering prompts
src/bugzilla_qa/answering/    LangGraph systems, read-only tools and prediction runner
src/bugzilla_qa/retrieval_v3/ Corpus variants, retriever registry and retrieval evaluation
src/bugzilla_qa/llm/          Shared provider, cache and request ledger
scripts/                     Terminal entry points
tests/                      Offline fixture tests
docs/                       Scientific plan and system documentation
outputs/                    Mostly ignored data bundle, indexes and predictions
requirements-answering.txt   Complete dependency stack
pyproject.toml               Package installation and Python requirement
```

Small explicitly allowed review artifacts are tracked; databases, raw text, caches, credentials and large logs are not.

## 5. Data and datasets

### Evidence corpus

The cohort contains **3,000 Firefox-product bugs**, seed 317. Canonical tables hold bugs, comments, explicit links, source/provenance records and sample membership. **Base `field_changes` is empty: never use it for lifecycle answers.** Those answers require the separate verified 50-bug history overlay. Archive snapshot time remains UNKNOWN; ingestion time is not the snapshot date. Private/unknown-visibility comment bodies are withheld.

### Question families

| Family | Answer required |
| --- | --- |
| F1 | Recorded archive field |
| F2 | Verified lifecycle duration/count, or UNKNOWN |
| F3 | Scoped distinct-bug count |
| F4 | Complete explicit relation-target set |
| F5 | Contributor-stated reason/constraint, or insufficient evidence |
| F6 | Abstention where the specified evidence cannot establish an answer |
| KI | ID-free known-item identification or field lookup |
| MH | Multi-hop relation/target answer |
| F6H | Hard abstention: absent IDs, missing fields or unsupported lifecycle duration |

### Final evaluation datasets

| Dataset | Location / layout | Role |
| --- | --- | --- |
| Phase 5 | `phase05_dir` in `configs/retrieval_v3.yaml`, under `outputs/benchmark/phase05/`; separate dev/test/challenge questions and gold JSONL, quality report and manifest | Human-signed benchmark: 169 questions; 6 supplemental paraphrases are not independent records |
| Natural rewrites | `natural_questions` in the same config; `natural_approved.jsonl` and approval manifest | 110 approved wording variants with parent grouping; gold is inline on disk and stripped by inference loaders |
| v3 | `v3_dir` in the same config, under `outputs/benchmark/v3/`; separate dev/test questions and gold JSONL, qrels and manifest | Human-spotchecked benchmark with KI (ID-free known-item), MH (multi-hop), F6H (hard abstention); some capped older-bank items are included inside v3 |

| Family | Phase 5 dev n | Phase 5 test n | Natural dev n | Natural test n | v3 dev n | v3 test n |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| F1 | 6 | 24 | 22 | 42 | 64 | 86 |
| F2 | 4 | 15 | 4 | 8 | 0 | 0 |
| F3 | 6 | 24 | 2 | 2 | 89 | 0 |
| F4 | 6 | 24 | 23 | 7 | 29 | 54 |
| F5 | 6 | 24 | 0 | 0 | 0 | 0 |
| F6 | 6 | 24 | 0 | 0 | 22 | 34 |
| KI | 0 | 0 | 0 | 0 | 42 | 123 |
| MH | 0 | 0 | 0 | 0 | 8 | 47 |
| F6H | 0 | 0 | 0 | 0 | 11 | 26 |
| **Total** | **34** | **135** | **51** | **59** | **265** | **370** |

**v3 gaps:** no F2, no F5, no test F3. Use Phase 5 dev for F5 and the applicable Phase 5/natural dev questions for F2. Phase 5 F5 includes 27 supported explanations and 3 insufficient-evidence cases, all from a FIXED-selected comment population.

Never edit frozen files. Keep test gold out of inference, retrieval text and normal traces. Test execution requires `--confirm-locked-test` and finalized method/scorer settings. Challenges and natural variants are not independent observations.

```bash
# Resolve the configured final dataset locations; prints paths without reading test questions.
python - <<'PYCONFIG'
import yaml
with open('configs/retrieval_v3.yaml') as f:
    c = yaml.safe_load(f)
for key in ('phase05_dir', 'v3_dir', 'natural_questions'):
    print(key, c[key])
PYCONFIG
```

## 6. Retrieval

### Corpus variants and registry

| Corpus | Construction |
| --- | --- |
| C0 | 14,443 chunks; source corpus as-is |
| C1 | 14,195 chunks; comments/history at most 200 embedder tokens, overlap 40; metadata/links retained |
| C2 | 14,666 chunks; C1 plus deterministic bug/component/summary/type prefix, split to fit the embedding limit |

C1/C2 require zero truncations. Embedder: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, 256-token maximum. Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`. Full pinned revisions live in `configs/retrieval_v3.yaml` and manifests.

All adapters are registered in `src/bugzilla_qa/retrieval_v3/registry.py` and expose `retrieve(query, k)` returning `chunk_id`, `record_id`, `bug_id`, `chunk_type`, `score`, `rank`, `text`.

| Registry name | Method |
| --- | --- |
| R1 | BM25 using SQLite FTS5; deterministic zero-score fills are marked |
| R2 | Dense FAISS search |
| R3 | BM25/dense reciprocal-rank fusion, k=60 |
| R4 | Hierarchical parent discovery/ranking, exact-ID restriction; top-10 Jaccard against R3 logged |
| R5 | R3 top-50 candidates reranked by cross-encoder |
| R6 | R5 + one-hop metadata from top-three bugs; at most three neighbour slots |
| R7a | Cached LLM-generated hypothetical report (HyDE), then R5 |
| R7b | Cached three-query transformation, RRF-fused R5 results |

### Inspection and outputs

Builds and dev-only selection are done and shipped with the data bundle; do not rebuild them for evaluation setup.

```bash
# Inspect existing workflow plans with no models loaded, API calls or writes to indexes/selection.
bash scripts/run_phase09_retrieval_v3.sh build --dry-run
bash scripts/run_phase09_retrieval_v3.sh eval --dry-run
bash scripts/run_phase09_retrieval_v3.sh eval --retrievers R7a R7b --dry-run
bash scripts/run_phase09_retrieval_v3.sh select --latest --dry-run
```

`outputs/retrieval/v3/run-*/` contains per-question ranked IDs, JSON/Markdown summaries, top-50 public retrieval cache, config and manifest. Index variants are under `outputs/indexes/retrieval_v3/build-*/C0|C1|C2/`.

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

Qrels are **incomplete known-citation labels**. Unlabeled results count as non-relevant for nDCG; retrieval scores are not answer accuracy. F3/F6/F6H passage metrics are **N/A**, not zero; **not in dataset** means absent family; missing applicable labels are UNKNOWN. Every metric carries **n**.

Statistics: paired parent/`cluster_id` bootstrap, 10,000 resamples, seed 317; same-corpus R1 comparisons on Hit@5/Recall@10 with percentile intervals and Holm correction. [Selection](docs/RETRIEVER_SELECTION.md) maximizes macro Recall@10 across v3/natural dev cells with n≥10 qrel-bearing questions; ties within one point favor lower p95 latency; R7 must exceed same-corpus R5 by >2 points. `configs/selected_retriever.yaml` selects **R7b/C1**; smaller cells remain descriptive.

## 7. Answering systems

Entry point: `src/bugzilla_qa/answering/cli.py`, wrapped by `scripts/run_phase10_answering.sh`. These systems produce **predictions only**.

Counts exclude transport retries. One repair may add a request; caches can reduce calls to zero. Transforms consume the same request cap.

| System | Behavior | LLM requests per question |
| --- | --- | --- |
| S0 | Closed-book, question only | 1 answer |
| S1 | R1 on selected C1 | 1 answer |
| S2 | Selected R7b/C1 | 1 answer + up to 1 missing transform |
| S3 | Query-transform RAG: also R7b/C1 | Same as S2; duplicate retrieval treatment |
| S4 | R5 score gate; local retry, then abstain below tau | 0 if abstaining, otherwise 1 |
| S5 | Public dossier: explicit IDs or S2 top parent; budget 12,000 | 1 answer + possible fallback transform |
| S6 | R6 graph-expansion RAG | 1 answer |
| S7 | Native functions, at most four tool steps | Up to 5 turns + possible repair/search transforms |
| S8 | Routes counts/relations/fields to S7, reasons+ID to S5, ID-free to S2 | Routed calls; ambiguous classification adds 1 |
| ORACLE | Gold-evidence diagnostic only | 1 answer; explicitly selected, separate ledger |

S7 allowlists read-only parameterized `get_bug_fields`, `get_links`, `count_bugs`, `get_lifecycle`, `search_text`; no model SQL. Missing history means unknown, not zero events. S4 tau is a dev-score suggestion, not correctness probability.

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

`answer` is a string, number, scalar list or null; abstention must agree with null. Citations must map to supplied evidence; `Cn` labels are normalized locally. Rationale: at most two sentences/1,000 characters. Validation checks format/citation membership, **not factual support**.

All arms share `prompts/answer_v1.txt`, temperature zero and one generator. Unsupported evidence requires abstention. Optional `--compact-prompts` selects `answer_v2_compact.txt`, a separate identity not live-validated; never mix profiles. Normal context budget: 3,000, conservatively counted as UTF-8 bytes rather than exact model tokens.

Shared provider: `src/bugzilla_qa/llm/provider.py`, `configs/llm.yaml`. It provides structured JSON/tools, SQLite cache keyed by model/prompts/version/schema, append-only ledger, pacing/backoff, a 90%-RPD guard and server cooldowns. Defaults: 3 RPM / 1,000 RPD; token limits may stop earlier. Calls require `--enable-llm` and a cap; otherwise plan/dry-run. Credentials are excluded from artifacts/traces.

LangGraph: `load_question → router → retrieve → pack_context → generate → validate → persist`, with bounded tool loops and one repair. State carries question/scope/identity, route, public evidence/context, output/answer/errors, calls/tools, usage/cache flags and timing.

## 8. Entry points

| Entry point | Purpose / key flags | Safe inspection command |
| --- | --- | --- |
| `scripts/run_phase09_retrieval_v3.sh` | Retrieval inspection; `build`/`eval`/`select`, `--dry-run`, `--retrievers` | `bash scripts/run_phase09_retrieval_v3.sh --help` |
| `scripts/run_phase10_answering.sh` | `plan`/`run`/`quota`/`suggest-tau`/`upload-dev`; `--dataset`, `--resume`, `--max-requests` | `bash scripts/run_phase10_answering.sh --help` |
| `scripts/llm_ping.py` | Provider check; `--dry-run`, `--role`, `--model`, `--max-requests 1` | `python scripts/llm_ping.py --help` |
| `scripts/smoke/check_structure.sh` | Structure/import check; no flags | `bash scripts/smoke/check_structure.sh` |
| Unit tests | Offline answering, provider and retrieval fixtures | Three commands in section 10 |

Older phase scripts under `scripts/` prepare data/benchmarks; that preparation is finished and should not be rerun. Package CLI equivalents are `python -m bugzilla_qa.answering.cli` and `python -m bugzilla_qa.retrieval_v3.cli`. No answer-scoring entry point exists yet.

## 9. Observability

Tracing is opt-in (`--trace`, deterministic `--trace-sample 0..1`); bulk retrieval disables it. Projects: `ensf621-dev` / `ensf621-test`. Root `system:qid` metadata includes system, qid, family, split, dataset, freeze/config identity, model, prompt version, route and cache flag. Retrieval, packing, routing and tools are traced.

Traces contain sanitized **public** evidence, scores, tools and outputs; private/unknown bodies, credentials and gold are excluded. ORACLE is diagnostic. Optional `upload-dev` supplies dev gold as reference outputs outside inference; it runs no evaluators.

Authoritative records: prediction JSONL/manifests, `outputs/predictions/logs/`, `outputs/llm/groq/ledger.jsonl` and retrieval reports/caches. Traces are not accuracy results. Separate retrieval/model cache hits, new calls and cached/new token usage.

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
# 5. Resolve one fixed dev QID from its public question metadata; expect one QID in the shell variable.
smoke_qid="$(python - <<'PY'
import json
import yaml
from pathlib import Path
with open('configs/retrieval_v3.yaml') as f:
    c = yaml.safe_load(f)
for line in (Path(c['v3_dir']) / 'dev.questions.jsonl').read_text().splitlines():
    row = json.loads(line)
    if 'bug 1767855 ' in row['question'] and 'recorded resolution' in row['question']:
        print(row['qid'])
        break
else:
    raise SystemExit('Fixed smoke question is missing; inspect inputs')
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

`COMPLETE_SELECTED_BATCH` means only the selected questions completed, not the full dataset. Repeating a fixed `--qid` never advances to new questions. The single F1 check does not establish correctness across all families or routing/correction branches.

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

Repeat for `--dataset phase05` and `--dataset natural` once budget permits. Lowering a request cap is safe. Full success requires `COMPLETE` and zero remaining work for **all systems on the full dataset**, not only a selected QID or limited family.

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

The local guard's date resets at **midnight America/Los_Angeles**. This is the implemented local accounting window; **do not assume Groq's server token quota resets then**. Groq response headers/cooldowns and the active-model dashboard are authoritative. Planner days are request-budget estimates, not promises under token limits; there is no configured token/day guard. Wait for an indicated cooldown instead of repeatedly spending requests on 429s.

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

No new S0–S8 answer scorer, F5 LLM judge, semantic grounding checker, abstention evaluation, final paired answer statistics or locked-test answering comparison has been implemented. A separate blinded LLM judge is optional, requires explicit quota safeguards and human auditing, and must never be the sole evidence for F5 correctness.

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

## 13. Evaluation limitations

- **S2/S3:** both currently use R7b/C1; they are duplicate retrieval treatments unless explicitly changed and versioned on dev.
- **S0:** abstains under the shared evidence-required prompt; evaluate this behavior rather than counting schema success as useful closed-book accuracy.
- **Incomplete qrels:** known-citation retrieval scores do not establish exhaustive relevance or answer correctness.
- **Firefox-only cohort:** does not represent all Firefox engineering or Mozilla products.
- **FIXED-biased comments:** F5 findings do not generalize to unresolved discussions.
- **No stale-versus-refreshed experiment:** archive snapshot time/availability are unknown; no historical refresh answering result is available.
- **Quota limits:** request and token budgets interrupt batches; cache reuse affects measured cost and latency.

## 14. Troubleshooting

| Symptom | Check / remedy |
| --- | --- |
| Missing provider key | Current backend requires `GROQ_API_KEY` in ignored `.env`; Never paste a key into a command or issue |
| 429, long Retry-After, PARTIAL | Inspect offline `quota`, preserved cooldown and active-model dashboard. Wait, then resume; request caps do not reserve tokens |
| Test split blocked | Intentional safety gate. Do not bypass during development; finalize methods/scoring before explicitly authorized test access |
| Missing corpus/index/cache | Receive the matching local artifact bundle and check configured paths. No large assets come with a normal clone; don't rebuild finished data casually |
| Missing model weights/offline load failure | Answering sets offline model flags. Provision pinned weights separately; no silent live downloads during answer runs |
| S4 requires tau | Use the dev-only `suggest-tau --dry-run` inspection; write a deliberate suggestion with `--write` only when establishing a new declared configuration |
| Invalid JSON/citation | One repair is allowed; inspect `errors`, `raw_output`, `context_map`, normalized citations and status. Do not alter gold to fit outputs |
| Resume starts a different directory | Input/config/code/prompt identity changed. Preserve both versions; inspect their snapshots rather than renaming or concatenating ledgers |
| Import error / Python version mismatch | Activate the correct environment and install `requirements-answering.txt`; use package installation or `PYTHONPATH=src` for fixture commands |

## 15. Deeper documentation

- [Scientific roadmap](docs/reference/research_roadmap.tex): research questions, rubric and fairness controls.
- [v3 benchmark](docs/BENCHMARK_V3.md): question generation, review and dataset coverage.
- [Retrieval harness](docs/RETRIEVAL_V3.md): corpus variants, metrics and outputs.
- [Retriever selection](docs/RETRIEVER_SELECTION.md): preregistered dev-only selection rule.
- [Answering systems](docs/ANSWERING_SYSTEMS.md): graph/tool behavior and provider controls.
- [Data dictionary](docs/DATA_DICTIONARY.md): canonical fields and provenance.
- [Temporal validity](docs/TEMPORAL_VALIDITY.md): permissible event-time and snapshot claims.
- [Agent notes](docs/AGENT_NOTES.md): implementation assumptions and adaptations.

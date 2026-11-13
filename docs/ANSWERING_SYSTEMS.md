# Phase 10 / Task 3: prediction-only answering

Implementation and offline fixture validation only; owner-terminal pilot pending.
No answer scorer, evaluator or comparison result is added. The prior M3 intent
parser is **deprecated for the new comparison** (recorded NO_INTENT failures);
its implementation and historical predictions remain untouched. S7 is a new,
audited function-tool arm and must not be relabeled as a successful old M3 run.

## Inventory: expected → found

| Expected | Found |
| --- | --- |
| Existing root/origin | Project/; ahmadfaisal9900/Bugzilla |
| Provider/model | `src/bugzilla_qa/llm/provider.py`; Groq `openai/gpt-oss-20b`, generator role |
| Registry | `src/bugzilla_qa/retrieval_v3/registry.py` |
| Selection | `configs/selected_retriever.yaml`: R7b/C1, SELECTED_DEV_ONLY |
| Index build | `outputs/indexes/retrieval_v3/build-aa0d0cdb13268fb4/` |
| Corpus counts | C0 14,443; C1 14,195; C2 14,666; manifest reports zero truncations |
| Offline retrieval/cache | `outputs/retrieval/v3/run-6dc5f2f12b0673ea/`; COMPLETE, 6,300 result rows |
| R7 retrieval/cache | `outputs/retrieval/v3/run-9c6eb525c415311a/`; COMPLETE, 4,200 result rows |
| v3 freeze | `outputs/benchmark/v3/run-289a50d1152f547a/frozen-e2207774a0f2cbad/` |
| Phase 5 freeze | `outputs/benchmark/phase05/run-65c5be3381f66811/frozen-d8ef826fbeb90d13/` |
| Natural questions | `outputs/eval_extension/bank-dacb7ca0ceb7e0ef/natural_approved.jsonl` |
| Canonical DB | `outputs/normalization/phase03b/run-20261022T023542Z-1182018/canonical.duckdb` |
| Verified lifecycle | `outputs/phase04/enrichment/cohort-8bb3150d29a598d8/checkpoint.json`; separate overlay |
| Graph/config/prompt | `src/bugzilla_qa/answering/`; `configs/answering.yaml`; `prompts/answer_v1.txt` |

The older 12,828-chunk/564-truncation description refers to a previous corpus.
These counts are observed saved metadata, not newly run retrieval experiments.
Selection source summary hashes and the public corpus are checked when loaded.
The GB canonical DB is size/manifest checked; it is not rehashed or imported.
All source data, frozen question/gold files and original M3 code are unchanged.

## Arms and assumptions fixed before prediction runs

All arms use the generator role, temperature zero, one shared prompt, answer
schema and maximum output length. A real LangGraph StateGraph implements load,
route, retrieve, pack, generate, tools, validate/one repair, and persist. S0 runs
first; requests are stateless and no earlier answer is inserted into another arm.

| ID | Evidence/behavior |
| --- | --- |
| S0 | Question only, no retrieved scope facts or tools |
| S1 | R1 on selected corpus C1 |
| S2 | Selected R7b/C1, using completed dev retrieval caches first |
| S3 | Configured R7 variant; currently R7b, therefore shares S2 retrieval |
| S4 | R5 cross-encoder score gate; one deterministic local three-query retry and re-rerank; below tau abstains without any LLM call |
| S5 | Exact referenced cohort bugs, else S2 top-1 bug; public dossier by metadata/comments/links/history, budget 12,000 |
| S6 | Existing R6 graph expansion on C1 |
| S7 | Native provider function calling, at most four executed tool steps then final answer; no free-form SQL |
| S8 | Preregistered rules to S7/S5/S2; one classification call only for ambiguous ID queries |
| ORACLE | Explicit diagnostic only: gold/qrel record IDs mapped to public corpus chunks; missing/packed IDs logged |

S3 is deliberately not presented as a different retrieval method while it has
the same setting as S2. Any alternate R7a configuration must be declared using
dev only and creates a new prediction identity. S4 must use R5 cross-encoder
scores, not RRF scores. Its tau is a dev-score-quantile **suggestion**, not a
calibrated correctness probability. The local retry uses original, punctuation
normalized and ID/keyword-tail queries. It performs no query-generation API call.

Context token budgets conservatively count UTF-8 bytes, including citation labels
and IDs. No compatible hosted-generator tokenizer is available locally. This can
pack less than 3,000 actual tokens; it cannot silently exceed that budget for the
configured byte-based tokenizer family. The same policy applies to all normal
RAG arms. The dossier alone has the predeclared 12,000 budget. Excessive tool
results are omitted from model context with an explicit message to narrow the
request; complete results remain in the local audit ledger. Lists of answer
values contain scalar JSON values; compound answers may be expressed as text.

The provider gains native Groq/Gemini function calling through its existing
cache, retry, quota and request ledger; it is not replaced. `submit_answer` uses
the same final answer schema. Tool results are serialized as public JSON evidence
on subsequent stateless turns. Native argument schemas are independently checked
locally. Rejected calls and every executed result are recorded. Transport/quota
failures stop the batch; JSON/answer-contract failures receive at most one repair.
Groq HTTP 400 tool_use_failed in a no-tool JSON request is an invalid model
output, not a transport retry: it uses that same single repair, with no browser
or hidden tool executed. Plain JSON requests explicitly set tool_choice=none.
Actual HTTP attempts, including retries and transforms, consume --max-requests.

## Source, scope and privacy gates

- Question loaders return only whitelisted question metadata. Natural rows contain
  gold on disk; it is stripped. Phase 5 lacks family in its question file, so only
  qid/family metadata is extracted from its hash-checked gold file. No SQL, typed
  gold, rubric or evidence labels enter a normal graph. ORACLE and optional dev
  reference upload have separate, explicitly named reference loaders.
- Test access requires --confirm-locked-test, records a receipt, and creates a
  separate split/run directory. Never tune prompts, routes, tau or selection on test.
- Only explicitly public indexed chunks are hydrated. Cached text is not trusted:
  chunk IDs are mapped back to checked public corpus text. Unknown/private bodies
  are refused. Emails/handles and known credential values are redacted before
  ledger and trace serialization. No .env values are persisted in config.
- get_bug_fields uses allowlisted archive fields; absent priority/severity remain
  null. It never exposes assignee/reporters. Relation sets are complete recorded
  target-ID sets; no historical relationship validity is inferred.
- count_bugs counts distinct canonical bugs, respects seed 317 and the declared
  partition, excludes conflicts for declared non-conflicted populations, and uses
  only creation [from,to) filters. Phase 5 and expanded-v2 have different partition
  functions; natural/v3 copied aggregates retain their original expanded-v2 scope.
  No original_scope typed gold is added. Broader `all` counts require an explicit
  declared all-canonical scope. Lookups cannot escape the indexed study cohort.
- get_lifecycle never reads base field_changes. It requires the separately verified
  Phase 4 parsed chronological history, excludes same-time/source-conflict cases,
  and reuses first-FIXED arithmetic with archive creation time. Missing transitions
  remain UNKNOWN; no latest-change proxy, engineer-hours or fabricated snapshot.
  Provenance includes fetch time, URL and response hash. Unsupported historical
  availability scopes return unknown. Reopening counts remain separate.
- v3 lacks F2/F5 and test F3. Phase 5 supplies F5; natural dev has no F5. Its F5
  evidence is FIXED-selected; no conclusion about unresolved discussion is implied.

## Owner-terminal commands, in order

Use the existing iqfm environment. These commands neither rebuild indexes nor
regenerate benchmark gold. The agent ran no live calls or real answer batches.

```bash
conda activate iqfm
python -m pip install -r requirements-answering.txt

# 1. Offline score-distribution suggestion; inspect output, then save it.
bash scripts/run_phase10_answering.sh suggest-tau --dry-run
bash scripts/run_phase10_answering.sh suggest-tau --write

# 2. Zero-call plans, including cache hits, tokens, quota and remaining work.
for dataset in v3 phase05 natural; do
  bash scripts/run_phase10_answering.sh plan --dataset "$dataset" --resume
 done

# 3. Fixed pilot: first up to three questions per present family per system.
# Each invocation is capped; repeat the SAME command on PARTIAL after quota resets.
for dataset in v3 phase05 natural; do
  bash scripts/run_phase10_answering.sh run --dataset "$dataset" \
    --limit-per-family 3 --run-tag pilot --enable-llm --max-requests 100 \
    --trace --trace-sample 1 --resume
 done

# 4. Daily dev batch; repeat for each dataset until remaining_by_system is zero.
# Without --limit-per-family, --limit advances through pending questions.
bash scripts/run_phase10_answering.sh plan --dataset v3 --limit 25 --resume
bash scripts/run_phase10_answering.sh run --dataset v3 --limit 25 \
  --enable-llm --max-requests 200 --resume
# Repeat with --dataset phase05 and --dataset natural.

# Optional: sampled tracing for a daily batch; changes no answer prompts.
# Add --trace --trace-sample 0.1 to the run command.

# Optional dev references in LangSmith; no answer evaluation is run.
bash scripts/run_phase10_answering.sh upload-dev --dry-run
bash scripts/run_phase10_answering.sh upload-dev --enable-upload --max-requests 100 --resume
```

The suggestion reports n, score quantiles and tau. Plan reports `DRY_RUN`, zero
actual calls, per-arm estimated/upper calls and safe daily remaining quota.
The pilot should write schema-valid rows and traces in `ensf621-dev`, or report
PARTIAL plus a concrete quota/transport/contract blocker. A completed limited
batch is `COMPLETE_SELECTED_BATCH`, **not the entire dataset**. Full completion
is `COMPLETE` with zero remaining questions for all requested systems. Repeating
pilot commands resumes the fixed pilot set; daily --limit advances instead.
The default S4 config blocks until tau is saved. Changing config/code/prompt,
selection, calibration or input hashes creates a distinct run directory.

Artifacts: `outputs/predictions/<dataset>/<split>/run-<config-hash>/S*.jsonl`,
identity/config snapshot, summary, manifest with input/output hashes, and optional
locked-test receipt. ORACLE has its own ledger and diagnostic marker. Each row
includes model/config/prompt identity, route/rule, source chunk IDs, token usage
(including transforms; cached tokens separate), actual call count, latency, tool
calls/results and errors. Successful rows are append-only and skipped on resume;
failed attempts remain auditable. An interrupted final append is backed up before
recovery. Logs are under `outputs/predictions/logs/`. All outputs remain ignored.

At configured 3 RPM, the shared limiter permits about two request starts/minute,
with a 900-request local daily safety cap shared with other jobs on that model.
Actual account token limits can stop earlier. The planner reports current ledger
usage; do not launch concurrent model jobs to bypass it. S7 may need up to five
turns plus a repair and search transforms. The 100/200 caps deliberately allow
partial resumable runs. Tracing/upload requests are separate LangSmith requests;
only opted-in questions are traced, and uploads have their own capped ledger.

## Validation scope and remaining work

Offline real-LangGraph tests use mock responses and tiny DuckDB fixtures. They
exercise every arm, tool calls/caps/injection/read-only behavior, independent
source partition rules, UTC lifecycle/unknown/conflict handling, one repair,
privacy/token bounds, locked-test gating, planning cache accounting, resumability,
frozen-file sentinels, native function transport/cache/ledger and mocked serialized
trace redaction. They do not establish answer quality or live provider/schema
compatibility. Owner must inspect the pilot's sanitized summary/trace samples
before daily runs. Answer scoring, test runs and production app are later tasks.

## Owner pilot inspection — 2026-11-13

Run `v3/dev/run-d0ac31d57bcca87e` is PARTIAL. S0 completed its fixed 21-item
pilot and abstained on all 21. S1 reached two unique questions: one valid
aggregate abstention and one contract failure (repeated cached attempt). No
S2–S8, Phase 5 or natural pilot ledger exists yet. Daily batches remain blocked.
The failed S1 raw answer states FIXED for bug 1861451, citing label C1. Direct
inspection of the mapped explicitly public metadata confirms that resolution
and matching bookmark-test summary. This is a citation representation defect,
not evidence of a wrong claim in this inspected case. It is not an accuracy
estimate or full pilot acceptance.
The validator now resolves only exact provided labels Cn / [Cn] to their mapped
chunk IDs and then applies the original citation whitelist. Unknown labels stay
invalid. Raw outputs remain unchanged and citation_normalization records every
mapping in new prediction ledgers. Gold and old predictions are not rewritten.
Retry the same fixed pilot command; code hashes produce a new output version,
while unchanged provider prompts can reuse cached model responses. Inspect all
three dataset pilots after they complete before beginning daily batches.
An aggregate-only local check is saved under ignored outputs/predictions/
pilot_checks/check-3a5b78ed4594a8c6/summary.json. All observed status/coverage
counts refer to original ledgers; an error fallback is not a model abstention.

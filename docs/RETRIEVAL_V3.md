# Task 2 — corpus variants and retrieval experiments

Implemented with offline 50-chunk fixtures; full builds, evaluations and live R7
calls are AWAITING_TERMINAL_RUN. The frozen v3 source is
`outputs/benchmark/v3/run-289a50d1152f547a/frozen-e2207774a0f2cbad/`, freeze
`e2207774a0f2cbad`, FROZEN_HUMAN_SPOTCHECKED on 2026-11-12. See
[BENCHMARK_V3.md](BENCHMARK_V3.md) for its counts and coverage gaps.

## Inventory and provenance

| Expected | Found/adaptation |
| --- | --- |
| Existing Project/origin | Existing Project root; `https://github.com/ahmadfaisal9900/Bugzilla.git` |
| Frozen v3 | Above path; all 15 manifest artifact hashes verified before implementation |
| qrels | Manifest names `qrels_v3_dev.jsonl` (265 rows: 143 applicable/122 N/A), `qrels_v3_test.jsonl` (370 rows: 310 applicable/60 N/A) |
| Phase 5 dev | `outputs/benchmark/phase05/run-65c5be3381f66811/frozen-d8ef826fbeb90d13/` (34 questions) |
| Natural dev | `outputs/eval_extension/bank-dacb7ca0ceb7e0ef/natural_approved.jsonl` (51 dev / 59 test); hash checked against adjacent approval manifest |
| Current corpus C0 | `outputs/eval_extension/39a751ca190bbbc3/corpus.jsonl`: 14,443 v2 chunks, not the older 12,828-chunk v1 corpus |
| Reusable dense index | `outputs/eval_extension/bank-dacb7ca0ceb7e0ef/dense.faiss` and dense manifest; 384 dimensions, reported truncation zero |
| Existing implementations | `eval_extension/retrieval.py` and `dense.py`: FTS5, FAISS, RRF, hierarchy, cross-encoder |
| Provider | `src/bugzilla_qa/llm/provider.py`, `create_provider(..., role='generator')`; configured Groq following the owner's switch from Gemini |
| History | Separate Phase 4 overlay via existing `eval_extension.cli.records`; never reads canonical `field_changes` |

All new paths/limits/model revisions are in `configs/retrieval_v3.yaml`.
`configs/llm.yaml` remains the shared provider configuration; GROQ_API_KEY stays
in ignored `.env`. Neither file's secret values enter reports. The original
Phase 5 and v3 directories are read-only inputs. Dev loading reads only dev gold;
shared natural exports are filtered to dev before evaluation. Expanded bank drafts
are not an evaluation dataset in this harness.

## Corpora and adapters

C0 copies the current corpus byte-for-byte and reuses the verified dense index
when model, revision, corpus and index hashes agree. C1 uses the existing public
source loader and fast-tokenizer chunker on complete comments/history, at most
200 tokenizer tokens with 40-token overlap; existing metadata/link payloads stay
unchanged. Source records are restricted to the C0 record population.

C2 prefixes every C1 payload with
`Bug {bug_id} | {component} | {summary} | {chunk_type}: ` using canonical public
component/summary. It splits payloads further where the full prefix would exceed
256 embedding tokens, preserving source record IDs, parent chunk IDs and original
character offsets. The complete prefix is retained; an impossibly long prefix
fails explicitly. Both C1/C2 validate final lengths before embedding and require
truncated_chunks=0. No tokenizer truncation is accepted for those variants.

New builds live under `outputs/indexes/retrieval_v3/build-<id>/C0|C1|C2/`.
Each variant has corpus, lexical SQLite, FAISS, embedding shards and checksummed
manifests including model/revision, counts and actual truncation. The build has
config/identity, an aggregate summary and explicit within-cohort link edges.
Only the separate verified overlay supplies history records. No history or
historical snapshot time is synthesized.

All retrievers implement `retrieve(query,k)` and return chunk_id, record_id,
bug_id, chunk_type, score, rank, text. `retrieval_v3.registry.REGISTRY` is the one
registry. R1/R2 use the existing unfiltered lexical/dense searches; R3 uses RRF
k=60; R4 wraps the existing hierarchy for parent discovery and ranks within the
chosen parent (explicit `bug`/`issue`/`report` IDs, `#ID`, or bare 6–8 digit IDs restrict directly). R5 cross-encodes the
top-50 R3 candidates. R6 adds metadata for explicit, either-direction one-hop
neighbours of R5's top-three distinct bugs, deterministically inserting at most
three into ranks 8–10. This ranking has a stable top-50 prefix. Fewer than k
results is legitimate when an R4 parent has fewer than k chunks or is absent.
R1 fills unmatched slots with deterministic zero-score chunks flagged as such.

R7a uses one hypothetical report over R5; R7b uses three query rewrites and RRF
fusion over R5. They reuse the existing provider, strict JSON schema, role
`generator`, request budget/retries, Pacific daily ledger and SQLite response
cache. There is no second provider implementation. Each unique question needs at
most two successful transform calls across all corpora. Retries consume the
HTTP cap. Resuming reuses both transform and retrieval caches.

## Owner-terminal commands, in order

From Project with the existing `iqfm` environment:

```bash
conda activate iqfm
python -m pip install -r requirements-v3.txt
bash scripts/run_phase09_retrieval_v3.sh --help

# 1. New indexes. C0 is copied/reused; C1/C2 are newly embedded.
bash scripts/run_phase09_retrieval_v3.sh build --dry-run
bash scripts/run_phase09_retrieval_v3.sh build --resume

# 2. All offline retrievers, all three corpora, dev only.
bash scripts/run_phase09_retrieval_v3.sh eval --dry-run
bash scripts/run_phase09_retrieval_v3.sh eval --resume

# 3. R7 plan (zero calls), then the opt-in capped run.
bash scripts/run_phase09_retrieval_v3.sh eval --retrievers R7a R7b --dry-run
bash scripts/run_phase09_retrieval_v3.sh eval --retrievers R7a R7b --enable-llm --max-requests 750 --resume

# 4. Only after both dev summaries say COMPLETE.
bash scripts/run_phase09_retrieval_v3.sh select --latest --dry-run
bash scripts/run_phase09_retrieval_v3.sh select --latest
```

Build expects COMPLETE, C1/C2 truncated_chunks=0; rerunning --resume verifies
completed artifacts. Evaluation expects COMPLETE and per-question rows for every
requested dataset/method/corpus; resume verifies completed work. R7 defaults to
DRY_RUN unless --enable-llm is present. The plan reports the unique-query call
upper bound (at most 700 for 350 dev questions), with zero actual calls. It
includes all question families to cache evidence for later answering, even when
passage metrics are N/A. Budget exhaustion yields PARTIAL / exit 2; repeat the
same command to resume when quota is available. Baseline R1/R5 caches from the
compatible latest offline run are reused automatically. A changed source, code,
configuration or index identity refuses reuse.

Selection expects SELECTED_DEV_ONLY and writes `configs/selected_retriever.yaml`.
It refuses an existing selection file; use --output with a new file name for an
explicit separately recorded selection. --latest uses completed dev pointers;
check the R7 run is COMPLETE first. Explicit --summaries paths are also supported,
listing the original offline summary before the R7 summary. Selection never
reads test questions/gold and rejects test/limited/partial summaries.

Optional bounded owner smoke: use `build --limit 5 --resume`, then
`eval --limit 2 --resume`; these create separate identities, remain ineligible
for selection, and must be followed by the unlimited build before full eval.
--limit means bugs for build and qids per dataset for eval. To use a specific
build, pass --index-run. --help lists all arguments.

Rough CPU planning estimates, not measurements: build 10–40 minutes; offline
R1–R6 evaluation 30 minutes–3 hours; R7 several additional hours. At the current
2 request-starts/minute provider pacing, 700 uncached transforms alone need
about 6 hours plus local retrieval and retry time. Account-specific token/daily
quotas can require a later resumed run. Allow roughly 0.3–1 GB for new corpus,
index/shard/report artifacts plus model caches. Initial pinned-weight downloads
add time. No paid service is required; the agent made no live calls.

## Reports, statistics and selection

`outputs/retrieval/v3/run-<id>/` contains:

- `per_question.jsonl`: ranked source IDs, metrics, timings, unmapped qrel counts,
  cache/transform provenance and R4/R3 top-10 Jaccard. No source comment bodies.
- `retrieval_cache.sqlite`: the complete top-50 public hits with text, indexed by
  corpus/retriever/dataset/qid, without typed gold or templates. A later answer
  stage can call `retrieval_v3.runner.load_cached_hits(...)` without retrieval.
- `summary.json` and `summary.md`: all requested metrics per dataset/family/method/
  corpus, metric-specific n, counts, coverage labels, p50/p95 and paired tests.
- `identity.json`, `config_snapshot.json`, `manifest.json`: SHA-256 pins, Git
  commit, model revisions, data hashes, limit/test flags and selection protocol.
- `LOCKED_TEST_ACCESS.json` only on an explicitly confirmed test invocation.

Bulk tracing is disabled in shell and Python, including LANGSMITH_TRACING and
both legacy LANGCHAIN flags. Real models are loaded once across corpora. Each
method's measured query computation starts with a fresh query memo, so sharing a
previous method's work does not artificially lower its latency; model weights
stay warm. Retrieval-cache resumes keep original measured latency. R7 cache hits
also retain the original measured transform generation latency, while reporting
observed reuse time and cache flags separately.

Known-citation Recall uses all supplied distinct evidence record IDs, including
unindexed ones. Overlapping chunks do not earn repeated record credit. Binary
nDCG treats unlabeled chunks as non-relevant and repeated records as zero gain;
labels are incomplete. A zero score is a miss, never a replacement for N/A.
F3/F6/F6H report N/A; an absent family says "not in dataset"; absent qrels on an
otherwise applicable item say UNKNOWN. MH full-evidence@10 requires every cited
record, not one target. Bug Hit@5 has its own denominator where acceptable IDs
are supplied. All table metrics carry n, including zero-size absent cells.

Accepted coverage gaps: v3 F2=0, F5=0, test F3=0. Natural dev is F1=22, F2=4,
F3=2, F4=23 and has no F5. Phase 5 dev supplies six F5 and four F2 questions.
The preregistered n>=10 rule excludes these small cells and v3 MH dev n=8 from
selection; they remain descriptive. Expected eligible selection cells are v3
F1/F4/KI and natural F1/F4, subject to actual qrel validation. See
[RETRIEVER_SELECTION.md](RETRIEVER_SELECTION.md) for the complete fixed rule.

Paired cluster bootstrap uses 10,000 resamples/seed 317 and question-weighted
paired differences versus R1 on the same corpus/cell. Parent bugs keep variants
together. JSON reports percentile CIs, centered bootstrap p values and Holm
adjustments across the run. This does not correct incomplete qrels or establish
answer correctness. Historical source availability remains unverified.

Locked test requires --split test --confirm-locked-test and refuses any existing
run directory, even with --resume. An intentional new test invocation requires
a new --run-tag and records that access. Do not run test before S2 is selected
and all answering methods/configurations are fixed. Task 3 answering is separate.

Validation: 38 offline tests pass (14 new 50-chunk fixture tests and 24 existing
retrieval/provider regressions); shell syntax, CLI help and diff whitespace
checks pass. Original/v3 frozen artifact hashes match. No actual corpus index
or API/evaluation job ran in the agent session.

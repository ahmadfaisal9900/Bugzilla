# Phase 0 — shared contracts and fixtures

## State and review gate

Phase 0 is being created on `feature/mlops`. The supplied partial uncommitted
package/config/dependency work was extended in place. Research code is unchanged.
This is shared foundation only; it does not implement either application stream.
Both Ahmad (`ahmadfaisal9900`) and `SpLasty` must review before the streams begin.
CODEOWNERS lists both; GitHub branch protection must separately require the intended
approvals (listing two owners alone does not require both to approve).

**Environment gate:** use Conda `iqfm`, not venv. Inspection found Python 3.9.25
and missing FastAPI, MLflow, Streamlit, pytest and Ruff. The target is Python 3.11.
No dependencies were installed by the agent, following the explicit owner rule.
The pinned direct dependencies are in pyproject extras and included from
`requirements.txt`. The Python 3.11 pytest/Ruff gates and OpenAPI snapshot generation
remain pending the owner installing them. Do not describe Phase 0 as approved,
fully tested, or ready for the streams until those gates pass.

## Expected → found

| Expected | Found / handling |
| --- | --- |
| Integration branch | `feature/mlops`; overview's `mlops` name is superseded by the owner's instruction |
| Empty Phase 0 | Partial uncommitted RunConfig, skeleton, serving/preset configs and pyproject pins; retained and extended |
| Python 3.11 in iqfm | Python 3.9.25; dependency installation and Python update belong to the owner |
| Contracts/engine/fixtures | Created in the paths named in the task; no research package edits |
| Scored partner pilot | `pilot125` contains `REVIEW.csv`/`START_HERE.html`, a PILOT human-review bundle, not full-dev metric results |
| Model context ceiling | Architectural limit was not supplied; the draft's 4,096 operational input cap is retained for review |
| Partner reviewer | Supplied during this task: `SpLasty` |

## Configuration and supported knobs

Every field is in `contracts/run_config.py`, and every widget specification is in
`configs/serving.yaml`. Default common fields remain in serialized configs for
stable tracking; nondefault inapplicable values and non-null inapplicable
system-specific settings are rejected. No graph setting is silently exposed as
an effective override when the selected arm ignores it.

| Field | Consumer in unchanged research code / adapter |
| --- | --- |
| system_id | `answering.graph.AnswerGraph.invoke`; R0 is the adapter's retrieval-only branch |
| retriever | `answering.backend.Backend.selected` and `retrieve`; fixed S1/R1, S4/R5 and S6/R6 arms reject conflicting choices; S3 must match its transform |
| corpus | Adapter selects the verified C0/C1/C2 directory and hydrates that public corpus |
| provider/model/temperature | `llm.provider.create_provider` and `_request`; tests inject the existing MockProvider |
| top_k | `Backend.retrieve` uses `retrieval_k`; S7 search tools explicitly supply their own k |
| context_budget_tokens | `AnswerGraph.pack_context`: `context_tokens`, conservative UTF-8 byte counting |
| prompt_version | Adapter maps only the two existing prompt files; `AnswerGraph._call` passes the version to the provider |
| s4_tau | `AnswerGraph.retrieve` compares R5 cross-encoder scores; starter -4.5 is not a measured correctness threshold |
| s5_dossier_budget | `AnswerGraph.pack_context`: `dossier_tokens`; applies to S5 and the router's S5 path |
| s7_max_tool_steps | `AnswerGraph.generate/tool`: capped at four; applies to S7/router |
| rrf_k | `retrieval_v3.registry.Engine.base/graph` and `Backend.corrective`; rejected for R1/R2 |
| query_transform | `AnswerGraph.retrieve` for S3; R7a/R7b only |

Research retrieval caches do not key every runtime knob. The adapter bypasses
those caches for arbitrary runtime overrides. Provider response caches are
namespaced by RunConfig hash because the original provider key omits temperature;
the shared per-model request ledger and quota accounting are retained.

The model offers Groq `openai/gpt-oss-20b` with 30 RPM, 1,000 RPD, 8,000 TPM and
200,000 TPD. `max_context_tokens=4096` is an **operational input cap**, not a claim
about the provider's architectural context window. Source budgets use the
research byte-based packer. Whole-request TPM/daily guards and serving degradation
remain Stream A work; context caps alone do not guarantee a request fits TPM.
The default dossier budget is reduced from the research 12,000 to this operational
cap. Fallback recommended/fast/deep presets make no performance or champion claim.

### Knobs deliberately not offered

| Setting | Reason |
| --- | --- |
| Index chunking, embedding/reranker model or revision, device, batch size | Index/build settings; not per-question graph overrides |
| Arbitrary prompt text | Would violate shared prompt/version provenance; only existing profiles are allowed |
| Output-token/thinking controls | Not requested RunConfig fields; retain pinned provider configuration |
| Arbitrary SQL / graph hops / unlimited tool steps | Unsupported; retain allowlisted research tools and existing graph bounds |
| Tracing sample, session limits, endpoint settings | Stream A runtime/observability responsibilities |
| R7 retrieval under R0 | Would consume an LLM call; R0 permits only R1–R6 |

## Bundle and adapter handoff to Stream A

`build_runner(cfg, provider=None).run(question, on_event=None)` returns the shared
AnswerRecord. Callback payloads are status-event envelopes with `event` and `data`;
stages are retrieving, retrieved, generating, done. The retrieved detail includes
the source count; R0's generating detail explains that generation was skipped.
R0 returns an abstention plus evidence, degraded=true and zero calls. No answering
logic is replaced. ORACLE requires an exact known dev question with explicitly
provided evidence references; arbitrary public chat cannot invent an oracle.

`BUNDLE_DIR/manifest.json` uses `schema_version=phase0-v1`, `split=dev`, a
`files` map (relative path → bytes/sha256), `runtime_config` and `dev_questions`.
The runtime config points to research-compatible retrieval/selection/source/history
files inside the bundle. The adapter verifies the bundle and refuses non-dev
questions, public-visibility failures and file tampering. A real serving bundle
must additionally include its read-only canonical database and real model indexes.
The fixture-only `synthetic=true` flag materializes `canonical.sql` into a temporary
DuckDB; this is not an import route for real research datasets.

The synthetic bundle contains 20 fake bugs, 61 public synthetic chunks, explicit
links, one synthetic history and ten dev questions across nine families. C0/C1/C2
use the existing `build_lexical` FTS5 builder. Dense/cross-encoder test doubles use
the same term-overlap approach as `tests/test_retrieval_v3.py`; they are patched
only by contract fixtures, not loaded as production model weights. No FAISS
quality or live inference result is implied. No original test questions or gold
are read by the builder or tests.

The sample partner export has the actual pilot's two-file layout and exact CSV
header, with synthetic contents and a PILOT subset label. It is not a scored
export. The sample retrieval summary follows the saved dev summary's top-level
and cell schema, with fake metrics and n. LangSmith fixtures contain 30 fake root
runs and user_rating feedback across three presets.

## Local commands (owner terminal)

```bash
# Prepare the existing Conda environment; the agent does not execute installations.
conda activate iqfm
conda install -n iqfm python=3.11
python -m pip install -r requirements.txt
```

If CPU-only PyTorch is needed, provision the pinned CPU build before the requirements
installation using the PyTorch CPU wheel index. Keep the declared version consistent.

```bash
# Generate synthetic files only; no APIs, datasets or model downloads.
PYTHONPATH=src python scripts/build_fixture_bundle.py
# Generate/review the initial schema snapshot once, after installing the exact pins.
UPDATE_SNAPSHOTS=1 python -m pytest tests/contracts/test_contracts.py -k openapi_snapshot -q
# Run the shared gate and existing no-download research regressions.
python -m pytest tests/contracts tests/test_answering_graphs.py tests/test_retrieval_v3.py -q
python -m ruff check
python -m ruff format --check
```

```bash
# Local fake tracking/registry only: nine runs, three config versions, two presets.
PYTHONPATH=src python scripts/seed_mlflow_fixture.py --tracking-uri file:./outputs/mlflow-phase0
# Repeating the seed command should report created_runs=0.
mlflow ui --backend-store-uri file:./outputs/mlflow-phase0 --host 127.0.0.1 --port 5000
```

The API stub returns health=ok and 501 for all remaining valid requests. Its
OpenAPI snapshot changes only when UPDATE_SNAPSHOTS=1. Serving routes and both
UIs are deliberately stubs. The seed script rejects remote tracking URIs, uses
synthetic tags/configs only, and publishes a synthetic fixture champion.

## Remaining gates / open questions

1. Owner installs the pinned environment, then agent runs/fixes the exact Python
   3.11 contract tests, MLflow seed checks, fake-key scan and Ruff. The OpenAPI
   snapshot cannot be generated accurately until FastAPI is available.
2. Confirm the 4,096 operational context cap; supply an architectural model cap
   only if it should be represented separately in a future reviewed contract.
3. Both collaborators review the shared code and initial snapshot before A/B work.
   No live inference, DagsHub/LangSmith operations, deployment or pushes occurred.

## Approved amendments — 2026-11-21

Approved by **ahmadfaisal9900; partner notified**:

- `RunConfig.validate_against(spec, mode="execute"|"record")` now separates
  execution eligibility from archival recording. Default `execute` retains
  serving ranges, applicability, allowed combinations and model caps. Engine/API
  call sites remain unchanged and therefore execute-strict.
- `record` preserves known typed configuration fields without numeric serving
  caps/applicability checks. Enum identity, forbidden extra fields, strict types
  and finite values still apply. Numeric bounds live in execute validation;
  the execute-facing OpenAPI schema is unchanged.
- `CONFIG_ORIGIN_TAG = "config_origin"` is exported in `names.py`. Only
  `source=backfill` may use `historical`/`reconstructed` record validation.
  Historical ledger imports use `historical`; review-only reconstruction uses
  `reconstructed`. Neither implies deployability.
- Preset publication and champion configuration loading always revalidate in
  execute mode. A policy override cannot bypass this gate. Historical 12,000-token
  S5/S8 dossiers remain recorded faithfully and cannot be published unchanged.
- Missing exact pilot prediction references permit a review-only backfill;
  cost/latency/token metrics are omitted. No synthetic replacement ledgers.

The missing `tests/contracts/openapi.json` artifact was restored from the
unchanged Phase 0 stub. Its JSON was compared byte-for-byte with OpenAPI generated
using the pre-amendment RunConfig: identical. No API implementation or contract
shape was changed. Golden RunConfig hashes remain covered by the original tests.

### Approved amendment: pending family counts (2026-11-21)

At ahmadfaisal9900's explicit request, `answer.<FAMILY>.pending` is now an allowed
nonnegative integer metric alongside `.score` and `.n`. It records shared human
review exclusions, not errors. No RunConfig, API or execution contract changed.

### Approved amendment: usage accounting (2026-11-22)

At ahmadfaisal9900's explicit request, `cost.usage_missing_n` and
`cost.llm_calls_per_question` are allowed metrics. Cached token totals remain
artifact columns, preserving the existing cached-token metric contract. Serving
configuration and API contracts are unchanged.

## Amendment 2 — dossier evidence cap (2026-11-22)

Approved by both collaborators in the B6 instruction. The former 4,096 dossier
maximum was a conservative Phase 0 placeholder, not a Groq quota limit. Raise
only s5_dossier_budget.max to 12,000; retain its 4,096 default, the separate
context_budget_tokens maximum, model operational cap, tool-step and other caps.
The label/help explicitly identify UTF-8 evidence bytes. The RunConfig validator
uses this knob's own byte range rather than comparing it to a token-input cap.
Its fields, hash serialization and OpenAPI schema remain unchanged.

Evidence from the accepted pilot: S5 reports 235,702 input tokens / 127 calls =
1,855.9 input tokens per call, with a 12,000-byte dossier budget, on the same
8,000 TPM / 200,000 TPD / 30 RPM / 1,000 RPD free tier. This is an observed
mean, not a maximum or proof every future request fits.

Engine resolution is unchanged: it loads runtime.json, then updates
dossier_tokens from cfg.s5_dossier_budget when provided; otherwise it uses the
serving.yaml default. Thus explicit 12,000 overrides bundle runtime 4,096. A
4,096-era config remains valid. Input estimates use complete historical system
usage when available, otherwise UTF-8 bytes/3. The send-time gate estimates the
whole request, including schema/tools and system instructions; it trims only
evidence when needed, or rejects fixed overhead that cannot fit. Estimated
input + maximum output (2,048) must fit 90% of TPM (7,200). One pacing instance
covers router, rewriting, tools and answers across a job. Daily quota guard and
explicit request caps remain active. The bytes/3 fallback is an estimate, not
a tokenizer or an architectural model-context measurement.

B6 additionally approves the explicit answer.macro_excl_F5 tracking metric,
bounded to [0,1], to preserve comparisons to pre-F5 scores. LLM-reference
semantic grades are imported only from a complete fingerprint-bound verdict
ledger; no research scorer or review file is changed.

Integration: API options/config validation must read the same dossier cap and
unit from serving.yaml. Its provider path must enforce the same request gate;
Stream B's pacing adapter alone does not alter the unmerged Stream A API.

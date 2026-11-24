# Demo hardening: phase 1 diagnosis

Inspected 2026-11-23 at base commit `4b8b615`. No live model calls.

## Confirmed running-API correction

The owner subsequently checked `/v1/presets`: Recommended was the MLflow
champion **S2 / R7b / C1**, Fast was S1, and Deep read was unpublished. Therefore
the reported question used Smart search and did not invoke either router.
The route-function findings below describe the additional V2 routing gap, not
an observed routing decision in that original request. The local bundle's zero
comments and metadata-only evidence remain confirmed. See `DEMO_RUNBOOK.md` for
serving support, promotion preview and rollback commands.

## Root cause

Both `rule_route` and `route_v2` return `(None, ambiguous_id_query)` for
“Do we know about bug 1809146? If so, what's the dev comments regarding this?”.
The question therefore requires an LLM routing decision; the reported original
classifier decision cannot be recovered from source inspection. The local sample
contains bug 1809146, but its comments table has **zero rows** for that bug and
the C1 corpus contains **one metadata chunk and zero comment chunks**.
Routing to a dossier would find that metadata, but cannot supply cited developer
comments absent from this archive; a source citation proves membership, not
comment availability.

## Confirmed configuration and evidence

- Initial branch: `main`; work branch: `fix/demo-hardening`; origin is unchanged.
- YAML Recommended fallback: S8 / R7b / C1, top_k 5, context 3000,
  `is_champion: false`. Fast: S1 / R1 / C1. Neither proves the configuration of
  the original running chat. An MLflow registry can override the fallback.
- Serving `RunConfig` rejects S8v2; `Runner.run` constructs legacy `AnswerGraph`.
  Thus this checkout does not substantiate the pasted Auto-router V2 champion claim.
- Sample membership: `Firefox|Messaging System|2023|RESOLVED|INVALID`, seed 317.
- Public comments: 0 (total comments also 0). Whether comment bodies contain
  the ID is inapplicable: there are no comment chunks for this bug.
- Only chunk:
  `C1:901bf8ff27cf3928629a01c5fd013defb499e5aaa04724e51b5c3764803647d8:0`
  (kind `metadata`, bug_id `1809146`, visibility `public`).
- Its complete text: “Bug 1809146. Product Firefox. Component Messaging System.
  Status RESOLVED. Resolution INVALID. Opened 2023-01-09 12:46:24+00:00.
  Summary Refactor MesssageInspectors.”
- Original ten retrieved chunks, actual packed context and raw model JSON:
  **unavailable**; no original request trace was supplied. No synthetic model
  response was substituted for the original request.

## Verification and next phase boundaries

Bounded read-only checks used the existing `iqfm` Python: DuckDB membership,
bug/comment counts, one pass through the 14 MB C1 corpus, and direct calls to
both routing functions. Both routing functions returned the result above.
System Python lacks DuckDB; use `conda activate iqfm` for subsequent commands.
No research files, configs, contracts, model artifacts or raw data were changed.

Steps 2–5 remain unimplemented. Before selecting the smallest fix, resolve two
scope issues: the requested V2 router is inside the prohibited
`src/bugzilla_qa` tree (a serving-only adaptation can preserve it), and the
1809146 live acceptance criterion requires public comments absent from this
bundle. Do not silently collect new data or fabricate those comments.

Owner commands to inspect the running API, without model calls:

```bash
conda activate iqfm
curl --fail --silent --show-error --max-time 10 \
  -H "X-API-Key: ${SERVING_API_KEY}" http://localhost:8000/v1/presets
curl --fail --silent --show-error --max-time 10 \
  -H "X-API-Key: ${SERVING_API_KEY}" http://localhost:8000/v1/ready
```

Expected: preset JSON identifying the actual selected systems, then a successful
readiness response. A connection error means the local API is not running.
Keep credentials and full trace payloads out of committed files.

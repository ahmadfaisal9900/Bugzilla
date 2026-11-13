# Task 1 inventory and limits

| Expected | Found |
| --- | --- |
| Existing repository | `Project/`, origin `https://github.com/ahmadfaisal9900/Bugzilla.git` |
| Phase 5 freeze | `outputs/benchmark/phase05/run-65c5be3381f66811/frozen-d8ef826fbeb90d13/`; state `FROZEN_HUMAN_SIGNED`; all seven manifest artifact hashes matched in a read-only check. |
| Frozen split | The quality report states 169 benchmark questions: 34 dev and 135 test, plus six supplemental challenges. The supplied 141 test count includes those six challenges. |
| Natural rewrites | `outputs/eval_extension/bank-dacb7ca0ceb7e0ef/natural_approved.jsonl`: 110, with 51 dev and 59 test. This is a reviewed export; separate track seal status must be checked before calling it frozen. |
| 12,828 source chunks and 564 truncations | The older v1 corpus. The later v2 dense manifest reports 14,443 chunks and zero truncations. |
| Expanded 3,000/750 draft | V1 exists at `outputs/eval_extension/bank-a34d7d0a4b66911d/`; later v2 at `bank-dacb7ca0ceb7e0ef/` reports 2,489 candidates and 693 selected. Both are drafts. |
| History | `outputs/phase04/enrichment/cohort-8bb3150d29a598d8/api_enrichment.duckdb` is a separate API overlay. The canonical database's field changes are empty; never infer history from current status. |
| LLM client | The baseline uses Ollama. Task 1 adds `src/bugzilla_qa/llm/provider.py`; the owner installed Google GenAI and confirmed HTTP 404 for the requested model. |
| Source/config | `configs/eval_extension.json` identifies canonical and history databases; `src/bugzilla_qa/eval_extension/` contains corpus, retrievers, and bank code. |

The frozen quality report has zero supported historical as-of questions; the original archive date is unknown. F5 is FIXED-selected. Retrieved known-citation labels are incomplete. Public comment text may still contain personal data and needs appropriate handling.

The Gemini provider is opt-in and fixture-tested. It uses a local locked ledger, a model-specific token bucket, Pacific-date daily cap, SQLite response cache, bounded retry and JSON Schema validation. Its ledger enforces quotas only for cooperating processes sharing that ledger; other machines or applications in the same Google project also consume project quota. Crashes between a successful remote call and cache commit can cause a repeated billable request. No successful live API call has verified SDK/model support. Never put API keys in config or command-line arguments.

The owner-run ping established HTTP 404. Model listing and environment overrides are explicit, budgeted commands; no accessible replacement or successful live ping is claimed. The complete Task 1 generator, independent SQL/evidence recheck, review export and freeze integration are implemented with 20-bug fixtures. The owner subsequently completed generation and spot checks; verified freeze details follow. See `BENCHMARK_V3.md` for commands and provenance limits.

## Verified v3 handoff — 2026-11-12

v3 is **FROZEN_HUMAN_SPOTCHECKED**, freeze ID `e2207774a0f2cbad`, at
`outputs/benchmark/v3/run-289a50d1152f547a/frozen-e2207774a0f2cbad/`.
All 15 manifest-listed artifact SHA-256 values matched a read-only check.

| Family | Dev n | Test n |
| --- | ---: | ---: |
| F1 | 64 | 86 |
| F2 | 0 | 0 |
| F3 | 89 | 0 |
| F4 | 29 | 54 |
| F5 | 0 | 0 |
| F6 | 22 | 34 |
| F6H | 11 | 26 |
| KI | 42 | 123 |
| MH | 8 | 47 |
| **Total** | **265** | **370** |

Accepted coverage gaps: F2/F5 are absent from v3; F3 is absent from v3 test.
Do not generate replacement items. F2/F5 retrieval evaluation uses the original
Phase 5 and natural development tracks where present. F3/F6/F6H passage metrics
are N/A, distinct from a family that is not in a dataset.
`qrels_v3_dev.jsonl` has 265 rows (143 applicable, 122 N/A);
`qrels_v3_test.jsonl` has 370 rows (310 applicable, 60 N/A).
No v3 retrieval or answer evaluation is claimed. Earlier statements that v3
generation/review are pending describe the prior implementation handoff.

## Task 2 inventory and implementation — 2026-11-12

See `RETRIEVAL_V3.md` for the expected → found inventory. C0 is the later
14,443-chunk v2 corpus at `outputs/eval_extension/39a751ca190bbbc3/`; dense bytes
are in `bank-dacb7ca0ceb7e0ef/`, not the corpus directory. Provider is
`src/bugzilla_qa/llm/provider.py`, currently Groq, reused with generator role.
Natural dev has no F5 (22 F1, 4 F2, 2 F3, 23 F4); Phase 5 dev supplies F5.
Task 2 wraps existing algorithms and adds tokenizer-safe variants, graph/query
transforms, evaluator/cache, clustered metrics and preregistered selection.
It makes no change to frozen gold/splits or source data. Only fixture jobs ran;
real index builds/evaluation and live R7 are AWAITING_TERMINAL_RUN. Existing
owner edits to `.env.example`, EXTENDED_EVALUATION_RUNBOOK and review_natural_v2
are preserved and excluded from the task commit.

## Task 3 inventory and assumptions — 2026-11-13

See ANSWERING_SYSTEMS.md for expected → found. Both owner-run retrieval manifests
now say COMPLETE; existing selected_retriever.yaml selects R7b/C1. Current C0 is
14,443 chunks, C1 14,195, C2 14,666, not the older 12,828-chunk corpus. Provider is
Groq openai/gpt-oss-20b, not the Gemini placeholders. Native function calling is
added to that shared budget/cache/ledger interface, without rewriting it.
S2/S3 currently share R7b retrieval; this is explicitly reported. S4 checks R5
cross-encoder scores and retries with deterministic local multi-query, allowing
zero-call low-evidence abstention. Conservative byte token budgets are explicit.
Phase 5 lacks family in question files: extract only metadata; never typed gold
for inference. Natural/v3 imported aggregates use expanded-v2 partitions, distinct
from Phase 5. Old M3 remains unchanged and deprecated for this comparison.
No frozen/source edits, answer scoring, live API call or full experiment by agent.

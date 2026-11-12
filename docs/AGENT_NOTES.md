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

The owner-run ping established HTTP 404. Model listing and environment overrides are explicit, budgeted commands; no accessible replacement or successful live ping is claimed. The complete Task 1 generator, independent SQL/evidence recheck, review export and freeze integration are implemented with 20-bug fixtures. Real generation and real human spot checks remain pending. See `BENCHMARK_V3.md` for commands and provenance limits.

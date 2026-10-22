# Phase 5 — deterministic candidates, review, and freeze

**IMPLEMENTED; fixture-tested; AWAITING_USER_GENERATION_AND_HUMAN_REVIEW.** No full benchmark generation, model inference, or live request was run by the agent. The 180-item / 36-development / 144-test plan is a target, achievable only if all six families supply 30 eligible reviewed items. Actual counts and any smaller split come from the user's generated summary and signed freeze report.

## Verified input gate

The status files were stale. As the Phase 5 prerequisite, a bounded offline check verified the completed user-run Phase 4 pilot `cohort-8bb3150d29a598d8`: 50/50 histories and current-metadata responses succeeded, with 147 HTTP-200 attempts, 884 accepted field changes, zero rejected/future events, 13/50 histories with an eligible first-FIXED metric, 37/50 UNKNOWN metrics, and 17 explicit REOPENED entries. There are 7 retained archive/current field differences and one same-time history group. Nine first-FIXED cases remain before metadata-conflict and partition filtering when those disagreements/ambiguities are excluded. Reopen cases overlap other groups; do not sum their counts as bugs. No historical API relationship adapter was configured: zero parsed API link events. The 317 retained public API comments are a separate overlay, not the explanatory CSV population.

The prerequisite check rehashed six small overlay artifacts, verified all 147 cached response body hashes/identities/URLs/times, replayed history parsing, checked metrics against filing times, checked current-metadata differences, and matched the 884 DuckDB event hashes to the parsed histories. It did not rehash the 1.89-GB canonical database or scan source CSVs. The base manifest is still `0454ce48d6ed7a52973aea5474bee18304e33b65970c2c8c69dccdd0a630b663`: 196,633 unique bugs, 419,458 comments, and the seed-317 3,000-Firefox sample. Base `field_changes` stays empty; the API evidence lives in its separate DuckDB.

[configs/phase05_sources.json](../configs/phase05_sources.json) pins both runs, the Phase 4 summary hash `831252b846a70cea4594b8d422300ae3a3f22af7941c1862552156ed04d1519c`, the candidate identity, and source counts. It cannot silently follow a changed latest API run. Source snapshot time remains UNKNOWN. The primary experiment remains controlled evidence addition/refresh; no historical-status T0/T1 is established.

## Generation and independent checks

`python -m bugzilla_qa.benchmark.phase05` provides `verify-inputs`, `generate`, `prepare-review`, and `validate-freeze`. No network client is invoked. DuckDB reads only the frozen sample and its related records, uses UTC and a 512-MB budget, and streams comment batches. Original CSVs are never opened.

| Family | Eligible scope and validation |
|---|---|
| F1 | Component/status/resolution recorded in broad metadata, qualified by archive identity and unknown snapshot date. Values and content hashes must agree with retained normalized source fields. Product is already specified as Firefox, so it is not used as a trivial lookup answer. Priority is not retained canonically and is skipped. |
| F2 | Conflict-free ordered pilot histories, with no same-time ambiguity. Earliest explicit resolution-to-FIXED is checked through overlay SQL, Python UTC subtraction, and the Phase 4 metric. Otherwise explicit REOPENED counts are checked independently, or a maximum six insufficient-history questions are eligible. An absent transition yields UNKNOWN; no initial state, latest-change duration, or work-hours inference is synthesized. |
| F3 | Exact distinct-ID counts in explicit, disjoint eligible sample partitions. Filing-year filters use UTC. SQL COUNT(DISTINCT) must equal an independent Python set count; the SQL, parameters, denominator, exclusions, membership manifest, source hashes, and matched-ID hash are preserved. Whole-denominator answers disclosed by the question are skipped. |
| F4 | Complete numeric target sets for a recorded relation, checked against SQL and retained metadata links. URL-only targets are explicitly excluded. All parent/target IDs must belong to one split; crossing cases are skipped, not truncated. Historical target status and edge validity are UNKNOWN. |
| F5 | Public available CSV comments only, on FIXED-resolution parents. A short extractive clause containing a possible reason marker creates a candidate, never verified causal gold. Excerpt/body hashes and source provenance are checked; conflicting comment versions are excluded. Every retained claim needs human source review. No generalization to open/non-FIXED explanations is supported. |
| F6 | Measured engineer-hours or the exact original CSV export timestamp cannot be established from the specified evidence. Schema/null assertions and an explicit effort-statement screen prevent obvious accidental answers. Labels make no claim about all possible external knowledge. |

Metadata-conflict parents are excluded across families. The canonical schema does not retain issue type: enhancement coverage is UNKNOWN, and the population is described as tracker issues, not defect-only bugs. Reviewers may record `issue_type_observed`; it is not silently inferred from text or summary wording.

Seeds use SHA-256 ordering, with no shared random state. Bug IDs hash into development (one fifth) or test (four fifths). Relation targets stay in the parent's partition, and aggregate populations use the same rule. `population_manifest.json` records actual eligible membership; scope/denominator labels include conflict exclusions. Separate development/test wording templates and one agent-authored challenge wording per supported family prevent tuning solely to a single form. Challenges stay with their test parent and require human wording/source review; they are reported separately from the 180 target. These checks reduce contamination, but do not claim that templated questions are equivalent to naturally authored questions.

## Terminal order

From the existing Project root, using the Python environment with free DuckDB 1.4.4:

```bash
bash scripts/run_phase05_generate_benchmark.sh --dry-run --seed 317
bash scripts/run_phase05_generate_benchmark.sh --seed 317 --resume
bash scripts/run_phase05_prepare_review.sh --seed 317 --resume
```

An optional bounded trial uses `--limit 2`; it produces a separate marked prefix that can never be frozen. `--f5-target 10` is an optional reduced manual workload; use the same generation options on resume. Output directories are versioned by source pins, seed, limits, and code hashes. A completed matching generation is skipped on resume; an interrupted generation can be deterministically restarted. No previous benchmark or user review is deleted.

Expected ignored outputs are `outputs/benchmark/phase05/run-<identity>/` containing `manifest.json`, `candidates.json`, `challenge_candidates.json`, `population_manifest.json`, `input_verification.json`, `summary.json`, and checkpoints. Logs have UTC timestamps under `outputs/benchmark/phase05/logs/`. Summary coverage reports per-family/type/split counts, question-parent outcome distributions, and shortfalls. Optional human-observed issue-type counts in the frozen report refer only to signed reviewed items, not the full population. Actual historical cutoff-question coverage is zero; the roadmap's 48-cutoff target is not claimed on these inputs.

## Small human review sheet

Open local `review.html` and edit `review_queue.csv`; the HTML is a readable rendering, not a submission form. It contains questions, candidate gold, short email/handle-redacted evidence excerpts, row hashes, source links, and aggregate SQL/parameters for inspection. It remains ignored: public text can still include personal names, so source review also checks privacy. Tracked docs contain aggregates only.

Review all rows marked `required=YES`: every retained F5 candidate, a seeded 20% of each F1–F4 family, up to six F6 labels (six when available), and every retained challenge. These are review targets, not a claim of perfect certainty. Optional second-rater rows are marked separately; disagreement needs an `ADJUDICATED` note. No agreement statistic is claimed without actual second ratings.

For a source-checked row fill `decision` with `APPROVE`, `CORRECT`, or `REJECT`, plus `reviewer`, timezone-aware `reviewed_at_utc`, and `source_checked=YES`. F5 additionally requires `rationale_present=YES`: a keyword match is insufficient. If the comment does not support a reason, reject the candidate. Corrections use `corrected_gold_json` with claims of the form `{"text":"reviewed claim","evidence_id":"cited comment key"}` inside `{"type":"supported_explanation","claims":[...]}`. Factual corrections inconsistent with deterministic recomputation block freeze and require fixing the source/validator and regenerating. A challenge's corrected gold must agree with its reviewed parent; `corrected_question` can revise challenge wording.

Run prepare-review with `--resume` after rejections: it preserves review edits and recalculates the spot-check targets over retained items. Newly required rows must be checked. Unreviewed rows remain PENDING in the sheet. Non-selected factual rows are labeled AUTO_VALIDATED/NOT_SELECTED, never individually human-verified.

Finally fill `review_signoff.json` with a reviewer and UTC review time, set `approve_freeze=true` and `acknowledge_actual_reduced_coverage=true` only after checking the actual counts and mandatory reviews. This is human sign-off; scripts never approve rows or the sign-off automatically.

```bash
bash scripts/run_phase05_validate_freeze.sh --dry-run --seed 317
bash scripts/run_phase05_validate_freeze.sh --seed 317 --resume
```

The terminal freeze rehashes the canonical database (a sequential 1.89-GB read, potentially minutes on slow storage), validates the compact manifests/caches, and independently rebuilds factual gold. It refuses prefixes, missing reviews, altered sources, future evidence, duplicate questions, changed gold, and unsigned F5. It writes `frozen-<identity>/` with a quality report, checksummed manifests and separate `dev`, `test`, and `challenge` question/gold JSONL files. A `FROZEN` pointer prevents replacing a locked test with edited reviews; an amendment needs a new generation version. Resume validates the existing release rather than overwriting it.

## Inference boundary

Only `*.questions.jsonl` is an inference input: its keys are qid, question, and factual scope. Typed gold, SQL, template IDs, review notes, excerpts and evaluation checks stay in `*.gold.jsonl` and review artifacts, outside model prompts/logged retrieved context. Build retrieval evidence from source records, never benchmark gold or review sheets. M3's later audited intent templates must be implemented/tuned using development data only; no canonical gold SQL or question template ID may be passed to inference. Test and challenge gold are for final evaluation and authorized human source review, never method tuning.

## Bounded validation

The fixture suite uses 20 synthetic parents, synthetic history/cache responses and quoted source text. It checks all families, deterministic UTC math/year filters, relation sets, metadata-conflict exclusion, disjoint populations, candidate/answer-hint/future-context rejection, mandatory F5 review, interrupted/prefix guards, review preservation, freeze/resume checksums and inference-file separation. No fixture approval is a real human annotation or corpus result. Full generation and human review remain pending; no method experiment has run.

Latest bounded check: **5 tests passed in 8.4 seconds**. The 20-parent synthetic fixture generated **30 candidates (5 per family), 6 development / 24 test, plus 6 challenges**. Its approvals/freeze are simulated test operations; they establish no real source review or corpus benchmark count.

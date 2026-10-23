# Phase 5B — assisted review preparation protocol

## State and preserved generation

The user-run Phase 5 generation is present at `outputs/benchmark/phase05/run-65c5be3381f66811/`. It contains 169 benchmark QIDs, 6 separately identified challenges, seed 317, and the frozen population partition manifest with 592 development / 2,408 test IDs. The candidate file SHA-256 is `3e3d0d8002c5fce2ef075fb8ded5611318954d2ffc808efb9994f9bdf39dfa38`; the challenge file SHA-256 is `f668c668b96a1b16ec909fe37f4518d71e1c527cd7a7965f5b16e4a6a365f6b6`. The current `review_queue.csv` and the existing `review_queue.pre_review_backup.csv` are byte-identical, each SHA-256 `6d2030a6fa0d4abba1a4a6ab09a68465a6f12beb31e9056056ca67b807cb430c`.

The assisted-preparation tool reads these files without changing them. It does not rerun Phases 2–4, regenerate candidate answers, edit review decisions, call an API, or freeze the benchmark. Its output is ignored under `outputs/benchmark/phase05/agent_review_prep/`. A full run is a user-terminal task; agent fixture tests cover at most ten cases. No full packet audit or F5 judgment has been run in the agent session.

## What the tool distinguishes

- **Deterministic validation** checks exact canonical/source fields, saved Phase 4 API history and UTC arithmetic, F3 SQL results against an independent Python ID set over exactly the saved 592/2,408 partitions, complete F4 target sets, and F6 answerability within the specified archive/API evidence. Each item receives `PASS`, `FAIL`, or `UNKNOWN`, with source paths, identifiers, and hashes. A missing history response is `UNKNOWN`; only a verified, parsed response with a valid empty history supports zero observed transitions. The empty Phase 3B `field_changes` table does not invalidate the separate Phase 4 history overlay.
- **F5 packet heuristics** flag possible short fragments, log/code, malformed URLs, trivial “because” uses, multiple readings, or missing/contradictory rationale. These are prompts for attention only; they do not reject candidates or substitute for reading the complete relevant comment and its context.
- **Interactive Codex recommendations** may suggest `APPROVE`, `CORRECT`, or `REJECT`, with a short rationale and evidence references. They are model-generated advice from the logged-in interactive agent, not an independent annotator or source verification. They are not written into `review_queue.csv`.
- **Human signoff** remains authoritative. A person checks Bugzilla source pages, candidate comment rationale, privacy, corrections/rejections, challenge wording, and the global signoff. No item becomes `SIGNED_SOURCE_REVIEW` from a deterministic pass or a Codex recommendation.

## Exact review queue schema

The generated CSV has these 21 columns, in this order:

```text
qid,family,split,required,optional_second_rater,question,suggested_gold_json,evidence_json,query_json,rubric,decision,reviewer,reviewed_at_utc,source_checked,rationale_present,corrected_gold_json,corrected_question,note,issue_type_observed,second_reviewer,second_decision
```

The first ten columns are generated inputs. The eleven editable columns are `decision`, `reviewer`, `reviewed_at_utc`, `source_checked`, `rationale_present`, `corrected_gold_json`, `corrected_question`, `note`, `issue_type_observed`, `second_reviewer`, and `second_decision`. The packet tool stores recommendations separately and never edits these cells.

### Primary decision values and freeze requirements

- `decision`: exactly `PENDING`, `APPROVE`, `CORRECT`, or `REJECT`. `PENDING` blocks a required row. A required `REJECT` removes the item; rerun `prepare-review --resume` so mandatory review targets are recalculated for retained items.
- For `APPROVE` or `CORRECT`, freeze requires a nonempty `reviewer`, `source_checked=YES`, and a timezone-aware ISO-8601 `reviewed_at_utc`.
- For `CORRECT`, `corrected_gold_json` must contain valid JSON. The exception is a challenge wording correction: `corrected_question` can satisfy the row-level correction requirement. Challenge gold still has to equal the reviewed parent gold.
- Factual F1/F2/F3/F4/F6 corrections cannot change recomputed gold; the freeze validator rejects them. Fix the source or validator and generate a new version if evidence proves a factual error.
- F5 `APPROVE` or `CORRECT` requires `rationale_present=YES`. Its corrected gold must have type `supported_explanation`, at least one nonempty claim, and each claim must cite an evidence ID from that question. Contributor identities containing `@` are rejected in the gold. The reviewer must decide whether the comment actually states the proposed rationale; a keyword or model recommendation is insufficient.
- `REJECT` is skipped before row-level signature checks in the current validator. For a useful audit trail, record reviewer, UTC time, source check, and a concise rejection reason in `note` even though the code does not require those fields for a rejected row.
- `issue_type_observed` is an optional human observation, not a generated label or a required defect-only claim.

### Second-rater behavior in the existing validator

Second review is optional. If `second_reviewer` is nonempty and `second_decision` differs from the primary decision, the validator requires the substring `ADJUDICATED` in `note`. The code does not independently enum-check `second_decision` and accepts blank when no second decision is entered. For a clean record, use blank or one of `APPROVE`, `CORRECT`, `REJECT`; document any disagreement and its adjudication in `note`. No agreement statistic is produced by filling these fields.

### Global signoff JSON

`review_signoff.json` is generated with these fields: `reviewer` (string), `reviewed_at_utc` (initially null), `approve_freeze` (initially false), `acknowledge_actual_reduced_coverage` (initially false), `source_population` (informational string), and `attestation` (informational string). Freeze requires a nonempty reviewer, a timezone-aware `reviewed_at_utc`, and both booleans set to JSON `true`. The other two fields are not enforced by the current validator; keep them accurate and do not sign until required row reviews and coverage checks are complete.

## F5 review rubric

All retained F5 rows require human review because the candidate population is selected from public comments on FIXED-resolution bugs. A packet includes the question, suggested claim, full sanitized comment when it is within the size bound or a bounded context window around the claim, comment ID/key and hashes, source URL, event/observed/ingested timestamps, and explicit public-privacy provenance. Private or unknown-privacy bodies are excluded. Email addresses, handles, signatures, and likely name/proper-noun tokens are scrubbed heuristically; the output remains local and ignored. Inspect the source page before sharing any packet outside the project.

For each claim, check that it is stated in this comment, addresses the question, preserves uncertainty and negation, and is not merely adjacent code, a path, a link, a proposed fix, or an unrelated “because” clause. Separate contributor-stated rationale from reviewer interpretation. If the comment does not support a causal reason, reject it or correct the claim to the narrower supported statement. Do not generalize these explanations to unresolved bugs.

Human review is still required for every retained F5 gold, every retained challenge, a seeded 20% of F1–F4, and up to six F6 labels. The automated validator does not turn these targets into human decisions.

## Commands and outputs

From the existing `Project/` root, first inspect the plan:

```bash
bash scripts/run_phase05_agent_review_prep.sh --dry-run --batch 10
```

Then run the full local packet preparation in the user's terminal:

```bash
bash scripts/run_phase05_agent_review_prep.sh --batch 10 --resume
```

Optional `--limit 10` creates a separate marked prefix run for a bounded terminal smoke; it does not stand in for the complete packet set. `--resume` only reuses checksummed packets for identical inputs. The runner timestamps its log under `outputs/benchmark/phase05/logs/`.

Expected files are `manifest.json`, `checkpoint.json`, `summary.json`, `validation_report.json`, and `packets/batch-NNNN/<qid>.json` under the prep run shown by the command. The report contains per-QID validation states/sources and F5 flag totals/QIDs. Do not edit or replace the original queue from a packet. The current queue checksum and backup checksum are recorded in the output manifest and summary.

With the current code and inputs, the dry-run resolves the full `--batch 10` packet directory to `outputs/benchmark/phase05/agent_review_prep/run-65c5be3381f66811-f162504b3b0f/packets/`; the first review batch is `.../packets/batch-0001/`.

## Prompt 5B — interactive Codex recommendation, one batch at a time

After the full packet-preparation run succeeds, give the logged-in interactive Codex agent one batch directory at a time (start with `batch-0001`) and use this prompt:

> Read `docs/PHASE05_ASSISTED_REVIEW_PROTOCOL.md`. Review only the F5 packet JSON files in `outputs/benchmark/phase05/agent_review_prep/run-65c5be3381f66811-f162504b3b0f/packets/batch-0001/`. For each F5 QID, give a **Codex recommendation only**: APPROVE, CORRECT, REJECT, or NEEDS HUMAN SOURCE CHECK; summarize the exact rationale stated in the supplied comment, cite the comment ID/hash, note ambiguity/negation/context and any heuristic flags, and say whether the suggested claim is supported. Do not edit `review_queue.csv` or `review_signoff.json`, do not browse/fetch external content, do not call an API, do not claim independent human annotation, and do not freeze the benchmark. Keep names/emails redacted. Stop after this batch and wait for the human reviewer.

The project owner checks the Bugzilla page and packet before transferring any recommendation into the editable queue. Repeat by batch as capacity allows. The agent must stop before judging all F5 rows or freezing unless the owner explicitly asks for another batch.

# S evaluation

## Start here

The normal evaluation command generates `START_HERE.html` and `REVIEW.csv` automatically after scoring, including partial runs. Open `outputs/evaluation/phase11/START_HERE.html` in a browser by double-clicking it, or run `Start-Process ".\outputs\evaluation\phase11\START_HERE.html"` from the repository root. The page is self-contained and needs no server. Both files are explicitly allowed through `.gitignore` for sharing. It contains all 720 saved responses from the 80-question pilot. The default view shows only responses needing review. Plain fields show the method answer, its explanation, the reference answer, reference source excerpts and the evidence the method actually received. `Needs your grading`, `Correct (automatic)` and `Wrong (automatic)` are shown directly.

There are 81 answer decisions and 306 evidence checks. The 81 are part of those 306 responses, not additional questions. `Answer and evidence` asks for both decisions. `Evidence only` leaves answer grading unchanged. Method names are hidden initially; the checkbox reveals them and the comparison tables. Browser draft decisions are separate from official scores until imported.

Use the decision controls and click `Save decision and continue`. Download the review CSV before closing or moving to another computer. Alternatively edit the single `outputs/evaluation/phase11/REVIEW.csv` in Excel. It combines all three collections, uses readable text instead of nested JSON and hides method identities. Edit only `answer_verdict`, `grounding_verdict`, `reviewer` and `note`. Leave `answer_verdict` blank for `Evidence only` rows. Do not change question IDs, answers, references or source text.

```powershell
.\scripts\run_phase11_evaluation.ps1 --review
.\scripts\run_phase11_evaluation.ps1 --import-review "$env:USERPROFILE\Downloads\REVIEW_completed.csv"
```

The first command rebuilds the page and CSV from saved results without model requests. Existing CSV decisions are retained and backed up. The second imports a downloaded review file, checks IDs and unchanged answer content, preserves previous review queues and refreshes the scores and page. Partial reviews are allowed; blank fields do not erase existing decisions. Saved comparisons remain separate for the overlapping collections. Imported decisions require reviewer initials and a source check note. The original raw predictions, references and scoring rules are unchanged by this presentation.

The default comparison includes S0 through S8. All systems use the same question roster and configured Groq model. The answering graph produces predictions; separate Python code scores them. Explanations and evidence support require human review. S3 currently duplicates S2's retrieval treatment and remains in the comparison with that limitation disclosed.

## Windows commands

The fixed 80-question pilot reuses existing answers and automatically reads available keys from `.env`:

```powershell
.\scripts\run_phase11_evaluation.ps1 --shared-source --pilot-size 80 --enable-llm
```

Repeat this command to resume. Append `--dry-run` to preview. The selection is saved in `outputs/evaluation/phase11/pilot80_selection.json`: all 34 original development questions, 10 natural rewrites stratified by family, 17 bug identification questions, all eight multi-hop questions and all 11 hard abstention questions. These are existing official development questions, not newly generated references. Selection uses question IDs and clusters, never method scores. Each of S0 through S8 receives the same 80 questions, giving 720 final answer slots. Results remain separate for the three collections because their facts overlap. This is a development pilot, not a hidden test result.

The runner discovers `GROQ_API_KEY` and optional `GROQ_API_KEY_2`, `GROQ_API_KEY_3` and `GROQ_API_KEY_4` automatically. Missing entries are skipped and duplicate credential values are used once. Environment variables override matching `.env` entries. Optional `--api-key-env NAME` or `--api-key-envs NAME ...` can restrict the selection. The default total cap is 900 HTTP attempts per invocation, shared across the keys; use `--max-requests` to override it. Run only one evaluation controller at a time.

The evaluation worker injects the same Groq provider with separate account ledgers and cooldowns, rotating credentials between calls. The model, prompts, response cache, answer parsing, repair rule and prediction identity remain unchanged. Its orchestration code checksum and credential names are recorded per batch. Existing key 2 usage is conservatively inherited from the old combined ledger, which is preserved. Other keys use separate local records; Groq still enforces any preexisting remote usage. Requests remain sequential, with the repository pacing applied separately to each account. A quota, authentication or connection failure can move to another account; an invalid model answer follows the existing repair rule and is not replaced through failover. The invocation cap includes retries and tool calls across all selected keys. Token limits may stop the run sooner. Human review remains required after automatic scoring.

The routing fix treats Groq `json_validate_failed` responses as invalid model output. S8 can repair its route once; this consumes the same single repair budget as answer repair. Two invalid routes produce a terminal method failure, while a transport failure is saved as unresolved. The fix creates prediction version `run-10ecc94f91603cbe` for Phase 5. It inherits 305 resolved predictions from `run-3c312201eeaba81e` after checking that only the provider error classification and graph error handling code changed. Original answer content and failed attempt records are preserved. `REUSED_PREDICTIONS.json` and each imported row record the original run, configuration and checksums. This is disclosed reuse across an error handling patch, not a fresh execution of those answers under the new code.

The official development datasets are now available: Phase 5 has 34 questions, natural has 51 and v3 has 265. To use them with the existing shared 3,000-bug export:

```powershell
.\scripts\run_phase11_evaluation.ps1 --shared-source --dry-run
.\scripts\run_phase11_evaluation.ps1 --shared-source --enable-llm --max-requests 900
```

To select the second credential, append `--api-key-env GROQ_API_KEY_2`. The runner reads it from `.env` or the process environment without changing the file. This keeps the same model configuration, saved answers and request accounting. Existing provider cooldowns remain in effect.

This verifies the source package, development evidence hashes, declared aggregate populations, lifecycle values and full public-record coverage in the local index. It checks the reconstructed history against the original 50-history summary, including exclusion flags. It fixes a new S4 threshold from all 350 development retrieval scores before inference. Progress is resumable with the same command. Results remain separate by dataset; 350 is not a pooled statistical sample.

The local index has 14,191 chunks, compared with 14,195 recorded for the owner's original C1 index. All 12,509 public source records are represented locally; chunk text is checked against sanitized source offsets. The original index is absent, so the four-chunk difference cannot be reconciled against its files. Reports describe the declared retrieval selection applied to a reconstructed runtime, not reproduction of the owner's exact runtime. Frozen questions and answers are unchanged. This mode is development only.

One recorded format repair is allowed per answer for every system, including S7. A Groq rejection of model-generated tool arguments uses that rule; rejected arguments never execute. A terminal invalid answer counts as wrong and is not retried on resume. Quota, authentication and transport failures stop the invocation and remain unresolved. Reports include repair counts and successful answers after repair. Cells with fewer than ten independent clusters receive descriptive results and intervals where possible, without significance tests.

Install `requirements-answering.txt` in the repository `.venv`. Put `GROQ_API_KEY` in the ignored `.env`. The PowerShell wrapper selects the repository Python environment automatically. Linux and Git Bash use `bash scripts/run_phase11_evaluation.sh` with the same arguments.

The current workflow uses the official question bundles. The earlier generated-question sample builder and its separate runner have been removed. Shared-source mode still uses the existing verified prepared index and source runtime; their recorded paths are retained so saved prediction provenance remains valid. Receive that runtime bundle alongside the source data on a fresh checkout.

For the full restored Phase 5, natural and v3 bundles:

```powershell
.\scripts\run_phase11_evaluation.ps1 --dry-run
.\scripts\run_phase11_evaluation.ps1 --enable-llm --max-requests 900
```

The real bundle must preserve the paths in `configs/answering.yaml`, `configs/retrieval_v3.yaml` and `configs/eval_extension.json`: database, verified history, frozen questions/gold, public corpus, pinned retrieval weights, indexes and caches. Question files alone cannot run retrieval and database systems. Shared-source mode verifies its prepared index and fixes S4's tenth-percentile development retrieval threshold before inference. This threshold is not a correctness probability.

Repeat the same command to resume. The request cap is shared across systems, datasets, transformations, retries and tool turns. Token quotas can stop execution sooner. Batches interleave question families and include every selected system, with S0 first. Successful predictions and terminal invalid model answers are not repeated. Provider failures remain pending and stop the invocation; inspect the diagnostics before retrying.

The present model is Groq `openai/gpt-oss-20b`. Repository limits allow three requests per minute and at most 900 requests per quota day. Transformation, routing and tool calls add requests beyond the final answer count, so completion can span several quota windows. A partial invocation is saved progress, not a completed comparison. Do not change model, prompts, indexes or generation code during a run; changed identities produce a separate version.

`--limit 2` selects at most two pending questions per dataset for a live check; scoring still reports full-roster coverage. `--datasets phase05` selects the original 34 development questions. Use `--systems` only to explicitly request a subset; all nine are included by default.

If predictions already exist, avoid generation:

```powershell
.\scripts\run_phase11_evaluation.ps1 --score-only --datasets v3 --prediction-run v3=outputs/predictions/v3/dev/run-YOUR_RUN
```

Repeat `--prediction-run DATASET=PATH` for several datasets. Scoring saved predictions makes no provider calls.

## Reports

`outputs/evaluation/phase11/latest.json` points to the dataset reports. Each evaluation folder contains:

| File | Contents |
|---|---|
| `report.md` | System comparison followed by per-family results |
| `comparison.csv` | Coverage, macro accuracy, pending reviews, abstentions and failures |
| `scores.jsonl` | Individual grades, numerical errors and set precision/recall/F1 |
| `summary.json` | Cluster intervals, paired comparisons, Holm correction, baseline, requests, tokens and latency |
| `review_queue.csv` | Blinded explanation and grounding review |
| `review_key.csv` | System mapping; keep away from reviewers |
| `manifest.json` | Source, prediction and scorer fingerprints |

Missing predictions and execution failures count as unsuccessful outcomes on the full roster. Missing or unresolved provider work produces PARTIAL. Terminal invalid answers remain failures even when collection finishes. Human-pending cells do not receive a final accuracy. Macro accuracy requires complete prediction coverage and uses the same fully graded families for every selected method. Explanations enter that average only after human grading for every method. An always-abstain baseline makes unsupported guessing and abstention behavior easier to compare.

Fields use normalized exact match. Counts are exact. Durations use explicit hours or days and the existing one-hour tolerance; ambiguous units need review. Relationships require complete target sets and also report partial precision/recall/F1. KI accepts one permitted ID in the answer or bug_ids; conflicting or multiple IDs fail. Its field form also requires the correct value and acceptable bug identity. Structured MH answers must parse as JSON with the required keys and complete sets. The scorer does not repair prose or change reference answers.

## Human checks and statistics

F5 always needs human judgement, including insufficient-evidence answers. Grounding checks cover all successful F5 responses, up to two other responses per system/family, and answers flagged for human marking. A valid citation ID does not establish that its text supports the claim.

For F5, mark an answer correct only when it addresses the requested reason and every material claim is explicitly supported by the retained source. Do not infer a cause from event order or fill gaps in truncated comments. An insufficient-evidence answer needs the same source check. Record ambiguous evidence as UNCLEAR rather than assuming support.

Recorded latency includes retrieval, model setup and quota waits. Shared response caches also affect charged requests and latency; cache hits are reported separately. These are observed workflow costs, not isolated model-speed measurements. Missing provider usage is flagged, not treated as zero billed tokens.

Reviewers inspect the cited public source text from the matching corpus/database. Mark answer_verdict CORRECT or INCORRECT where human grading is needed. Mark grounding_verdict SUPPORTED, UNSUPPORTED, UNCLEAR or NOT_APPLICABLE. NOT_APPLICABLE is for an abstention without factual claims. Add reviewer initials and a source-check note. Rerun scoring to import the sheet; decisions in the same evaluation folder are preserved. Add `--reviews PATH_TO_COMPLETED_CSV` to import an earlier sheet while selecting one dataset. Content-bound IDs prevent changed questions, references or answers from inheriting old decisions. No AI judge replaces human review.

Results stay separate by dataset and family. Bootstrap intervals use 10,000 parent/cluster draws at seed 317. Paired cluster sign-flip tests use exact enumeration for up to 12 clusters and 10,000 draws otherwise. Holm correction covers the reported method/family tests within each dataset. Intervals are unadjusted. Fewer than two independent clusters means no interval; fewer than ten means no significance test. Related wording variants and overlapping datasets are not pooled as independent observations. S8 is composite; ORACLE is diagnostic.

Final test execution requires `--split test --confirm-locked-test` only after methods, model, prompts, thresholds and scoring rules are finalized. Test scoring verifies the matching answering-run access receipt. Shared-source preparation does not read locked test questions or reference answers.

## Offline unit fixture

The old 12-question fixture tests only the scorer with 60 predefined answers. It is a test fixture, separate from actual model inference:

```powershell
.\scripts\run_phase11_evaluation.ps1 --fixture
$env:PYTHONPATH = "src"
.venv/Scripts/python.exe -m unittest discover -s tests -p test_phase11_evaluation.py -q
```

# Stream B backfill mapping and operations

## Scope and source inventory

`pilot125` is a **PILOT subset**, not full-dev results. All work is dev-only;
source CSV/HTML, raw predictions, questions, gold and reviewer identities are
never uploaded as tracking artifacts. Frozen sources/research code are unchanged.

| Expected → found | Adapter |
| --- | --- |
| `feature/mlops` → checked out | Existing root/origin retained; no pushes |
| Contracts → `src/bugzilla_serving/contracts/` | Reuse names and canonical hashes |
| Answer results → `outputs/evaluation/phase11/pilot125/REVIEW.csv`, `START_HERE.html` | CSV rows joined by review_id to saved HTML metadata; never execute HTML/JS |
| Exact pilot ledgers → no references/manifests locally | Auto selects review-only; never substitute nearby partial smoke runs |
| Retrieval results → two COMPLETE dev `outputs/retrieval/v3/run-*/summary.json` | 24 unique retriever/corpus plans |
| Environment → Conda `iqfm`, Python 3.11 | Existing MLflow 2.22.1, PyYAML 6.0.2, Pydantic 2.11.7, pytest 8.3.5, Ruff 0.11.13; no installs |

Observed CSV: 358 rows, datasets natural=83, phase05=149, v3=126.
Current saved **answer_verdict fields are all blank**: 151 Correct (automatic),
121 Wrong (automatic), 86 awaiting grading. F5 has 54 rows, all pending. The
embedded HTML contains 1,125 rows (=125 questions ×9 systems); review-only uses
only the 358 CSV rows, not the entire HTML population. No completed human answer
review is claimed. Grounding verdicts are not answer correctness.

## Answer mapping

| Source field or calculation | Contract output |
| --- | --- |
| HTML method/family/question_id joined on CSV review_id | system/family/qid identity; no text artifact |
| CSV answer_verdict CORRECT/INCORRECT, nonblank reviewer + source-check note | Human answer verdict; family tag `scorer.<FAMILY>=human-review` |
| CSV current_result exactly Correct/Wrong (automatic), absent human answer verdict | Saved automatic binary score; F5 excluded without human answer verdict |
| Missing/pending/ambiguous verdict | Excluded from score denominator; `pending_n`, `source_n`, `scored_n`, `human_n` in per_family.csv |
| Fraction CORRECT among scored system/family rows | `answer.<FAMILY>.score`, `.n` = scored rows |
| Unweighted mean over families with scored rows | `answer.macro`; pending tag prevents automatic promotion |
| Dataset names actually present | `datasets` tag; individual family coverage in artifacts |
| No rows for a family | No family metric (not in dataset) |
| Present family, all rows pending | `.n=0`, `.pending` holds the known count; score omitted |

### Modes and provenance

Default `--mode auto` requires exact references for every dataset before choosing
`ledgers`. References come from original `latest.json` evaluations' manifests,
or an explicit local `provenance.json`:

```json
{"prediction_dirs": {"phase05": "outputs/predictions/phase05/dev/run-EXACT", "natural": "outputs/predictions/natural/dev/run-EXACT", "v3": "outputs/predictions/v3/dev/run-EXACT"}}
```

Do not invent these references. `--mode ledgers` fails clearly if they are absent.
This path reuses partner `evaluation.systems.load_items`, `select_predictions`
and `grade`; checks frozen dev/source/prediction hashes; binds every human
verdict to its exact review ID computed from item, answer, config and context.
The mixed natural export is hash-checked as bytes; only dev-marked rows are staged
and decoded for the partner loader. Locked test gold objects are never parsed.
Where the HTML roster is present it defines the full pilot question/system scope;
the CSV supplies human overrides. No bootstrap/scoring API calls or model runs.
Snapshot settings and identity.json (when present) take precedence over defaults;
the identity hash and snapshot agree before using archived LLM/selection settings.

Ledger mode maps:

- Per-family partner CORRECT/INCORRECT to binary correctness (not relation-set F1).
  Signed human verdicts remain source-bound. Under the requested balanced-pending
  protocol, execution/malformed-output failures are incorrect even when the source
  scorer requests clarification of an unparseable duration unit. Genuine review
  pending qids (dataset + qid) are excluded identically for every system. Their
  counts are `answer.<F>.pending`; present families have `.n`, including zero.
- `fail.rate`: missing, execution-failed or malformed-output predictions divided
  by the shared eligible pilot question count. Ordinary wrong answers/valid
  abstentions are not execution failures. Source verdict/reason and the applied
  denominator decision are retained in the aggregate-safe `score_audit.jsonl`.
- `abstain.correct_rate`: abstained / records with explicitly unanswerable gold;
  `abstain.false_rate`: abstained / explicitly answerable records. Empty
  denominators omit metrics. Gold kind determines this, not a family guess.
- `cost.llm_calls`: sum saved call_count including failed attempts; token metrics
  sum saved input_tokens/output_tokens only when all attempts supply them.
  Reported tokens are saved-response usage, not a billing estimate for failed
  requests with missing usage. `latency.*`: saved non-cache attempt latencies,
  sorted p50 index n//2, p95 min(n-1,floor(.95n)), matching partner convention.
- Source SHA-256s and per-family denominators are artifacts; no raw predictions.

### Why F2 denominators differed; balanced-pending-v1

The source scorer returned `NEEDS_HUMAN/ambiguous_duration_unit` for 32 F2
system/question records (24 natural, eight Phase 5); these were excluded on a
per-system basis. Two natural F2 records were execution failures, already graded
incorrect. The new user-requested protocol treats unparseable duration outputs
as incorrect/failures. The remaining shared pending set is exactly six F5 qids.
All nine systems therefore have 119 scored + six pending out of 125 pilot qids.
Every family denominator is identical: F1=21, F2=8, F3=15, F4=19, F5=0 (six
pending), F6=13, KI=24, MH=8, F6H=11. Macros cover eight scored families only.
Research grading code, frozen gold and original predictions remain unchanged.

### MH/F3 diagnostics from saved S7 predictions (dev only)

All questions below refer to recorded archive fields, not live state; snapshot
date is UNKNOWN. These are observed saved answers, not newly generated answers.

| Family / qid | Question and scope | Saved S7 answer / tool trace | Frozen gold | Source verdict |
| --- | --- | --- | --- | --- |
| MH `v3_13b1d27d94419f10879fac40` | How many cohort bugs explicitly blocking #1769546 are unresolved? Downloaded Firefox cohort, seed 317. | Answer `[0]`; `get_links(1769546, blocks)` returned `targets=[]`. | Scalar `0` | INCORRECT / integer: list is not a scalar number. |
| MH `v3_0b91748d0094c32d222d04bd` | Within the downloaded Firefox cohort, what does #1874162 depend on, and which targets are resolved FIXED? | Abstained (`null`). `get_links(1874162, depends_on)` returned 1873766, 1874176, 1874184, 1874189; next `get_bug_fields(1873766, [resolution])` returned `known=false`, outside indexed cohort. No fields were fetched for in-cohort target 1874184. | `{"depends_on":["1874184"],"resolved_fixed":["1874184"]}` | INCORRECT / false_abstention. |
| F3 `natural_14dea18947f819a165f2` | How many Security-component bugs in the seed-317 dev partition of 882 distinct bugs? Year means filing year. | `count_bugs(component=Security, scope=cohort)` returned count 29, partition=dev. Final answer `[29]`. | Scalar `29` | INCORRECT / integer: tool got the count, final answer had wrong shape. |
| F3 `q_25ca7696bb093bcc4eb6` | How many distinct Firefox bugs have component=Search in the eligible seed-317 Phase 5 dev partition, denominator 592? | Abstained (`null`); zero tool steps, no count call. | Scalar `17` | INCORRECT / false_abstention. |

Sources: `outputs/predictions/{natural,phase05,v3}/dev/` exact runs resolved from
pilot125 manifests (natural run-022290e9f5c5f6a3, Phase 5 run-10ecc94f91603cbe,
v3 run-bd6b90ea33a3d4b0), S7.jsonl; hashes remain pinned in backfill provenance.

`evaluation/systems.py:grade` and its `number` helper reject singleton arrays for
integer answers. No permissive singleton unwrapping was introduced. Structured
MH comparison already ignores target-set order and normalizes numeric/string IDs
through `id_set`; a fixture verifies that. S7's eight MH cases are seven false
abstentions plus one malformed scalar answer, not a set-order mismatch. Its
15 F3 cases are six false abstentions plus nine integer comparisons (one correct).
In particular, saved tools successfully count the dev partition: lack of a dev
filter is not the blanket cause. The unchanged count tool explicitly handles
declared Phase 5/expanded-v2 partitions and distinct canonical IDs.

There is also a directed-relationship limitation: benchmark blocking-count gold
uses incoming `blocks` edges (target=root); `get_links(root, blocks)` retrieves
outgoing edges. Consequently an empty outgoing list does not establish that
there are no incoming blockers. Dependency tools can return targets outside the
cohort, and the saved agent stopped on an out-of-cohort target instead of checking
the eligible ones. These are observed method limitations, not permission to
change frozen gold, rewrite existing predictions or rerun inference here.

`review-only` uses CSV decisions/results above and system configuration projected
from `configs/answering.yaml`, selection, LLM config and applicable calibration.
It tags `provenance=review-only`, `config_origin=reconstructed`. It omits cost,
latency, tokens, abstention and failure rates because the review sheet cannot
establish those metrics reliably. Never zero-fill them. Ledger imports tag
`provenance=ledgers`, `config_origin=historical`. Both are `source=backfill`.

### Portable historical references

Saved Windows/POSIX machine paths are resolved using their exact, unambiguous
`outputs/…` suffix under this checkout. Relative Windows separators are normalized.
Run IDs are preserved; no glob search or nearby-run substitution is used. Every
prediction input must match the original evaluation manifest's SHA-256, and the
partner scorer separately checks the prediction manifest's file hashes. Changed
inputs raise an error; missing inputs permit review-only fallback. Test prediction
references are refused before hashing or loading their contents. Source manifests
are never rewritten. The provenance artifact records original-to-local mappings
and pins the evaluation manifests and latest/provenance metadata.

Prediction identity uses the answering runner's compact-JSON digest, not the
evaluation scorer's differently serialized digest. Config/identity files are also
checked against saved manifest hashes. For this local pilot all 30 prediction
inputs (nine ledgers plus manifest per dataset) match their evaluation pins.

The archived `outputs/evaluation/phase11/official_runtime/retrieval.json` is absent.
Its RRF setting remains `null` in the historical config and is explicitly listed
in provenance `unknown_config_fields`; today's setting is not substituted.
Restore that archived file with its pinned hash before claiming a fully reproduced
configuration or choosing a preset based on it. Other saved settings, including
the selected pair and S4 tau, come from verified run identity/config snapshots.

The actual dry-run selects `ledgers`: 1,125 system/question records (125-question
pilot × nine systems), not just the 358 rows in the review CSV. Human verdicts
remain joined to their original review IDs. Saved call-count metrics are present
for nine systems and latency for seven; incomplete token usage remains omitted.
This is a no-write backfill inspection, not a new inference or full-dev evaluation.

### Idempotency and immutable configuration

Tracking identity is `(source, config_hash, eval_set)` within each experiment.
Canonical RunConfig params are validated before creating an experiment/run.
Serial reruns update that run. A later exact ledger import with the same
configuration upgrades the same run ID and tags; a review-only rerun cannot
downgrade it. If actual historical settings differ from reconstructed settings,
the adapter refuses rather than create another pilot/system or mutate immutable
MLflow params. Reconcile that explicit source conflict; do not relabel historical
settings as the reconstructed ones. Concurrent backfills are not supported: run
one apply process at a time.

Seven current `b1-local` review-only system configs differ from the archived
ledger configs. Do not overwrite their immutable MLflow params. Inspect with
`python scripts/backfill_answer_eval.py --mode ledgers`; write a separate local
store with `--apply --tracking-uri "file:$PWD/outputs/mlflow/b1-ledgers"` if you
want to preserve the reconstructed store. Point the dashboard at the chosen
tracking URI. Backfill retrieval runs there separately if needed. No apply or
remote write was performed while implementing this repair.

## Retrieval mapping

Each cell maps to `retr.<dataset>.<family>.<metric>` using shared contract names,
including hit_at_1/5/10, recall_at_5/10, mrr_at_10, ndcg_at_10, bug_hit_at_5,
mh_full_evidence_at_10, latency_p50_ms/p95_ms and n. A dict's value is logged only
when nonnull with positive n; otherwise `na_cells.csv` records its state and
per-metric denominator. Counts are canonical cell counts, never pooled across
runs. Absent families and N/A metrics stay distinct. `per_family.csv` preserves
source cell coverage. Bootstrap intervals go in `intervals.json` (CI metric
names are not in the contract). Known-citation labels remain incomplete.

Overlapping R1/R5 cells in the two summaries must have identical non-latency
results; otherwise fail. First lexicographically ordered source supplies latency
(no averaging of medians). All input summary hashes are retained. Selection is
read from `selected_retriever.yaml`'s **selected** object (currently R7b/C1), not
its candidate list. These RunConfigs are a projection to identify retriever/corpus
settings, not evidence that an answering system ran.

## Publication

See `docs/PROMOTION_POLICY.md`, declared before choosing any real champion.
Only dev configs pass publication, and execute validation is mandatory even for
non-champion presets. Registry versions are pyfunc config wrappers with the same
config.yaml format as the seed. Repeat registration reuses a config hash;
preset slugs are unique among published versions. One version has one preset
slug. Publishing a new slug on that version replaces its old slug. Unpublish
retains the version/history; moving champion does not delete old versions.
The current real review-only results cannot establish automatic promotion:
required rates/latency and F5 grades are missing; S5/S8 exceed serving caps.
No real champion or preset was published by the agent.

## Terminal commands (Conda iqfm; no virtualenv)

1. Offline tests and dry runs (no tracking connection):

```bash
conda activate iqfm
python -m pytest tests/contracts tests/b_tracking -q
python scripts/backfill_answer_eval.py --source outputs/evaluation/phase11/pilot125/
python scripts/backfill_retrieval_eval.py --runs 'outputs/retrieval/v3/run-*'
```

Expected: passing tests; nine answer plans in review-only mode with the fallback
reason; 24 retrieval plans and one selected pair.

2. Explicit local apply, then view (no DagsHub required):

```bash
export MLFLOW_TRACKING_URI="file:$PWD/outputs/mlflow/b1-local"
python scripts/backfill_answer_eval.py --source outputs/evaluation/phase11/pilot125/ --apply
python scripts/backfill_retrieval_eval.py --runs 'outputs/retrieval/v3/run-*' --apply
mlflow ui --backend-store-uri "$MLFLOW_TRACKING_URI" --port 5000
```

Expected: nine PILOT answer runs and 24 retrieval runs; reruns preserve run IDs.
Open http://127.0.0.1:5000. Stop UI with Ctrl+C before changing environments.

3. DagsHub apply, in a new terminal with securely supplied environment variables
(no secrets in CLI/history):

```bash
conda activate iqfm
# Supply MLFLOW_TRACKING_URI, MLFLOW_TRACKING_USERNAME and MLFLOW_TRACKING_PASSWORD
# using your existing secure environment; the URI must contain no credentials.
python scripts/backfill_answer_eval.py --source outputs/evaluation/phase11/pilot125/ --apply
python scripts/backfill_retrieval_eval.py --runs 'outputs/retrieval/v3/run-*' --apply
```

These tools read environment variables; they do not load or upload .env.
Expected: same validated aggregates in DagsHub. No calls to Groq or LangSmith.

4. Once complete comparable dev metrics identify a deployable policy winner,
set CHAMPION_RUN_ID, FAST_RUN_ID and DEEP_RUN_ID to actual MLflow run IDs.
The Deep config must be a **new, evaluated serving-compliant** config; never
clip the archived 12K configuration during publication.

```bash
python scripts/publish_preset.py --run-id "$CHAMPION_RUN_ID" --slug recommended --label Recommended --description 'Policy-selected dev configuration' --champion
python scripts/publish_preset.py --run-id "$CHAMPION_RUN_ID" --slug recommended --label Recommended --description 'Policy-selected dev configuration' --champion --apply
python scripts/publish_preset.py --run-id "$FAST_RUN_ID" --slug fast --label Fast --description 'Evaluated fast configuration' --apply
python scripts/publish_preset.py --run-id "$DEEP_RUN_ID" --slug deep --label 'Deep read' --description 'Evaluated bounded dossier' --apply
```

First command is read-only comparison. Automatic champion publication refuses
until policy passes. An owner may explicitly supply `--override-policy 'reason'`
for policy thresholds only; this is audited, not generated by the agent. Missing
metrics and missing human F5 grades remain missing. Unpublish without deletion:
`python scripts/publish_preset.py --slug fast --unpublish --apply`.

### Verified local balanced-family results

Local store: `outputs/mlflow/b1-ledgers`. Original nine answer-run IDs retained;
champion aliases and both registry versions/preset tags unchanged. A before-metrics
backup and verification summary are under ignored
`outputs/mlops/backfill_repair/20261122T025849Z/`.

Cells are **correct/scored n**; `P6` means six shared pending answer-grading
reviews, score unavailable. These are Phase 11 answer reviews, not pending
benchmark-gold approvals; frozen benchmark files remain unchanged.

| System | F1 | F2 | F3 | F4 | F5 | F6 | KI | MH | F6H |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S0 | 0/21 | 1/8 | 0/15 | 0/19 | P6 | 13/13 | 0/24 | 0/8 | 11/11 |
| S1 | 8/21 | 1/8 | 0/15 | 18/19 | P6 | 13/13 | 16/24 | 0/8 | 11/11 |
| S2 | 21/21 | 2/8 | 0/15 | 19/19 | P6 | 10/13 | 18/24 | 0/8 | 7/11 |
| S3 | 21/21 | 2/8 | 0/15 | 19/19 | P6 | 10/13 | 18/24 | 0/8 | 7/11 |
| S4 | 14/21 | 1/8 | 0/15 | 19/19 | P6 | 11/13 | 18/24 | 0/8 | 10/11 |
| S5 | 20/21 | 2/8 | 0/15 | 17/19 | P6 | 12/13 | 18/24 | 0/8 | 7/11 |
| S6 | 14/21 | 1/8 | 0/15 | 19/19 | P6 | 11/13 | 18/24 | 0/8 | 10/11 |
| S7 | 21/21 | 2/8 | 1/15 | 18/19 | P6 | 13/13 | 0/24 | 0/8 | 8/11 |
| S8 | 21/21 | 2/8 | 0/15 | 17/19 | P6 | 12/13 | 17/24 | 0/8 | 8/11 |

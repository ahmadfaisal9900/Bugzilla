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
| No rows, or no scored rows, for a family | No score/n metric; artifact distinguishes pending from absent |

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
  Human verdicts override when signed; F5 otherwise remains ungraded.
- `fail.rate`: missing/execution-failed predictions / pilot records.
- `abstain.correct_rate`: abstained / records with explicitly unanswerable gold;
  `abstain.false_rate`: abstained / explicitly answerable records. Empty
  denominators omit metrics. Gold kind determines this, not a family guess.
- `cost.llm_calls`: sum saved call_count including failed attempts; token metrics
  sum saved input_tokens/output_tokens only when all attempts supply them.
  Reported tokens are saved-response usage, not a billing estimate for failed
  requests with missing usage. `latency.*`: saved non-cache attempt latencies,
  sorted p50 index n//2, p95 min(n-1,floor(.95n)), matching partner convention.
- Source SHA-256s and per-family denominators are artifacts; no raw predictions.

`review-only` uses CSV decisions/results above and system configuration projected
from `configs/answering.yaml`, selection, LLM config and applicable calibration.
It tags `provenance=review-only`, `config_origin=reconstructed`. It omits cost,
latency, tokens, abstention and failure rates because the review sheet cannot
establish those metrics reliably. Never zero-fill them. Ledger imports tag
`provenance=ledgers`, `config_origin=historical`. Both are `source=backfill`.

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

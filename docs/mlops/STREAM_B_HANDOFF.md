# Stream B integration handoff

B4/B5 and B6 implementation are in the existing `Project` repository on
`feature/mlops`. No Stream A API/chat/Compose/CD code, research implementation,
review input, delivered bundle, or promotion policy was edited. No push or new
champion publication was performed. Direct dependencies remain exactly pinned.
The shared engine includes a compatibility fix for the accepted bundle's
text-only examples: it inherits dev scope from the verified manifest for those
rows, while structured rows still require an explicit dev split.
See [CI.md](CI.md), [dashboard README](../../src/bugzilla_serving/dashboard/README.md)
and [AGENT_NOTES.md](../AGENT_NOTES.md) for checks and timing evidence.

## Registry source of truth and current state

DagsHub is the source of truth. Read the reason from the champion registry
version's `policy_override` tag. The owner supplied its current text:

> Policy winner S8 (0.563) routes to the S5 12K dossier, which exceeds the serving cap; S2 (0.551) is the best config that passes serving validation.

This records the decision before dossier amendment 2; it is not rewritten by a
backfill or cap change. `outputs/mlflow/b1-ledgers` is a **local reference store**
whose registry tags predate the final publish. Its old override is not authoritative.
The capped-S8 versus S2 live comparison is dropped. S2 remains champion. No agent
published, rolled back, or otherwise changed DagsHub registry state.

The unchanged promotion policy requires **every** scored family >=0.50, false
abstention <=0.20, failure <=0.05, complete grading, and p95 time. It then chooses
macro accuracy, breaking ties within 0.01 by p95. Current ledgers select **none**:
all systems fail existing non-F5 family minimums (including MH=0 and F3≈0).
Adding F5 cannot fix these failures. Do not publish a policy winner that does not
exist, weaken the policy, or add an override for the conditional commands below.

## B6 changes and execution state

- **F5:** the 54 pending responses are six dev questions × nine systems. Every
  question has one existing reference shared by all systems; no saved verdicts
  exist. Following the user's clarified choice, `grade_f5.py` prepares a separate
  semantic-grading job, six question batches with anonymous candidates. It does
  not regenerate references or answers. `--f5-gold human` keeps the previous
  backfill behavior. `--f5-gold llm` requires all saved judgments to match their
  reference/answer fingerprints before scoring anything. Imported runs carry
  `f5_gold=llm`, F5-inclusive `answer.macro` and comparable
  `answer.macro_excl_F5`. A human-mode rerun cannot silently downgrade an already
  imported LLM-gold run. The real judgment job/import are **not executed** yet;
  denominators become 125/125 only after the complete verdict ledger is imported.
- **Parity:** three questions from smoke-5 pass through the same engine used by
  Lab and POST `/v1/ask`. Compare answer text, abstention, cited bug IDs and config
  hash. Mock mode is default; both sides receive the same mock-provider config.
  A fake API matches; the Phase 0 stub returns a readable HTTP 501 mismatch and
  exit 1. Real partner API parity remains an integration check.
- **LangSmith:** one live `smoke=true` trace and one positive `user_rating` were
  created and read back, with zero LLM calls. A transient indexing 404 was resolved
  by reading the same ID later; no duplicate trace/rating was created. Production
  hides smoke traces by default; turn on Show test traces after Refresh.
- **Rollback:** dry-run by default; apply requires a reason, validates the target,
  and records `rollback_reason`, `rolled_back_from`, `rolled_back_at` before moving
  the champion alias. Presets displays those tags from its snapshot. These tags
  show the latest rollback into each version, not a full immutable alias log.
  Mutation was tested only in a temporary local store.
- **Dossier amendment 2:** only the evidence-byte knob max becomes 12,000, with
  truthful byte labeling. Its default remains 4,096; all other limits remain.
  The validator no longer compares dossier bytes to the model's token cap. The
  engine already overrides bundle runtime with an explicit config dossier value.
  See [PHASE0_NOTES.md](PHASE0_NOTES.md#amendment-2--dossier-evidence-cap-2026-11-22).
  History-complete usage supplies the planning mean; otherwise use UTF-8 bytes/3.
  Send-time estimates include schema/tools/system prompt. Evidence is trimmed
  until estimated input + 2,048 output <=7,200, or fixed overhead is refused.
  One pacing instance covers router, rewrites, tools and answers; request/daily
  limits remain active. No capped live S8/S2 comparison is scheduled.

## Operator commands

Run in your own terminal. No `.env` is required by CI; never commit its values.
The shell examples use registry configs unchanged and never the Recommended YAML
fallback. The full-data/model jobs remain owner-terminal operations.

```bash
conda activate iqfm
cd "/home/ict317/master's/ENSF 621/Project"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
set -a
source .env
set +a
export BUNDLE_DIR="$PWD/serving_bundle"
export LOCAL_TRACKING_URI="file:$PWD/outputs/mlflow/b1-ledgers"
# MLFLOW_TRACKING_URI from .env must point to DagsHub for the remote commands.
```

1. **Prepare the F5 judgments, then backfill local, then DagsHub, then refresh.**

   ```bash
   scripts/phases/run_phase06_f5_grade.sh --dry-run --limit 6 --max-requests 6
   # The separately authorized job you chose to run: six batches, 54 verdicts.
   scripts/phases/run_phase06_f5_grade.sh --enable-llm --limit 6 --max-requests 6
   python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm \
     --tracking-uri "$LOCAL_TRACKING_URI"
   python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm \
     --tracking-uri "$LOCAL_TRACKING_URI" --apply
   python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm
   python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm --apply
   scripts/phases/run_phase05_dashboard_snapshot.sh --max-requests 1000
   ```

   Expected first: DRY_RUN, six batches, 54 pending rows, zero API calls. The live
   job saves complete, fingerprint-bound batches to
   `outputs/mlops/f5_gold/verdicts.jsonl`; repeat to resume. Timestamped log and
   summary paths are under `outputs/mlops/f5_gold/jobs/`. On success expect 54
   verdicts and COMPLETE, with at most six model requests on an uncached run.
   Missing, partial, duplicate, stale or out-of-scope judgments refuse import.
   Backfill dry-runs create no tracking client. Applied runs keep identities and
   have F5 n=6, pending=0 and 125 scored answers per system. They show Overall
   and Overall without Reasons. No gold/reference text is added to MLflow.
   Scores are graded by an LLM judge against the human-reviewed reference from the frozen benchmark; this is not evidence that
   the references or model judge are infallible. Neither backfill changes aliases.
   Snapshot refresh uses artifact content revisions so updated aggregate scores
   replace earlier cached ones while unchanged downloads remain resumable.

2. **Parity against the Phase 0 stub.** In one terminal:

   ```bash
   python -m uvicorn bugzilla_serving.api.stub:create_app --factory \
     --host 127.0.0.1 --port 8000
   ```

   In another, with the same environment:

   ```bash
   python scripts/mlops/parity_check.py --api-url http://127.0.0.1:8000 \
     --config-source champion --provider mock --n 3
   # An exact evaluated config can instead be selected with --config-source run:ID.
   ```

   Expected: three rows, API HTTP 501 / DIFF, exit 1; no crash or quota use.
   Against the partner's working API, expect four matching fields per row and
   exit 0. Mock must be supported on both sides. The real bundle is verified and
   used by default; local model files are required even with MockProvider.

3. **LangSmith smoke and Production.** The requested check already exists at
   [this trace](https://smith.langchain.com/o/e906d1d7-e702-4a19-a9ed-6fa3de69fe08/projects/p/8a6bd5d1-459e-4652-a21c-33d50de2470c/r/96b5c506-32c6-4205-ba1b-9eb67c8b0f50?poll=true).
   To deliberately create another single test trace later:

   ```bash
   python scripts/mlops/langsmith_smoke.py
   LANGSMITH_SOURCE=live DASHBOARD_LAB_ENABLED=true \
     python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
   ```

   Expected smoke JSON: trace URL, smoke=true, llm_calls=0; exactly one root and
   one rating per invocation. It forces sampling for the intentional smoke and
   retries bounded read-index delays. In Production click Refresh data, then
   Show test traces. The trace has rating 1. With the toggle off it is excluded
   from tables, charts and aggregates. Live dashboard rendering itself remains
   an operator check; its filtering and feedback parsing have offline coverage.

4. **Rollback demo, dry-run only on DagsHub.** Save the current S2 version before
   any future promotion (read the registry champion version; do not assume the
   local store's version number matches DagsHub).

   ```bash
   python scripts/mlops/rollback_champion.py
   python scripts/mlops/rollback_champion.py --to-version "$S2_VERSION" \
     --reason 'Demo: return to the previously published Smart search'
   ```

   Expected: DRY_RUN with before/after versions, no writes. If S2 is still the
   current champion, the explicit S2 target reports Already champion; there is
   no rollback to perform. With no `--to-version`, previous means the nearest
   smaller registered version, not an inferred previous alias event. Applying
   would additionally require `--apply --reason TEXT`; do not apply on DagsHub
   as part of this handoff. Do not move champion merely to manufacture a demo.

5. **Minimal live Lab loop, published Fast/S1 unchanged.**

   ```bash
   python scripts/mlops/run_experiment.py --registry-presets --preset fast \
     --bundle ./serving_bundle --eval-set smoke-5 --max-requests 8 \
     --label live-smoke-s1 --dry-run
   python scripts/mlops/run_experiment.py --registry-presets --preset fast \
     --bundle ./serving_bundle --eval-set smoke-5 --max-requests 8 \
     --label live-smoke-s1 --enable-llm
   scripts/phases/run_phase05_dashboard_snapshot.sh --max-requests 1000
   ```

   Expected on fresh daily quota: fits=true and fits_request_cap=true. Five normal
   S1 calls plus up to three repair calls fit the eight-request cap; provider
   reservation enforces it. No top_k/context or other knob changes are made.
   A synthetic fresh-quota test checks this cap and token estimate. Current used
   quota may correctly refuse it. Live execution is owner-run, resumable and
   paced; it creates a playground run with source=lab, label=live-smoke-s1.
   After rebuilding the snapshot and Refresh data, find the named Lab run on the
   dashboard. This checks plumbing, not a new research comparison.

6. **Execute validation, post-F5 policy preview, conditional publication.**

   ```bash
   # Current view without generating/scoring F5:
   python scripts/mlops/preview_promotion.py
   # Run only after step 1 has produced the complete saved judgment ledger:
   python scripts/mlops/preview_promotion.py --f5-gold llm
   ```

   Expected execute validation: S1–S6 and S8 pass; S0/S7 retain their recorded
   inapplicable top_k failures. Current policy selects none; non-F5 family scores
   make this invariant to the missing F5 grades. No changed champion is expected.
   If a future fully evidenced preview genuinely selects another config, these
   are the conditional commands; never bypass the policy:

   ```bash
   # POLICY_WINNER_RUN_ID must be the policy-allowed historical run on DagsHub.
   python scripts/mlops/publish_preset.py --run-id "$POLICY_WINNER_RUN_ID" \
     --slug recommended --label Recommended --description 'Policy-selected dev config' \
     --champion
   # Only after that dry-run passes; no --override-policy:
   python scripts/mlops/publish_preset.py --run-id "$POLICY_WINNER_RUN_ID" \
     --slug recommended --label Recommended --description 'Policy-selected dev config' \
     --champion --apply
   # Keep S2 selectable without changing its configuration:
   python scripts/mlops/publish_preset.py --run-id "$S2_RUN_ID" --slug smart \
     --label 'Smart search' --description 'Published Smart search configuration'
   python scripts/mlops/publish_preset.py --run-id "$S2_RUN_ID" --slug smart \
     --label 'Smart search' --description 'Published Smart search configuration' --apply
   python scripts/mlops/rollback_champion.py --to-version "$S2_VERSION" \
     --reason 'Demo: return to Smart search'
   ```

   Expected today: no winner, so skip the recommended publication commands.
   The Smart search republish is supplied for the conditional future change;
   it was not applied. The rollback command is always a dry-run here.

7. **Review, commit and push `feature/mlops`; no PR into main.**

   ```bash
   git diff --cached --check
   git diff --cached --name-only
   git diff --cached --stat
   git commit -m "Complete B6 integration tools and approved dossier amendment"
   git push origin feature/mlops
   ```

   Review the exact named B6 staged set before committing. No raw data, model,
   credential, generated verdict ledger or large log belongs in that set. These
   commands are provided for you; no push or publication was performed by the agent.

## Retained deployment and dashboard behavior

Snapshot JSON is under `outputs/dashboard_cache/<credential-free source>/` and
loaded once via cache_resource. Missing snapshots build with progress; stale ones
stay visible (30-minute default, separate five-minute LangSmith indicator).
Refresh data is explicit. Immutable details are lazy; mutable aggregate artifacts
are keyed by their tracked content revisions. Small downloads use eight workers.
`DASHBOARD_PROFILE=1` prints SDK/data/page timings to stderr and sidebar.

The readonly Docker target stays torch-free, starts its snapshot builder in the
background, and uses writable DASHBOARD_CACHE_DIR. Lab-only imports and registry
writes remain gated by DASHBOARD_LAB_ENABLED=true. Stream B supplies dashboard
Dockerfile and CI; A owns API/chat images, Compose and CD. Docker/GitHub execution
remain operator gates, separate from fixture/AppTest/localhost checks.

Every dashboard page has its purpose, How to read this, Notes, human labels and
technical details. Overview has both macro scores; Compare preserves matching n,
paired tests when complete per-question binary data exists, and heuristic noise
labels otherwise. Test-aggregate runs expose only metrics, never questions/gold.

## Integration open questions

1. `configs/presets.yaml` fallback still says recommended=S8. It must match the
   registry's recommended=S2 under a separately approved shared-file change; B6
   does not edit it. Never use that fallback for the examples above.
2. The real API must read the dossier max/unit from serving.yaml and apply the
   same request/pacing gate. Stream B cannot change its unmerged provider path.
3. Run the six-request F5 job and import all saved judgments before claiming
   125/125 denominators or reporting an F5-inclusive real score.
4. The existing policy cannot automatically promote any current pilot system.
   Keep S2; changing that policy would be a separate explicit decision.
5. Real API parity, live S1 completion, live dashboard Refresh and Docker/GitHub
   CI execution are owner/integration gates. B6 does not claim they passed.


## B7b — scorer v2, audited tools and owner runbook (2026-11-22)

**Superseded plan:** the original score table and quota commands in this section
predate rule (d) and measured pacing. Use [B7_ONE_DAY_PLAN.md](B7_ONE_DAY_PLAN.md)
for current scores, composite scope and owner commands. No separate S7v2 or
holdout run is scheduled by the current plan.

Implemented and tested offline. No live model, DagsHub or LangSmith requests;
no commit, push, publication or champion change. Nine re-score plans are ready,
not uploaded. New system answer quality is **not executed or validated**.

### Decisions, exclusions and F5 provenance

`configs/scoring_exclusions.yaml` is the authoritative `f3_test_scope_v1` list.
The three dev-labelled test-population F3 aggregates are excluded for every
system/version; no test population is computed. Pilot scoring n=122 and F3 n=12.
Other dev-labelled single-bug questions retain their frozen v3 dev identity;
original-v2 partition labels do not turn them into aggregate test populations.
Gold, freeze files and all original ledgers are unchanged.

All six pilot grading references equal the signed Phase 5 supported_explanation
claims rendered as text. The reference is human-reviewed; the **answer judge is
an LLM**. This supersedes B6's inaccurate reference-origin wording above. Original
judge verdicts/fingerprints were reused without regeneration.

| qid | Equal to frozen human-reviewed claim? |
| --- | --- |
| q_0f02c856b8576c53962d | yes |
| q_103fc1febfb8153ed3d2 | yes |
| q_639f25ec01824d49c28e | yes |
| q_7e52cb5dac94d7614825 | yes |
| q_a5c70180da726d9445de | yes |
| q_df73d0a04940f296b92e | yes |

There are no reference diffs. The display short text is now:
“Graded by an LLM judge against the human-reviewed reference from the frozen benchmark”.

### Old → new correct counts

Both columns apply the exclusions, so old F3 is zero for all nine systems (the
previous one S7 success was an excluded test-population aggregate). Denominators:
F1=21, F2=8, F3=12, F4=19, F5=6, F6=13, KI=24, MH=8, F6H=11.

| System | F1 | F2 | F3 | F4 | F5 | F6 | KI | MH | F6H |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S0 | 0→0 | 1→1 | 0→0 | 0→0 | 0→0 | 13→13 | 0→0 | 0→0 | 11→11 |
| S1 | 8→8 | 1→1 | 0→0 | 18→18 | 0→0 | 13→13 | 16→16 | 0→0 | 11→11 |
| S2 | 21→21 | 2→2 | 0→0 | 19→19 | 0→0 | 10→10 | 18→18 | 0→0 | 7→7 |
| S3 | 21→21 | 2→2 | 0→0 | 19→19 | 0→0 | 10→10 | 18→18 | 0→0 | 7→7 |
| S4 | 14→14 | 1→1 | 0→0 | 19→19 | 0→0 | 11→11 | 18→18 | 0→0 | 10→10 |
| S5 | 20→20 | 2→2 | 0→0 | 17→17 | 1→1 | 12→12 | 18→18 | 0→0 | 7→7 |
| S6 | 14→14 | 1→1 | 0→0 | 19→19 | 0→0 | 11→11 | 18→18 | 0→0 | 10→10 |
| S7 | 21→21 | 2→2 | 0→6 | 18→18 | 0→0 | 13→13 | 0→0 | 0→1 | 8→8 |
| S8 | 21→21 | 2→2 | 0→6 | 17→17 | 1→1 | 12→12 | 17→17 | 0→1 | 8→8 |

Fourteen changed verdicts, all INCORRECT → CORRECT by `singleton_number`:

| System | Dataset | qid | Family | Rule |
| --- | --- | --- | --- | --- |
| S7 | natural | natural_14dea18947f819a165f2 | F3 | singleton_number |
| S7 | natural | natural_1ff9db21c37498214734 | F3 | singleton_number |
| S7 | v3 | v3_bb5fff7e16d6b379f9ddade7 | F3 | singleton_number |
| S7 | v3 | v3_13b1d27d94419f10879fac40 | MH | singleton_number |
| S7 | v3 | v3_16911b9ae12cae02c201d505 | F3 | singleton_number |
| S7 | v3 | v3_315be90cc9884d93d950e584 | F3 | singleton_number |
| S7 | v3 | v3_c405fd55813cd6dfaf9f9b72 | F3 | singleton_number |
| S8 | natural | natural_14dea18947f819a165f2 | F3 | singleton_number |
| S8 | natural | natural_1ff9db21c37498214734 | F3 | singleton_number |
| S8 | v3 | v3_16911b9ae12cae02c201d505 | F3 | singleton_number |
| S8 | v3 | v3_bb5fff7e16d6b379f9ddade7 | F3 | singleton_number |
| S8 | v3 | v3_13b1d27d94419f10879fac40 | MH | singleton_number |
| S8 | v3 | v3_315be90cc9884d93d950e584 | F3 | singleton_number |
| S8 | v3 | v3_c405fd55813cd6dfaf9f9b72 | F3 | singleton_number |

The MH [0] format correction does not validate its original link-direction reasoning;
these are answer-score changes, not new grounding or generation results.

F2 is unchanged: the approved adapter does not infer an hours unit for a bare
number labelled `answer_type=number`. Explicit matching-unit strings are parsed;
finite numeric singleton lists are unwrapped only for scalar numeric gold.
Wrong counts, multi-element lists, list-typed gold, abstentions and original
one-hour tolerance are unchanged. Archived confidence intervals predate these
exclusions/scores and are omitted rather than reused with new denominators.

The unchanged promotion-policy preview selects **none**. No publication occurs.
MLflow keeps canonical base RunConfig params; scorer_version distinguishes v1/v2.
System variants use `system_id=S7v2|S8v2`, iteration, variant_hash and a complete
system_variant.json artifact. The shared contracts do not support these IDs, so
these are **research-only** systems, executed through the new CLI, not serving
API presets. Dashboard labels read the variant tag, and Scorer version defaults
to v2 when present. V1 remains selectable. Historical costs are reused for
re-scoring; the offline adapter itself makes zero model requests.

### TOOL-error breakdown (28 primary TOOL rows)

Incidence is per row and overlaps: a row can contain both rejected output and
answer-contract failure. Raw saved messages are preserved below. No 429/5xx is
recorded in these 28 prediction rows; this does not claim the provider never
rate-limited other runs. Three tool results preserve only ValueError, not the
underlying exception message.

| Saved error class/message | Row incidence |
| --- | ---: |
| `answer_contract:ValidationError` | 24 |
| `answer_contract:ValueError` | 2 |
| `invalid_output:InvalidJSONResponse:Model produced a rejected tool call; return answer JSON without tool calls` | 17 |
| `invalid_output:InvalidJSONResponse:Provider rejected model output against the requested schema` | 7 |
| `known=false:Outside the public indexed study cohort` | 6 |
| `tool_rejected:ValueError` | 3 |
| `tool_result:ValueError` | 3 |

V2 accepts exactly one call per tool turn, validates its exact name and arguments
before execution and allows one repair request for malformed/schema-rejected
calls. Failed repair exhausts that turn; provider RuntimeErrors (including rate
limits/server failures) receive no tool repair. Every fresh attempt counts in
llm_calls. Four native tool steps remain; count and lifecycle computation are
inherited unchanged. No duplicate count/history implementation exists.

Linked-bug semantics: bugs blocking X = X.depends_on targets; bugs X blocks =
X.blocks. Each target has status, resolution, component and in_cohort. Membership
uses sample_membership seed=317 plus conflict exclusion. Cohort-scoped questions
exclude out-of-cohort/conflicted targets without stopping on the first unknown.
Public comment hashes resolve through record IDs; private/unknown-visibility
segments and unknown/ambiguous hashes are refused. The cited comment is the first
labelled dossier block. All other routes/prompt/cache-key calculations remain
those of S8. The local cache has zero verified complete matches at planning time;
no speculative hits are subtracted. A cache-only replay can credit complete
matches after earlier jobs warm the cache, without model loading or API calls.

Findings includes exactly:
“Version-2 tools and router were developed after a failure audit on the development pilot (FAILURE_AUDIT.md); their pilot scores are therefore optimistic.”

### Held-out coverage and quota plan

fix-holdout is deterministic, excludes pilot IDs and all test-scoped F3
aggregates, and has **F2=0, F3=15, F5=0, MH=0**. Three families have fewer than
five items. This can check counting only, not generalization on the other fixes.
No replacement questions were generated.

Plans use 7,200 tokens/request as a conservative reservation (estimated input
plus 2,048 output), respecting a 10% TPM margin. Each invocation permits at most
25 **fresh** requests and checks the shared provider ledger before starting:
25 × 7,200 = 180,000/day, a 10% TPD margin. Cached requests do not count as fresh
calls. Actual future usage is unknown. Per-day caps are enforced; no background
sleep across quota days. PAUSED_QUOTA is resumed by invoking the same command on
a later provider quota day. Earlier partial-attempt usage is retained separately
and included in backfill costs. Repaired/transient logs do not silently turn
completed successful answers into failures.

| Run | Questions | Verified cache hits | Estimated fresh calls | Reserved tokens | Upper calls/tokens | Expected relative days | Worst-case relative days |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| S7v2 / fix-pilot-tools | 21 | 0 | 58 | 417,600 | 210 / 1,512,000 | D1–D3 | D1–D9 |
| S8v2 / pilot122-v2 | 122 | 0 | 274 | 1,972,800 | 1051 / 7,567,200 | D4–D14 | D10–D52 |
| S7v2 / fix-holdout | 15 | 0 | 30 | 216,000 | 150 / 1,080,000 | D16–D17 | D54–D59 |
| S8v2 / fix-holdout | 15 | 0 | 30 | 216,000 | 150 / 1,080,000 | D18–D19 | D60–D65 |

These are reservations and bounds, not measured tokens or promised durations.
Start each stage on the next quota day after its predecessor completes; re-plan
then to credit warmed caches. Expected day 15 (worst-case day 53) reserves up to
12 F5 grading calls across both new systems: **86,400 tokens**. Optional holdout
starts on the following quota day. Days are relative provider quota days, not
wall-clock dates; the current day may have other organization usage.

### Numbered owner commands

Use the existing checkout and Conda iqfm; paths are quoted for the apostrophe
and spaces. No dependency installation or .env requirement for offline checks.

1. Offline re-score and compare (zero API calls/tokens):

```bash
cd "/home/ict317/master's/ENSF 621/Project"
conda activate iqfm
export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
python -m bugzilla_serving.experiments.rescore
```

Expected: the table above, fourteen changed rows with rules, six equality=yes,
TOOL table and promotion selected=None. Analysis reports go to ignored
outputs/analysis/b7b/. No MLflow write.

2. Inspect both MLflow versions and the unchanged policy (zero inference quota):

```bash
python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm --scorer-version 1
python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm --scorer-version 2
python scripts/mlops/preview_promotion.py --f5-gold llm --scorer-version 2
```

Expected: nine plans per version, F3 n=12 and both macro metrics; policy selects
none, published=false. Scripts must resolve this checkout's source (the existing
editable installation or PYTHONPATH set as in command 1).

3. Explicit owner MLflow upload, local store or DagsHub URI supplied through
MLFLOW_TRACKING_URI (no credentials in arguments/history):

```bash
python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm --scorer-version 1 --apply --resume
python scripts/mlops/backfill_answer_eval.py --mode ledgers --f5-gold llm --scorer-version 2 --apply --resume
```

Expected: existing v1 IDs updated only for the required exclusions, nine distinct
v2 runs; v1 superseded_by points to its corresponding fully uploaded v2 run.
Re-running preserves IDs. No registry alias changes. Zero model calls/tokens;
MLflow SDK calls are live only when the owner runs --apply. Never run concurrent
uploaders.

4. Reproduce plans (zero live calls; no models loaded):

```bash
scripts/phases/run_phase07_v2.sh plan --system S7v2 --eval-set fix-pilot-tools --dry-run
scripts/phases/run_phase07_v2.sh plan --system S8v2 --eval-set pilot122-v2 --dry-run
scripts/phases/run_phase07_v2.sh plan --system S7v2 --eval-set fix-holdout --dry-run
scripts/phases/run_phase07_v2.sh plan --system S8v2 --eval-set fix-holdout --dry-run
```

Expected: DRY_RUN, actual_api_calls=0, counts/reservations above. The full pilot
means 125 original questions minus the three binding exclusions = 122 eligible.

5. Owner-only resumable inference, in the stage/day order above. Invoke the same
command on a subsequent quota day after PAUSED_QUOTA, until COMPLETE. Optional
--limit caps newly completed questions per invocation without changing the roster.

```bash
scripts/phases/run_phase07_v2.sh run --system S7v2 --eval-set fix-pilot-tools --enable-llm --max-requests 25
scripts/phases/run_phase07_v2.sh run --system S8v2 --eval-set pilot122-v2 --enable-llm --max-requests 25
```

Expected: timestamped summary/manifest and immutable completed prediction rows in
outputs/predictions/v2/dev/run-*/. The printed ledger path is authoritative.
Daily maximum reservation 180,000 tokens; request pacing reserves at most 7,200
per minute. Failed/incomplete attempts remain in attempts.jsonl. Original ledgers
are never modified. Do not run both inference commands on the same quota day
unless a fresh preflight establishes remaining allowance.

6. Set S7_LEDGER and S8_LEDGER to the exact paths printed by the completed jobs;
then plan and run source-bound grading on the next quota day:

```bash
scripts/phases/run_phase07_v2.sh grade --system S7v2 --eval-set fix-pilot-tools --ledger "$S7_LEDGER" --f5-verdicts outputs/analysis/b7b/S7v2-f5.jsonl --dry-run
scripts/phases/run_phase07_v2.sh grade --system S8v2 --eval-set pilot122-v2 --ledger "$S8_LEDGER" --f5-verdicts outputs/analysis/b7b/S8v2-f5.jsonl --dry-run
scripts/phases/run_phase07_v2.sh grade --system S7v2 --eval-set fix-pilot-tools --ledger "$S7_LEDGER" --f5-verdicts outputs/analysis/b7b/S7v2-f5.jsonl --enable-llm --max-requests 6
scripts/phases/run_phase07_v2.sh grade --system S8v2 --eval-set pilot122-v2 --ledger "$S8_LEDGER" --f5-verdicts outputs/analysis/b7b/S8v2-f5.jsonl --enable-llm --max-requests 6
```

Expected: six requests per new system before cache hits, maximum 43,200 tokens
each (86,400 combined). The judge uses the frozen human-reviewed reference;
new fingerprints bind the new answers/configs. Old pilot verdicts are never
applied to new answers. Grading checkpoints each question; repeat to resume.

7. New-ledger backfill, dry-run first and then explicit owner apply:

```bash
scripts/phases/run_phase07_v2.sh backfill --system S7v2 --eval-set fix-pilot-tools --ledger "$S7_LEDGER" --f5-verdicts outputs/analysis/b7b/S7v2-f5.jsonl --dry-run
scripts/phases/run_phase07_v2.sh backfill --system S8v2 --eval-set pilot122-v2 --ledger "$S8_LEDGER" --f5-verdicts outputs/analysis/b7b/S8v2-f5.jsonl --dry-run
scripts/phases/run_phase07_v2.sh backfill --system S7v2 --eval-set fix-pilot-tools --ledger "$S7_LEDGER" --f5-verdicts outputs/analysis/b7b/S7v2-f5.jsonl --apply
scripts/phases/run_phase07_v2.sh backfill --system S8v2 --eval-set pilot122-v2 --ledger "$S8_LEDGER" --f5-verdicts outputs/analysis/b7b/S8v2-f5.jsonl --apply
```

Expected: complete source/checksum-bound research-answer-eval runs with
iteration=v2, diagnosed_on=pilot125, scorer_version=2 and exclusions=f3_test_scope_v1.
Zero inference quota. Incomplete ledgers/ref mismatches are refused. Without a
new F5 verdict file, F5 remains pending, not an invented score.

8. Optional holdout, starting the next quota day after the required stages:

```bash
scripts/phases/run_phase07_v2.sh run --system S7v2 --eval-set fix-holdout --enable-llm --max-requests 25
scripts/phases/run_phase07_v2.sh run --system S8v2 --eval-set fix-holdout --enable-llm --max-requests 25
```

Expected: fifteen development F3 questions each. Use separate quota days and
resume as above. Then use backfill with --eval-set fix-holdout and the exact new
ledger path, first --dry-run, then --apply; no F5 verdict file is needed. Both
remain tagged iteration=v2, diagnosed_on=pilot125. Estimates 30 calls/216,000
reserved tokens each; conservative upper 150/1,080,000, split into daily caps.

9. Snapshot rebuild after uploads (zero inference quota):

```bash
LANGSMITH_SOURCE=fixture python scripts/mlops/build_dashboard_snapshot.py --dry-run
LANGSMITH_SOURCE=fixture python scripts/mlops/build_dashboard_snapshot.py --max-requests 1000
```

Expected: explicit MLflow snapshot fetch with no live LangSmith request; COMPLETE
when all configured MLflow sources/artifacts are available. Dashboard defaults
to scorer v2, with v1 selectable. This does not publish a champion.

### Open questions / practical limits

No scientific decision is blocking the implemented work. The optional holdout
has only F3 coverage. Exact historical payload matches are unavailable locally;
restore a matching response cache to reduce the conservative plans. V2 is a
research-only extension; exposing new IDs through the shared API/RunConfig would
require a separate approved contract change. It is not needed for these jobs.
No new system accuracy claim is made before owner-run ledgers and judgments are
reviewed. Persisted snapshots refresh only through the explicit command above.


## B7e — JSON tools and immutable resume (2026-11-23)

The native-tool B7b/day-plan is superseded by [B7E_RESUME.md](B7E_RESUME.md).
Pilot F2/F3/F4/MH parser coverage is 47/47. New tool routes use bounded plain JSON
planning and deterministic numerical/link answers, preserving S0–S8 bytes.
The run-cf2c6f2cf859a3c6 source stays immutable: ten clean new answers (six F5)
are preserved, nine failed/error qids marked superseded, 83 questions rerun and
29 v1 answers carried in a new run. Estimate: two fresh calls / 4,704 tokens;
upper three / 7,056. Daily accounted usage is 118,839 with 61,161 remaining for
the run's Pacific quota date. All 60 F5 candidates are exported blind for one
external judge; validated import updates catalog wording and supplies provenance
for every system. No live execution or external judgment has occurred here.

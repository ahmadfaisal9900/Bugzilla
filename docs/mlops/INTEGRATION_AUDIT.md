# Stream A / Stream B integration audit — 2026-11-23

Implementation and bounded smoke checks are complete for the fixes listed here.
**Integration acceptance is not green:** the evaluated Auto-router cannot pass the
shared serving loader, and full tests/coverage, image builds and Compose smoke are
owner-terminal gates. The owner explicitly requested stopping long-running tasks.
No push, publication, deployment or successful live service call is claimed.

## Merge summary

- Existing repository/remote preserved. Branch: `integration/merge-audit`.
- B baseline: `f2cb612`; locally available A tip: `3160874`.
  No fetch was performed, so these are local ref observations.
- Merge: `efa8bd5`, `merge integration/stream-a-mlops into feature/mlops`.
  Both parents retained; no rebase. One text conflict, `.gitleaksignore`, resolved
  by retaining both branches' documented false-positive fingerprints.
- Kept B9 dashboard, results-pack/registry scripts and tests, B tracking/experiments,
  scorer_v2 and `answering_v2`. Kept A API/chat/bundle/quota/tracing/Compose/CD.
- Runtime/script audit fixes: `75727fe`; CI/evidence follow in a separate commit.
- Rejected A's edits to two research files and to their hash fixture. Kept the
  existing evaluation outputs unchanged. No research source was edited by this audit.
- Moved B9 scripts into `scripts/app/` and `scripts/mlops/`, updated references,
  and retained two small compatibility shims for frozen research help messages.
- Restored B's coverage path remapping; removed A's broad temporary-source omit.
  All `bugzilla_serving` modules remain in the denominator; local/CI gate is 70%.
- Enabled CI Compose smoke, including all three services and feedback checks.
- Added Linux launchers and an owner-only live-smoke wrapper. No long job was
  launched after the owner's follow-up instruction.

## AUDIT TABLE

`PASS` means the stated bounded evidence passed. `FIXED` describes implemented
fixes with bounded checks; it does not imply a full end-to-end run. Unexecuted or
incompatible requirements are explicitly `FAIL-REPORTED`.

| Item | Status | Evidence / remaining limit |
| --- | --- | --- |
| a. Research bytes | PASS | All 72 entries in `tests/fixtures/b7_legacy_bytes.json` match SHA-256; fixture unchanged from B. `git diff f2cb612 -- src/bugzilla_qa` is empty. B8 `input_sha256.json` contains input provenance, with zero `src/bugzilla_qa/` keys; the 72-entry fixture is the research-byte gate. |
| b. Test-data diagnosis / dev-only | PASS | `258f49a` cleared inherited `LLM_PROVIDER=mock` and `LANGSMITH_SOURCE` in the Windows launcher. This was mock runtime settings, not a test split. `bundle.py:27` calls the dev-only manifest verifier; `tests/a_bundle/test_bundle.py:45` passes rejection of non-dev. No locked-test questions/gold were inspected. Search of serving and scripts found no `--confirm-locked-test`, `test.gold` or `test.questions` references. |
| c. Secrets / tracked outputs | FAIL-REPORTED | Gitleaks history scan: 38 commits, ~2.73 MB, no leaks. `.env.example` uses placeholders; ignore files exclude runtime outputs, data, bundle, credentials and coverage. However **36 pre-existing `outputs/` files remain tracked**, including intentionally shared releases/review assets. No `.env`, serving bundle or results/coverage files are tracked. Removing frozen/shared research releases is outside this audit's minimal-fix scope. |
| d. A deletions | PASS | All 118 deletions relative to merge-base are listed below: build copies, egg-info and generated test reports. No contract fixture, OpenAPI snapshot or active test was deleted relative to merge-base. B9 files/tests missing on A relative to B were preserved. |
| e. Test inventory / assertions | FIXED | B: 432; A: 528; final: 545 collected. Zero test IDs lost from either branch. Four new regression tests. Existing assertion changes are script-path updates, not removed assertions. New A `importorskip` guards cover optional UI dependencies; with the full environment, collection completes. |
| f. Honest coverage | FIXED | `pyproject.toml:75` uses source `bugzilla_serving`, no omit, canonical clean-source path mapping and `fail_under=70`. Interrupted merged run measured 81.05%, **not a completed passing run**. Final full coverage is pending. |
| g. Contracts / hashes | PASS | Full merged contracts passed 37 tests before audit fixes. Subsequent bounded hash/schema checks pass. OpenAPI equals the real API snapshot and is unchanged from B. Phase 0 differences and inherited amendments are listed below. |
| h. Presets / registry | FIXED | `api/presets.py:18`: 300-second cache, champion exposed as Recommended, published tag presets, YAML fallback; execute validation. Fixed standalone registry versions that store config.yaml instead of params. Regression passes. Fast=S1/R1; Deep=S5, default dossier 4096 bytes, context 3000 under 4096 cap. Fallback Recommended is legacy S8 and is explicitly not champion. Actual evaluated Auto-router champion remains blocked by item i. |
| i. Auto-router / parity | FAIL-REPORTED | `tracking/final_registry.py:51` exercises Registry.get_config → executable → RunConfig. Evaluated S8v2 plus router/tool version fields are rejected. All three API probes return 422 `invalid_config`, without constructing a runner; new regression passes. Engine imports original AnswerGraph/Tools at `engine.py:195`. All three B9 safety routes fail at shared-config loading, before graph execution. Thus no answer/abstain/cited-ID/hash parity is claimed. See exact diagnosis below. |
| j. Quota / degradation | PASS | Existing `tests/a_quota/test_quota.py` covers daily 90% guard, degraded R0, status event, session 429/retry_after and quota shape. These passed in the interrupted merged run; bounded session-window test also passes after fixes. Full rerun remains pending. |
| k. SSE / authentication | FIXED | `tests/a_api/test_api.py:156` checks SSE order/payload against fixtures. All defined /v1 routes except health require the key. Disabled unauthenticated FastAPI docs/OpenAPI HTTP endpoints; programmatic schema is unchanged and regression passes. |
| l. LangSmith | PASS | `tracing.py:147`, `root_metadata` and `tests/a_tracing`: root project `ensf621-serving`, exact application metadata keys including **system_id** (binding spec spelling), sample/cap, user_rating, mocked SDK redaction. A checksum-valid private-comment bundle is rejected with no sentinel in the mocked trace (`test_private_bundle_comment_never_reaches_mocked_trace`); no live LangSmith validation. |
| m. Chat UI | PASS | AppTest for Ask and the other pages passed in the interrupted merged run. Final bounded AppTest repeats Ask, Cited bugs, History, About successfully. Existing UI tests cover abstention, option controls, inline 422 and research/torch separation; public Bugzilla URLs are constructed by the UI. No Windows execution claimed. |
| n. B9 dashboard | PASS | `tests/b_dashboard/test_final_dashboard.py:49` renders B9 tabs using synthetic results, including Auto-router naming and seven charts; bounded final run passes. `results_source.links` uses env links and omits missing/credential-bearing URLs. B9 source/tests preserved. |
| o. CI | FIXED | Original B SHA pins, read permissions, concurrency and lint/contracts/test/secrets/docker jobs retained. `ci.yml:183` now enables all-service Compose mock smoke. Added pinned-model provisioning before API builds. actionlint passes. GitHub execution is pending. |
| p. CD | FAIL-REPORTED | `cd.yml:114`: tag v*, manual deploy=false, three GHCR images, pinned actions, SSH secrets, R0 smoke, .last_good and rollback are present; actionlint passes. Deploy requires DEPLOY_HOST/USER/SSH_KEY, reachable Docker host, .env, real bundle and GHCR pull access. No secrets/host access was verified. Dual architecture follows A's Oracle A1 target; actual host architecture remains to confirm. |
| q. Docker | FAIL-REPORTED | Daemon 29.5.2 available via local escalation. Compose CI parses. API build fails at `COPY models ./models`: local models/ absent. No valid new API/chat/dashboard size or Compose smoke result. Previously cached dashboard images (1.67 GB readonly, 4.03 GB Lab) are **not** evidence of merged builds. All Compose files declare 8000/8501/8502; dashboard Lab disabled; real bundles read-only; production/local use .env; CI intentionally uses keyless mock env. Dockerfiles have healthchecks. |
| r. Linux launchers | FIXED | `scripts/app/run_local.sh`: safe .env parsing, BUNDLE_DIR/manifest verification, quoted paths, occupied-port checks, API/chat with optional --dashboard, child cleanup on Ctrl-C. `run_dashboard.sh` added. Syntax/help checks pass. Actual long-running startup is owner-run. |
| s. README / commands | FIXED | Added Linux/Windows paths, audit/spec links; fixed Quick start anchor and B9 paths. Static literal script-path scan finds zero missing paths, including frozen help-text compatibility wrappers. Windows and full user commands need owner execution. |

## Exact champion failure and contract changes for Faiz to approve

No new RunConfig fields, system IDs, config hash algorithm, MLflow/LangSmith names
or OpenAPI snapshot changes were introduced by these audit fixes.

The evaluated config from `tracking/final_results.py:134` contains:
`system_id=S8v2`, `router_rules_version=json-tools-v2`,
`tool_route_version=json-tools-v2`, top_k=10 and dossier=12000 bytes.
RunConfig accepts S0–S8/R0/ORACLE and forbids extra fields. Consequently:

1. Registry/Lab config loading raises validation errors for system_id and version fields.
2. `/v1/ask` responds 422 `invalid_config` naming these fields; zero inference occurs.
3. Even adding the ID alone would run the original graph unless engine dispatch also
   selects AnswerGraphV2 and ToolsV2. Substituting S8 would serve a different method.
4. Shrinking the evaluated 12000-byte dossier to a serving budget would create a
   new configuration needing development validation, not parity for the evaluated config.

This requires a coordinated contract + graph-dispatch + fixture/preset change,
so it is reported rather than silently rewritten. The current promotion refusal
is retained; the live-smoke script refuses an unsupported/non-champion router
before asking any question. No registry alias was changed.

Inherited changes for Faiz's review (not newly invented here):

| Shared surface | Change / reason |
| --- | --- |
| configs/serving.yaml | A added tracing defaults sample=0.2 and daily_cap=150, consumed by API startup. Retained for configurable trace limits. |
| Phase 0 → B amendments | Dossier max increased from 4096 to 12000 **bytes**, separate from model's 4096 context cap; RunConfig validates these independently. Existing B amendment retained, not approval of a new serving champion. |
| Phase 0 → B metric names | Added answer.macro_excl_F5, answer family pending counts, cost.llm_calls_per_question and cost.usage_missing_n to retain denominator/cost provenance. No project/model/alias/feedback names changed. |
| OpenAPI | First committed complete snapshot is 7e61959; no diff from that snapshot to final. b66c630 predates the checked-in snapshot. |

`git diff 7e61959 -- src/bugzilla_serving/contracts configs/serving.yaml tests/contracts/openapi.json`
shows the inherited amendments; `git diff f2cb612` on the same paths shows only
A's tracing YAML block. Ask Faiz to approve that retained addition and confirm
historical amendments before treating the integrated contract as jointly approved.

## Tests, lint and coverage before / after

| Check | Before f2cb612 | Final audit state |
| --- | --- | --- |
| Ruff check | Passed | Passed |
| Ruff format --check | 95 files formatted | 137 files formatted |
| Collection | 432 tests | 545 tests; A separately collected 528 |
| Full offline tests | Interrupted snapshot runs; no reliable complete baseline | Interrupted at owner's request: 537 passed, 1 failed; no skipped/xfail/deselected reported before interruption. Failure isolated checkout .env leakage; fixed by fixture isolation and short regression. No final full count is claimed. |
| Coverage | Interrupted baseline snapshot measured 72.45%; invalid as a full baseline (Git-index mismatch affected clean-copy test) | Interrupted merged measurement 81.05% over all serving modules, before final fixes; not final validated coverage |
| Contracts | Not separately rerun on original snapshot | 37 passed pre-fixes; final bounded hash/OpenAPI checks pass |
| Final smoke checks | — | 8 passed in 4.69 s (API/schema/presets/credential isolation/dashboard); 7 passed in 1.06 s (hash/dev split/session/metadata/three secondary UI pages); 2 passed in 1.53 s for private-comment trace refusal and Ask AppTest; 3 CI/coverage-config checks passed in 0.06 s; earlier 4-test isolation regression passed |
| Actionlint | Original CI retained | Both ci.yml and cd.yml pass |
| Gitleaks | — | 38 commits scanned, no leaks before final fix commit; repeat command below for final history |
| Docker | Existing cached images only | API build blocked by missing models; remaining builds/smoke delegated |

Some earlier broad runs were deliberately stopped or timed out; their partial dot
output is not counted as a pass. Diagnostic logs are local under
`/tmp/bugzilla-integration-audit/`, outside Git. No large logs or coverage reports
are committed. Test collection on both isolated snapshots copied source/fixtures
and one review-server Python file only; locked benchmark questions/gold were not copied.

Coverage configuration before A's change was `source=[bugzilla_serving]` with
canonical clean-source remapping and no omit. A added `omit=[*/pytest-of-*/*]`;
it omitted copied sources, not a named serving package. This conflicted with B's
clean-copy coverage test. Final config removes it and retains all serving modules.
The offline pytest fixture now ignores the checkout .env, still reads temporary
fixture .env files, restores startup environment defaults, and denies external HTTP.

## Files changed by the audit fixes

- `.gitattributes`
- `.github/workflows/ci.yml`
- `README.md`
- `compose.ci.yaml`
- `docs/RESEARCH_STATUS.md`
- `docs/mlops/B9_DASHBOARD.md`
- `docs/mlops/INTEGRATION_AUDIT.md`
- `pyproject.toml`
- `scripts/app/live_smoke.py`
- `scripts/app/run_dashboard.py`
- `scripts/app/run_dashboard.sh`
- `scripts/app/run_dev_dashboard.sh`
- `scripts/app/run_local.sh`
- `scripts/build_results_pack.py`
- `scripts/log_final_results.py`
- `scripts/mlops/build_results_pack.py`
- `scripts/mlops/log_final_results.py`
- `scripts/mlops/register_all_systems.py`
- `scripts/phases/run_phase11_evaluation.sh`
- `scripts/phases/run_phase12_live_smoke.sh`
- `scripts/register_all_systems.py`
- `scripts/run_dashboard.py`
- `scripts/run_dev_dashboard.sh`
- `scripts/run_eval_extension.sh`
- `scripts/run_phase05_generate_benchmark.sh`
- `scripts/testing/smoke.sh`
- `src/bugzilla_serving/api/app.py`
- `src/bugzilla_serving/api/presets.py`
- `src/bugzilla_serving/dashboard/README.md`
- `src/bugzilla_serving/dashboard/app.py`
- `src/bugzilla_serving/experiments/parity.py`
- `tests/a_api/test_api.py`
- `tests/a_tracing/test_tracing.py`
- `tests/b_ci/pytest_offline.py`
- `tests/b_ci/test_ci.py`
- `tests/b_dashboard/test_final_dashboard.py`

The deleted top-level B9 script names above are rename provenance, not runnable
commands. Their replacements are under app/ or mlops/. The complete merge's
changed-file list can be inspected with `git diff --name-status efa8bd5^1 efa8bd5`.

## Numbered owner commands and expected output

Run long checks yourself. None of these commands pushes until step 6.
Do not publish/promote the evaluated Auto-router while item i is unresolved.

1. **Full offline checks and coverage** (Linux, existing checkout):

   ```bash
   cd "/home/ict317/master's/ENSF 621/Project"
   conda activate iqfm
   export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
   export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
   python -m ruff check
   python -m ruff format --check
   actionlint .github/workflows/ci.yml .github/workflows/cd.yml
   python -m pytest --collect-only -q
   bash scripts/testing/test_coverage.sh
   gitleaks detect --log-opts="origin/main..HEAD" --redact
   ```

   Expected: Ruff/actionlint clean; 545 collected after the final privacy test;
   full pytest exit 0 and coverage >=70%, with reports in ignored
   results/coverage/. **Full pass count and final percentage are pending your run.**
   The tested actionlint/gitleaks binaries are also available locally in
   `/tmp/bugzilla-ci-tools/`; add that directory to PATH if needed.
   Windows coverage: `.\scripts\testing\test_coverage.ps1` (Docker).

2. **Build all three images and run Compose CI smoke** (long downloads/builds):

   ```bash
   python scripts/app/fetch_models.py --dry-run
   python scripts/app/fetch_models.py
   docker compose -f compose.ci.yaml config --quiet
   docker compose -f compose.ci.yaml build
   docker image inspect bugzilla-api:ci bugzilla-chat:ci bugzilla-dashboard:ci --format '{{.RepoTags}} {{.Size}}'
   docker compose -f compose.ci.yaml up -d
   bash scripts/testing/smoke.sh
   docker compose -f compose.ci.yaml logs --no-color --tail 100
   docker compose -f compose.ci.yaml down -v
   ```

   Expected: pinned models provisioned; build exit 0; actual image sizes printed;
   health/ready, all preset asks, feedback and both UIs pass against mock evidence.
   On failure, keep logs before down. This has **not** passed locally in this audit.
   Model downloads are retrieval weights, not LLM/MLflow/LangSmith calls.

3. **Linux without Docker**, after setting local `.env` and receiving the real dev bundle:

   ```bash
   bash scripts/app/run_local.sh --dashboard
   ```

   Expected: verified manifest first; API :8000, chat :8501, dashboard :8502.
   One Ctrl-C stops all children. Omit `--dashboard` for only API/chat.
   Standalone dashboard: `bash scripts/app/run_dashboard.sh`.
   Windows equivalent: `.\scripts\app\run_local.ps1` (optional `-NoDashboard`).

4. **Local Docker**, after stopping step 3 to free ports:

   ```bash
   docker compose -f compose.local.yaml config --quiet
   docker compose -f compose.local.yaml up --build
   # Ctrl-C, then:
   docker compose -f compose.local.yaml down
   ```

   Expected: same three ports, actual `.env`, read-only serving bundle, dashboard
   Lab disabled. Do not use CI fixture results to claim real-answer quality.

5. **Four-question live smoke and observability — currently gated**:

   ```bash
   bash scripts/phases/run_phase12_live_smoke.sh --dry-run --limit 4 --max-requests 4
   # After coordinated S8v2 contract/adapter support and explicit champion publication:
   bash scripts/phases/run_phase12_live_smoke.sh --enable-llm --limit 4 --max-requests 4 \
     --bug-id "$DEV_BUG_ID" --comment-ref "$PUBLIC_COMMENT_REF" --resume
   ```

   Supply a public bug/comment reference from the **dev serving bundle**, never
   test questions or gold. It checks database, cited-comment dossier, Smart search
   and unanswerable engineer-hours behavior. Dry-run makes zero requests. Current
   live mode refuses without an executable S8v2 champion and sends **zero asks**.
   Once support is implemented, expected state is COMPLETE with four successful
   probes; otherwise REFUSED/PARTIAL and exit 2. The max-requests cap counts API
   ask requests, **not underlying model calls** (API can allow up to 32 per ask).
   The provider's quota guard still applies; this is not a four-model-call budget.
   A failed in-flight request consumes its reservation; missing model usage is flagged rather than reported as a known zero. Returned config_hash must match the selected Groq champion. Resume will not replay
   completed probes or silently accept changed inputs. Check timestamps and
   summary/log paths under ignored outputs/serving/live-smoke/.

   Set TRACE_SAMPLE=1 and a sufficient TRACE_DAILY_CAP in the **API process** for
   this owner test, then restore normal sampling. The summary lists request IDs
   and LangSmith run IDs; open project `ensf621-serving` and inspect config_hash,
   preset_slug, system_id, model, retriever, corpus, route, degraded, request_id,
   session_id. For explicit feedback, add `--feedback-score 0` or
   `--feedback-score 1` when running the probes. Expect `user_rating` feedback
   with comment "Owner live smoke feedback" on the same traced run. Missing
   tracing credentials/sample selection means local feedback only; no remote
   trace/feedback success is promised. This script has only been dry-run here.

6. **Push and open the integration PR only after reviewing the remaining failures**:

   ```bash
   git status --short
   git log --oneline feature/mlops..integration/merge-audit
   git push -u origin integration/merge-audit
   gh pr create --base feature/mlops --head integration/merge-audit \
     --title "Integrate Stream A serving and audit Stream B compatibility" \
     --body-file docs/mlops/INTEGRATION_AUDIT.md
   ```

   Expected: PR targets feature/mlops with merge and audit history. Keep it draft
   or explicitly document item i until agreed; no push/PR was performed by the agent.
   If using gh before acceptance, add `--draft` to the command.

7. **After that PR merges and feature/mlops is verified, open the main PR**:

   ```bash
   gh pr create --base main --head feature/mlops \
     --title "Integrate MLOps serving and development dashboard" \
     --body-file docs/mlops/INTEGRATION_AUDIT.md
   ```

   Expected: feature/mlops → main; do not deploy or tag a release based on this
   report alone. CD manual dispatch with deploy=false should skip SSH deployment;
   it still runs smoke/build/push jobs and needs GHCR package-write permissions.

## Open questions

1. Approve a coordinated S8v2/version-field contract and true V2 engine adapter,
   or deliberately keep the evaluated Auto-router research-only? Which newly
   evaluated serving-compliant dossier budget should be used if it changes?
2. Confirm the pre-existing shared-contract amendments and A's tracing YAML block.
3. Should intentionally tracked outputs/releases remain as research handoff assets?
   A blanket removal would conflict with the repository's frozen-release workflow.
4. Supply/confirm the deploy host architecture, three DEPLOY_* secrets, real bundle
   and GHCR permissions. No credential values should be shared in chat or Git.
5. Run steps 1–2 and retain their final counts, coverage and actual image sizes.
   These are the remaining execution gates, not claimed completed results.

## Every deletion on A relative to the merge-base (118 paths)

Generated build copies and reports only; names listed without reading their data.
B9 deletions visible when comparing the two tips were not merge-base deletions and
were preserved by the three-way merge.

```text
.coverage
build/lib/bugzilla_qa/__init__.py
build/lib/bugzilla_qa/answering/__init__.py
build/lib/bugzilla_qa/answering/backend.py
build/lib/bugzilla_qa/answering/calibration.py
build/lib/bugzilla_qa/answering/cli.py
build/lib/bugzilla_qa/answering/contracts.py
build/lib/bugzilla_qa/answering/graph.py
build/lib/bugzilla_qa/answering/runner.py
build/lib/bugzilla_qa/answering/sources.py
build/lib/bugzilla_qa/answering/tools.py
build/lib/bugzilla_qa/answering/upload.py
build/lib/bugzilla_qa/app/__init__.py
build/lib/bugzilla_qa/benchmark/__init__.py
build/lib/bugzilla_qa/benchmark/assisted_review.py
build/lib/bugzilla_qa/benchmark/dev_supplement.py
build/lib/bugzilla_qa/benchmark/phase05.py
build/lib/bugzilla_qa/benchmark/v3.py
build/lib/bugzilla_qa/benchmark/v3_freeze.py
build/lib/bugzilla_qa/benchmark/v3_rules.py
build/lib/bugzilla_qa/benchmark/v3_source.py
build/lib/bugzilla_qa/benchmark/v3_validate.py
build/lib/bugzilla_qa/benchmark/v3_verify.py
build/lib/bugzilla_qa/data/__init__.py
build/lib/bugzilla_qa/data/normalize.py
build/lib/bugzilla_qa/data/phase04.py
build/lib/bugzilla_qa/data/profile.py
build/lib/bugzilla_qa/eval_extension/__init__.py
build/lib/bugzilla_qa/eval_extension/audit.py
build/lib/bugzilla_qa/eval_extension/bank.py
build/lib/bugzilla_qa/eval_extension/cli.py
build/lib/bugzilla_qa/eval_extension/contracts.py
build/lib/bugzilla_qa/eval_extension/dense.py
build/lib/bugzilla_qa/eval_extension/diagnose.py
build/lib/bugzilla_qa/eval_extension/generation.py
build/lib/bugzilla_qa/eval_extension/m3_adapter.py
build/lib/bugzilla_qa/eval_extension/m3_repair.py
build/lib/bugzilla_qa/eval_extension/metrics.py
build/lib/bugzilla_qa/eval_extension/pipeline.py
build/lib/bugzilla_qa/eval_extension/plots.py
build/lib/bugzilla_qa/eval_extension/retrieval.py
build/lib/bugzilla_qa/eval_extension/robustness.py
build/lib/bugzilla_qa/evaluation/__init__.py
build/lib/bugzilla_qa/evaluation/experiment.py
build/lib/bugzilla_qa/evaluation/phase06.py
build/lib/bugzilla_qa/evaluation/review.py
build/lib/bugzilla_qa/evaluation/scoring.py
build/lib/bugzilla_qa/evaluation/shared_dev.py
build/lib/bugzilla_qa/evaluation/shared_source.py
build/lib/bugzilla_qa/evaluation/systems.py
build/lib/bugzilla_qa/file_lock.py
build/lib/bugzilla_qa/llm/__init__.py
build/lib/bugzilla_qa/llm/provider.py
build/lib/bugzilla_qa/methods/__init__.py
build/lib/bugzilla_qa/methods/contract.py
build/lib/bugzilla_qa/methods/generation.py
build/lib/bugzilla_qa/methods/local_model.py
build/lib/bugzilla_qa/methods/m3_intent.py
build/lib/bugzilla_qa/methods/m3_sql.py
build/lib/bugzilla_qa/retrieval/__init__.py
build/lib/bugzilla_qa/retrieval/bm25.py
build/lib/bugzilla_qa/retrieval_v3/__init__.py
build/lib/bugzilla_qa/retrieval_v3/cli.py
build/lib/bugzilla_qa/retrieval_v3/common.py
build/lib/bugzilla_qa/retrieval_v3/corpus.py
build/lib/bugzilla_qa/retrieval_v3/datasets.py
build/lib/bugzilla_qa/retrieval_v3/metrics.py
build/lib/bugzilla_qa/retrieval_v3/registry.py
build/lib/bugzilla_qa/retrieval_v3/runner.py
build/lib/bugzilla_qa/retrieval_v3/selection.py
build/lib/bugzilla_qa/retrieval_v3/transforms.py
build/lib/bugzilla_serving/__init__.py
build/lib/bugzilla_serving/api/__init__.py
build/lib/bugzilla_serving/api/stub.py
build/lib/bugzilla_serving/chat_ui/__init__.py
build/lib/bugzilla_serving/contracts/__init__.py
build/lib/bugzilla_serving/contracts/api_models.py
build/lib/bugzilla_serving/contracts/names.py
build/lib/bugzilla_serving/contracts/records.py
build/lib/bugzilla_serving/contracts/run_config.py
build/lib/bugzilla_serving/dashboard/__init__.py
build/lib/bugzilla_serving/dashboard/app.py
build/lib/bugzilla_serving/dashboard/data/__init__.py
build/lib/bugzilla_serving/dashboard/data/common.py
build/lib/bugzilla_serving/dashboard/data/langsmith_source.py
build/lib/bugzilla_serving/dashboard/data/mlflow_source.py
build/lib/bugzilla_serving/dashboard/lab.py
build/lib/bugzilla_serving/dashboard/pages/answer_eval.py
build/lib/bugzilla_serving/dashboard/pages/compare_runs.py
build/lib/bugzilla_serving/dashboard/pages/cost_latency.py
build/lib/bugzilla_serving/dashboard/pages/error_analysis.py
build/lib/bugzilla_serving/dashboard/pages/experiment_lab.py
build/lib/bugzilla_serving/dashboard/pages/overview.py
build/lib/bugzilla_serving/dashboard/pages/presets_page.py
build/lib/bugzilla_serving/dashboard/pages/production.py
build/lib/bugzilla_serving/dashboard/pages/retrieval_eval.py
build/lib/bugzilla_serving/dashboard/theme.py
build/lib/bugzilla_serving/dashboard/views.py
build/lib/bugzilla_serving/engine.py
build/lib/bugzilla_serving/experiments/__init__.py
build/lib/bugzilla_serving/experiments/data.py
build/lib/bugzilla_serving/experiments/fixtures.py
build/lib/bugzilla_serving/experiments/preflight.py
build/lib/bugzilla_serving/experiments/runner.py
build/lib/bugzilla_serving/experiments/scoring.py
build/lib/bugzilla_serving/experiments/sweep.py
build/lib/bugzilla_serving/tracking/__init__.py
build/lib/bugzilla_serving/tracking/backfill.py
build/lib/bugzilla_serving/tracking/client.py
build/lib/bugzilla_serving/tracking/policy.py
build/lib/bugzilla_serving/tracking/registry.py
coverage.xml
junit.xml
src/firefox_history_qa.egg-info/PKG-INFO
src/firefox_history_qa.egg-info/SOURCES.txt
src/firefox_history_qa.egg-info/dependency_links.txt
src/firefox_history_qa.egg-info/requires.txt
src/firefox_history_qa.egg-info/top_level.txt
```

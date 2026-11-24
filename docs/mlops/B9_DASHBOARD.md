# B9 — final development results dashboard

Implemented and smoke-tested offline. No model calls or DagsHub writes were made.
Publication and registration below are owner commands; default is dry-run.

## Expected → found / diagnosis before edits

| Expected | Found |
| --- | --- |
| Current dashboard startup | Started a local Streamlit server on port 8519. Sandbox socket restriction required local-only escalation. |
| AppTest on every old page | All nine pages passed against the saved real snapshot; no page exception was reproduced. |
| Reported PyTorch traceback | Reproduced directly in Streamlit's `get_module_paths(torch.classes)`. |
| Final data | B8 pack, 122 eligible development questions, imported external Reasons judgments, all present. |
| Serving loader for evaluated router | Unsupported. Shared contract accepts the earlier implementation only; API is still a Phase 0 stub. |

The reported traceback is Streamlit's file watcher inspecting PyTorch's dynamic
`__path__` attribute. It is not evidence of a scorer or dashboard-page failure.
The old app also read the legacy MLflow snapshot, not B8; a missing snapshot started
a synchronous remote rebuild (the saved real build took 89.7 seconds). The new app
loads B8 directly and never imports research/model code for its ordinary tabs.
The launcher disables the incompatible file watcher, including for Advanced pages.
There is no blanket exception handler that hides failures.

Full pre-edit diagnostics: `outputs/analysis/b9/before_tracebacks.log`,
`before_apptest.json`, `watcher_traceback.log`. The watcher traceback was:

```text
Traceback (most recent call last):
  File "/home/ict317/miniconda3/envs/iqfm/lib/python3.11/site-packages/streamlit/watcher/local_sources_watcher.py", line 217, in get_module_paths
    potential_paths = extract_paths(module)
  File "/home/ict317/miniconda3/envs/iqfm/lib/python3.11/site-packages/streamlit/watcher/local_sources_watcher.py", line 210, in <lambda>
    lambda m: list(m.__path__._path),
  File "/home/ict317/miniconda3/envs/iqfm/lib/python3.11/site-packages/torch/_classes.py", line 13, in __getattr__
    proxy = torch._C._get_custom_class_python_wrapper(self.name, attr)
RuntimeError: Tried to instantiate class '__path__._path', but it does not exist! Ensure that it is registered via torch::class_
```

## What changed

- Three tabs: Results, Compare, How it works & links. Password gate retained.
  The earlier router is removed before renaming the evaluated router. Sources are
  Core benchmark, Extended benchmark and Natural rewrites.
- Local CSV-first loading; validated required headers. With no local pack and a
  configured tracking URI, fetch the latest `results_pack=true` final-results run.
  Downloads are stored under the run ID and content hash, and the lookup is cached
  ten minutes. Ordinary local views do not contact MLflow.
- Missing data names the builder command. This builder extends existing B8 inputs;
  it cannot invent missing ledgers or recreate B8 from nothing. Restore the pack or
  run its original saved build script when starting from an empty machine.
- Links use explicit environment variables only. A final-experiment link uses the
  public experiment-ID receipt written by a successful remote publication; optional
  `DASHBOARD_REMOTE_ENABLED=true` allows lookup by name on a separate machine.
  No remote lookup is made just to render links for a local pack by default.
- Advanced is absent unless `DASHBOARD_ADVANCED=true`. Lab additionally retains
  its existing `DASHBOARD_LAB_ENABLED` controls. The earlier router is excluded
  from Lab choices in this app, and the evaluated router is explicitly unavailable
  pending serving support. Production retains its existing fixture/live source gate.
- `legacy_app.py` is a regression harness for retained old page modules, not a
  link or page in the current app. Old tests explicitly target that harness;
  new tests exercise the actual three-tab entrypoint.

### Cost meaning

`python scripts/build_results_pack.py` writes `system_cost.csv` and prints:

```text
calls/question = (0*82 + 15 + 2.08*23 + 1.016*6 + 1)/122 = 0.573246
tokens/question = (44317 + 2400.272*23 + 1999.184*6)/122 = 914.084918
```

These are route-weighted estimates including the historical model answers, not
just the last invocation's one failed call. Failed-call tokens remain unknown.
Query rewriting shares Smart search's figures. Original costs were measured on
125 pilot questions; accuracy uses 122 eligible questions. Auto-router p50/p95
are shown per route in `route_latency.csv`, derived from the saved question
latencies: 82 parser answers, four preserved database-model answers, six pinned
dossiers, 23 original Smart search answers, six original dossier answers and one
failed request. No pooled percentile is invented or logged as zero. Its
MLflow run has route-specific latency metrics and an explicit missing-pooled-time
tag instead of invalid `latency_p50_s` / `latency_p95_s` metrics.

## Owner commands

Stop an existing local Streamlit server with Ctrl+C before relaunching.
Run from the existing repository root; activate `iqfm` first. Paths with spaces
and apostrophes are supported. No CI test requires `.env`.

1. Build cost data and launch:

   ```bash
   conda activate iqfm
   export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
   python scripts/build_results_pack.py
   scripts/run_dev_dashboard.sh
   ```

   Expected: cost file COMPLETE; open http://localhost:8502. Three tabs, nine
   systems, 122 questions, Auto-router 92.5%, interval 87.5–96.8%, 82/122 local
   answers. Warm AppTest reruns measured below three seconds (about 0.23 s in
   the initial local smoke test). To enable Advanced, set `DASHBOARD_ADVANCED=true`;
   Lab controls additionally require `DASHBOARD_LAB_ENABLED=true`.
   To load link/password environment settings explicitly from the owner’s local
   file, use `DASHBOARD_ENV_FILE=.env scripts/run_dev_dashboard.sh` (no secrets
   are printed). Without that option the dashboard does not require `.env`.

2. Preview, then log final results with credentials from the owner's local file:

   ```bash
   python scripts/log_final_results.py --env-file .env
   python scripts/log_final_results.py --env-file .env --apply
   ```

   Expected: DRY_RUN then APPLIED. Nine named system runs plus results-pack in
   final-results. Existing 24 research-retrieval-eval runs receive display tags;
   missing pairs are logged once in final-retrieval. Repeating creates no duplicate
   runs. No model calls occur. Params preserve actual historical config values;
   raw original B8 CSV artifacts remain an audit trail, while the app filters the
   earlier router. No new run is created for that earlier router.

3. Preview registry and safety checks; register evaluated configs without moving
   champion while serving support is blocked:

   ```bash
   python scripts/register_all_systems.py --env-file .env
   python scripts/register_all_systems.py --env-file .env --apply
   ```

   Expected: dry-run prints database/dossier/search FAIL at the shared loader.
   Apply creates/reuses nine config versions, in the requested order, Auto-router
   last/newest. System-slug aliases and `fast` are assigned; existing versions are
   retained. The Auto-router version is marked serving-blocked. Champion remains
   unchanged. A source run must exist first and its config.yaml must match exactly.

4. Requested champion command (currently refuses safely):

   ```bash
   python scripts/register_all_systems.py --env-file .env --apply --move-champion
   ```

   Expected now: REFUSED, exit 2, no registry writes and no champion change.
   After Stream A provides actual loader/engine support, all three route checks
   must PASS. The promotion-policy result is recorded; the owner-specified override
   reason applies only to policy, never to failed serving checks. Dry-run exercises
   the existing `Registry.get_config → executable → RunConfig` path using the
   proposed local artifact, because no new remote version exists yet. Promotion
   rechecks the actual registered version through Registry.get_config.

5. Verify on DagsHub: open the configured repository's MLflow UI, choose
   **final-results**, select named system runs and **Compare**. Open **results-pack**
   artifacts for the CSVs. Open **Models → bugzilla-qa-config → Versions**: the
   newest new version is Auto-router; inspect its source run, config artifact,
   serving status and aliases. Existing champion should be unchanged until serving
   support is implemented. The dashboard's environment-driven link buttons point
   to these locations when configured; no repository URL is guessed.

6. Rebuild/restart the dashboard without changing Stream A's compose files:

   ```bash
   docker build -f docker/dashboard.Dockerfile --target dashboard-readonly -t bugzilla-dashboard:dev .
   docker stop bugzilla-dev-dashboard
   docker rm bugzilla-dev-dashboard
   docker run -d --name bugzilla-dev-dashboard -p 8502:8502 \
     --mount "type=bind,source=$PWD/outputs/analysis/results_pack,target=/app/outputs/analysis/results_pack,readonly" \
     --entrypoint python bugzilla-dashboard:dev \
     -m streamlit run src/bugzilla_serving/dashboard/app.py \
     --server.address=0.0.0.0 --server.port=8502 --server.fileWatcherType=none
   ```

   Stop/remove only if that named development container already exists. Expected:
   local pack available immediately, no inference or background snapshot rebuild.
   Pass the existing `DASHBOARD_PASSWORD` securely if using the password gate.
   The explicit entrypoint bypasses the old image's background snapshot builder.
   For remote pack fallback, pass `--env-file .env` to docker run and provide a
   writable cache mount; do not mount a local pack if testing remote fallback.
   These Docker commands were prepared, not executed by the agent.

## Open questions for Stream A

1. `src/bugzilla_serving/contracts/run_config.py:RunConfig.system_id` cannot load
   the evaluated identity or variant metadata. Contracts were not edited.
2. `src/bugzilla_serving/engine.py:Runner.__init__, Runner.run / ProgressGraph`
   uses the original research graph/tools. It must explicitly dispatch the
   evaluated JSON-tool/parser/pinned-comment implementation and preserve its
   runtime identity; renaming the earlier router would publish the wrong behavior.
3. `src/bugzilla_serving/api/stub.py:create_app` is still a Phase 0 stub. There is
   no implemented API config loader to call. The registry check uses the existing
   shared Registry.get_config path and reports this limitation honestly.
4. `docker/dashboard-entrypoint.sh` starts the old snapshot builder automatically.
   It is outside this task's allowed edit paths; use the explicit container
   entrypoint above or have the owning stream remove that obsolete startup job.

These blockers prevent champion promotion, not offline results browsing or storing
all nine evaluated config artifacts. No override can bypass them.

## Files and verification

Changed application files:

- `src/bugzilla_serving/dashboard/app.py`, `results_source.py`, `results_app.py`,
  `theme.py`, `views.py`, `legacy_app.py`, `README.md`.
- `src/bugzilla_serving/tracking/final_results.py`, `final_registry.py`, `environment.py`.
- `scripts/build_results_pack.py`, `log_final_results.py`, `register_all_systems.py`,
  `run_dashboard.py`, `run_dev_dashboard.sh`.
- `tests/b_dashboard/test_final_dashboard.py`, the 13 trimmed CSV fixtures under
  `tests/b_dashboard/fixtures/results_pack/`, and legacy entrypoint references in
  `test_dashboard.py` / `test_launch.py`.
- `tests/b_tracking/test_final_publication.py`, this runbook and `docs/AGENT_NOTES.md`.
- Generated `system_cost.csv`, `route_latency.csv` and the added CSV links in the
  existing `outputs/analysis/results_pack/results_pack.md`; diagnostic/test logs
  under `outputs/analysis/b9/`.

Pre-existing `configs/display_catalog.yaml` and `docs/verdicts.jsonl` edits were
not changed. No staging, commit, push, remote write or dependency installation.
No new dependency was needed: explicit settings loading uses only the standard
library, supports quoted values, never executes shell expressions, and does not
load model-provider keys.

75 distinct focused tests passed in bounded runs: retained dashboard 21, retained
B5 9, tracking 28, final UI 8, final publication 3, byte identity 1, scorer selector
2, contract secret scan 1 and real localhost launch 2. The final 12-test group
passed in about 11 seconds. Registry tests retain a pre-existing version and
champion, append the nine new versions in order, verify no duplicates on rerun,
and confirm failed promotion leaves the existing champion intact. Updates to lower
metric values are also tested. Ruff check/format passed; the B8 validator still
passes. Existing dependency Pydantic warnings remain.

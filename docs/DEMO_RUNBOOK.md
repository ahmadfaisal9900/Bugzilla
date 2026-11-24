# Demo runbook

## S8v2 serving prerequisite (2026-11-23)

The owner confirmed the running registry champion was S2 / R7b / C1, Fast was
S1, and Deep read was unpublished. The reported 1809146 question used Smart
search. The local bundle has no comments for 1809146; do not promise a cited
comment answer for that ID.

The serving adapter now selects `AnswerGraphV2` and `ToolsV2` for S8v2, preserving
all research files. Four synthetic routes pass API TestClient / Lab experiment
runner parity (identical answers, routes and config hashes). This proves wiring,
not live answer quality. The 92.5% figure describes the historical development
composite; the serving dossier cap differs from the evaluated 12,000-byte cap.

Contract changes for Faiz:

- `RunConfig.system_id` additionally accepts `S8v2` (no S8 substitution).
- Optional `router_rules_version` and `tool_route_version` accept `json-tools-v2`,
  applicable to S8v2. Unset extension fields preserve legacy config hashes.
- S8v2 execute validation caps `s5_dossier_budget` at 4,096 UTF-8 bytes.
  Existing legacy S5/S8 record limits are retained for historical compatibility.
- `/v1/options` exposes corresponding choices; OpenAPI snapshot includes the new
  enum and optional fields. Answer, evidence, SSE and endpoint shapes are unchanged.

## Owner-run promotion and rollback

From the existing repository root, activate `iqfm`. Set `PYTHONPATH=src` and use
`.env` for existing MLflow credentials. Never paste credentials into commands.
The following commands make no Groq calls. Preview is the default. The B9 CLI's
`--serving-demo` path publishes only capped serving configurations, leaving the
immutable evaluated registrations alone.

1. Preview and save the **previous_champion** version (S2) for rollback:

   ```bash
   PYTHONPATH=src python scripts/mlops/register_all_systems.py --env-file .env --serving-demo --dry-run
   ```

   Expected: `state: DRY_RUN`, S8v2 Recommended, S5 Deep read (4096), and
   `fast_unchanged` identifying S1. If fast is missing or is not S1, it refuses.

2. Apply explicitly:

   ```bash
   PYTHONPATH=src python scripts/mlops/register_all_systems.py --env-file .env --serving-demo --apply
   ```

   Expected: `state: APPLIED`, new/reused Recommended and Deep read versions,
   champion points to the capped S8v2 version. Fast alias is never written.

3. Stop the existing launcher with Ctrl-C, then restart:

   ```bash
   TRACE_SAMPLE=1.0 bash scripts/app/run_local.sh
   ```

   In another terminal with `SERVING_API_KEY` loaded:

   ```bash
   curl -fsS --max-time 10 -H "X-API-Key: ${SERVING_API_KEY}" http://localhost:8000/v1/presets
   ```

   Expected: Recommended `is_champion=true`, `config.system_id=S8v2`; Fast=S1;
   Deep read=S5 and `s5_dossier_budget=4096`. A fallback preset has
   `is_champion=false`; that is not proof of registry promotion.

4. Roll back if live checks fail (replace `S2_VERSION` with step 1's version):

   ```bash
   PYTHONPATH=src python scripts/mlops/register_all_systems.py --env-file .env --serving-demo --rollback-version S2_VERSION --dry-run
   PYTHONPATH=src python scripts/mlops/register_all_systems.py --env-file .env --serving-demo --rollback-version S2_VERSION --apply
   ```

   Restart and check presets again. Rollback refuses any target whose config is
   not S2; Fast remains unchanged. YAML fallback deliberately remains S8v2, so
   verify registry connectivity and `is_champion=true` after rollback.

## B11 routing and checks

`serving_bug_scope` is a new optional boolean contract field. Presets set it to
true and include it in their config hashes. Unset values preserve legacy hashes
and retrieval behavior, so historical S1/S2 configs are unchanged. It restricts
explicit-ID text retrieval to the named bugs' public chunks. All modes check
cohort membership before provider use. S8v2 adds discussion wording and an
explicit-ID dossier fallback after existing structured rules. The dossier packs
metadata, the earliest available comment and recent comments, then links/history;
truncation is marked within the conservative byte cap. It cannot certify that
the earliest archived comment is Bugzilla comment 0 when that record is absent.

The final offline route diff is **6/122 changed**, all formerly ambiguous export
snapshot timestamp questions. Every question is listed in `DEMO_ROUTE_DIFF.md`;
no rules were tuned on them. No new evaluation accuracy is claimed.

There are 24 dev demo cases. CI runs their router and tiny synthetic evidence
checks; the same retrieval-only assertions were also checked against the local
real C1 bundle (10 passed, zero model calls). The API/Lab wiring and contract
subset passed (10 tests). A broader contract/API run reached its 30-second cap
without a completed result; the full suite remains an owner-run job.

The mock checker uses four explicitly synthetic questions for the Compose
fixture. It checks routes, sources, errors and latency; generated answer quality
and semantic citations are tested only by `--live`. Its output says this clearly.
No production question or expected answer is sent to a mock provider.

Owner-run validation (commands preview by default):

```bash
bash scripts/phases/run_phase11_demo_validation.sh --stage checks --dry-run
bash scripts/phases/run_phase11_demo_validation.sh --stage checks --run --run-dir results/demo_jobs/checks
bash scripts/phases/run_phase11_demo_validation.sh --stage routes --limit 122 --run --run-dir results/demo_jobs/routes
```

Expected: checks stage COMPLETE only if the full offline pytest suite, Ruff and
installed actionlint pass. Routes reports 122 questions and six changes. Each
stage writes timestamps, logs and summary.json. Add `--resume` with the same
`--run-dir` to reuse successful commands; changed code/config refuses resume.
Failed live cases are retained and never automatically re-requested.

For a running **synthetic/mock** API (including CI Compose):

```bash
SERVING_API_KEY=ci-smoke-key python scripts/testing/demo_check.py --mock
```

Expected: four PASS wiring rows and a timestamped JSON in `results/demo_check/`.
For the real API, use the four live route cases below. The script checks that
Recommended really is the S8v2 registry champion before sending any question.

```bash
PYTHONPATH=src python scripts/testing/demo_check.py --live --case field,cited-why,find-description-1,outside --max-requests 5 --dry-run
PYTHONPATH=src python scripts/testing/demo_check.py --live --case field,cited-why,find-description-1,outside --max-requests 5
```

The four questions are printed in `tests/demo/demo_cases.yaml`: component of
1809146 (database), cited reason in 1708248 (dossier), the popupNode/triggerNode
report (Smart search), and bug 1000000 (decline). Expect about **3 normal Groq
calls**, with a conservative **5-call upper bound** including repairs; database
and out-of-archive cases need zero. This is more precise than a 4–6-call estimate.
A lower cap is refused before API calls. Results must be reviewed before claiming
live success. Never run the full live suite unintentionally.

After a quota downgrade the chat shows the R0 sources-only banner. Stop live
checks and use retrieval-only mode or the saved development dashboard; do not
raise provider limits. Use TRACE_SAMPLE=1.0 for the demo and restore the normal
sampling rate afterward.

## Chat sharing (5b)

Start order: API → readiness → chat → optional read-only dashboard. The local
launcher manages this order through API startup and starts the UIs. Keep the
API process bound to loopback. Warm up with the zero-call field lookup for bug
1809146; the first description search loads local embedding/reranking models
and can take longer than subsequent questions. Run the four-case live check
before opening the public tunnel.

Install cloudflared on Debian/Ubuntu Linux (owner terminal, matching architecture):

```bash
curl -fL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$(dpkg --print-architecture).deb" -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
bash scripts/app/share_demo.sh --dry-run
bash scripts/app/share_demo.sh
```

Expected: both local health checks pass, followed by an HTTPS
`*.trycloudflare.com` URL. Only chat port 8501 is exposed. The browser uses
Streamlit's connection; chat-to-API SSE stays on localhost. Cloudflare Quick
Tunnels do not support SSE, so never expose the API through this script. The
session limiter and Groq quota guard remain active. Ctrl-C ends the temporary
tunnel. If it drops, use `http://localhost:8501` and restart sharing for a new URL.
Do not publish the serving API key in a URL or browser setting.

References: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
and [cloudflared releases](https://github.com/cloudflare/cloudflared/releases).

## Lightweight dashboard (5a)

Community Cloud entrypoint: `dashboard/streamlit_app.py`, Python 3.11. Its adjacent
`dashboard/requirements.txt` pins only dashboard/client dependencies; do not
install this repository package or the serving extra. The entrypoint adds src
and unconditionally disables Lab and advanced engine views. Root Streamlit
configuration is unchanged, preserving the chat's theme.

Configure the repository `ahmadfaisal9900/Bugzilla`, the reviewed branch (currently
`fix/demo-hardening`) and that entrypoint in Community Cloud. Paste the placeholder
keys in `.streamlit/secrets.toml.example` into Advanced settings with real values.
Credentials come from `st.secrets` or environment variables and are never logged.
No real secrets.toml is committed.

The app tries the B9 `final-results` results-pack artifact first, then its bundled
read-only snapshot. The 232 KiB snapshot contains 12 allowlisted CSVs: dev
aggregates and 1,098 per-question verdict rows identified by qid only, with no
question text, gold or test rows. Its builder verifies every qid against the
fixed pilot122-v2 dev roster and records source hashes. Snapshot data describes
the historical evaluation; serving changes have not been re-evaluated.

Local AppTest rendered successfully with **191.23 MiB peak process RSS**, without
importing torch, sentence-transformers, the engine or Lab. This used the existing
iqfm environment with matching direct dependency versions; a clean installation
and Community Cloud execution are not yet validated.

Run the clean installation/render/server health gate yourself (downloads packages):

```bash
bash scripts/phases/run_phase11_demo_validation.sh --stage cloud --dry-run
bash scripts/phases/run_phase11_demo_validation.sh --stage cloud --run --run-dir results/demo_jobs/cloud
```

Expected: requirements-only venv, pip check success, no torch installed, AppTest
PASS, peak RSS below 700 MiB, and Streamlit health PASS. Inspect
`results/demo_jobs/cloud/render.json`, `peak_rss.txt`, `server.log` and
`summary.json`. The script uses loopback port 8599 and stops its own server.

For hosting measurements, first start all three real Compose services. With the
promoted S8v2 champion and SERVING_API_KEY in the terminal:

```bash
bash scripts/phases/run_phase11_demo_validation.sh --stage resources --dry-run
bash scripts/phases/run_phase11_demo_validation.sh --stage resources --run --run-dir results/demo_jobs/resources
```

Expected: resources.json with each image size in bytes and per-container Docker
MemUsage before and after one deterministic database question (zero Groq calls).
These are Docker working-set readings, not process peak RSS. **Container image
sizes and idle/after-question RAM are unmeasured here**; Docker builds and running
service measurements remain owner-run. No resource figures have been invented.

If `actionlint` is missing before the checks stage, install the CI-pinned binary
into a temporary tools directory:

```bash
mkdir -p /tmp/bugzilla-tools
curl -fsSL https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_linux_amd64.tar.gz -o /tmp/bugzilla-tools/actionlint.tgz
tar -xzf /tmp/bugzilla-tools/actionlint.tgz -C /tmp/bugzilla-tools actionlint
export PATH="/tmp/bugzilla-tools:$PATH"
```

On other CPU architectures, select the matching actionlint release asset.

References: [Community Cloud dependencies](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies),
[deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
and [secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

## Final bounded checks for this branch

The final demo directory passed 48 checks; the cloud/UI/route/historical-cap
subset passed 31, and API/Lab/quota/tool-coverage checks passed. Global Ruff
check and formatting passed; shell syntax checks passed. Real-bundle field,
reopen, unknown first-FIXED and missing-comment probes all completed with zero
model calls and no errors. The full offline suite, actionlint, Compose smoke,
clean venv installation, live Groq checks and container measurements remain
owner-run gates. Registry promotion, public tunnel and Cloud deployment were
not executed by the agent.

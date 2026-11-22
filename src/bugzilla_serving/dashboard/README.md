# Dev dashboard

Run these commands from the repository root in Conda `iqfm` (Python 3.11).
The pinned `[dashboard]`, `[serving]` and `[dev]` packages are already declared
in `pyproject.toml`. This dashboard never calls the FastAPI service.

## Local, synthetic demo

```bash
conda activate iqfm
python scripts/seed_mlflow_fixture.py --tracking-uri "file:$PWD/outputs/mlflow/dashboard-demo"
MLFLOW_TRACKING_URI="file:$PWD/outputs/mlflow/dashboard-demo" \
LANGSMITH_SOURCE=fixture DASHBOARD_LAB_ENABLED=true \
python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
```

Open <http://localhost:8502>. Expect nine pages, a **SIMULATED** champion,
two synthetic presets and 30 fixture production roots dated January 1, 2020.
The seeder is idempotent. Its values are synthetic plumbing checks.

For the existing backfilled local data, replace the tracking URI with
`file:$PWD/outputs/mlflow/b1-local`. At inspection this contained 9 review-only
answer runs and 24 retrieval runs, with no playground run. `pilot125` is a
**pilot subset**, not full-dev evaluation. Missing review-only scores, costs
and latencies stay unavailable; absent families and retrieval N/A differ.

Without a real `BUNDLE_DIR`, the Lab enables only the synthetic bundle and
MockProvider. Start with Defaults / S2, smoke-5, limit 1. Expect a preflight,
job status, then a simulated playground run; zero provider requests. Mock
writes always use a local file store, even when viewing remote MLflow. Those
local results can be viewed by starting the dashboard with the local URI
printed in job status. Mock answers against real dev questions are not
research results. Synthetic retrieval weights never download models.

## DagsHub and real LangSmith

Provide `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`,
`MLFLOW_TRACKING_PASSWORD`, `LANGSMITH_API_KEY`, and `DASHBOARD_PASSWORD`
through your environment. Do not put credentials in the URI or command
history. Add `GROQ_API_KEY` and a real `BUNDLE_DIR` only for live experiments.

```bash
LANGSMITH_SOURCE=live DASHBOARD_LAB_ENABLED=true \
python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
```

Expect password authentication, DagsHub runs, and root-run/feedback
aggregates from `ensf621-serving`, or “No production data yet.” The Lab's
**Use live LLM** toggle defaults off. Its preflight checks today's safe
per-model quota; the request cap and B2 runner's lock/resume/cancel remain
in force. Sweeps accept at most two knobs and run sequentially. With no real
bundle, live execution remains disabled. No remote service was exercised
during implementation.

## Read-only mode

```bash
LANGSMITH_SOURCE=live DASHBOARD_LAB_ENABLED=false \
python -m streamlit run src/bugzilla_serving/dashboard/app.py --server.port 8502
```

The Lab explains that it is disabled; Presets is hidden. Set a dashboard
password for shared access; authentication is skipped when unset locally.
Publish/unpublish requires an explicit confirmation. Champion promotion
reuses the B1 policy and strict execute-mode config validation, without a
dashboard override. Reads and publication previews cache for 60 seconds;
each source shows its fetch time. Confirmation rechecks current policy
before writing. Source credentials are environment-only.

## Offline checks and interpretation

```bash
python -m pytest tests/b_dashboard -q
python -m pytest tests/b_tracking tests/b_experiments -q
ruff check src/bugzilla_serving/dashboard tests/b_dashboard
ruff format --check src/bugzilla_serving/dashboard tests/b_dashboard
```

Tests deny HTTP and use temporary file stores plus synthetic fixtures,
including a completed background mock job and fake-key output scan.
No test questions/gold are read. Test-aggregate runs expose metrics only;
their artifacts are refused before download. Dev artifact reads are
allowlisted and capped at 10 MB; no gold or raw prompt fields are displayed.
Production reads are capped at 1,000 roots and 2,000 feedback records per
date-range request, so high-volume views may be incomplete. Invalid trace
metadata is excluded with a count. Text/email/credential redaction is a
display safeguard, not permission to upload private source content.

v3 has no F2/F5 and no test F3. Family charts show n. Saved confidence
intervals are plotted separately by original dataset scope; the dashboard
does not invent intervals for pooled scores. Token cost per question needs
source-row accounting and never substitutes the scored subset denominator.
Quota percentage uses configured daily limits, not live provider headers.
Unknown production abstention or unrated feedback keeps its own denominator.

# Stream A: Serving & Chat (FastAPI, Chat UI, LangSmith tracing, CD, hosting)

Read `mlops_overview.md` first. This stream depends **only** on the Phase 0 contracts and fixtures. Until integration, it uses `scripts/seed_mlflow_fixture.py` instead of the real MLflow, and `MockProvider` instead of Groq.

**Owns:** `src/bugzilla_serving/api/`, `bundle.py`, `quota.py`, `tracing.py`, `chat_ui/`, `engine.py` (maintenance), `scripts/build_serving_bundle.py`, `docker/api.Dockerfile`, `docker/chat.Dockerfile`, `compose*.yaml`, `.github/workflows/cd.yml`, `docs/DEPLOYMENT.md`, `tests/a_*`.

**Never touches:** `tracking/`, `experiments/`, `dashboard/`, `ci.yml`, research code. Shared files only through a PR both people approve.

---

## A1. Serving bundle

- `scripts/build_serving_bundle.py --out serving_bundle/`. Dry-run by default; `--apply` writes.
- Contents:
  - a DuckDB with `bugs` + `bug_links` metadata, public comments for the 3,000 cohort bugs, and the Phase 4 history overlay;
  - corpora C0/C1/C2 with their FTS5 + FAISS indexes;
  - dev example questions (text only);
  - `manifest.json` with sha256, counts and sizes.
- `bundle.py` loads it once, verifies the manifest, opens DuckDB read-only, and **refuses any non-dev split**.

**Done when:** the real bundle builds locally, the manifest shows no test files, and the loader works on the synthetic fixture bundle and the real one.

Local A1 status: the builder and loader are implemented. The available Phase 11 runtime
contains C1 only; C0 and C2 are absent. The built bundle records that limitation and
the runner refuses missing corpora. Do not duplicate C1 under another corpus name.
The real C1 bundle contains the 3,000-bug database, history, existing indexes, pinned
model snapshots and 299 text-only Phase 5/v3 dev examples. No test questions or gold
files are included. `load_bundle(path).examples()` returns a list of strings;
`load_bundle(path).db` is read-only. Close the bundle when the application shuts down.

From the repo root, with `iqfm` active:

```powershell
python scripts/build_serving_bundle.py --out serving_bundle
python scripts/build_serving_bundle.py --out serving_bundle --apply
python -m pytest tests/a_bundle -q
```

The first command only previews files and sizes. An existing output folder is never
overwritten; choose another `--out` to rebuild. Add `--require-all` to refuse a build
unless all three corpora are present. The builder copies data and model snapshots;
it does not regenerate indexes, download models or call Groq. Copy the complete
`serving_bundle/` folder to the host, alongside the installed application. It is
gitignored. The source defaults come from the local `official_runtime/answering.json`;
`--root` and `--runtime` allow the same layout on another machine.

Real-data smoke check, without API calls:

```powershell
$env:BUNDLE_DIR = "serving_bundle"
python -c "from bugzilla_serving.engine import build_runner; from bugzilla_serving.contracts.run_config import RunConfig; r=build_runner(RunConfig(system_id='S1',retriever='R1',provider='mock')); a=r.run('What component is bug 1701902 in?',on_event=print); print(a); r.close()"
```

Expect four status events, real Firefox sources and a mock abstention. A successful
mock check verifies the package and retrieval wiring, not answer quality or every
dense/reranking method. C0/C2 support remains pending delivery of their real indexes.
An additional local S2/R2 mock check also passed using only the packaged model weights.

## A2. API core (FastAPI, `/v1`, contract section 4.4)

- App factory; the bundle, indexes and model weights load at startup; one uvicorn worker; the engine runs in a threadpool.
- Endpoints:
  - `health`, `ready`, `options`, `presets`, `examples`, `quota`;
  - `ask`, `chat/stream` (SSE events exactly as in the contract), `feedback`.
- **Presets source:** MLflow registry (`bugzilla-qa-config`, versions tagged `published=true`, plus alias `champion`), cached for 5 min. Falls back to `configs/presets.yaml` if MLflow is unreachable. Develop against the seeded local MLflow store.
- **Request flow:** preset config + user overrides → `RunConfig` validation (`invalid_config` 422 with a field-level message the UI can show) → quota check → `engine.build_runner(cfg).run(question, on_event=…)` → SSE events.
- Auth: `SERVING_API_KEY` header (the chat UI sends it), except on `health`.

## A3. Quota and graceful degradation

- Per-model daily request and token guard at 90% of the configured limits, reusing the provider ledger. A tokens-per-minute pre-check estimates the prompt size.
- When over the limit, run **R0 retrieval-only** with `degraded=true`, and emit a `status` event explaining it.
- A per-session rate limit (e.g. 6 questions/min) returns `rate_limited` with `retry_after`.
- `/v1/quota` exposes used/limit per model for the UI banner.
- Optional, if time allows: a bring-your-own Groq key header, request-scoped and never stored or logged.

## A4. LangSmith tracing and feedback

- One root run per chat message in project `ensf621-serving`, with the metadata keys from contract section 4.6. Sampling is set by `trace_sample` (default 0.2), with a daily trace cap.
- Child runs show retrieval (sources + scores), generation and tools.
- `/v1/feedback` → `create_feedback(run_id, key="user_rating", score, comment)` when the request was traced, and is always stored in local SQLite.
- `docs/LANGSMITH_MONITORING.md`: how to filter the built-in Monitor charts by `preset_slug`, `model` and `degraded`.

## A5. Chat UI (user-facing; Streamlit chat components)

Design goals: fast perceived response, plain language, no S0–S8/R1–R7 jargon unless the user opens Advanced settings, and it works on a phone.

- **Header:** the name, one sentence on what it can answer, and a small "answers come from the Firefox Bugzilla archive (3,000-bug sample)" note.
- **Mode picker:** preset labels and descriptions from `/v1/presets`; champion marked "Recommended" and selected by default.
- **Advanced settings drawer:**
  - widgets generated from `/v1/options` hyperparameter specs, showing only the knobs whose `applies_to` matches the selected mode's system;
  - plain-language tooltips, valid ranges and the model's rate-limit hint;
  - "Custom settings" badge and a Reset button; validation errors shown inline.
- **Chat:**
  - `st.chat_input`, with history kept in session state. Every message is answered independently; a single-turn limitation note sits in the "About" section.
  - Example-question buttons on an empty chat.
  - Live status line from SSE events (*Searching… Found N sources… Writing answer…*).
- **Answer card:**
  - the answer text; for an abstention, a friendly "I couldn't find enough evidence" with the closest sources;
  - citation chips (bug #, snippet, link to bugzilla.mozilla.org);
  - a "How this was answered" expander (mode, model, sources, time, degraded flag);
  - 👍/👎 + optional comment.
- **Banners:** degraded mode, rate-limited with a countdown, API down.
- Performance: cache `/options` and `/presets`; keep reruns minimal; no heavy imports (the UI must not import torch or research code).

## A6. Containers, CD and hosting

- `docker/api.Dockerfile`:
  - python:3.11-slim, CPU-only torch;
  - embedder + reranker baked in at the pinned revisions; runtime offline;
  - non-root user, healthcheck.
- `docker/chat.Dockerfile`: Streamlit + httpx only.
- The dashboard image name and port come from the contract; B provides the Dockerfile.
- `compose.yaml`:
  - services api, chat and dashboard (image tags from `IMAGE_TAG`);
  - the bundle mounted read-only; an app-data volume; `env_file: .env`;
  - `DASHBOARD_LAB_ENABLED=false` on the host.
- `compose.ci.yaml`: fixture bundle, `LLM_PROVIDER=mock`, local builds.
- `scripts/smoke.sh`: `/v1/ready`, one `/v1/ask` per preset with mock, chat page and dashboard return 200.
- `.github/workflows/cd.yml`:
  - triggered by tags `v*` and manual dispatch;
  - build and push all three images to GHCR, using amd64 + arm64 if the host is ARM;
  - SSH deploy (`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`): `compose pull && up -d`, then a smoke with one R0 query, so no LLM quota is spent;
  - record `.last_good`; roll back automatically on a failed smoke;
  - actions pinned to SHAs.
- `docs/DEPLOYMENT.md`:
  - Oracle Always Free A1 VM setup; or own PC + `cloudflared tunnel`;
  - first-time `scp` of the bundle; the `.env` template on the host;
  - rollback and key rotation.

## A7. Tests (`tests/a_*`)

- **unit:**
  - bundle loader (rejects a test split, bad checksum);
  - quota guard and degradation;
  - per-session rate limit;
  - presets source with MLflow fallback (seeded store / unreachable);
  - feedback with a mocked LangSmith client;
  - secret grep across logs, DB and responses.
- **contract:**
  - TestClient on every endpoint;
  - SSE event order and shapes match the contract fixtures;
  - OpenAPI snapshot; every preset/system answers with MockProvider.
- **ui:** Streamlit AppTest for the chat against a mocked API: empty state, normal answer, abstention, degraded, rate-limited, Advanced settings validation.
- **live** (manual only): one real streamed answer + feedback.

## Handoff checklist for integration

- [ ] API passes contract tests against the Phase 0 fixtures; OpenAPI snapshot updated and reviewed.
- [ ] Chat works against the seeded MLflow presets and the real bundle with mock and with Groq.
- [ ] Traces visible in LangSmith with every metadata key; feedback attached.
- [ ] Images build; compose + smoke pass locally; the host is reachable; `cd.yml` dry-run (manual dispatch with deploy skipped) is green.
- [ ] List of any contract changes requested (should be none).

**Out of scope:** dashboard, MLflow writes, CI workflow, experiment running, multi-turn conversation memory.

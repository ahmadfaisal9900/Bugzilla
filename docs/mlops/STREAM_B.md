# Stream B: Experiments & Dev Dashboard (MLflow, Experiment Lab, dashboard UI, CI)

Read `mlops_overview.md` first. This stream depends **only** on the Phase 0 contracts, the engine adapter and the fixtures. It never calls the FastAPI service. Until integration it uses the sample LangSmith export instead of real chat traffic.

**Owns:** `src/bugzilla_serving/tracking/`, `experiments/`, `dashboard/`, `scripts/backfill_*.py`, `scripts/run_experiment.py`, `scripts/publish_preset.py`, `configs/eval_sets.yaml`, `docker/dashboard.Dockerfile`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, pytest/ruff/coverage config, `tests/b_*`.

**Never touches:** `api/`, `chat_ui/`, `compose*.yaml`, `cd.yml`, research code. Shared files only through a PR both people approve.

---

## B1. MLflow setup and backfill

- MLflow is the DagsHub-hosted server, set via `MLFLOW_TRACKING_URI` / `MLFLOW_TRACKING_USERNAME` / `MLFLOW_TRACKING_PASSWORD`. All tests use a local `file:` store in a temp directory.
- `tracking/` wraps logging so every run follows contract section 4.5 (experiment names, params, required tags, metric names, artifacts). A validator rejects anything off-contract.
- `scripts/backfill_answer_eval.py` reads the partner's dev evaluation outputs and logs one run per system into `research-answer-eval`. Each run carries per-family score and n, macro score, abstention/failure rates, cost, latency and intervals if the partner computed them.
- `scripts/backfill_retrieval_eval.py` reads the retrieval `summary.json` files and logs one run per (retriever, corpus) into `research-retrieval-eval`, with the `retr.*` metrics.
- Both scripts: dry-run by default; idempotent (keyed by `config_hash` + source); no question text or gold logged; test results only ever as `split=test-aggregate` metrics.

**Done when:** the dashboard leaderboard can be fully populated from the backfilled runs alone.

## B2. Experiment runner (the backend of the Experiment Lab)

- `experiments/runner.py`, also exposed as `scripts/run_experiment.py`. Input: `RunConfig` + eval set + limit.
- Steps:
  1. **Validate** the config against `configs/serving.yaml`.
  2. **Preflight:** estimated LLM calls and tokens vs today's remaining per-model quota, read from the provider ledger. Refuse if it doesn't fit.
  3. **Run** each dev question through `engine.build_runner(cfg)`. Resumable by (`config_hash`, qid).
  4. **Score** with the partner's scorer. If it isn't available: F1 exact normalized, F3 exact count, F4 set-F1, F6/F6H abstention, KI bug-id with acceptable alternates; other families "not scored", with n.
  5. **Log** one MLflow run in `playground` (`source=lab`) with `config.yaml`, `per_family.csv` and `predictions.jsonl` artifacts.
- `configs/eval_sets.yaml`: named **dev-only** qid lists (e.g. `smoke-20`, stratified by family, seed 317, plus `family-<X>` sets). Any qid not in the dev split is an error.
- One job at a time (file/SQLite lock); job status readable by the dashboard; cancel support.
- Optional **sweep:** a small grid over 1–2 knobs (e.g. `top_k` × `temperature`), capped so the total estimate fits today's budget. Each point is its own run with a shared `sweep_id` tag.

## B3. Registry: presets and champion

`scripts/publish_preset.py --run-id <id> --slug fast --label "Fast" --description "…" [--champion] [--apply]`:
- registers a version of `bugzilla-qa-config` (a pyfunc wrapper with a `config.yaml` artifact);
- sets the preset tags and `published=true`;
- optionally moves the `champion` alias.

Dry-run prints a comparison against the current champion. `--unpublish` removes a preset.

Write `docs/PROMOTION_POLICY.md` **before** choosing the first champion: the rule for which config becomes champion, based on the partner's dev per-family results, with n and abstention behaviour considered.

Suggested initial presets, to be confirmed from the evaluation:
- "Recommended" = champion (likely the router);
- "Fast" = BM25 RAG on the fastest model;
- "Deep read" = the dossier system.

## B4. Dev Dashboard (Streamlit multipage; reads MLflow and LangSmith only)

Design goals: dense but readable, n shown everywhere, coverage gaps explicit ("not in dataset" vs "N/A"), and every number traceable to an MLflow run.

| Page | Content |
|---|---|
| Overview | Champion card (config, key metrics); leaderboard of systems × families (score + n), sortable; macro score with family coverage; dataset coverage-gap note (v3 has no F2/F5/test F3) |
| Answer eval | Per-family bar charts per system with intervals; abstention correct vs false; filters by dataset/eval set |
| Retrieval eval | R1–R7 × C0–C2 heatmap per metric (Hit@5, Recall@10, MRR, nDCG); KI/MH highlighted; latency p95; selected retriever marked |
| Cost & latency | Calls, tokens in/out and p50/p95 per system/model; quota cost of one question per system |
| Error analysis | Failure categories per system; sample dev predictions with cited evidence (dev only) |
| Experiment Lab | Same hyperparameter widgets as the chat (generated from `configs/serving.yaml`); eval-set picker; preflight budget panel; Run / Cancel; live progress; on completion, results with a link to the MLflow run. **Disabled with an explanation when `DASHBOARD_LAB_ENABLED=false`** |
| Compare runs | Pick 2–3 runs; param diff table (only differing params highlighted); per-family delta chart |
| Presets | Published presets and champion; publish/unpublish from a run with a confirmation (locally only; hidden when the Lab is disabled) |
| Production | From LangSmith project `ensf621-serving`: questions/day, 👍 rate, abstention and degraded rates, p50/p95 latency by `preset_slug` and model, recent 👎 comments |

- Access: `DASHBOARD_PASSWORD` gate. All MLflow and LangSmith reads are cached for 60 s, and the dashboard shows "last updated".
- Charts: one consistent palette, labelled axes, n in tooltips/labels; no pooled overall score as the headline.

## B5. CI (`.github/workflows/ci.yml`) and repo hygiene

- Triggers: pull requests into `mlops`/`main`, and pushes.
- Jobs:
  - **lint:** ruff check + format check, plus actionlint;
  - **test:** `pytest -m "not live and not integration"` with coverage; job summary shows coverage and failed tests; JUnit artifact;
  - **contracts:** `tests/contracts/` run as a separate required check;
  - **docker:** build the three images (api/chat Dockerfiles from A, dashboard from B) with the GHA cache, no push;
  - the compose smoke job is added at integration.
- Actions pinned to SHAs, minimal permissions, concurrency cancel-in-progress. If the repo is private, the docker job runs only on PRs to `main` to save minutes.
- `.github/dependabot.yml` for pip and actions, weekly. pytest markers, ruff and coverage config in `pyproject.toml`.
- `docker/dashboard.Dockerfile`: python:3.11-slim with Streamlit, MLflow client, LangSmith client and plotting. It includes torch + engine deps **only if** the Lab is enabled in that image; otherwise build a lighter read-only variant (target `dashboard-readonly` for the host).

## B6. Tests (`tests/b_*`)

- **unit:**
  - MLflow naming validator;
  - backfill on the Phase 0 sample partner output, and on a sample retrieval `summary.json`, into a temp store (idempotent rerun);
  - scorer adapter per family, including edge cases;
  - runner preflight refusal, resume without duplicate calls, lock, non-dev qid rejection;
  - publish/unpublish/champion on a temp store;
  - secret grep across MLflow artifacts.
- **ui:** Streamlit AppTest for each page against a seeded temp MLflow store and the sample LangSmith export, covering Lab disabled vs enabled and empty states.
- **live** (manual only): one 3-question Lab run against Groq + DagsHub.

## Handoff checklist for integration

- [ ] DagsHub MLflow has the backfilled answer and retrieval runs, ≥1 Lab run, champion + 2–3 published presets.
- [ ] Dashboard runs read-only against DagsHub and LangSmith; the Lab works locally.
- [ ] `ci.yml` is green on a PR, including the contracts job and building all three images.
- [ ] Dashboard image(s) build; port and env vars match the contract.
- [ ] List of any contract changes requested (should be none).

**Out of scope:** FastAPI, chat UI, tracing writes, CD/deploy, multi-turn chat.

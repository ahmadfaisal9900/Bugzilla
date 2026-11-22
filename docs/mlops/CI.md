# Stream B CI

Run from the existing repository root with `conda activate iqfm` (Python 3.11).
CI installs pinned extras directly from pyproject; it never reads the repository `.env`.
The root CI conftest loads `tests/b_ci/pytest_offline.py` before collection. It
removes inherited provider credentials and model overrides inside pytest only,
so temporary synthetic `.env` files retain their intended meaning. Requests and
HTTPX network transports are blocked; ASGI/fake clients and localhost launch
checks remain available. The invoking shell environment stays unchanged.
Provider/model tests use synthetic fixtures and Dense/Cross doubles. They need no
Hugging Face downloads, so there is deliberately no model cache in CI.

| Job | Checks | Estimated minutes (cold / warm) |
| --- | --- | --- |
| lint | Ruff checks and format; actionlint 1.7.7 | 1–2 / 1 |
| contracts | Separate frozen contract gate, synthetic engine + local MLflow | 3–5 / 2–3 |
| test | All offline tests, serving coverage ≥70%, JUnit/XML artifacts and summary | 4–7 / 2–4 |
| secrets | Free Gitleaks action, PR/push commit diff, no license on public repo | 1–2 / 1 |
| docker | Readonly build and health; conditional Lab/API/chat builds; GHA cache; no push | 4–10 readonly, 10–25 with Lab / 2–6 |

These are planning estimates, not measured Actions results. Jobs overlap.
Triggers: PRs into and pushes to `feature/mlops`/`main`, plus manual dispatch.
Readonly builds on every public-repo PR/push and manual dispatch. **Lab, API and
chat build only on PRs into main or manual dispatch.** Missing A Dockerfiles emit
notices. The private-repo guard limits Docker to main PRs/manual dispatch.
Compose smoke is a commented TODO until OVERVIEW §6 step 5 integration.

Actions use commit SHAs, contents read permission and per-ref cancellation.
Dependabot proposes weekly grouped minor/patch pip/actions changes against
feature/mlops; review compatibility before merging. Direct dependencies are
pinned. The base is the requested `python:3.11-slim`; transitive packages and
that mutable base are not a fully reproducible lockfile.

Existing Phase 0 formatting/import-order debt is explicitly scoped in Ruff's
config to preserve A/shared ownership. B4 and other B files remain checked.
Only narrowly matched LangGraph and Starlette/AnyIO deprecations are filtered;
third-party MLflow/Pydantic deprecations remain visible. Never suppress project
serializer warnings. No contract `min_items` remains in this checkout.

## Exact local equivalents

1. Prepare tools (owner terminal; installations/downloads are not agent checks):

```bash
cd "/home/ict317/master's/ENSF 621/Project"
conda activate iqfm
python -m pip install 'torch==2.6.0+cpu' --index-url https://download.pytorch.org/whl/cpu
python -m pip install '.[serving,ui,dashboard,dev]'
mkdir -p /tmp/bugzilla-ci-tools
curl -fsSL https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_linux_amd64.tar.gz -o /tmp/bugzilla-ci-tools/actionlint.tgz
tar -xzf /tmp/bugzilla-ci-tools/actionlint.tgz -C /tmp/bugzilla-ci-tools actionlint
curl -fsSL https://github.com/gitleaks/gitleaks/releases/download/v8.24.3/gitleaks_8.24.3_linux_x64.tar.gz -o /tmp/bugzilla-ci-tools/gitleaks.tgz
tar -xzf /tmp/bugzilla-ci-tools/gitleaks.tgz -C /tmp/bugzilla-ci-tools gitleaks
```

2. Lint, contracts, test, secrets equivalents:

```bash
python -m ruff check
python -m ruff format --check
/tmp/bugzilla-ci-tools/actionlint .github/workflows/ci.yml
export LLM_PROVIDER=mock LANGSMITH_SOURCE=fixture DASHBOARD_LAB_ENABLED=false
export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
B4_STORE="$(mktemp -d)/mlruns"
export MLFLOW_TRACKING_URI="file:$B4_STORE"
python -m pytest tests/contracts -q
python -m pytest -m 'not live and not integration' --cov=src/bugzilla_serving --cov-fail-under=70 --cov-report=xml --junitxml=junit.xml -q
# PR diff equivalent; use main instead when targeting main.
B4_BASE="$(git merge-base HEAD origin/feature/mlops)"
/tmp/bugzilla-ci-tools/gitleaks git --redact --log-opts="$B4_BASE..HEAD" .
# Push equivalent: replace BEFORE_SHA with the pre-push commit.
# /tmp/bugzilla-ci-tools/gitleaks git --redact --log-opts='BEFORE_SHA..HEAD' .
```

Expected: Ruff/actionlint silent or success; passing pytest; coverage ≥70%; no
Gitleaks findings. An empty diff needs staged/committed changes before scanning;
Gitleaks scans commits, not unstaged files. XML files expose only synthetic test
identities; Git-ignore/do not commit generated reports. CI summary extracts
coverage and failed testcase names from these same reports, even after failure.

3. Docker equivalent (owner only; needs daemon, network and disk):

```bash
docker buildx create --use --name bugzilla-ci-builder
# Skip create if that builder already exists.
docker buildx build --load --target dashboard-readonly -f docker/dashboard.Dockerfile -t bugzilla-dashboard:readonly .
# Main PR/manual equivalent:
docker buildx build --load --target dashboard-lab -f docker/dashboard.Dockerfile -t bugzilla-dashboard:lab .
for image in api chat; do
  if [ -f "docker/$image.Dockerfile" ]; then
    docker buildx build --load -f "docker/$image.Dockerfile" -t "bugzilla-$image:ci" .
  else
    echo "NOTICE: docker/$image.Dockerfile absent; skipped"
  fi
done
docker image inspect bugzilla-dashboard:readonly bugzilla-dashboard:lab --format '{{.RepoTags}} {{.Size}} bytes'
B4_SMOKE="$(mktemp -d)"
docker run --rm --user "$(id -u):$(id -g)" -v "$B4_SMOKE:$B4_SMOKE" --entrypoint python bugzilla-dashboard:readonly scripts/seed_mlflow_fixture.py --tracking-uri "file:$B4_SMOKE/mlruns"
chmod -R a+rX "$B4_SMOKE" # Synthetic fixture only; readable by container UID 10001.
docker run -d --name dashboard-ci -p 8502:8502 -v "$B4_SMOKE:$B4_SMOKE:ro" -e "MLFLOW_TRACKING_URI=file:$B4_SMOKE/mlruns" -e LANGSMITH_SOURCE=fixture -e DASHBOARD_LAB_ENABLED=false bugzilla-dashboard:readonly
timeout 90 bash -c 'until curl --fail --silent http://localhost:8502/_stcore/health; do sleep 2; done'
docker logs dashboard-ci
docker rm -f dashboard-ci
```

Expected seed: COMPLETE, synthetic=true, created_runs=9; health: `ok` within
90 seconds. Absolute store paths match inside/outside the container because
MLflow file-store artifact URIs are absolute. The seeded `source=ci` evaluation
rows are intentionally excluded from leaderboards; synthetic presets/champion
still render. GHA cache is available in Actions only; local BuildKit uses its
normal local cache. No image sizes or successful builds are claimed until run.

4. DagsHub readonly dashboard (owner terminal, `.env` contains credential variables):

```bash
docker buildx build --load --target dashboard-readonly -f docker/dashboard.Dockerfile -t bugzilla-dashboard:readonly .
docker run --rm --name bugzilla-dashboard -p 8502:8502 --env-file .env -e DASHBOARD_LAB_ENABLED=false -e LANGSMITH_SOURCE=fixture bugzilla-dashboard:readonly
```

Open http://localhost:8502; health should return `ok`. MLflow reads DagsHub
through environment-only credentials; no credentials enter the build context.
Use `LANGSMITH_SOURCE=live` only when ready for real trace reads and a securely
configured LangSmith key. Set DASHBOARD_PASSWORD in `.env` for shared access.
Lab image additionally bakes CPU torch and both model revisions from
configs/retrieval_v3.yaml; models remain offline at runtime. Mount a verified real
dev bundle and enable Lab locally; building the image does not build that bundle.

5. Push and PR (B4 is committed locally; nothing was pushed by the agent):

```bash
git diff --check
git status --short
git show --stat --oneline HEAD
# Existing integration branch: push it, then open its PR into main.
git push origin feature/mlops
gh pr create --base main --head feature/mlops --title 'Stream B CI, dashboard images and handoff' --body-file docs/mlops/STREAM_B_HANDOFF.md
```

Expected: clean working tree, local B4 commit, remote branch updated, PR URL.
Use an existing PR if one already exists. To submit B4 into feature/mlops from an
isolated branch instead, coordinate the integration-branch commit with your
partner before pushing; do not rewrite history or change origin. For later
fixes stage named B-owned files only, inspect `git diff --cached --name-only`,
run targeted checks and commit before pushing.

6. Required checks: after the first successful CI run, open repository **Settings
→ Rules → Rulesets → New branch ruleset**, target `main` and `feature/mlops`,
enable **Require status checks to pass**, select `lint`, `contracts`, `test`,
`secrets`. Add `docker` once A's images exist and main-PR builds are verified.
Alternatively use Settings → Branches → Branch protection rule → Require status
checks. Do not require the commented compose placeholder. CI has not been run
on GitHub in this offline task; check names become selectable after a run.

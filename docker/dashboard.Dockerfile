# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS dashboard-readonly
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    DASHBOARD_LAB_ENABLED=false LANGSMITH_SOURCE=fixture \
    PYTHONPATH=/app/src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
WORKDIR /app
RUN groupadd --gid 10001 dashboard && useradd --uid 10001 --gid dashboard --create-home dashboard
COPY pyproject.toml ./
COPY src/bugzilla_serving ./src/bugzilla_serving
# dashboard extra deliberately excludes serving (and therefore torch).
RUN pip install '.[dashboard]' 'pydantic==2.11.7' && python -c "import importlib.util; assert importlib.util.find_spec('torch') is None"
COPY configs ./configs
COPY scripts/publish_preset.py scripts/seed_mlflow_fixture.py ./scripts/
COPY tests/fixtures/sample_langsmith_runs.json ./tests/fixtures/sample_langsmith_runs.json
RUN mkdir -p /app/outputs && chown -R dashboard:dashboard /app /home/dashboard
USER dashboard
EXPOSE 8502
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8502/_stcore/health', timeout=2)"
CMD ["python", "-m", "streamlit", "run", "src/bugzilla_serving/dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8502"]

FROM dashboard-readonly AS dashboard-lab
USER root
COPY src/bugzilla_qa ./src/bugzilla_qa
COPY scripts/run_experiment.py scripts/make_eval_sets.py scripts/build_fixture_bundle.py ./scripts/
COPY tests/fixtures ./tests/fixtures
RUN pip install 'torch==2.6.0+cpu' --index-url https://download.pytorch.org/whl/cpu \
    && pip install '.[serving]' 'huggingface-hub==0.33.4'
# Read exact revisions from the research configuration; no floating model refs.
RUN HF_HUB_OFFLINE=0 python -c "import json; from huggingface_hub import snapshot_download; c=json.load(open('configs/retrieval_v3.yaml')); [snapshot_download(c[m], revision=c[r], cache_dir='/home/dashboard/.cache/huggingface/hub', allow_patterns=['*.json','*.txt','*.safetensors','pytorch_model.bin']) for m,r in [('embedding_model','embedding_revision'),('reranker_model','reranker_revision')]]" \
    && chown -R dashboard:dashboard /home/dashboard/.cache /app
ENV DASHBOARD_LAB_ENABLED=true LLM_PROVIDER=mock
USER dashboard

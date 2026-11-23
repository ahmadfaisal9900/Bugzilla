# syntax=docker/dockerfile:1
# Serving API: FastAPI + the answering pipeline, CPU only, models baked in, no runtime downloads.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # The code finds configs/, prompts/ and outputs/ relative to src/, so run it from /app/src
    # rather than from site-packages.
    PYTHONPATH=/app/src \
    HF_HOME=/app/models/huggingface \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    BUNDLE_DIR=/bundle

WORKDIR /app

# CPU-only torch first, so `.[serving]` finds torch already satisfied instead of pulling CUDA.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --index-url "${TORCH_INDEX_URL}" torch==2.6.0

# Dependencies change less often than code: install them from pyproject.toml alone first.
COPY pyproject.toml ./
RUN mkdir -p src/bugzilla_qa src/bugzilla_serving \
    && touch src/bugzilla_qa/__init__.py src/bugzilla_serving/__init__.py \
    && pip install ".[serving]" \
    && pip uninstall -y firefox-history-qa \
    && rm -rf src

COPY src ./src
COPY configs ./configs
COPY prompts ./prompts
COPY scripts/testing/build_fixture_bundle.py ./scripts/testing/build_fixture_bundle.py
COPY models ./models

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/outputs \
    && chown -R app:app /app/outputs
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4)"

CMD ["uvicorn", "bugzilla_serving.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

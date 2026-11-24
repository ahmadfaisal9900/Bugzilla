# syntax=docker/dockerfile:1
# Chat UI: Streamlit only. It talks to the API over HTTP and never imports torch or the pipeline.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[ui]"

# Streamlit reads the theme from .streamlit/ in the working directory.
COPY .streamlit ./.streamlit

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "src/bugzilla_serving/chat_ui/app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]

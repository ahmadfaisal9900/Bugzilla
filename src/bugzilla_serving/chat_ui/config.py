"""Runtime settings from the environment (or the repo-root .env for local runs).

The API key stays on the Streamlit server. It is never rendered or sent to the browser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_URL = "http://127.0.0.1:8000"  # not localhost: on Windows that tries IPv6 first
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"  # repo root, shared with the API


class ConfigError(ValueError):
    """Raised when the frontend cannot start with the current environment."""


def read_env_file(path: Path) -> dict[str, str]:
    """Parse simple KEY=value lines. Real environment variables always win over the file."""
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("'\"")
    return values


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_key: str
    request_timeout_s: float = 10.0
    stream_timeout_s: float = 180.0

    @classmethod
    def from_env(cls, env_file: Path = ENV_FILE) -> Settings:
        env = {**read_env_file(env_file), **os.environ}
        api_url = env.get("API_URL", DEFAULT_API_URL).strip().rstrip("/")
        api_key = env.get("SERVING_API_KEY", "").strip()
        if not api_url.startswith(("http://", "https://")):
            raise ConfigError("API_URL must start with http:// or https://")
        if not api_key:
            raise ConfigError("SERVING_API_KEY is not set")
        return cls(api_url=api_url, api_key=api_key)

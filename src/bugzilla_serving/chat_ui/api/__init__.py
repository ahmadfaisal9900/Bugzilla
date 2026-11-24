"""API layer: transport, error handling and typed response models."""

from .client import ApiClient, ApiError, ApiUnavailable, StreamEvent, parse_sse
from .models import AnswerRecord, Catalog, Evidence, Preset, QuotaStatus, Setting

__all__ = [
    "AnswerRecord",
    "ApiClient",
    "ApiError",
    "ApiUnavailable",
    "Catalog",
    "Evidence",
    "Preset",
    "QuotaStatus",
    "Setting",
    "StreamEvent",
    "parse_sse",
]

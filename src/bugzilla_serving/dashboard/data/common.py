"""Typed snapshots, missing-value semantics and display redaction."""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class Snapshot(Generic[T]):
    value: T
    updated_at: str
    error: str | None = None


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def scrub(value):
    if isinstance(value, str):
        for key, secret in os.environ.items():
            if secret and any(s in key for s in ("KEY", "PASSWORD", "TOKEN", "SECRET")):
                if len(secret) >= 8:
                    value = value.replace(secret, "[redacted]")
        return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email withheld]", value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


@dataclass(frozen=True)
class Cell:
    value: float | None
    n: int | None
    state: str

    @property
    def label(self):
        if self.value is not None:
            return f"{self.value:.3g} · n={self.n if self.n is not None else 'unknown'}"
        return f"{self.state} · n={self.n if self.n is not None else 'unknown'}"


def family_cell(
    metrics, family, *, dataset=None, metric="score", na_rows=(), tags=None, family_rows=()
):
    prefix = f"retr.{dataset}.{family}" if dataset else f"answer.{family}"
    n = metrics.get(prefix + ".n")
    value = metrics.get(prefix + "." + metric)
    if value is not None:
        return Cell(float(value), int(n) if n is not None else None, "value")
    matches = [
        r
        for r in na_rows
        if r.get("family") == family and r.get("dataset") == dataset and r.get("metric") == metric
    ]
    if matches:
        state = matches[0].get("state", "N/A")
        return Cell(
            None,
            int(matches[0]["n"]) if matches[0].get("n") not in (None, "") else None,
            "not in dataset" if state == "not in dataset" else "N/A",
        )
    rows = [
        r
        for r in family_rows
        if r.get("family") == family and (not dataset or r.get("dataset") == dataset)
    ]
    if tags and tags.get("provenance") == "review-only" and (rows or not family_rows):
        return Cell(
            None,
            int(rows[0]["source_n"])
            if rows and rows[0].get("source_n") not in (None, "")
            else None,
            "not available yet: review-only",
        )
    if rows and int(rows[0].get("source_n", rows[0].get("n", 0)) or 0) > 0:
        return Cell(None, int(rows[0].get("source_n", rows[0].get("n"))), "not scored")
    return Cell(None, None, "not in dataset")

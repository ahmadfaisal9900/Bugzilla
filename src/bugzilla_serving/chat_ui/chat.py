"""Chat use case: send one question, follow the stream, return a finished Turn.

Framework-free on purpose: the Streamlit pages call this, and tests call it directly.
Each question is answered on its own; earlier turns are never sent to the API.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .api import AnswerRecord, ApiClient, ApiError, Evidence, Preset, Setting

ProgressCallback = Callable[[str], None]

STAGE_LABELS = {
    "retrieving": "Searching…",
    "generating": "Writing answer…",
    "done": "Done",
}


@dataclass
class Turn:
    question: str
    mode_label: str
    model_label: str
    record: AnswerRecord | None = None
    error: str = ""  # set instead of record when the question couldn't be answered
    request_id: str = ""
    feedback: int | None = None  # 1 = helpful, 0 = not helpful
    asked_at: float = field(default_factory=time.time)


def progress_label(stage: str, detail: str) -> str:
    """Friendly progress text. 'retrieved' carries a useful count, e.g. "Found 5 sources"."""
    if stage == "retrieved" and detail:
        return detail if detail.endswith("…") else f"{detail}…"
    if "sources without generating" in detail:  # quota guard notice
        return "Answer generation is limited, showing sources…"
    return STAGE_LABELS.get(stage, detail or "Working…")


def ask(
    client: ApiClient,
    *,
    session_id: str,
    question: str,
    preset: Preset,
    overrides: dict[str, Any],
    model_label: str,
    on_progress: ProgressCallback = lambda _: None,
) -> Turn:
    """Run one question end to end. Raises ApiError on any failure; never returns half a turn."""
    turn = Turn(question=question, mode_label=preset.display_label, model_label=model_label)
    on_progress(STAGE_LABELS["retrieving"])
    for event in client.stream(client.chat_body(session_id, question, preset.slug, overrides)):
        if event.name == "status":
            on_progress(progress_label(event.data.get("stage", ""), event.data.get("detail", "")))
        elif event.name == "answer":
            turn.record = AnswerRecord.from_json(event.data)
        elif event.name == "error":
            raise ApiError(
                500,
                str(event.data.get("code", "internal")),
                str(event.data.get("message", "Answer generation failed")),
                event.data.get("retry_after"),
            )
        elif event.name == "done":
            turn.request_id = str(event.data.get("request_id", ""))
    if turn.record is None:
        raise ApiError(502, "incomplete_stream", "The answer stream ended without an answer.")
    return turn


def preset_values(preset: Preset, settings: list[Setting]) -> dict[str, Any]:
    """The value each visible setting has when the user changes nothing.

    The API sends every RunConfig field, with null for ones the preset leaves unset (for example
    s7_max_tool_steps on S8). Those fall back to the spec default.
    """
    values = {}
    for setting in settings:
        value = preset.config.get(setting.name)
        values[setting.name] = setting.default if value is None else value
    return values


def changed_settings(baseline: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Only send overrides that differ from the preset, so the API logs 'custom' honestly."""
    return {k: v for k, v in values.items() if baseline.get(k) != v}


@dataclass
class CitedBug:
    """One bug report and every place it was used in this session."""

    bug_id: str
    url: str | None
    snippets: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    best_score: float = 0.0
    last_turn: int = 0  # index of the newest turn that cited it

    @property
    def times_cited(self) -> int:
        return len(self.questions)

    def add(self, source: Evidence, question: str, turn_index: int) -> None:
        if source.snippet and source.snippet not in self.snippets:
            self.snippets.append(source.snippet)
        if question not in self.questions:
            self.questions.append(question)
        self.best_score = max(self.best_score, source.score)
        self.last_turn = max(self.last_turn, turn_index)


def cited_bugs(turns: Iterable[Turn]) -> list[CitedBug]:
    """Each bug once, newest citation first, with its evidence and the questions that used it."""
    bugs: dict[str, CitedBug] = {}
    for index, turn in enumerate(turns):
        if turn.record is None:
            continue
        for source in turn.record.sources():
            bug = bugs.setdefault(source.bug_id, CitedBug(source.bug_id, source.url))
            bug.add(source, turn.question, index)
    return sorted(bugs.values(), key=lambda b: b.last_turn, reverse=True)

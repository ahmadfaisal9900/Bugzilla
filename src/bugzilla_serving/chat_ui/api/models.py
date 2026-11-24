"""Typed views of the serving API's JSON (see src/bugzilla_serving/contracts).

Parsing is deliberately forgiving: a missing optional field becomes a safe default
instead of crashing the page. The contract test keeps these shapes honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

BUGZILLA_HOST = "bugzilla.mozilla.org"

# Settings the end user never edits; presets own them.
HIDDEN_SETTINGS = frozenset({"system_id", "provider"})


def bug_url(bug_id: str, supplied: str = "") -> str | None:
    """Return a safe Bugzilla link, or None. Only https links to Bugzilla are allowed."""
    if supplied:
        parts = urlsplit(supplied)
        if parts.scheme == "https" and parts.hostname == BUGZILLA_HOST and not parts.username:
            return supplied
    if str(bug_id).isdecimal() and int(bug_id) > 0:
        return f"https://{BUGZILLA_HOST}/show_bug.cgi?id={int(bug_id)}"
    return None


@dataclass(frozen=True)
class Preset:
    slug: str
    label: str
    description: str
    config: dict[str, Any]
    is_champion: bool = False

    @property
    def display_label(self) -> str:
        """The champion preset is always shown as "Recommended"."""
        return "Recommended" if self.is_champion else self.label

    @property
    def system_id(self) -> str:
        return str(self.config.get("system_id", ""))

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Preset:
        return cls(
            slug=str(data["slug"]),
            label=str(data.get("label") or data["slug"]),
            description=str(data.get("description", "")),
            config=dict(data.get("config") or {}),
            is_champion=bool(data.get("is_champion", False)),
        )


@dataclass(frozen=True)
class Setting:
    """One tunable hyperparameter from /v1/options."""

    name: str
    kind: str  # "choice" | "integer" | "number"
    label: str
    help: str
    default: Any
    applies_to: tuple[str, ...]
    choices: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def applies(self, system_id: str) -> bool:
        return system_id in self.applies_to

    @property
    def user_editable(self) -> bool:
        return self.name not in HIDDEN_SETTINGS and not (
            self.kind == "choice" and len(self.choices) < 2
        )

    @classmethod
    def from_json(cls, name: str, data: dict[str, Any]) -> Setting:
        return cls(
            name=name,
            kind=str(data.get("type", "choice")),
            label=str(data.get("label") or name.replace("_", " ").capitalize()),
            help=str(data.get("help", "")),
            default=data.get("default"),
            applies_to=tuple(data.get("applies_to") or ()),
            choices=tuple(data.get("choices") or ()),
            minimum=data.get("min"),
            maximum=data.get("max"),
        )


@dataclass(frozen=True)
class Catalog:
    """Everything the page needs before the first question; cached by the UI layer."""

    presets: list[Preset]
    settings: list[Setting]
    model_labels: dict[str, str]
    examples: list[str]

    @property
    def default_preset(self) -> Preset:
        return next((p for p in self.presets if p.is_champion), self.presets[0])

    def preset(self, slug: str | None) -> Preset:
        return next((p for p in self.presets if p.slug == slug), self.default_preset)

    def settings_for(self, preset: Preset) -> list[Setting]:
        return [s for s in self.settings if s.user_editable and s.applies(preset.system_id)]


@dataclass(frozen=True)
class Evidence:
    chunk_id: str
    bug_id: str
    snippet: str
    score: float
    url: str | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Evidence:
        bug_id = str(data.get("bug_id", ""))
        return cls(
            chunk_id=str(data.get("chunk_id", "")),
            bug_id=bug_id,
            snippet=" ".join(str(data.get("snippet", "")).split()),
            score=float(data.get("score") or 0.0),
            url=bug_url(bug_id, str(data.get("url", ""))),
        )


@dataclass(frozen=True)
class AnswerRecord:
    abstain: bool
    value: Any
    rationale: str
    bug_ids: tuple[int, ...]
    citations: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    route: str
    latency_ms: float
    llm_calls: int
    degraded: bool

    @property
    def sources_only(self) -> bool:
        """Quota guard fallback: sources are shown, no answer text was generated."""
        return self.degraded or self.route == "R0"

    @property
    def text(self) -> str:
        value = self.value
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def sources(self, limit: int = 8) -> list[Evidence]:
        """One entry per bug: cited chunks first, then answer bug IDs, then the rest by score."""
        cited = set(self.citations)
        answered = {str(b) for b in self.bug_ids}
        ranked = sorted(
            self.evidence,
            key=lambda e: (e.chunk_id not in cited, e.bug_id not in answered, -e.score),
        )
        seen: dict[str, Evidence] = {}
        for item in ranked:
            seen.setdefault(item.bug_id, item)
        return list(seen.values())[:limit]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AnswerRecord:
        answer = data.get("answer") or {}
        return cls(
            abstain=bool(answer.get("abstain", True)),
            value=answer.get("answer"),
            rationale=str(answer.get("rationale", "")),
            bug_ids=tuple(int(b) for b in answer.get("bug_ids") or ()),
            citations=tuple(str(c) for c in answer.get("citations") or ()),
            evidence=tuple(Evidence.from_json(e) for e in data.get("evidence") or ()),
            route=str(data.get("route", "")),
            latency_ms=float(data.get("latency_ms") or 0.0),
            llm_calls=int(data.get("llm_calls") or 0),
            degraded=bool(data.get("degraded", False)),
        )


@dataclass(frozen=True)
class QuotaStatus:
    degraded_now: bool
    models: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> QuotaStatus:
        models = [m for m in data.get("models") or () if isinstance(m, dict)]
        return cls(degraded_now=any(m.get("degraded_now") for m in models), models=models)

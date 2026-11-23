"""Plain-English starter questions for the welcome screen.

The API's examples come from the bundle's dev questions, which are written as benchmark prompts
("Using the specified frozen evidence, ... The source snapshot date is UNKNOWN."). Read cold in a
demo, they're confusing. This module rewrites the common shapes into the question a person would
type, tags each with its kind and bug number, and drops shapes it can't phrase simply.
No Streamlit here, so it's easy to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LOOKUP, RELATIONS, COUNT = "Lookup", "Relationships", "Count"

RELATION_QUESTIONS = {
    "depends_on": "Which bugs does bug {n} depend on?",
    "blocks": "Which bugs does bug {n} block?",
    "duplicate_of": "Which bug is bug {n} a duplicate of?",
    "has_duplicate": "Which bugs were closed as duplicates of bug {n}?",
    "regressed_by": "Which bug caused the regression in bug {n}?",
    "see_also": "Which bugs does bug {n} list under See also?",
}
FIELDS = {"component", "resolution", "status", "product"}

_FIELD = [
    re.compile(r"bug (?P<n>\d+)\b[^?]*?what is its recorded (?P<f>\w+)\?", re.I),
    re.compile(r"what (?P<f>\w+) is recorded for (?:Firefox )?bug (?P<n>\d+)", re.I),
    re.compile(r"what is the recorded (?P<f>\w+) of bug (?P<n>\d+)", re.I),
]
_RELATION = re.compile(
    r"recorded for (?:relation )?(?P<r>[a-z_]+) from (?:Firefox )?bug (?P<n>\d+)", re.I
)
_COUNT = re.compile(
    r"how many distinct Firefox bug IDs have (?P<f>component|status|resolution)=(?P<v>[^?]+?) in ",
    re.I,
)
_BOILERPLATE = re.compile(r"frozen evidence|snapshot date|unknown|cohort|seed \d|partition", re.I)
_BUG = re.compile(r"\bbug (\d+)", re.I)


@dataclass(frozen=True)
class Example:
    question: str
    kind: str
    bug_id: str | None = None

    @property
    def tag(self) -> str:
        """The small line above the question: what kind it is and which bug it's about."""
        return f"{self.kind} · Bug {self.bug_id}" if self.bug_id else self.kind


def tidy(text: str) -> Example | None:
    """The plain version of one API example, or None if it has no simple phrasing."""
    for pattern in _FIELD:
        match = pattern.search(text)
        if match and match["f"].lower() in FIELDS:
            field, bug = match["f"].lower(), match["n"]
            if field == "component":
                return Example(f"What component is bug {bug} filed under?", LOOKUP, bug)
            return Example(f"What is the {field} of bug {bug}?", LOOKUP, bug)
    match = _RELATION.search(text)
    if match and match["r"].lower() in RELATION_QUESTIONS:
        bug = match["n"]
        return Example(RELATION_QUESTIONS[match["r"].lower()].format(n=bug), RELATIONS, bug)
    match = _COUNT.search(text)
    if match:
        field, value = match["f"].lower(), match["v"].strip()
        if field == "component":
            return Example(f"How many bugs in the sample are filed under {value}?", COUNT)
        return Example(f"How many bugs in the sample have {field} {value}?", COUNT)
    text = text.strip()
    if len(text) <= 100 and not _BOILERPLATE.search(text):  # already reads like a person's question
        bug = _BUG.search(text)
        return Example(text, _kind(text), bug.group(1) if bug else None)
    return None


def tidy_all(texts: list[str]) -> list[Example]:
    """Every example that has a plain phrasing, in the API's order, without repeats."""
    seen: set[str] = set()
    tidied = []
    for text in texts:
        example = tidy(text)
        if example and example.question not in seen:
            seen.add(example.question)
            tidied.append(example)
    return tidied


def starters(texts: list[str], limit: int = 3) -> list[Example]:
    """Up to `limit` tidied examples, one of each kind first, then in the API's order."""
    tidied = tidy_all(texts)
    picked = []
    for kind in (LOOKUP, RELATIONS, COUNT):
        first = next((e for e in tidied if e.kind == kind), None)
        if first:
            picked.append(first)
    picked += [e for e in tidied if e not in picked]
    return picked[:limit]


def task_questions(texts: list[str]) -> dict[str, str]:
    """A question per kind for the task tiles: the second example of that kind, so the tiles
    don't repeat the example rows and always name bugs that are really in the sample."""
    by_kind: dict[str, list[Example]] = {}
    for example in tidy_all(texts):
        by_kind.setdefault(example.kind, []).append(example)
    return {kind: found[min(1, len(found) - 1)].question for kind, found in by_kind.items()}


def _kind(text: str) -> str:
    lowered = text.lower()
    if lowered.startswith("how many") or "most bugs" in lowered:
        return COUNT
    if re.search(r"depend|block|duplicate|regress|see also|related", lowered):
        return RELATIONS
    return LOOKUP

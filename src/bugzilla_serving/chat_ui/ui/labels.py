"""Chat UI names for the advanced settings, in the field's usual terms.

The API's /v1/options labels are shared with research tooling, so the chat renames them here.
A setting or choice missing from these maps keeps the API's label.
"""

from __future__ import annotations

# setting name -> (label, help)
SETTINGS: dict[str, tuple[str, str]] = {
    "system_id": (
        "Answering system",
        "The pipeline that answers. S8 is the router: it picks S2, S5 or S7 per question.",
    ),
    "retriever": (
        "Retriever",
        "How passages are found: BM25 keyword, dense embeddings, hybrid, reranked, HyDE or "
        "multi-query.",
    ),
    "corpus": (
        "Corpus (chunking)",
        "Which chunked copy of the bug text is searched.",
    ),
    "provider": ("LLM provider", "Groq for real answers; mock is the offline test model."),
    "model": ("LLM", "The model that writes the answer."),
    "top_k": ("Top-k passages", "How many retrieved passages are given to the LLM."),
    "temperature": (
        "Temperature",
        "LLM sampling temperature. 0 gives the same answer every time.",
    ),
    "context_budget_tokens": (
        "Context budget (tokens)",
        "Most evidence put in the prompt. Counted as bytes, so the real token count is lower.",
    ),
    "prompt_version": (
        "Prompt version",
        "answer-v1 is the full instruction prompt; answer-v2-compact is shorter and uses fewer "
        "tokens.",
    ),
    "s4_tau": (
        "Rerank threshold (tau)",
        "Below this cross-encoder score the system searches again, then abstains. "
        "Not a probability.",
    ),
    "s5_dossier_budget": (
        "Dossier size (bytes)",
        "Most of the bug's records loaded into the prompt for the full dossier.",
    ),
    "s7_max_tool_steps": (
        "Max tool calls",
        "Database lookups the LLM may make before it must answer.",
    ),
    "rrf_k": (
        "RRF k (rank fusion)",
        "Reciprocal rank fusion constant for merging keyword and dense results. "
        "Lower trusts each list's top hits more; 60 is the usual value.",
    ),
    "query_transform": (
        "Query transformation",
        "HyDE searches with a model-written hypothetical answer; multi-query searches with "
        "several rewrites.",
    ),
}

# setting name -> {choice value -> shown text}
CHOICES: dict[str, dict[str, str]] = {
    "system_id": {
        "R0": "R0 · Retrieval only (no LLM)",
        "S0": "S0 · Closed-book LLM (no retrieval)",
        "S1": "S1 · BM25 keyword RAG",
        "S2": "S2 · Multi-query RAG",
        "S3": "S3 · Query rewriting RAG",
        "S4": "S4 · Corrective RAG (search again if weak)",
        "S5": "S5 · Full bug dossier (long context)",
        "S6": "S6 · Graph expansion (linked bugs)",
        "S7": "S7 · Database tools",
        "S7v2": "Database path",
        "S8v2": "Auto-router",
        "S8": "S8 · Router (picks S2, S5 or S7)",
        "ORACLE": "Oracle (diagnostic only)",
    },
    "retriever": {
        "R1": "R1 · BM25 keyword",
        "R2": "R2 · Dense embeddings (MiniLM)",
        "R3": "R3 · Hybrid (BM25 + dense)",
        "R4": "R4 · Hierarchical (bug, then passages)",
        "R5": "R5 · Cross-encoder reranked",
        "R6": "R6 · Graph expansion (linked bugs)",
        "R7a": "R7a · HyDE (hypothetical answer)",
        "R7b": "R7b · Multi-query (several rewrites, merged)",
    },
    "corpus": {
        "C0": "C0 · Original chunks (long text cut off)",
        "C1": "C1 · Full-text chunks",
        "C2": "C2 · Chunks with bug ID and title",
    },
    "query_transform": {
        "R7a": "R7a · HyDE (hypothetical answer)",
        "R7b": "R7b · Multi-query (several rewrites)",
    },
    "provider": {"groq": "Groq", "mock": "Mock (offline test model)"},
}


# Settings panel sections, in order. A setting not listed goes under the last section.
GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Answering", ("system_id",)),
    ("Search", ("retriever", "corpus", "query_transform", "top_k", "rrf_k", "s4_tau")),
    (
        "Language model",
        (
            "provider",
            "model",
            "temperature",
            "prompt_version",
            "context_budget_tokens",
            "s5_dossier_budget",
            "s7_max_tool_steps",
        ),
    ),
]


def grouped(names: list[str]) -> list[tuple[str, list[str]]]:
    """Split setting names into the panel's sections, keeping only non-empty ones."""
    placed = {name for _, members in GROUPS for name in members}
    sections = [(title, [n for n in members if n in names]) for title, members in GROUPS]
    extra = [n for n in names if n not in placed]
    if extra:
        sections[-1][1].extend(extra)
    return [(title, members) for title, members in sections if members]


def label(name: str, default: str) -> str:
    return SETTINGS.get(name, (default, ""))[0]


def help_text(name: str, default: str | None) -> str | None:
    return SETTINGS[name][1] if name in SETTINGS else default


def choice(name: str, value: object) -> str:
    return CHOICES.get(name, {}).get(str(value), str(value))

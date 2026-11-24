"""Serving adaptations only; evaluated research graphs and configs stay immutable."""

from __future__ import annotations

import re
from collections import defaultdict

from bugzilla_qa.answering.contracts import abstention, pack
from bugzilla_qa.answering_v2.graph import AnswerGraphV2, route_v2

DISCUSSION = re.compile(
    r"\b(comments?|discussion|discuss|said|developers?|devs?|what happened|history of|"
    r"tell me about|know about|summary|summari[sz]e|explain|details|overview|status update)\b",
    re.I,
)


def explicit_ids(question):
    named = re.findall(r"\b(?:bug|issue|report)\s*#?\s*([1-9]\d*)\b", question, re.I)
    bare = re.findall(r"(?<![\w.])([1-9]\d{5,7})(?![\w.])", question)
    return list(dict.fromkeys(named + bare))


def tool_question(question):
    question = re.sub(r"does (bug\s+#?\s*\d+) depend on", r"\1 depends on", question, flags=re.I)
    return re.sub(r"does (bug\s+#?\s*\d+) block\b", r"\1 blocks", question, flags=re.I)


def route_serving(question):
    route, rule = route_v2(tool_question(question))
    # Preserve all structured and explanation rules before the new open-ended intent.
    if route in ("S7v2", "S5"):
        return route, rule
    if explicit_ids(question):
        if DISCUSSION.search(question):
            return "S5", "discussion_with_id_serving"
        return "S5", "explicit_id_dossier_fallback_serving"
    return route, rule


def ordered_dossier(docs, question):
    metadata, groups, other = [], defaultdict(list), []
    for doc in docs:
        kind = doc.get("kind", doc.get("chunk_type"))
        if kind == "metadata":
            metadata.append(doc)
        elif kind == "comment":
            groups[str(doc["record_id"])].append(doc)
        else:
            other.append(doc)
    for group in groups.values():
        group.sort(key=lambda d: (d.get("source_char_start", 0), d["chunk_id"]))
    comments = sorted(
        groups.values(), key=lambda g: (str(g[0].get("event_time_utc") or ""), g[0]["record_id"])
    )
    pinned = re.search(r"cited comment\s+([a-f0-9]{12,64})", question, re.I)
    if pinned:
        comments.sort(key=lambda g: not g[0]["record_id"].startswith(pinned[1].lower()))
    elif len(comments) > 1:
        # Earliest available comment (comment 0 when present), then newest records.
        comments = comments[:1] + list(reversed(comments[1:]))
    return metadata + [d for group in comments for d in group] + other


def pack_dossier(docs, budget):
    marker = "\n[Archive context truncated to serving budget.]\n"
    full_size = sum(
        len((f"[C{i}] chunk_id={d['chunk_id']}\n" + d["text"] + "\n").encode())
        for i, d in enumerate(docs, 1)
    )
    truncated = full_size > budget
    context, mapping = pack(docs, budget - len(marker.encode()) if truncated else budget)
    return context + (marker if truncated else ""), mapping


class ServingGraphV2(AnswerGraphV2):
    def router(self, state):
        route, rule = route_serving(state["question"])
        if route is not None:
            return dict(route=route, route_rule=rule)
        return super().router(state)

    def retrieve(self, state):
        result = super().retrieve(state)
        if state["route"] == "S5":
            result["retrieved"] = ordered_dossier(result["retrieved"], state["question"])
            if re.search(
                r"\b(comments?|discussion|devs?|developers?)\b", state["question"], re.I
            ) and not any(
                d.get("kind", d.get("chunk_type")) == "comment" for d in result["retrieved"]
            ):
                result["raw_output"] = abstention(
                    "The named bug is in the archive, but no public comments were included."
                )
        return result

    def pack_context(self, state):
        if state["route"] == "S5":
            context, mapping = pack_dossier(
                state["retrieved"], min(4096, self.config["dossier_tokens"])
            )
            return dict(context=context, context_map=mapping, context_ids=list(mapping.values()))
        return super().pack_context(state)

    def generate(self, state):
        if state["route"] == "S7v2":
            state = dict(state, question=tool_question(state["question"]))
        result = super().generate(state)
        # A supported-but-unknown lifecycle fact is a valid decline. A rejected tool
        # or unavailable field for an existing bug gets its public dossier instead.
        log = state.get("tool_log", [])
        if (
            state["route"] == "S7v2"
            and explicit_ids(state["question"])
            and result.get("raw_output", {}).get("abstain")
            and not state["errors"]
            and log
        ):
            last = log[-1]
            tool = last.get("result", {})
            unavailable = (
                tool.get("known") is False
                or tool.get("error")
                or last.get("name") == "get_bug_fields"
                and all(v is None for v in tool.get("fields", {}).values())
            )
            if unavailable:
                updated = dict(state, route="S5", raw_output=None)
                retrieved = self.retrieve(updated)
                updated.update(retrieved)
                packed = self.pack_context(updated)
                updated.update(packed)
                generated = super().generate(updated)
                return {
                    **retrieved,
                    **packed,
                    **generated,
                    "route": "S5",
                    "route_rule": "database_coverage_dossier_serving",
                }
        return result

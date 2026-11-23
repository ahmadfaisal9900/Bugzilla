"""Text-only JSON planning and deterministic answers, using public question facts.

No gold, expected answer, evidence oracle or native function-call transport enters
this module. Only explicit question syntax selects answer shapes/operations.
"""

import json
import re

from jsonschema import ValidationError, validate

from bugzilla_qa.answering.contracts import ANSWER_SCHEMA, abstention, normalize_citations, pack
from bugzilla_qa.llm.provider import InvalidJSONResponse

from .tools import TOOLS

SPECS = {s["name"]: s for s in TOOLS if s["name"] != "submit_answer"}
PLAN_SCHEMA = {
    "oneOf": [
        dict(
            type="object",
            properties={"tool": {"const": name}, "args": spec["parameters"]},
            required=["tool", "args"],
            additionalProperties=False,
        )
        for name, spec in SPECS.items()
    ]
}
OPEN = {"UNCONFIRMED", "NEW", "ASSIGNED", "REOPENED"}
CLOSED = {"RESOLVED", "VERIFIED", "CLOSED"}


def preparse(question):
    """Extract explicit syntax, not answers. Unknown/compound filters stay partial."""
    text = question["question"]
    low = text.lower()
    ids = list(
        dict.fromkeys(int(x) for x in re.findall(r"\b(?:bug|issue)\s*#?\s*(\d+)\b", text, re.I))
    )
    facts = dict(
        bug_ids=ids,
        population=None,
        scope={},
        mode=None,
        temporal_requested=bool(re.search(r"\bas of\b", low)),
        free_text_requested=bool(re.search(r"\bwhy\b|\breason\b|\bconstraint\b", low)),
    )
    if re.search(r"\btest partition\b|\bpartition(?:=|\s+)test\b", low):
        return dict(plan=None, complete=True, facts={**facts, "refused_population": True})
    if re.search(r"\bdev\b", low) and re.search(r"\b592\b", low):
        facts.update(
            population="phase05_dev_eligible",
            scope=dict(partition="dev", partition_scheme="phase05"),
        )
    elif re.search(r"\bdev\b", low) and re.search(r"\b882\b", low):
        facts.update(
            population="bank_v2_dev_noconflict",
            scope=dict(partition="dev", partition_scheme="expanded-v2"),
        )
    elif "cohort" in low:
        facts["population"] = "cohort"
    plan = None
    complete = False
    if len(ids) == 1 and re.search(r"engineer(?:ing)? work hours", low.split("?")[0]):
        return dict(
            plan=dict(tool="get_lifecycle", args=dict(bug_id=ids[0])),
            complete=True,
            facts={**facts, "mode": "work_hours"},
        )
    comment = re.search(r"cited comment\s+([a-f0-9]{12,64})", low)
    if len(ids) == 1 and comment:
        plan = dict(tool="get_comment", args=dict(bug_id=ids[0], comment_ref=comment[1]))
        facts["mode"] = "text"
        complete = True
    elif len(ids) == 1 and ("reopened" in low or ("hours" in low and "fixed" in low)):
        plan = dict(tool="get_lifecycle", args=dict(bug_id=ids[0]))
        facts["mode"] = (
            "reopened"
            if "transitions into reopened" in low or "how many" in low and "reopened" in low
            else "hours"
        )
        complete = (
            "engineer work hours" not in low.split("calendar duration")[0] and "as of" not in low
        )
    elif len(ids) == 1:
        relation = None
        direction = "outgoing"
        if re.search(r"\bblocking\b|\bblockers\b", low):
            relation, direction = "blocks", "incoming"
        else:
            for pattern, name in (
                (r"depends_on|depends on|dependencies", "depends_on"),
                (r"has_duplicate|duplicates of", "has_duplicate"),
                (r"duplicate_of|duplicate of", "duplicate_of"),
                (r"regressed_by|regressed by", "regressed_by"),
                (r"see_also|see also", "see_also"),
                (r"\bregresses\b", "regresses"),
                (r"\bblocks\b", "blocks"),
            ):
                if re.search(pattern, low):
                    relation = name
                    break
        if relation:
            plan = dict(
                tool="get_linked_bugs",
                args=dict(bug_id=ids[0], relation=relation, direction=direction),
            )
            facts.update(
                relation=relation,
                direction=direction,
                mode="unresolved_count"
                if "how many" in low and "unresolved" in low
                else "depends_fixed"
                if "which of those" in low and "fixed" in low
                else "id_set",
            )
            complete = True
        else:
            fields = [
                f
                for f in ("component", "status", "resolution", "priority", "severity", "product")
                if re.search(r"\b" + f + r"\b", low.split("?")[0])
            ]
            if fields:
                plan = dict(tool="get_bug_fields", args=dict(bug_id=ids[0], fields=fields))
                facts["mode"] = "field" if len(fields) == 1 else "text"
                complete = len(fields) == 1 and not re.search(
                    r"\bwhy|reason|historical|as of|changed\b", low
                )
    if plan is None and not ids and re.search(r"how many|bug count|count of|number of", low):
        args = dict(scope="cohort")
        match = re.search(r"\bcomponent(?:=|\s+)(.+?)(?=\s+in the dev|[?.;]|$)", text, re.I)
        if match:
            args["component"] = match[1].strip()
        for field in ("status", "resolution"):
            match = re.search(r"\b" + field + r"(?:=|\s+)([A-Z]+)\b", text)
            if match:
                args[field] = match[1]
        facts["mode"] = "count"
        plan = dict(tool="count_bugs", args=args)
        # Do not silently ignore other explicit conditions or historical dates.
        complete = bool(
            facts["population"]
            and (len(args) > 1 or bool(re.search(r"how many bugs in the downloaded cohort", low)))
            and not re.search(
                r"\b(?:19|20)\d\d\b|before|after|between| and (?:status|component|resolution)", low
            )
        )
    facts["filters"] = {k: v for k, v in (plan or {}).get("args", {}).items() if k != "scope"}
    if plan and facts["free_text_requested"]:
        facts["mode"] = "text"
    if plan:
        try:
            validate(plan, PLAN_SCHEMA)
        except ValidationError:
            plan, complete = None, False
    return dict(plan=plan, complete=complete, facts=facts)


def deterministic(parsed, result):
    """Return a common-contract answer or None for genuinely free-text work."""
    facts, plan = parsed["facts"], parsed["plan"]
    if result.get("known") is False or result.get("error"):
        return abstention(result.get("reason", "The public tool could not establish the answer."))
    mode = facts["mode"]
    if facts.get("free_text_requested"):
        return None
    value, kind = None, "unknown"
    if mode == "count":
        value, kind = result.get("count"), "integer"
    elif mode in ("hours", "reopened", "work_hours"):
        value = result.get(
            {
                "hours": "first_fixed_hours",
                "reopened": "reopened_count",
                "work_hours": "engineer_work_hours",
            }[mode]
        )
        kind = "hours" if mode == "hours" else "integer"
    elif mode in ("id_set", "unresolved_count", "depends_fixed"):
        targets = result.get("targets")
        if targets is None:
            return None
        if mode in ("unresolved_count", "depends_fixed") and any(
            t["status"] not in OPEN | CLOSED for t in targets
        ):
            return abstention("Recorded target state is unavailable.")
        ids = sorted({str(t["bug_id"]) for t in targets}, key=int)
        if mode == "unresolved_count":
            value, kind = sum(t["status"] in OPEN for t in targets), "integer"
        elif mode == "depends_fixed":
            if any(t["status"] in CLOSED and not t["resolution"] for t in targets):
                return abstention("Recorded target resolution is unavailable.")
            # Shared answer contract represents structured objects as JSON text.
            value = json.dumps(
                dict(
                    depends_on=ids,
                    resolved_fixed=sorted(
                        {
                            str(t["bug_id"])
                            for t in targets
                            if t["status"] in CLOSED and t["resolution"] == "FIXED"
                        },
                        key=int,
                    ),
                ),
                sort_keys=True,
            )
            kind = "structured"
        else:
            value, kind = ids, "id_set"
    elif mode == "field" and plan:
        value = result.get("fields", {}).get(plan["args"]["fields"][0])
        kind = "string"
    else:
        return None
    if value is None:
        return abstention("The verified public tool result is unknown.")
    return dict(
        abstain=False,
        answer=value,
        answer_type=kind,
        bug_ids=[],
        citations=result.get("evidence_ids", []),
        rationale="Computed from the recorded public tool result.",
    )


def answer(state, tools, call, backend, config):
    parsed = preparse(state)
    if parsed["facts"].get("refused_population"):
        state["tool_log"].append(
            dict(
                name="population_refusal",
                arguments={},
                plan_source="parser",
                result=dict(known=False),
            )
        )
        return abstention("Test populations are refused."), []
    source = "parser"
    plan = parsed["plan"]
    if not parsed["complete"]:
        source = "fallback"
        payload = dict(
            question=state["question"],
            explicit_facts=parsed["facts"],
            tools={k: v["description"] for k, v in SPECS.items()},
        )
        for attempt in range(2):
            try:
                value = call(
                    json.dumps(payload),
                    PLAN_SCHEMA,
                    purpose="json-plan-v2" if not attempt else "json-plan-repair-v2",
                )
                validate(value, PLAN_SCHEMA)
                if (
                    "bug_id" in value["args"]
                    and value["args"]["bug_id"] not in parsed["facts"]["bug_ids"]
                ):
                    raise ValueError("The plan invented a bug ID")
                if (
                    value["tool"] == "get_comment"
                    and value["args"]["comment_ref"] not in state["question"].lower()
                ):
                    raise ValueError("The plan invented a comment reference")
                if plan:
                    for key, expected in plan["args"].items():
                        if key in value["args"] and value["args"][key] != expected:
                            raise ValueError("The plan contradicted explicit question facts")
                plan = value
                source = "repair" if attempt else "llm"
                break
            except (InvalidJSONResponse, ValidationError, ValueError, KeyError) as exc:
                state["errors"].append("json_plan_v2:" + type(exc).__name__)
                payload["repair"] = (
                    "Return one exact tool name and args matching its schema. No function calls."
                )
    result = {}
    mapping = {}
    if plan:
        validate(plan, PLAN_SCHEMA)
        # Keep execution/answer operation from question syntax, never LLM-provided gold/type.
        parsed["plan"] = plan
        if plan["tool"] == "count_bugs":
            parsed["facts"]["mode"] = "count"
        elif plan["tool"] == "get_linked_bugs" and parsed["facts"]["mode"] is None:
            text = state["question"].lower()
            parsed["facts"]["mode"] = (
                "unresolved_count"
                if "how many" in text and "unresolved" in text
                else "depends_fixed"
                if "which of those" in text and "fixed" in text
                else "id_set"
            )
        elif plan["tool"] == "get_lifecycle" and parsed["facts"]["mode"] is None:
            text = state["question"].lower()
            parsed["facts"]["mode"] = (
                "reopened" if "reopened" in text else "hours" if "hours" in text else "text"
            )
        elif plan["tool"] == "get_bug_fields" and len(plan["args"]["fields"]) == 1:
            parsed["facts"]["mode"] = "field"
        q = dict(state, scope={**state.get("scope", {}), **parsed["facts"]["scope"]})
        try:
            result = tools.execute(plan["tool"], plan["args"], q)
        except (ValueError, ValidationError, KeyError) as exc:
            result = dict(known=False, reason=type(exc).__name__, evidence_ids=[])
        if parsed["facts"].get("temporal_requested") and plan["tool"] != "get_lifecycle":
            result = dict(known=False, reason="No verified historical snapshot", evidence_ids=[])
        state["tool_log"].append(
            dict(
                name=plan["tool"],
                arguments=plan["args"],
                result=result,
                plan_source=source,
                explicit_facts=parsed["facts"],
            )
        )
        direct = deterministic(parsed, result)
        if direct is not None:
            return direct, result.get("evidence_ids", [])
        ids = result.get("evidence_ids", [])
        if plan["tool"] == "get_comment" or "chunks" in result:
            docs = (
                tools.comment_chunks(**plan["args"])
                if plan["tool"] == "get_comment"
                else result["chunks"]
            )
            evidence, mapping = pack(docs, config["context_tokens"])
            ids = list(mapping.values())
            payload = dict(
                question=state["question"],
                evidence=evidence,
                citation_map=mapping,
                evidence_ids=ids,
            )
        else:
            payload = dict(question=state["question"], tool_result=result, evidence_ids=ids)
    else:
        docs, _ = backend.retrieve(state, "R1", k=10, use_cache=False)
        evidence, mapping = pack(docs, config["context_tokens"])
        ids = list(mapping.values())
        payload = dict(question=state["question"], evidence=evidence, citation_map=mapping)
        state["tool_log"].append(
            dict(
                name="text_retrieval_fallback",
                plan_source="fallback",
                arguments={"method": "R1"},
                result={"evidence_ids": ids},
            )
        )
    value = call(json.dumps(payload), ANSWER_SCHEMA, purpose="json-tool-answer-v2")
    validate(value, ANSWER_SCHEMA)
    return normalize_citations(value, mapping)[0], ids

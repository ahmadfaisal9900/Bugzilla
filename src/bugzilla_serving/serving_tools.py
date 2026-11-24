"""Serving-only additions to the research database tools: grouped counts for ranking questions.

The research tools count one component at a time, so "which component has the most bugs?" could
not be answered. The chat adds one read-only grouped count. The evaluation tool list is unchanged.
"""

from __future__ import annotations

import re

from jsonschema import validate

from bugzilla_qa.answering.tools import RESOLUTIONS, STATUSES, TOOLS, Tools, obj

GROUP_FIELDS = {
    "component": "component",
    "product": "product",
    "status": "snapshot_status",
    "resolution": "snapshot_resolution",
}

COUNT_BY = {
    "name": "count_bugs_by",
    "description": (
        "Count all bugs in the sample grouped by one field, sorted by count. Use for most, "
        "fewest, top, per-component or breakdown questions."
    ),
    "parameters": obj(
        {
            "field": {"type": "string", "enum": list(GROUP_FIELDS)},
            "order": {"type": "string", "enum": ["most", "fewest"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "status": {"type": "string", "enum": STATUSES},
            "resolution": {"type": "string", "enum": RESOLUTIONS},
        },
        ["field"],
    ),
}

# submit_answer stays last, as in the research list.
SERVING_TOOLS = [*TOOLS[:-1], COUNT_BY, TOOLS[-1]]

_RANKING = re.compile(
    r"\b(most|least|fewest|top|largest|biggest|highest|lowest|rank\w*|breakdown|"
    r"distribution|per|each|by)\b",
    re.IGNORECASE,
)
_GROUP = re.compile(r"\b(components?|products?|status(es)?|resolutions?)\b", re.IGNORECASE)


def is_ranking_question(text: str) -> bool:
    """'Which component has the most bugs?', 'top 5 products', 'bugs per status'."""
    return bool(_RANKING.search(text) and _GROUP.search(text))


class ServingTools(Tools):
    def execute(self, name, args, question):
        if name != COUNT_BY["name"]:
            return super().execute(name, args, question)
        validate(args, COUNT_BY["parameters"])
        column = GROUP_FIELDS[args["field"]]
        clauses, params = [], []
        for key in ("status", "resolution"):
            if key in args:
                clauses.append(GROUP_FIELDS[key] + "=?")
                params.append(args[key])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        fewest = args.get("order") == "fewest"
        # Always show a few runners-up: a one-row result reads as "only one group exists".
        limit = max(args.get("limit", 10), 5)
        rows = self.db.execute(
            f"SELECT {column}, count(DISTINCT bug_id) AS n FROM bugs{where} "
            f"GROUP BY 1 ORDER BY n {'ASC' if fewest else 'DESC'}, 1 LIMIT ?",
            [*params, limit],
        ).fetchall()
        groups, bugs = self.db.execute(
            f"SELECT count(DISTINCT {column}), count(DISTINCT bug_id) FROM bugs{where}", params
        ).fetchone()
        result = {
            "field": args["field"],
            "ranking": ("fewest" if fewest else "most") + " bugs first",
            "groups": [{"rank": i, "value": v, "count": n} for i, (v, n) in enumerate(rows, 1)],
            "groups_total": groups,
            "bugs_counted": bugs,
            "scope": "all bugs in the serving sample (complete, not a search result)",
            "evidence_ids": [],
        }
        if rows:
            top, count = rows[0]
            result["summary"] = (
                f"{top} has the {'fewest' if fewest else 'most'} bugs: {count} of {bugs}, "
                f"out of {groups} {args['field']} values."
            )
        return result

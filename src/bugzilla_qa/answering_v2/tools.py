"""New allowlisted lookups; existing count/history implementations are reused."""

import re
from copy import deepcopy

from jsonschema import validate

from bugzilla_qa.answering.contracts import public_chunk
from bugzilla_qa.answering.tools import ID, RELATIONS, Tools, obj
from bugzilla_qa.answering.tools import TOOLS as LEGACY_TOOLS

TOOLS = deepcopy(LEGACY_TOOLS)
TOOLS = [t for t in TOOLS if t["name"] != "get_links"]
TOOLS.extend(
    [
        dict(
            name="get_linked_bugs",
            description=(
                "bugs blocking X = X.depends_on targets; bugs X blocks = X.blocks. "
                "Use relation=blocks,direction=incoming for blockers; outgoing for bugs X blocks. "
                "Returns target recorded fields and cohort membership, "
                "filtered to the question scope."
            ),
            parameters=obj(
                dict(
                    bug_id=ID,
                    relation=dict(type="string", enum=RELATIONS),
                    direction=dict(type="string", enum=["incoming", "outgoing"]),
                ),
                ["bug_id", "relation", "direction"],
            ),
        ),
        dict(
            name="get_comment",
            description="Resolve a cited record hash to public comment text only.",
            parameters=obj(
                dict(bug_id=ID, comment_ref=dict(type="string", pattern="^[a-f0-9]{12,64}$")),
                ["bug_id", "comment_ref"],
            ),
        ),
    ]
)
for spec in TOOLS:
    if spec["name"] == "get_bug_fields":
        spec["parameters"]["properties"]["fields"].update(maxItems=8, uniqueItems=True)


def require_dev(question):
    scope = question.get("scope", {})
    scope = scope.get("original_scope", scope)
    if question.get("split") != "dev" or (
        question.get("family") == "F3" and scope.get("partition") == "test"
    ):
        raise ValueError("Only development questions/populations are permitted")


class ToolsV2(Tools):
    def comment_chunks(self, bug_id, comment_ref):
        if not re.fullmatch(r"[a-f0-9]{12,64}", comment_ref):
            raise ValueError("Expected cited comment hash")
        candidates = [
            d
            for d in self.backend.docs
            if str(d["bug_id"]) == str(bug_id)
            and d.get("kind", d.get("chunk_type")) == "comment"
            and d["record_id"].startswith(comment_ref)
        ]
        if len({d["record_id"] for d in candidates}) != 1:
            raise ValueError("Unknown or ambiguous cited comment")
        # Fail closed on every segment, including mixed-visibility records.
        return sorted(
            [public_chunk(d) for d in candidates],
            key=lambda d: (d.get("source_char_start", 0), d["chunk_id"]),
        )

    def get_comment(self, bug_id, comment_ref):
        chunks = self.comment_chunks(bug_id, comment_ref)
        return dict(
            known=True,
            label="Cited comment",
            record_id=chunks[0]["record_id"],
            text="\n".join(d["text"] for d in chunks),
            evidence_ids=[d["chunk_id"] for d in chunks],
        )

    def get_linked_bugs(self, bug_id, relation, direction, question):
        """bugs blocking X = X.depends_on targets; bugs X blocks = X.blocks.

        incoming blocks and outgoing depends_on are equivalent semantic queries.
        Unpaired raw reverse-edge rows do not override this explicit convention.
        Non-cohort/conflicted targets have in_cohort=false and are excluded when
        the question says within the downloaded cohort.
        """
        if not self.db.execute("SELECT 1 FROM bugs WHERE bug_id=?", [str(bug_id)]).fetchone():
            return dict(
                known=False,
                reason="Source bug is outside the public canonical records",
                evidence_ids=[],
            )
        if relation in ("blocks", "depends_on"):
            effective = (
                relation
                if direction == "outgoing"
                else {"blocks": "depends_on", "depends_on": "blocks"}[relation]
            )
            sql = "SELECT DISTINCT target_bug_id FROM bug_links WHERE bug_id=? AND relation=?"
        else:
            sql = (
                "SELECT DISTINCT target_bug_id FROM bug_links WHERE bug_id=? AND relation=?"
                if direction == "outgoing"
                else "SELECT DISTINCT bug_id FROM bug_links WHERE target_bug_id=? AND relation=?"
            )
            effective = relation
        ids = sorted(
            {str(r[0]) for r in self.db.execute(sql, [str(bug_id), effective]).fetchall()}, key=int
        )
        targets = []
        for target in ids:
            row = self.db.execute(
                """SELECT snapshot_status,snapshot_resolution,component,
                EXISTS(SELECT 1 FROM sample_membership m WHERE m.bug_id=b.bug_id AND m.seed=?)
                AND NOT EXISTS(SELECT 1 FROM source_records v WHERE v.bug_id=b.bug_id
                    AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT')
                FROM bugs b WHERE bug_id=?""",
                [self.config["seed"], target],
            ).fetchone()
            targets.append(
                dict(
                    bug_id=target,
                    status=row[0] if row else None,
                    resolution=row[1] if row else None,
                    component=row[2] if row else None,
                    in_cohort=bool(row and row[3]),
                )
            )
        cohort_only = "cohort" in question["question"].lower()
        kept = [t for t in targets if t["in_cohort"] or not cohort_only]
        evidence = set(self.evidence(bug_id, {"link", "relationship"}))
        for target in kept:
            evidence.update(self.evidence(target["bug_id"], {"metadata"}))
        return dict(
            targets=kept,
            excluded_outside_cohort=[
                t["bug_id"] for t in targets if cohort_only and not t["in_cohort"]
            ],
            relation=relation,
            direction=direction,
            effective_outgoing_relation=effective,
            snapshot_as_of="UNKNOWN",
            evidence_ids=sorted(evidence),
        )

    def execute(self, name, args, question):
        require_dev(question)
        spec = next((s for s in TOOLS if s["name"] == name and name != "submit_answer"), None)
        if spec is None:
            raise ValueError("Unknown or forbidden tool")
        validate(args, spec["parameters"])
        if name == "count_bugs" and question.get("scope", {}).get("partition") == "test":
            raise ValueError("Test population refused")
        if name == "search_text":
            hits, cached = self.backend.retrieve(
                dict(question, question=args["query"]), "R1", k=args["k"], use_cache=False
            )
            return dict(chunks=hits, cache_hit=cached, evidence_ids=[h["chunk_id"] for h in hits])
        if name == "get_comment":
            return self.get_comment(args["bug_id"], args["comment_ref"])
        if name == "get_linked_bugs":
            return self.get_linked_bugs(**args, question=question)
        return super().execute(name, args, question)

"""Phase 6 M3: validated intents run allowlisted, parameterized, read-only SQL.

Nothing model-written or question-written ever becomes SQL text. `parse_dev_wording` is built from
development wording only: held-out test wording returns None on purpose, and NO_INTENT scores as
incorrect. The study's M3 needs an intent parser that passes `validate_intent` for held-out wording.
"""
import json
import re

import duckdb

from bugzilla_qa.benchmark import phase05 as p5
from bugzilla_qa.data import normalize, phase04 as p4
from bugzilla_qa.methods.contract import NO_INTENT, make_answer

METHOD = "M3"
BUG_URL = "https://bugzilla.mozilla.org/show_bug.cgi?id="
LOOKUP_COLUMNS = {"product": "product", "component": "component",
                  "status": "snapshot_status", "resolution": "snapshot_resolution"}
FILTER_COLUMNS = {"component": "component", "status": "snapshot_status", "creation_year": "year(opened_at_utc)"}
RELATIONS = frozenset(normalize.RELATIONS.values())
ABSTAIN_REASONS = {"engineer_hours": "These records contain no measured engineer-hours or work log.",
                   "export_time": "The original CSV export time is not recorded in these records.",
                   "explanation": "Structured rows alone do not support an explanation."}
# Static text only. Values always travel as bound parameters.
LOOKUP_SQL = {f: f"SELECT {c} FROM bugs WHERE bug_id=?" for f, c in LOOKUP_COLUMNS.items()}
COUNT_SQL = {f: f"SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND {c}=?"
             for f, c in FILTER_COLUMNS.items()}
TARGETS_SQL = ("SELECT DISTINCT target_bug_id FROM bug_links WHERE bug_id=? AND relation=? "
               "AND target_bug_id IS NOT NULL LIMIT 10000")
OPENED_SQL = "SELECT strftime(opened_at_utc, '%Y-%m-%dT%H:%M:%S.%fZ') FROM bugs WHERE bug_id=?"
# The overlay stores old_value/new_value JSON-encoded, so FIXED is the 7 characters "FIXED".
EVENTS_SQL = ("SELECT event_time_utc FROM field_changes WHERE bug_id=? AND field_name=? AND new_value=? "
              "AND old_value IS DISTINCT FROM ? AND history_state='PARSED'")
HISTORY_ROWS_SQL = "SELECT count(*) FROM field_changes WHERE bug_id=? AND history_state='PARSED'"
POPULATION_SQL = """SELECT b.bug_id FROM bugs b JOIN sample_membership m USING(bug_id)
    JOIN source_records s USING(source_record_id)
    WHERE NOT EXISTS(SELECT 1 FROM source_records v WHERE v.bug_id=b.bug_id
        AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT') ORDER BY b.bug_id"""

_BUG = r"Firefox bug (\d+)\?"
DEV_WORDING = (
    (re.compile(r"what (product|component|status|resolution) is recorded for " + _BUG),
     lambda m: {"template": "field_lookup", "field": m[1], "bug_id": m[2]}),
    (re.compile(r"how many calendar hours elapsed from filing to the FIRST evidenced FIXED transition for " + _BUG),
     lambda m: {"template": "first_fixed_hours", "bug_id": m[1]}),
    (re.compile(r"how many explicit transitions into REOPENED occur for " + _BUG),
     lambda m: {"template": "reopen_count", "bug_id": m[1]}),
    (re.compile(r"how many distinct Firefox bug IDs have (component|status|creation_year)=(.+?) in the (dev|test) partition\?"),
     lambda m: {"template": "count_in_partition", "field": m[1], "value": m[2], "partition": m[3]}),
    (re.compile(r"which target bug IDs are explicitly recorded for (\w+) from " + _BUG),
     lambda m: {"template": "relation_targets", "relation": m[1], "bug_id": m[2]}),
    (re.compile(r"what reason or constraint is explicitly stated in cited comment \S+ for " + _BUG),
     lambda m: {"template": "abstain", "reason": "explanation"}),
    (re.compile(r"what exact UTC export timestamp establishes the archived fields for " + _BUG),
     lambda m: {"template": "abstain", "reason": "export_time"}),
    (re.compile(r"how many engineer work hours were spent on " + _BUG),
     lambda m: {"template": "abstain", "reason": "engineer_hours"}),
)


def _bug_id(value):
    return isinstance(value, str) and re.fullmatch(r"\d{1,12}", value) is not None


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 200


INTENTS = {
    "field_lookup": {"bug_id": _bug_id, "field": lambda v: v in LOOKUP_COLUMNS},
    "first_fixed_hours": {"bug_id": _bug_id},
    "reopen_count": {"bug_id": _bug_id},
    "count_in_partition": {"field": lambda v: v in FILTER_COLUMNS, "value": _text, "partition": lambda v: v in ("dev", "test")},
    "relation_targets": {"bug_id": _bug_id, "relation": lambda v: v in RELATIONS},
    "abstain": {"reason": lambda v: v in ABSTAIN_REASONS},
}


def validate_intent(intent):
    """Allowlist gate for any intent parser, including a future LLM one."""
    if not isinstance(intent, dict):
        return False
    spec = INTENTS.get(intent.get("template")) if isinstance(intent.get("template"), str) else None
    if spec is None or set(intent) != set(spec) | {"template"}:
        return False
    try:
        return all(check(intent[name]) for name, check in spec.items())
    except TypeError:  # an unhashable value is simply not on the allowlist
        return False


def parse_dev_wording(question):
    for pattern, build in DEV_WORDING:
        match = pattern.search(question)
        if match:
            return build(match)
    return None


class SqlStore:
    """Read-only connections to the canonical database and the separate API history overlay."""

    def __init__(self, base_path, overlay_path, seed=317):
        self.seed = seed
        self.base = duckdb.connect(str(base_path), read_only=True)
        self.base.execute("SET TimeZone='UTC'")
        self.base.execute("SET memory_limit='512MB'")
        self.overlay = duckdb.connect(str(overlay_path), read_only=True)
        self.population = {b for b, in self.base.execute(POPULATION_SQL).fetchall()}
        self.partitions = {sp: sorted(b for b in self.population if p5.partition(seed, b) == sp) for sp in ("dev", "test")}
        self.population_sha256 = p5.digest(self.partitions)

    def close(self):
        self.base.close()
        self.overlay.close()

    def _events(self, bug, field, value):
        token = p4.canonical(value)
        return [p5.dt(t) for t, in self.overlay.execute(EVENTS_SQL, [int(bug), field, token, token]).fetchall()]

    def _has_history(self, bug):
        return self.overlay.execute(HISTORY_ROWS_SQL, [int(bug)]).fetchone()[0] > 0

    def execute(self, intent, scope):
        """Returns (text, abstained, value, evidence)."""
        template = intent["template"]
        if template == "abstain":
            return ABSTAIN_REASONS[intent["reason"]], True, None, []
        if template == "count_in_partition":
            return self._count(intent, scope)
        bug = intent["bug_id"]
        if bug not in self.population:
            return f"Bug {bug} is outside the frozen sample.", True, None, []
        return getattr(self, "_" + template)(intent, bug)

    def _field_lookup(self, intent, bug):
        value = self.base.execute(LOOKUP_SQL[intent["field"]], [bug]).fetchone()[0]
        evidence = [{"bug_id": bug, "record_id": "snapshot:" + bug, "url": BUG_URL + bug}]
        if value is None:
            return f"Bug {bug} has no recorded {intent['field']}.", True, None, evidence
        return f"Bug {bug} has recorded {intent['field']} {value}.", False, value, evidence

    def _first_fixed_hours(self, intent, bug):
        unknown = f"No qualifying verified FIXED transition is available for bug {bug}."
        opened = self.base.execute(OPENED_SQL, [bug]).fetchone()[0]
        if opened is None:
            return unknown, True, None, []
        opened = p5.dt(opened)
        fixed = [t for t in self._events(bug, "resolution", "FIXED") if t >= opened]
        if not fixed:
            return unknown, True, None, []
        first = min(fixed)
        hours = (first - opened).total_seconds() / 3600
        text = (f"Filed {opened.isoformat()}; first FIXED {first.isoformat()}; difference {hours} calendar hours. "
                "This is elapsed time, not engineer work hours.")
        return text, False, hours, _history_evidence(bug)

    def _reopen_count(self, intent, bug):
        if not self._has_history(bug):
            return f"No verified history is available for bug {bug}.", True, None, []
        count = len(self._events(bug, "status", "REOPENED"))
        return f"Bug {bug} has {count} recorded transitions into REOPENED.", False, count, _history_evidence(bug)

    def _count(self, intent, scope):
        field, value, partition = intent["field"], intent["value"], intent["partition"]
        if scope.get("partition") != partition:
            return "The question's partition differs from its stated scope.", True, None, []
        expected = scope.get("population_manifest_sha256")
        if expected != self.population_sha256:
            return "The stated population does not match this database.", True, None, []
        if field == "creation_year":
            if not re.fullmatch(r"\d{4}", value):
                return f"{value} is not a filing year.", True, None, []
            value = int(value)
        count = self.base.execute(COUNT_SQL[field], [self.partitions[partition], value]).fetchone()[0]
        text = f"{count} distinct bugs in the {partition} partition have {field}={intent['value']}."
        return text, False, count, [{"bug_id": None, "record_id": "population:" + expected, "url": None}]

    def _relation_targets(self, intent, bug):
        rows = self.base.execute(TARGETS_SQL, [bug, intent["relation"]]).fetchall()
        targets = sorted((t for t, in rows), key=int)
        text = f"Bug {bug} records {intent['relation']} targets: {', '.join(targets) or 'none'}."
        return text, False, targets, [{"bug_id": bug, "record_id": "snapshot:" + bug, "url": BUG_URL + bug}]


def _history_evidence(bug):
    return [{"bug_id": bug, "record_id": "history:" + bug, "url": f"{p4.BASE_URL}/bug/{bug}/history"}]


def answer_question(store, question, parser=parse_dev_wording):
    """Takes only the inference fields: qid, question, scope."""
    qid = question["qid"]
    intent = parser(question["question"])
    if not validate_intent(intent):
        return make_answer(qid, METHOD, "", status=NO_INTENT, trace={"intent": json.dumps(intent, default=str)})
    text, abstained, value, evidence = store.execute(intent, question["scope"])
    return make_answer(qid, METHOD, text, abstained, value, evidence, trace={"intent": intent})

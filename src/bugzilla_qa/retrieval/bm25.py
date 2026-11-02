"""Phase 6: standard-library BM25 and the shared text corpus for M1 and M2.

Every arm sees the same documents. They are built from source records, never from benchmark gold or
review sheets. Private or unavailable comment bodies are excluded.
"""
import json
import math
import re
from collections import Counter, defaultdict

from bugzilla_qa.benchmark import phase05 as p5
from bugzilla_qa.data import phase04 as p4
from bugzilla_qa.methods.m3_sql import BUG_URL, POPULATION_SQL

TOKEN = re.compile(r"[a-z0-9]+")
CHUNK_WORDS = 200
OVERLAP_WORDS = 40


def tokenize(text):
    return TOKEN.findall(text.lower())


class BM25Index:
    def __init__(self, documents, k1=1.5, b=0.75):
        self.documents, self.k1, self.b = list(documents), k1, b
        self.postings, self.lengths = defaultdict(list), []
        for number, doc in enumerate(self.documents):
            counts = Counter(tokenize(doc["text"]))
            self.lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self.postings[term].append((number, frequency))
        self.average = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0

    def search(self, query, k=10):
        """Ties break on doc_id, so identical input always gives an identical ranking."""
        total, scores = len(self.documents), defaultdict(float)
        for term in sorted(set(tokenize(query))):
            postings = self.postings.get(term, ())
            idf = math.log(1 + (total - len(postings) + 0.5) / (len(postings) + 0.5))
            for number, frequency in postings:
                norm = 1 - self.b + self.b * self.lengths[number] / self.average
                scores[number] += idf * frequency * (self.k1 + 1) / (frequency + self.k1 * norm)
        ranked = sorted(scores.items(), key=lambda x: (-x[1], self.documents[x[0]]["doc_id"]))
        return [{**self.documents[n], "score": s, "rank": rank + 1} for rank, (n, s) in enumerate(ranked[:k])]


def chunks(text, size=CHUNK_WORDS, overlap=OVERLAP_WORDS):
    words = text.split()
    if len(words) <= size:
        return [" ".join(words)] if words else []
    step = size - overlap
    return [" ".join(words[start:start + size]) for start in range(0, len(words) - overlap, step)]


def _document(doc_id, record_id, bug, kind, text, url):
    return {"doc_id": doc_id, "record_id": record_id, "bug_id": bug, "kind": kind, "text": text, "url": url}


def snapshot_documents(db, population):
    """Structured fields rendered as text, so M1 and M2 get the same facts M3 can query."""
    links = defaultdict(list)
    for bug, relation, target in db.execute("""SELECT bug_id, relation, target_bug_id FROM bug_links
            WHERE target_bug_id IS NOT NULL ORDER BY bug_id, relation, target_bug_id""").fetchall():
        if bug in population:
            links[bug].append(f"{relation} {target}")
    rows = db.execute("""SELECT bug_id, product, component, snapshot_status, snapshot_resolution,
            strftime(opened_at_utc, '%Y-%m-%dT%H:%M:%SZ'), summary FROM bugs ORDER BY bug_id""").fetchall()
    for bug, product, component, status, resolution, opened, summary in rows:
        if bug not in population:
            continue
        text = (f"Firefox bug {bug}. product {product}. component {component}. status {status}. "
                f"resolution {resolution or 'none'}. filed {opened or 'unknown'}. summary {p5.safe(summary or '')}. "
                f"recorded links: {'; '.join(links[bug]) or 'none'}.")
        yield _document("snapshot:" + bug, "snapshot:" + bug, bug, "bug_snapshot", text, BUG_URL + bug)


def comment_documents(db, population):
    """The comment key is in the text because F5 cites it; report F5 recall as a pointer lookup (D-043)."""
    cursor = db.execute("""SELECT bug_id, comment_key, source_url, body FROM comments
        WHERE private_flag=false AND text_availability='AVAILABLE' AND body IS NOT NULL ORDER BY comment_key""")
    while True:
        batch = cursor.fetchmany(1024)
        if not batch:
            return
        for bug, key, url, body in batch:
            if bug not in population:
                continue
            for number, part in enumerate(chunks(p5.safe(body))):
                yield _document(f"comment:{key}:{number}", key, bug, "comment",
                                f"Firefox bug {bug}. comment {key}. {part}", url)


def history_documents(overlay, population):
    """Verified API events as text; actor fields stay out."""
    events = defaultdict(list)
    for bug, when, field, old, new in overlay.execute("""SELECT bug_id, event_time_utc, field_name, old_value, new_value
            FROM field_changes WHERE history_state='PARSED' ORDER BY bug_id, event_time_utc, event_index, change_index""").fetchall():
        events[str(bug)].append(f"{when} {field} {json.loads(old)} to {json.loads(new)}")
    for bug in sorted(events):
        if bug in population:
            text = f"Firefox bug {bug}. verified history: " + "; ".join(events[bug]) + "."
            for number, part in enumerate(chunks(text)):
                yield _document(f"history:{bug}:{number}", "history:" + bug, bug, "history", part,
                                f"{p4.BASE_URL}/bug/{bug}/history")


def build_corpus(db, overlay):
    population = {b for b, in db.execute(POPULATION_SQL).fetchall()}
    yield from snapshot_documents(db, population)
    yield from comment_documents(db, population)
    yield from history_documents(overlay, population)


def relevant_records(item):
    """Record IDs a retriever should surface; empty when text retrieval cannot apply (F3, F6)."""
    # bug_ids is sorted and includes link targets, so only the evidence names the parent reliably.
    bug = item["evidence"][0]["bug_id"]
    if item["family"] in ("F1", "F4"):
        return {"snapshot:" + bug}
    if item["family"] == "F2":
        return {"history:" + bug}
    if item["family"] == "F5":
        return {e["id"] for e in item["evidence"]}
    return set()


def recall_at(retrieved, relevant, k):
    return len({d["record_id"] for d in retrieved[:k]} & relevant) / len(relevant)


def precision_at(retrieved, relevant, k):
    top = retrieved[:k]
    return sum(d["record_id"] in relevant for d in top) / len(top) if top else 0.0

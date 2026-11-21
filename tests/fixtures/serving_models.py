"""Transparent retrieval test doubles; never used by a deployed runner."""


class Dense:
    def __init__(self, docs):
        self.docs = docs

    def search(self, query, k, filter_bug=True, allowed_bug_ids=None):
        terms = set(query.lower().split())
        docs = [d for d in self.docs if allowed_bug_ids is None or d["bug_id"] in allowed_bug_ids]
        hits = [dict(d, score=float(len(terms & set(d["text"].lower().split())))) for d in docs]
        return sorted(hits, key=lambda d: (-d["score"], d["chunk_id"]))[:k]


class Cross:
    def predict(self, pairs, **kwargs):
        return [len(set(q.lower().split()) & set(t.lower().split())) for q, t in pairs]

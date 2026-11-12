"""Small deterministic rules used by the planned v3 dataset builder."""
import hashlib
import math
import re

FAMILIES = ('KI','MH','F6H','F1','F2','F3','F4','F5','F6')


def cluster_split(seed, bug_id):
    value = hashlib.sha256(('%s:v3:%s' % (seed, bug_id)).encode()).digest()
    return 'dev' if int.from_bytes(value[:8], 'big') % 3 == 0 else 'test'


def tokens(text):
    return re.findall(r'\w+', text.casefold())


def valid_description(description, summary):
    if not isinstance(description, str) or not description.strip():
        return False
    if re.search(r'(?i)\b(?:bug|issue|report)\s*#?\s*\d+\b|#\d+\b|(?<!\w)\d{5,}(?!\w)', description):
        return False
    candidate, original = tokens(description), tokens(summary)
    fivegrams = {tuple(original[i:i+5]) for i in range(len(original)-4)}
    return not any(tuple(candidate[i:i+5]) in fivegrams for i in range(len(candidate)-4))


def cosine(a, b):
    if len(a) != len(b) or not a:
        raise ValueError('Vectors must have the same positive dimension')
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    if not norm:
        raise ValueError('Zero vectors cannot establish similarity')
    return sum(x*y for x,y in zip(a,b))/norm


def ambiguity_set(root, duplicate_edges, vectors, threshold=0.92, max_alternates=3):
    root = str(root)
    if root not in vectors:
        raise ValueError('Missing root summary embedding')
    neighbours = {str(b) for a,b in duplicate_edges if str(a) == root}
    neighbours.update(str(a) for a,b in duplicate_edges if str(b) == root)
    neighbours &= set(vectors)
    neighbours.update(str(bug) for bug, vector in vectors.items() if cosine(vectors[root], vector) >= threshold)
    neighbours.discard(root)
    if len(neighbours) > max_alternates:
        return None
    return sorted({root} | neighbours, key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value))

"""Source-only retrieval primitives. No benchmark questions or gold enter an index."""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

TOKEN = re.compile(r"[A-Za-z0-9]+")
BUG_ID = re.compile(r"\bbug\s*#?\s*(\d+)\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def safe_text(value):
    text = EMAIL.sub('[email]', str(value or ''))
    return re.sub(r'(?<!\w)@[A-Za-z][\w.-]*', '[handle]', text)


def chunks(text, size=180, overlap=30):
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError('invalid chunk size/overlap')
    words = text.split()
    for start in range(0, len(words), size - overlap):
        yield ' '.join(words[start:start + size])
        if start + size >= len(words):
            break


def make_chunks(record, size=180, overlap=30):
    required = ('record_id', 'bug_id', 'kind', 'text', 'url', 'source_hash', 'visibility')
    if any(k not in record for k in required):
        raise ValueError('missing document field')
    if record['visibility'] != 'public':
        raise ValueError('non-public or unknown visibility')
    for i, part in enumerate(chunks(safe_text(record['text']), size, overlap)):
        yield dict(record, text=part, chunk_id=record['record_id'] + ':' + str(i),
                   chunk_hash=hashlib.sha256(part.encode()).hexdigest())


def tokenizer_chunks(record, tokenizer, size=180, overlap=30):
    """Offsets are into sanitized public text; no tokenizer truncation is requested."""
    if size <= 0 or not 0 <= overlap < size: raise ValueError('invalid chunk configuration')
    if record.get('visibility')!='public': raise ValueError('non-public or unknown visibility')
    text=safe_text(record['text'])
    offsets=tokenizer(text,add_special_tokens=False,return_offsets_mapping=True,truncation=False)['offset_mapping']
    for start in range(0,len(offsets),size-overlap):
        end=min(start+size,len(offsets));begin_char=offsets[start][0];end_char=offsets[end-1][1]
        part=text[begin_char:end_char]
        if part:
            yield dict(record,text=part,chunk_id=record['record_id']+':'+str(start),
                       chunk_hash=hashlib.sha256(part.encode()).hexdigest(),
                       source_char_start=begin_char,source_char_end=end_char,
                       offset_basis='sanitized_text',token_count=end-start)
        if end==len(offsets): break


def build_lexical(path, records, identity):
    """Transactional rebuild: an interrupted build is never mistaken for a valid index."""
    path = Path(path)
    temp = path.with_suffix('.building.sqlite')
    if temp.exists():
        temp.unlink()
    db = sqlite3.connect(str(temp))
    try:
        db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('CREATE TABLE docs (chunk_id TEXT PRIMARY KEY, bug_id TEXT, record_id TEXT, payload TEXT NOT NULL)')
        db.execute('CREATE VIRTUAL TABLE search USING fts5(chunk_id UNINDEXED, text)')
        n = 0
        for record in records:
            payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
            db.execute('INSERT INTO docs VALUES (?,?,?,?)', (record['chunk_id'], record['bug_id'], record['record_id'], payload))
            db.execute('INSERT INTO search VALUES (?,?)', (record['chunk_id'], record['text']))
            n += 1
        db.execute('INSERT INTO metadata VALUES (?,?)', ('identity', identity))
        db.execute('INSERT INTO metadata VALUES (?,?)', ('count', str(n)))
        db.commit()
    finally:
        db.close()
    temp.replace(path)
    return n


def lexical_search(path, question, top_k=5, filter_bug=True):
    if top_k < 1:
        raise ValueError('top_k must be positive')
    tokens = TOKEN.findall(question.lower())
    if not tokens:
        return []
    query = ' OR '.join('"' + token + '"' for token in sorted(set(tokens)))
    match = BUG_ID.search(question) if filter_bug else None
    db = sqlite3.connect(str(path))
    try:
        sql = ('SELECT docs.payload, bm25(search) AS score FROM search JOIN docs USING(chunk_id) '
               'WHERE search MATCH ?')
        params = [query]
        if match:
            sql += ' AND docs.bug_id = ?'
            params.append(match.group(1))
        sql += ' ORDER BY score ASC, docs.chunk_id ASC LIMIT ?'
        params.append(top_k)
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [dict(json.loads(payload), rank=i + 1, score=-score) for i, (payload, score) in enumerate(rows)]


def hierarchical_search(path, question, top_k=10, max_bugs=5):
    """Search bug metadata first, then independently search all passages of those bugs."""
    tokens=TOKEN.findall(question.lower())
    if not tokens: return []
    query=' OR '.join('"'+t+'"' for t in sorted(set(tokens)))
    explicit=BUG_ID.search(question)
    db=sqlite3.connect(str(path))
    try:
        sql=("SELECT docs.bug_id, bm25(search) s FROM search JOIN docs USING(chunk_id) "
             "WHERE search MATCH ? AND json_extract(docs.payload,'$.kind')='metadata'")
        params=[query]
        if explicit:
            sql+=' AND docs.bug_id=?';params.append(explicit.group(1))
        parents=[r[0] for r in db.execute(sql+' ORDER BY s, docs.chunk_id LIMIT ?',params+[max_bugs]).fetchall()]
        if not parents: return []
        placeholders=','.join('?' for _ in parents)
        sql=('SELECT docs.payload,bm25(search) s FROM search JOIN docs USING(chunk_id) '
             'WHERE search MATCH ? AND docs.bug_id IN ('+placeholders+') ORDER BY s,docs.chunk_id LIMIT ?')
        rows=db.execute(sql,[query]+parents+[top_k]).fetchall()
        return [dict(json.loads(payload),rank=i,score=-score,stage1_bug_ids=parents) for i,(payload,score) in enumerate(rows,1)]
    finally: db.close()


def rrf(rankings, top_k=5, k=60):
    if k < 1 or top_k < 1:
        raise ValueError('invalid RRF configuration')
    combined = {}
    for name, hits in sorted(rankings.items()):
        seen = set()
        for rank, hit in enumerate(hits, 1):
            key = hit['chunk_id']
            if key in seen:
                continue
            seen.add(key)
            entry = combined.setdefault(key, {'document': hit, 'score': 0.0, 'components': {}})
            entry['score'] += 1.0 / (k + rank)
            entry['components'][name] = {'rank': rank, 'score': hit['score']}
    ordered = sorted(combined.values(), key=lambda x: (-x['score'], x['document']['chunk_id']))[:top_k]
    return [dict(row['document'], rank=i + 1, score=row['score'], components=row['components'])
            for i, row in enumerate(ordered)]


def retrieval_metrics(hits, relevant, family, k=5):
    """Known-citation metrics are incomplete-label proxies, not exhaustive recall."""
    if family in ('F3', 'F6') or not relevant:
        return {'state': 'NOT_APPLICABLE', 'known_citation_recall': None, 'hit': None}
    found = {h['record_id'] for h in hits[:k]} & set(relevant)
    return {'state': 'KNOWN_CITATION_PROXY', 'known_citation_recall': len(found) / len(set(relevant)),
            'hit': bool(found)}

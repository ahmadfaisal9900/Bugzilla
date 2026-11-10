"""Local aggregate corpus audit and pending F5 evidence packets."""
import json
import re
from collections import Counter
from pathlib import Path

from bugzilla_qa.eval_extension.cli import ROOT, file_hash
from bugzilla_qa.eval_extension.retrieval import safe_text


def audit_corpus(path):
    types=Counter(); records=set(); bugs=set(); visibility=Counter(); truncation_candidates=0
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            d=json.loads(line)
            types[d['kind']]+=1;records.add(d['record_id']);bugs.add(d['bug_id']);visibility[d['visibility']]+=1
            if len(d['text'].split()) > 180: truncation_candidates+=1
            if d['visibility']!='public': raise ValueError('non-public chunk in corpus')
            if not d['record_id'] or not d['source_hash'] or not d['chunk_id']: raise ValueError('missing provenance')
    return {'state':'COMPLETE','corpus_sha256':file_hash(Path(path)),'chunks':sum(types.values()),
            'distinct_records':len(records),'distinct_bugs':len(bugs),'chunk_types':dict(types),
            'visibility':dict(visibility),'over_180_words':truncation_candidates,
            'snapshot_as_of_utc':None,'private_unknown_comment_exclusion':'enforced by source query',
            'tokenizer_truncation':'see dense manifest; words are not tokenizer tokens'}


def explanation_packets(config, limit=60):
    import duckdb
    db=duckdb.connect(str(ROOT/config['canonical_db']),read_only=True)
    db.execute("SET memory_limit='512MB'")
    try:
        rows=db.execute('''SELECT c.bug_id,c.comment_key,c.source_url,c.content_hash,c.body
            FROM comments c JOIN sample_membership m USING(bug_id) JOIN bugs b USING(bug_id)
            WHERE m.seed=? AND b.snapshot_resolution='FIXED' AND c.private_flag=false
            AND c.text_availability='AVAILABLE' AND c.body IS NOT NULL
            AND regexp_matches(c.body,'(?i)because|due to|blocked by|waiting for|delayed by')
            QUALIFY row_number() OVER (PARTITION BY c.bug_id ORDER BY c.comment_key)=1
            ORDER BY c.comment_key LIMIT ?''',[config['sample_seed'],limit]).fetchall()
        return [{'bug_id':bug,'comment_id':key,'source_url':url,'content_hash':sha,
                 'public_comment_sanitized':safe_text(body), 'question':'What reason or constraint, if any, does this comment explicitly state?',
                 'suggested_gold':None,'human_review_state':'PENDING_HUMAN_REVIEW',
                 'population':'FIXED-selected comments; not unresolved bugs',
                 'note':'Keyword is a candidate only; human must assess full context and contradictions.'}
                for bug,key,url,sha,body in rows]
    finally: db.close()

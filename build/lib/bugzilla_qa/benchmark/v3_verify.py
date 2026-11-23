"""Independent SQL oracles. Generator answers and wording are never inputs to SQL."""
import json
import math
from jsonschema import validate as validate_schema

from bugzilla_qa.data.normalize import digest
from bugzilla_qa.eval_extension.bank import partition as v2_partition
from .v3_source import FIELD_COLUMNS, null
from .v3_rules import FAMILIES

QUESTION_SCHEMA = {'type':'object','required':['qid','family','split','question','answer_type','cluster_id','generator','provenance'],
    'additionalProperties':False,'properties':{
        'qid':{'type':'string','pattern':'^v3_[0-9a-f]{24}$'},
        'family':{'enum':list(FAMILIES)},'split':{'enum':['dev','test']},
        'question':{'type':'string','minLength':1},
        'answer_type':{'enum':['bug_id','string','integer','structured','id_set','abstain','calendar_hours']},
        'cluster_id':{'type':'string','minLength':1},'generator':{'enum':['deterministic','aux_description']},
        'provenance':{'type':'object','required':['root_bug_id','source_scope','evidence_source_hashes','snapshot_as_of_utc'],
            'properties':{'root_bug_id':{'type':'string','pattern':'^[1-9][0-9]*$'},
                          'source_scope':{'type':'string','minLength':1},'evidence_source_hashes':{'type':'object'},
                          'snapshot_as_of_utc':{'type':'null'}}}}}
GOLD_SCHEMA = {'type':'object','required':['qid','answer','acceptable_bug_ids','evidence_record_ids'],
    'additionalProperties':False,'properties':{'qid':QUESTION_SCHEMA['properties']['qid'],
    'answer':{'type':['string','number','object','array']},
    'acceptable_bug_ids':{'type':'array','uniqueItems':True,'items':{'type':'string','pattern':'^[1-9][0-9]*$'}},
    'evidence_record_ids':{'type':'array','uniqueItems':True,'items':{'type':'string','minLength':1}}}}


def validate_pair(question, gold):
    try:
        validate_schema(question, QUESTION_SCHEMA); validate_schema(gold, GOLD_SCHEMA)
    except Exception:
        raise ValueError('Question or gold schema mismatch') from None
    if question['qid'] != gold['qid']: raise ValueError('Question/gold identity mismatch')
    value, kind = gold['answer'], question['answer_type']
    if kind == 'integer' and type(value) is not int: raise ValueError('Integer answer required')
    if kind == 'calendar_hours' and (type(value) not in (int,float) or not math.isfinite(value) or value < 0):
        raise ValueError('Finite nonnegative calendar hours required')
    if kind in ('bug_id','string') and (not isinstance(value,str) or not value): raise ValueError('String answer required')
    if kind == 'abstain' and value != 'ABSTAIN': raise ValueError('ABSTAIN answer required')
    if kind == 'bug_id' and (not value.isdigit() or value not in gold['acceptable_bug_ids']):
        raise ValueError('Gold bug ID must be among accepted targets')
    if kind == 'id_set' and (not isinstance(value,list) or any(not isinstance(x,str) or not x.isdigit() for x in value) or len(value)!=len(set(value))):
        raise ValueError('Unique bug-ID set required')
    if kind == 'structured':
        if not isinstance(value,dict) or set(value)!={'depends_on','resolved_fixed'}: raise ValueError('Invalid multi-hop answer')
        for name in value:
            if not isinstance(value[name],list) or any(not isinstance(x,str) or not x.isdigit() for x in value[name]) or len(value[name])!=len(set(value[name])):
                raise ValueError('Invalid multi-hop target set')
        if not set(value['resolved_fixed']) <= set(value['depends_on']): raise ValueError('FIXED targets outside dependency set')


def evidence_hash(source, record_id):
    record = source.record_index.get(record_id)
    if not record: raise ValueError('Evidence is not indexed')
    kind = record['kind']
    if kind == 'metadata':
        rows = source.base.execute('SELECT content_hash FROM bugs WHERE source_record_id=?', [record_id]).fetchall()
    elif kind == 'comment':
        rows = source.base.execute("""SELECT content_hash FROM comments WHERE comment_key=?
           AND private_flag=false AND text_availability='AVAILABLE' AND body IS NOT NULL""", [record_id]).fetchall()
    elif kind == 'link':
        rows = source.base.execute('SELECT content_hash FROM bug_links WHERE link_key=?', [record_id]).fetchall()
    elif kind == 'history':
        rows = source.overlay.execute("""SELECT content_sha256 FROM field_changes
            WHERE source_row_key=? AND history_state='PARSED'""", [record_id]).fetchall()
    else: raise ValueError('Unsupported evidence type')
    if not rows or any(row[0] != record['source_hash'] for row in rows):
        raise ValueError('Source and corpus evidence hashes differ')
    return record['source_hash']


def _field(source, bug, field):
    if field not in source.available_fields: raise ValueError('Field unavailable')
    rows = source.base.execute('SELECT ' + FIELD_COLUMNS[field] + ' FROM bugs WHERE bug_id=?', [str(bug)]).fetchall()
    if len(rows) != 1: raise ValueError('Missing or non-unique metadata')
    return rows[0][0]


def recompute(source, oracle):
    """A separate SQL route; no call to candidate-generation functions."""
    kind, root = oracle['kind'], str(oracle['root'])
    cohort = sorted(source.bugs)
    if kind == 'identify':
        count = source.base.execute('SELECT count(*) FROM bugs WHERE bug_id=?', [root]).fetchone()[0]
        if count != 1: raise ValueError('Unknown identification target')
        return root
    if kind == 'field':
        return _field(source, root, oracle['field'])
    if kind in ('depends_fixed', 'duplicate_component', 'blocking_count'):
        if kind == 'blocking_count':
            rows = source.base.execute("""SELECT DISTINCT b.bug_id,b.snapshot_status,b.snapshot_resolution,b.component
              FROM bug_links l JOIN bugs b ON b.bug_id=l.bug_id
              WHERE l.target_bug_id=? AND l.relation='blocks' AND b.bug_id IN (SELECT unnest(?))""",
              [root, cohort]).fetchall()
        else:
            relation = 'depends_on' if kind == 'depends_fixed' else 'duplicate_of'
            rows = source.base.execute("""SELECT DISTINCT b.bug_id,b.snapshot_status,b.snapshot_resolution,b.component
              FROM bug_links l JOIN bugs b ON b.bug_id=l.target_bug_id
              WHERE l.bug_id=? AND l.relation=? AND b.bug_id IN (SELECT unnest(?))""", [root, relation, cohort]).fetchall()
        ids = sorted({str(r[0]) for r in rows}, key=int)
        if ids != oracle['targets']: raise ValueError('Independent complete target set differs')
        if kind == 'depends_fixed':
            fixed = sorted({str(r[0]) for r in rows if r[1] in source.config['closed_statuses'] and r[2] == 'FIXED'}, key=int)
            return {'depends_on': ids, 'resolved_fixed': fixed}
        if kind == 'duplicate_component':
            if len(rows) != 1 or null(rows[0][3]): raise ValueError('Duplicate target component unavailable')
            return rows[0][3]
        if any(r[1] not in source.config['open_statuses'] + source.config['closed_statuses'] for r in rows):
            raise ValueError('Unknown target status')
        return sum(r[1] in source.config['open_statuses'] for r in rows)
    if kind == 'absent':
        if source.base.execute('SELECT count(*) FROM bugs WHERE bug_id=?', [root]).fetchone()[0] != 0:
            raise ValueError('Supposedly absent bug is present')
        return 'ABSTAIN'
    if kind == 'null_field':
        if not null(_field(source, root, oracle['field'])): raise ValueError('Requested field is populated')
        return 'ABSTAIN'
    if kind == 'no_history':
        info = source.history.get(root, {}).get('history', {})
        if (info.get('state') == 'PARSED' and info.get('error') is None
                and info.get('malformed_count') == 0 and info.get('future_event_after_observed_at') is False
                and info.get('chronology_ok') is True):
            raise ValueError('Verified history exists; not a missing-history refusal')
        # Query only the separate overlay. An absent base history table is irrelevant.
        parsed = source.overlay.execute("""SELECT count(*) FROM field_changes
           WHERE CAST(bug_id AS VARCHAR)=? AND history_state='PARSED'""", [root]).fetchone()[0]
        if parsed:
            raise ValueError('Parsed overlay events exist; missing-history claim needs adjudication')
        return 'ABSTAIN'
    if kind == 'v2_f2':
        result = source.f2(root)
        if not result: raise ValueError('Insufficient verified ordered history')
        return result['seconds'] / 3600
    if kind == 'v2_f4':
        return source.independent_targets(root, oracle['relation'])
    if kind == 'v2_f6':
        if oracle['evidence_scope'] != 'product, component, status, resolution and filing time only':
            raise ValueError('Engineer-hours refusal has unsupported scope')
        return 'ABSTAIN'
    if kind == 'v2_f3':
        scope = oracle['scope']
        universe = sorted(b for b in source.bugs if b not in source.conflicts and
                          v2_partition(source.config['seed'], b) == scope['partition'])
        if len(universe) != scope['denominator'] or digest(universe) != scope['population_hash']:
            raise ValueError('Original v2 aggregate population changed')
        filters = scope['filter']
        if len(filters) != 1: raise ValueError('Unsupported aggregate filters')
        field, value = next(iter(filters.items()))
        column = {'component': 'component', 'status': 'snapshot_status', 'resolution': 'snapshot_resolution',
                  'year': 'year(opened_at_utc)'}.get(field)
        if not column: raise ValueError('Unsupported count field')
        if field == 'year': value = int(value)
        return source.base.execute('SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND '
                                   + column + '=?', [universe, value]).fetchone()[0]
    raise ValueError('No independent oracle for this item')


def verify_candidate(source, candidate, excluded):
    question, gold, oracle = candidate['question'], candidate['gold'], candidate['oracle']
    validate_pair(question, gold)
    if oracle['kind'] != 'v2_f3' and set(oracle.get('participants', [str(oracle['root'])])) & excluded:
        raise ValueError('Excluded parent or target bug')
    if recompute(source, oracle) != gold['answer']: raise ValueError('Independent SQL gold mismatch')
    root, kind = str(oracle['root']), oracle['kind']
    if kind in ('identify','field','null_field','no_history','v2_f6'):
        required = {source.metadata_evidence(root)}
        if question['family'] == 'KI':
            if root not in source.comments: raise ValueError('Public KI comment unavailable')
            required.add(source.comments[root]['record_id'])
    elif kind in ('depends_fixed','duplicate_component','blocking_count'):
        participants = [root] + oracle['targets']
        required = {source.metadata_evidence(b) for b in participants}
        if kind == 'blocking_count':
            keys = source.base.execute("""SELECT link_key FROM bug_links WHERE target_bug_id=?
                 AND relation='blocks' AND bug_id IN (SELECT unnest(?))""", [root,oracle['targets']]).fetchall()
        else:
            relation = 'depends_on' if kind == 'depends_fixed' else 'duplicate_of'
            keys = source.base.execute("""SELECT link_key FROM bug_links WHERE bug_id=?
                AND relation=? AND target_bug_id IN (SELECT unnest(?))""", [root,relation,oracle['targets']]).fetchall()
        required.update(r[0] for r in keys)
    elif kind == 'v2_f4':
        required = {r[0] for r in source.base.execute("""SELECT link_key FROM bug_links
            WHERE bug_id=? AND relation=? AND target_bug_id IS NOT NULL""", [root,oracle['relation']]).fetchall()}
    elif kind == 'v2_f2':
        required = {source.metadata_evidence(root), source.f2(root)['record_id']}
    else:
        required = set()
    if set(gold['evidence_record_ids']) != required: raise ValueError('Required complete supporting evidence set differs')
    hashes = {rid: evidence_hash(source, rid) for rid in gold['evidence_record_ids']}
    if hashes != question['provenance']['evidence_source_hashes']:
        raise ValueError('Evidence provenance hash mismatch')
    if gold['answer'] != 'ABSTAIN' and question['family'] != 'F3' and not hashes:
        raise ValueError('Answerable question has no indexed evidence')
    return {'qid': question['qid'], 'state': 'PASS', 'oracle': oracle['kind'],
            'evidence_records_checked': len(hashes)}

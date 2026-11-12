"""Read-only, cohort-bounded sources for v3. Never queries base field_changes."""
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from bugzilla_qa.data.normalize import bug_id, digest
from bugzilla_qa.data.phase04 import parse_utc

FIELD_COLUMNS = {'component': 'component', 'status': 'snapshot_status',
                 'resolution': 'snapshot_resolution', 'severity': 'severity', 'priority': 'priority'}
PUBLIC_SCOPE = 'Frozen downloaded Firefox-product cohort, seed 317; archive snapshot date UNKNOWN; recorded fields only.'


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''): result.update(chunk)
    return result.hexdigest()


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            if line.strip(): yield json.loads(line)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, sort_keys=True, indent=2, default=str) + '\n', encoding='utf-8')
    temp.replace(path)


def write_jsonl(path, values):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as handle:
        for value in values: handle.write(json.dumps(value, sort_keys=True, default=str) + '\n')
    temp.replace(path)


def latest_run(config_path, root):
    from bugzilla_qa.llm.provider import read_config
    config = read_config(config_path)
    directory = Path(root) / config['output_root']
    pointer = json.loads((directory/'LATEST_RUN.json').read_text())
    name = pointer['run']
    if Path(name).name != name or not name.startswith('run-'):
        raise RuntimeError('Invalid v3 latest-run pointer')
    return directory/name


def verify_original(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('state') != 'FROZEN_HUMAN_SIGNED':
        raise RuntimeError('Original benchmark is not validator-frozen')
    for name, expected in manifest['sha256'].items():
        if Path(name).name != name or file_hash(directory / name) != expected:
            raise RuntimeError('Original frozen artifact mismatch')
    return manifest


def verify_exports(config, root):
    root = Path(root)
    original = verify_original(root/config['phase05_dir'])
    if original['id'] != config['phase05_freeze_id']: raise RuntimeError('Unexpected original freeze identity')
    expanded = json.loads((root/config['expanded_manifest']).read_text())
    if expanded['hashes']['selected.jsonl'] != file_hash(root/config['expanded_selected']):
        raise RuntimeError('Existing v2 selected export hash differs')
    natural = json.loads((root/config['natural_manifest']).read_text())
    if natural['sha256'] != file_hash(root/config['natural_approved']):
        raise RuntimeError('Human-approved natural export hash differs')
    return original


def exclusions(directory, natural_path):
    """Extract references from question text/identity only, never original test gold."""
    result = set()
    def add_question(question):
        text = question.get('question', '')
        result.update(m.group(1) for m in re.finditer(r'(?i)\b(?:bug|issue|report)\s*#?\s*(\d+)\b', text))
        result.update(re.findall(r'(?<!\w)[1-9]\d{4,}(?!\w)',text))
        for match in re.finditer(r'(?i)\b(\d+)\s+(?:blocks?|duplicates?|depends on)\s+(?:bug\s*#?\s*)?(\d+)\b',text):
            result.update(match.groups())
        result.update(str(x) for x in question.get('bug_ids', []) if bug_id(x))
        if bug_id(question.get('scope', {}).get('bug_id')):
            result.add(bug_id(question['scope']['bug_id']))
    for split in ('dev', 'test', 'challenge'):
        for question in read_jsonl(Path(directory) / (split + '.questions.jsonl')): add_question(question)
    for question in read_jsonl(natural_path): add_question(question)
    return {bug_id(x) for x in result if bug_id(x)}


def configured_exclusions(config, root):
    from .v3_rules import cluster_split
    root = Path(root)
    original = exclusions(root/config['phase05_dir'], root/config['natural_approved'])
    previous_dev = set()
    if config.get('avoid_prior_v2_dev_roots_in_new_test'):
        for question in read_jsonl(root/config['expanded_selected']):
            if question.get('split') == 'dev' and question['family'] != 'F3':
                previous_dev.update(str(b) for b in question.get('bug_ids', [])
                                    if cluster_split(config['seed'],str(b)) == 'test')
    return original | previous_dev, {'original_or_natural':len(original),
                                     'prior_v2_dev_new_test_roots':len(previous_dev-original)}


def null(value):
    return value is None or str(value).strip().casefold() in ('', 'none', 'nan', 'null', 'unknown', '<na>')


def redact(text, names=()):
    text = re.sub(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[redacted-email]', text or '')
    for name in sorted({n for n in names if isinstance(n, str) and n}, key=len, reverse=True):
        if name and len(name) >= 3:
            text = re.sub(re.escape(name), '[redacted-identity]', text, flags=re.IGNORECASE)
    return text


class Source:
    def __init__(self, config, root):
        import duckdb
        self.config, self.root = config, Path(root)
        self.base = duckdb.connect(str(self.root / config['canonical_db']), read_only=True)
        self.overlay = None
        try:
            self.overlay = duckdb.connect(str(self.root / config['history_db']), read_only=True)
            self.base.execute("SET memory_limit='512MB'")
            columns = {r[0] for r in self.base.execute('DESCRIBE bugs').fetchall()}
            optional = [c for c in ('severity', 'priority') if c in columns]
            self.available_fields = [key for key,col in FIELD_COLUMNS.items() if col in columns]
            selected = ['b.bug_id', 'b.summary', 'b.product', 'b.component', 'b.snapshot_status',
                        'b.snapshot_resolution', 'b.opened_at_utc', 'b.source_record_id', 'b.content_hash',
                        'b.source_url', 'b.snapshot_assignee'] + ['b.' + c for c in optional]
            cursor = self.base.execute('SELECT ' + ','.join(selected) + ''' FROM bugs b JOIN sample_membership m USING(bug_id)
                WHERE m.seed=? AND b.product='Firefox' ORDER BY b.bug_id''', [config['seed']])
            names = [c[0] for c in cursor.description]
            self.bugs = {}
            for row in cursor.fetchall():
                item = dict(zip(names, row)); key = bug_id(item['bug_id'])
                if not key or key in self.bugs: raise RuntimeError('Invalid or duplicate canonical cohort ID')
                self.bugs[key] = item
            if len(self.bugs) != config['expected_cohort_size']:
                raise RuntimeError('Canonical cohort size differs from the configured verified sample')
            conflicts = self.base.execute("""SELECT DISTINCT bug_id FROM source_records
                WHERE source_dataset='metadata' AND disposition='CONFLICT_VARIANT'""").fetchall()
            self.conflicts = {bug_id(r[0]) for r in conflicts}
            ids = sorted(self.bugs)
            self.edges = [dict(zip(('root', 'relation', 'target', 'record_id', 'hash'), row))
                for row in self.base.execute("""SELECT bug_id,relation,target_bug_id,link_key,content_hash FROM bug_links
                WHERE bug_id IN (SELECT unnest(?)) ORDER BY bug_id,relation,target_bug_id,link_key""", [ids]).fetchall()]
            for edge in self.edges:
                edge['root'], edge['target'] = bug_id(edge['root']), bug_id(edge['target'])
            self.comments = {}
            # Only public and available bodies enter memory. Windowing bounds the
            # returned data to one comment per cohort bug, in deterministic time order.
            for row in self.base.execute("""SELECT bug_id,comment_key,substr(body,1,?),content_hash FROM (
                SELECT bug_id,comment_key,body,content_hash,
                 row_number() OVER (PARTITION BY bug_id ORDER BY event_time_utc NULLS LAST,comment_key) AS n
                FROM comments WHERE bug_id IN (SELECT unnest(?)) AND private_flag=false
                 AND text_availability='AVAILABLE' AND body IS NOT NULL) WHERE n=1""", [config['comment_character_limit'], ids]).fetchall():
                self.comments[bug_id(row[0])] = {'record_id': row[1], 'body': row[2], 'hash': row[3]}
            checkpoint = self.root / config['history_checkpoint']
            self.history = json.loads(checkpoint.read_text())['candidate_results']
            self.record_index, self.records_by_bug = {}, defaultdict(list)
            for record in read_jsonl(self.root / config['corpus']):
                if record.get('visibility') != 'public':
                    raise RuntimeError('Corpus contains private/unknown visibility; refuse all processing')
                rid = record['record_id']
                small = {k: record.get(k) for k in ('record_id', 'chunk_id', 'source_hash', 'bug_id', 'kind', 'url')}
                if rid in self.record_index and self.record_index[rid]['source_hash'] != small['source_hash']:
                    raise RuntimeError('Conflicting source hashes in corpus')
                self.record_index.setdefault(rid, small)
                self.records_by_bug[str(record['bug_id'])].append(small)
        except Exception:
            self.close()
            raise

    def close(self):
        self.base.close()
        if self.overlay is not None: self.overlay.close()

    def field(self, bug, field):
        return self.bugs[bug].get(FIELD_COLUMNS[field])

    def metadata_evidence(self, bug):
        return self.bugs[bug]['source_record_id']

    def history_verified(self, bug):
        info = self.history.get(str(bug))
        if not info: return False
        qc = info.get('history', {})
        return (qc.get('state') == 'PARSED' and qc.get('error') is None
                and qc.get('malformed_count') == 0 and qc.get('future_event_after_observed_at') is False
                and qc.get('chronology_ok') is True)

    def f2(self, bug):
        """Independently subtract explicit SQL event time from canonical creation."""
        info = self.history.get(str(bug), {})
        qc = info.get('history', {})
        if not self.history_verified(bug) or info.get('source_consistency_differences') or qc.get('same_time_groups'):
            return None
        rows = self.overlay.execute("""SELECT event_time_utc,source_row_key,content_sha256 FROM field_changes
             WHERE CAST(bug_id AS VARCHAR)=? AND history_state='PARSED' AND field_name='resolution'
              AND new_value=? AND old_value<>? ORDER BY event_time_utc,event_index,change_index""",
             [str(bug), '"FIXED"', '"FIXED"']).fetchall()
        if not rows: return None
        created = self.bugs[bug]['opened_at_utc']
        created = parse_utc(str(created)) if created is not None else None
        when = parse_utc(str(rows[0][0]))
        if created is None or when is None or when < created: return None
        seconds = (when-created).total_seconds()
        metric = info.get('fix_metric', {})
        if metric.get('state') != 'VALID_EVENT_TIME' or abs(metric.get('elapsed_calendar_days', -1)*86400-seconds) > 1:
            return None
        return {'seconds': seconds, 'record_id': rows[0][1], 'hash': rows[0][2]}

    def independent_field(self, bug, field):
        column = FIELD_COLUMNS.get(field)
        if field not in self.available_fields: return None
        row = self.base.execute('SELECT ' + column + ' FROM bugs WHERE bug_id=?', [bug]).fetchone()
        return row[0] if row else None

    def independent_targets(self, bug, relation):
        return sorted({bug_id(r[0]) for r in self.base.execute(
            'SELECT DISTINCT target_bug_id FROM bug_links WHERE bug_id=? AND relation=? AND target_bug_id IS NOT NULL',
            [bug, relation]).fetchall() if bug_id(r[0])}, key=int)

    def source_hashes(self, ids):
        if any(rid not in self.record_index for rid in ids): raise ValueError('Evidence not indexed')
        return {rid: self.record_index[rid]['source_hash'] for rid in ids}

    def sql_absent(self, bug):
        return self.base.execute('SELECT count(*) FROM bugs WHERE bug_id=?', [bug]).fetchone()[0] == 0

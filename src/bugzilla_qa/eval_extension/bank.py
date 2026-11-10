"""Create a separate, deterministic draft factual bank from sampled canonical records."""
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from bugzilla_qa.data.normalize import digest
from bugzilla_qa.eval_extension.cli import ROOT, file_hash, verify_source_manifests
from bugzilla_qa.eval_extension.contracts import validate

VERSION = 'expanded-bank-v1'


def partition(seed, bug):
    return 'dev' if int(digest([seed, str(bug)])[:12], 16) % 5 == 0 else 'test'


def ordered(seed, value):
    return digest([seed, value])


def make_item(family, text, gold, bug, evidence, seed, extra=None):
    scope = {'corpus': 'broad BugsRepo metadata; sampled Firefox-product bugs', 'sample_seed': seed,
             'snapshot_as_of_utc': None, 'partition': partition(seed, bug)}
    if extra:
        scope.update(extra)
    cluster = 'bug:' + str(bug)
    item = {'family': family, 'question': text, 'gold': gold, 'bug_ids': [str(bug)],
            'evidence': evidence, 'scope': scope, 'split': scope['partition'], 'cluster_id': cluster,
            'seed': seed, 'version': VERSION, 'human_review_state': 'NOT_HUMAN_REVIEWED'}
    item['qid'] = 'ex_' + digest([VERSION, seed, family, text, scope])[:20]
    return item


def build_bank(config, limit=None, target=3000, evaluated=750):
    import duckdb
    from tqdm import tqdm
    from bugzilla_qa.data import phase04 as p4
    verify_source_manifests(config)
    seed = config['sample_seed']
    db = duckdb.connect(str(ROOT / config['canonical_db']), read_only=True)
    api = duckdb.connect(str(ROOT / config['history_db']), read_only=True)
    db.execute("SET memory_limit='512MB'")
    try:
        sql = '''SELECT b.bug_id,b.product,b.component,b.snapshot_status,b.snapshot_resolution,
                  year(b.opened_at_utc),b.source_record_id,b.source_url,b.content_hash,s.normalized_fields
                  FROM bugs b JOIN sample_membership m USING(bug_id)
                  JOIN source_records s USING(source_record_id) WHERE m.seed=?
                  AND NOT EXISTS (SELECT 1 FROM source_records v WHERE v.bug_id=b.bug_id
                        AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT')
                  ORDER BY b.bug_id'''
        params = [seed]
        if limit is not None:
            sql += ' LIMIT ?'; params.append(limit)
        bugs = {}
        for row in db.execute(sql, params).fetchall():
            bug, product, component, status, resolution, year, rid, url, sha, raw = row
            original = json.loads(raw)
            if digest(original) != sha or any(str(original[k]) != str(v) for k,v in
                   [('product',product),('component',component),('snapshot_status',status),('snapshot_resolution',resolution)]):
                continue
            bugs[bug] = {'product': product, 'component': component, 'status': status,
                         'resolution': resolution, 'year': year, 'record_id': rid, 'url': url,
                         'source_hash': sha, 'normalized': original}
        buckets = defaultdict(list)
        for bug in tqdm(sorted(bugs), desc='Generate source-backed candidates', unit='bug'):
            row = bugs[bug]
            ev = [{'id': row['record_id'], 'bug_id': bug, 'source_url': row['url'], 'content_hash': row['source_hash']}]
            for field in ('product','component','status','resolution'):
                value = row[field]
                if value is None or str(value).upper() in ('UNKNOWN', ''):
                    continue
                text = 'In the broad metadata archive for Firefox bug %s (snapshot date unknown), what is its recorded %s?' % (bug, field)
                item = make_item('F1', text, {'type': 'string', 'value': value}, bug, ev, seed)
                item['validator'] = 'normalized source field equals canonical field and source hash'
                buckets['F1', str(row['year']), str(row['component']), str(row['status']), str(row['resolution'])].append(item)
            # Restrict F6 to schema, not potentially contradictory comment evidence.
            text = ('How many engineer work hours did Firefox bug %s require, using only its recorded product, '
                    'component, status, resolution and filing time?' % bug)
            item = make_item('F6', text, {'type': 'unanswerable', 'value': 'cannot be established from the specified evidence'}, bug, ev, seed,
                             {'evidence_scope': 'product, component, status, resolution and filing time only'})
            item['validator'] = 'explicit five-field scope contains no engineer-hours field'
            buckets['F6', str(row['status'])].append(item)
        # Counts use disjoint partition membership and two independent implementations.
        for sp in ('dev', 'test'):
            universe = sorted(b for b in bugs if partition(seed, b) == sp)
            groups = defaultdict(set)
            for bug in universe:
                row = bugs[bug]
                for field in ('component', 'status', 'resolution', 'year'):
                    if row[field] is not None:
                        groups[field, str(row[field])].add(bug)
            for (field, value), ids in groups.items():
                if not ids or len(ids) == len(universe):
                    continue
                col = {'component':'component', 'status':'snapshot_status', 'resolution':'snapshot_resolution', 'year':'year(opened_at_utc)'}[field]
                result = db.execute('SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND ' + col + '=?',
                                    [universe, int(value) if field == 'year' else value]).fetchone()[0]
                if result != len(ids):
                    raise ValueError('F3 independent SQL/set mismatch')
                first = sorted(ids)[0]; row = bugs[first]
                text = ('Within the seed %d Firefox sample %s partition (%d distinct non-conflicted bugs), '
                        'how many distinct bugs have recorded %s %s? Filing year is not a status-change date; snapshot date is unknown.'
                        % (seed, sp, len(universe), field, value))
                ev = [{'id':'population:' + digest(universe), 'bug_id':first, 'source_url':row['url'],
                       'content_hash':row['source_hash']}]
                item = make_item('F3', text, {'type':'integer','value':result}, first, ev, seed,
                                 {'denominator':len(universe),'filter':{field:value},'population_hash':digest(universe)})
                item['cluster_id'] = 'aggregate:%s:%s:%s' % (sp, field, value)
                item['validator'] = 'SQL COUNT(DISTINCT bug_id) equals independent Python set'
                buckets['F3', sp, field].append(item)
        if bugs:
            ids = sorted(bugs)
            edges = db.execute('''SELECT bug_id,relation,target_bug_id,link_key,source_url,content_hash
                     FROM bug_links WHERE bug_id IN (SELECT unnest(?)) AND target_bug_id IS NOT NULL
                     ORDER BY bug_id,relation,target_bug_id,link_key''', [ids]).fetchall()
            groups = defaultdict(list)
            for bug, relation, target_id, key, url, sha in edges:
                groups[bug, relation].append((str(target_id), key, url, sha))
            for (bug, relation), entries in groups.items():
                targets = sorted({x[0] for x in entries}, key=int)
                if any(partition(seed, target_id) != partition(seed, bug) for target_id in targets):
                    continue
                raw_targets = {str(e['target_bug_id']) for e in bugs[bug]['normalized']['recorded_links']
                               if e['relation'] == relation and e.get('target_bug_id')}
                if raw_targets != set(targets):
                    continue
                independent = {str(x[0]) for x in db.execute('SELECT DISTINCT target_bug_id FROM bug_links WHERE bug_id=? AND relation=? AND target_bug_id IS NOT NULL',[bug,relation]).fetchall()}
                if independent != set(targets):
                    raise ValueError('F4 target set mismatch')
                ev = [{'id':k,'bug_id':bug,'source_url':u,'content_hash':h} for _,k,u,h in entries]
                text = 'Which target bug IDs are explicitly recorded for relation %s from Firefox bug %s in the archive? Historical validity is unknown.' % (relation,bug)
                item = make_item('F4',text,{'type':'id_set','value':targets},bug,ev,seed)
                item['validator'] = 'canonical SQL set equals Python set and retained source links'
                buckets['F4', str(relation), str(len(targets))].append(item)
        checkpoint = json.loads((ROOT / config['history_db']).parent.joinpath('checkpoint.json').read_text())
        for bug, saved in checkpoint['candidate_results'].items():
            if bug not in bugs or saved.get('source_consistency_differences') or saved['history'].get('same_time_groups'):
                continue
            metric = saved.get('fix_metric', {})
            if metric.get('state') != 'VALID_EVENT_TIME':
                continue
            evs = [e for e in saved['changes'] if e['field_name'] == 'resolution' and e['new_value'] == p4.canonical('FIXED') and e['old_value'] != p4.canonical('FIXED')]
            if not evs:
                continue
            first = min(evs, key=lambda e: p4.parse_utc(e['event_time_utc']))
            stored = api.execute('SELECT source_row_key,source_url,content_sha256,event_time_utc FROM field_changes WHERE bug_id=? AND event_index=? AND change_index=?', [int(bug),first['event_index'],first['change_index']]).fetchone()
            if not stored or stored[2] != p4.digest(first):
                continue
            opened = bugs[bug]['normalized'].get('opened_at_utc')
            # The verified Phase 4 metric is independently checked against canonical creation.
            created = db.execute('SELECT opened_at_utc FROM bugs WHERE bug_id=?',[bug]).fetchone()[0]
            first_dt = p4.parse_utc(stored[3])
            if created is None or first_dt is None:
                continue
            seconds = (first_dt - created).total_seconds()
            if seconds < 0 or abs(seconds / 86400 - metric['elapsed_calendar_days']) > 1e-8:
                continue
            ev = [{'id':bugs[bug]['record_id'],'bug_id':bug,'source_url':bugs[bug]['url'],'content_hash':bugs[bug]['source_hash']},
                  {'id':stored[0],'bug_id':bug,'source_url':stored[1],'content_hash':stored[2]}]
            text = 'Using the verified API history and filing time for Firefox bug %s, how many calendar hours elapsed before its first recorded FIXED transition?' % bug
            item = make_item('F2',text,{'type':'calendar_duration','seconds':seconds,'hours':seconds/3600,'days':seconds/86400,'first_fixed_at_utc':first_dt.isoformat(),'tolerance_seconds':1},bug,ev,seed)
            item['validator'] = 'verified event hash and independent UTC subtraction agree with pilot metric'
            buckets['F2',str(bugs[bug]['status'])].append(item)
        for items in buckets.values():
            items.sort(key=lambda x: ordered(seed, x['qid']))
        # Round-robin across observed strata: no artificial equal family quota.
        all_items = []
        keys = sorted(buckets, key=lambda x: ordered(seed, x))
        while keys and len(all_items) < target:
            remaining = []
            for key in keys:
                if len(all_items) >= target: break
                all_items.append(buckets[key].pop())
                if buckets[key]: remaining.append(key)
            keys = remaining
        if len({q['qid'] for q in all_items}) != len(all_items):
            raise ValueError('duplicate question IDs')
        for item in all_items:
            validate('Question',item); validate('Gold',item)
        grouped = defaultdict(list)
        for item in all_items:
            grouped[item['family'], item['split']].append(item)
        for values in grouped.values():
            values.sort(key=lambda q: ordered(seed + 1, q['qid']))
        selected = []
        active = sorted(grouped)
        while active and len(selected) < min(evaluated, len(all_items)):
            following = []
            for key in active:
                if len(selected) >= evaluated: break
                selected.append(grouped[key].pop())
                if grouped[key]: following.append(key)
            active = following
        return all_items, selected, {'eligible_sample_bugs':len(bugs), 'candidate_count':len(all_items),
               'evaluated_selected':len(selected), 'families':dict(Counter(q['family'] for q in all_items)),
               'selected_families':dict(Counter(q['family'] for q in selected)),
               'splits':dict(Counter(q['split'] for q in all_items)), 'target':target,
               'f2_source': 'selective verified API history only', 'f5': 'separate human-reviewed benchmark only',
               'snapshot_as_of_utc':None,'state':'DRAFT_NOT_FROZEN'}
    finally:
        db.close(); api.close()

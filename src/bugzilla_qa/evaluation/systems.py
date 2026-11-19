"""Score saved S-system answers and export separate human evidence reviews."""
import csv
import hashlib
import itertools
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from .scoring import DURATION_TOLERANCE_HOURS, score as legacy_score

VERSION = 's-evaluation-v1'
SYSTEMS = ['S' + str(i) for i in range(9)]


def read(path):
    text = Path(path).read_text(encoding='utf-8')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import yaml
        return yaml.safe_load(text)


def rows(path):
    with Path(path).open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def write_csv(path, values, fields):
    with Path(path).open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def unique(values):
    result = {value['qid']: value for value in values}
    if len(result) != len(values):
        raise ValueError('Duplicate question IDs')
    return result


def load_items(root, config, dataset, split='dev', confirm=False):
    if split == 'test' and not confirm:
        raise ValueError('Test requires --confirm-locked-test after finalizing methods and scoring')
    root = Path(root)
    pins = {}
    dataset_notes = {}
    if dataset == 'sample':
        if split != 'dev':
            raise ValueError('The source sample is development only')
        directory = root / config['sample_dir']
        manifest_path = directory / 'manifest.json'
        manifest = read(manifest_path)
        dataset_notes = manifest.get('sample_limitations', {})
        if manifest.get('state') != 'SOURCE_VERIFIED_DEV_SAMPLE':
            raise ValueError('Sample is not independently source verified')
        for name in ['questions.jsonl', 'gold.jsonl']:
            path = directory / name
            if file_hash(path) != manifest['sha256'][name]:
                raise ValueError('Sample checksum mismatch')
            pins[str(path)] = file_hash(path)
        questions = rows(directory / 'questions.jsonl')
        gold = unique(rows(directory / 'gold.jsonl'))
        freeze = manifest['sample_id']
        pins[str(manifest_path)] = file_hash(manifest_path)
    elif dataset == 'natural':
        path = root / config['natural_questions']
        manifest_path = root / config['natural_manifest']
        manifest = read(manifest_path)
        if file_hash(path) != manifest['sha256']:
            raise ValueError('Natural question checksum mismatch')
        all_questions = rows(path)
        unique(all_questions)
        questions = [q for q in all_questions if q['split'] == split]
        if any(q.get('human_review_state') != 'HUMAN_APPROVED_WORDING' for q in questions):
            raise ValueError('Natural wording is not approved')
        gold = unique(questions)
        freeze = manifest['sha256']
        pins = {str(path): file_hash(path), str(manifest_path): file_hash(manifest_path)}
    else:
        directory = root / config[dataset + '_dir']
        manifest_path = directory / 'manifest.json'
        manifest = read(manifest_path)
        freeze = manifest.get('freeze_id', manifest.get('id'))
        if freeze != config[dataset + '_freeze_id'] or manifest.get('status', manifest.get('state')) not in (
                'FROZEN_HUMAN_SIGNED', 'FROZEN_HUMAN_SPOTCHECKED'):
            raise ValueError('Wrong or unfrozen benchmark')
        loaded = []
        for suffix in ['questions', 'gold']:
            name = split + '.' + suffix + '.jsonl'
            path = directory / name
            if file_hash(path) != manifest['sha256'][name]:
                raise ValueError('Frozen checksum mismatch: ' + name)
            pins[str(path)] = file_hash(path)
            loaded.append(rows(path))
        questions, gold_rows = loaded
        gold = unique(gold_rows)
        pins[str(manifest_path)] = file_hash(manifest_path)
    if set(unique(questions)) != set(gold) or not questions:
        raise ValueError('Question and gold rosters differ or are empty')
    result = []
    for q in questions:
        g = gold[q['qid']]
        typed = g.get('gold')
        kind = typed['type'] if typed else q['answer_type']
        if q.get('answer_type') in ('bug_id', 'structured'):
            kind = q['answer_type']
        expected = typed if typed and kind == 'supported_explanation' else typed.get('value', typed.get('hours')) if typed else g['answer']
        bug_ids = g.get('acceptable_bug_ids', g.get('bug_ids', []))
        family = q.get('family', g.get('family'))
        cluster = q.get('cluster_id') or g.get('cluster_id') or q.get('parent_qid') or q.get('provenance', {}).get('root_bug_id')
        cluster = cluster or ('bug:' + str(bug_ids[0]) if bug_ids and family != 'F3' else 'aggregate:' + split)
        if q.get('split', split) != split or g.get('split', split) != split:
            raise ValueError('Question/gold split mismatch')
        result.append(dict(qid=q['qid'], question=q['question'], family=family, dataset=dataset,
                           split=split, freeze_id=freeze, cluster_id=str(cluster).removeprefix('bug:'),
                           kind=kind, expected=expected, acceptable_bug_ids=[str(x) for x in bug_ids],
                           evidence=g.get('evidence', g.get('evidence_record_ids', [])),
                           scope=q.get('scope', g.get('scope', q.get('provenance', {}))),
                           dataset_notes=dataset_notes,
                           tolerance_hours=DURATION_TOLERANCE_HOURS))
    return sorted(result, key=lambda q: q['qid']), pins


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError, OverflowError):
        return None


def id_set(value):
    if not isinstance(value, list) or any(isinstance(x, bool) or not str(x).isdigit() for x in value):
        return None
    return {str(int(x)) for x in value}


def grade(item, prediction):
    result = dict(qid=item['qid'], dataset=item['dataset'], family=item['family'],
                  cluster_id=item['cluster_id'], verdict='INCORRECT', reason='missing_prediction', attempted=False, resolved=False)
    if item['kind'] == 'id_set':
        result.update(precision=0.0, recall=0.0, f1=0.0)
    if prediction is None:
        return result
    result.update(attempted=True, resolved=prediction.get('status')=='ok' or bool(prediction.get('terminal_error')))
    if prediction.get('status') != 'ok':
        return dict(result, reason='execution_failure')
    answer = prediction.get('answer', {})
    if not isinstance(answer, dict):
        return dict(result, reason='invalid_answer_contract')
    value = answer.get('answer')
    if type(answer.get('abstain')) is not bool or answer['abstain'] != (value is None) or isinstance(value, (bool, dict)):
        return dict(result, reason='invalid_answer_contract')
    supplied = set(prediction.get('context_chunk_ids', []))
    citations = answer.get('citations', [])
    if not isinstance(citations, list) or any(not isinstance(x, str) or x not in supplied for x in citations):
        return dict(result, reason='invalid_citation_id')
    kind, expected = item['kind'], item['expected']
    if item['family'] == 'F5':
        return dict(result, verdict='NEEDS_HUMAN', reason='explanation_review')
    if kind in ('unknown', 'unanswerable', 'abstain'):
        return dict(result, verdict='CORRECT' if answer['abstain'] else 'INCORRECT',
                    reason='correct_abstention' if answer['abstain'] else 'answered_unanswerable')
    if answer['abstain']:
        return dict(result, reason='false_abstention')
    metrics = {}
    if kind in ('string', 'integer', 'calendar_duration', 'calendar_hours', 'id_set'):
        legacy_kind = 'calendar_duration' if kind == 'calendar_hours' else kind
        legacy_gold = dict(type=legacy_kind, value=expected)
        if kind == 'string' and not isinstance(value, str):
            return dict(result, reason='invalid_field_value')
        if kind == 'id_set' and id_set(value) is None:
            return dict(result, reason='invalid_id_set', precision=0.0, recall=0.0, f1=0.0)
        if legacy_kind == 'calendar_duration':
            value = number(value)
            unit = answer.get('answer_type', '').casefold()
            if unit in ('days', 'calendar_days') and value is not None:
                value *= 24
            elif unit not in ('hours', 'calendar_hours', 'calendar_duration'):
                return dict(result, verdict='NEEDS_HUMAN', reason='ambiguous_duration_unit')
            legacy_gold.update(hours=expected, tolerance_seconds=0)
            metrics['absolute_error_hours'] = abs(value - expected) if value is not None else None
        if kind == 'integer':
            parsed = number(value)
            metrics['absolute_error'] = abs(parsed - expected) if parsed is not None else None
        marked = legacy_score(dict(qid=item['qid'], family=item['family'], gold=legacy_gold),
                              dict(qid=item['qid'], method=prediction['system_id'], status='OK', abstained=False, value=value))
        correct = marked['verdict'] == 'CORRECT'
        metrics.update({k: marked[k] for k in ('precision', 'recall', 'f1', 'exact') if k in marked})
        if kind == 'id_set' and not value and not expected:
            metrics.update(precision=1.0, recall=1.0, f1=1.0)
    elif kind == 'bug_id':
        got = {str(value)} if not isinstance(value, bool) and str(value).isdigit() else id_set(value)
        declared = id_set(answer.get('bug_ids', []))
        identified = got if got is not None else declared if isinstance(value, str) else None
        correct = bool(identified) and len(identified) == 1 and identified <= set(item['acceptable_bug_ids'])
        correct = correct and declared is not None and (not got or not declared or got == declared)
    elif kind == 'structured':
        try:
            got = json.loads(value) if isinstance(value, str) else value
            correct = isinstance(got, dict) and set(got) == set(expected) and all(
                id_set(got[k]) is not None and id_set(got[k]) == id_set(expected[k]) for k in expected)
            metrics['parts_correct'] = sum(isinstance(got, dict) and id_set(got.get(k)) is not None
                                          and id_set(got[k]) == id_set(expected[k]) for k in expected)
            metrics['parts_total'] = len(expected)
        except (ValueError, TypeError):
            correct = False
    else:
        raise ValueError('Unsupported gold type: ' + kind)
    if item['family'] == 'KI' and kind != 'bug_id':
        ids = id_set(answer.get('bug_ids'))
        correct = correct and bool(ids) and ids <= set(item['acceptable_bug_ids'])
    return dict(result, verdict='CORRECT' if correct else 'INCORRECT', reason=kind, **metrics)


def select_predictions(directory, items, systems):
    directory = Path(directory)
    manifest = read(directory / 'manifest.json')
    config_hash = manifest['config_hash']
    by_id = unique(items)
    if items[0]['split'] == 'test':
        receipt_path = directory / 'LOCKED_TEST_ACCESS.json'
        receipt = read(receipt_path)
        if not receipt.get('confirmed') or receipt.get('freeze_id') != items[0]['freeze_id'] or file_hash(receipt_path) != manifest['sha256'][receipt_path.name]:
            raise ValueError('Missing or invalid test access receipt')
    selected, attempts, pins, identities = {}, {}, {}, set()
    for system in systems:
        path = directory / (system + '.jsonl')
        values = rows(path) if path.exists() else []
        if path.exists():
            if file_hash(path) != manifest['sha256'][path.name]:
                raise ValueError('Prediction checksum mismatch: ' + str(path))
            pins[str(path)] = file_hash(path)
        grouped = defaultdict(list)
        for row in values:
            q = by_id.get(row['qid'])
            if q is None:
                raise ValueError('Prediction question absent from this benchmark')
            if any(row.get(k) != q[k] for k in ('dataset', 'split', 'family', 'freeze_id')):
                raise ValueError('Prediction dataset identity mismatch')
            if row.get('config_hash') != config_hash or row.get('system_id') != system:
                raise ValueError('Mixed prediction configuration/system')
            identities.add(tuple(row.get(k) for k in ('model', 'provider', 'prompt_version')))
            grouped[row['qid']].append(row)
        selected[system], attempts[system] = {}, values
        for qid, candidates in grouped.items():
            successful = [r for r in candidates if r['status'] == 'ok']
            if len(successful) > 1:
                raise ValueError('Duplicate successful answers in prediction ledger')
            terminal=[r for r in candidates if r['status']=='ok' or r.get('terminal_error')]
            if len(terminal)>1:
                raise ValueError('Multiple terminal attempts; a method failure cannot be replaced by a later success')
            selected[system][qid] = terminal[0] if terminal else candidates[-1]
    if len(identities) > 1 or any(not all(identity) for identity in identities):
        raise ValueError('Model/provider/prompt differ within comparison')
    pins[str(directory / 'manifest.json')] = file_hash(directory / 'manifest.json')
    return selected, attempts, pins


def bootstrap(groups, rounds=10000):
    values = list(groups.values())
    if len(values) < 2:
        return None
    rng = random.Random(317)
    samples = []
    for _ in range(rounds):
        picked = [x for group in rng.choices(values, k=len(values)) for x in group]
        samples.append(sum(picked) / len(picked))
    samples.sort()
    return [samples[int(rounds * .025)], samples[int(rounds * .975) - 1]]


def summarize(scores):
    table = []
    grouped = defaultdict(list)
    for row in scores:
        grouped[row['system_id'], row['family']].append(row)
    for (system, family), values in sorted(grouped.items()):
        counts = Counter(r['verdict'] for r in values)
        clusters = defaultdict(list)
        for row in values:
            clusters[row['cluster_id']].append(int(row['verdict'] == 'CORRECT'))
        pending = counts['NEEDS_HUMAN']
        unresolved = sum(not r.get('resolved',True) for r in values)
        observed = [r for r in values if r.get('resolved',True) and r['verdict']!='NEEDS_HUMAN']
        means = {}
        for metric in ('absolute_error', 'absolute_error_hours', 'precision', 'recall', 'f1'):
            measured = [r[metric] for r in values if r.get(metric) is not None]
            if measured:
                means[metric] = dict(mean=sum(measured) / len(measured), n=len(measured))
        table.append(dict(system_id=system, family=family, n=len(values), correct=counts['CORRECT'],
                          incorrect=counts['INCORRECT'], needs_human=pending,
                          unresolved=unresolved,
                          accuracy=None if pending or unresolved else counts['CORRECT'] / len(values),
                          observed_n=len(observed),
                          observed_accuracy=sum(r['verdict']=='CORRECT' for r in observed)/len(observed) if observed else None,
                          provisional_lower_bound=counts['CORRECT'] / len(values),
                          cluster_bootstrap_95=None if pending or unresolved else bootstrap(clusters),
                          clusters=len(clusters), metrics=means, reasons=dict(Counter(r['reason'] for r in values))))
    return table


def paired(scores, systems):
    output = []
    for a, b in itertools.combinations([s for s in systems if s != 'ORACLE'], 2):
        for family in sorted({r['family'] for r in scores}):
            left = {r['qid']: r for r in scores if r['system_id'] == a and r['family'] == family}
            right = {r['qid']: r for r in scores if r['system_id'] == b and r['family'] == family}
            if left.keys() != right.keys():
                continue
            eligible = [qid for qid in left if all(r.get('resolved',True) and r['verdict']!='NEEDS_HUMAN' for r in [left[qid],right[qid]])]
            provisional = len(eligible) != len(left)
            clusters = defaultdict(list)
            gaps = []
            for qid in eligible:
                row=left[qid]
                gap = int(row['verdict'] == 'CORRECT') - int(right[qid]['verdict'] == 'CORRECT')
                clusters[row['cluster_id']].append(gap)
                gaps.append(gap)
            if gaps:
                sums = [sum(group) for group in clusters.values()]
                rng = random.Random(317)
                if len(sums) < 10 or provisional:
                    probability = None
                elif len(sums) <= 12:
                    trials = [abs(sum(v * sign for v, sign in zip(sums, signs))) for signs in itertools.product((-1, 1), repeat=len(sums))]
                    probability = sum(v >= abs(sum(gaps)) for v in trials) / len(trials)
                else:
                    extreme = sum(abs(sum(v * rng.choice((-1, 1)) for v in sums)) >= abs(sum(gaps)) for _ in range(10000))
                    probability = (extreme + 1) / 10001
                output.append(dict(a=a, b=b, family=family, n=len(gaps), clusters=len(clusters),
                                   expected_n=len(left), excluded_n=len(left)-len(gaps), provisional=provisional,
                                   difference=sum(gaps) / len(gaps), cluster_bootstrap_95=bootstrap(clusters),
                                   permutation_p=probability,
                                   interpretation='Matched resolved questions, including terminal failures; provisional comparisons make no significance claim; Holm covers complete method/family tests'))
    tested = sorted((r for r in output if r['permutation_p'] is not None), key=lambda r: r['permutation_p'])
    previous = 0.0
    for rank, row in enumerate(tested):
        previous = max(previous, min(1.0, row['permutation_p'] * (len(tested) - rank)))
        row['holm_p'] = previous
    return output


def visible_evidence(prediction, config, documents):
    budget = config.get('context_tokens', 3000)
    if prediction.get('route') == 'S7':
        used, visible = 0, []
        for entry in reversed(prediction.get('tools', [])):
            text = json.dumps(entry, sort_keys=True)
            if used + len(text.encode()) > budget:
                text = json.dumps({'name':entry['name'],'result':'Withheld from prompt: result exceeds remaining context budget; narrow the tool request.'})
                result = None
            else:
                result = entry.get('result')
            if used + len(text.encode()) + 1 > budget:
                break
            used += len(text.encode()) + 1
            if isinstance(result, dict):
                result = {k:v for k,v in result.items() if k not in ('sql_template','parameters','cache_hit')}
            if result is not None:
                visible.insert(0,dict(request=entry.get('arguments',{}),result=result))
        return json.dumps(visible, sort_keys=True)
    identifiers = prediction.get('context_chunk_ids', [])
    if not identifiers:
        return ''
    if any(i not in documents for i in identifiers):
        return 'Source text unavailable locally; resolve the recorded context IDs before grounding review.'
    from bugzilla_qa.answering.contracts import pack
    budget = config.get('dossier_tokens', 12000) if prediction.get('route') == 'S5' else budget
    context, _ = pack([documents[i] for i in identifiers], budget)
    return context


def evaluate(items, selected, attempts, output, systems, pins, sample=False, reviews=None, context_config=None, documents=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    review_path = Path(reviews) if reviews else output / 'review_queue.csv'
    review_input_hash = file_hash(review_path) if review_path.exists() else None
    saved_reviews = {}
    if review_path.exists():
        with review_path.open(newline='', encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                if row['review_id'] in saved_reviews:
                    raise ValueError('Duplicate human review ID')
                saved_reviews[row['review_id']] = row
    scores, queue, key, reliability = [], [], [], []
    for system in systems:
        candidates = defaultdict(list)
        for item in items:
            prediction = selected[system].get(item['qid'])
            result = dict(grade(item, prediction), system_id=system)
            if prediction and prediction['status'] == 'ok':
                review_id = digest([VERSION, item, system,
                                    prediction['config_hash'], prediction['answer'], prediction.get('context_chunk_ids')])[:24]
                result['review_id'] = review_id
                candidates[item['family']].append((review_id, item, prediction, result))
                review = saved_reviews.get(review_id, {})
                verdict = review.get('answer_verdict', '').strip().upper()
                if verdict and verdict not in ('CORRECT', 'INCORRECT'):
                    raise ValueError('Human answer verdict must be CORRECT or INCORRECT')
                if result['verdict'] == 'NEEDS_HUMAN' and verdict:
                    if not review.get('reviewer', '').strip() or not review.get('note', '').strip():
                        raise ValueError('Human decisions require reviewer and source-check note')
                    result.update(verdict=verdict, reason='human_review')
            scores.append(result)
        for family, values in candidates.items():
            chosen = [v for index, v in enumerate(sorted(values)) if index < 2 or v[3]['verdict'] == 'NEEDS_HUMAN' or v[0] in saved_reviews] if family != 'F5' else sorted(values)
            for review_id, item, prediction, result in chosen:
                prior = saved_reviews.get(review_id, {})
                grounding = prior.get('grounding_verdict', '').strip().upper()
                if grounding not in ('', 'SUPPORTED', 'UNSUPPORTED', 'UNCLEAR', 'NOT_APPLICABLE'):
                    raise ValueError('Invalid grounding verdict')
                if grounding and (not prior.get('reviewer', '').strip() or not prior.get('note', '').strip()):
                    raise ValueError('Grounding decisions require reviewer and source-check note')
                queue.append(dict(review_id=review_id, question=item['question'], family=family,
                                  scope=json.dumps(item['scope'], sort_keys=True),
                                  answer=json.dumps(prediction['answer'], sort_keys=True),
                                  reference=json.dumps(item['expected'], sort_keys=True),
                                  evidence=json.dumps(item['evidence'], sort_keys=True),
                                  context_chunk_ids=json.dumps(prediction.get('context_chunk_ids', [])),
                                  provided_evidence=visible_evidence(prediction,context_config or {},documents or {}),
                                  answer_verdict=prior.get('answer_verdict', ''), grounding_verdict=grounding,
                                  reviewer=prior.get('reviewer', ''), note=prior.get('note', '')))
                key.append(dict(review_id=review_id, system_id=system, qid=item['qid']))
        events = attempts[system]
        usage = Counter()
        for event in events:
            usage.update({k: v for k, v in event.get('tokens', {}).items() if k != 'usage_missing' and isinstance(v, (float, int))})
        latencies = sorted(r['latency_ms'] for r in events if isinstance(r.get('latency_ms'), (int, float)) and not r.get('llm_cache_hit'))
        reliability.append(dict(system_id=system, attempts=len(events),
                                failed_attempts=sum(r['status'] != 'ok' for r in events),
                                repair_attempts=sum(r.get('repair_count',0) for r in events),
                                successful_after_repair=sum(r['status']=='ok' and r.get('repair_count',0)>0 for r in events),
                                missing_questions=sum(q['qid'] not in selected[system] for q in items),
                                selected_errors=sum(r['status'] != 'ok' for r in selected[system].values()),
                                unresolved_questions=sum(r['status'] != 'ok' and not r.get('terminal_error') for r in selected[system].values()),
                                http_attempts=sum(r.get('call_count', 0) for r in events), tokens=dict(usage),
                                usage_missing_events=sum(bool(r.get('tokens', {}).get('usage_missing', True)) for r in events),
                                uncached_latency_n=len(latencies),
                                uncached_latency_p50_ms=latencies[len(latencies)//2] if latencies else None,
                                uncached_latency_p95_ms=latencies[min(len(latencies)-1, int(len(latencies)*.95))] if latencies else None))
    table = summarize(scores)
    baseline = [dict(grade(q, dict(status='ok', system_id='ALWAYS_ABSTAIN',
                                  answer=dict(abstain=True, answer=None, citations=[]))), system_id='ALWAYS_ABSTAIN') for q in items]
    reviewed_grounding = Counter(r['grounding_verdict'] for r in queue if r['grounding_verdict'])
    common_families={family for family in {r['family'] for r in table}
                     if all(r['accuracy'] is not None for r in table if r['family']==family)}
    coverage_complete=not any(r['missing_questions'] or r['unresolved_questions'] for r in reliability)
    comparison = []
    for system, reliability_row in zip(systems, reliability):
        cells = [r for r in table if r['system_id'] == system]
        graded = [r for r in cells if r['family'] in common_families]
        comparison.append(dict(system_id=system, questions=len(items),
                               predictions=len(selected[system]),
                               correct=sum(r['correct'] for r in cells),
                               needs_human=sum(r['needs_human'] for r in cells),
                               macro_accuracy=sum(r['accuracy'] for r in graded)/len(graded) if graded and coverage_complete else None,
                               macro_families=','.join(r['family'] for r in graded),
                               missing=reliability_row['missing_questions'],
                               failed_predictions=reliability_row['selected_errors'],
                               http_attempts=reliability_row['http_attempts'],
                               correct_abstentions=sum(r['reason']=='correct_abstention' for r in scores if r['system_id']==system),
                               false_abstentions=sum(r['reason']=='false_abstention' for r in scores if r['system_id']==system),
                               answered_unanswerable=sum(r['reason']=='answered_unanswerable' for r in scores if r['system_id']==system)))
    state = 'PARTIAL' if any(r['missing_questions'] or r['unresolved_questions'] for r in reliability) else 'NEEDS_REVIEW' if any(r['needs_human'] for r in table) or any(not r['grounding_verdict'] for r in queue) else 'REVIEWED'
    summary = dict(state=state, simulated=sample, dataset=items[0]['dataset'], split=items[0]['split'],
                   runtime='reconstructed shared-source development runtime' if (context_config or {}).get('runtime_manifest') else 'declared prediction configuration',
                   questions=len(items), systems=systems, scoring_version=VERSION, table=table,
                   family_coverage={f:sum(q['family']==f for q in items) for f in ['F1','F2','F3','F4','F5','F6','KI','MH','F6H']},
                   dataset_notes=items[0].get('dataset_notes', {}),
                   reliability=reliability, comparison=comparison, paired=paired(scores, systems), always_abstain=summarize(baseline),
                   grounding_review=dict(sample_n=len(queue), decisions=dict(reviewed_grounding)),
                   limitations=['Grounding is human-reviewed on all F5 answers and up to two other answers per system/family.',
                                'No pooled score across overlapping datasets. Confidence intervals are unadjusted; Holm p-values are per dataset.',
                                'Synthetic scores are workflow checks, not model accuracy.' ] if sample else
                                ['Grounding review is sampled; unreviewed answers are not established as supported.',
                                 'No pooled score across overlapping datasets. Confidence intervals are unadjusted; Holm p-values are per dataset.'])
    write(output / 'summary.json', summary)
    (output / 'scores.jsonl').write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in scores), encoding='utf-8')
    write_csv(output / 'review_queue.csv', sorted(queue, key=lambda r: r['review_id']),
              ['review_id', 'question', 'family', 'scope', 'answer', 'reference', 'evidence', 'context_chunk_ids', 'provided_evidence', 'answer_verdict', 'grounding_verdict', 'reviewer', 'note'])
    write_csv(output / 'review_key.csv', key, ['review_id', 'system_id', 'qid'])
    write_csv(output / 'comparison.csv', comparison, list(comparison[0]))
    write(output / 'manifest.json', dict(scoring_version=VERSION, input_sha256=pins,
                                        scorer_sha256=file_hash(__file__), simulated=sample,
                                        review_input_sha256=review_input_hash))
    lines = ['# ' + ('Simulated evaluation' if sample else 'Development evaluation' if items[0]['split'] == 'dev' else 'Test evaluation'),
             '', 'State: ' + state,
             'Not in dataset: ' + (', '.join(f for f,n in summary['family_coverage'].items() if not n) or 'none'),
             '', '| System | Predictions | Correct | Human pending | Macro accuracy | Failures |',
             '|---|---:|---:|---:|---:|---:|']
    if (context_config or {}).get('runtime_manifest'):
        lines[3:3]=['Runtime: verified shared source export with a reconstructed local index and history; not the original owner runtime.','']
    if summary['dataset_notes']:
        notes = summary['dataset_notes']
        lines[3:3] = ['Source-based sample: development diagnostics, not independently held-out final-test evidence.',
                       'Question eligibility: ' + str(notes.get('eligibility', {}).get('definition', 'declared in the sample manifest')) + '.',
                       'Cross-partition target facts in diagnostic items: ' + str(len(notes.get('non_dev_target_facts', []))) + '.', '']
    for row in comparison:
        accuracy = 'pending' if row['macro_accuracy'] is None else f"{row['macro_accuracy']:.1%}"
        lines.append(f"| {row['system_id']} | {row['predictions']}/{row['questions']} | {row['correct']} | {row['needs_human']} | {accuracy} | {row['failed_predictions']} |")
    lines += ['', 'Macro accuracy requires complete prediction coverage and uses the same fully graded families for every method, listed in comparison.csv. Human-pending families are excluded for every method until reviewed. Partial coverage is not a final result.',
             '', '| System | Family | Questions | Correct | Needs review | Accuracy |',
             '|---|---|---:|---:|---:|---:|']
    for row in table:
        accuracy = 'pending' if row['accuracy'] is None else f"{row['accuracy']:.1%}"
        lines.append(f"| {row['system_id']} | {row['family']} | {row['n']} | {row['correct']} | {row['needs_human']} | {accuracy} |")
    lines += ['', '| Always-abstain baseline | Questions | Correct | Accuracy |',
              '|---|---:|---:|---:|']
    for row in summary['always_abstain']:
        accuracy='human pending' if row['accuracy'] is None else f"{row['accuracy']:.1%}"
        lines.append(f"| {row['family']} | {row['n']} | {row['correct']} | {accuracy} |")
    lines += ['', 'Missing answers and execution failures count as unsuccessful outcomes. Human grading remains pending where shown.',
              'Grounding decisions apply only to reviewed answers. Keep review_key.csv away from blinded reviewers.',
              'See summary.json for paired intervals, failure counts, tokens and latency.']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary

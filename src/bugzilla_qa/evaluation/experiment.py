"""Run or resume S predictions, then score them and prepare human review."""
import argparse
import datetime
import json
import itertools
import os
import subprocess
import sys
import shutil
from pathlib import Path
from collections import defaultdict
from . import systems as scoring

ROOT = Path(__file__).resolve().parents[3]
os.environ.setdefault('HF_HOME', str(ROOT / 'models/huggingface'))
KEY_NAMES = ['GROQ_API_KEY','GROQ_API_KEY_2','GROQ_API_KEY_3','GROQ_API_KEY_4']


def configured_keys(root, requested=None):
    from bugzilla_qa.llm.provider import env_values
    values = env_values(root / '.env')
    names, seen = [], set()
    for name in requested if requested is not None else KEY_NAMES:
        credential = os.environ.get(name) or values.get(name)
        if not credential:
            if requested is not None:
                raise ValueError(name+' is missing')
            continue
        if credential in seen:
            if requested is not None:
                raise ValueError('Selected credentials must be distinct')
            continue
        seen.add(credential)
        names.append(name)
    return names


class CredentialPool:
    def __init__(self, factory, config, role, names, **kwargs):
        from bugzilla_qa.llm.provider import env_values
        values = env_values(kwargs['root'] / config['env_file'])
        self.max_requests = kwargs['max_requests']
        self.providers, self.keys = [], []
        self.position, self.disabled, self.last_rate_limit = 0, set(), None
        for name in names:
            key = os.environ.get(name) or values.get(name)
            if not key:
                raise ValueError(name + ' is missing')
            account = kwargs['root'] / Path(config['ledger']).parent / 'accounts' / scoring.digest(key)[:16]
            account.mkdir(parents=True, exist_ok=True)
            receipt = account / 'origin.json'
            if not receipt.exists():
                legacy = kwargs['root'] / config['ledger']
                if name == 'GROQ_API_KEY_2' and legacy.exists():
                    shutil.copyfile(legacy, account / 'ledger.jsonl')
                    cooldown = legacy.parent / 'rate_limit_cooldowns.json'
                    if cooldown.exists():
                        shutil.copyfile(cooldown, account / cooldown.name)
                scoring.write(receipt, dict(credential_name=name,
                              legacy_usage_conservatively_inherited=name == 'GROQ_API_KEY_2',
                              legacy_sha256=scoring.file_hash(legacy) if name == 'GROQ_API_KEY_2' and legacy.exists() else None))
            effective = dict(config, ledger=str((account / 'ledger.jsonl').relative_to(kwargs['root'])))
            self.providers.append(factory(effective, role, **kwargs))
            self.keys.append(key)

    @property
    def calls(self):
        return sum(provider.calls for provider in self.providers)

    def generate_json(self, *args, **kwargs):
        from bugzilla_qa.llm.provider import InvalidJSONResponse, ProviderRateLimitError
        last_error = None
        for _ in self.providers:
            index = self.position % len(self.providers)
            self.position += 1
            if index in self.disabled:
                continue
            if self.calls >= self.max_requests:
                raise RuntimeError('Invocation request budget exhausted')
            provider = self.providers[index]
            provider.max_requests = provider.calls + self.max_requests - self.calls
            previous = os.environ.get('GROQ_API_KEY')
            os.environ['GROQ_API_KEY'] = self.keys[index]
            try:
                return provider.generate_json(*args, **kwargs)
            except InvalidJSONResponse:
                raise
            except (ProviderRateLimitError, RuntimeError) as error:
                text = str(error)
                if not isinstance(error, ProviderRateLimitError) and not any(
                    marker in text for marker in ('daily request budget', 'HTTP 401', 'HTTP 403', 'APIConnectionError', 'APITimeoutError')):
                    raise
                self.disabled.add(index)
                self.last_rate_limit = getattr(provider, 'last_rate_limit', None)
                last_error = error
            finally:
                if previous is None:
                    os.environ.pop('GROQ_API_KEY', None)
                else:
                    os.environ['GROQ_API_KEY'] = previous
        raise last_error or RuntimeError('All configured credential pools are unavailable; resume later')

    def generate_tools(self, prompt, tools, **kwargs):
        from bugzilla_qa.llm.provider import tool_turn_schema
        return self.generate_json(prompt, tool_turn_schema(tools), **kwargs)


def worker(argv=None):
    from bugzilla_qa.answering import runner, cli
    names = json.loads(os.environ['BUGZILLA_EVAL_KEY_NAMES'])
    factory = runner.create_provider
    runner.create_provider = lambda config, role, **kwargs: CredentialPool(factory, config, role, names, **kwargs)
    return cli.main(argv)


def pilot_selection(datasets, size=80):
    selected = {'phase05': sorted(q['qid'] for q in datasets['phase05'][0]), 'natural': [], 'v3': []}
    if len(selected['phase05']) != 34:
        raise ValueError('The 80-question pilot requires the original 34 development questions')
    def choose(items, count):
        groups = defaultdict(list)
        for q in sorted(items, key=lambda q: scoring.digest([317, q['qid']])):
            groups[q['cluster_id']].append(q)
        ordered = [q for group in itertools.zip_longest(*(groups[c] for c in sorted(groups, key=lambda c:scoring.digest([317,c])))) for q in group if q]
        if len(ordered) < count:
            raise ValueError('Insufficient development questions for the pilot')
        return [q['qid'] for q in ordered[:count]]
    natural = datasets['natural'][0]
    families = sorted({q['family'] for q in natural})
    groups = {f:choose([q for q in natural if q['family']==f], sum(q['family']==f for q in natural)) for f in families}
    selected['natural'] = [qid for group in itertools.zip_longest(*(groups[f] for f in families)) for qid in group if qid][:10]
    for family, count in (('KI',17), ('MH',8), ('F6H',11)):
        selected['v3'].extend(choose([q for q in datasets['v3'][0] if q['family']==family], count))
    if sum(map(len, selected.values())) != 80:
        raise ValueError('Pilot selection must contain exactly 80 questions')
    if size==125:
        for dataset, target in [('natural',20),('v3',71)]:
            remaining=[q for q in datasets[dataset][0] if q['qid'] not in selected[dataset]]
            families=sorted({q['family'] for q in remaining})
            groups=[choose([q for q in remaining if q['family']==family],sum(q['family']==family for q in remaining)) for family in families]
            extra=[qid for group in itertools.zip_longest(*groups) for qid in group if qid]
            selected[dataset].extend(extra[:target-len(selected[dataset])])
        if sum(map(len,selected.values()))!=125:
            raise ValueError('Insufficient questions for the 125-question pilot')
    elif size!=80:
        raise ValueError('Supported pilot sizes are 80 and 125')
    return selected


def evidence_inputs(directory, fallback):
    manifest = scoring.read(directory / 'manifest.json')
    snapshot = directory / 'config_snapshot.json'
    config = fallback
    if snapshot.exists():
        if scoring.file_hash(snapshot) != manifest['sha256']['config_snapshot.json']:
            raise ValueError('Prediction context configuration checksum mismatch')
        config = scoring.read(snapshot)
    if not config.get('selection'):
        return config, {}, {}
    selection_path = ROOT / config['selection']
    expected = manifest.get('input_sha256', {}).get(config['selection'])
    if not selection_path.exists() or expected and scoring.file_hash(selection_path) != expected:
        return config, {}, {}
    selection = scoring.read(selection_path)
    folder = ROOT / selection['index_build'] / selection['selected']['corpus']
    corpus = folder / 'corpus.jsonl'
    if not corpus.exists():
        return config, {}, {}
    receipt = scoring.read(folder / 'manifest.json')
    if scoring.file_hash(corpus) != receipt['sha256']['corpus.jsonl']:
        raise ValueError('Review evidence corpus checksum mismatch')
    documents = {r['chunk_id']:r for r in scoring.rows(corpus)}
    if any(r.get('visibility') != 'public' for r in documents.values()):
        raise ValueError('Review evidence includes nonpublic sources')
    return config, documents, {str(corpus):scoring.file_hash(corpus)}


def demo(output, dry_run=False):
    fixture = ROOT / 'tests/fixtures/s_evaluation.json'
    data = scoring.read(fixture)
    fixture_systems = list(data[0]['answers'])
    if dry_run:
        return dict(state='DRY_RUN', simulated=True, questions=len(data), systems=fixture_systems)
    items, selected, attempts = [], {}, {}
    config_hash = scoring.file_hash(fixture)
    for index, row in enumerate(data):
        items.append(dict(qid='sample_' + str(index + 1), question=row['question'], family=row['family'],
                          kind=row['kind'], expected=row['expected'], acceptable_bug_ids=row.get('acceptable_bug_ids', []),
                          cluster_id=row.get('cluster_id', str(index + 1)), evidence=row.get('evidence', []),
                          scope={'population': 'synthetic fixture'}, tolerance_hours=1.0,
                          dataset='sample', split='dev', freeze_id='synthetic'))
    prediction_dir = output / 'sample_predictions'
    prediction_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for system in fixture_systems:
        predictions = []
        for item, case in zip(items, data):
            value = case['answers'][system]
            answer = dict(abstain=value is None, answer=value, answer_type=item['kind'],
                          bug_ids=case.get('bug_ids', []), citations=[] if system == 'S0' or value is None else ['sample_evidence'],
                          rationale='Synthetic response for an offline workflow check.')
            predictions.append(dict(qid=item['qid'], system_id=system, dataset='sample', split='dev',
                                    family=item['family'], freeze_id='synthetic', config_hash=config_hash,
                                    model='mock', provider='fixture', prompt_version='sample-v1', simulated=True,
                                    status='ok', answer=answer, context_chunk_ids=[] if system == 'S0' else ['sample_evidence'],
                                    call_count=0, tokens={'input': 0, 'output': 0, 'usage_missing': False},
                                    latency_ms=None, llm_cache_hit=False, diagnostic_only=False))
        path = prediction_dir / (system + '.jsonl')
        path.write_text(''.join(json.dumps(p) + '\n' for p in predictions), encoding='utf-8')
        hashes[path.name] = scoring.file_hash(path)
    scoring.write(prediction_dir / 'manifest.json', dict(simulated=True, config_hash=config_hash, sha256=hashes))
    selected, attempts, pins = scoring.select_predictions(prediction_dir, items, fixture_systems)
    pins[str(fixture)] = config_hash
    return scoring.evaluate(items, selected, attempts, output / 'fixture', fixture_systems, pins, sample=True)


def generate(args):
    config_path = ROOT / args.config
    config = scoring.read(config_path)
    retrieval_path = ROOT / config['retrieval_config']
    retrieval = scoring.read(retrieval_path)
    retrieval['datasets'] = args.datasets
    plans = []
    for dataset in args.datasets:
        from bugzilla_qa.answering.calibration import with_calibration
        from bugzilla_qa.answering.runner import plan, prepare
        effective = with_calibration(config, ROOT)
        calibration_preview = None
        if 'S4' in args.systems and effective.get('corrective_tau') is None:
            if args.split != 'dev':
                raise RuntimeError('S4 needs its finalized development calibration before test execution')
            from bugzilla_qa.answering.calibration import suggest
            calibration_preview = suggest(config, ROOT, write=not args.dry_run)
            effective = with_calibration(config, ROOT)
        fixed = getattr(args, 'selected_qids', {}).get(dataset)
        result = plan(effective, ROOT, dataset=dataset, split=args.split, confirm=args.confirm_locked_test,
                      systems=args.systems, resume=True, limit=args.limit, **({'qids':fixed} if fixed is not None else {}))
        if calibration_preview is not None:
            result['s4_calibration'] = calibration_preview
        questions, _, _, _, _, directory = prepare(effective, ROOT, dataset, args.split, args.confirm_locked_test)
        if fixed is not None:
            questions = [q for q in questions if q['qid'] in set(fixed)]
        plans.append((dataset, directory, result, questions))
    if args.dry_run:
        return {dataset: plan for dataset, _, plan, _ in plans}, {}
    remaining = args.max_requests
    runs = {dataset: directory for dataset, directory, _, _ in plans}
    generation = {}
    for dataset, directory, _, questions in plans:
        if remaining <= 0:
            generation[dataset] = dict(state='PENDING', reason='Shared request budget exhausted')
            continue
        done = []
        for system in args.systems:
            path = directory / (system + '.jsonl')
            done.append({r['qid'] for r in scoring.rows(path) if r['status'] == 'ok' or r.get('terminal_error')} if path.exists() else set())
        groups = defaultdict(list)
        for q in questions:
            if not all(q['qid'] in finished for finished in done):
                groups[q['family']].append(q['qid'])
        ordered = [qid for group in itertools.zip_longest(*(groups[f] for f in sorted(groups))) for qid in group if qid]
        if args.limit:
            ordered = ordered[:args.limit]
        batches = []
        for start in range(0, len(ordered), 3):
            if remaining <= 0:
                break
            command = [sys.executable, '-m', 'bugzilla_qa.answering.cli', 'run', '--config', str(config_path),
                       '--dataset', dataset, '--split', args.split, '--systems', *args.systems,
                       '--qid', *ordered[start:start + 3], '--resume', '--enable-llm', '--max-requests', str(remaining)]
            environment = os.environ.copy()
            if getattr(args, 'api_key_envs', None):
                command = [sys.executable, '-c', 'from bugzilla_qa.evaluation.experiment import worker; raise SystemExit(worker())'] + command[3:]
                environment['BUGZILLA_EVAL_KEY_NAMES'] = json.dumps(args.api_key_envs)
            if args.confirm_locked_test:
                command += ['--confirm-locked-test']
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            log = ROOT / 'outputs/evaluation/phase11/logs' / (dataset + '-' + stamp + '.log')
            log.parent.mkdir(parents=True, exist_ok=True)
            print('Running', dataset, 'balanced batch', len(batches) + 1, 'with', remaining, 'remaining HTTP attempts; log:', log, flush=True)
            with log.open('w', encoding='utf-8') as handle:
                summary_path = directory / 'summary.json'
                before = summary_path.stat().st_mtime_ns if summary_path.exists() else None
                process = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, env=environment)
            if not summary_path.exists() or summary_path.stat().st_mtime_ns == before:
                raise RuntimeError('Answering runner did not save a summary; inspect ' + str(log))
            result = scoring.read(summary_path)
            batches.append(dict(result, process_exit_code=process.returncode, log=str(log),
                                credential_names=getattr(args, 'api_key_envs', None),
                                orchestration_sha256=scoring.file_hash(__file__)))
            remaining -= result['actual_api_calls']
            if result['state'] == 'PARTIAL':
                break
        unfinished = len(batches) * 3 < len(ordered) or bool(batches and batches[-1]['state'] == 'PARTIAL')
        generation[dataset] = dict(state='PARTIAL' if unfinished else 'COMPLETE_SELECTED_BATCH' if args.limit else 'COMPLETE',
                                   batches=batches, actual_api_calls=sum(b['actual_api_calls'] for b in batches))
        if unfinished:
            break
    return generation, runs


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run S0-S8 on official question bundles, score answers and build the review page.')
    parser.add_argument('--shared-source', action='store_true', help='Verify and use the shared source export with official development questions.')
    parser.add_argument('--fixture', action='store_true', help='Offline scorer unit fixture only; never calls a model.')
    parser.add_argument('--score-only', action='store_true')
    parser.add_argument('--prediction-run', action='append', default=[], metavar='DATASET=PATH')
    parser.add_argument('--config', default='configs/answering.yaml')
    parser.add_argument('--datasets', nargs='+', choices=['phase05', 'natural', 'v3'], default=['phase05', 'natural', 'v3'])
    parser.add_argument('--systems', nargs='+', choices=['S' + str(i) for i in range(9)] + ['ORACLE'], default=scoring.SYSTEMS)
    parser.add_argument('--split', choices=['dev', 'test'], default='dev')
    parser.add_argument('--confirm-locked-test', action='store_true')
    parser.add_argument('--enable-llm', action='store_true')
    credentials = parser.add_mutually_exclusive_group()
    credentials.add_argument('--api-key-env', choices=KEY_NAMES, help='Use one selected .env entry instead of automatic discovery.')
    credentials.add_argument('--api-key-envs', nargs='+', choices=KEY_NAMES, help='Use selected .env entries instead of automatic discovery.')
    parser.add_argument('--pilot-size', type=int, choices=[80,125], help='Fixed official development pilot; reuses saved answers.')
    parser.add_argument('--max-requests', type=int, default=900)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--output', default='outputs/evaluation/phase11')
    parser.add_argument('--reviews', help='Completed review_queue.csv; use with one dataset')
    parser.add_argument('--review', action='store_true', help='Openable review page and readable CSV from saved results; no API calls.')
    parser.add_argument('--import-review', metavar='CSV', help='Import decisions from the simplified review CSV and refresh scores.')
    args = parser.parse_args(argv)
    if args.review or args.import_review:
        if args.enable_llm or args.dry_run:
            parser.error('Review commands use saved results only; omit --enable-llm and --dry-run')
        output = (ROOT / args.output).resolve()
        if not output.is_relative_to((ROOT / 'outputs/evaluation').resolve()):
            parser.error('Evaluation output must stay under outputs/evaluation')
        from . import review
        try:
            result = review.apply(ROOT,output,ROOT / args.import_review) if args.import_review else review.build(ROOT,output)
            print(json.dumps(result,indent=2))
            return 0
        except (OSError,ValueError,KeyError,RuntimeError) as error:
            print(json.dumps(dict(state='BLOCKED',error=str(error))))
            return 2
    if not args.fixture and not args.score_only:
        requested = [args.api_key_env] if args.api_key_env else args.api_key_envs
        try:
            args.api_key_envs = configured_keys(ROOT,requested)
        except ValueError as error:
            parser.error(str(error))
    if args.pilot_size and (not args.shared_source or args.limit or args.datasets != ['phase05','natural','v3']):
        parser.error('--pilot-size requires --shared-source and all three datasets, without --limit')
    if args.shared_source and (args.fixture or args.split!='dev'):
        parser.error('--shared-source is for the official development datasets only')
    if not args.fixture and not args.enable_llm and not args.score_only:
        args.dry_run = True
    if args.max_requests < 1 or args.limit is not None and args.limit < 1:
        parser.error('Limits must be positive')
    if len(set(args.systems)) != len(args.systems) or len(set(args.datasets)) != len(args.datasets):
        parser.error('Duplicate systems or datasets')
    if args.split == 'test' and not args.confirm_locked_test:
        parser.error('Test requires --confirm-locked-test after finalizing methods and scoring')
    if args.fixture and (args.enable_llm or args.score_only or args.prediction_run or args.split == 'test' or args.reviews):
        parser.error('The offline fixture is separate from real inference and scoring')
    if args.reviews and len(args.datasets) != 1:
        parser.error('--reviews requires exactly one dataset')
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to((ROOT / 'outputs/evaluation').resolve()):
        parser.error('Evaluation output must stay under outputs/evaluation')
    try:
        if args.shared_source:
            from .shared_source import official
            prepared = official(ROOT,args.dry_run)
            if args.dry_run and not args.pilot_size:
                print(json.dumps(prepared,indent=2))
                return 0
            if not args.dry_run:
                args.config = str(prepared.relative_to(ROOT))
            else:
                args.config = 'outputs/evaluation/phase11/official_runtime/answering.json'
        if args.fixture:
            result = demo(output, args.dry_run)
            print(json.dumps({k: result[k] for k in ('state', 'simulated', 'questions', 'systems')}, indent=2))
            if not args.dry_run:
                print('Report:', output / 'fixture/report.md')
            return 0
        config = scoring.read(ROOT / args.config)
        retrieval_path = ROOT / config['retrieval_config']
        retrieval = scoring.read(retrieval_path)
        datasets = {}
        for dataset in args.datasets:
            datasets[dataset] = scoring.load_items(ROOT, retrieval, dataset, args.split, args.confirm_locked_test)
        if args.pilot_size:
            args.selected_qids = pilot_selection(datasets,args.pilot_size)
            selection = dict(state='DEVELOPMENT_PILOT', seed=317, questions=args.pilot_size,
                             selection_rule='All 34 original dev; 10 natural stratified by family; 17 KI, all 8 MH and all 11 F6H, cluster spread; no answer scores used.' if args.pilot_size==80 else 'Retain the original 80; extend to 20 natural and 71 v3 by family and cluster spread. No answer scores used.',
                             qids=args.selected_qids,
                             source_pins={d:pins for d, (_,pins) in datasets.items()})
            selection_path = output / ('pilot'+str(args.pilot_size)+'_selection.json')
            if selection_path.exists() and scoring.read(selection_path) != selection:
                raise ValueError('Saved pilot selection differs; preserve it and inspect source versions')
            if not args.dry_run:
                scoring.write(selection_path, selection)
        runs = {}
        for specification in args.prediction_run:
            dataset, path = specification.split('=', 1)
            if dataset not in args.datasets or dataset in runs:
                raise ValueError('Specify exactly one prediction run per selected dataset')
            runs[dataset] = ROOT / path
        if args.score_only:
            if set(runs) != set(args.datasets):
                raise ValueError('--score-only requires --prediction-run DATASET=PATH for every selected dataset')
            generation = {}
        else:
            if runs:
                raise ValueError('--prediction-run is only for --score-only')
            if not args.enable_llm:
                args.dry_run = True
            generation, runs = generate(args)
        result = dict(state='DRY_RUN' if args.dry_run else 'COMPLETE', generation=generation, evaluations={})
        if args.pilot_size:
            result.update(pilot_questions=args.pilot_size, selection=str(selection_path), credential_names=args.api_key_envs)
        for dataset, directory in runs.items():
            items, pins = datasets[dataset]
            full_items = items
            if args.pilot_size:
                ids = set(args.selected_qids[dataset])
                items = [q for q in items if q['qid'] in ids]
                pins = dict(pins, pilot_selection=scoring.digest(selection))
            if args.dry_run:
                result['evaluations'][dataset] = dict(questions=len(items), prediction_run=str(directory))
                continue
            if not (directory / 'manifest.json').exists():
                result['evaluations'][dataset] = dict(state='PENDING', reason='No predictions yet')
                result['state'] = 'PARTIAL'
                continue
            selected, attempts, prediction_pins = scoring.select_predictions(directory, full_items, args.systems)
            if args.pilot_size:
                selected = {system:{qid:p for qid,p in values.items() if qid in ids} for system,values in selected.items()}
                attempts = {system:[p for p in values if p['qid'] in ids] for system,values in attempts.items()}
            context_config, documents, evidence_pins = evidence_inputs(directory, config)
            dataset_pins = dict(pins)
            pins.update(prediction_pins)
            pins.update(evidence_pins)
            pins[str(ROOT / args.config)] = scoring.file_hash(ROOT / args.config)
            pins[str(retrieval_path)] = scoring.file_hash(retrieval_path)
            identity = scoring.digest([dataset_pins, scoring.read(directory / 'manifest.json')['config_hash'],
                                       args.systems, scoring.file_hash(scoring.__file__)])[:16]
            destination = output / dataset / args.split / ('run-' + identity)
            summary = scoring.evaluate(items, selected, attempts, destination, args.systems, pins, reviews=args.reviews,
                                       context_config=context_config, documents=documents)
            if args.pilot_size:
                summary['pilot'] = dict(total_questions=args.pilot_size, collection_questions=len(items), selection=str(selection_path),
                                       limitation='Development subset; overlapping collections reported separately; not a final test.')
                scoring.write(destination / 'summary.json', summary)
                with (destination / 'report.md').open('a', encoding='utf-8') as handle:
                    handle.write('\nFixed '+str(args.pilot_size)+'-question development pilot: this collection contains '+str(len(items))+
                                 ' selected questions. Collections overlap and are reported separately. Not a final test.\n')
            result['evaluations'][dataset] = dict(state=summary['state'], output=str(destination), questions=len(items))
            if summary['state'] != 'REVIEWED':
                result['state'] = 'PARTIAL' if summary['state'] == 'PARTIAL' else 'NEEDS_REVIEW' if result['state'] != 'PARTIAL' else 'PARTIAL'
        if not args.dry_run:
            scoring.write(output / 'latest.json', result)
            if config.get('selection') and any(e.get('output') for e in result['evaluations'].values()):
                from .review import build
                result['review_files'] = build(ROOT,output)
                scoring.write(output / 'latest.json',result)
        print(json.dumps(result, indent=2))
        return 2 if result['state'] == 'PARTIAL' else 0
    except (OSError, ValueError, KeyError, ImportError, RuntimeError) as error:
        print(json.dumps(dict(state='BLOCKED', error=str(error))))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

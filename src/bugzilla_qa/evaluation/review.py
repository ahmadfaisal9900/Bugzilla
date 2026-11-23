"""Present saved evaluation answers in one page and import validated human reviews."""
import csv
import json
from pathlib import Path
from . import systems as s

TYPES = {'F1':'Bug fields','F2':'Timing and history','F3':'Counts','F4':'Links',
         'F5':'Explanations','F6':'Missing information','KI':'Bug identification',
         'MH':'Multi hop','F6H':'Hard abstention'}
FIELDS = ['review_id','dataset','question_type','review_needed','current_result','review_reason',
          'question','model_answer','model_explanation','reference_answer','reference_evidence','model_evidence',
          'answer_verdict','grounding_verdict','reviewer','note']
EDITABLE = ['answer_verdict','grounding_verdict','reviewer','note']


def plain(value):
    if value is None:
        return 'No answer supplied'
    if isinstance(value, dict):
        if 'claims' in value:
            return '\n'.join(plain(x.get('text',x)) for x in value['claims'])
        return '\n'.join(str(k)+': '+plain(v) for k,v in value.items())
    if isinstance(value, list):
        return '\n'.join(plain(x) for x in value) or 'None'
    if isinstance(value,str) and value.startswith(('{','[')):
        try:
            parsed = json.loads(value)
            if isinstance(parsed,(dict,list)):return plain(parsed)
        except ValueError:
            pass
    return str(value)


def sheet_value(value):
    value = str(value)
    return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value


def csv_row(row):
    return {k:sheet_value(row.get(k,'')) for k in FIELDS}


def reference_evidence(item, documents):
    parts = []
    for source in item['evidence']:
        if isinstance(source,dict):
            parts.append('\n'.join(str(x) for x in [source.get('source_url',''),plain(source.get('fields',{}))] if x))
        else:
            chunks = [d for d in documents.values() if d.get('record_id')==source]
            parts.append('\n'.join(d['text'] for d in chunks) if chunks else 'Reference source record: '+str(source)+' (text unavailable in this view)')
    return '\n\n'.join(parts) or 'No reference excerpt supplied. Check the question scope and reference answer.'


def collect(root, output):
    from .experiment import evidence_inputs
    latest = s.read(output / 'latest.json')
    collections, entries, summaries = {}, [], []
    for dataset, record in latest['evaluations'].items():
        if not record.get('output'):
            continue
        folder = Path(record['output'])
        summary = s.read(folder / 'summary.json')
        manifest = s.read(folder / 'manifest.json')
        paths = [Path(p) for p in manifest['input_sha256'] if Path(p).name=='manifest.json' and 'predictions' in Path(p).parts]
        if len(paths)!=1:
            raise ValueError('Cannot identify the exact prediction run for '+dataset)
        prediction_run = paths[0].parent
        for path, sha in manifest['input_sha256'].items():
            if path=='pilot_selection':
                selection = s.read(Path(summary.get('pilot',{}).get('selection',output / 'pilot80_selection.json')))
                if s.digest(selection)!=sha:
                    raise ValueError('Pilot selection changed')
                continue
            source = root / path
            if not source.exists() or s.file_hash(source)!=sha:
                raise ValueError('Evaluation source changed: '+str(source))
        config, documents, _ = evidence_inputs(prediction_run,{})
        retrieval = s.read(root / config['retrieval_config'])
        summary = s.read(folder / 'summary.json')
        split = summary['split']
        items, _ = s.load_items(root,retrieval,dataset,split,confirm=split=='test')
        selected, attempts, _ = s.select_predictions(prediction_run,items,summary['systems'])
        scores = s.rows(folder / 'scores.jsonl')
        keys = {(x['system_id'],x['qid']):x for x in scores}
        items = [q for q in items if any(q['qid']==key[1] for key in keys)]
        with (folder / 'review_queue.csv').open(newline='',encoding='utf-8-sig') as handle:
            queue = {x['review_id']:x for x in csv.DictReader(handle)}
        for item in items:
            for method in summary['systems']:
                score = keys[(method,item['qid'])]
                prediction = selected[method].get(item['qid']) or {}
                original = s.grade(item,prediction or None)
                answer = prediction.get('answer') or {}
                review_id = score.get('review_id') or s.digest([dataset,item['qid'],method,'no-valid-answer'])[:24]
                old = queue.get(review_id,{})
                needs_answer = original['verdict']=='NEEDS_HUMAN'
                needs_evidence = bool(old)
                task = 'Answer and evidence' if needs_answer else 'Evidence only' if needs_evidence else 'No review required'
                reason = 'Check the explanation against the source comments.' if original['reason']=='explanation_review' else 'Confirm the time unit and compare the duration within one hour.' if original['reason']=='ambiguous_duration_unit' else 'Sampled check: does the supplied evidence support the response?' if needs_evidence else 'Automatically graded; included for inspection.'
                status = 'Needs your grading' if score['verdict']=='NEEDS_HUMAN' else ('Correct' if score['verdict']=='CORRECT' else 'Wrong')+(' (human)' if score['reason']=='human_review' else ' (automatic)')
                value = 'Abstained: no factual answer' if answer.get('abstain') else plain(answer.get('answer'))
                if prediction.get('status')!='ok':
                    value = 'Method failure: no valid completed answer' if prediction.get('terminal_error') else 'No completed answer yet'
                reference = plain(item['expected'])
                if item['kind']=='calendar_duration':
                    reference += ' hours (tolerance: 1 hour)'
                evidence = s.visible_evidence(prediction,config,documents) if prediction else ''
                if prediction.get('route')=='S7':
                    try:evidence = plain(json.loads(evidence))
                    except (ValueError,TypeError):pass
                entries.append(dict(review_id=review_id,dataset=dataset,question_id=item['qid'],method=method,
                                    family=item['family'],question_type=TYPES.get(item['family'],item['family']),
                                    review_needed=task,current_result=status,review_reason=reason,
                                    question=item['question'],model_answer=value,model_explanation=answer.get('rationale',''),
                                    reference_answer=reference,reference_evidence=reference_evidence(item,documents),
                                    model_evidence=evidence or 'No evidence was supplied to this method.',
                                    scope=plain(item['scope']),needs_answer=needs_answer,needs_evidence=needs_evidence,
                                    auto_result=original['verdict'],**{k:old.get(k,'') for k in EDITABLE}))
        collections[dataset] = dict(folder=folder,items=items,selected=selected,attempts=attempts,
                                    summary=summary,pins=manifest['input_sha256'],config=config,documents=documents,queue=queue)
        summaries.append(dict(dataset=dataset,questions=len(items),comparison=summary['comparison']))
    entries.sort(key=lambda row:(not row['needs_answer'],not row['needs_evidence'],row['dataset'],row['question_id'],row['method']))
    return entries, summaries, collections


def validate_reviews(rows, entries):
    expected = {x['review_id']:x for x in entries if x['needs_evidence']}
    changes, seen = {}, set()
    for row in rows:
        review_id = row.get('review_id')
        if review_id not in expected or review_id in seen:
            raise ValueError('Unknown or duplicate review ID')
        seen.add(review_id)
        source = expected[review_id]
        exported = csv_row(source)
        if any(row.get(k)!=exported[k] for k in FIELDS if k not in EDITABLE and k!='current_result'):
            raise ValueError('A question, answer or other fixed review field changed: '+review_id)
        decision = {k:row.get(k,'').strip() for k in EDITABLE}
        decision['answer_verdict'] = decision['answer_verdict'].upper()
        decision['grounding_verdict'] = decision['grounding_verdict'].upper()
        if decision['answer_verdict'] not in ('','CORRECT','INCORRECT'):
            raise ValueError('Answer decision must be CORRECT or INCORRECT')
        if decision['answer_verdict'] and not source['needs_answer']:
            raise ValueError('This response needs only an evidence check; leave answer_verdict blank')
        if decision['grounding_verdict'] not in ('','SUPPORTED','UNSUPPORTED','UNCLEAR','NOT_APPLICABLE'):
            raise ValueError('Invalid evidence decision')
        if decision['grounding_verdict']=='NOT_APPLICABLE' and source['model_answer']!='Abstained: no factual answer':
            raise ValueError('NOT_APPLICABLE is only for abstentions without factual claims')
        if decision['answer_verdict'] or decision['grounding_verdict']:
            if not decision['reviewer'] or not decision['note']:
                raise ValueError('Add reviewer initials and a note for each decision')
        changes[review_id] = decision
    return changes


def apply(root, output, path):
    entries, _, collections = collect(root,output)
    with Path(path).open(newline='',encoding='utf-8-sig') as handle:
        changes = validate_reviews(list(csv.DictReader(handle)),entries)
    for collection in collections.values():
        queue = collection['queue']
        for review_id, decision in changes.items():
            if review_id in queue:
                queue[review_id].update({k:v for k,v in decision.items() if v})
    for collection in collections.values():
        path = collection['folder'] / 'review_queue.csv'
        old = path.read_bytes()
        backup = path.with_name('review_queue.before-'+s.file_hash(path)[:12]+'.csv')
        if not backup.exists():backup.write_bytes(old)
        s.write_csv(path,list(collection['queue'].values()),list(next(iter(collection['queue'].values()))))
        summary = s.evaluate(collection['items'],collection['selected'],collection['attempts'],collection['folder'],
                             collection['summary']['systems'],collection['pins'],
                             context_config=collection['config'],documents=collection['documents'])
        if collection['summary'].get('pilot'):
            summary['pilot'] = collection['summary']['pilot']
            s.write(collection['folder']/'summary.json',summary)
    latest = s.read(output/'latest.json')
    for dataset, collection in collections.items():
        latest['evaluations'][dataset]['state'] = s.read(collection['folder']/'summary.json')['state']
    latest['state'] = 'PARTIAL' if any(v['state']=='PARTIAL' for v in latest['evaluations'].values()) else 'NEEDS_REVIEW' if any(v['state']=='NEEDS_REVIEW' for v in latest['evaluations'].values()) else 'REVIEWED'
    s.write(output/'latest.json',latest)
    return build(root,output)


def build(root, output):
    entries, summaries, _ = collect(root,output)
    selected = [row for row in entries if row['needs_evidence']]
    path = output / 'REVIEW.csv'
    if path.exists():
        with path.open(newline='',encoding='utf-8-sig') as handle:
            old = list(csv.DictReader(handle))
        if any(any(row.get(k,'').strip() for k in EDITABLE) for row in old):
            backup = path.with_name('REVIEW.saved-'+s.file_hash(path)[:12]+'.csv')
            if not backup.exists():backup.write_bytes(path.read_bytes())
            decisions = validate_reviews(old,entries)
            for row in entries:
                if row['review_id'] in decisions:
                    row.update({k:v for k,v in decisions[row['review_id']].items() if v})
    with path.open('w',newline='',encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(csv_row(row) for row in selected)
    payload = dict(rows=entries,summaries=summaries,fields=FIELDS,editable=EDITABLE,
                   questions=len({(r['dataset'],r['question_id']) for r in entries}),
                   methods=len({r['method'] for r in entries}))
    payload['id'] = s.digest([{k:v for k,v in row.items() if k not in EDITABLE} for row in entries])[:20]
    data = json.dumps(payload,ensure_ascii=False).replace('<',chr(92)+'u003c').replace('>',chr(92)+'u003e').replace('&',chr(92)+'u0026')
    page = output / 'START_HERE.html'
    page.write_text(PAGE.replace('__DATA__',data),encoding='utf-8')
    return dict(page=str(page),review_csv=str(path),answers=len(entries),answer_decisions=sum(row['needs_answer'] for row in entries),evidence_checks=len(selected))


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bugzilla evaluation results</title>
<style>
:root{--bg:#f5f6f8;--surface:#fff;--sunken:#f3f4f7;--line:#e4e7ec;--line-strong:#d0d5dd;--text:#1d2433;--muted:#5f6b7a;--faint:#98a1ad;
--accent:#3b5bdb;--accent-soft:#eaeefd;--accent-text:#2f4ac0;
--ok:#1f7a4a;--ok-soft:#e4f4ea;--bad:#b4362f;--bad-soft:#fbe8e6;--warn:#a05e00;--warn-soft:#fdf1dc;--info:#0e7c86;--info-soft:#dff3f4;
--mark:#fff1a8;--shadow:0 1px 2px rgba(20,30,50,.05);color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111418;--surface:#181c22;--sunken:#1f242b;--line:#2a3039;--line-strong:#3a414c;--text:#e6e9ee;--muted:#a1aab7;--faint:#7c8693;
--accent:#7b93f2;--accent-soft:#232c48;--accent-text:#a9b8f7;--ok:#5cc28c;--ok-soft:#173326;--bad:#f08a80;--bad-soft:#3a1d1b;--warn:#e5b05c;--warn-soft:#352812;--info:#5cc9d1;--info-soft:#14302f;--mark:#5a4b10;--shadow:none;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#111418;--surface:#181c22;--sunken:#1f242b;--line:#2a3039;--line-strong:#3a414c;--text:#e6e9ee;--muted:#a1aab7;--faint:#7c8693;
--accent:#7b93f2;--accent-soft:#232c48;--accent-text:#a9b8f7;--ok:#5cc28c;--ok-soft:#173326;--bad:#f08a80;--bad-soft:#3a1d1b;--warn:#e5b05c;--warn-soft:#352812;--info:#5cc9d1;--info-soft:#14302f;--mark:#5a4b10;--shadow:none;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
button,input,select,textarea{font:inherit;color:inherit}button{cursor:pointer}
.top{position:sticky;top:0;z-index:20;background:var(--surface);border-bottom:1px solid var(--line)}
.top-in{max-width:1400px;margin:auto;display:flex;align-items:center;gap:18px;padding:10px 20px;flex-wrap:wrap}
.brand{font-weight:650;font-size:16px}
.prog{flex:1;min-width:200px;display:flex;align-items:center;gap:10px;font-size:13px;color:var(--muted)}
.prog b{color:var(--text);font-weight:600;white-space:nowrap}
.bar{flex:1;max-width:260px;height:6px;border-radius:99px;background:var(--sunken);overflow:hidden}
.bar i{display:block;height:100%;background:var(--ok);border-radius:99px;transition:width .25s}
.tools{display:flex;align-items:center;gap:8px}
.btn{border:1px solid var(--line-strong);background:var(--surface);border-radius:8px;padding:7px 12px;font-size:14px;line-height:1.2}
.btn:hover{background:var(--sunken)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
:root[data-theme="dark"] .btn.primary{color:#0f1424}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .btn.primary{color:#0f1424}}
.btn.small{padding:4px 10px;font-size:13px}.btn:disabled{opacity:.4;cursor:default}
.initials input{width:92px;padding:7px 9px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);text-transform:uppercase;font-size:14px}
.initials input.missing{border-color:var(--warn);background:var(--warn-soft)}
.menu{position:relative}
.menu-pop{position:absolute;right:0;top:calc(100% + 6px);background:var(--surface);border:1px solid var(--line);border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.14);padding:6px;min-width:280px;display:none;z-index:30}
.menu.open .menu-pop{display:block}
.menu-pop button,.menu-pop label{display:flex;align-items:flex-start;gap:8px;width:100%;text-align:left;padding:8px 10px;border:0;background:none;border-radius:6px;font-size:14px;cursor:pointer}
.menu-pop button:hover,.menu-pop label:hover{background:var(--sunken)}
.menu-pop hr{border:0;border-top:1px solid var(--line);margin:6px 0}
.menu-pop small{display:block;color:var(--muted);font-size:12px}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(20px);background:var(--text);color:var(--bg);padding:10px 16px;border-radius:10px;font-size:14px;opacity:0;pointer-events:none;transition:.2s;z-index:50;max-width:min(560px,90vw)}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}#toast.error{background:var(--bad);color:#fff}
.layout{max-width:1400px;margin:16px auto 40px;padding:0 20px;display:grid;grid-template-columns:320px minmax(0,1fr);gap:16px;align-items:start}
.side{position:sticky;top:72px;background:var(--surface);border:1px solid var(--line);border-radius:12px;display:flex;flex-direction:column;max-height:calc(100vh - 88px)}
.side-head{padding:14px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:12px}
.sgroup{display:flex;flex-direction:column;gap:2px}
.sgroup .h{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);font-weight:700;margin:2px 0 4px 2px}
.sopt{display:flex;align-items:center;gap:9px;border:0;background:none;border-radius:8px;padding:6px 9px;font-size:14px;text-align:left;width:100%}
.sopt:hover{background:var(--sunken)}
.sopt.on{background:var(--accent-soft);color:var(--accent-text);font-weight:600}
.sopt i{width:9px;height:9px;border-radius:50%;flex:none}
.sopt span{flex:1}.sopt em{font-style:normal;font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums;font-weight:500}
.d-human{background:var(--warn)}.d-evidence{background:var(--info)}.d-reviewed{background:var(--accent)}.d-correct{background:var(--ok)}.d-incorrect{background:var(--bad)}.d-all{background:var(--line-strong)}
.frow{display:grid;grid-template-columns:1fr 1fr;gap:8px}
select,.search{width:100%;border:1px solid var(--line-strong);border-radius:8px;padding:7px 9px;background:var(--surface);font-size:14px}
#list{overflow:auto;flex:1}
.count{font-size:12px;color:var(--muted);padding:8px 14px;border-bottom:1px solid var(--line)}
.q{display:flex;gap:10px;width:100%;text-align:left;border:0;border-bottom:1px solid var(--line);background:none;padding:10px 14px;border-left:3px solid transparent;align-items:flex-start}
.q:hover{background:var(--sunken)}.q.on{background:var(--accent-soft);border-left-color:var(--accent)}
.q-main{flex:1;min-width:0}
.q-title{font-size:14px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.q-sub{font-size:12px;color:var(--muted);margin-top:2px}
.q-n{flex:none;font-size:12px;font-weight:600;min-width:22px;text-align:center;padding:1px 7px;border-radius:99px;background:var(--sunken);color:var(--muted);margin-top:1px}
.empty{padding:40px 20px;text-align:center;color:var(--muted)}
.main{display:flex;flex-direction:column;gap:14px;min-width:0}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.qcard{padding:16px 20px}
.qcard-top{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px;color:var(--muted)}
.qcard-top .sp{flex:1}
.qcard h1{font-size:19px;line-height:1.4;margin:0;font-weight:650}
.wording{margin-top:6px;font-size:13px}
.wording summary{cursor:pointer;color:var(--accent-text);display:inline}
.wording div{margin-top:6px;padding:10px 12px;background:var(--sunken);border-radius:8px;color:var(--muted);white-space:pre-wrap;overflow-wrap:anywhere}
.tabs{display:flex;gap:6px;padding:12px 16px;border-bottom:1px solid var(--line);overflow-x:auto}
.tab{border:1px solid var(--line);background:var(--surface);border-radius:8px;padding:5px 10px;font-size:13px;display:inline-flex;align-items:center;gap:6px;white-space:nowrap;color:var(--muted)}
.tab:hover{background:var(--sunken)}
.tab.on{border-color:var(--accent);background:var(--accent-soft);color:var(--accent-text);font-weight:600}
.tab i{width:8px;height:8px;border-radius:50%}
.resp{padding:18px 20px;display:flex;flex-direction:column;gap:14px}
.rhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.rhead h2{margin:0;font-size:16px}.rhead .sp{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;padding:3px 10px;border-radius:99px}
.pill i{width:7px;height:7px;border-radius:50%}
.p-human{background:var(--warn-soft);color:var(--warn)}.p-human i{background:var(--warn)}
.p-evidence{background:var(--info-soft);color:var(--info)}.p-evidence i{background:var(--info)}
.p-reviewed{background:var(--accent-soft);color:var(--accent-text)}.p-reviewed i{background:var(--accent)}
.p-correct{background:var(--ok-soft);color:var(--ok)}.p-correct i{background:var(--ok)}
.p-incorrect{background:var(--bad-soft);color:var(--bad)}.p-incorrect i{background:var(--bad)}
.instr{font-size:14px;color:var(--muted);margin:-4px 0 0}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.ans{border:1px solid var(--line);border-radius:10px;padding:10px 14px 12px;min-width:0}
.ans .lab{font-size:12px;font-weight:600;color:var(--muted)}
.ans .val{font-size:16.5px;font-weight:600;margin-top:3px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto}
.ans .val.abst{color:var(--muted);font-weight:500;font-style:italic}
.ans.ref{background:var(--ok-soft);border-color:transparent}.ans.ref .lab{color:var(--ok)}
.hint{font-size:13px;padding:7px 12px;border-radius:8px}
.hint.good{background:var(--ok-soft);color:var(--ok)}.hint.bad{background:var(--bad-soft);color:var(--bad)}
.why{font-size:14px;color:var(--muted)}
.why b{color:var(--text);font-weight:600}
details.fold{border:1px solid var(--line);border-radius:10px}
details.fold>summary{cursor:pointer;padding:9px 14px;font-weight:600;font-size:14px;list-style:none;display:flex;gap:8px;align-items:center}
details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary::before{content:"";width:6px;height:6px;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(-45deg);transition:.15s;margin-right:4px}
details.fold[open]>summary::before{transform:rotate(45deg)}
details.fold>summary small{font-weight:400;color:var(--muted)}
.fold-body{padding:0 14px 14px;display:flex;flex-direction:column;gap:8px;max-height:440px;overflow:auto}
.snip{border-left:3px solid var(--line-strong);padding:4px 0 4px 12px}
.snip b{display:block;font-size:12px;color:var(--muted);font-weight:600;margin-bottom:2px}
.snip div{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13.5px}
.prose{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13.5px;color:var(--muted)}
.sub-h{font-size:12px;font-weight:700;color:var(--muted);margin-top:4px}
mark{background:var(--mark);color:inherit;border-radius:3px;padding:0 1px}
a{color:var(--accent-text)}
.decide{border-top:1px solid var(--line);padding:16px 20px 18px;background:var(--sunken);border-radius:0 0 12px 12px;display:flex;flex-direction:column;gap:14px}
.qlab{font-weight:600;font-size:14px;margin-bottom:6px}
.choices{display:flex;gap:8px;flex-wrap:wrap}
.choice{border:1.5px solid var(--line-strong);background:var(--surface);border-radius:9px;padding:7px 16px;font-size:14px;font-weight:500}
.choice:hover{border-color:var(--accent)}
.choice:disabled{opacity:.4;cursor:not-allowed;border-color:var(--line-strong)}
.choice.on.c-good{background:var(--ok);border-color:var(--ok);color:#fff}
.choice.on.c-bad{background:var(--bad);border-color:var(--bad);color:#fff}
.choice.on.c-mid{background:var(--warn);border-color:var(--warn);color:#fff}
.choice.on.c-na{background:var(--muted);border-color:var(--muted);color:#fff}
textarea{width:100%;min-height:56px;resize:vertical;border:1px solid var(--line-strong);border-radius:9px;padding:8px 11px;background:var(--surface);font-size:14px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}
.chip{border:1px solid var(--line);background:var(--surface);border-radius:99px;padding:2px 10px;font-size:12.5px;color:var(--muted)}
.chip:hover{color:var(--text);border-color:var(--line-strong)}
.actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.err{color:var(--bad);font-size:13.5px;font-weight:500}
.actions .sp{flex:1}
.link{border:0;background:none;color:var(--muted);font-size:13px;text-decoration:underline}
dialog{border:1px solid var(--line);border-radius:14px;padding:0;max-width:600px;width:calc(100% - 32px);background:var(--surface);color:var(--text)}
dialog::backdrop{background:rgba(10,15,25,.45)}
.dlg{padding:20px 22px}
.dlg h2{margin:0 0 12px;font-size:18px}
.dlg ol{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:8px;font-size:14.5px}
.dlg p{font-size:14px;color:var(--muted)}
kbd{display:inline-block;padding:0 6px;border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:5px;background:var(--sunken);font:12px ui-monospace,Consolas,monospace}
.dlg .row{display:flex;justify-content:flex-end;margin-top:16px}
#results{padding:16px 20px;display:none}#results.show{display:block}
#results summary{cursor:pointer;font-weight:650}
.res-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}th{font-size:12px;color:var(--muted);font-weight:600}
caption{text-align:left;font-weight:600;padding-bottom:4px}
@media (max-width:960px){.layout{grid-template-columns:1fr}.side{position:static;max-height:none}#list{max-height:320px}.compare{grid-template-columns:1fr}}
@media (max-width:600px){.top-in,.layout{padding-left:16px;padding-right:16px}.qcard,.resp,.decide{padding:14px 16px}.qcard h1{font-size:17px}.bar{display:none}}
</style></head>
<body>
<header class="top"><div class="top-in">
  <div class="brand">Bugzilla evaluation results</div>
  <div class="prog"><b id="progTxt"></b><div class="bar"><i id="progBar"></i></div></div>
  <div class="tools">
    <label class="initials"><input id="me" maxlength="8" placeholder="Initials" aria-label="Your initials" autocomplete="off"></label>
    <button class="btn primary" id="export">Download CSV</button>
    <div class="menu" id="more"><button class="btn" id="moreBtn" aria-haspopup="true">More ▾</button>
      <div class="menu-pop" role="menu">
        <button id="helpBtn">How to review</button>
        <button id="import">Load a saved review CSV</button>
        <input type="file" id="upload" accept=".csv" hidden>
        <hr>
        <label><input type="checkbox" id="unblind"><span>Show method names and scores<small>Leave off while reviewing so you are not biased.</small></span></label>
        <button id="themeBtn">Switch light / dark</button>
      </div></div>
  </div>
</div></header>

<dialog id="help"><div class="dlg">
  <h2>How to review</h2>
  <ol>
    <li>Pick <b>Needs human review</b> on the left. These are answers the computer could not grade (time questions and explanations).</li>
    <li>Compare <b>Method answer</b> with the <b>Correct answer</b>. For hours, a difference of up to 1 hour still counts as correct.</li>
    <li>Open <b>Evidence given to the method</b> and decide whether those snippets back up the answer. Choose <b>Not applicable</b> only when the method gave no answer.</li>
    <li>Add a short note and click <b>Save and next</b>.</li>
    <li>Then do <b>Needs evidence check</b>. These were already graded automatically; you only judge the evidence.</li>
    <li>When finished, click <b>Download CSV</b> and run <kbd>scripts\phases\run_phase11_evaluation.ps1 --import-review PATH_TO_CSV</kbd> to update the official scores.</li>
  </ol>
  <p>Shortcuts: <kbd>Y</kbd> correct, <kbd>X</kbd> incorrect, <kbd>S</kbd> supported, <kbd>U</kbd> unsupported, <kbd>C</kbd> unclear, <kbd>N</kbd> not applicable, <kbd>Ctrl</kbd>+<kbd>Enter</kbd> save, <kbd>J</kbd>/<kbd>K</kbd> next or previous response.</p>
  <p>Your decisions are saved in this browser as you go. Download the CSV to keep a copy.</p>
  <div class="row"><button class="btn primary" id="helpClose">Got it</button></div>
</div></dialog>

<div class="layout">
  <aside class="side">
    <div class="side-head">
      <div class="sgroup" id="sg1"><div class="h">To review</div></div>
      <div class="sgroup" id="sg2"><div class="h">Graded result</div></div>
      <input class="search" id="search" type="search" placeholder="Search bug ID or words">
      <div class="frow">
        <select id="dataset" aria-label="Collection"><option value="">All collections</option></select>
        <select id="family" aria-label="Question type"><option value="">All question types</option></select>
      </div>
      <select id="method" aria-label="Method" hidden><option value="">All methods</option></select>
    </div>
    <div class="count" id="count"></div>
    <div id="list"></div>
  </aside>
  <main class="main">
    <section class="card" id="results"></section>
    <section class="card qcard" id="qcard"></section>
    <section class="card" id="rcard"></section>
  </main>
</div>
<div id="toast" role="status" aria-live="polite"></div>

<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
const key='bugzilla-review-'+D.id,ABST='Abstained: no factual answer',drafts={};
const S={status:'human',q:'',r:'',unblind:false};
const FAM={F1:'Bug fields',F2:'Time to fix',F3:'Counting bugs',F4:'Linked bugs',F5:'Reasons in comments',F6:'Info not in data',KI:'Find the bug',MH:'Multi-step links',F6H:'Should decline'};
const ST={human:{label:'Needs human review',hint:'The computer could not grade this answer. Decide if it is correct, then check its evidence.'},
  evidence:{label:'Needs evidence check',hint:'The answer was already graded automatically. Only decide whether the evidence supports it.'},
  reviewed:{label:'Review decisions',hint:'You can change your decision and save again.'},
  correct:{label:'Correct'},incorrect:{label:'Incorrect'},ungraded:{label:'Not graded yet'},all:{label:'All responses'}};
let storageOK=true;
function load(k,d){try{const v=localStorage.getItem(k);return v===null?d:v}catch(e){storageOK=false;return d}}
function put(k,v){try{localStorage.setItem(k,v)}catch(e){storageOK=false}}
try{Object.assign(drafts,JSON.parse(load(key,'{}')))}catch(e){}
function store(){put(key,JSON.stringify(drafts));if(!storageOK)toast('This browser cannot keep drafts. Download the CSV before closing the page.',true)}

function el(tag,text,cls,attrs){const n=document.createElement(tag);if(text!==undefined&&text!==null)n.textContent=text;if(cls)n.className=cls;if(attrs)for(const k in attrs)n.setAttribute(k,attrs[k]);return n}
function edit(r){return {...Object.fromEntries(D.editable.map(k=>[k,r[k]||''])),...(drafts[r.review_id]||{})}}
function pending(r){const d=edit(r);return (r.needs_answer&&!d.answer_verdict)||(r.needs_evidence&&!d.grounding_verdict)}
function abst(r){return r.model_answer===ABST}
/* one review status per response */
function rstate(r){if(r.needs_evidence&&pending(r))return r.needs_answer?'human':'evidence';if(r.needs_evidence)return 'reviewed';return 'done'}
/* graded result: your decision if you made one, otherwise the automatic grade */
function result(r){const d=edit(r);if(d.answer_verdict)return d.answer_verdict==='CORRECT'?'correct':'incorrect';if(r.current_result.startsWith('Correct'))return 'correct';if(r.current_result.startsWith('Wrong'))return 'incorrect';return 'ungraded'}
function pillKey(r){const s=rstate(r);return s==='done'?result(r):s}
function pillLabel(r){const k=pillKey(r);if(k==='correct'||k==='incorrect'){const d=edit(r);return ST[k].label+(d.answer_verdict?' (your grade)':' (auto-graded)')}return ST[k].label}
function safe(v){v=String(v??'');return /^[=+\-@\t\r]/.test(v)?"'"+v:v}
function rowCSV(r){const e=edit(r);return D.fields.map(k=>safe(D.editable.includes(k)?e[k]:r[k]))}
function valid(r,d){if(d.answer_verdict&&!['CORRECT','INCORRECT'].includes(d.answer_verdict))return 'Choose Correct or Incorrect.';if(d.answer_verdict&&!r.needs_answer)return 'This response only needs an evidence check.';if(d.grounding_verdict&&!['SUPPORTED','UNSUPPORTED','UNCLEAR','NOT_APPLICABLE'].includes(d.grounding_verdict))return 'Choose an evidence decision.';if(d.grounding_verdict==='NOT_APPLICABLE'&&r.model_answer!==ABST)return '"Not applicable" is only for responses that gave no answer.';if((d.answer_verdict||d.grounding_verdict)&&(!d.reviewer.trim()||!d.note.trim()))return 'Add your initials and a short note.';return ''}
let toastT;function toast(msg,err){const t=$('toast');t.textContent=msg;t.className='show'+(err?' error':'');clearTimeout(toastT);toastT=setTimeout(()=>t.className=err?'error':'',err?6000:2400)}
function shortHash(s){return s.replace(/\b[0-9a-f]{32,}\b/g,m=>m.slice(0,8)+'…')}
const BOILER=[/^Use the specified broad metadata archive and verified event overlay; snapshot date is unknown\.\s*/i,/^Use the seed-317 Firefox sample dev partition of [\d,]+ distinct bugs; year means filing year\.\s*/i,/^Using the specified frozen evidence,\s*/i];
function headline(q){let t=q;for(const re of BOILER){const m=t.match(re);if(m)t=t.slice(m[0].length)}const qi=t.indexOf('?');let head=qi>0?t.slice(0,qi+1):t.split(/(?<=\.)\s+/)[0];return shortHash(head.charAt(0).toUpperCase()+head.slice(1))}
function bugIds(text){return [...new Set((String(text).match(/\b1[5-9]\d{5}\b/g)||[]))]}
function highlight(parent,text,terms){terms=terms.filter(t=>t&&t.length>=3).sort((a,b)=>b.length-a.length);text=String(text);if(!terms.length){parent.append(text);return}
  const re=new RegExp('('+terms.map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')','gi');let last=0,m;
  while((m=re.exec(text))){if(m.index>last)parent.append(text.slice(last,m.index));parent.append(el('mark',m[0]));last=m.index+m[0].length}
  if(last<text.length)parent.append(text.slice(last))}
function snippets(text){const s=String(text||'');if(!/\[C\d+\]/.test(s))return null;return s.split(/\n?(?=\[C\d+\]\s)/).filter(x=>x.trim()).map(p=>p.replace(/^\[C\d+\]\s*(chunk_id=\S+)?\s*\n?/,'').trim())}
function num(v){const m=String(v).replace(/,/g,'').match(/-?\d+(?:\.\d+)?/);return m?parseFloat(m[0]):null}
function refText(g){return String(g.reference).replace(/ hours \(tolerance: 1 hour\)$/,' hours')}

/* questions */
const groups=new Map();
for(const r of D.rows){const k=r.dataset+'|'+r.question_id;if(!groups.has(k))groups.set(k,{key:k,dataset:r.dataset,family:r.family,question:r.question,reference:r.reference_answer,refEvidence:r.reference_evidence,scope:r.scope,rows:[],head:headline(r.question)});groups.get(k).rows.push(r)}
for(const g of groups.values()){g.rows.sort((a,b)=>a.review_id<b.review_id?-1:1);g.rows.forEach((r,i)=>r._n=i+1);g.ids=bugIds(g.question)}
const famOrder=['F1','F2','F3','F4','F5','F6','KI','MH','F6H'];
const allGroups=[...groups.values()].sort((a,b)=>a.dataset.localeCompare(b.dataset)||famOrder.indexOf(a.family)-famOrder.indexOf(b.family)||a.head.localeCompare(b.head));
function inStatus(r,s){if(s==='all')return true;if(s==='human'||s==='evidence'||s==='reviewed')return rstate(r)===s;return result(r)===s}
function rowMatches(r){if(!inStatus(r,S.status))return false;if(S.unblind&&$('method').value&&r.method!==$('method').value)return false;return true}
function baseMatch(g){if($('dataset').value&&g.dataset!==$('dataset').value)return false;if($('family').value&&g.family!==$('family').value)return false;const q=$('search').value.trim().toLowerCase();return !q||(g.question+' '+g.reference+' '+g.rows.map(r=>r.model_answer).join(' ')).toLowerCase().includes(q)}
function visibleGroups(){return allGroups.filter(g=>baseMatch(g)&&g.rows.some(rowMatches))}
function label(r){return S.unblind?r.method:'Response '+r._n}

function renderSide(){const base=allGroups.filter(baseMatch).flatMap(g=>g.rows).filter(r=>!S.unblind||!$('method').value||r.method===$('method').value);
  for(const [id,keys] of [['sg1',['human','evidence','reviewed']],['sg2',['correct','incorrect','ungraded','all']]]){const box=$(id);box.replaceChildren(box.firstChild);
    for(const k of keys){const n=base.filter(r=>inStatus(r,k)).length;if(k==='ungraded'&&!n)continue;const b=el('button',null,'sopt'+(S.status===k?' on':''));b.append(el('i',null,'d-'+(k==='ungraded'?'all':k)),el('span',ST[k].label),el('em',String(n)));b.onclick=()=>{S.status=k;S.r='';put('bugzilla-status',k);renderAll()};box.append(b)}}}
function renderTop(){const need=D.rows.filter(r=>r.needs_evidence),done=need.filter(r=>!pending(r)).length;$('progTxt').textContent=done+' of '+need.length+' reviews done';$('progBar').style.width=(need.length?100*done/need.length:100)+'%'}
function renderList(){const vis=visibleGroups(),list=$('list');list.replaceChildren();const nr=vis.reduce((n,g)=>n+g.rows.filter(rowMatches).length,0);
  $('count').textContent=nr+' response'+(nr===1?'':'s')+' in '+vis.length+' question'+(vis.length===1?'':'s');
  if(!vis.length){list.append(el('div',(S.status==='human'||S.status==='evidence')?'Nothing left here. Nice work.':'No responses match.','empty'));return vis}
  for(const g of vis){const b=el('button',null,'q'+(g.key===S.q?' on':'')),m=el('div',null,'q-main');m.append(el('div',g.head,'q-title'),el('div',g.dataset+' · '+(FAM[g.family]||g.family),'q-sub'));
    b.append(m,el('span',String(g.rows.filter(rowMatches).length),'q-n',{title:'responses in this view'}));b.onclick=()=>{S.q=g.key;S.r='';renderAll();window.scrollTo({top:0,behavior:'smooth'})};list.append(b)}
  return vis}
function renderQuestion(g,vis){const c=$('qcard');c.replaceChildren();const top=el('div',null,'qcard-top');top.append(el('span',g.dataset+' · '+(FAM[g.family]||g.family)+' ('+g.family+')'),el('span',null,'sp'));
  const i=vis.indexOf(g),p=el('button','‹ Previous','btn small'),n=el('button','Next question ›','btn small');p.disabled=i<=0;n.disabled=i<0||i>=vis.length-1;
  p.onclick=()=>{S.q=vis[i-1].key;S.r='';renderAll()};n.onclick=()=>{S.q=vis[i+1].key;S.r='';renderAll()};top.append(p,n);
  const h=el('h1');highlight(h,g.head,g.ids);const w=el('details',null,'wording');w.append(el('summary','Full question wording'),el('div',g.question));c.append(top,h,w)}
function fold(title,sub,open){const d=el('details',null,'fold');d.open=!!open;const s=el('summary',title);if(sub)s.append(el('small',sub));const b=el('div',null,'fold-body');d.append(s,b);return [d,b]}
function renderResponse(g){const c=$('rcard');c.replaceChildren();const rows=g.rows.filter(rowMatches);if(!rows.length)return;
  let r=rows.find(x=>x.review_id===S.r)||rows[0];S.r=r.review_id;
  if(rows.length>1){const tabs=el('div',null,'tabs');for(const x of rows){const t=el('button',null,'tab'+(x===r?' on':''));t.append(el('i',null,'d-'+pillKey(x)),label(x));t.title=pillLabel(x);t.onclick=()=>{S.r=x.review_id;renderAll()};tabs.append(t)}c.append(tabs)}
  const body=el('div',null,'resp'),head=el('div',null,'rhead'),k=pillKey(r),pill=el('span',null,'pill p-'+k);pill.append(el('i'),pillLabel(r));
  head.append(el('h2',label(r)),pill,el('span',null,'sp'));
  const i=rows.indexOf(r);if(rows.length>1){const pv=el('button','‹','btn small',{title:'Previous response (K)'}),nx=el('button','›','btn small',{title:'Next response (J)'});pv.disabled=i===0;nx.disabled=i===rows.length-1;pv.onclick=()=>step(-1);nx.onclick=()=>step(1);head.append(pv,nx)}
  body.append(head);if(ST[k].hint)body.append(el('p',ST[k].hint,'instr'));
  const cmp=el('div',null,'compare'),ma=el('div',null,'ans'),ra=el('div',null,'ans ref');
  ma.append(el('div','Method answer','lab'),el('div',abst(r)?'No answer (the method declined)':r.model_answer,'val'+(abst(r)?' abst':'')));
  ra.append(el('div','Correct answer','lab'),el('div',refText(g)=== 'ABSTAIN'?'Should decline: the data cannot answer this':refText(g),'val'));cmp.append(ma,ra);body.append(cmp);
  if(/hours \(tolerance/.test(g.reference)&&!abst(r)){const a=num(r.model_answer),b=num(g.reference);if(a!==null&&b!==null){const diff=Math.abs(a-b),ok=diff<=1;body.append(el('div',ok?'✓ The two numbers are '+(diff<0.01?'under 0.01':diff.toFixed(2))+' hours apart, within the 1 hour allowance.':'The two numbers are '+diff.toFixed(2)+' hours apart, more than the 1 hour allowance. Check whether the method used other units.','hint '+(ok?'good':'bad')))}}
  if(r.model_explanation){const w=el('div',null,'why');w.append(el('b','Method’s reasoning: '));highlight(w,r.model_explanation,g.ids);body.append(w)}
  const terms=[...g.ids],ref=refText(g).replace(/ hours$/,'');if(ref.length>=3&&ref.length<=40&&ref!=='ABSTAIN')terms.push(ref);
  const sn=snippets(r.model_evidence);const [ev,evb]=fold('Evidence given to the method',sn?sn.length+' text snippet'+(sn.length===1?'':'s')+' it could read':(r.model_evidence.startsWith('No evidence')?'none':''),rstate(r)!=='done');
  if(sn)sn.forEach((t,j)=>{const s=el('div',null,'snip'),d=el('div');highlight(d,t,terms);s.append(el('b','Snippet '+(j+1)),d);evb.append(s)});else{const d=el('div',null,'prose');highlight(d,r.model_evidence,terms);evb.append(d)}
  body.append(ev);
  const [more,mb]=fold('Where the correct answer comes from','',false);mb.append(el('div','Source of the correct answer','sub-h'),el('div',r.reference_evidence,'prose'),el('div','Question scope','sub-h'),el('div',g.scope,'prose'));body.append(more);
  c.append(body);if(r.needs_evidence)c.append(decision(r))}
let cur=null;
function decision(r){const d=edit(r);if(!d.reviewer)d.reviewer=$('me').value.trim();const wrap=el('div',null,'decide');cur={r,d,wrap};
  function group(title,name,opts){const q=el('div');q.append(el('div',title,'qlab'));const ch=el('div',null,'choices');
    for(const [v,t,cls,dis] of opts){const b=el('button',t,'choice '+cls+(d[name]===v?' on':''));b.disabled=!!dis;b.dataset.name=name;b.dataset.v=v;b.onclick=()=>{d[name]=d[name]===v?'':v;refresh()};ch.append(b)}q.append(ch);return q}
  if(r.needs_answer)wrap.append(group(r.family==='F5'?'1. Does the answer state the same reason as the correct answer?':r.family==='F2'?'1. Is the answer correct (within 1 hour)?':'1. Is the answer correct?','answer_verdict',[['CORRECT','Correct','c-good'],['INCORRECT','Incorrect','c-bad']]));
  wrap.append(group((r.needs_answer?'2. ':'')+'Do the evidence snippets support this answer?','grounding_verdict',[['SUPPORTED','Supported','c-good'],['UNSUPPORTED','Not supported','c-bad'],['UNCLEAR','Unclear','c-mid'],['NOT_APPLICABLE','Not applicable (no answer given)','c-na',!abst(r)]]));
  const nq=el('div');nq.append(el('div',(r.needs_answer?'3. ':'')+'Short note','qlab'));const chips=el('div',null,'chips'),ta=el('textarea',null,null,{placeholder:'What did you check?'});ta.value=d.note;ta.oninput=()=>{d.note=ta.value};
  for(const t of abst(r)?['Gave no answer','Answer was in the evidence']:['Snippet shows the value','Matches the correct answer','Not in the snippets']){const b=el('button',t,'chip');b.onclick=()=>{ta.value=(ta.value.trim()?ta.value.trim()+'; ':'')+t;d.note=ta.value};chips.append(b)}
  nq.append(chips,ta);wrap.append(nq);
  const act=el('div',null,'actions'),err=el('span','','err'),save=el('button','Save and next','btn primary');save.onclick=commit;act.append(save,err,el('span',null,'sp'));
  if(drafts[r.review_id]){const cl=el('button','Undo my decision','link');cl.onclick=()=>{delete drafts[r.review_id];store();renderAll();toast('Decision removed')};act.append(cl)}
  wrap.append(act);cur.err=err;
  function refresh(){for(const b of wrap.querySelectorAll('.choice'))b.classList.toggle('on',d[b.dataset.name]===b.dataset.v);err.textContent=''}
  return wrap}
function commit(){if(!cur)return;const {r,d}=cur;d.reviewer=(d.reviewer||$('me').value).trim().toUpperCase();
  if(!d.reviewer){cur.err.textContent='Type your initials in the box at the top first.';$('me').classList.add('missing');$('me').focus();return}
  if(r.needs_answer&&!d.answer_verdict){cur.err.textContent='Choose Correct or Incorrect.';return}
  if(!d.grounding_verdict){cur.err.textContent='Choose an evidence answer.';return}
  const decision=Object.fromEntries(D.editable.map(k=>[k,String(d[k]||'').trim()]));const e=valid(r,decision);if(e){cur.err.textContent=e;return}
  const g=groups.get(S.q),before=g.rows.filter(rowMatches),idx=before.indexOf(r);
  drafts[r.review_id]=decision;store();toast('Saved');
  const after=g.rows.filter(rowMatches);let nextR=after.find((x,j)=>before.indexOf(x)>idx)||null;
  if(nextR){S.r=nextR.review_id}else{const vis=visibleGroups(),gi=allGroups.indexOf(g);const ng=allGroups.slice(gi+1).concat(allGroups.slice(0,gi+1)).find(x=>vis.includes(x));S.q=ng?ng.key:'';S.r=''}
  renderAll();const rc=$('qcard');if(rc.getBoundingClientRect().top<64)window.scrollTo({top:window.scrollY+rc.getBoundingClientRect().top-76,behavior:'smooth'})}
function step(dx){const g=groups.get(S.q);if(!g)return;const rows=g.rows.filter(rowMatches),i=rows.findIndex(x=>x.review_id===S.r),j=i+dx;if(j>=0&&j<rows.length){S.r=rows[j].review_id;renderAll()}}
function renderResults(){const box=$('results');box.replaceChildren();box.classList.toggle('show',S.unblind);if(!S.unblind)return;const d=el('details');d.open=true;d.append(el('summary','Saved scores by method'));
  const p=el('p','Official saved scores. Your decisions here count only after you import the CSV.');p.style.cssText='margin:6px 0 0;font-size:13px;color:var(--muted)';d.append(p);
  const grid=el('div',null,'res-grid');for(const col of D.summaries){const t=el('table');t.append(el('caption',col.dataset+' · '+col.questions+' questions'));const hr=el('tr');for(const h of ['Method','Correct','Incorrect','Needs review','Accuracy'])hr.append(el('th',h));t.append(hr);
    for(const row of col.comparison){const tr=el('tr');for(const v of [row.system_id,row.correct,col.questions-row.correct-row.needs_human,row.needs_human,row.macro_accuracy==null?'–':(100*row.macro_accuracy).toFixed(1)+'%'])tr.append(el('td',String(v)));t.append(tr)}grid.append(t)}
  d.append(grid);box.append(d)}
function renderAll(){renderTop();renderSide();renderResults();const vis=renderList();let g=groups.get(S.q);if(!g||!vis.includes(g)){g=vis[0]||null;S.q=g?g.key:'';S.r=''}
  cur=null;if(!g){$('qcard').replaceChildren(el('div',ST[S.status]&&(S.status==='human'||S.status==='evidence')?'Nothing left in “'+ST[S.status].label+'”. Pick another category on the left.':'No responses match. Pick another category or clear the filters.','empty'));$('rcard').replaceChildren();$('rcard').hidden=true;return}
  $('rcard').hidden=false;renderQuestion(g,vis);renderResponse(g);const on=$('list').querySelector('.q.on');if(on)on.scrollIntoView({block:'nearest'})}

for(const d of [...new Set(D.rows.map(r=>r.dataset))].sort()){const o=el('option',d);o.value=d;$('dataset').append(o)}
for(const f of famOrder.filter(f=>D.rows.some(r=>r.family===f)).concat([...new Set(D.rows.map(r=>r.family))].filter(f=>!famOrder.includes(f)))){const o=el('option',(FAM[f]||f)+' ('+f+')');o.value=f;$('family').append(o)}
for(const id of ['dataset','family','method','search'])$(id).addEventListener('input',()=>{S.r='';renderAll()});
S.status=load('bugzilla-status','human');if(!ST[S.status])S.status='human';
$('me').value=load('bugzilla-reviewer','');$('me').addEventListener('input',()=>{$('me').classList.remove('missing');put('bugzilla-reviewer',$('me').value.trim().toUpperCase());if(cur&&!drafts[cur.r.review_id])cur.d.reviewer=$('me').value.trim()});
$('me').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key==='Escape')$('me').blur()});
$('moreBtn').onclick=e=>{e.stopPropagation();$('more').classList.toggle('open')};document.addEventListener('click',e=>{if(!$('more').contains(e.target))$('more').classList.remove('open')});
$('unblind').onchange=()=>{S.unblind=$('unblind').checked;const m=$('method');m.hidden=!S.unblind;m.replaceChildren(el('option','All methods'));m.firstChild.value='';if(S.unblind)for(const x of [...new Set(D.rows.map(r=>r.method))].sort()){const o=el('option',x);o.value=x;m.append(o)}renderAll()};
$('themeBtn').onclick=()=>{const r=document.documentElement,dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;r.dataset.theme=dark?'light':'dark';put('bugzilla-theme',r.dataset.theme)};
{const t=load('bugzilla-theme','');if(t)document.documentElement.dataset.theme=t}
function openHelp(){$('more').classList.remove('open');if($('help').showModal)$('help').showModal()}
$('helpBtn').onclick=openHelp;$('helpClose').onclick=()=>{$('help').close();put('bugzilla-help-seen','1')};
document.addEventListener('keydown',e=>{const tag=(e.target.tagName||'').toLowerCase(),typing=['textarea','input','select'].includes(tag);
  if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();commit();return}
  if(typing||e.ctrlKey||e.metaKey||e.altKey||$('help').open)return;const k=e.key.toLowerCase();
  if(k==='j'){step(1);e.preventDefault()}else if(k==='k'){step(-1);e.preventDefault()}
  else if(cur){const map={y:['answer_verdict','CORRECT'],x:['answer_verdict','INCORRECT'],s:['grounding_verdict','SUPPORTED'],u:['grounding_verdict','UNSUPPORTED'],c:['grounding_verdict','UNCLEAR'],n:['grounding_verdict','NOT_APPLICABLE']}[k];
    if(map){const b=cur.wrap.querySelector('.choice[data-name="'+map[0]+'"][data-v="'+map[1]+'"]');if(b&&!b.disabled){b.click();e.preventDefault()}}}});

$('export').onclick=()=>{for(const r of D.rows.filter(r=>r.needs_evidence)){const e=valid(r,edit(r));if(e){const g=[...groups.values()].find(g=>g.rows.includes(r));S.q=g.key;S.r=r.review_id;S.status='all';renderAll();toast('Fix this response before downloading: '+e,true);return}}
  const quote=v=>'"'+String(v).replaceAll('"','""')+'"',text='﻿'+[D.fields,...D.rows.filter(r=>r.needs_evidence).map(rowCSV)].map(row=>row.map(quote).join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'})),a=el('a');a.href=url;a.download='REVIEW_completed.csv';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  toast('CSV downloaded. Run the import command to update the official scores.')};
function parseCSV(text){const out=[];let row=[],cell='',quoted=false;for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++}else quoted=!quoted}else if(c===','&&!quoted){row.push(cell);cell=''}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);if(row.some(x=>x!==''))out.push(row);row=[];cell=''}else cell+=c}if(quoted)throw Error('CSV contains an unclosed quote.');if(cell||row.length){row.push(cell);out.push(row)}return out}
$('import').onclick=()=>{$('more').classList.remove('open');$('upload').click()};
$('upload').onchange=async()=>{try{const parsed=parseCSV((await $('upload').files[0].text()).replace(/^﻿/,'')),header=parsed.shift();if(JSON.stringify(header)!==JSON.stringify(D.fields))throw Error('Use the CSV downloaded from this page.');const staged={},seen=new Set();
  for(const cells of parsed){if(cells.length!==header.length)throw Error('CSV column count changed.');const row=Object.fromEntries(header.map((k,i)=>[k,cells[i]])),r=D.rows.find(x=>x.review_id===row.review_id&&x.needs_evidence);if(!r||seen.has(r.review_id))throw Error('Unknown or duplicate response ID.');seen.add(r.review_id);
    const expected=rowCSV({...r,...Object.fromEntries(D.editable.map(k=>[k,'']))});for(let i=0;i<header.length;i++)if(!D.editable.includes(header[i])&&header[i]!=='current_result'&&cells[i]!==expected[i])throw Error('A fixed question or answer field was changed.');
    const decision=Object.fromEntries(D.editable.map(k=>[k,row[k].trim()]));const error=valid(r,decision);if(error)throw Error(error);staged[r.review_id]={...edit(r),...Object.fromEntries(Object.entries(decision).filter(([k,v])=>v))}}
  Object.assign(drafts,staged);store();renderAll();toast('Loaded '+Object.keys(staged).length+' rows. Official scores change only after the import command.')}catch(e){toast(e.message,true)}finally{$('upload').value=''}};

renderAll();
if(load('bugzilla-help-seen','')!=='1')openHelp();
if(!storageOK)toast('This browser cannot keep drafts. Download the CSV before closing the page.',true);
})();
</script></body></html>
'''

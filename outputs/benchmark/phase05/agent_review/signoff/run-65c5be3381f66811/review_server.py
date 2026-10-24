#!/usr/bin/env python3
"""Local-only review UI backend for existing signoff_queue.csv.

Place this file beside signoff.html and signoff_queue.csv, then run:
    python3 review_server.py
No third-party dependencies. Only review columns can change.
"""
import argparse
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import webbrowser

MUTABLE = {
    'human_review_state', 'human_review_classification', 'decision',
    'reviewer', 'reviewed_at_utc', 'source_checked', 'rationale_present',
    'corrected_gold_json', 'corrected_question', 'note', 'issue_type_observed'
}
DECISIONS = {'APPROVE', 'CORRECT', 'REJECT', 'PENDING'}
LOCK = threading.Lock()


def read_queue(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames
    if not fields or not {'qid','decision','required','family','typed_candidate_gold_json'}.issubset(fields):
        raise ValueError('Unexpected signoff_queue.csv headers')
    if len({r['qid'] for r in rows}) != len(rows):
        raise ValueError('Duplicate question IDs')
    return fields, rows


def update(path, payload):
    with LOCK:
        fields, rows = read_queue(path)
        qid = payload.get('qid')
        row = next((r for r in rows if r['qid'] == qid), None)
        if row is None:
            raise ValueError('Unknown question ID')
        decision = payload.get('decision')
        if decision not in DECISIONS:
            raise ValueError('Unknown decision')
        if row['required'].upper() != 'YES' and decision != 'PENDING':
            raise ValueError('This question is not in the required human queue')
        reviewer = str(payload.get('reviewer','')).strip()
        checked = payload.get('source_checked') is True
        rationale = payload.get('rationale_present') is True
        note = str(payload.get('note','')).strip()
        corrected_question = str(payload.get('corrected_question','')).strip()
        corrected_gold = str(payload.get('corrected_gold_json','')).strip()
        if any(len(v) > 25000 for v in (reviewer, note, corrected_gold, corrected_question)):
            raise ValueError('Text exceeds review size limit')
        if decision != 'PENDING' and not reviewer:
            raise ValueError('Enter your reviewer name first')
        if decision in ('APPROVE', 'CORRECT') and not checked:
            raise ValueError('Check the source evidence before approving or correcting')
        if row['family'] == 'F5' and decision in ('APPROVE', 'CORRECT') and not rationale:
            raise ValueError('F5 requires explicit evidence of the rationale')
        if decision == 'CORRECT':
            if not corrected_gold and not corrected_question:
                raise ValueError('Supply corrected answer or question')
            if corrected_gold:
                try:
                    obj=json.loads(corrected_gold)
                    if not isinstance(obj,dict) or 'type' not in obj:
                        raise ValueError('Corrected gold needs typed JSON')
                except (ValueError,TypeError) as e:
                    raise ValueError('Invalid corrected gold JSON') from e
        if decision == 'REJECT' and not note:
            raise ValueError('Give a short reason for rejecting this question')
        values = {
            'decision': decision,
            'reviewer': reviewer if decision != 'PENDING' else '',
            'reviewed_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z') if decision != 'PENDING' else '',
            'source_checked': 'YES' if checked and decision != 'PENDING' else ('NO' if decision != 'PENDING' else ''),
            'rationale_present': ('YES' if rationale else 'NO') if row['family'] == 'F5' and decision != 'PENDING' else '',
            'corrected_gold_json': corrected_gold if decision == 'CORRECT' else '',
            'corrected_question': corrected_question if decision == 'CORRECT' else '',
            'note': note if decision != 'PENDING' else '',
            'human_review_state': ('HUMAN_REVIEWED' if decision != 'PENDING' else 'PENDING_NOT_HUMAN_VERIFIED'),
            'human_review_classification': ('HUMAN_VERIFIED' if decision in ('APPROVE','CORRECT') else 'HUMAN_REJECTED') if decision != 'PENDING' else 'PENDING',
        }
        for k,v in values.items():
            if k not in MUTABLE or k not in fields:
                raise ValueError(f'Unexpected writable field: {k}')
            row[k]=v
        # A complete original copy is preserved before the first update.
        backup=path.with_name('signoff_queue.before_review.csv')
        if not backup.exists():
            shutil.copy2(path, backup)
        fd,tmp=tempfile.mkstemp(prefix='.signoff-',suffix='.csv',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\r\n')
                writer.writeheader(); writer.writerows(rows)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        return row, sum(r['required'].upper()=='YES' and r['decision']!='PENDING' for r in rows), sum(r['required'].upper()=='YES' for r in rows)


def make_handler(folder):
    html_path=folder/'signoff.html'
    csv_path=folder/'signoff_queue.csv'
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,obj):
            b=json.dumps(obj,ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(b)))
            self.end_headers();self.wfile.write(b)
        def do_GET(self):
            if self.path in ('/','/signoff.html'):
                data=html_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
            elif self.path == '/api/queue':
                try:
                    fields,rows=read_queue(csv_path)
                    self.reply(200,{'fields':fields,'rows':rows})
                except Exception as e:
                    self.reply(500,{'error':str(e)})
            else:
                self.reply(404,{'error':'Not found'})
        def do_POST(self):
            if self.path != '/api/review':
                return self.reply(404,{'error':'Not found'})
            origin=self.headers.get('Origin','')
            host=self.headers.get('Host','')
            if origin and origin not in (f'http://{host}',f'https://{host}'):
                return self.reply(403,{'error':'Unexpected browser origin'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>150000:
                    raise ValueError('Invalid request size')
                body=json.loads(self.rfile.read(size))
                row,done,total=update(csv_path,body)
                self.reply(200,{'ok':True,'row':row,'reviewed':done,'required':total})
            except (ValueError, json.JSONDecodeError) as e:
                self.reply(400,{'error':str(e)})
            except Exception as e:
                self.reply(500,{'error':str(e)})
        def log_message(self,fmt,*args):
            if not (self.path.startswith('/api/queue')):
                super().log_message(fmt,*args)
    return Handler


def main():
    ap=argparse.ArgumentParser(description='Local Phase 5 reviewer; edits signoff_queue.csv directly')
    ap.add_argument('--port',type=int,default=8765)
    ap.add_argument('--no-browser',action='store_true')
    ap.add_argument('--check',action='store_true',help='Print review progress and verify immutable columns against backup')
    args=ap.parse_args()
    folder=Path(__file__).resolve().parent
    for name in ('signoff.html','signoff_queue.csv'):
        if not (folder/name).is_file():
            ap.error(f'{name} must be beside review_server.py')
    fields, rows = read_queue(folder/'signoff_queue.csv')
    if args.check:
        required=[r for r in rows if r['required'].upper()=='YES']
        remaining=[r for r in required if r['decision']=='PENDING']
        from collections import Counter
        print(f'Questions: {len(rows)} | Required: {len(required)} | Remaining: {len(remaining)}')
        print('Required decisions:',dict(Counter(r['decision'] for r in required)))
        backup=folder/'signoff_queue.before_review.csv'
        if backup.exists():
            old_fields, old_rows=read_queue(backup)
            if fields != old_fields or len(rows)!=len(old_rows):
                raise SystemExit('ERROR: CSV header or row count changed')
            immutable=[f for f in fields if f not in MUTABLE]
            differences=[(i+2,k) for i,(a,b) in enumerate(zip(old_rows,rows)) for k in immutable if a[k]!=b[k]]
            if differences:
                raise SystemExit(f'ERROR: Immutable source fields changed! Examples: {differences[:5]}')
            print('Immutable original question/evidence/hash fields: unchanged')
        else:
            print('No pre-review backup found yet; cross-file integrity not verified')
        bad=[]
        for r in required:
            if r['decision'] in ('APPROVE','CORRECT') and (not r['reviewer'] or r['source_checked']!='YES' or (r['family']=='F5' and r['rationale_present']!='YES')):
                bad.append(r['qid'])
        if bad:raise SystemExit(f'ERROR: Approved/corrected reviews missing confirmation: {bad[:5]}')
        print('Review-field consistency: passed')
        if remaining: print('Review not complete; finish required rows before freezing.')
        else: print('Required decisions complete. Next: Codex validator compatibility and benchmark freeze.')
        return
    server=HTTPServer(('127.0.0.1',args.port),make_handler(folder))
    url=f'http://127.0.0.1:{server.server_port}/'
    print(f'\nReview interface: {url}\nCSV updated after each button click. Ctrl+C to stop.\n',flush=True)
    if not args.no_browser:
        threading.Timer(.7,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Local-only human review of an existing natural_review.csv."""
import argparse
import csv
import html
import io
import os
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs


def serve(path, port):
    path=Path(path).resolve()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with path.open(newline='',encoding='utf-8') as f:
                reader=csv.DictReader(f);rows=list(reader)
            pending=next(((i,r) for i,r in enumerate(rows) if r['decision']=='PENDING'),None)
            if not pending: body='<h1>No pending reviews</h1>'
            else:
                i,r=pending; esc=html.escape
                choices=('SEMANTICALLY_EQUIVALENT','CONTEXT_DEPENDENT','AMBIGUOUS_NEEDS_CLARIFICATION','INVALID')
                options=''.join('<option%s>%s</option>'%(' selected' if c==r.get('classification') else '',c) for c in choices)
                body=('<h1>Question wording review</h1><p>Remaining: %d</p><h2>Original</h2><p>%s</p><h2>Proposed</h2><p>%s</p><h3>Shared context</h3><p>%s</p>'
                      '<form method="post"><input type="hidden" name="index" value="%d"><label>Your name <input name="reviewer" required></label><p>'
                      '<select name="classification">%s</select></p>'
                      '<button name="decision" value="APPROVE">Approve</button> <button name="decision" value="REJECT">Reject</button></form>'
                      % (sum(x['decision']=='PENDING' for x in rows),esc(r['original']),esc(r['proposed_question']),esc(r['shared_context']),i,options))
            data=('<!doctype html><meta charset="utf-8">'+body).encode();self.send_response(200);self.end_headers();self.wfile.write(data)
        def do_POST(self):
            size=int(self.headers.get('Content-Length','0'))
            if size>4096: self.send_error(413);return
            data=parse_qs(self.rfile.read(size).decode())
            try:
                with path.open(newline='',encoding='utf-8') as f:
                    reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
                i=int(data['index'][0]); reviewer=data['reviewer'][0].strip();decision=data['decision'][0];classification=data['classification'][0]
                if i<0 or i>=len(rows) or rows[i]['decision']!='PENDING' or not reviewer or decision not in ('APPROVE','REJECT') or classification not in ('SEMANTICALLY_EQUIVALENT','CONTEXT_DEPENDENT','AMBIGUOUS_NEEDS_CLARIFICATION','INVALID'):
                    raise ValueError('invalid review')
                if decision=='APPROVE' and classification=='INVALID': raise ValueError('invalid wording cannot be approved')
                rows[i].update(decision=decision,reviewer=reviewer,classification=classification,reviewed_at_utc=datetime.now(timezone.utc).isoformat())
                fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix='.review-',text=True)
                with os.fdopen(fd,'w',newline='',encoding='utf-8') as f:
                    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
                os.replace(tmp,path)
            except (ValueError,KeyError,UnicodeError): self.send_error(400);return
            self.send_response(303);self.send_header('Location','/');self.end_headers()
        def log_message(self,fmt,*args): pass
    HTTPServer(('127.0.0.1',port),Handler).serve_forever()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('csv');p.add_argument('--port',type=int,default=8766)
    args=p.parse_args();serve(args.csv,args.port)

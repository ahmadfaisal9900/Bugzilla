#!/usr/bin/env python3
"""Review explicitly selected natural-language variants on localhost."""
import argparse
import csv
import html
import os
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

CHOICES = ('SEMANTICALLY_EQUIVALENT', 'CONTEXT_DEPENDENT',
           'AMBIGUOUS_NEEDS_CLARIFICATION', 'INVALID')
PAGE_SIZE = 20


def read_queue(path):
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def serve(path, port):
    path = Path(path).resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            _, rows = read_queue(path)
            pending = [(i, row) for i, row in enumerate(rows) if row['decision'] == 'PENDING']
            try:
                page = max(0, int(parse_qs(urlsplit(self.path).query).get('page', ['0'])[0]))
            except ValueError:
                self.send_error(400); return
            pages = max(1, (len(pending) + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(page, pages - 1)
            selected = pending[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            esc = html.escape
            cards = []
            for i, row in selected:
                options = ''.join('<label><input type="radio" name="classification_%d" value="%s"%s> %s</label>' %
                    (i, c, ' checked' if c == row.get('classification') else '',
                     esc(c.replace('_', ' ').title())) for c in CHOICES)
                cards.append('''<article><label class="check"><input type="checkbox" name="selected" value="{i}">
                    <strong>Select this question</strong></label>
                    <input type="hidden" name="identity_{i}" value="{identity}">
                    <div><b>Original:</b> {original}</div><div><b>Proposed:</b> {proposed}</div>
                    <div><b>Context:</b> {context}</div>
                    <fieldset><legend>Classification</legend><div class="choices">{options}</div></fieldset></article>'''.format(
                        i=i, identity=esc(row['parent_qid'] + ':' + row['variant'], quote=True),
                        original=esc(row['original']), proposed=esc(row['proposed_question']),
                        context=esc(row['shared_context']), options=options))
            navigation = ''
            if page: navigation += '<a href="?page=%d">← Previous</a> ' % (page - 1)
            if page + 1 < pages: navigation += '<a href="?page=%d">Next →</a>' % (page + 1)
            body = '''<!doctype html><html><head><meta charset="utf-8"><title>Question review</title>
              <style>body{{font:16px system-ui;max-width:1050px;margin:2rem auto;padding:0 1rem;color:#172433}}
              article{{border:1px solid #c8d1db;border-radius:8px;padding:1rem;margin:1rem 0;display:grid;gap:.6rem}}
              .bar{{position:sticky;top:0;background:#eef3f8;padding:1rem;z-index:1;border-radius:8px}}
              button,input{{font:inherit}}button{{padding:.45rem .8rem;margin:.2rem}}
              .choices{{display:flex;flex-wrap:wrap;gap:.7rem 1.2rem}}fieldset{{border:1px solid #d4dde5}}
              .check input{{width:1.15rem;height:1.15rem}}a{{margin-right:1rem}}</style></head><body>
              <h1>Question wording review</h1><p>{remaining} pending · Page {page} of {pages} · {reviewed} reviewed</p>
              <p>Read the original, proposed wording and context. Tick only items you have checked.
              The classification is preselected for each item; change it when needed.</p>
              <form method="post"><div class="bar"><label>Your name: <input id="reviewer" name="reviewer" required autocomplete="name"></label>
              <button type="button" id="select-page">Select this page</button>
              <button type="button" id="clear-page">Clear selection</button>
              <div>Set classification for selected:
              <button type="button" class="set-class" data-value="SEMANTICALLY_EQUIVALENT">Equivalent</button>
              <button type="button" class="set-class" data-value="CONTEXT_DEPENDENT">Needs context</button>
              <button type="button" class="set-class" data-value="AMBIGUOUS_NEEDS_CLARIFICATION">Ambiguous</button>
              <button type="button" class="set-class" data-value="INVALID">Invalid</button></div>
              <button name="decision" value="APPROVE">Approve selected</button>
              <button name="decision" value="REJECT">Reject selected</button>
              <span id="count">0 selected</span></div>{cards}</form><nav>{navigation}</nav>
              <script>const nameField=document.getElementById('reviewer');
              try{{nameField.value=localStorage.getItem('naturalReviewReviewer')||'';
              nameField.addEventListener('input',()=>localStorage.setItem('naturalReviewReviewer',nameField.value));}}catch(e){{}}
              const boxes=[...document.querySelectorAll('input[name=selected]')];
              const update=()=>document.getElementById('count').textContent=boxes.filter(x=>x.checked).length+' selected';
              boxes.forEach(x=>x.addEventListener('change',update));
              document.getElementById('select-page').onclick=()=>{{boxes.forEach(x=>x.checked=true);update()}};
              document.getElementById('clear-page').onclick=()=>{{boxes.forEach(x=>x.checked=false);update()}};
              document.querySelectorAll('.set-class').forEach(button=>button.onclick=()=>{{
                const chosen=boxes.filter(x=>x.checked);
                if(!chosen.length){{alert('Select at least one question first.');return;}}
                chosen.forEach(box=>{{const radio=document.querySelector('input[name="classification_'+box.value+'"][value="'+button.dataset.value+'"]');
                  if(radio) radio.checked=true;}});
              }});
              document.querySelector('form').addEventListener('submit',e=>{{if(!boxes.some(x=>x.checked)){{e.preventDefault();alert('Select at least one reviewed question.')}}}});
              </script></body></html>'''.format(remaining=len(pending), page=page+1, pages=pages,
                    reviewed=len(rows)-len(pending), cards=''.join(cards) or '<p>No pending reviews.</p>',
                    navigation=navigation)
            data = body.encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size <= 0 or size > 100000: raise ValueError('invalid request size')
                data = parse_qs(self.rfile.read(size).decode('utf-8'))
                reviewer = data['reviewer'][0].strip()
                decision = data['decision'][0]
                indices = [int(i) for i in data.get('selected', [])]
                if not reviewer or decision not in ('APPROVE', 'REJECT') or not indices or len(indices) > PAGE_SIZE or len(set(indices)) != len(indices):
                    raise ValueError('invalid selection')
                fields, rows = read_queue(path)
                updates = []
                for i in indices:
                    if i < 0 or i >= len(rows): raise ValueError('invalid row')
                    row = rows[i]
                    identity = data['identity_' + str(i)][0]
                    classification = data['classification_' + str(i)][0]
                    if (row['decision'] != 'PENDING' or identity != row['parent_qid'] + ':' + row['variant']
                            or classification not in CHOICES or (decision == 'APPROVE' and classification == 'INVALID')):
                        raise ValueError('a selected row changed or has an invalid classification')
                    updates.append((row, classification))
                timestamp = datetime.now(timezone.utc).isoformat()
                for row, classification in updates:
                    row.update(decision=decision, reviewer=reviewer, classification=classification,
                               reviewed_at_utc=timestamp)
                fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.review-', text=True)
                try:
                    with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
                    os.replace(tmp, path)
                finally:
                    if os.path.exists(tmp): os.unlink(tmp)
            except (ValueError, KeyError, UnicodeError):
                self.send_error(400, 'Selection invalid, already reviewed, or contains an INVALID approval. Reload and try again.'); return
            self.send_response(303); self.send_header('Location', '/'); self.end_headers()

        def log_message(self, fmt, *args):
            pass

    HTTPServer(('127.0.0.1', port), Handler).serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv'); parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args(); serve(args.csv, args.port)

"""Small, dependency-free aggregate SVG chart for the local report."""
from html import escape
from pathlib import Path


def retrieval_chart(summary, path):
    rows=[r for r in summary if r.get('hit_at_5') is not None]
    height=max(80,45+25*len(rows));width=650
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (width,height,width,height),
           '<title>Known-citation Hit at 5 by method and family</title>',
           '<rect width="100%" height="100%" fill="white"/>',
           '<text x="8" y="20" font-size="14">Known-citation Hit@5 (incomplete relevance labels)</text>']
    for i,row in enumerate(rows):
        y=40+i*25; val=row['hit_at_5'];label=escape(str(row['method'])+' / '+str(row['family']))
        parts.extend(['<text x="8" y="%d" font-size="11">%s</text>'%(y+9,label),
                      '<rect x="175" y="%d" width="%.2f" height="12" fill="#31688e"/>'%(y,350*val),
                      '<text x="535" y="%d" font-size="11">%.3f (n=%d)</text>'%(y+10,val,row['retrievable'])])
    parts.append('</svg>')
    Path(path).write_text('\n'.join(parts)+'\n',encoding='utf-8')

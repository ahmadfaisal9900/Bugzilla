"""Versioned portable records; schema validation is explicit and fail-closed."""
import json
from pathlib import Path

VERSION='eval-extension-contract-v1'
REQUIRED={
 'Question':{'qid':str,'family':str,'question':str,'split':str,'scope':dict,'cluster_id':str},
 'Gold':{'qid':str,'gold':dict,'evidence':list,'validator':str},
 'Document':{'record_id':str,'bug_id':str,'kind':str,'url':str,'source_hash':str,'visibility':str,'text':str},
 'Chunk':{'record_id':str,'bug_id':str,'chunk_id':str,'chunk_hash':str,'text':str,'visibility':str},
 'RankedHit':{'chunk_id':str,'record_id':str,'bug_id':str,'rank':int,'score':(int,float)},
 'Prediction':{'qid':str,'method':str,'status':str,'abstained':bool},
 'Judgment':{'qid':str,'method':str,'family':str,'verdict':str,'reason':str},
 'RunManifest':{'state':str,'identity':str},
}


def validate(kind, value):
    if kind not in REQUIRED or not isinstance(value,dict): raise ValueError('unknown contract or non-object')
    for key, expected in REQUIRED[kind].items():
        if key not in value or not isinstance(value[key], expected) or isinstance(value[key],bool) and expected in (int,float):
            raise ValueError('%s.%s missing or wrong type' % (kind,key))
    if kind in ('Document','Chunk') and value['visibility'] != 'public': raise ValueError('non-public record')
    if kind == 'Question' and value['split'] not in ('dev','test'): raise ValueError('invalid split')
    if kind == 'RankedHit' and value['rank'] < 1: raise ValueError('invalid rank')
    return value


def read_jsonl(path, kind):
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            if line.strip(): yield validate(kind,json.loads(line))


def write_jsonl(path, kind, rows):
    with Path(path).open('w',encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(validate(kind,row),sort_keys=True,ensure_ascii=False)+'\n')


def jsonl_to_parquet(source, destination, kind):
    """Use DuckDB's streaming JSON reader; no PyArrow requirement."""
    import duckdb
    for _ in read_jsonl(source,kind): pass
    connection=duckdb.connect()
    try:
        connection.execute("COPY (SELECT * FROM read_json_auto(?)) TO ? (FORMAT PARQUET)",[str(destination),str(source)])
    finally: connection.close()

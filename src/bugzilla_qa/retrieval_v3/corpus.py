"""New corpus/index variants built from public sources using existing loaders."""
import hashlib
import shutil
from collections import Counter
from pathlib import Path
from bugzilla_qa.eval_extension.cli import records, verify_source_manifests
from bugzilla_qa.eval_extension.retrieval import build_lexical, safe_text, tokenizer_chunks
from bugzilla_qa.eval_extension.dense import build_dense
from .common import (ROOT, code_hashes, digest, file_hash, git_commit, locked,
                     read_config, read_jsonl, receipt, verify_artifacts, write_json, write_jsonl)


def source_metadata(config, root):
    import duckdb
    db=duckdb.connect(str(Path(root)/config['canonical_db']),read_only=True)
    try:
        rows=db.execute('''SELECT bug_id,component,summary FROM bugs WHERE bug_id IN
            (SELECT bug_id FROM sample_membership WHERE seed=?) ORDER BY bug_id''',[config['seed']]).fetchall()
        metadata={str(b):{'component':safe_text(c),'summary':safe_text(s)} for b,c,s in rows}
        rows=db.execute('''SELECT bug_id,target_bug_id,relation,link_key FROM bug_links
            WHERE bug_id IN (SELECT bug_id FROM sample_membership WHERE seed=?)
               OR target_bug_id IN (SELECT bug_id FROM sample_membership WHERE seed=?)
            ORDER BY link_key''',[config['seed'],config['seed']]).fetchall()
        edges=[{'source':str(b),'target':str(t),'relation':r,'record_id':rid}
               for b,t,r,rid in rows if str(b) in metadata and str(t) in metadata]
        return metadata,edges
    finally: db.close()


def token_length(tokenizer,text,special=True):
    return len(tokenizer(text,add_special_tokens=special,truncation=False)['input_ids'])


def rechunk(record, tokenizer, config, prefix=''):
    """Use the existing offset chunker; budget the *final* prefixed embedding text."""
    maximum=config['model_max_tokens']; size=config['chunk_tokens']; overlap=config['overlap_tokens']
    size=min(size,maximum-token_length(tokenizer,prefix)-2)
    if size<=overlap:
        raise RuntimeError('Full deterministic prefix leaves insufficient room: bug '+str(record['bug_id']))
    while size>overlap:
        parts=list(tokenizer_chunks(record,tokenizer,size,overlap))
        if all(token_length(tokenizer,prefix+p['text'])<=maximum
               and token_length(tokenizer,p['text'],False)<=config['chunk_tokens'] for p in parts):
            for part in parts:
                part['text']=prefix+part['text']
                part['chunk_hash']=hashlib.sha256(part['text'].encode()).hexdigest()
                part['token_count']=token_length(tokenizer,part['text'])
                part['prefix_tokens']=token_length(tokenizer,prefix,False) if prefix else 0
                yield part
            return
        size-=1
    raise RuntimeError('Unable to chunk within tokenizer budget')


def variant_rows(variant, current, source_records, metadata, tokenizer, config):
    if any(d.get('visibility')!='public' for d in current):
        raise RuntimeError('C0 contains non-public or unknown visibility')
    if variant=='C0':
        yield from current; return
    if variant=='C2':
        # Prefix the exact C1 payloads, splitting only to make room for the prefix.
        for base in variant_rows('C1',current,source_records,metadata,tokenizer,config):
            m=metadata[str(base['bug_id'])]
            prefix='Bug %s | %s | %s | %s: ' % (base['bug_id'],m['component'],m['summary'],base['kind'])
            for part in rechunk(base,tokenizer,config,prefix):
                local_start=part['source_char_start']
                part['chunk_id']='C2:'+base['chunk_id']+':'+str(local_start)
                part['parent_chunk_id']=base['chunk_id']
                for field in ('source_char_start','source_char_end'):
                    part[field]+=base.get('source_char_start',0)
                yield part
        return
    by_record={}
    for d in current: by_record.setdefault(d['record_id'],[]).append(d)
    for d in source_records:
        if d.get('visibility')!='public': raise RuntimeError('Source visibility is not public')
        if variant=='C1' and d['kind'] not in ('comment','history'):
            yield from by_record[d['record_id']]
            continue
        for p in rechunk(d,tokenizer,config):
            # Variant-scoped IDs prevent accidental cache mixing, while record IDs stay stable.
            p['chunk_id']=variant+':'+p['chunk_id']
            yield p


def build(config, root=ROOT, *, dry_run=False, limit=None, resume=False, variants=None):
    root=Path(root); variants=variants or config['corpora']
    source=root/config['source_corpus']; sm=read_config(root/config['source_corpus_manifest'])
    source_config=read_config(root/config['source_config'])
    if source_config['canonical_db']!=config['canonical_db'] or source_config['sample_seed']!=config['seed']:
        raise RuntimeError('Source loader and retrieval cohort configuration differ')
    input_paths=[root/config['source_corpus_manifest'],root/config['source_config'],
                 (root/source_config['canonical_db']).parent/'manifest.json',
                 (root/source_config['history_db']).parent/'summary.json']
    identity={'config':config,'code':code_hashes(),'limit':limit,'variants':variants,
              'input_sha256':{str(p.relative_to(root)):file_hash(p) for p in input_paths},
              'git_commit':git_commit()}
    directory=root/config['index_root']/('build-'+digest(identity)[:16])
    plan={'state':'DRY_RUN','output':str(directory),'variants':variants,'limit_bugs':limit,
          'source_chunks':sm['chunks'],'network_calls':0,'note':'Full build may download pinned model weights.'}
    if dry_run: return plan
    if file_hash(source)!=sm['sha256']: raise RuntimeError('Source corpus hash mismatch')
    with locked(directory):
        if (directory/'manifest.json').exists():
            if not resume: raise RuntimeError('Index build exists; use --resume')
            manifest=read_config(directory/'manifest.json'); verify_artifacts(directory,manifest)
            write_json(root/config['index_root']/'LATEST_BUILD.json',{'run':directory.name})
            return dict(plan,state='ALREADY_BUILT_VERIFIED')
        if (directory/'identity.json').exists() and read_config(directory/'identity.json')!=identity:
            raise RuntimeError('Build identity mismatch')
        write_json(directory/'identity.json',identity); write_json(directory/'config_snapshot.json',config)
        metadata,edges=source_metadata(config,root)
        if limit: metadata={k:metadata[k] for k in sorted(metadata)[:limit]}
        edges=[e for e in edges if e['source'] in metadata and e['target'] in metadata]
        write_json(directory/'graph.json',edges)
        current=[d for d in read_jsonl(source) if str(d['bug_id']) in metadata]
        if any(d.get('visibility')!='public' for d in current):
            raise RuntimeError('C0 contains non-public or unknown visibility')
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(config['embedding_model'],revision=config['embedding_revision'],use_fast=True)
        if not tokenizer.is_fast: raise RuntimeError('Fast tokenizer is required')
        verify_source_manifests(source_config)
        # Existing loader reads complete public comments, canonical metadata and the separate history overlay.
        # Keep only C0 source records, preserving the frozen corpus population.
        record_ids={d['record_id'] for d in current}
        sources=None
        from tqdm import tqdm
        for variant in tqdm(variants,desc='Corpus variants',unit='corpus'):
            out=directory/variant; out.mkdir(exist_ok=True)
            if (out/'manifest.json').exists():
                if not resume: raise RuntimeError('Existing variant requires --resume')
                verify_artifacts(out,read_config(out/'manifest.json')); continue
            corpus=out/'corpus.jsonl'
            if not corpus.exists():
                if variant=='C0' and not limit:
                    shutil.copy2(source,corpus)
                if variant!='C0' and sources is None:
                    sources=[r for r in records(source_config,limit) if r['record_id'] in record_ids]
                    if {r['record_id'] for r in sources}!=record_ids:
                        raise RuntimeError('Current source record coverage differs from C0')
                if not corpus.exists():
                    write_jsonl(corpus,variant_rows(variant,current,sources or [],metadata,tokenizer,config))
            docs=list(read_jsonl(corpus))
            if len({d['chunk_id'] for d in docs})!=len(docs): raise RuntimeError('Duplicate chunk IDs')
            truncated=sum(token_length(tokenizer,d['text'])>config['model_max_tokens'] for d in docs)
            if variant!='C0' and truncated: raise RuntimeError('Variant has truncated chunks')
            lexical=out/'lexical.sqlite'
            if not lexical.exists(): build_lexical(lexical,docs,digest(identity))
            # Reuse C0 dense bytes only when corpus, pinned model/revision and hash match exactly.
            reuse=root/config['source_dense_dir']; dm=read_config(reuse/'dense_manifest.json')
            if variant=='C0' and not limit and not (out/'dense_manifest.json').exists():
                if (dm['corpus_sha256']==file_hash(corpus) and dm['model']==config['embedding_model']
                    and dm['revision']==config['embedding_revision'] and file_hash(reuse/'dense.faiss')==dm['index_sha256']):
                    shutil.copy2(reuse/'dense.faiss',out/'dense.faiss')
                    write_json(out/'dense_manifest.json',dm)
            if not (out/'dense_manifest.json').exists():
                # Existing builder handles embedding shards, checksums and interrupted resume.
                write_json(out/'corpus_manifest.json',{'tokenizer_revision':config['embedding_revision']})
                build_dense(corpus,out,config['embedding_model'],config['batch_size'],config['device'],
                            resume=resume,revision=config['embedding_revision'])
            dm=read_config(out/'dense_manifest.json')
            if (dm['model']!=config['embedding_model'] or dm['revision']!=config['embedding_revision']
                or dm['corpus_sha256']!=file_hash(corpus)
                or dm['index_sha256']!=file_hash(out/'dense.faiss')):
                raise RuntimeError('Dense artifact/model/corpus hash mismatch')
            if dm['truncated_chunks']!=truncated: raise RuntimeError('Truncation accounting differs')
            receipt(out,state='COMPLETE',variant=variant,model=config['embedding_model'],
                    revision=config['embedding_revision'],reranker_model=config['reranker_model'],
                    reranker_revision=config['reranker_revision'],chunks=len(docs),
                    chunk_types=dict(Counter(d['kind'] for d in docs)),truncated_chunks=truncated,
                    record_count=len({d['record_id'] for d in docs}),source_corpus_sha256=sm['sha256'])
        write_json(directory/'summary.json',{'state':'COMPLETE','variants':{
            c:{k:read_config(directory/c/'manifest.json')[k] for k in ('chunks','record_count','truncated_chunks')}
            for c in variants},'limit_bugs':limit,'network_api_calls':0})
        result=receipt(directory,state='COMPLETE',identity=digest(identity),variants=variants,limit_bugs=limit)
        write_json(root/config['index_root']/'LATEST_BUILD.json',{'run':directory.name})
        return dict(plan,state='COMPLETE',manifest_sha256=file_hash(directory/'manifest.json'))

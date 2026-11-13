"""Reuse versioned public corpus, retrieval registry and top-50 caches."""
import json
import os
import sqlite3
from langsmith import traceable
from bugzilla_qa.retrieval_v3.common import read_config, read_jsonl, file_hash, digest
from bugzilla_qa.retrieval_v3.runner import load_cached_hits, load_engine, load_models
from bugzilla_qa.retrieval_v3.registry import get_retriever, explicit_bug_id, normalize
from bugzilla_qa.retrieval_v3.transforms import QueryTransforms
from bugzilla_qa.eval_extension.retrieval import rrf
from bugzilla_qa.eval_extension.dense import rerank
from .contracts import clean, public_chunk


class Backend:
    def __init__(self, config, root, provider):
        self.config,self.root,self.provider=config,root,provider
        self.rc=read_config(root/config['retrieval_config'])
        self.selection=read_config(root/config['selection'])
        if self.selection.get('state')!='SELECTED_DEV_ONLY' or self.selection.get('test_used'):
            raise RuntimeError('Missing valid preregistered development selection')
        for source in self.selection.get('sources',[]):
            if file_hash(root/source['path'])!=source['sha256']:
                raise RuntimeError('Selected-retriever source summary changed')
        self.selected=self.selection['selected']['retriever']; self.corpus=self.selection['selected']['corpus']
        self.index=root/self.selection['index_build']; self.directory=self.index/self.corpus
        build=read_config(self.index/'manifest.json')
        if build.get('state')!='COMPLETE' or file_hash(self.directory/'manifest.json')!=build['sha256'][self.corpus+'/manifest.json']:
            raise RuntimeError('Selected index manifest mismatch')
        m=read_config(self.directory/'manifest.json')
        if m['state']!='COMPLETE' or file_hash(self.directory/'corpus.jsonl')!=m['sha256']['corpus.jsonl']:
            raise RuntimeError('Public corpus integrity mismatch')
        self.docs=[dict(public_chunk(d),chunk_type=d.get('chunk_type',d.get('kind')))
                   for d in read_jsonl(self.directory/'corpus.jsonl')]
        self.by_id={d['chunk_id']:d for d in self.docs}; self.engine=None
        self.cache_manifests={}
        for path in config['retrieval_runs']:
            manifest=root/path/'manifest.json'
            if not manifest.exists(): continue
            m=read_config(manifest)
            if m.get('state')=='COMPLETE':
                cache=root/path/'retrieval_cache.sqlite'
                if file_hash(cache)!=m['sha256']['retrieval_cache.sqlite']:
                    raise RuntimeError('Retrieval cache checksum mismatch')
                self.cache_manifests[path]=m

    def _engine(self):
        if self.engine is None:
            os.environ['HF_HUB_OFFLINE']='1'; os.environ['TRANSFORMERS_OFFLINE']='1'
            self.engine=load_engine(self.directory,self.rc,load_models(self.rc),QueryTransforms(self.provider))
        return self.engine

    def _hydrate(self,hits):
        # Never trust text or visibility copied into a cached payload.
        return [dict(public_chunk(self.by_id[h['chunk_id']]),score=h.get('score',0.0),rank=i+1)
                for i,h in enumerate(hits) if h['chunk_id'] in self.by_id]

    @traceable(name='retrieve',process_inputs=clean,process_outputs=clean)
    def retrieve(self, question, method, k=None, use_cache=True, cached_only=False):
        k=k or self.config['retrieval_k']
        if use_cache:
            for path,m in self.cache_manifests.items():
                identity=read_config(self.root/path/'identity.json')
                if identity.get('split')!=question['split']: continue
                old=identity.get('config',{})
                if any(old.get(f)!=self.rc.get(f) for f in ('v3_freeze_id','phase05_freeze_id','canonical_db','seed')):
                    continue
                if identity.get('compatibility')!=self.selection.get('compatibility'): continue
                cache=self.root/path/'retrieval_cache.sqlite'
                with sqlite3.connect('file:'+str(cache)+'?mode=ro',uri=True) as db:
                    row=db.execute('SELECT query_sha256 FROM results WHERE corpus=? AND retriever=? AND dataset=? AND qid=?',
                        [self.corpus,method,question['dataset'],question['qid']]).fetchone()
                if not row or row[0]!=digest(question['question']): continue
                hits=load_cached_hits(self.root/path,self.corpus,method,question['dataset'],question['qid'],k)
                if any(h['chunk_id'] not in self.by_id for h in hits): raise RuntimeError('Cached chunk missing from corpus')
                return self._hydrate(hits),True
        if cached_only:raise KeyError('No compatible cached retrieval')
        hits=get_retriever(method,self._engine()).retrieve(question['question'],k)
        return self._hydrate(hits),False

    def dossier(self,question):
        import re
        ids=set(re.findall(r'\b(?:bug|issue|report)\s*#?\s*([1-9]\d*)\b',question['question'],re.I))
        if not ids:
            single=explicit_bug_id(question['question'])
            if single: ids={single}
        ids.update(re.findall(r'(?<![\w.])([1-9]\d{5,7})(?![\w.])',question['question']))
        if not ids:
            hits,_=self.retrieve(question,self.selected,k=1)
            ids={str(hits[0]['bug_id'])} if hits else set()
        order={'metadata':0,'comment':1,'link':2,'relationship':2,'history':3}
        return sorted((d for d in self.docs if str(d['bug_id']) in ids),
                      key=lambda d:(order.get(d.get('kind',d.get('chunk_type')),9),
                         str(d.get('event_time_utc') or ''),str(d['bug_id']),d['record_id'],d.get('source_char_start',0)))

    def oracle(self,refs):
        return [d for d in self.docs if d['record_id'] in set(refs)]

    def corrective(self,question,hits):
        # Deterministic three-query retry: no provider call on the low-evidence path.
        import re
        text=question['question']; bug=explicit_bug_id(text)
        queries=list(dict.fromkeys([text,re.sub(r'[^\w\s]',' ',text),
                          ('bug '+bug+' ' if bug else '')+' '.join(re.findall(r'\w+',text)[-12:])]))
        engine=self._engine()
        fused=rrf({str(i):get_retriever('R5',engine).retrieve(q,50) for i,q in enumerate(queries)},50,self.rc['rrf_k'])
        checked=rerank(text,fused,engine.cross_encoder,self.config['retrieval_k'])
        return self._hydrate(checked),queries

    def score_top(self,hits):
        return hits[0]['score'] if hits and not hits[0].get('unmatched_fallback') else float('-inf')

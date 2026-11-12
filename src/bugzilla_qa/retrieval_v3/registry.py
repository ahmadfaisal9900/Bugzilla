"""Adapters for existing FTS5, FAISS, RRF, hierarchy and cross-encoder code."""
import re
from collections import defaultdict
from typing import Protocol
from bugzilla_qa.eval_extension.retrieval import BUG_ID, hierarchical_search, lexical_search, rrf
from bugzilla_qa.eval_extension.dense import rerank

REGISTRY = {
    'R1':'BM25', 'R2':'dense', 'R3':'hybrid RRF', 'R4':'hierarchical',
    'R5':'hybrid + cross-encoder', 'R6':'R5 + explicit graph neighbours',
    'R7a':'HyDE over R5', 'R7b':'multi-query RRF over R5',
}


def explicit_bug_id(query):
    match=re.search(r'\b(?:bug|issue|report)\s*#?\s*([1-9]\d*)\b',query,re.I)
    if match is None: match=re.search(r'(?<!\w)#([1-9]\d{4,})(?!\w)',query)
    if match is None: match=re.search(r'(?<![\w.])([1-9]\d{5,7})(?![\w.])',query)
    return match.group(1) if match else None


class Retriever(Protocol):
    def retrieve(self, query, k): ...


def normalize(hits, k):
    result=[]; seen=set()
    for h in hits:
        if h['chunk_id'] in seen: continue
        seen.add(h['chunk_id'])
        result.append(dict(h,bug_id=str(h['bug_id']),chunk_type=h.get('chunk_type',h.get('kind')),
                           rank=len(result)+1,score=float(h['score'])))
        if len(result)==k: break
    return result


def complete(hits, docs, k):
    seen={h['chunk_id'] for h in hits}
    return normalize(hits+[dict(d,score=0.0,unmatched_fallback=True) for d in docs if d['chunk_id'] not in seen],k)


def jaccard(a,b):
    x={h['chunk_id'] for h in a[:10]}; y={h['chunk_id'] for h in b[:10]}
    return len(x&y)/len(x|y) if x|y else None


class Engine:
    """One source-only backend per corpus. No labels or question IDs enter here."""
    def __init__(self, docs, lexical_path, dense, cross_encoder, edges, config, transforms=None):
        self.docs=sorted(docs,key=lambda d:d['chunk_id']); self.lexical_path=lexical_path
        self.dense,self.cross_encoder,self.config=dense,cross_encoder,config
        self.transforms=transforms
        self.metadata=defaultdict(list); self.neighbours=defaultdict(set)
        for d in self.docs:
            if d['kind']=='metadata': self.metadata[str(d['bug_id'])].append(d)
        for e in edges:
            a,b=str(e['source']),str(e['target'])
            self.neighbours[a].add(b); self.neighbours[b].add(a)
        self._query=None; self._memo={}

    def _cached(self, query, name, function):
        if self._query!=query: self._query=query; self._memo={}
        if name not in self._memo: self._memo[name]=function()
        return self._memo[name]

    def base(self, query, name):
        n=min(self.config['candidate_k'],len(self.docs))
        if name=='R1':
            return complete(lexical_search(self.lexical_path,query,n,filter_bug=False),self.docs,n)
        if name=='R2': return normalize(self.dense.search(query,n,filter_bug=False),n)
        if name=='R3':
            return rrf({'lexical':self.run('R1',query,n),'dense':self.run('R2',query,n)},n,self.config['rrf_k'])
        if name=='R4':
            explicit=explicit_bug_id(query)
            if explicit: parents={explicit}
            else:
                parent_hits=hierarchical_search(self.lexical_path,query,top_k=1,
                                                max_bugs=self.config['hierarchical_max_bugs'])
                if parent_hits: parents={str(h['bug_id']) for h in parent_hits}
                else:
                    meta=[h for h in self.run('R3',query,n) if h['kind']=='metadata']
                    # Dense search over all metadata if the flat shortlist missed every parent.
                    if not meta:
                        meta=self.dense.search(query,len(self.docs),filter_bug=False)
                        meta=[h for h in meta if h['kind']=='metadata']
                    parents={str(h['bug_id']) for h in meta[:self.config['hierarchical_max_bugs']]}
            allowed=[d for d in self.docs if str(d['bug_id']) in parents]
            lex=[h for h in lexical_search(self.lexical_path,query,len(self.docs),filter_bug=False)
                 if str(h['bug_id']) in parents]
            den=self.dense.search(query,n,filter_bug=False,allowed_bug_ids=parents)
            hits=rrf({'lexical':lex,'dense':den},n,self.config['rrf_k'])
            return [dict(h,stage1_bug_ids=sorted(parents)) for h in complete(hits,allowed,n)]
        if name=='R5':
            return rerank(query,self.run('R3',query,n),self.cross_encoder,n)
        if name=='R6':
            # Construct at retrieval k below; the reusable top-50 candidate list is R5 plus neighbours.
            return self.run('R5',query,n)
        if name in ('R7a','R7b'):
            if self.transforms is None: raise RuntimeError('R7 requires the shared provider adapter')
            rewrites=self.transforms.get(name,query)['queries']
            if name=='R7a': return self.run('R5',rewrites[0],n)
            return rrf({str(i):self.run('R5',q,n) for i,q in enumerate(rewrites)},n,self.config['rrf_k'])
        raise ValueError('Unknown retriever '+name)

    def run(self,name,query,k):
        if k<1: raise ValueError('k must be positive')
        if name not in REGISTRY: raise ValueError('Unknown retriever')
        if name=='R6': return self.graph(query,k)
        return normalize(self._cached(query,name,lambda:self.base(query,name)),k)

    def graph(self,query,k):
        base=self.run('R5',query,self.config['candidate_k']); roots=[]
        for h in base:
            if h['bug_id'] not in roots: roots.append(h['bug_id'])
            if len(roots)==self.config['graph_top_bugs']: break
        neighbours=sorted(set().union(*(self.neighbours[b] for b in roots))-set(roots),key=int)
        candidates=[]
        for b in neighbours:
            # One representative metadata chunk per neighbour, deterministic across resumes.
            if self.metadata[b]: candidates.append(dict(self.metadata[b][0],score=0.0,graph_expansion=True))
        slots=min(self.config['graph_max_slots'],len(candidates))
        chosen=candidates[:slots]; chosen_ids={d['chunk_id'] for d in chosen}
        core=[h for h in base if h['chunk_id'] not in chosen_ids]
        insert=min(self.config['graph_insert_after'],len(core))
        return normalize(core[:insert]+chosen+core[insert:],k)


class NamedRetriever:
    def __init__(self,name,engine):
        if name not in REGISTRY: raise ValueError('Unknown retriever')
        self.name,self.engine=name,engine
    def retrieve(self,query,k):
        # Measure a complete method, not just its marginal work after a previous method.
        # Model weights remain warm; no previously embedded query is reused in timing.
        self.engine._query=None; self.engine._memo={}
        if hasattr(self.engine.dense,'_last_query_vector'):
            self.engine.dense._last_query_vector=None
        return self.engine.run(self.name,query,k)


def get_retriever(name,engine): return NamedRetriever(name,engine)

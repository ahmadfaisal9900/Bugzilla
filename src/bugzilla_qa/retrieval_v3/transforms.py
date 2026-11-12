"""R7 transforms use the existing generator provider, never question gold."""
import time
from .common import digest


class QueryTransforms:
    def __init__(self,provider):
        self.provider=provider; self.saved={}

    def get(self,name,query):
        key=(name,query)
        if key in self.saved:
            self.saved[key]=dict(self.saved[key],reuse_latency_ms=0.0,cache_hit=True)
            return self.saved[key]
        if name=='R7a':
            instruction='Write one short hypothetical public bug report that could match the question. Do not claim it is factual. Return queries containing exactly that one report.'
            count=1
        else:
            instruction='Rewrite the question into three distinct concise search queries. Preserve explicit bug IDs and scope. Do not answer the question. Return exactly three queries.'
            count=3
        schema={'type':'object','properties':{'queries':{'type':'array','items':{'type':'string'},
                'minItems':count,'maxItems':count}},'required':['queries'],'additionalProperties':False}
        start=time.perf_counter()
        response=self.provider.generate_json(query,schema,system_prompt=instruction,
                        prompt_version='retrieval-v3-'+name+'-v1',purpose='query-transform-'+name)
        elapsed=time.perf_counter()-start
        if response['state']=='DRY_RUN':
            raise RuntimeError('R7 execution requires --enable-llm (planning makes zero calls)')
        queries=response['value']['queries']
        if any(not q.strip() or len(q)>6000 for q in queries): raise RuntimeError('Invalid transformed query')
        value={'queries':queries,'prompt_hash':response['prompt_hash'],
               'cache_hit':response['state']=='CACHE_HIT','reuse_latency_ms':elapsed*1000,
               'original_latency_ms':response.get('latency_ms',elapsed*1000)}
        self.saved[key]=value
        return value

    def info(self,name,query): return self.saved.get((name,query),{})

"""One shared LangGraph, configured as S0-S8 or diagnostic ORACLE."""
import json
import re
import time
from langgraph.graph import StateGraph, START, END
from langsmith import traceable
from jsonschema import ValidationError
from bugzilla_qa.llm.provider import InvalidJSONResponse
from .contracts import AnswerState, ANSWER_SCHEMA, clean, pack, abstention, check_answer, normalize_citations
from .tools import TOOLS

SYSTEMS={f'S{i}':name for i,name in enumerate([
    'closed-book','BM25 RAG','selected RAG','query-transform RAG','corrective RAG',
    'long-context dossier','graph expansion','structured tools','router'])}
SYSTEMS['ORACLE']='gold-evidence diagnostic'


@traceable(name='router',process_inputs=clean,process_outputs=clean)
def rule_route(question):
    from bugzilla_qa.retrieval_v3.registry import explicit_bug_id
    text=question.lower(); bug=explicit_bug_id(text)
    if re.search(r'\b(how many|count|number of)\b',text): return 'S7','count'
    if bug and re.search(r'\b(why|reason|constraint)\b',text):return 'S5','explanation_with_id'
    if re.search(r'\b(depends|dependencies|blocks|blocking|duplicate)\b',text):return 'S7','explicit_relation'
    if not bug:return 'S2','no_id'
    if re.search(r'\b(component|status|resolution|priority|severity|product|fixed|reopen|elapsed|filed)\b',text):
        return 'S7','structured_lookup_with_id'
    return None,'ambiguous_id_query'


class AnswerGraph:
    def __init__(self,config,provider,backend,tools,prompt,persist,confirm=False):
        self.config,self.provider,self.backend,self.tools=config,provider,backend,tools
        self.prompt,self.persist_callback,self.confirm=prompt,persist,confirm
        g=StateGraph(AnswerState)
        for name in ('load_question','router','retrieve','pack_context','generate','tool','validate','persist'):
            g.add_node(name,getattr(self,name))
        g.add_edge(START,'load_question');g.add_edge('load_question','router')
        g.add_edge('router','retrieve');g.add_edge('retrieve','pack_context')
        g.add_conditional_edges('pack_context',lambda s:'validate' if s.get('raw_output') is not None else 'generate')
        g.add_conditional_edges('generate',lambda s:'tool' if s.get('raw_output',{}).get('calls') else 'validate')
        g.add_edge('tool','pack_context')
        g.add_conditional_edges('validate',lambda s:'generate' if s.get('status')=='repair' else 'persist')
        g.add_edge('persist',END)
        self.graph=g.compile()

    def load_question(self,s):
        if s['split']=='test' and not self.confirm:raise RuntimeError('Locked test requires --confirm-locked-test')
        if s['system_id'] not in SYSTEMS:raise ValueError('Unknown system')
        # Reinitialize all transient fields for each question.
        return dict(retrieved=[],context='',context_ids=[],context_map={},errors=[],usage=[],
                    raw_output=None,tool_log=[],tool_step=0,repair_count=0,call_count=0,
                    started_at=time.perf_counter(),status='pending',cache_hit=False,citation_normalization=[],retrieval_cache_hit=False)

    def _call(self,s,prompt,schema=None,tools=None,purpose='answer'):
        before=self.provider.calls
        try:
            if tools is not None:
                response=self.provider.generate_tools(prompt,tools,system_prompt=self.prompt,
                   prompt_version=self.config['prompt_version'],purpose=purpose)
            else:
                response=self.provider.generate_json(prompt,schema,system_prompt=self.prompt,
                   prompt_version=self.config['prompt_version'],purpose=purpose)
            if response['state']=='DRY_RUN':raise RuntimeError('Enable LLM explicitly; use plan for zero-call runs')
            s['usage']=s['usage']+[dict(response, value=None)]
            s['cache_hit']=bool(s.get('cache_hit')) or response['state']=='CACHE_HIT'
            return response['value']
        finally:
            s['call_count']+=self.provider.calls-before

    @traceable(name='route',process_inputs=clean,process_outputs=clean)
    def router(self,s):
        route=s['system_id'];rule='system_selected'
        if route=='S8':
            route,rule=rule_route(s['question'])
            if route is None:
                value=self._call(s,s['question'],{'type':'object','properties':{'route':{'type':'string','enum':['S2','S5','S7']}},
                     'required':['route'],'additionalProperties':False},purpose='router')
                route=value['route'];rule='llm_ambiguous'
        return dict(route=route,route_rule=rule,call_count=s['call_count'],usage=s['usage'],cache_hit=s['cache_hit'])

    @traceable(name='retrieve',process_inputs=clean,process_outputs=clean)
    def retrieve(self,s):
        route=s['route'];cache=False;chunks=[];raw=None;before=self.provider.calls
        if route=='S0' or route=='S7':pass
        elif route=='S5':chunks=self.backend.dossier(s)
        elif route=='ORACLE':chunks=self.backend.oracle(s.get('oracle_refs',[]))
        elif route=='S4':
            tau=self.config.get('corrective_tau')
            if tau is None:raise RuntimeError('S4 requires the dev-only tau suggestion/configuration first')
            chunks,cache=self.backend.retrieve(s,'R5')
            if self.backend.score_top(chunks)<tau:
                chunks,queries=self.backend.corrective(s,chunks)
                if self.backend.score_top(chunks)<tau:
                    raw=abstention('The retrieved public evidence did not meet the configured evidence threshold.')
                    route='abstain_low_evidence'
                s['tool_log']=s['tool_log']+[{'name':'corrective_local_multiquery','arguments':{'queries':queries},
                    'result':{'top_reranker_score':self.backend.score_top(chunks),'tau':tau}}]
        else:
            method={'S1':'R1','S2':self.backend.selected,'S3':self.config['query_transform'],'S6':'R6'}[route]
            chunks,cache=self.backend.retrieve(s,method)
        return dict(retrieved=chunks,raw_output=raw,route=route,cache_hit=s['cache_hit'] or cache,
                    retrieval_cache_hit=cache,
                    tool_log=s['tool_log'],call_count=s['call_count']+self.provider.calls-before)

    @traceable(name='pack_context',process_inputs=clean,process_outputs=clean)
    def pack_context(self,s):
        if s['route']=='S7':
            entries=[];ids=[];size=0
            for entry in reversed(s['tool_log']):
                text=json.dumps(clean(entry),sort_keys=True)
                if size+len(text.encode())>self.config['context_tokens']:
                    text=json.dumps({'name':entry['name'],'result':'Withheld from prompt: result exceeds remaining context budget; narrow the tool request.'})
                else:ids+=entry.get('result',{}).get('evidence_ids',[])
                if size+len(text.encode())+1>self.config['context_tokens']:break
                entries.insert(0,text);size+=len(text.encode())+1
            return dict(context='\n'.join(entries),context_map={},context_ids=list(set(ids)))
        budget=self.config['dossier_tokens'] if s['route']=='S5' else self.config['context_tokens']
        context,mapping=pack(s.get('retrieved',[]),budget)
        return dict(context=context,context_map=mapping,context_ids=list(mapping.values()))

    def generate(self,s):
        # A single prompt file, generation model and output schema for all arms.
        payload={'question':s['question']}
        if s['route']!='S0':
            payload.update(declared_scope=s.get('scope',{}),evidence=s['context'],citation_map=s['context_map'])
        if s.get('status')=='repair':payload['repair']='Return answer JSON directly. No tools or browser are available on this repair turn. Use only supplied evidence IDs; abstain if evidence is unavailable.'
        try:
            if s['route']=='S7' and s['tool_step']<min(4,self.config['tool_steps']) and s.get('status')!='repair':
                payload['instruction']='Use an allowlisted function, or submit_answer when enough evidence is available. Do not invent missing facts.'
                value=self._call(s,json.dumps(payload),tools=TOOLS,purpose='structured-tools')
            else:value=self._call(s,json.dumps(payload),ANSWER_SCHEMA,purpose='answer-repair' if s.get('status')=='repair' else 'answer')
            return dict(raw_output=value,usage=s['usage'],call_count=s['call_count'],cache_hit=s['cache_hit'],status='generated')
        except (RuntimeError,ValueError,KeyError,ValidationError) as exc:
            # Preserve no unsanitized provider messages; the provider ledger has error class/status.
            label='provider_failure:' if isinstance(exc,RuntimeError) and not isinstance(exc,InvalidJSONResponse) else 'invalid_output:'
            detail=':'+clean(str(exc)) if isinstance(exc,RuntimeError) else ''
            return dict(raw_output={},errors=s['errors']+[label+type(exc).__name__+detail],usage=s['usage'],
                        call_count=s['call_count'],status='generated')

    @traceable(name='tools',process_inputs=clean,process_outputs=clean)
    def tool(self,s):
        log=list(s['tool_log']);step=s['tool_step'];raw=None;errors=list(s['errors']);before=self.provider.calls
        for call in s['raw_output']['calls']:
            args={}
            try:
                args=json.loads(call['arguments_json'])
                if call['name']=='submit_answer':
                    raw=args;break # Common validator checks final answer/citations.
                if step>=min(4,self.config['tool_steps']):raise ValueError('Tool step cap exceeded')
                step+=1
                result=self.tools.execute(call['name'],args,s)
                log.append({'name':call['name'],'arguments':args,'result':clean(result)})
            except Exception as exc:
                # Invalid tool arguments are auditable, count as a step and never execute SQL.
                if call['name']=='submit_answer':
                    errors.append('invalid_submit_answer');raw={};break
                log.append({'name':call['name'],'arguments':clean(args),'result':{'error':type(exc).__name__}})
                if step==s['tool_step']:step+=1
                errors.append('tool_rejected:'+type(exc).__name__)
        return dict(raw_output=raw,tool_log=log,tool_step=step,errors=errors,
                    call_count=s['call_count']+self.provider.calls-before)

    def validate(self,s):
        if any(e.startswith('provider_failure:') for e in s['errors']):
            return dict(answer=abstention('The provider request could not complete.'),status='error')
        try:
            candidate,changes=normalize_citations(s.get('raw_output'),s['context_map'])
            answer=check_answer(candidate,s['context_ids'])
            return dict(answer=answer,status='ok',citation_normalization=changes)
        except Exception as exc:
            errors=s['errors']+['answer_contract:'+type(exc).__name__]
            if s['repair_count']<1:
                return dict(repair_count=1,status='repair',errors=errors,raw_output=None)
            return dict(answer=abstention('No valid supported answer was produced.'),status='error',errors=errors)

    def persist(self,s):
        self.persist_callback(s)
        return {}

    def invoke(self,question,system,config_hash):
        return self.graph.invoke(dict(question,system_id=system,config_hash=config_hash),{'recursion_limit':50})

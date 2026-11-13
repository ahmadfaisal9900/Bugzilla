"""Allowlisted parameterized read-only tools. Base field_changes is never read."""
import datetime as dt
import json
from langsmith import traceable
from jsonschema import validate
from bugzilla_qa.retrieval_v3.common import read_config
from bugzilla_qa.benchmark.phase05 import partition as phase05_partition
from bugzilla_qa.eval_extension.bank import partition as expanded_partition
from bugzilla_qa.data.phase04 import classify_first_fixed
from .contracts import clean, ANSWER_SCHEMA

FIELDS={'product':'product','component':'component','status':'snapshot_status',
        'resolution':'snapshot_resolution','created_at':'opened_at_utc',
        'snapshot_as_of':'snapshot_as_of_utc','priority':None,'severity':None}
RELATIONS=['blocks','depends_on','duplicate_of','has_duplicate','regressed_by','regresses','see_also','related']
STATUSES=['UNCONFIRMED','NEW','ASSIGNED','REOPENED','RESOLVED','VERIFIED','CLOSED']
RESOLUTIONS=['','FIXED','DUPLICATE','INVALID','INCOMPLETE','WONTFIX','WORKSFORME','MOVED','EXPIRED']

def obj(properties,required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}

ID={'type':'integer','minimum':1}
TOOLS=[
 {'name':'get_bug_fields','description':'Recorded archive fields; unknown snapshot date. Missing fields stay null.',
  'parameters':obj({'bug_id':ID,'fields':{'type':'array','items':{'type':'string','enum':list(FIELDS)},'minItems':1}},['bug_id','fields'])},
 {'name':'get_links','description':'Explicit recorded snapshot relations; no historical validity implied.',
  'parameters':obj({'bug_id':ID,'link_type':{'type':'string','enum':RELATIONS}},['bug_id','link_type'])},
 {'name':'count_bugs','description':'Count canonical distinct IDs in declared cohort/all scope, respecting question partition. Dates filter creation only, not first FIXED.',
  'parameters':obj({'component':{'type':'string','maxLength':200},'status':{'type':'string','enum':STATUSES},
   'resolution':{'type':'string','enum':RESOLUTIONS},'created_from':{'type':'string'},'created_to':{'type':'string'},
   'scope':{'type':'string','enum':['cohort','all']}},['scope'])},
 {'name':'get_lifecycle','description':'Verified separate Phase 4 event evidence; unknown if absent, conflicted or ambiguous.',
  'parameters':obj({'bug_id':ID},['bug_id'])},
 {'name':'search_text','description':'Search public text with the selected retriever.',
  'parameters':obj({'query':{'type':'string','maxLength':6000},'k':{'type':'integer','minimum':1,'maximum':10}},['query','k'])},
 {'name':'submit_answer','description':'Finish with the common answer JSON.', 'parameters':ANSWER_SCHEMA}]


def iso(value):
    if value is None:return None
    return value.isoformat() if hasattr(value,'isoformat') else value


class Tools:
    def __init__(self,config,root,backend):
        self.config,self.root,self.backend=config,root,backend
        self.source=read_config(root/config['source_config']); self._db=None; self._history=None

    @property
    def db(self):
        if self._db is None:
            import duckdb
            self._db=duckdb.connect(str(self.root/self.source['canonical_db']),read_only=True)
            self._db.execute("SET TimeZone='UTC'")
            self._db.execute('SET memory_limit=?',[self.config['duckdb_memory']])
            self._db.execute('SET threads=1')
        return self._db

    def close(self):
        if self._db is not None:self._db.close();self._db=None

    def evidence(self,bug,kinds):
        return sorted({d['chunk_id'] for d in self.backend.docs if str(d['bug_id'])==str(bug)
                       and d.get('kind',d.get('chunk_type')) in kinds})

    @traceable(name='tool',process_inputs=clean,process_outputs=clean)
    def execute(self,name,args,question):
        spec=next((s for s in TOOLS if s['name']==name and name!='submit_answer'),None)
        if spec is None:raise ValueError('Unknown or forbidden tool')
        validate(args,spec['parameters'])
        if 'bug_id' in args and str(args['bug_id']) not in {str(d['bug_id']) for d in self.backend.docs}:
            return {'known':False,'reason':'Outside the public indexed study cohort','evidence_ids':[]}
        if name=='get_bug_fields':
            fields=args['fields']
            cols=list(dict.fromkeys(FIELDS[f] for f in fields if FIELDS[f]))
            if 'source_record_id' not in cols: cols.append('source_record_id')
            row=self.db.execute('SELECT '+','.join(cols)+' FROM bugs WHERE bug_id=?',[str(args['bug_id'])]).fetchone()
            if row is None:return {'known':False,'evidence_ids':[]}
            data=dict(zip(cols,row)); extra={}
            if any(FIELDS[f] is None for f in fields):
                r=self.db.execute('SELECT normalized_fields FROM source_records WHERE source_record_id=? AND disposition=? LIMIT 1',
                                  [data['source_record_id'],'NORMALIZED']).fetchone()
                if r:extra=json.loads(r[0])
            return clean({'known':True,'snapshot_as_of':'UNKNOWN','fields':{f:iso(data.get(FIELDS[f])) if FIELDS[f] else extra.get(f) for f in fields},
                          'evidence_ids':self.evidence(args['bug_id'],{'metadata'})},self.root)
        if name=='get_links':
            rows=self.db.execute('SELECT target_bug_id,link_key FROM bug_links WHERE bug_id=? AND relation=? ORDER BY target_bug_id,link_key',
                [str(args['bug_id']),args['link_type']]).fetchall()
            # ID sets are complete; never truncate a relationship answer silently.
            return {'targets':sorted({str(r[0]) for r in rows if r[0]},key=int),'historical_validity':'UNKNOWN',
                    'evidence_ids':self.evidence(args['bug_id'],{'link','relationship'})}
        if name=='count_bugs':return self.count(args,question)
        if name=='get_lifecycle':
            if question.get('scope',{}).get('as_of') or question.get('scope',{}).get('snapshot_as_of_utc'):
                return {'known':False,'reason':'A historical availability snapshot is not verified','evidence_ids':[]}
            return self.lifecycle(args['bug_id'])
        query=dict(question,question=args['query'])
        hits,cache=self.backend.retrieve(query,self.backend.selected,k=args['k'],use_cache=False)
        return {'chunks':hits,'cache_hit':cache,'evidence_ids':[h['chunk_id'] for h in hits]}

    def count(self,args,question):
        clauses=[];params=[]
        scope=question.get('scope',{})
        if args['scope']=='all' and 'all canonical' not in str(scope.get('corpus','')).lower():
            raise ValueError('All-corpus counts require an explicitly declared all canonical scope')
        if args['scope']=='cohort':
            clauses.append('bug_id IN (SELECT bug_id FROM sample_membership WHERE seed=?)');params.append(self.config['seed'])
        if scope.get('partition') in ('dev','test') or 'non-conflicted' in question['question']:
            clauses.append("NOT EXISTS (SELECT 1 FROM source_records v WHERE v.bug_id=bugs.bug_id AND v.source_dataset='metadata' AND v.disposition='CONFLICT_VARIANT')")
        if scope.get('product'):
            clauses.append('product=?');params.append(scope['product'])
        for key,col in (('component','component'),('status','snapshot_status'),('resolution','snapshot_resolution')):
            if key in args:
                if key=='component' and not self.db.execute('SELECT 1 FROM bugs WHERE component=? LIMIT 1',[args[key]]).fetchone():
                    raise ValueError('Component outside canonical allowlist')
                clauses.append(col+'=?');params.append(args[key])
        for key,op in (('created_from','>='),('created_to','<')):
            if key in args:
                value=dt.datetime.fromisoformat(args[key].replace('Z','+00:00'))
                if value.tzinfo is None:raise ValueError('Date requires UTC or timezone offset')
                clauses.append('opened_at_utc'+op+'?');params.append(value)
        where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
        partition_name=scope.get('partition')
        if partition_name in ('dev','test'):
            # Reuse the frozen partition implementation; counts never use export rows.
            bugs=self.db.execute('SELECT DISTINCT bug_id FROM bugs'+where,params).fetchall()
            scheme=scope.get('partition_scheme')
            if scheme not in ('phase05','expanded-v2'):raise ValueError('Unknown declared partition scheme')
            partition=phase05_partition if scheme=='phase05' else expanded_partition
            count=sum(partition(self.config['seed'],b[0])==partition_name for b in bugs)
        else:count=self.db.execute('SELECT count(DISTINCT bug_id) FROM bugs'+where,params).fetchone()[0]
        return {'count':count,'scope':args['scope'],'partition':partition_name,'time_filter':'creation [from,to)',
                'snapshot_as_of':'UNKNOWN','evidence_ids':[],
                'sql_template':'canonical_distinct_bug_count_v1','parameters':args}

    def lifecycle(self,bug):
        if self._history is None:
            self._history=read_config(self.root/self.config['history_checkpoint'])['candidate_results']
        record=self._history.get(str(bug))
        if not record:return {'known':False,'reason':'No verified Phase 4 history','evidence_ids':[]}
        h=record.get('history',{})
        if h.get('state')!='PARSED' or not h.get('chronology_ok') or h.get('same_time_groups') or record.get('source_consistency_differences'):
            return {'known':False,'reason':'History incomplete, ambiguous or source-conflicted','evidence_ids':[]}
        row=self.db.execute('SELECT opened_at_utc FROM bugs WHERE bug_id=?',[str(bug)]).fetchone()
        metric=classify_first_fixed(h,iso(row[0]) if row else None)
        # Only explicit qualified events supply a first FIXED; never current status.
        return {'known':True,'first_fixed_known':metric['state']=='VALID_EVENT_TIME',
                'fix_metric':metric,'reopened_count':h.get('reopened_count'),
                'snapshot_as_of':'UNKNOWN','temporal_mode':'verified_event_time_retrospective',
                'provenance':{k:record.get('history_fetch',{}).get(k) for k in
                    ('url','fetched_at_utc','raw_sha256','source_visibility','status_code')},
                'evidence_ids':self.evidence(bug,{'history','metadata'})}

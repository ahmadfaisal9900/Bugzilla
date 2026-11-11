"""Conservative v2 question parser; only visible wording and public scope enter SQL."""
import re

from bugzilla_qa.data.normalize import digest
from bugzilla_qa.eval_extension.bank import partition
from bugzilla_qa.methods import m3_sql


def parse(question):
    q=' '.join(question.split())
    if not re.search(r'(?i)archive|metadata|verified API history|recorded product',q):
        return None
    bug=re.search(r'(?i)\b(?:bug|issue)\s*#?\s*(\d+)\b',q)
    if bug and re.search(r'(?i)engineer work hours',q):
        return {'template':'abstain','reason':'engineer_hours'}
    if bug and re.search(r'(?i)first recorded FIXED transition',q) and re.search(r'(?i)calendar hours',q):
        return {'template':'first_fixed_hours','bug_id':bug.group(1)}
    if bug:
        field=re.search(r'(?i)recorded (component|status|resolution|product)\?',q)
        if not field:
            field=re.search(r'(?i)what (component|status|resolution|product) (?:does|is)',q)
        if not field:
            field=re.search(r'(?i)(?:recorded |which )(component|status|resolution|product) (?:for|is)',q)
        if field: return {'template':'field_lookup','field':field.group(1).lower(),'bug_id':bug.group(1)}
        relation=re.search(r'(?i)recorded for relation ([\w-]+) from',q)
        if relation and relation.group(1) in m3_sql.RELATIONS:
            return {'template':'relation_targets','relation':relation.group(1),'bug_id':bug.group(1)}
    match=re.search(r'(?i)sample (dev|test) partition \(\d+ distinct non-conflicted bugs\), how many distinct bugs have recorded (component|status|resolution|year) (.+?)\?',q)
    if match:
        field={'year':'creation_year'}.get(match.group(2).lower(),match.group(2).lower())
        return {'template':'count_in_partition','partition':match.group(1).lower(),'field':field,'value':match.group(3)}
    return None


class Store(m3_sql.SqlStore):
    def __init__(self, base_path, overlay_path, seed=317):
        super().__init__(base_path,overlay_path,seed)
        self.partitions={sp:sorted(b for b in self.population if partition(seed,b)==sp) for sp in ('dev','test')}

    def _count(self,intent,scope):
        sp=intent['partition']; universe=self.partitions[sp]
        if scope.get('partition')!=sp or scope.get('population_hash')!=digest(universe) or scope.get('denominator')!=len(universe):
            return 'The stated population does not match this database.',True,None,[]
        column={'component':'component','status':'snapshot_status','resolution':'snapshot_resolution','creation_year':'year(opened_at_utc)'}.get(intent['field'])
        if column is None: return 'Unsupported filter.',True,None,[]
        value=intent['value']
        if intent['field']=='creation_year':
            if not re.fullmatch(r'\d{4}',value): return 'Invalid year.',True,None,[]
            value=int(value)
        count=self.base.execute('SELECT count(DISTINCT bug_id) FROM bugs WHERE bug_id IN (SELECT unnest(?)) AND '+column+'=?',[universe,value]).fetchone()[0]
        return str(count),False,count,[]


def answer(store, question):
    intent=parse(question['question'])
    # resolution is supported by this adapter's fixed SQL allowlist.
    valid=m3_sql.validate_intent(intent)
    if intent and intent.get('template')=='count_in_partition' and intent.get('field')=='resolution':
        valid=set(intent)=={'template','field','value','partition'} and intent['partition'] in ('dev','test') and isinstance(intent['value'],str) and 0<len(intent['value'])<=200
    if not valid:
        return m3_sql.make_answer(question['qid'],m3_sql.METHOD,'',status=m3_sql.NO_INTENT,trace={'intent':None})
    text,abstained,value,evidence=store.execute(intent,question['scope'])
    return m3_sql.make_answer(question['qid'],m3_sql.METHOD,text,abstained,value,evidence,trace={'intent':intent})

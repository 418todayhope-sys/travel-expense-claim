from pathlib import Path
from copy import deepcopy
from collections import Counter
import hashlib,json,subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
ROOT=Path('/home/maxg/travel-expense-claim-omega4');sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
WORK=Path(tempfile.mkdtemp(prefix='omega4-v3-step2-'))
print('TEMPORARY_EVIDENCE',WORK,flush=True)
def git(*a):return subprocess.check_output(['git',*a],cwd=ROOT)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def state():
 names=set(git('ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0'))-{''}
 return {'files':{p:digest((ROOT/p).read_bytes()) for p in sorted(names)},'HEAD':git('rev-parse','HEAD').decode().strip(),'refs':git('show-ref').decode(),'status':git('status','--porcelain=v1').decode(),'index_sha256':digest((ROOT/'.git/index').read_bytes()),'unstaged_diff':git('diff').decode()}
def save(name,obj):
 with (WORK/name).open('x') as f:json.dump(obj,f,indent=2,sort_keys=True);f.write('\n')
expected=json.loads(Path('/tmp/omega4-v2-stage-audit-452aulfk/staged-hashes.json').read_text())
for e in expected:assert digest(git('show',':'+e['path']))==e['sha256']
canonical=''.join(f"{e['mode']}\0{e['path']}\0{e['git_blob']}\0{e['sha256']}\0{e['bytes']}\n" for e in expected).encode();assert digest(canonical)=='bd413067415932b53803d840181f3d132f31794291541199d0645696c2c1a83b'
assert set(git('diff','--name-only','-z').decode().split('\0'))-{''}=={'validation/validate.py'}
before=state();save('before.json',before);started=time.monotonic()
A=ROOT/'artifacts/runs/omega4-live-20261020-attempt002';N=ROOT/'artifacts/normalizations/omega4-attempt002-normalization-v1';V,R,O=[WORK/n for n in ('validation','reconciliation','operator')]
commands=[]
def cli(module,args,expected_code):
 command=[sys.executable,'-B','-m',module,*map(str,args)]
 result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
 commands.append({'command':command,'exit_code':result.returncode,'expected':expected_code,'stdout':result.stdout,'stderr':result.stderr})
 print('CLI',module,args[0] if args else '', 'exit',result.returncode,flush=True)
 assert result.returncode==expected_code,(command,result.returncode,result.stderr,result.stdout)
 return result
try:
 cli('validation.validate',['--run',A,'--normalized',N,'--output',V,'--ordinary-v3'],2)
 cli('reconciliation.reconcile',['--run',A,'--normalized',N,'--validated',V,'--output',R],2)
 cli('operator_delivery.build',['build','--acquisition',A,'--normalized',N,'--validated',V,'--reconciled',R,'--output',O,'--run-id','omega4-v3-temporary-verification'],2)
 checked=json.loads(cli('operator_delivery.build',['verify',O],0).stdout);save('commands.json',commands);save('operator-verification.json',checked)
 from validation import validate as v
 from reconciliation import reconcile as r
 from operator_delivery import build as b
 doc,report,validated,reconciled=b.load_verified(A,N,V,R)
 targets=validated['ordinary_claim_ids'];assert targets==['C01','C04','C05','C06']
 snapshots=[json.loads((O/f'batches/{i:03}.json').read_text()) for i in range(1,5)];final=snapshots[-1]
 print('TEMPORARY_OUTPUT_VERIFIED',checked,flush=True)
 def current(result,ident):return next(c for c in result['claims'] if c['claim_id']==ident and c.get('current_at_batch',True))
 amounts={'C01':10000,'C04':10000,'C05':100000,'C06':100001}
 details=[]
 for ident,amount in amounts.items():
  c=current(reconciled,ident);proof=c['ordinary_closure'];s=next(c for c in final['claims'] if c['claim_id']==ident)
  details.append({'claim_id':ident,'revision':c['revision'],'amount_cents':proof['amount_cents'],'request_id':proof['request_id'],'accepted_event_id':proof['accepted_event_id'],'settlement_event_id':proof['settlement_event_id'],'decision_ids':proof['decision_ids'],'status':s['status'],'known_paid_cents':s['known_paid_cents'],'balance_cents':s['balance_cents'],'incremental_authorized_cents':c['incremental_authorized_cents'],'attribution':'Derived unique revision/cost join; Finance source fields have claim/request but no revision/cost columns.','package_certification':proof['package_certification']})
 save('closure-results.json',{'claims':details,'snapshot_status_counts':dict(Counter(c['status'] for c in final['claims'])),'batches':[{'batch':i+1,'closed':sorted(c['claim_id'] for c in snap['claims'] if c['status']=='closed-reimbursed')} for i,snap in enumerate(snapshots)]})
 # Run unchanged repository regression tests, including create-only integration.
 suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_ordinary_closure*.py',top_level_dir=str(ROOT/'tests'))
 print('EXISTING_REGRESSION_TESTS',suite.countTestCases(),flush=True)
 with (WORK/'existing-tests.log').open('x') as log, patch('socket.create_connection',side_effect=AssertionError('Offline verification')):
  result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
 existing={'total':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),'failures':[{'test':str(t),'detail':e} for t,e in result.failures],'errors':[{'test':str(t),'detail':e} for t,e in result.errors],'skipped':result.skipped}
 save('existing-tests.json',existing);print('EXISTING_RESULTS',json.dumps(existing),flush=True)
 # Supplemental probes live only in this temporary runner and in-memory copies.
 original_digest=v.digest(v.encoded(doc));case_names=[];probes=unittest.TestSuite()
 def add(name,fn):
  probes.addTest(unittest.FunctionTestCase(fn,description=name));case_names.append(name)
 def assert_true(value,reason):
  if not value:raise AssertionError(reason)
 def evaluate(change):
  fixture=deepcopy(doc);change(fixture)
  result=r.evaluate(fixture,report,v.evaluate(fixture,report,ordinary_claim_ids=targets))
  assert v.digest(v.encoded(doc))==original_digest
  return fixture,result
 def settlement(fixture,ident):return next(x for x in v.rows(fixture,'Finance activity') if x['values'].get('Activity reference')==f'F-{ident}-1')
 def fields(row,fixture,updates):
  row['values'].update(updates)
  for column,cell in row['raw_cells'].items():
   label=fixture['workbook']['Finance activity']['headers'][column]
   if label in updates:cell.update(value=str(updates[label]),raw_xml_value=str(updates[label]))
 def mutation(ident,kind):
  def change(fixture):
   if kind in ('duplicate','conflict','invalid_conflict','refund'):
    row=deepcopy(settlement(fixture,ident));row['record_id']=f'synthetic:v3:{ident}:{kind}'
    if kind=='duplicate':fields(row,fixture,{'Arrival batch':4})
    elif kind=='conflict':fields(row,fixture,{'Arrival batch':4,'Amount (EUR)':str((amounts[ident]+1)/100)})
    elif kind=='invalid_conflict':fields(row,fixture,{'Arrival batch':0,'Amount (EUR)':str((amounts[ident]+1)/100)})
    else:fields(row,fixture,{'Arrival batch':3,'Activity reference':f'SYN-{ident}-refund','Activity type':'refund','Amount (EUR)':'1.00','Original activity reference':f'F-{ident}-1','Activity time (UTC)':'2026-09-13T12:00:00Z'})
    v.rows(fixture,'Finance activity').append(row)
   elif kind=='later_receipt':
    receipt=next(x for x in fixture['receipts'] if x['receipt_id']==f'R-COST-{ident[1:]}')
    receipt['issued_date']='2026-09-04';receipt['raw_fields']['Issued date']='2026-09-04';receipt['raw_text']=receipt['raw_text'].replace('2026-09-01','2026-09-04')
   elif kind=='late_approval':
    for row in v.rows(fixture,'Review ledger'):
     if row['values'].get('Subject reference')==ident:row['values']['Decision time (UTC)']='2026-09-13T12:00:00Z'
   elif kind=='correction':
    claim=deepcopy(next(x for x in fixture['claims'] if x['claim_id']==ident));claim.update(revision=2,arrival_batch=4,record_id=f'synthetic:v3:{ident}:r2');claim['raw_fields']['Revision']='2';fixture['claims'].append(claim)
   elif kind=='cancellation':
    claim=next(x for x in fixture['claims'] if x['claim_id']==ident);person=next(x['values'] for x in v.rows(fixture,'People') if x['values']['Employee ID']==claim['employee_id'])
    for action in ('requested','confirmed'):
     row=deepcopy(next(x for x in v.rows(fixture,'Travel cancellations') if x['values'].get('Cancellation activity reference')==f'TC018-{action}'))
     row['record_id']=f'synthetic:v3:{ident}:cancellation:{action}'
     row['values'].update({'Cancellation reference':f'SYN-TC-{ident}','Cancellation activity reference':f'SYN-TC-{ident}-{action}','Trip reference':claim['trip_id'],'Trip revision':claim['trip_revision'],'Acting employee or supervisor':claim['employee_id'] if action=='requested' else person['Supervisor'],'Initiation activity reference':None if action=='requested' else f'SYN-TC-{ident}-requested'})
     v.rows(fixture,'Travel cancellations').append(row)
   elif kind=='missing_merchant':
    v.rows(fixture,'Merchant payments')[:]=[x for x in v.rows(fixture,'Merchant payments') if x['values'].get('Expense reference')!=f'COST-{ident[1:]}']
   else:raise ValueError(kind)
  return change
 for ident,amount in amounts.items():
  def positive(ident=ident,amount=amount):
   claim=current(reconciled,ident);proof=claim['ordinary_closure'];snap=next(c for c in final['claims'] if c['claim_id']==ident)
   assert proof['amount_cents']==amount and proof['request_id']==f'REQ-{ident}' and proof['expense_id']==f'COST-{ident[1:]}'
   assert snap['status']=='closed-reimbursed' and snap['known_paid_cents']==amount and snap['balance_cents']==0
   assert claim['incremental_authorized_cents']==0
   assert proof['accepted_event_id']==f'F-{ident}-accepted' and proof['settlement_event_id']==f'F-{ident}-1'
  add(f'{ident}: independent exact certificate and attributed amount',positive)
  for kind in ('duplicate','conflict','invalid_conflict','refund','later_receipt','late_approval','correction','cancellation','missing_merchant'):
   def probe(ident=ident,kind=kind):
    fixture,result=evaluate(mutation(ident,kind));claim=current(result,ident)
    if kind=='duplicate':assert claim['ordinary_closure']['amount_cents']==amounts[ident]
    else:assert 'ordinary_closure' not in claim,(ident,kind,'unexpected closure')
    assert all('ordinary_closure' in current(result,other) for other in targets if other!=ident),(ident,kind,'unrelated selected case blocked')
   add(f'{ident}: {kind}',probe)
 def threshold():
  c5=current(validated,'C05');c6=current(validated,'C06')
  assert 'director' not in c5['claim_review']['required_roles'] and 'director' in c6['claim_review']['required_roles']
  assert c6['claim_review']['selected_decisions']['director']=='D-C06-1-claim-director-1'
 add('Exact EUR1000 versus EUR1000.01 director threshold',threshold)
 for mode in ('missing','wrong_actor'):
  def director(mode=mode):
   def change(fixture):
    ledger=v.rows(fixture,'Review ledger')
    if mode=='missing':ledger[:]=[x for x in ledger if x['values'].get('Decision reference')!='D-C06-1-claim-director-1']
    else:next(x for x in ledger if x['values'].get('Decision reference')=='D-C06-1-claim-director-1')['values']['Reviewer']='SYN-WRONG-ACTOR'
   fixture,result=evaluate(change);assert 'ordinary_closure' not in current(result,'C06')
  add(f'C06: director {mode}',director)
 for ident in ('C08','C18'):
  def held(ident=ident):
   claim=next(c for c in final['claims'] if c['claim_id']==ident);assert claim['status']=='held';assert 'ordinary_closure' not in current(reconciled,ident)
  add(f'{ident}: remains held under preset',held)
 def only_four():assert {c['claim_id'] for c in final['claims'] if c['status']=='closed-reimbursed'}==set(targets)
 add('No claim outside the four selected claims closes',only_four)
 def source_timing():
  for ident in targets:
   claim=current(validated,ident);req=next(q for q in reconciled['requests'] if q['claim_id']==ident)
   assert all(v.instant(x['decision_time'])<=v.instant(req['accepted_at']) for x in claim['claim_review']['imports'])
   assert all(f['status']=='supported' for x in claim['claim_review']['imports'] for f in x['findings'] if f['code']=='review_evidence_freshness')
 add('All four source approvals fresh and before acceptance',source_timing)
 old=json.loads((ROOT/'artifacts/reconciliations/omega4-attempt002-ordinary-closure-reconciliation-v2/reconciliation.v1.json').read_text())
 def unchanged_finance():
  assert reconciled['finance_events']==old['finance_events'];assert reconciled['finance_deliveries']==old['finance_deliveries']
  assert [c for c in reconciled['claims'] if c['claim_id'] not in ('C04','C05','C06')]==[c for c in old['claims'] if c['claim_id'] not in ('C04','C05','C06')]
 add('Finance admitted facts and all other claim findings unchanged versus v2',unchanged_finance)
 def batch_checks():
  assert all(c['status']=='held' for c in snapshots[0]['claims'])
  for snap in snapshots[1:]:assert {c['claim_id'] for c in snap['claims'] if c['status']=='closed-reimbursed'}==set(targets)
  assert checked['verified_snapshots']==4 and checked['actual_financial_closures']==4
 add('Four snapshot chain and no closure before batch2 settlement',batch_checks)
 print('SUPPLEMENTAL_CASES',probes.countTestCases(),flush=True)
 with (WORK/'supplemental-tests.log').open('x') as log,patch('socket.create_connection',side_effect=AssertionError('Offline verification')):
  supplemental_result=unittest.TextTestRunner(stream=log,verbosity=2).run(probes)
 supplemental={'total':supplemental_result.testsRun,'passed':supplemental_result.testsRun-len(supplemental_result.failures)-len(supplemental_result.errors)-len(supplemental_result.skipped),'failures':[{'test':str(t),'detail':e} for t,e in supplemental_result.failures],'errors':[{'test':str(t),'detail':e} for t,e in supplemental_result.errors],'skipped':supplemental_result.skipped,'case_names':case_names}
 save('supplemental-tests.json',supplemental);print('SUPPLEMENTAL_RESULTS',json.dumps({k:x for k,x in supplemental.items() if k!='case_names'}),flush=True)
 assert v.digest(v.encoded(doc))==original_digest
 success=result.wasSuccessful() and supplemental_result.wasSuccessful()
finally:
 after=state();save('after.json',after);preservation={'all_state_equal':before==after,'files_checked':len(before['files']),'index_unchanged':before['index_sha256']==after['index_sha256'],'unstaged_v3_edit_unchanged':before['unstaged_diff']==after['unstaged_diff'],'head_unchanged':before['HEAD']==after['HEAD'],'refs_unchanged':before['refs']==after['refs'],'staged_inventory_hash':digest(canonical),'elapsed_seconds':round(time.monotonic()-started,3)};save('preservation.json',preservation);print('PRESERVATION',json.dumps(preservation),flush=True)
print('CLOSURE_TOTALS',dict(Counter(c['status'] for c in final['claims'])),flush=True)
print('TOTAL_TESTS',existing['total']+supplemental['total'],'TOTAL_PASSED',existing['passed']+supplemental['passed'],flush=True)
if not success or not preservation['all_state_equal']:sys.exit(1)

from pathlib import Path
import hashlib,json,subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
ROOT=Path('/home/maxg/travel-expense-claim-omega4')
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
WORK=Path(tempfile.mkdtemp(prefix='omega4-v2-full-regression-'))
print('TEMPORARY_EVIDENCE',WORK,flush=True)
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def state():
 names=set(git('ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0'))-{''}
 return {'files':{name:digest(ROOT/name) for name in sorted(names) if (ROOT/name).is_file()},'status':git('status','--porcelain=v1').decode(),'head':git('rev-parse','HEAD').decode().strip(),'refs':git('show-ref').decode(),'index_sha256':digest(ROOT/'.git/index')}
def save(name,data):
 with (WORK/name).open('x') as f:json.dump(data,f,indent=2,sort_keys=True);f.write('\n')
before=state();save('before.json',before)
started=time.monotonic()
from validation import validate as v
from reconciliation import reconcile as r
from operator_delivery import build as b
import test_reconciliation as tr
import test_operator_delivery as to
import test_containment as tc
import test_shared_blockers as ts
A=ROOT/'artifacts/runs/omega4-live-20261020-attempt002'
N=ROOT/'artifacts/normalizations/omega4-attempt002-normalization-v1'
V,R,C=[WORK/name for name in ('validation-default','reconciliation-default','containment-default')]
try:
 with patch('socket.create_connection',side_effect=AssertionError('Full regression is offline')):
  validation=v.validate(A,N,V)
  print('FRESH_VALIDATION',validation['summary'],flush=True)
  reconciliation=r.reconcile(A,N,V,R)
  print('FRESH_RECONCILIATION',reconciliation['summary'],flush=True)
  b.build(A,N,V,R,C,'full-regression-default-containment',dependency_containment=True,prior_operator=ROOT/'artifacts/runs/omega4-attempt002-operator-v1')
  checked=b.verify(C);save('fixture-verification.json',checked)
  print('FRESH_FIXTURE_VERIFIED',checked,flush=True)
  # Only filesystem fixture defaults change, in memory. Validators, hash checks,
  # assertions, historical artifacts and fixture business data are untouched.
  tr.VALIDATED=V
  to.VALIDATED=V;to.RECONCILED=R
  tc.V=V;tc.R=R
  ts.SOURCE=C
  suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py',top_level_dir=str(ROOT/'tests'))
  print('DISCOVERED_TESTS',suite.countTestCases(),flush=True)
  result=unittest.TextTestRunner(stream=sys.stdout,verbosity=2).run(suite)
  test_report={'total':result.testsRun,'passes':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),'failures':[{'test':str(t),'traceback':e} for t,e in result.failures],'errors':[{'test':str(t),'traceback':e} for t,e in result.errors],'skipped':result.skipped,'successful':result.wasSuccessful()}
  save('tests.json',test_report)
  output=ROOT/'artifacts/runs/omega4-attempt002-ordinary-closure-operator-v2'
  verification=b.verify(output)
  snap=json.loads((output/'batches/004.json').read_text())
  c01=next(c for c in snap['claims'] if c['claim_id']=='C01')
  old=ROOT/'artifacts/runs/omega4-attempt002-ordinary-closure-operator-v1'
  oldsnap=json.loads((old/'batches/004.json').read_text())
  other_unchanged=[c for c in snap['claims'] if c['claim_id']!='C01']==[c for c in oldsnap['claims'] if c['claim_id']!='C01']
  save('closure-verification.json',{'standalone_verification':verification,'c01':c01,'unrelated_claims_equal_v1':other_unchanged,'held_other_claims':sum(c['status']=='held' for c in snap['claims'] if c['claim_id']!='C01')})
finally:
 after=state();save('after.json',after)
 preservation={'files_checked':len(before['files']),'file_bytes_and_inventory_unchanged':before['files']==after['files'],'status_unchanged':before['status']==after['status'],'head_unchanged':before['head']==after['head'],'refs_unchanged':before['refs']==after['refs'],'index_unchanged':before['index_sha256']==after['index_sha256'],'elapsed_seconds':round(time.monotonic()-started,3)}
 save('preservation.json',preservation)
 print('PRESERVATION',json.dumps(preservation),flush=True)
print('FINAL_TEST_COUNTS',json.dumps(test_report),flush=True)
print('FINAL_OPERATOR_VERIFICATION',json.dumps(verification),flush=True)
print('C01_STATUS',c01['status'],'PAID_CENTS',c01['known_paid_cents'],'BALANCE_CENTS',c01['balance_cents'],'UNRELATED_UNCHANGED',other_unchanged,flush=True)
if not test_report['successful'] or not all(preservation[k] for k in preservation if k.endswith('unchanged')):sys.exit(1)

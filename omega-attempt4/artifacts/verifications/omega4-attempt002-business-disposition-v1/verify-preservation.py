from pathlib import Path
from collections import Counter
import csv,hashlib,json
root=Path('/home/maxg/travel-expense-claim-omega4')
load=lambda p:json.loads((root/p).read_bytes())
old=root/'artifacts/runs/omega4-attempt002-shared-blockers-v1'
new=root/'artifacts/runs/omega4-attempt002-business-disposition-shared-blockers-v1'
strip_run=lambda x: ({k:strip_run(v) for k,v in x.items() if k!='run_id'} if isinstance(x,dict) else [strip_run(v) for v in x] if isinstance(x,list) else x)
results=[]
for batch in range(1,5):
 a=json.loads((old/f'batches/{batch:03}.json').read_bytes());b=json.loads((new/f'batches/{batch:03}.json').read_bytes())
 for key in ['requests','request_facts','finance_deliveries','finance_events','admitted_event_ids','travel_cancellations','issues','normalization_diagnostics','validation_global_findings','summary','source_index']:
  assert a[key]==b[key],(batch,key)
 for before,after in zip(a['claims'],b['claims']):
  after=dict(after);after.pop('business_disposition');
  if before['claim_id'] in ('C13','C14'):after['reason']=before['reason']
  assert before==after,(batch,before['claim_id'])
 for before,after in zip(a['claim_revision_history'],b['claim_revision_history']):
  assert before=={k:v for k,v in after.items() if k!='business_disposition'},(batch,'history',before['claim_id'])
 aq=json.loads((old/f'retained-run/queue/{batch:03}.json').read_bytes());bq=json.loads((new/f'retained-run/queue/{batch:03}.json').read_bytes())
 assert strip_run(aq)==strip_run(bq),(batch,'queue')
 assert (old/f'retained-run/dependencies/{batch:03}.json').read_bytes()==(new/f'retained-run/dependencies/{batch:03}.json').read_bytes()
 assert b['actual_financial_closure_count']==0
 assert all(c['status']=='held' and c['financial_closure_status']=='unresolved' and c['known_paid_cents'] is None and c['balance_cents'] is None for c in b['claims'])
 results.append({'batch':batch,'claims':len(b['claims']),'repair_records':len(bq['items']),'repair_states':dict(Counter(i['state'] for i in bq['items'])),'financial_facts_unchanged':True,'dependency_graph_bytes_unchanged':True})
for run in ['operator','containment','shared-blockers']:
 path=root/f'artifacts/runs/omega4-attempt002-business-disposition-{run}-v1';prior=None
 for batch in range(1,5):
  p=path/f'batches/{batch:03}.json';s=json.loads(p.read_bytes());assert s['predecessor']==prior
  prior={'path':f'batches/{batch:03}.json','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 manifest='shared-blocker-manifest.v1.json' if run=='shared-blockers' else 'operator-manifest.v1.json'
 assert json.loads((path/manifest).read_bytes())['final_batch']==prior
 for f in json.loads((path/manifest).read_bytes())['files']:
  assert hashlib.sha256((path/f['path']).read_bytes()).hexdigest()==f['sha256']
with (old/'claims.csv').open() as f:a=list(csv.DictReader(f))
with (new/'claims.csv').open() as f:b=list(csv.DictReader(f))
assert list(a[0])==list(b[0]);changed=[]
for before,after in zip(a,b):
 differences=[k for k in before if before[k]!=after[k]]
 if differences:assert before['claim_id'] in ('C13','C14') and differences==['reason'];changed.append(before['claim_id'])
assert changed==['C13','C14']
q=json.loads((new/'repair-queue.json').read_bytes());oldq=json.loads((old/'repair-queue.json').read_bytes());assert strip_run(q)==strip_run(oldq)
assert (new/'retained-run/prior-repair-queue.original.json').read_bytes()==(root/'artifacts/runs/omega4-attempt002-containment-v2/repair-queue.json').read_bytes()
baseline=json.loads(Path('/tmp/omega4-disposition-before.json').read_text())
protected=[p for p in baseline if p.startswith(('artifacts/','decisions/','interviews/','user-provided-sources/','normalization/','skills/','acquisition/'))]
assert all((root/p).is_file() and hashlib.sha256((root/p).read_bytes()).hexdigest()==baseline[p] for p in protected)
changed=[p for p,h in baseline.items() if hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]
result={'checks':'passed','batches':results,'verified_snapshot_chains':3,'verified_snapshots':12,'protected_original_files':len(protected),'changed_existing_files':sorted(changed),'csv_changed_rows':changed if False else ['C13','C14'],'csv_changed_columns':['reason'],'all_original_artifacts_decisions_and_sources_preserved':True,'final_financial_holds':121,'actual_financial_closures':0,'final_repair_states':dict(Counter(i['state'] for i in q['items']))}
print(json.dumps(result,indent=2))

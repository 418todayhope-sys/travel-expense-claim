"""Terminal disposition regressions: retained C13/C14 plus synthetic edges."""
from copy import deepcopy
import csv
import json
from pathlib import Path

import pytest

from test_ordinary import batches, synthetic
from travel_claim.expenses import load_expense_policy
from travel_claim.outputs import (project_claim_outputs, new_repair_queue, add_repair_item,
                                  write_repair_queue, load_repair_queue)


def retained():
    root = Path(__file__).parent
    parsed = json.loads((root / 'fixtures/retained_approval_records.json').read_text())
    parsed['expense_policy'] = load_expense_policy(root / 'fixtures/POL-2026.2-browser-copy.txt')
    parsed['event_clock'] = {'date': '2026-11-15', 'timezone': 'Europe/Amsterdam'}
    return parsed


@pytest.mark.parametrize('claim_id,status,reason', [
    ('C13', 'withdrawn', 'Employee withdrew before review.'),
    ('C14', 'rejected', 'Client work was cancelled.'),
])
def test_retained_terminal_claim_does_not_request_payment_authorization(claim_id, status, reason):
    result = batches(retained())[-1]
    workflow = result['domain']['ordinary_workflows'][claim_id]
    assert workflow['status'] == status and workflow['next_owner'] is None
    assert reason in workflow['reason']
    row = next(r for r in project_claim_outputs(result['snapshot']['claims'], result['domain']['repair_queue'])
               if r['claim_id'] == claim_id)
    assert row['status'] == status and row['next_owner'] is None and row['reason'] == workflow['reason']
    active = [i for i in result['domain']['repair_queue']['items'].values()
              if i['subject_id'] == claim_id and i['status'] == 'open']
    assert not any('obligation-missing' in i['item_id'] or
                   i['item_id'].endswith((':request_obligation', ':required_approvals', ':financial_closure'))
                   for i in active)


def pursuit(parsed, *, outcome='withdrawn'):
    from test_expenses import setfield
    parsed['records']['finance_events'] = []
    parsed['records']['reimbursement_requests'] = []
    if outcome == 'withdrawn':
        setfield(parsed['records']['claim_revisions'][0], 'Status', 'withdrawn')
        setfield(parsed['records']['claim_revisions'][0], 'Claim reason', 'SYNTHETIC employee withdrawal')
    else:
        for d in parsed['records']['decisions']:
            setfield(d, 'Outcome', 'reject')
            setfield(d, 'Reason', 'SYNTHETIC human rejection')
    return parsed


@pytest.mark.parametrize('outcome', ['withdrawn', 'rejected'])
@pytest.mark.parametrize('effect', ['payment', 'fully-refunded', 'request', 'cancellation'])
def test_terminal_source_label_does_not_hide_outstanding_financial_or_cancellation_work(outcome, effect):
    from test_completion import cancellation
    p = synthetic()
    old_events = deepcopy(p['records']['finance_events'])
    old_requests = deepcopy(p['records']['reimbursement_requests'])
    pursuit(p, outcome=outcome)
    if effect in {'payment','fully-refunded'}:
        p['records']['finance_events'] = old_events
        if effect == 'fully-refunded':
            from test_completion import activity
            from travel_claim.ordinary import fields
            payment=next(fields(e)['Activity reference'] for e in old_events if fields(e)['Activity type']=='settled')
            activity(p,'SYN-REFUND','refund',amount=100,
                     **{'Original activity reference':payment})
    elif effect == 'request': p['records']['reimbursement_requests'] = old_requests
    else:
        p['records']['reimbursement_requests'] = old_requests
        cancellation(p)
        p['records']['reimbursement_requests'] = []
    result = batches(p)[-1]
    w = result['domain']['ordinary_workflows']['SYN-C01']
    assert w['status'] != outcome and w['next_owner'] is not None
    assert any(i['status'] == 'open' and i['subject_id'] == 'SYN-C01'
               for i in result['domain']['repair_queue']['items'].values())
    if effect in {'payment','fully-refunded'}:
        assert result['finance_reconciliations']['SYN-C01']['net_confirmed_cents'] == (0 if effect=='fully-refunded' else 10000)
        assert result['finance_reconciliations']['SYN-C01']['admitted_events']
    if effect == 'cancellation': assert result['domain']['cancellation_records']


def test_scope_retirement_preserves_history_and_unrelated_repairs_and_reopens(tmp_path):
    from travel_claim.integration import _sync_finance_repairs, _sync_ordinary_repairs
    p = pursuit(synthetic())
    result = batches(p)[-1];domain = result['domain'];q = domain['repair_queue']
    w = domain['ordinary_workflows']['SYN-C01']
    refs = w['source_refs']
    for key in ['finance:finance-obligation-missing:SYN-C01:1', 'ordinary:SYN-C01:r1:required_approvals',
                'source-conflict:keep', 'independent-cancellation:keep']:
        add_repair_item(q,item_id=key,subject_type='claim',subject_id='SYN-C01',revision=1,
                       source_refs=refs,missing_or_return_reason='SYNTHETIC open issue',owner='Finance',
                       next_action='SYNTHETIC review',run_id='ordinary-test',batch_id='arrival-001')
    originals = deepcopy(q['items'])
    _sync_finance_repairs(domain,result['finance_reconciliations'],run_id='ordinary-test',batch_id='arrival-004')
    _sync_ordinary_repairs(domain,run_id='ordinary-test',batch_id='arrival-004')
    for key in ['finance:finance-obligation-missing:SYN-C01:1','ordinary:SYN-C01:r1:required_approvals']:
        item=q['items'][key]
        assert item['status']=='superseded'
        assert item['history'][:-1] == originals[key]['history']
        assert item['history'][-1]['event']=='repair-inapplicable'
        assert item['history'][-1]['source_refs']==refs
    for key in ['source-conflict:keep','independent-cancellation:keep']:
        assert q['items'][key]==originals[key]
    before=deepcopy(q)
    _sync_finance_repairs(domain,result['finance_reconciliations'],run_id='ordinary-test',batch_id='arrival-004')
    _sync_ordinary_repairs(domain,run_id='ordinary-test',batch_id='arrival-004')
    assert q==before
    path=tmp_path/'queue.json';write_repair_queue(q,path);assert load_repair_queue(path)==q
    w['status']='pending';w['next_owner']='Finance'
    _sync_finance_repairs(domain,result['finance_reconciliations'],run_id='ordinary-test',batch_id='arrival-005')
    _sync_ordinary_repairs(domain,run_id='ordinary-test',batch_id='arrival-005')
    assert q['items']['finance:finance-obligation-missing:SYN-C01:1']['status']=='open'
    assert q['items']['ordinary:SYN-C01:r1:required_approvals']['status']=='open'


def terminal_run(tmp_path):
    """Synthetic bound source capture for file-generation and tampering tests."""
    from test_offline_replay import _capture, SCHEMA
    from travel_claim.policy_evidence import create_policy_replay
    run,_ = _capture(tmp_path)
    path=run/'parsed-records.json';parsed=json.loads(path.read_text())
    manifest=json.loads((run/'sources.json').read_text())
    parsed['records']['decisions']=[];parsed['records']['finance_events']=[]
    for c in parsed['records']['claim_revisions']:
        c.update(source_id=manifest['files'][1]['source_id'],source_sha256=manifest['files'][1]['sha256'])
        c['fields'] += [{'label':'Status','value':'withdrawn'},
                        {'label':'Employee','value':'SYN-EMP'},
                        {'label':'Claim reason','value':'SYNTHETIC employee withdrew before review'}]
    for t in parsed['records']['trips']:
        t.update(source_id=manifest['files'][4]['source_id'],source_sha256=manifest['files'][4]['sha256'])
        t['values']['Employee ID']={'value':'SYN-EMP'}
    parsed['records']['people']=[dict(source_id=manifest['files'][4]['source_id'],
        source_sha256=manifest['files'][4]['sha256'],locator='SYNTHETIC People row 2',
        values={'Employee ID':{'value':'SYN-EMP'}})]
    path.write_text(json.dumps(parsed))
    replay=tmp_path/'terminal-policy'
    create_policy_replay(run,replay,run_id=replay.name,
        browser_policy=Path(__file__).parent/'fixtures/POL-2026.2-browser-copy.txt',schema_path=SCHEMA)
    return replay


def test_file_outputs_and_readiness_agree_and_reject_wrong_terminal_csv(tmp_path):
    from test_offline_replay import SCHEMA
    from test_readiness import _repo
    from travel_claim.readiness import validate_readiness
    run=terminal_run(tmp_path);repo=_repo(tmp_path)
    with (run/'claims.csv').open() as stream: rows=list(csv.DictReader(stream))
    assert rows[0]['status']=='withdrawn' and rows[0]['next_owner']==''
    assert rows[0]['reason']=='Clean business withdrawn: SYNTHETIC employee withdrew before review'
    assert rows[0]['reason'] in (run/'report.md').read_text()
    q=json.loads((run/'repair-queue.json').read_text())
    assert not any('obligation-missing' in k and i['status']=='open' for k,i in q['items'].items())
    result=validate_readiness(run,schema_path=SCHEMA,repo_dir=repo)
    assert next(c for c in result['checks'] if c['check']=='claims-csv-contract')['status']=='PASS'
    rows[0].update(next_owner='Finance',reason='Missing payment authorization')
    with (run/'claims.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
    bad=validate_readiness(run,schema_path=SCHEMA,repo_dir=repo)
    assert next(c for c in bad['checks'] if c['check']=='claims-csv-contract')['status']=='FAIL'


def test_readiness_rejects_actionable_authorization_repair_even_with_correct_terminal_csv(tmp_path):
    from test_offline_replay import SCHEMA
    from test_readiness import _repo
    from travel_claim.readiness import validate_readiness
    run=terminal_run(tmp_path);repo=_repo(tmp_path)
    q=load_repair_queue(run/'repair-queue.json')
    w=json.loads((run/'ordinary-workflow.json').read_text())['claims']['C-SYN-RUN']
    add_repair_item(q,item_id='finance:finance-obligation-missing:C-SYN-RUN:2',subject_type='claim',
        subject_id='C-SYN-RUN',revision=2,source_refs=w['source_refs'],missing_or_return_reason='Missing authorization',
        owner='Finance',next_action='Supply authorization',run_id=run.name,batch_id='arrival-002')
    write_repair_queue(q,run/'repair-queue.json')
    state=json.loads((run/'offline-replay-state.json').read_text());state['repair_queue']=q
    (run/'offline-replay-state.json').write_text(json.dumps(state))
    result=validate_readiness(run,schema_path=SCHEMA,repo_dir=repo)
    check=next(c for c in result['checks'] if c['check']=='claims-csv-contract')
    assert check['status']=='FAIL' and 'actionable missing-authorization' in check['detail']


@pytest.mark.parametrize('missing', ['withdrawal-reason','source-binding','human-rejection'])
def test_terminal_label_without_current_supported_disposition_keeps_repairs(missing):
    from test_expenses import setfield
    p=pursuit(synthetic());claim=p['records']['claim_revisions'][0]
    if missing=='withdrawal-reason': setfield(claim,'Claim reason','')
    elif missing=='source-binding': claim['source_sha256']='0'*64
    else:
        setfield(claim,'Status','rejected');p['records']['decisions']=[]
    result=batches(p)[-1];w=result['domain']['ordinary_workflows']['SYN-C01']
    assert w['status'] not in {'withdrawn','rejected'} and w['next_owner'] is not None
    assert any(i['status']=='open' and 'obligation-missing' in i['item_id']
               for i in result['domain']['repair_queue']['items'].values())


@pytest.mark.parametrize('status', ['closed-reimbursed','closed-no-payment','withdrawn','rejected','held','pending'])
def test_terminal_projection_never_borrows_an_unrelated_repair_reason(status):
    c=dict(claim_id='SYN-X',revision=1,trip_id='SYN-T',status=status,allowed_cents=0,paid_cents=0,
           balance_cents=0,next_owner='Finance' if status in {'held','pending'} else None,reason='Source-backed disposition')
    q=new_repair_queue()
    add_repair_item(q,item_id='synthetic',subject_type='claim',subject_id='SYN-X',revision=1,
                   source_refs=['synthetic@hash#row'],missing_or_return_reason='Actionable repair',owner='Employee',
                   next_action='Supply evidence',run_id='synthetic',batch_id='arrival-001')
    row=project_claim_outputs([c],q)[0]
    if status in {'held','pending'}:
        assert row['next_owner']=='Employee' and row['reason']=='Actionable repair'
    else:
        assert row['next_owner'] is None and row['reason']==c['reason']

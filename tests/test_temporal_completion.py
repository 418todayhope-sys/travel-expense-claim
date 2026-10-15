"""Step 188 reproductions and Step 189 checks; all changed facts are SYNTHETIC."""
from copy import deepcopy

import pytest

from test_completion import activity, cancellation
from test_ordinary import synthetic, batches, workflow, stages
from test_expenses import setfield
from travel_claim.ordinary import connect_claim, fields, ref, table


def changed_paid_basis():
    """An admitted resolution predates a later receipt-source correction."""
    p = synthetic()
    activity(p, 'SYN-OLD-RES', 'resolution', batch=2,
             time='2026-09-12T13:00:00', obligation=100,
             **{'Resolved activity references': 'F-SYN-C01-accepted'})
    for d in p['records']['decisions']:
        setfield(d, 'Arrival batch', 2)
        setfield(d, 'Decision time (UTC)', '2026-09-12T14:00:00')
    paid = batches(p)[1]
    assert workflow(paid)['status'] == 'closed-reimbursed'
    receipt = p['records']['receipts'][0]
    receipt['source_sha256'] = 'c' * 64
    p['source_observations'].append(dict(source_id=receipt['source_id'], sha256='c' * 64,
                                        status='read', missing_scope=[]))
    for d in p['records']['decisions']:
        setfield(d, 'Decision reference', fields(d)['Decision reference'] + '-new')
        setfield(d, 'Source revisions', ref(p['records']['claim_revisions'][0]) + '\nPOL-2026.2')
        setfield(d, 'Arrival batch', 3)
        setfield(d, 'Decision time (UTC)', '2026-09-14T12:00:00')
    for packet in table(p, 'review_packets', 'Review packets'):
        setfield(packet, 'Decision reference', fields(packet)['Decision reference'] + '-new')
    setfield(p['records']['reimbursement_requests'][0], 'Decision references',
             '\n'.join(fields(d)['Decision reference'] for d in p['records']['decisions']))
    return p, paid


def recheck(p, paid, *, prior=None, batch=3, events=None):
    return connect_claim(parsed=p,
        claim=deepcopy(paid['domain']['revision_history']['claim']['SYN-C01']['revisions'][0]),
        decisions=p['records']['decisions'],
        finance_events=events if events is not None else paid['domain']['finance_records'],
        finance=deepcopy(paid['finance_reconciliations']['SYN-C01']), cancellations=[],
        arrival_batch=batch, source_observations=p['source_observations'],
        prior_finance=paid['finance_reconciliations']['SYN-C01'],
        budget_data=paid['domain']['budget'], prepaid_data=paid['domain']['budget']['cost_attribution'],
        prior_workflow=prior if prior is not None else workflow(paid))


def test_step188_resolution_before_material_receipt_change_cannot_close():
    p, paid = changed_paid_basis()
    current = recheck(p, paid)
    assert current['claim_approval']['material_same_revision']
    assert current['claim_approval']['approved']
    assert current['status'] == 'pending'
    assert stages(current)['finance_resolution']['status'] == 'BLOCKED'
    assert current['finance']['admitted_events'] == paid['finance_reconciliations']['SYN-C01']['admitted_events']


def test_step188_cancellation_after_paid_before_acceptance_requires_resolution():
    p = synthetic(); cancellation(p)
    for e in p['records']['finance_events']:
        if fields(e)['Activity type'] == 'settled':
            setfield(e, 'Activity time (UTC)', '2026-09-04T12:00:00')
    result = batches(p)[-1]
    assert workflow(result)['status'] == 'pending'
    assert stages(workflow(result))['finance_resolution']['status'] == 'BLOCKED'
    assert result['finance_reconciliations']['SYN-C01']['net_confirmed_cents'] == 10000


def employee_dates(p, paid='2026-11-16', submitted='2026-11-16'):
    p['event_clock'] = {'date': '2026-11-15', 'timezone': 'Europe/Amsterdam'}
    p['case_clock'] = None
    claim = p['records']['claim_revisions'][0]
    setfield(claim, 'Submitted date', submitted)
    claim['text'] = claim['text'].replace('2026-09-01', submitted)
    for r in table(p, 'merchant_payments', 'Merchant payments'):
        setfield(r, 'Paid date', paid)
    setfield(p['records']['trips'][0], 'End date', '2026-11-17')
    return p


def test_step188_future_employee_payment_and_submission_cannot_close():
    p = employee_dates(synthetic())
    result = batches(p)[-1]; current = workflow(result)
    assert current['expense_calculation']['status'] == 'BLOCKED'
    assert current['allowed_cents'] is None
    assert current['status'] == 'pending'
    assert 'future' in current['lines'][0]['reason'].lower()
    assert result['finance_reconciliations']['SYN-C01']['net_confirmed_cents'] == 10000


def resolution_for_basis(p, *, identity='SYN-CURRENT-RES', batch=3, source_versions=None):
    return activity(p, identity, 'resolution', batch=batch,
        time='2026-09-13T13:00:00' if batch==3 else '2026-09-14T13:00:00', obligation=100,
        **{'Resolved activity references':'F-SYN-C01-accepted',
           'Source revisions': ref(p['records']['receipts'][0]) if source_versions is None else source_versions})


def test_current_source_bound_resolution_allows_corrected_basis_without_erasing_cash():
    p, paid = changed_paid_basis()
    resolution = resolution_for_basis(p)
    events = paid['domain']['finance_records'] + [resolution]
    current = recheck(p, paid, events=events)
    assert current['status']=='closed-reimbursed'
    assert current['financial_basis']['latest_change']['arrival_batch']==3
    assert current['financial_basis']['latest_change']['source_refs']==[ref(p['records']['receipts'][0])]
    assert current['finance']['net_confirmed_cents']==10000
    for identity,event in paid['finance_reconciliations']['SYN-C01']['admitted_events'].items():
        assert current['finance']['admitted_events'][identity]==event
    assert 'SYN-OLD-RES' in current['finance']['admitted_events']


@pytest.mark.parametrize('versions', ['', 'unrelated', '0'*64])
def test_later_resolution_without_current_source_version_is_not_authority(versions):
    p, paid = changed_paid_basis()
    resolution=resolution_for_basis(p,source_versions=versions)
    current=recheck(p,paid,events=paid['domain']['finance_records']+[resolution])
    assert current['status']=='pending'
    assert stages(current)['finance_resolution']['status']=='BLOCKED'


def test_old_resolution_redelivery_does_not_refresh_its_evidence_authority():
    p, paid=changed_paid_basis()
    replay=deepcopy(next(e for e in paid['domain']['finance_records'] if fields(e)['Activity reference']=='SYN-OLD-RES'))
    setfield(replay,'Arrival batch',3)
    current=recheck(p,paid,events=paid['domain']['finance_records']+[replay])
    assert current['status']=='pending'
    assert current['finance']['net_confirmed_cents']==10000


def test_latest_material_change_invalidates_previously_current_resolution():
    p,paid=changed_paid_basis();resolution=resolution_for_basis(p)
    events=paid['domain']['finance_records']+[resolution]
    first=recheck(p,paid,events=events)
    assert first['status']=='closed-reimbursed'
    receipt=p['records']['receipts'][0];receipt['source_sha256']='d'*64
    p['source_observations'].append(dict(source_id=receipt['source_id'],sha256='d'*64,status='read',missing_scope=[]))
    for d in p['records']['decisions']:setfield(d,'Arrival batch',4)
    second=recheck(p,paid,prior=first,batch=4,events=events)
    assert second['status']=='pending'
    assert second['financial_basis']['latest_change']['arrival_batch']==4
    assert len(second['financial_basis']['changes'])==2
    newer=resolution_for_basis(p,identity='SYN-NEWEST-RES',batch=4)
    final=recheck(p,paid,prior=second,batch=4,events=events+[newer])
    assert final['status']=='closed-reimbursed'
    assert final['financial_basis']['digest']==second['financial_basis']['digest']


def test_unchanged_and_unrelated_evidence_does_not_invalidate_resolution():
    p=synthetic();paid=batches(p)[1]
    unrelated=deepcopy(p['records']['receipts'][0]);unrelated['locator']='SYNTHETIC unrelated receipt';setfield(unrelated,'Receipt reference','UNRELATED')
    setfield(unrelated,'Expense reference','UNRELATED-COST');p['records']['receipts'].append(unrelated)
    current=recheck(p,paid)
    assert current['status']=='closed-reimbursed'
    assert current['financial_basis']['latest_change'] is None


@pytest.mark.parametrize('confirmation,payment,needs_resolution', [
    ('2026-09-05T12:00:00','2026-09-12T12:00:00',False),
    ('2026-09-05T12:00:00','2026-09-04T12:00:00',True),
    ('2026-09-05T12:00:00','2026-09-05T12:00:00',True),
    ('2026-09-13T12:00:00','2026-09-12T12:00:00',True),
])
def test_cancellation_chronology_uses_acceptance_and_cash_history(confirmation,payment,needs_resolution):
    p=synthetic();cancellation(p,confirmation=confirmation,reviews='2026-09-14T14:00:00')
    for e in p['records']['finance_events']:
        if fields(e)['Activity type']=='settled':setfield(e,'Activity time (UTC)',payment)
    result=batches(p)[-1]
    assert workflow(result)['status']==('pending' if needs_resolution else 'closed-reimbursed')
    if needs_resolution:
        activity(p,'SYN-CANCELLATION-RESOLUTION','resolution',batch=4,time='2026-09-14T13:00:00',obligation=100,
            **{'Travel cancellation reference':'TC-SYN','Resolved activity references':'F-SYN-C01-accepted'})
        resolved=batches(p)[-1]
        assert workflow(resolved)['status']=='closed-reimbursed'
        assert resolved['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000
        assert resolved['domain']['cancellation_state']['admitted_records']==result['domain']['cancellation_state']['admitted_records']


@pytest.mark.parametrize('paid,submitted,expected',[
    ('2026-11-14','2026-11-14','PASS'),
    ('2026-11-15','2026-11-15','PASS'),
    ('2026-11-16','2026-11-16','BLOCKED'),
    ('2026-11-16','2026-11-15','BLOCKED'),
    ('2026-11-14','2026-11-16','BLOCKED'),
])
def test_employee_calendar_dates_before_on_after_case_date(paid,submitted,expected):
    p=employee_dates(synthetic(),paid,submitted);r=batches(p)[-1];w=workflow(r)
    assert w['expense_calculation']['status']==expected
    checks=w['lines'][0]['employee_date_checks']
    assert checks and all(c['case_date']=='2026-11-15' and c['timezone']=='Europe/Amsterdam' for c in checks)
    if expected=='BLOCKED':
        assert w['status']=='pending' and w['allowed_cents'] is None
        assert any(c['status']=='BLOCKED' for c in checks)
    assert r['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000


def test_future_cost_submission_is_not_hidden_by_earlier_claim_date():
    p=synthetic();claim=p['records']['claim_revisions'][0]
    claim['text']=claim['text'].replace('2026-09-01','2026-11-16')
    p['event_clock']={'date':'2026-11-15','timezone':'Europe/Amsterdam'}
    w=workflow(batches(p)[-1])
    assert w['status']=='pending'
    assert 'Cost first submission date is future' in w['lines'][0]['reason']


@pytest.mark.parametrize('clock,date_value,expected',[
    ('2026-11-14T23:30:00Z','2026-11-14','PASS'),
    ('2026-11-14T23:30:00Z','2026-11-15','BLOCKED'),
    ('2026-11-14T22:30:00Z','2026-11-15','BLOCKED'),
])
def test_employee_dates_use_policy_timezone_and_do_not_invent_same_day_instants(clock,date_value,expected):
    p=employee_dates(synthetic(),date_value,date_value);p['event_clock']=clock
    w=workflow(batches(p)[-1])
    assert w['expense_calculation']['status']==expected
    if expected=='BLOCKED':assert w['status']=='pending'


def test_second_change_cannot_reuse_reviews_from_before_latest_basis():
    p,paid=changed_paid_basis();first_resolution=resolution_for_basis(p)
    events=paid['domain']['finance_records']+[first_resolution]
    first=recheck(p,paid,events=events)
    receipt=p['records']['receipts'][0];receipt['source_sha256']='d'*64
    p['source_observations'].append(dict(source_id=receipt['source_id'],sha256='d'*64,status='read',missing_scope=[]))
    newer=resolution_for_basis(p,identity='SYN-NEWEST-RES',batch=4)
    current=recheck(p,paid,prior=first,batch=4,events=events+[newer])
    assert current['status']=='pending'
    assert stages(current)['required_approvals']['status']=='BLOCKED'


def test_batch_integration_reopens_then_closes_only_with_current_basis_authority():
    from travel_claim.integration import integrate_arrival_batch
    p,paid=changed_paid_basis();sealed_before=deepcopy(paid['snapshot'])
    def integrate(batch,prior):
        return integrate_arrival_batch(p,arrival_batch=batch,run_id='ordinary-test',batch_id=f'arrival-{batch:03d}',
            source_binding={'path':'sources.json','sha256':'a'*64},
            predecessor={'path':f'batches/arrival-{batch-1:03d}.json','sha256':'b'*64},
            prior_result=prior,source_observations=p['source_observations'])
    held=integrate(3,paid)
    assert workflow(held)['status']=='pending'
    assert stages(workflow(held))['finance_resolution']['status']=='BLOCKED'
    resolution_for_basis(p,batch=4)
    new_decisions=deepcopy(p['records']['decisions'])
    new_packets=deepcopy(table(p,'review_packets','Review packets'))
    for d in new_decisions:
        setfield(d,'Decision reference',fields(d)['Decision reference']+'-current')
        setfield(d,'Arrival batch',4);setfield(d,'Decision time (UTC)','2026-09-14T14:00:00')
    for packet in new_packets:setfield(packet,'Decision reference',fields(packet)['Decision reference']+'-current')
    p['records']['decisions'].extend(new_decisions)
    table(p,'review_packets','Review packets').extend(new_packets)
    setfield(p['records']['reimbursement_requests'][0],'Decision references','\n'.join(fields(d)['Decision reference'] for d in new_decisions))
    final=integrate(4,held)
    assert workflow(final)['status']=='closed-reimbursed'
    assert final['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000
    for identity,event in paid['finance_reconciliations']['SYN-C01']['admitted_events'].items():
        assert final['finance_reconciliations']['SYN-C01']['admitted_events'][identity]==event
    assert paid['snapshot']==sealed_before
    assert workflow(held)['status']=='pending'


def test_future_employee_evidence_does_not_hold_independent_valid_claim():
    import json
    p=synthetic();good=json.loads(json.dumps(p).replace('SYN-C01','SYN-C02').replace('COST-01','COST-02'))
    employee_dates(p)
    p['records']['finance_events']=[];p['records']['reimbursement_requests']=[]
    p['records']['merchant_payments']=deepcopy(table(p,'merchant_payments','Merchant payments')+table(good,'merchant_payments','Merchant payments'))
    p['records']['review_packets']=deepcopy(table(p,'review_packets','Review packets')+table(good,'review_packets','Review packets'))
    for key in ['claim_revisions','receipts','decisions','finance_events','reimbursement_requests','closure_authorities']:
        p['records'][key].extend(deepcopy(good['records'][key]))
    result=batches(p)[-1]
    assert workflow(result)['status']=='pending'
    assert workflow(result,'SYN-C02')['status']=='closed-reimbursed'
    assert result['finance_reconciliations']['SYN-C02']['net_confirmed_cents']==10000


@pytest.mark.parametrize('revision',[None,2])
def test_current_source_links_do_not_replace_explicit_current_revision_authority(revision):
    p,paid=changed_paid_basis();event=resolution_for_basis(p)
    setfield(event,'Claim revision',revision)
    current=recheck(p,paid,events=paid['domain']['finance_records']+[event])
    assert current['status']=='pending'
    assert current['finance']['net_confirmed_cents']==10000


def test_missing_material_basis_context_is_blocked_not_inferred_from_revision():
    from travel_claim.completion import financial_dependencies
    p,paid=changed_paid_basis()
    f=paid['finance_reconciliations']['SYN-C01']
    result=financial_dependencies(finance=f,revision=1,allowed=10000,cancellations=[],
        review={'material_same_revision':True})
    assert result['status']=='BLOCKED'

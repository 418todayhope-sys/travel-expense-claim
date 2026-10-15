"""POL-2026.2 completion regressions; all changed facts are SYNTHETIC."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from test_ordinary import synthetic, batches, workflow, stages
from test_expenses import setfield
from test_revalidation import corrected
from travel_claim.approvals import table, fields


def activity(p, identity, kind, batch=3, time='2026-09-13T12:00:00', amount=None, obligation=None, revision=1, **extra):
    event=deepcopy(p['records']['finance_events'][0])
    for key in ['Amount (EUR)','Obligation (EUR)','Original activity reference']:
        event['values'].pop(key,None)
    values={'Activity reference':identity,'Activity type':kind,'Arrival batch':batch,
            'Activity time (UTC)':time,'Claim revision':revision}
    if amount is not None:values['Amount (EUR)']=amount
    if obligation is not None:values['Obligation (EUR)']=obligation
    values.update(extra)
    for key,value in values.items():setfield(event,key,value)
    p['records']['finance_events'].append(event)
    return event


def cancellation(p, *, confirmation='2026-09-05T12:00:00', amount='100.00', reviews='2026-09-06T12:00:00'):
    source=json.loads((Path(__file__).parent/'fixtures/retained_finance_records.json').read_text())
    rows=[deepcopy(r) for r in source['records']['cancellation_activities'] if fields(r).get('Cancellation reference')=='TC018'][:2]
    for r in rows:
        r.update(source_id='synthetic-travel-registers-workbook',source_sha256=p['records']['trips'][0]['source_sha256'])
        action=fields(r)['Action']
        values={'Cancellation activity reference':'SYN-CANCEL-'+action,'Cancellation reference':'TC-SYN',
            'Trip reference':'T01','Trip revision':1,'Permit reference':None,'Permit revision':None,
            'Cancelled subject':'trip','Arrival batch':1 if confirmation<'2026-09-11' else 3,
            'Acting employee or supervisor':'EMP-01' if action=='requested' else 'SUP-01',
            'Activity time (UTC)':'2026-09-04T12:00:00' if action=='requested' else confirmation,
            'Initiation activity reference':None if action=='requested' else 'SYN-CANCEL-requested',
            'Effective time (UTC)':None if action=='requested' else confirmation}
        for key,value in values.items():setfield(r,key,value)
    p['records']['cancellation_activities']=rows
    claim=p['records']['claim_revisions'][0]
    for key,value in {'Authorizing Finance officer':'FIN-01','Applies to claim':'SYN-C01','Applies to revision':'1',
        'Expense reference':'COST-01','Allowed original amount':amount,'Exception reason':'SYNTHETIC cancellation disposition',
        'Covered issues':'travel_cancellation','Travel cancellation reference':'TC-SYN'}.items():setfield(claim,key,value)
    for d in p['records']['decisions']:
        setfield(d,'Decision time (UTC)',reviews)
        setfield(d,'Arrival batch',1 if confirmation<'2026-09-11' else 4)
        if confirmation>='2026-09-11':setfield(d,'Source revisions',claim['source_sha256']+'\nPOL-2026.2')
    for packet in table(p,'review_packets','Review packets'):setfield(packet,'Travel cancellation references','TC-SYN')
    setfield(p['records']['reimbursement_requests'][0],'Amount (EUR)',amount)
    return rows


def test_verified_policy_date_can_close_without_legacy_synthetic_authority_tables():
    p=synthetic();p['records'].pop('workflow_policy_rules');p['records'].pop('closure_authorities')
    p['case_clock']=None;p['event_clock']={'date':'2026-11-15','timezone':'Europe/Amsterdam'}
    assert workflow(batches(p)[-1])['status']=='closed-reimbursed'


def test_supported_personal_zero_closes_without_inventing_finance_request():
    p=synthetic();setfield(p['records']['receipts'][0],'Category','personal')
    p['records']['finance_events']=[];p['records']['reimbursement_requests']=[]
    r=batches(p)[-1];w=workflow(r)
    assert w['allowed_cents']==0 and w['status']=='closed-no-payment'
    assert w['request'] is None and w['balance_cents']==0
    assert r['finance_reconciliations']['SYN-C01']['admitted_events']=={}


def test_correction_after_payment_requires_explicit_finance_resolution_even_at_same_total():
    p=synthetic();corrected(p)
    old=deepcopy(p['records']['decisions'])
    for d in old:
        setfield(d,'Revision',2);setfield(d,'Arrival batch',3)
        setfield(d,'Decision reference',fields(d)['Decision reference']+'-r2');setfield(d,'Decision time (UTC)','2026-09-14T12:00:00')
    packets=deepcopy(table(p,'review_packets','Review packets'))
    for packet in packets:setfield(packet,'Decision reference',fields(packet)['Decision reference']+'-r2')
    table(p,'review_packets','Review packets').extend(packets);p['records']['decisions'].extend(old)
    request=deepcopy(p['records']['reimbursement_requests'][0]);setfield(request,'Revision',2);setfield(request,'Arrival batch',3)
    setfield(request,'Decision references','\n'.join(fields(d)['Decision reference'] for d in old))
    p['records']['reimbursement_requests'].append(request)
    authority=deepcopy(p['records']['closure_authorities'][0]);setfield(authority,'Revision',2);setfield(authority,'Arrival batch',3)
    p['records']['closure_authorities'].append(authority)
    activity(p,'SYN-ADJUST','adjustment',obligation=100,revision=2)
    result=batches(p)[-1]
    assert result['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000
    assert workflow(result)['status']=='pending'
    activity(p,'SYN-RESOLVE','resolution',batch=4,time='2026-09-14T13:00:00',obligation=100,revision=2,
        **{'Resolved activity references':'F-SYN-C01-accepted\nSYN-ADJUST'})
    # Use the actual immutable accepted identity from the synthetic fixture.
    accepted=next(fields(e)['Activity reference'] for e in p['records']['finance_events'] if fields(e)['Activity type']=='accepted')
    setfield(p['records']['finance_events'][-1],'Resolved activity references',accepted+'\nSYN-ADJUST')
    for d in old:setfield(d,'Arrival batch',4);setfield(d,'Decision time (UTC)','2026-09-14T14:00:00')
    assert workflow(batches(p)[-1])['status']=='closed-reimbursed'


def test_pre_acceptance_business_cancellation_can_complete_without_extra_resolution():
    p=synthetic();cancellation(p)
    result=batches(p)[-1]
    assert workflow(result)['status']=='closed-reimbursed'
    assert workflow(result)['permit_approval']['arrangement_authorized'] is False
    assert result['snapshot']['travel_cancellations'][0]['financial_status']=='resolved'


def test_post_acceptance_cancellation_requires_current_bound_resolution():
    p=synthetic();cancellation(p,confirmation='2026-09-13T12:00:00',reviews='2026-09-14T14:00:00')
    assert workflow(batches(p)[-1])['status']=='pending'
    activity(p,'SYN-CANCEL-RESOLVE','resolution',batch=4,time='2026-09-14T13:00:00',obligation=100,
        **{'Travel cancellation reference':'TC-SYN','Resolved activity references':'F-SYN-C01-accepted'})
    assert workflow(batches(p)[-1])['status']=='closed-reimbursed'


def test_pre_confirmation_review_packet_is_not_current_cancellation_authority():
    p=synthetic();cancellation(p,reviews='2026-09-04T13:00:00')
    r=batches(p)[-1]
    assert not workflow(r)['claim_approval']['approved']
    assert workflow(r)['status']=='pending'


def test_pending_transfer_can_be_cleared_only_by_explicit_admitted_resolution():
    from travel_claim.integration import integrate_arrival_batch
    def batches(p):
        prior=None;results=[]
        for number in p['arrival_batches']:
            prior=integrate_arrival_batch(p,arrival_batch=number,run_id='synthetic',batch_id=f'arrival-{number:03d}',
                source_binding={'path':'sources.json','sha256':'a'*64},prior_result=prior,
                predecessor={'path':'previous.json','sha256':'b'*64} if prior else None,
                source_observations=p['source_observations'],source_classifications={'synthetic_pending':'pending_transfer'})
            results.append(prior)
        return results
    p=synthetic();activity(p,'SYN-PENDING','synthetic_pending',amount=100)
    assert workflow(batches(p)[-1])['status']=='pending'
    activity(p,'SYN-PENDING-RESOLVE','resolution',batch=4,time='2026-09-14T13:00:00',obligation=100,
        **{'Resolved activity references':'SYN-PENDING'})
    for d in p['records']['decisions']:
        setfield(d,'Arrival batch',4);setfield(d,'Decision time (UTC)','2026-09-14T14:00:00')
    assert workflow(batches(p)[-1])['status']=='closed-reimbursed'


def test_request_cancellation_releases_commitment_but_never_refunds_cash():
    p=synthetic();activity(p,'SYN-REQUEST-CANCEL','cancelled')
    f=batches(p)[-1]['finance_reconciliations']['SYN-C01']
    assert f['recorded_obligation']['amount_cents']==0
    assert f['net_confirmed_cents']==10000 and f['recorded_ledger_balance_cents']==-10000


def test_report_uses_verified_date_precision_instead_of_claiming_missing_clock():
    from travel_claim.revalidation import verification_document
    r=batches(synthetic())[-1]
    _,text=verification_document(r['domain'],[],run_id='synthetic')
    assert 'authoritative case clock remains unconfirmed' not in text


def test_unverified_finance_obligation_cannot_close_but_cash_is_preserved():
    p=synthetic()
    accepted=next(e for e in p['records']['finance_events'] if fields(e)['Activity type']=='accepted')
    accepted['source_sha256']='0'*64
    r=batches(p)[-1]
    assert workflow(r)['status']=='pending'
    assert r['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000


@pytest.mark.parametrize('paid,balance', [(40,6000),(120,-2000)])
def test_partial_or_excess_payment_never_closes_and_duplicates_do_not_change_cash(paid,balance):
    p=synthetic()
    for e in p['records']['finance_events']:
        if fields(e)['Activity type']=='settled':setfield(e,'Amount (EUR)',paid)
    if paid>100:
        for d in p['records']['decisions']:
            setfield(d,'Arrival batch',3);setfield(d,'Decision time (UTC)','2026-09-14T14:00:00')
    r=batches(p)[-1];w=workflow(r)
    assert w['status']=='pending' and w['balance_cents']==balance
    assert r['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==paid*100
    assert len(r['finance_reconciliations']['SYN-C01']['confirmed_payment_event_ids'])==1


def test_late_transfer_reopens_closed_case_and_preserves_prior_snapshot():
    p=synthetic();activity(p,'SYN-LATE','settled',batch=4,time='2026-09-14T12:00:00',amount=10)
    results=batches(p)
    assert workflow(results[1])['status']=='closed-reimbursed'
    assert workflow(results[-1])['status']=='pending'
    assert results[-1]['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==11000
    assert results[1]['snapshot']['claims'][0]['paid_cents']==10000


def test_post_payment_zero_adjustment_requires_linked_refund_resolution_and_current_reviews():
    p=synthetic();setfield(p['records']['receipts'][0],'Category','personal')
    setfield(p['records']['reimbursement_requests'][0],'Amount (EUR)',0)
    activity(p,'SYN-ZERO','adjustment',obligation=0)
    payment=next(fields(e)['Activity reference'] for e in p['records']['finance_events'] if fields(e)['Activity type']=='settled')
    refund=activity(p,'SYN-REFUND','refund',amount=100,**{'Original activity reference':payment})
    assert workflow(batches(p)[-1])['status']=='pending'
    activity(p,'SYN-ZERO-RESOLVE','resolution',batch=4,time='2026-09-14T13:00:00',obligation=0,
        **{'Resolved activity references':'SYN-ZERO'})
    for d in p['records']['decisions']:
        setfield(d,'Arrival batch',4);setfield(d,'Decision time (UTC)','2026-09-14T14:00:00')
    r=batches(p)[-1]
    assert workflow(r)['status']=='closed-no-payment'
    assert r['finance_reconciliations']['SYN-C01']['confirmed_payment_cents']==10000
    assert r['finance_reconciliations']['SYN-C01']['confirmed_refund_cents']==10000
    duplicate=deepcopy(refund);setfield(duplicate,'Arrival batch',4);p['records']['finance_events'].append(duplicate)
    assert workflow(batches(p)[-1])['status']=='closed-no-payment'


@pytest.mark.parametrize('change', ['stale','unlinked','wrong-cancellation','early'])
def test_cancellation_resolution_must_bind_current_revision_target_and_time(change):
    p=synthetic();cancellation(p,confirmation='2026-09-13T12:00:00',reviews='2026-09-14T14:00:00')
    e=activity(p,'SYN-RES','resolution',batch=4,time='2026-09-14T13:00:00',obligation=100,
        **{'Travel cancellation reference':'TC-SYN','Resolved activity references':'F-SYN-C01-accepted'})
    if change=='stale':setfield(e,'Claim revision',2)
    if change=='unlinked':setfield(e,'Resolved activity references','unrelated')
    if change=='wrong-cancellation':setfield(e,'Travel cancellation reference','TC-OTHER')
    if change=='early':setfield(e,'Activity time (UTC)','2026-09-12T13:00:00')
    assert workflow(batches(p)[-1])['status']=='pending'


def test_pending_business_cancellation_never_changes_finance_or_establishes_disposition():
    p=synthetic();rows=cancellation(p);p['records']['cancellation_activities']=rows[:1]
    r=batches(p)[-1]
    assert workflow(r)['status']=='pending'
    assert r['snapshot']['travel_cancellations'][0]['status']=='requested'
    assert r['finance_reconciliations']['SYN-C01']['recorded_obligation']['amount_cents']==10000
    assert r['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000


def test_cancellation_completion_updates_queue_and_request_projection():
    p=synthetic();cancellation(p)
    r=batches(p)[-1]
    assert r['domain']['repair_queue']['items']['cancellation-financial:TC-SYN']['status']=='resolved'
    assert r['snapshot']['requests'][0]['status']=='accepted'
    assert not any(i['status']=='open' and i['item_id'].startswith('ordinary:SYN-C01') for i in r['domain']['repair_queue']['items'].values())


@pytest.mark.parametrize('commitment', [None,''])
def test_explicit_blank_first_commitment_is_not_a_late_permit(commitment):
    from travel_claim.exceptions import travel_findings
    from travel_claim.ordinary import ref
    p=synthetic();trip=fields(p['records']['trips'][0]);trip.update({'International':True,
        'Permit reference':'P-SYN','Permit revision':1,'Estimate (EUR)':100,'First commitment date':commitment})
    decisions=deepcopy(p['records']['decisions'])
    for d in decisions:
        setfield(d,'Subject type','permit');setfield(d,'Subject reference','P-SYN')
    assert travel_findings(trip=trip,employee='EMP-01',decisions=decisions,people=table(p,'people','People'),
        cancellations=[],fields=fields,ref=ref,observations=p['source_observations'])==[]


def test_confirmation_does_not_reactivate_arrangements_after_reimbursement_completion():
    p=synthetic();cancellation(p)
    r=batches(p)[-1];w=workflow(r)
    assert w['status']=='closed-reimbursed'
    assert w['permit_approval']['arrangements_at_commitment_supported'] is True
    assert w['permit_approval']['arrangement_authorized'] is False
    assert r['domain']['cancellation_state']['processes']['TC-SYN']['state']=='confirmed'
    assert r['snapshot']['travel_cancellations'][0]['admitted_cancellation_event_ids']==['SYN-CANCEL-requested','SYN-CANCEL-confirmed']


def test_resolution_alone_cannot_recreate_a_cancelled_finance_commitment():
    p=synthetic();activity(p,'SYN-REQUEST-CANCEL','cancelled')
    activity(p,'SYN-RESURRECT','resolution',batch=4,time='2026-09-14T13:00:00',obligation=100,
        **{'Resolved activity references':'SYN-REQUEST-CANCEL'})
    for d in p['records']['decisions']:
        setfield(d,'Arrival batch',4);setfield(d,'Decision time (UTC)','2026-09-14T14:00:00')
    r=batches(p)[-1]
    assert workflow(r)['status']=='pending'
    assert r['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000

    request=next(req for scope in r['domain']['budget']['scopes'].values() for req in scope['requests'].values() if req['request_id']=='REQ-SYN-C01')
    assert request['commitment_cents']==0
    assert request['confirmed_payment_cents']==10000


def no_claim_package():
    """Explicitly synthetic complete inventories, never a native acquisition."""
    import hashlib
    p=synthetic()
    retained=json.loads((Path(__file__).parent/'fixtures/retained_finance_records.json').read_text())
    trip=deepcopy(next(r for r in retained['records']['trips'] if fields(r).get('Trip reference')=='T122'))
    rows=[deepcopy(r) for r in retained['records']['cancellation_activities'] if fields(r).get('Cancellation reference')=='TC122']
    sid=p['records']['trips'][0]['source_id'];sha=p['records']['trips'][0]['source_sha256']
    for r in [trip]+rows:r.update(source_id=sid,source_sha256=sha)
    setfield(trip,'First commitment date',None)
    p['records']['trips'].append(trip);p['records']['cancellation_activities']=rows
    p['pdf_pages']=[];p['source_inventory']=[];p['transcription_issues']=[]
    for name in ['initial-claim-binder','claim-updates-binder','receipt-binder']:
        source='synthetic-'+name;digest=hashlib.sha256(source.encode()).hexdigest()
        p['pdf_pages'].append(dict(source_id=source,source_sha256=digest,locator='PDF page 1',page=1,text='SYNTHETIC complete document'))
        p['source_inventory'].append(dict(source_id=source,kind='pdf',page_count=1))
        if not any(o['source_id']==source for o in p['source_observations']):p['source_observations'].append(dict(source_id=source,sha256=digest,status='read',missing_scope=[]))
    for name in ['Trips','Caps','Review ledger','Finance activity','Travel cancellations']:
        p['workbook_sheets'].append(dict(name=name,records=[]))
    for sheet in p['workbook_sheets']:sheet.update(source_id=sid,source_sha256=sha)
    p['source_inventory'].append(dict(source_id=sid,kind='xlsx',sheet_count=10))
    return p


def test_complete_no_claim_cancellation_can_prove_no_financial_effect_without_inventing_claim():
    p=no_claim_package();r=batches(p)[-1];c=r['snapshot']['travel_cancellations'][0]
    assert c['cancellation_id']=='TC122' and c['affected_claim_ids']==[]
    assert c['financial_status']=='no-financial-effect' and c['next_owner'] is None
    assert list(r['domain']['ordinary_workflows'])==['SYN-C01']
    assert workflow(r)['status']=='closed-reimbursed'
    assert r['domain']['repair_queue']['items']['cancellation-financial:TC122']['status']=='resolved'


@pytest.mark.parametrize('missing',['inventory','page','cost','unmatched-finance'])
def test_absence_of_claim_alone_never_proves_absence_of_financial_effect(missing):
    p=no_claim_package()
    if missing=='inventory':p.pop('source_inventory')
    if missing=='page':p['pdf_pages'].pop()
    if missing=='cost':setfield(p['records']['receipts'][0],'Trip reference','T122')
    if missing=='unmatched-finance':setfield(activity(p,'SYN-UNMATCHED','accepted',obligation=10),'Claim reference','UNKNOWN')
    c=batches(p)[-1]['snapshot']['travel_cancellations'][0]
    assert c['financial_status']=='unresolved'


def test_trip_cancellation_projection_preserves_source_associated_permit():
    p=no_claim_package();r=batches(p)[-1];c=r['snapshot']['travel_cancellations'][0]
    assert c['target_type']=='trip' and c['trip_id']=='T122'
    assert c['permit_id']=='P122' and c['permit_revision']==1

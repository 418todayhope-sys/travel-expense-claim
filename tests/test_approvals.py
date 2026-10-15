"""Native-shaped review records and explicitly synthetic authority probes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_ordinary import synthetic, batches, workflow, stages
from test_expenses import setfield
from test_revalidation import corrected
from travel_claim.approvals import evaluate_reviews, evaluate_permit, fields, ref, table
from travel_claim.integration import integrate_arrival_batch


def subject(kind='claim',amount=10000):
    p=synthetic();record=p['records']['claim_revisions'][0];trip=p['records']['trips'][0]
    if kind=='permit':
        setfield(trip,'International',True);setfield(trip,'Permit reference','P-SYN');setfield(trip,'Permit revision',1)
        setfield(trip,'Estimate (EUR)',str(amount/100))
        record=deepcopy(trip);record['text']='Synthetic source version SRC-D-3'
        for d in p['records']['decisions']:
            setfield(d,'Subject type','permit');setfield(d,'Subject reference','P-SYN')
    for packet in table(p,'review_packets','Review packets'):
        for key in ('Permit reference','Permit revision'): setfield(packet,key,fields(trip).get(key))
        if kind=='permit':setfield(packet,'Reviewed estimate (EUR)',str(amount/100))
    return p,record,trip


def check(p,record,trip,kind='claim',amount=10000,prior=None,batch=4):
    return evaluate_reviews(parsed=p,kind=kind,subject_id='P-SYN' if kind=='permit' else 'SYN-C01',revision=1,
        trip_record=trip,employee='EMP-01',subject_record=record,amount_cents=amount,
        decisions=p['records']['decisions'],arrival_batch=batch,observations=p['source_observations'],
        cost_ids=['COST-01'],prior=prior)


def director(p):
    d=deepcopy(p['records']['decisions'][0]);setfield(d,'Decision reference','SYN-DIRECTOR');setfield(d,'Review roles','director');setfield(d,'Reviewer','DIR-01')
    packet=deepcopy(table(p,'review_packets','Review packets')[0]);setfield(packet,'Decision reference','SYN-DIRECTOR')
    p['records']['decisions'].append(d)
    table(p,'review_packets','Review packets').append(packet)


@pytest.mark.parametrize('kind',['claim','permit'])
@pytest.mark.parametrize('amount,needs_director',[(99999,False),(100000,False),(100001,True)])
def test_exact_policy_thresholds_for_distinct_subjects(kind,amount,needs_director):
    p,record,trip=subject(kind,amount)
    value=check(p,record,trip,kind,amount)
    assert ('director' in value['required_roles'])==needs_director
    assert value['approved']==(not needs_director)
    director(p)
    assert check(p,record,trip,kind,amount)['approved']


@pytest.mark.parametrize('kind',['claim','permit'])
@pytest.mark.parametrize('field,value',[('Subject type','other'),('Subject reference','OTHER'),('Revision',2),
    ('Reviewer','OTHER'),('Reviewer','EMP-01'),('Review roles','director'),('Review roles','unknown'),
    ('Reason',''),('Source revisions','SRC-D-OLD\nPOL-2026.2'),('Source revisions','SRC-D-3\nPOL-2026.1')])
def test_wrong_role_actor_subject_version_and_reason_never_authorize(kind,field,value):
    p,record,trip=subject(kind);setfield(p['records']['decisions'][0],field,value)
    result=check(p,record,trip,kind)
    assert not result['approved']
    assert any(d['rejection_reasons'] for d in result['deliveries'])
    assert result['deliveries'][0]['raw_record']==p['records']['decisions'][0]


@pytest.mark.parametrize('kind',['claim','permit'])
def test_explicit_combined_roles_only_for_same_directory_person(kind):
    p,record,trip=subject(kind)
    person=table(p,'people','People')[0];setfield(person,'Supervisor',fields(person)['Budget owner'])
    combined=p['records']['decisions'][1];setfield(combined,'Review roles','budget_owner\nsupervisor')
    p['records']['decisions']=p['records']['decisions'][:2]
    assert check(p,record,trip,kind)['approved']
    setfield(combined,'Review roles','budget_owner')
    assert not check(p,record,trip,kind)['approved']
    setfield(combined,'Review roles','budget_owner\nsupervisor');setfield(person,'Supervisor','OTHER')
    assert not check(p,record,trip,kind)['approved']


def test_permit_approvals_do_not_approve_claims():
    p,record,trip=subject('permit')
    assert check(p,record,trip,'permit')['approved']
    assert not check(p,p['records']['claim_revisions'][0],trip,'claim')['approved']


@pytest.mark.parametrize('outcome,state',[('return','returned'),('reject','rejected')])
def test_human_outcomes_and_new_reply_transitions_preserve_history(outcome,state):
    p,record,trip=subject();d=p['records']['decisions'][1];setfield(d,'Outcome',outcome)
    if outcome=='return':setfield(d,'Repair requested','SYNTHETIC supply corrected receipt')
    first=check(p,record,trip);assert first['state']==state
    later=deepcopy(d);setfield(later,'Decision reference','SYN-AFTER-REPAIR');setfield(later,'Outcome','approve');setfield(later,'Arrival batch',3);setfield(later,'Decision time (UTC)','2026-09-05T12:00:00')
    packet=deepcopy(table(p,'review_packets','Review packets')[1]);setfield(packet,'Decision reference','SYN-AFTER-REPAIR')
    p['records']['decisions'].append(later);table(p,'review_packets','Review packets').append(packet)
    result=check(p,record,trip)
    assert result['approved'] and len(result['deliveries'])==4
    assert first['state']==state
    assert not next(x for x in result['deliveries'] if x['decision_id']==fields(d)['Decision reference'])['active']


def test_return_without_repair_is_invalid():
    p,record,trip=subject();setfield(p['records']['decisions'][0],'Outcome','return')
    result=check(p,record,trip)
    assert result['state']=='pending' and 'repair' in result['deliveries'][0]['rejection_reasons'][0]


def test_old_reply_imported_later_does_not_override_later_human_decision():
    p,record,trip=subject();later=deepcopy(p['records']['decisions'][0])
    setfield(later,'Decision reference','SYN-OLD-RETURN');setfield(later,'Outcome','return');setfield(later,'Repair requested','Old repair')
    setfield(later,'Arrival batch',4);setfield(later,'Decision time (UTC)','2026-08-01T12:00:00')
    packet=deepcopy(table(p,'review_packets','Review packets')[0]);setfield(packet,'Decision reference','SYN-OLD-RETURN')
    p['records']['decisions'].append(later);table(p,'review_packets','Review packets').append(packet)
    assert check(p,record,trip)['approved']


def test_exact_and_conflicting_reply_replays_are_retained_without_duplicate_authority():
    p,record,trip=subject();first=check(p,record,trip)
    p['records']['decisions'].append(deepcopy(p['records']['decisions'][0]))
    duplicate=check(p,record,trip)
    assert duplicate['active_decision_ids']==first['active_decision_ids'] and duplicate['approved']
    assert duplicate['deliveries'][-1]['import_status']=='exact-replay'
    setfield(p['records']['decisions'][-1],'Reviewer','WRONG')
    conflict=check(p,record,trip)
    assert not conflict['approved'] and conflict['deliveries'][0]['import_status']=='conflicting-replay'


@pytest.mark.parametrize('commitment,authorized',[(None,True),('2026-09-05',True),('2026-08-01',False),('2026-09-03',False)])
def test_domestic_exemption_and_native_local_commitment_order(commitment,authorized):
    p,record,trip=subject('permit')
    p['workbook_sheets'][0]['source_id']=trip['source_id']
    p['workbook_sheets'][0]['preamble']=[dict(cell='A2',value='Synthetic source version SRC-D-3')]
    setfield(trip,'First commitment date',commitment)
    result=evaluate_permit(parsed=p,trip_record=trip,decisions=p['records']['decisions'],arrival_batch=4,observations=p['source_observations'])
    assert result['approved'] and result['arrangement_authorized']==authorized
    setfield(trip,'International',False)
    assert evaluate_permit(parsed=p,trip_record=trip,decisions=[],arrival_batch=4,observations=p['source_observations'])['state']=='not-required'


def test_material_same_revision_trip_authority_change_holds_until_fresh_bound_reply():
    p,record,trip=subject();prior=check(p,record,trip,batch=1)
    setfield(trip,'Business purpose','SYNTHETIC material change')
    for packet in table(p,'review_packets','Review packets'):setfield(packet,'Business purpose','SYNTHETIC material change')
    held=check(p,record,trip,prior=prior,batch=3)
    assert held['material_same_revision'] and not held['approved']
    assert not check(p,record,trip,prior=held,batch=4)['approved']
    for d in p['records']['decisions']:
        setfield(d,'Source revisions',ref(record)+'\nPOL-2026.2');setfield(d,'Arrival batch',3)
    assert check(p,record,trip,prior=held,batch=4)['approved']


@pytest.mark.parametrize('status,outcome,expected',[('withdrawn',None,'withdrawn'),('submitted','reject','rejected'),('submitted','return','pending')])
def test_clean_business_transitions_never_invent_financial_closure(status,outcome,expected):
    p=synthetic();setfield(p['records']['claim_revisions'][0],'Status',status)
    p['records']['finance_events']=[];p['records']['reimbursement_requests']=[]
    if outcome:
        setfield(p['records']['decisions'][0],'Outcome',outcome)
        if outcome=='return':setfield(p['records']['decisions'][0],'Repair requested','SYNTHETIC correct cost')
    result=workflow(batches(p)[-1]);assert result['status']==expected
    assert result['request'] is None and stages(result)['financial_closure']['status']=='BLOCKED'
    assert not result['status'].startswith('closed-')


def test_withdrawal_after_payment_preserves_cash_and_requires_finance_disposition():
    p=synthetic();new=corrected(p);setfield(new,'Status','withdrawn')
    results=batches(p);current=workflow(results[-1])
    assert workflow(results[1])['status']=='closed-reimbursed'
    assert current['status']=='held' and stages(current)['nonpayment_disposition']['status']=='BLOCKED'
    assert current['claim_approval']['state']=='withdrawn' and current['request'] is None
    assert results[-1]['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000
    assert results[-1]['finance_reconciliations']['SYN-C01']['admitted_events']==results[1]['finance_reconciliations']['SYN-C01']['admitted_events']


def test_actual_retained_claim_and_permit_packets_roles_and_outcomes():
    from travel_claim.expenses import load_expense_policy
    p=json.loads((Path(__file__).parent/'fixtures/retained_approval_records.json').read_text())
    p['expense_policy']=load_expense_policy(Path(__file__).parent/'fixtures/POL-2026.2-browser-copy.txt')
    for claim,amount,expected in [('C01',10000,'approved'),('C02',54000,'approved'),('C09',8000,'returned'),
                                 ('C14',4000,'rejected'),('C21',8000,'returned'),('C46',4500,'approved')]:
        record=next(r for r in p['records']['claim_revisions'] if fields(r)['Claim reference']==claim and fields(r)['Revision']=='1')
        trip=next(r for r in p['records']['trips'] if fields(r)['Trip reference']==fields(record)['Trip reference'])
        costs=[line['cost_id'] for line in __import__('travel_claim.ordinary',fromlist=['expense_lines']).expense_lines(record)]
        result=evaluate_reviews(parsed=p,kind='claim',subject_id=claim,revision=1,trip_record=trip,employee=fields(record)['Employee'],
            subject_record=record,amount_cents=amount,decisions=p['records']['decisions'],arrival_batch=1,
            observations=p['source_observations'],cost_ids=costs)
        assert result['state']==expected,(claim,result['deliveries'])
        assert all(d['raw_record'] in p['records']['decisions'] for d in result['deliveries'])
        if claim=='C46':assert any(d['active'] and set(d['roles'])=={'budget_owner','supervisor'} for d in result['deliveries'])
        if claim=='C02':
            permit=evaluate_permit(parsed=p,trip_record=trip,decisions=p['records']['decisions'],arrival_batch=1,observations=p['source_observations'])
            assert permit['approved'] and 'director' in permit['required_roles']
            assert 'director' not in result['required_roles']  # estimate 1,100 EUR; paid USD 600 at 0.9 = EUR 540
            assert permit['subject_id']=='P02'
            assert set(permit['active_decision_ids']).isdisjoint(result['active_decision_ids'])


def test_standalone_permit_without_a_claim_and_batch_replay():
    p,record,trip=subject('permit');p['records']['claim_revisions']=[];p['records']['finance_events']=[];p['records']['reimbursement_requests']=[];setfield(trip,'First commitment date',None)
    p['workbook_sheets'][0]['source_id']=trip['source_id'];p['workbook_sheets'][0]['preamble']=[dict(cell='A2',value='SRC-D-3')]
    first=integrate_arrival_batch(p,arrival_batch=1,run_id='permit-only',batch_id='arrival-001',
        source_binding={'path':'sources.json','sha256':'a'*64},source_observations=p['source_observations'])
    assert first['domain']['permit_approvals']['P-SYN:r1']['approved']
    assert first['snapshot']['claims']==[]
    replay=integrate_arrival_batch(p,arrival_batch=1,run_id='permit-only',batch_id='arrival-001',
        source_binding={'path':'sources.json','sha256':'a'*64},source_observations=p['source_observations'],prior_result=first)
    assert replay['snapshot']==first['snapshot'] and replay['domain']==first['domain']


def test_correction_revalidates_reviews_without_reusing_old_version_authority():
    p=synthetic();new=corrected(p,receipt='SYN-REVISED-RECEIPT')
    results=batches(p);current=workflow(results[-1]);old=workflow(results[1])
    assert old['claim_approval']['approved'] and not current['claim_approval']['approved']
    assert stages(current)['request_obligation']['status']=='BLOCKED'
    assert len(current['claim_approval']['deliveries'])==3
    assert all(not d['evidence_valid'] for d in current['claim_approval']['deliveries'])
    assert results[-1]['finance_reconciliations']['SYN-C01']['admitted_events']==results[1]['finance_reconciliations']['SYN-C01']['admitted_events']


def test_cancellation_retires_current_arrangement_authority_without_erasing_permit_history():
    p,record,trip=subject('permit');setfield(trip,'First commitment date',None)
    p['workbook_sheets'][0]['source_id']=trip['source_id'];p['workbook_sheets'][0]['preamble']=[dict(cell='A2',value='SRC-D-3')]
    cancellation=dict(cancellation_id='TC-SYN',trip_id='T01',trip_revision=1,target_type='permit',permit_id='P-SYN',permit_revision=1)
    value=evaluate_permit(parsed=p,trip_record=trip,decisions=p['records']['decisions'],arrival_batch=4,observations=p['source_observations'],cancellations=[cancellation])
    assert value['approved'] and value['arrangements_at_commitment_supported'] and not value['arrangement_authorized']
    assert value['cancellation_ids']==['TC-SYN']
    cancellation['permit_revision']=2
    assert evaluate_permit(parsed=p,trip_record=trip,decisions=p['records']['decisions'],arrival_batch=4,
        observations=p['source_observations'],cancellations=[cancellation])['arrangement_authorized']


@pytest.mark.parametrize('versions',['POL-2026.2\nPOL-2026.1\nSRC-D-3','POL-2026.2\nSRC-D-3\nSRC-D-OLD','POL-2026.2\nSRC-D-3\nSRC-D-2'])
def test_contradictory_policy_or_numeric_source_versions_are_not_current_authority(versions):
    p,record,trip=subject();setfield(p['records']['decisions'][0],'Source revisions',versions)
    value=check(p,record,trip)
    assert not value['approved']


def test_return_repair_is_visible_in_owned_queue_then_resolves_after_new_approval():
    p=synthetic();d=p['records']['decisions'][0];setfield(d,'Outcome','return');setfield(d,'Repair requested','SYNTHETIC supply matched receipt')
    result=batches(p)[0];queue=result['domain']['repair_queue']['items']
    item=next(item for name,item in queue.items() if 'review_return:' in name)
    assert item['status']=='open' and item['next_action']=='SYNTHETIC supply matched receipt'
    assert item['owner']=='EMP-01' and item['source_refs']


def test_unknown_reviewed_amount_never_silently_omits_required_director_decision():
    p,record,trip=subject();value=check(p,record,trip,amount=None)
    assert not value['approved'] and not value['amount_known'] and value['state']=='pending'


def test_untrusted_withdrawal_cannot_be_treated_as_a_clean_terminal_state():
    p=synthetic();setfield(p['records']['claim_revisions'][0],'Status','withdrawn')
    p['records']['finance_events']=[];p['records']['reimbursement_requests']=[]
    p['records']['claim_revisions'][0]['source_sha256']='0'*64
    value=workflow(batches(p)[-1]);assert value['status']=='pending'


def test_new_claim_cost_does_not_invalidate_unchanged_permit_reviews():
    p,record,trip=subject('permit');prior=check(p,record,trip,'permit',batch=1)
    assert prior['approved']
    current=evaluate_reviews(parsed=p,kind='permit',subject_id='P-SYN',revision=1,trip_record=trip,
        employee='EMP-01',subject_record=record,amount_cents=10000,decisions=p['records']['decisions'],
        arrival_batch=3,observations=p['source_observations'],cost_ids=['COST-NEW'],prior=prior)
    assert current['approved'] and not current['material_same_revision']
    assert current['policy_source_refs'] and all('#line ' in r for r in current['policy_source_refs'])

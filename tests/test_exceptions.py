"""POL-2026.2 exception authority; mutations are explicitly synthetic probes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_expenses import setup, setfield, evaluate, merchant
from test_ordinary import synthetic, batches, workflow, stages
from test_revalidation import corrected
from travel_claim.exceptions import (apply_coverage, covered_issues, finding, travel_findings, validate_exception)
from travel_claim.expenses import evaluate_expenses, load_expense_policy
from travel_claim.ordinary import expense_lines, fields, ref, table

FIXTURES=Path(__file__).parent/'fixtures'


def exception(record, *, amount='80.00', covered='None', **overrides):
    values={'Authorizing Finance officer':'FIN-01','Applies to claim':fields(record)['Claim reference'],
        'Applies to revision':fields(record)['Revision'],'Expense reference':expense_lines(record)[0]['cost_id'],
        'Allowed original amount':amount,'Covered issues':covered,'Exception reason':'SYNTHETIC explicit Finance disposition'}
    values.update(overrides)
    for key,value in values.items(): setfield(record,key,value)


def validate(parsed,record):
    return validate_exception(record=record,line=expense_lines(record)[0],employee=fields(record)['Employee'],
        people=table(parsed,'people','People'),observations=parsed.get('source_observations',[]),fields=fields,ref=ref)


def test_amount_only_replacement_and_original_cost_are_preserved():
    parsed,record,trip=setup(); exception(record)
    result,lines=evaluate(parsed,record,trip)
    assert result['status']=='PASS' and result['calculated_cents']==8000
    line=lines[0]
    assert line['base_allowed_original_amount']=='100.00'
    assert line['original_cents']==10000 and line['conversion']['original_amount']=='100.00'
    assert line['conversion']['allowed_original_amount']=='80.00'
    assert line['exception']['currency']=='EUR' and line['exception']['covered_issues']==[]
    assert line['exception']['source_refs'] and line['replacement_amount_changed']


@pytest.mark.parametrize('field', ['Authorizing Finance officer','Applies to claim','Applies to revision',
    'Expense reference','Allowed original amount','Exception reason','Covered issues'])
def test_each_required_native_field_is_required(field):
    parsed,record,trip=setup(); exception(record)
    record['fields']=[f for f in record['fields'] if f['label']!=field]
    result,lines=evaluate(parsed,record,trip)
    assert result['status']=='BLOCKED'
    assert lines[0]['exception']['status']=='BLOCKED' and field in lines[0]['exception']['raw_fields']


@pytest.mark.parametrize('field,value', [('Authorizing Finance officer','EMP-01'),('Authorizing Finance officer','OTHER'),
    ('Applies to claim','OTHER'),('Applies to revision','2'),('Applies to revision',True),
    ('Expense reference','OTHER'),('Allowed original amount','NaN'),('Allowed original amount','-1'),
    ('Allowed original amount',True),('Allowed original amount',None),('Exception reason',''),
    ('Covered issues',None),('Covered issues',''),('Covered issues','Late Filing'),
    ('Covered issues','not_late_filing'),('Covered issues','late_filing\nunknown')])
def test_invalid_or_stale_authority_is_visible_not_applied(field,value):
    parsed,record,trip=setup(); exception(record,**{field:value})
    result,lines=evaluate(parsed,record,trip)
    assert result['status']=='BLOCKED' and lines[0]['exception']['status']=='BLOCKED'
    assert lines[0]['exception']['raw_fields'][field]==value
    assert lines[0].get('conversion',{}).get('allowed_original_amount')!='80.00'


@pytest.mark.parametrize('target',['record','directory','observations'])
def test_source_binding_is_required(target):
    parsed,record,trip=setup(); exception(record)
    if target=='record': record['source_sha256']='0'*64
    if target=='directory': table(parsed,'people','People')[0]['source_sha256']='0'*64
    if target=='observations': parsed['source_observations']=[]
    assert evaluate(parsed,record,trip)[0]['status']=='BLOCKED'


def test_amount_only_covers_no_eligibility_issues():
    parsed,record,trip=setup(); exception(record); trip['End date']='2026-06-01'
    result,lines=evaluate(parsed,record,trip)
    assert result['status']=='BLOCKED' and lines[0]['calculated_cents']==8000
    assert lines[0]['eligibility_findings'][0]['issue']=='late_filing'
    assert lines[0]['eligibility_findings'][0]['status']=='unresolved'


def test_exact_coverage_is_independent_and_keeps_original_findings():
    parsed,record,trip=setup(); exception(record,covered='late_filing\nlate_permit')
    context=[finding('late_permit','Originally late permit',['source#permit']),
             finding('permit_unapproved','Original missing approval',['source#approval'])]
    lines=expense_lines(record); trip['End date']='2026-06-01'
    setfield(table(parsed,'trips','Trips')[0], 'End date', trip['End date'])
    result=evaluate_expenses(lines=lines,parsed=parsed,employee='EMP-01',trip_id='T01',trip=trip,record=record,
        history=[],fields=fields,ref=ref,table=table,eligibility_findings=context)
    findings={f['issue']:f for f in lines[0]['eligibility_findings']}
    assert result['status']=='BLOCKED'
    assert findings['late_filing']['status']==findings['late_permit']['status']=='covered_for_reimbursement'
    assert findings['permit_unapproved']['status']=='unresolved'
    assert findings['late_permit']['original_finding']=='Originally late permit'
    assert findings['late_permit']['exception_source_refs']
    assert context[0]['status']=='unresolved'  # input evidence not mutated


@pytest.mark.parametrize('cancel_id', [None,'WRONG','TC-SYN'])
def test_travel_cancellation_needs_exact_id_and_affected_cost(cancel_id):
    parsed,record,trip=setup(); exception(record,covered='Travel cancellation',**{'Travel cancellation reference':cancel_id})
    context=[finding('travel_cancellation','Confirmed travel cancellation',['source#TC-SYN'],'TC-SYN')]
    lines=expense_lines(record)
    result=evaluate_expenses(lines=lines,parsed=parsed,employee='EMP-01',trip_id='T01',trip=trip,record=record,
        history=[],fields=fields,ref=ref,table=table,eligibility_findings=context)
    assert result['status']==('PASS' if cancel_id=='TC-SYN' else 'BLOCKED')
    assert lines[0]['eligibility_findings'][0]['travel_cancellation_id']=='TC-SYN'
    assert context[0]['status']=='unresolved'


def test_cancellation_exception_for_no_current_affected_cost_cannot_replace_amount():
    parsed,record,trip=setup(); exception(record,covered='travel_cancellation',**{'Travel cancellation reference':'TC-OLD'})
    assert evaluate(parsed,record,trip)[0]['status']=='BLOCKED'


@pytest.mark.parametrize('unpaid', ['missing','pending','mismatch'])
def test_exception_never_establishes_employee_payment(unpaid):
    parsed,record,trip=setup(); exception(record,covered='late_filing')
    if unpaid=='missing': parsed['records']['merchant_payments']=[]
    elif unpaid=='pending': setfield(merchant(parsed),'Payment status','pending')
    else: setfield(merchant(parsed),'Gross amount','80.00')
    result,lines=evaluate(parsed,record,trip)
    assert result['status']=='BLOCKED' and lines[0]['calculated_cents'] is None
    assert lines[0]['exception']['status']=='valid' and lines[0]['evidence_status']=='BLOCKED'


def test_replacement_uses_original_currency_then_exact_fx_rounding():
    parsed,record,trip=setup(); record['text']=record['text'].replace('EUR','USD')
    setfield(parsed['records']['receipts'][0],'Currency','USD');setfield(merchant(parsed),'Currency','USD')
    parsed['records']['fx_rates']=[dict(source_id='synthetic-fx',source_sha256='a'*64,locator='FX',
        values={k:dict(value=v) for k,v in {'Currency':'USD','Rate date':'2026-09-01','EUR per currency unit':'0.90005'}.items()})]
    parsed['source_observations'].append(dict(source_id='synthetic-fx',sha256='a'*64,status='read',missing_scope=[]))
    exception(record,amount='50.00')
    result,lines=evaluate(parsed,record,trip)
    assert result['calculated_cents']==4500 and lines[0]['exception']['currency']=='USD'
    exception(record,amount='100.00')
    assert evaluate(parsed,record,trip)[0]['calculated_cents']==9001


def test_exact_exception_replay_has_identical_result_and_no_extra_effect():
    parsed,record,trip=setup(); exception(record)
    before=deepcopy(parsed)
    first=evaluate(parsed,record,trip); second=evaluate(parsed,record,trip)
    assert first==second and parsed==before


def test_native_retained_exceptions_keep_actual_refs_and_amounts():
    parsed=json.loads((FIXTURES/'retained_exception_records.json').read_text())
    parsed['expense_policy']=load_expense_policy(FIXTURES/'POL-2026.2-browser-copy.txt')
    for claim,revision,expected,covered,cancellation in [('C12','2',7000,'late_filing',None),
        ('C19','2',8000,None,None),('C121','2',2000,'travel_cancellation','TC121'),('C19','3',8000,'travel_cancellation','TC019')]:
        record=next(r for r in parsed['records']['claim_revisions'] if fields(r)['Claim reference']==claim and fields(r)['Revision']==revision)
        trip=fields(next(r for r in parsed['records']['trips'] if fields(r)['Trip reference']==fields(record)['Trip reference']))
        context=[]
        if cancellation:
            raw=[r for r in parsed['records']['cancellation_activities'] if fields(r)['Cancellation reference']==cancellation]
            context=[finding('travel_cancellation','Retained cancellation context',[ref(r) for r in raw],cancellation)]
        lines=expense_lines(record)
        result=evaluate_expenses(lines=lines,parsed=parsed,employee='EMP-01',trip_id=trip['Trip reference'],trip=trip,
            record=record,history=[],fields=fields,ref=ref,table=table,eligibility_findings=context)
        assert result['status']=='PASS' and result['calculated_cents']==expected
        assert lines[0]['exception']['source_refs'][0]==ref(record)
        assert '03c15787d18e2928457cd0164b573dc03a3baade0ed26a391ba79c73a568da3b' in ref(record)
        assert lines[0]['exception']['covered_issues']==([covered] if covered else [])
        if covered: assert any(f['issue']==covered and f['status']=='covered_for_reimbursement' for f in lines[0]['eligibility_findings'])


def test_material_replacement_rejects_stale_reviews_and_preserves_admitted_cash():
    parsed=synthetic(); record=corrected(parsed); exception(record)
    result=batches(parsed)
    assert workflow(result[1])['status']=='closed-reimbursed'
    current=workflow(result[-1])
    assert current['lines'][0]['calculated_cents']==8000 and current['revision']==2
    assert stages(current)['exception_revalidation']['status']=='BLOCKED'
    assert stages(current)['required_approvals']['status']=='BLOCKED'
    assert stages(current)['request_obligation']['status']=='BLOCKED'
    assert result[-1]['finance_reconciliations']['SYN-C01']['admitted_events']==result[1]['finance_reconciliations']['SYN-C01']['admitted_events']
    assert result[-1]['snapshot']['claims'][0]['paid_cents']==10000
    assert any('exception_revalidation' in key for key in result[-1]['domain']['repair_queue']['items'])


def test_current_source_bound_reviews_and_matching_authorization_allow_synthetic_replacement():
    parsed=synthetic(); record=parsed['records']['claim_revisions'][0]; exception(record)
    for d in parsed['records']['decisions']: setfield(d,'Source revisions',ref(record)+'\nPOL-2026.2')
    setfield(parsed['records']['reimbursement_requests'][0],'Amount (EUR)',80)
    for event in parsed['records']['finance_events']:
        for key in ('Amount (EUR)','Obligation (EUR)'):
            if key in event['values']: setfield(event,key,80)
    results=batches(parsed); final=workflow(results[-1])
    assert stages(final)['exception_revalidation']['status']=='PASS'
    assert stages(final)['request_obligation']['status']=='PASS'
    assert final['status']=='closed-reimbursed' and final['allowed_cents']==8000
    assert results[-1]['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==8000
    # Original evidence and admission identity are not replaced by the exception.
    assert final['lines'][0]['original_cents']==10000


def test_original_travel_finding_is_not_a_business_approval():
    parsed=synthetic(); record=parsed['records']['claim_revisions'][0]; exception(record,amount='100.00',covered='permit_unapproved')
    trip=parsed['records']['trips'][0];setfield(trip,'International',True);setfield(trip,'Permit reference','P-SYN');setfield(trip,'Permit revision',1)
    current=workflow(batches(parsed)[-1]); line=current['lines'][0]
    assert any(f['issue']=='permit_unapproved' and f['status']=='covered_for_reimbursement' for f in line['eligibility_findings'])
    assert stages(current)['travel_permission']['status']=='BLOCKED'
    assert line['calculated_cents']==10000 and current['status']=='pending'


@pytest.mark.parametrize('approval_date,expected', [('2026-08-30T12:00:00',None),
    ('2026-09-02T12:00:00','late_permit'),('2026-09-01T12:00:00','late_permit')])
def test_native_permit_timing_findings_do_not_invent_same_day_order(approval_date,expected):
    parsed=synthetic(); trip=fields(parsed['records']['trips'][0]); trip.update({'International':True,
        'Permit reference':'P-SYN','Permit revision':1,'Estimate (EUR)':100,'First commitment date':'2026-09-01'})
    decisions=deepcopy(parsed['records']['decisions'])
    for d in decisions:
        setfield(d,'Subject type','permit');setfield(d,'Subject reference','P-SYN');setfield(d,'Decision time (UTC)',approval_date)
    items=travel_findings(trip=trip,employee='EMP-01',decisions=decisions,people=table(parsed,'people','People'),
        cancellations=[],fields=fields,ref=ref,observations=parsed['source_observations'])
    assert [f['issue'] for f in items]==([expected] if expected else [])
    if approval_date.startswith('2026-09-01'): assert 'unconfirmed' in items[0]['original_finding']


def test_wrong_actor_permit_reply_remains_unapproved_and_cancellation_does_not_create_it():
    parsed=synthetic(); trip=fields(parsed['records']['trips'][0]); trip.update({'International':True,
        'Permit reference':'P-SYN','Permit revision':1,'Estimate (EUR)':100,'First commitment date':'2026-09-01'})
    decisions=deepcopy(parsed['records']['decisions'])
    for d in decisions:
        setfield(d,'Subject type','permit');setfield(d,'Subject reference','P-SYN');setfield(d,'Decision time (UTC)','2026-08-30T12:00:00')
    cancellations=[dict(cancellation_id='TC-SYN',trip_id='T01',trip_revision=1,target_type='permit',
        permit_id='P-SYN',permit_revision=1,source_refs=['source#cancel'])]
    args=dict(trip=trip,employee='EMP-01',decisions=decisions,people=table(parsed,'people','People'),
        cancellations=cancellations,fields=fields,ref=ref,observations=parsed['source_observations'])
    assert [f['issue'] for f in travel_findings(**args)]==['travel_cancellation']
    setfield(decisions[0],'Reviewer','WRONG')
    assert [f['issue'] for f in travel_findings(**args)]==['permit_unapproved','travel_cancellation']
    cancellations[0]['trip_id']='T-OLD'
    assert [f['issue'] for f in travel_findings(**args)]==['permit_unapproved']


def test_same_revision_material_change_requires_new_source_binding_and_hold_survives_replay():
    from travel_claim.ordinary import connect_claim
    parsed=synthetic(); paid=batches(parsed)[1]; record=parsed['records']['claim_revisions'][0]
    prior=deepcopy(workflow(paid)); exception(record)
    record['source_sha256']='c'*64
    parsed['source_observations'].append(dict(source_id=record['source_id'],sha256='c'*64,status='read',missing_scope=[]))
    claim=deepcopy(paid['domain']['revision_history']['claim']['SYN-C01']['revisions'][0]);claim['record']=record
    finance=deepcopy(paid['finance_reconciliations']['SYN-C01']);finance['revision_history']=[claim]
    args=dict(parsed=parsed,claim=claim,decisions=parsed['records']['decisions'],finance_events=paid['domain']['finance_records'],
        finance=finance,cancellations=[],arrival_batch=3,source_observations=parsed['source_observations'],
        prior_finance=paid['finance_reconciliations']['SYN-C01'],budget_data=paid['domain']['budget'],prepaid_data=paid['domain']['budget']['cost_attribution'])
    held=connect_claim(**args,prior_workflow=prior)
    assert held['exception_revalidation']['same_revision_change']
    assert stages(held)['required_approvals']['status']=='BLOCKED'
    replay=connect_claim(**args,prior_workflow=held)
    assert stages(replay)['exception_revalidation']['status']=='BLOCKED'
    assert replay['finance']['admitted_events']==held['finance']['admitted_events']
    for d in args['decisions']:
        setfield(d,'Source revisions',ref(record)+'\nPOL-2026.2')
        setfield(d,'Arrival batch',3)
    reviewed=connect_claim(**args,prior_workflow=replay)
    assert stages(reviewed)['exception_revalidation']['status']=='PASS'
    assert stages(reviewed)['required_approvals']['status']=='PASS'
    assert stages(reviewed)['request_obligation']['status']=='BLOCKED'  # old authorized amount cannot be reused
    assert reviewed['finance']['net_confirmed_cents']==10000


def test_exact_batch_replay_with_exception_preserves_state_and_cash():
    from travel_claim.integration import integrate_arrival_batch
    parsed=synthetic();exception(parsed['records']['claim_revisions'][0])
    result=batches(parsed)[0]
    replay=integrate_arrival_batch(parsed,arrival_batch=1,run_id='ordinary-test',batch_id='arrival-001',
        source_binding={'path':'sources.json','sha256':'a'*64},prior_result=result,
        source_observations=parsed['source_observations'])
    assert replay['domain']==result['domain']
    assert replay['snapshot']==result['snapshot']


def test_conflicting_same_revision_exception_delivery_holds_without_losing_paid_history():
    parsed=synthetic(); original=parsed['records']['claim_revisions'][0]
    conflict=deepcopy(original);setfield(conflict,'Arrival batch','3');conflict['locator']='SYNTHETIC conflicting same-revision exception'
    exception(conflict);parsed['records']['claim_revisions'].append(conflict)
    results=batches(parsed)
    final=workflow(results[-1])
    assert stages(final)['claim_trip_link']['status']=='BLOCKED'
    assert final['status']=='pending' and stages(final)['request_obligation']['status']=='BLOCKED'
    assert results[-1]['finance_reconciliations']['SYN-C01']['admitted_events']==results[1]['finance_reconciliations']['SYN-C01']['admitted_events']
    assert results[-1]['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000


@pytest.mark.parametrize('raw,expected', [('None',[]),([],[]),(['late_filing'],['late_filing']),
    ('Late permit\nPermit unapproved',['late_permit','permit_unapproved'])])
def test_exact_native_and_canonical_issue_lists(raw,expected):
    assert covered_issues(raw)==expected


def test_repeated_authority_fields_and_missing_permit_time_remain_unresolved():
    parsed,record,trip=setup();exception(record)
    record['fields'].append(dict(label='Authorizing Finance officer',value='FIN-01'))
    assert validate(parsed,record)['status']=='BLOCKED'
    parsed=synthetic();trip=fields(parsed['records']['trips'][0]);trip.update({'International':True,
        'Permit reference':'P-SYN','Permit revision':1,'Estimate (EUR)':100})
    decisions=deepcopy(parsed['records']['decisions'])
    for d in decisions:
        setfield(d,'Subject type','permit');setfield(d,'Subject reference','P-SYN');setfield(d,'Decision time (UTC)',None)
    items=travel_findings(trip=trip,employee='EMP-01',decisions=decisions,people=table(parsed,'people','People'),
        cancellations=[],fields=fields,ref=ref,observations=parsed['source_observations'])
    assert items[0]['issue']=='late_permit' and 'Missing' in items[0]['original_finding']


def test_multiple_cancellations_require_independent_exact_coverage():
    parsed,record,trip=setup();exception(record,covered='travel_cancellation',**{'Travel cancellation reference':'TC-ONE'})
    items=[finding('travel_cancellation','First process',['source#one'],'TC-ONE'),
           finding('travel_cancellation','Second process',['source#two'],'TC-TWO')]
    applied=apply_coverage(deepcopy(items),validate(parsed,record))
    assert [f['status'] for f in applied]==['covered_for_reimbursement','unresolved']
    assert [f['travel_cancellation_id'] for f in applied]==['TC-ONE','TC-TWO']


def test_decimal_display_precision_is_not_a_material_same_version_change():
    from travel_claim.ordinary import connect_claim
    parsed=synthetic();record=parsed['records']['claim_revisions'][0];exception(record,amount='80.00')
    for d in parsed['records']['decisions']: setfield(d,'Source revisions',ref(record)+'\nPOL-2026.2')
    paid=batches(parsed)[1];prior=deepcopy(workflow(paid))
    exception(record,amount='80.0')
    claim=deepcopy(paid['domain']['revision_history']['claim']['SYN-C01']['revisions'][0]);claim['record']=record
    finance=deepcopy(paid['finance_reconciliations']['SYN-C01']);finance['revision_history']=[claim]
    current=connect_claim(parsed=parsed,claim=claim,decisions=parsed['records']['decisions'],
        finance_events=paid['domain']['finance_records'],finance=finance,cancellations=[],arrival_batch=3,
        source_observations=parsed['source_observations'],prior_finance=paid['finance_reconciliations']['SYN-C01'],prior_workflow=prior)
    assert not current['exception_revalidation']['same_revision_change']
    assert current['lines'][0]['calculated_cents']==8000


def test_administration_cannot_collapse_into_another_permit_role():
    parsed=synthetic();trip=fields(parsed['records']['trips'][0]);trip.update({'International':True,
        'Permit reference':'P-SYN','Permit revision':1,'Estimate (EUR)':100,'First commitment date':'2026-09-01'})
    person=table(parsed,'people','People')[0]
    setfield(person,'Supervisor',fields(person)['Administration reviewer'])
    decisions=deepcopy(parsed['records']['decisions'][:2])
    for d in decisions:
        setfield(d,'Subject type','permit');setfield(d,'Subject reference','P-SYN');setfield(d,'Decision time (UTC)','2026-08-30T12:00:00')
    setfield(decisions[0],'Review roles','administration\nsupervisor')
    items=travel_findings(trip=trip,employee='EMP-01',decisions=decisions,people=table(parsed,'people','People'),
        cancellations=[],fields=fields,ref=ref,observations=parsed['source_observations'])
    assert items[0]['issue']=='permit_unapproved'

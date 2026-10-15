"""Step 184: synthetic mutations of retained schemas, never real authority."""
from copy import deepcopy
import pytest

from test_expenses import setup, evaluate, merchant, setfield
from test_approvals import subject, check
from test_ordinary import synthetic, batches, workflow, stages
from travel_claim.policy_evidence import CLOCK


@pytest.mark.parametrize('kind', ['receipt','merchant','claim'])
@pytest.mark.parametrize('field,value', [('source_sha256',None),('source_sha256','0'*64),
    ('source_sha256','bad'),('source_id','unobserved-source'),('locator',None),('locator',' ')])
def test_expense_evidence_needs_verified_source_reference(kind,field,value):
    p,r,t=setup()
    row={'receipt':p['records']['receipts'][0],'merchant':merchant(p),'claim':r}[kind]
    row[field]=value
    before=deepcopy(row)
    result,lines=evaluate(p,r,t)
    assert result['status']=='BLOCKED' and lines[0]['calculated_cents'] is None
    assert lines[0]['evidence_status']=='BLOCKED'
    assert row==before
    assert 'source' in lines[0]['reason'].lower()


def test_step183_unbound_evidence_cannot_close_connected_workflow():
    p=synthetic()
    p['records']['receipts'][0]['source_sha256']='0'*64
    merchant(p)['source_sha256']='0'*64
    before=deepcopy(p)
    result=batches(p)[-1];w=workflow(result)
    assert w['status']=='pending' and w['allowed_cents'] is None and w['request'] is None
    assert stages(w)['supporting_evidence']['status']=='BLOCKED'
    assert result['finance_reconciliations']['SYN-C01']['net_confirmed_cents']==10000
    assert p==before
    assert any('0'*64 in r for r in w['lines'][0]['source_refs'])


@pytest.mark.parametrize('kind',['claim','permit'])
@pytest.mark.parametrize('stamp,approved', [('2026-11-14T22:59:59Z',True),
    ('2026-11-14T23:00:00Z',False),('2026-11-15T12:00:00Z',False),
    ('2026-11-15T23:00:00Z',False),('2027-01-01T12:00:00Z',False)])
def test_reviews_use_policy_calendar_date_in_amsterdam(kind,stamp,approved):
    p,r,t=subject(kind);p['event_clock']=dict(CLOCK)
    decision=p['records']['decisions'][0]
    setfield(decision,'Decision time (UTC)',stamp)
    before=deepcopy(decision)
    result=check(p,r,t,kind=kind)
    assert result['approved']==approved
    delivery=next(d for d in result['deliveries'] if d['decision_id']==decision['values']['Decision reference']['value'])
    assert delivery['raw_record']==before
    assert delivery['evidence_valid']==approved and delivery['active']==approved
    if not approved: assert delivery['rejection_reasons']


@pytest.mark.parametrize('stamp',['2026-11-15T12:00:00Z','2026-11-16T12:00:00Z'])
def test_late_review_cannot_authorize_connected_reimbursement(stamp):
    p=synthetic();p['event_clock']=dict(CLOCK)
    setfield(p['records']['decisions'][0],'Decision time (UTC)',stamp)
    result=batches(p)[-1];w=workflow(result)
    assert not w['claim_approval']['approved']
    assert w['request'] is None and w['status']=='pending'
    assert stages(w)['required_approvals']['status']=='BLOCKED'
    assert result['domain']['decision_records']==p['records']['decisions']


@pytest.mark.parametrize('status,scope', [('partial',[]),('unavailable',[]),('read',['missing page']),('read',None)])
def test_incomplete_source_observation_is_not_expense_authority(status,scope):
    p,r,t=setup();receipt=p['records']['receipts'][0]
    obs=next(o for o in p['source_observations'] if o['source_id']==receipt['source_id'])
    obs.update(status=status,missing_scope=scope)
    assert evaluate(p,r,t)[0]['status']=='BLOCKED'


@pytest.mark.parametrize('kind',['trip','directory'])
def test_eligibility_context_requires_verified_sources(kind):
    p,r,t=setup()
    table_name='Trips' if kind=='trip' else 'People'
    target=next(s['records'][0] for s in p['workbook_sheets'] if s['name']==table_name) if kind=='directory' else p['records']['trips'][0]
    target['source_sha256']='0'*64
    result,lines=evaluate(p,r,t)
    assert result['status']=='BLOCKED' and lines[0]['calculated_cents'] is None


@pytest.mark.parametrize('kind',['cap','fx'])
@pytest.mark.parametrize('verified',[True,False])
def test_only_observed_cap_and_fx_sources_can_supply_amounts(kind,verified):
    from travel_claim.ordinary import table
    p,r,t=setup()
    if kind=='cap':
        setfield(p['records']['receipts'][0],'Category','lodging')
        setfield(p['records']['receipts'][0],'Documented units','1')
        evidence=dict(source_id='synthetic-cap',source_sha256='a'*64,locator='SYNTHETIC cap',values={})
        p['source_observations'].append(dict(source_id='synthetic-cap',sha256='a'*64,status='read',missing_scope=[]))
        for key,value in {'Destination':t['Destination'],'Category':'lodging','Currency':'EUR',
            'Effective from':'2026-01-01','Effective to':'2026-12-31','Amount per unit':'40'}.items():setfield(evidence,key,value)
        p['records']['caps']=[evidence]
    else:
        r['text']=r['text'].replace('EUR','USD')
        setfield(p['records']['receipts'][0],'Currency','USD');setfield(merchant(p),'Currency','USD')
        evidence=deepcopy(table(p,'fx_rates','FX')[0])
        for key,value in {'Currency':'USD','Rate date':'2026-09-01','EUR per currency unit':'0.90005'}.items():setfield(evidence,key,value)
        p['records']['fx_rates']=[evidence]
    if not verified:evidence['source_sha256']='0'*64
    before=deepcopy(evidence)
    result,lines=evaluate(p,r,t)
    assert (result['status']=='PASS')==verified
    assert evidence==before
    if not verified:
        assert result['calculated_cents'] is None
        assert any('0'*64 in ref for ref in lines[0]['source_refs'])


def test_unverified_prior_submission_cannot_supply_timely_filing():
    p,r,t=setup();old=deepcopy(r);old['source_sha256']='0'*64
    r['text']=r['text'].replace('2026-09-01','2026-11-01');setfield(r,'Submitted date','2026-11-01')
    t['End date']='2026-08-31'
    result,lines=evaluate(p,r,t,[dict(revision=1,record=old)])
    assert result['status']=='BLOCKED' and 'Prior submission' in lines[0]['reason']


@pytest.mark.parametrize('kind',['receipt','merchant'])
def test_native_evidence_locator_must_be_verifiable(kind):
    p,r,t=setup();target=p['records']['receipts'][0] if kind=='receipt' else merchant(p)
    target['locator']='unverifiable record reference'
    assert evaluate(p,r,t)[0]['status']=='BLOCKED'


@pytest.mark.parametrize('clock,stamp,approved', [
    ('2026-09-15T12:00:00Z','2026-09-15T12:00:00Z',True),
    ('2026-09-15T12:00:00Z','2026-09-15T12:00:01Z',False),
    (None,'2026-09-03T12:00:00Z',False)])
def test_exact_supplied_clock_and_missing_clock(clock,stamp,approved):
    p,r,t=subject();p['event_clock']=clock;p['case_clock']=clock
    setfield(p['records']['decisions'][0],'Decision time (UTC)',stamp)
    assert check(p,r,t)['approved']==approved


def test_inadmissible_later_review_stays_in_history_without_replacing_earlier_authority():
    p,r,t=subject();p['event_clock']=dict(CLOCK)
    later=deepcopy(p['records']['decisions'][0]);setfield(later,'Decision reference','SYN-FUTURE')
    setfield(later,'Decision time (UTC)','2026-11-16T00:00:00Z')
    from travel_claim.approvals import table
    packet=deepcopy(table(p,'review_packets','Review packets')[0]);setfield(packet,'Decision reference','SYN-FUTURE')
    p['records']['decisions'].append(later);table(p,'review_packets','Review packets').append(packet)
    first=check(p,r,t);replay=check(p,r,t)
    assert first==replay and first['approved']
    held=next(d for d in first['deliveries'] if d['decision_id']=='SYN-FUTURE')
    assert not held['active'] and not held['evidence_valid'] and held['raw_record']==later


@pytest.mark.parametrize('fault',['expense','review'])
def test_independent_valid_claim_still_closes_when_other_claim_is_held(fault):
    import json
    from travel_claim.approvals import table
    p=synthetic()
    good=json.loads(json.dumps(p).replace('SYN-C01','SYN-C02').replace('COST-01','COST-02'))
    p['records']['finance_events']=[];p['records']['reimbursement_requests']=[]
    if fault=='expense':p['records']['receipts'][0]['source_sha256']='0'*64
    else:setfield(p['records']['decisions'][0],'Decision time (UTC)','2027-01-01T12:00:00Z')
    p['records']['merchant_payments']=deepcopy(table(p,'merchant_payments','Merchant payments')+table(good,'merchant_payments','Merchant payments'))
    p['records']['review_packets']=deepcopy(table(p,'review_packets','Review packets')+table(good,'review_packets','Review packets'))
    for key in ['claim_revisions','receipts','decisions','finance_events','reimbursement_requests','closure_authorities']:
        p['records'][key].extend(deepcopy(good['records'][key]))
    result=batches(p)[-1]
    assert workflow(result)['status']=='pending'
    assert workflow(result,'SYN-C02')['status']=='closed-reimbursed'
    assert workflow(result,'SYN-C02')['allowed_cents']==10000


def test_clock_recheck_preserves_previously_retained_review_history():
    p,r,t=subject();p['event_clock']='2026-11-15T23:00:00Z'
    setfield(p['records']['decisions'][0],'Decision time (UTC)','2026-11-15T12:00:00Z')
    prior=check(p,r,t);saved=deepcopy(prior)
    assert prior['approved']
    p['event_clock']=dict(CLOCK)
    current=check(p,r,t,prior=prior)
    assert not current['approved'] and prior==saved
    assert current['deliveries'][0]['raw_record']==prior['deliveries'][0]['raw_record']


def test_no_source_observations_cannot_establish_employee_paid_expense():
    p,r,t=setup();p['source_observations']=[]
    assert evaluate(p,r,t)[0]['status']=='BLOCKED'


def test_matching_but_malformed_hash_is_not_verified_authority():
    p,r,t=setup();receipt=p['records']['receipts'][0]
    observation=next(o for o in p['source_observations'] if o['source_id']==receipt['source_id'])
    receipt['source_sha256']=observation['sha256']='not-a-sha256'
    assert evaluate(p,r,t)[0]['status']=='BLOCKED'


@pytest.mark.parametrize('kind',['page','cell'])
def test_native_locator_must_agree_with_retained_record_metadata(kind):
    p,r,t=setup()
    if kind=='page':r['locator']='PDF page 999'
    else:merchant(p)['locator']="tab 'Merchant payments', row 999"
    result,lines=evaluate(p,r,t)
    assert result['status']=='BLOCKED' and lines[0]['evidence_status']=='BLOCKED'

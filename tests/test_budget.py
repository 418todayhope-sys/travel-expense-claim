"""Policy budget arithmetic and actual retained rows; mutations are synthetic."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from test_ordinary import synthetic,batches,workflow,stages,row
from test_expenses import setfield
from travel_claim.approvals import fields,table,ref
from travel_claim.budget import reconcile_budgets,scope_id,budget_reply_error,claim_budget_view
from travel_claim.expenses import load_expense_policy
from travel_claim.integration import integrate_arrival_batch

SCOPE=scope_id(('Consulting','Client-A','2026'))


def scope(result):return result['domain']['budget']['scopes'][SCOPE]


def native():
    p=json.loads((Path(__file__).parent/'fixtures/retained_budget_records.json').read_text())
    p['expense_policy']=load_expense_policy(Path(__file__).parent/'fixtures/POL-2026.2-browser-copy.txt')
    p['event_clock']={'date':'2026-11-15','timezone':'Europe/Amsterdam'}
    return p


def run_one(p,batch=1,prior=None):
    return integrate_arrival_batch(p,arrival_batch=batch,run_id='budget-test',batch_id=f'arrival-{batch:03d}',
        source_binding={'path':'sources.json','sha256':'a'*64},predecessor={'path':f'batches/arrival-{batch-1:03d}.json','sha256':'b'*64} if prior else None,
        prior_result=prior,source_observations=p['source_observations'])


def test_native_opening_ledger_does_not_subtract_settled_part_twice():
    p=synthetic();p['records']['claim_revisions']=[];p['records']['finance_events']=[]
    value=scope(run_one(p))
    assert value['allocation_cents']==2000000
    assert value['historical_net_settled_cents']==200000
    assert value['remaining_commitment_cents']==300000
    assert value['available_cents']==1500000
    assert value['opening_obligations']['OLD-1']['revision'] is None
    assert value['opening_obligations']['OLD-1']['arrival_batch'] is None
    assert value['opening_obligations']['OLD-1']['source_refs']


def test_request_settlement_and_exact_redelivery_never_double_count():
    results=batches(synthetic());first,paid,_,final=results
    assert scope(first)['available_cents']==scope(paid)['available_cents']==1490000
    assert scope(first)['requests']['REQ-SYN-C01']['authorized_obligation_cents']==10000
    assert scope(first)['requests']['REQ-SYN-C01']['authorized_balance_cents']==10000
    assert scope(paid)['requests']['REQ-SYN-C01']['authorized_balance_cents']==0
    assert scope(first)['remaining_commitment_cents']==310000
    assert scope(paid)['remaining_commitment_cents']==300000
    assert scope(paid)['confirmed_payment_cents']==10000
    assert scope(final)['requests']['REQ-SYN-C01']['confirmed_payment_cents']==10000
    assert len(scope(final)['requests']['REQ-SYN-C01']['events'])==2
    assert final['finance_reconciliations']['SYN-C01']['admitted_events']==paid['finance_reconciliations']['SYN-C01']['admitted_events']


@pytest.mark.parametrize('allocation,expected',[(5000,'BLOCKED'),(5100,'PASS'),(5099.99,'BLOCKED')])
def test_budget_exhaustion_and_exact_funding_boundary(allocation,expected):
    p=synthetic();budget=table(p,'budget','Budget')[0];setfield(budget,'Allocation or commitment (EUR)',allocation)
    current=workflow(batches(p)[-1])
    assert current['budget_view']['status']==expected
    assert stages(current)['budget_availability']['status']==expected
    assert (current['request'] is not None)==(expected=='PASS')
    assert current['lines'][0]['calculated_cents']==10000


@pytest.mark.parametrize('field,value',[('Allocation or commitment (EUR)',None),('Allocation or commitment (EUR)',True),
    ('Settled (EUR)','0.001'),('Refunded (EUR)',1),('Currency','USD'),('Ledger reference',None),
    ('Entry type','unknown'),('Revision',True),('Arrival batch','1.5')])
def test_invalid_budget_identity_precision_and_optional_membership_are_held(field,value):
    p=synthetic();setfield(table(p,'budget','Budget')[0],field,value)
    result=run_one(p)
    assert scope(result)['status']=='BLOCKED'
    assert scope(result)['available_cents'] is None
    assert workflow(result)['request'] is None


def test_missing_scope_allocation_never_defaults_to_zero_or_borrows_other_scope():
    p=synthetic();person=table(p,'people','People')[0];setfield(person,'Project','MISSING')
    value=workflow(run_one(p))['budget_view']
    assert value['status']=='BLOCKED' and value.get('available_cents') is None


def test_exact_duplicate_ledger_is_inert_and_conflict_preserves_admitted_facts():
    p=synthetic();budget=table(p,'budget','Budget');budget.append(deepcopy(budget[0]))
    initial=run_one(p);assert scope(initial)['allocation_cents']==2000000
    setfield(budget[-1],'Allocation or commitment (EUR)',1)
    result=run_one(p,2,initial)
    assert scope(result)['allocation_cents']==2000000 and scope(result)['available_cents'] is None
    assert result['domain']['budget']['admitted_budget_entries']['B-ALLOC']==initial['domain']['budget']['admitted_budget_entries']['B-ALLOC']


def test_version_bound_opening_correction_changes_budget_and_revalidates_only_budget_role():
    p=synthetic();first=run_one(p)
    # Separate synthetic ledger source isolates this budget change from unchanged trip/directory facts.
    new_rows=deepcopy(table(p,'budget','Budget'))
    for r in new_rows:r.update(source_id='synthetic-budget-revision',source_sha256='d'*64)
    setfield(new_rows[0],'Allocation or commitment (EUR)',19000)
    p['records']['budget']=new_rows
    p['source_observations'].append(dict(source_id='synthetic-budget-revision',sha256='d'*64,status='read',missing_scope=[]))
    changed=run_one(p,2,first);view=workflow(changed)['budget_view']
    assert scope(changed)['allocation_cents']==1900000
    assert view['material_batch']==2
    deliveries=workflow(changed)['claim_approval']['deliveries']
    assert next(d for d in deliveries if 'administration' in d['roles'])['evidence_valid']
    owner=next(d for d in deliveries if 'budget_owner' in d['roles'])
    assert owner['evidence_valid'] and not owner['budget_evidence_valid']
    assert stages(workflow(changed))['request_obligation']['status']=='BLOCKED'
    decision=deepcopy(p['records']['decisions'][1]);setfield(decision,'Decision reference','SYN-BUDGET-REVIEW-NEW');setfield(decision,'Arrival batch',3)
    setfield(decision,'Decision time (UTC)','2026-09-13T12:00:00');setfield(decision,'Source revisions','SRC-D-3\nPOL-2026.2\n'+'d'*64)
    packet=deepcopy(table(p,'review_packets','Review packets')[1]);setfield(packet,'Decision reference','SYN-BUDGET-REVIEW-NEW')
    p['records']['decisions'].append(decision);table(p,'review_packets','Review packets').append(packet)
    # Existing request names old decisions, so recovered budget authority alone never sends a new request.
    recovered=run_one(p,3,changed)
    assert workflow(recovered)['claim_approval']['approved']
    assert workflow(recovered)['request'] is None
    assert scope(recovered)['allocation_cents']==1900000


def test_native_prepaid_cost_corrections_cancellations_refunds_and_refs():
    results=batches(native());first,paid,changed,final=results
    c24=workflow(changed,'C24')['budget_view']
    assert c24['prior_committed_cents']==c24['prior_net_paid_cents']==20000
    assert c24['remaining_request_cents']==5000
    cost=next(l for l in c24['lines'] if l['cost_id']=='COST-03')
    assert cost['remaining_request_cents']==0 and cost['prior_reservations'][0]['request_id']=='REQ-C03'
    assert any('#PDF page 3' in r for r in cost['source_refs'])
    req18=scope(changed)['requests']['REQ-C18'];assert req18['commitment_cents']==0 and req18['net_paid_cents']==0
    late18=scope(final)['requests']['REQ-C18'];assert late18['commitment_cents']==0 and late18['net_paid_cents']==10000
    assert scope(changed)['requests']['REQ-C19']['recorded_balance_cents']==-2000
    req19=scope(final)['requests']['REQ-C19']
    assert req19['confirmed_payment_cents']==10000 and req19['confirmed_refund_cents']==2000
    assert req19['commitment_cents']==8000 and req19['remaining_commitment_cents']==0
    assert scope(final)['available_cents']==1457000
    assert all(finance.get('authorized_obligation') is None for finance in final['finance_reconciliations'].values())
    assert final['finance_reconciliations']['C18']['net_confirmed_cents']==10000
    assert scope(first)['opening_obligations']==scope(final)['opening_obligations']


def test_business_cancellation_alone_does_not_release_finance_commitment():
    p=native();p['records']['finance_events']=[r for r in p['records']['finance_events'] if fields(r).get('Activity reference')!='F-C18-2']
    result=batches(p)[-1]
    assert scope(result)['requests']['REQ-C18']['commitment_cents']==10000
    assert result['snapshot']['travel_cancellations']


def test_conflicting_finance_redelivery_holds_without_erasing_paid_money():
    p=synthetic();first=run_one(p);paid=run_one(p,2,first)
    duplicate=deepcopy(p['records']['finance_events'][1]);setfield(duplicate,'Arrival batch',3);setfield(duplicate,'Amount (EUR)',999)
    p['records']['finance_events'].append(duplicate)
    held=run_one(p,3,paid)
    assert scope(held)['available_cents'] is None and scope(held)['confirmed_payment_cents']==10000
    assert held['finance_reconciliations']['SYN-C01']['admitted_events']==paid['finance_reconciliations']['SYN-C01']['admitted_events']


def test_budget_sufficiency_is_not_human_budget_approval():
    p=synthetic();p['records']['decisions']=[d for d in p['records']['decisions'] if fields(d).get('Review roles')!='budget_owner']
    value=workflow(batches(p)[-1]);assert value['budget_view']['status']=='PASS'
    assert not value['claim_approval']['approved'] and value['request'] is None


def test_exact_batch_replay_preserves_scope_prepaid_history_and_admitted_events():
    p=synthetic();first=run_one(p)
    replay=integrate_arrival_batch(p,arrival_batch=1,run_id='budget-test',batch_id='arrival-001',
        source_binding={'path':'sources.json','sha256':'a'*64},prior_result=first,source_observations=p['source_observations'])
    assert replay['domain']==first['domain'] and replay['snapshot']==first['snapshot']


def test_refund_alone_does_not_release_an_unchanged_commitment():
    p=synthetic();refund=deepcopy(p['records']['finance_events'][1])
    setfield(refund,'Activity reference','SYN-REFUND');setfield(refund,'Activity type','refund')
    setfield(refund,'Arrival batch',3);setfield(refund,'Amount (EUR)',20)
    setfield(refund,'Original activity reference',fields(p['records']['finance_events'][1])['Activity reference'])
    setfield(refund,'Activity time (UTC)','2026-09-13T12:00:00');p['records']['finance_events'].append(refund)
    results=batches(p);before=scope(results[1]);after=scope(results[-1])
    assert after['confirmed_refund_cents']==2000
    assert after['requests']['REQ-SYN-C01']['remaining_commitment_cents']==2000
    assert before['available_cents']==after['available_cents']


def test_ambiguous_shared_cost_allocation_is_held_not_prorated():
    p=synthetic();result=run_one(p);record=p['records']['claim_revisions'][0]
    from travel_claim.ordinary import expense_lines
    attribution={'costs':{},'unallocated_costs':{'COST-01':[dict(claim_id='EARLIER',request_id='REQ-EARLIER',source_refs=[ref(record)])]}}
    view=claim_budget_view(parsed=p,claim=result['domain']['revision_history']['claim']['SYN-C01']['revisions'][0],
        lines=[dict(expense_lines(record)[0],calculated_cents=10000)],budgets=result['domain']['budget'],attribution=attribution,arrival_batch=1)
    assert view['remaining_request_cents'] is None and view['status']=='BLOCKED'
    assert any('allocation' in i['reason'] for i in view['issues'])


def test_budget_owner_packet_must_include_the_whole_scope_ledger():
    p=synthetic();packet=table(p,'review_packets','Review packets')[1]
    setfield(packet,'Budget record references','B-ALLOC')
    value=workflow(batches(p)[-1])
    assert value['budget_view']['status']=='PASS' and not value['claim_approval']['approved']
    owner=next(d for d in value['claim_approval']['deliveries'] if 'budget_owner' in d['roles'])
    assert 'omits' in owner['budget_revalidation_reason']


def test_correction_cannot_offset_a_different_cost_with_an_old_own_commitment():
    p=native();p['records']['finance_events']=[r for r in p['records']['finance_events'] if fields(r).get('Activity reference')!='F-C18-2']
    result=batches(p)[-1];view=workflow(result,'C18')['budget_view']
    assert scope(result)['requests']['REQ-C18']['commitment_cents']==10000
    assert view['remaining_request_cents']==10000
    assert view['existing_recorded_commitment_cents']==0 and view['incremental_cents']==10000


def test_other_scope_conflict_does_not_block_an_independent_valid_claim():
    p=synthetic();other=deepcopy(table(p,'budget','Budget')[0]);setfield(other,'Ledger reference','OTHER-ALLOC');setfield(other,'Project','OTHER')
    conflict=deepcopy(other);setfield(conflict,'Allocation or commitment (EUR)',1)
    table(p,'budget','Budget').extend([other,conflict]);result=batches(p)[-1]
    assert scope(result)['status']=='PASS' and workflow(result)['status']=='closed-reimbursed'
    assert result['domain']['budget']['scopes'][scope_id(('Consulting','OTHER','2026'))]['status']=='BLOCKED'


def test_prior_paid_cost_mismatch_requires_finance_repair_instead_of_zero():
    p=native();record=next(r for r in p['records']['claim_revisions'] if fields(r).get('Claim reference')=='C24')
    # No invented evidence: a deliberately broken link must remain unresolved.
    setfield(record,'Related earlier claims','None')
    value=workflow(batches(p)[-1],'C24')['budget_view']
    assert value['status']=='BLOCKED' and value['remaining_request_cents'] is None
    assert any('linkage' in i['reason'] for i in value['issues'])


def test_budget_membership_uses_only_arrived_rows_and_keeps_first_replay_context():
    p=synthetic();original=table(p,'budget','Budget')[0];setfield(original,'Arrival batch',1)
    first=run_one(p)
    duplicate=deepcopy(original);setfield(duplicate,'Arrival batch',2);duplicate['locator']='SYNTHETIC redelivered ledger'
    p['records']['budget']=[duplicate]+deepcopy(table(p,'budget','Budget')[1:])
    second=run_one(p,2,first)
    fact=second['domain']['budget']['admitted_budget_entries']['B-ALLOC']
    assert fields(fact)['Arrival batch']==1 and fact['locator']==original['locator']
    assert scope(first)['allocation_cents']==scope(second)['allocation_cents']==2000000
    assert second['domain']['budget']['budget_deliveries'][0]['locator']==duplicate['locator']
    future=deepcopy(original);setfield(future,'Arrival batch',4);setfield(future,'Ledger reference','FUTURE-ALLOCATION')
    p['records']['budget'].append(future)
    third=run_one(p,3,second)
    assert scope(third)['allocation_cents']==2000000


def test_tampered_budget_readiness_state_fails_evidence_replay(tmp_path):
    from test_readiness import _run,_repo,SCHEMA
    from travel_claim.readiness import validate_readiness
    run=_run(tmp_path);path=run/'offline-replay-state.json';state=json.loads(path.read_text())
    state['budget_reconciliation']['arrival_batch']=999;path.write_text(json.dumps(state))
    report=validate_readiness(run,schema_path=SCHEMA,repo_dir=_repo(tmp_path))
    assert report['status']=='FAIL'
    assert any(c['status']=='FAIL' and c['check']=='snapshot-content-evidence' for c in report['checks'])


def test_budget_owner_repairs_are_grouped_with_exact_claim_revision_and_sources():
    p=synthetic();setfield(table(p,'budget','Budget')[0],'Allocation or commitment (EUR)',1)
    result=run_one(p);items=result['repair_queue_by_owner']['LEAD-01']
    item=next(i for i in items if 'budget_owner_authorization' in i['item_id'])
    assert item['subject_id']=='SYN-C01' and item['revision']==1 and item['status']=='open'
    assert item['source_refs'] and all('@' in r and '#' in r for r in item['source_refs'])
    assert 'complete scope ledger' in item['next_action']


def test_transfer_attempt_cancellation_is_not_request_release_or_cash_refund():
    p=synthetic();transfer=p['records']['finance_events'][1];cancel=deepcopy(transfer)
    setfield(cancel,'Activity reference','SYN-ATTEMPT-CANCEL');setfield(cancel,'Activity type','cancelled')
    setfield(cancel,'Arrival batch',3);setfield(cancel,'Original activity reference',fields(transfer)['Activity reference'])
    setfield(cancel,'Activity time (UTC)','2026-09-13T12:00:00');cancel['values'].pop('Amount (EUR)',None)
    p['records']['finance_events'].append(cancel)
    result=batches(p)[-1];request=scope(result)['requests']['REQ-SYN-C01']
    assert request['commitment_cents']==10000 and request['net_paid_cents']==10000
    assert request['confirmed_refund_cents']==0 and scope(result)['status']=='BLOCKED'
    assert any('transfer activity' in i['reason'] for i in scope(result)['issues'])


def test_new_finance_batch_can_be_reviewed_using_verified_native_printed_version():
    p=synthetic();result=run_one(p);context=deepcopy(workflow(result)['budget_view'])
    context.update(material_batch=2,requires_exact_source=False,printed_source_versions=['SRC-D-3'])
    decision=deepcopy(p['records']['decisions'][1]);setfield(decision,'Arrival batch',3)
    setfield(decision,'Decision time (UTC)','2026-09-13T12:00:00')
    assert budget_reply_error(context,decision,table(p,'review_packets','Review packets')[1]) is None
    context['requires_exact_source']=True
    assert 'version binding' in budget_reply_error(context,decision,table(p,'review_packets','Review packets')[1])


@pytest.mark.parametrize('identity',[True,1,' '])
def test_budget_ledger_identity_requires_a_stable_nonblank_string(identity):
    p=synthetic();setfield(table(p,'budget','Budget')[0],'Ledger reference',identity)
    result=run_one(p)
    assert scope(result)['status']=='BLOCKED' and scope(result)['allocation_cents'] is None


def test_future_redelivery_does_not_retire_an_already_observed_opening_fact():
    p=synthetic();first=run_one(p)
    rows=deepcopy(table(p,'budget','Budget'));setfield(rows[0],'Arrival batch',4);p['records']['budget']=rows
    second=run_one(p,2,first)
    assert scope(second)['status']=='PASS' and scope(second)['allocation_cents']==2000000

"""POL-2026.2 lines 21, 27 and 29; no real financial projections changed."""
from copy import deepcopy
import json

import pytest

from test_finance import _finance_row
from test_integration import _parsed_fixture, _integrate
from travel_claim.finance import reconcile_finance_events
from travel_claim.workflow import reduce_cancellation_activities

CLOCK = {'date': '2026-11-15', 'timezone': 'Europe/Amsterdam'}
CONTEXT = {'clock': CLOCK, 'requests': {'REQ-SYN': {
    'claim_id': 'C-SYN-01', 'payee_id': 'EMP-SYN', 'actor': 'FIN-SYN-01', 'currency': 'EUR'}}}


def finance(events, previous=None, context=CONTEXT):
    return reconcile_finance_events(events, claim_id='C-SYN-01', current_revision=1,
        event_context=context, previous_reconciliation=previous,
        authorized_obligation={'amount_cents': 1000, 'claim_revision': 1, 'source_refs': ['synthetic:authority']})


def payment():
    return _finance_row(1, 'SYN-PAY', 'settled', amount=10)


def test_admitted_payment_survives_conflict_exact_replay_and_delta_only_calls():
    first = payment(); initial = finance([first]); saved = deepcopy(initial)
    replay = deepcopy(first); replay['values']['Arrival batch']['value'] = 2; replay['locator'] = 'SYNTHETIC redelivery'
    duplicate = finance([replay], initial)
    assert duplicate['net_confirmed_cents'] == 1000
    assert len(duplicate['event_history']) == 2
    bad = deepcopy(replay); bad['values']['Amount (EUR)']['value'] = 99; bad['locator'] = 'SYNTHETIC conflict'
    held = finance([bad], duplicate)
    assert held['net_confirmed_cents'] == 1000 and held['balance_cents'] is None
    assert held['confirmed_payment_event_ids'] == ['SYN-PAY']
    assert held['admitted_events']['SYN-PAY']['source_record']['Amount (EUR)'] == 10
    assert held['conflicting_events'] and any('conflict' in i['record_id'] for i in held['repair_issues'])
    # Another exact replay does not silently resolve the earlier conflict.
    final = finance([replay], json.loads(json.dumps(held)))
    assert final['net_confirmed_cents'] == 1000 and final['balance_cents'] is None
    assert len(final['event_history']) == 3
    assert final['admitted_events'] == initial['admitted_events']
    assert initial == saved


@pytest.mark.parametrize('field,value', [
    ('Activity reference', ''), ('Request reference', 'REQ-UNKNOWN'), ('Payee ID', 'WRONG'),
    ('Currency', 'USD'), ('Finance officer', 'EMP-SYN'), ('Amount (EUR)', 0),
    ('Amount (EUR)', -1), ('Amount (EUR)', '0.001'), ('Amount (EUR)', True),
    ('Activity time (UTC)', 'not-a-time'), ('Activity time (UTC)', '2026-11-16T00:00:00Z'),
    ('Activity time (UTC)', '2026-11-15T00:00:00Z'), ('Activity time (UTC)', '2026-09-01T12:00:00+01:00')])
def test_invalid_finance_delivery_stays_visible_without_admission(field, value):
    event = payment(); event['values'][field]['value'] = value
    result = finance([event])
    assert result['net_confirmed_cents'] == 0 and result['admitted_events'] == {}
    assert result['balance_cents'] is None
    assert result['event_history'][0]['source_record'][field] == value
    assert result['repair_issues']


def test_missing_finance_fields_and_context_do_not_gain_authority_from_event_itself():
    for field in ('Request reference', 'Payee ID', 'Finance officer', 'Activity time (UTC)'):
        event = payment(); event['values'].pop(field)
        assert finance([event])['admitted_events'] == {}
    assert finance([payment()], context=None)['admitted_events'] == {}


def test_same_batch_conflicts_are_held_without_choosing_sheet_row_authority():
    event = payment(); conflict = deepcopy(event); conflict['values']['Amount (EUR)']['value'] = 11
    assert finance([event, conflict])['admitted_events'] == {}
    assert finance([conflict, event])['net_confirmed_cents'] == 0


def test_refunds_keep_admitted_money_and_validate_original_payee_request_and_remainder():
    transfer = payment()
    refund = _finance_row(2, 'SYN-REFUND', 'refund', amount=4, original='SYN-PAY', batch=2)
    initial = finance([transfer, refund]); assert initial['net_confirmed_cents'] == 600
    excess = _finance_row(3, 'SYN-EXCESS', 'refund', amount=7, original='SYN-PAY', batch=3)
    result = finance([excess], initial)
    assert result['net_confirmed_cents'] == 600
    assert result['confirmed_refund_event_ids'] == ['SYN-REFUND']
    assert 'SYN-EXCESS' in result['unresolved_event_ids']
    bad = deepcopy(refund); bad['values']['Amount (EUR)']['value'] = 5; bad['locator'] = 'SYNTHETIC refund conflict'
    result = finance([bad], initial)
    assert result['net_confirmed_cents'] == 600 and result['conflicting_events']


def business():
    parsed = _parsed_fixture()
    events = [r for r in parsed['records']['cancellation_activities']
              if r['values']['Cancellation reference']['value'] == 'TC-SYN-TRIP']
    return events, {'trips': parsed['records']['trips'], 'people': parsed['records']['people'],
                    'clock': CLOCK, 'arrival_batch': 4}


def reduce(events, ctx, previous=None):
    return reduce_cancellation_activities(events, previous_state=previous, **ctx)


@pytest.mark.parametrize('fault', ['actor', 'equal', 'scheduled', 'backdated', 'future', 'same-day',
                                  'target', 'permit', 'initiation', 'stale-trip', 'stale-permit'])
def test_invalid_confirmation_cannot_establish_authority(fault):
    events, ctx = business(); value = events[1]['values']
    if fault == 'actor': value['Acting employee or supervisor']['value'] = 'FIN-SYN-01'
    elif fault == 'equal':
        value['Activity time (UTC)']['value'] = events[0]['values']['Activity time (UTC)']['value']
        value['Effective time (UTC)']['value'] = value['Activity time (UTC)']['value']
    elif fault in {'scheduled', 'backdated'}: value['Effective time (UTC)']['value'] = '2026-09-03T09:00:00' if fault == 'scheduled' else '2026-09-01T09:00:00'
    elif fault in {'future', 'same-day'}:
        value['Activity time (UTC)']['value'] = '2026-11-16T09:00:00Z' if fault == 'future' else '2026-11-15T09:00:00Z'
        value['Effective time (UTC)']['value'] = value['Activity time (UTC)']['value']
    elif fault == 'target': value['Trip reference']['value'] = 'T-SYN-02'
    elif fault == 'permit': value['Permit reference']['value'] = 'P-OTHER'
    elif fault == 'initiation': value['Initiation activity reference']['value'] = 'UNMATCHED'
    elif fault == 'stale-trip':
        new = deepcopy(ctx['trips'][0]); new['values']['Trip revision']['value'] = 2; ctx['trips'].append(new)
    else: value['Permit revision']['value'] = 9
    result = reduce(events, ctx)
    assert result['processes']['TC-SYN-TRIP']['state'] != 'confirmed'
    assert events[1] in result['delivery_history'] and result['issues']
    assert events[1]['values']['Cancellation activity reference']['value'] not in result['admitted_records']
    assert result['finance_effects'] == []


def test_invalid_and_conflicting_deliveries_preserve_admitted_cancellation_history():
    events, ctx = business(); initial = reduce(events, ctx); saved = deepcopy(initial)
    process = initial['processes']['TC-SYN-TRIP']
    assert process['state'] == 'confirmed'
    wrong = deepcopy(events[1]); wrong['values']['Acting employee or supervisor']['value'] = 'FIN-SYN-01'
    wrong['values']['Arrival batch']['value'] = 3; wrong['locator'] = 'SYNTHETIC invalid redelivery'
    result = reduce([wrong], ctx, json.loads(json.dumps(initial)))
    assert result['processes']['TC-SYN-TRIP'] == process
    assert result['admitted_records'] == initial['admitted_records']
    assert result['conflicting_events'] and len(result['delivery_history']) == 3
    replay = deepcopy(events[1]); replay['values']['Arrival batch']['value'] = 4
    final = reduce([replay], ctx, result)
    assert final['processes']['TC-SYN-TRIP'] == process
    assert final['issues'] and initial == saved


def test_confirmation_rechecks_when_initiation_arrives_and_never_depends_on_row_order():
    events, ctx = business(); request, confirm = events
    confirm['values']['Arrival batch']['value'] = 1; request['values']['Arrival batch']['value'] = 2
    first = reduce([confirm], {**ctx, 'arrival_batch': 1})
    assert first['processes']['TC-SYN-TRIP']['state'] == 'unseen'
    final = reduce([request], {**ctx, 'arrival_batch': 2}, first)
    assert final['processes']['TC-SYN-TRIP']['state'] == 'confirmed'
    request['values']['Arrival batch']['value'] = 1
    confirm['row'] = 1; request['row'] = 999
    assert reduce([confirm, request], ctx)['processes']['TC-SYN-TRIP']['state'] == 'confirmed'


def test_requested_record_fields_and_arrival_cutoff_are_validated():
    events, ctx = business()
    for field in ('Initiation activity reference', 'Effective time (UTC)'):
        changed = deepcopy(events[0]); changed['values'][field] = {'value': 'invalid-on-initiation'}
        assert reduce([changed], ctx)['admitted_records'] == {}
    result = reduce([events[1]], {**ctx, 'arrival_batch': 1})
    assert result['admitted_records'] == {}


def test_repeated_action_keeps_one_valid_process_and_creates_hold():
    events, ctx = business(); initial = reduce(events, ctx)
    repeated = deepcopy(events[1]); repeated['values']['Cancellation activity reference']['value'] = 'SYN-SECOND-CONFIRM'
    repeated['values']['Arrival batch']['value'] = 3
    result = reduce([repeated], ctx, initial)
    assert result['processes'] == initial['processes']
    assert any('repeated action' in i['reason'] for i in result['issues'])


def test_integration_never_projects_wrong_supervisor_as_confirmed_or_erases_cash_on_conflict():
    parsed = _parsed_fixture()
    for event in parsed['records']['cancellation_activities']:
        if event['values']['Action']['value'] == 'confirmed': event['values']['Acting employee or supervisor']['value'] = 'FIN-SYN-01'
    first = _integrate(parsed, 1); second = _integrate(parsed, 2, previous=first)
    assert all(c['status'] == 'requested' for c in second['snapshot']['travel_cancellations'])
    bad = deepcopy(parsed['records']['finance_events'][0]); bad['values']['Arrival batch']['value'] = 3
    bad['values']['Amount (EUR)']['value'] = 999
    parsed['records']['finance_events'].append(bad)
    final = _integrate(parsed, 3, previous=second)
    finance_result = final['finance_reconciliations']['C-SYN-01']
    assert finance_result['net_confirmed_cents'] == 1000
    assert 'F-SYN-01-SETTLED' in final['snapshot']['admitted_event_ids']
    assert finance_result['conflicting_events'] and finance_result['balance_cents'] is None


def test_legacy_cash_state_cannot_be_silently_reinterpreted_as_unadmitted_zero():
    with pytest.raises(ValueError, match='verified migration'):
        finance([payment()], previous={'net_confirmed_cents': 1000, 'claim_revision': 1})


def test_local_calendar_clock_uses_zone_without_inventing_a_time_of_day():
    event = payment(); event['values']['Activity time (UTC)']['value'] = '2026-11-14T23:00:00Z'
    assert finance([event])['admitted_events'] == {}  # Nov 15 in Amsterdam; cutoff unknown
    event['values']['Activity time (UTC)']['value'] = '2026-11-14T22:59:59Z'
    assert finance([event])['net_confirmed_cents'] == 1000


def test_unknown_claim_finance_delivery_is_visible_and_never_admitted():
    parsed = _parsed_fixture()
    event = deepcopy(parsed['records']['finance_events'][0])
    event['values']['Claim reference']['value'] = 'SYN-NO-CLAIM'
    event['values']['Activity reference']['value'] = 'SYN-UNMATCHED'
    parsed['records']['finance_events'].append(event)
    first = _integrate(parsed, 1); final = _integrate(parsed, 2, previous=first)
    assert event in final['domain']['unmatched_finance_records']
    assert 'SYN-UNMATCHED' not in final['snapshot']['admitted_event_ids']
    assert any(i['record_id'].startswith('finance-unmatched:') for i in final['snapshot']['issues'])


def test_no_claim_cancellation_validates_authority_without_creating_finance_effect():
    from test_retained_finance import _fixture
    parsed = _fixture()
    events = [r for r in parsed['records']['cancellation_activities'] if r['values']['Cancellation reference']['value'] == 'TC122']
    result = reduce_cancellation_activities(events, trips=parsed['records']['trips'], people=parsed['records']['people'], clock=CLOCK)
    assert result['processes']['TC122']['state'] == 'confirmed'
    assert len(result['admitted_records']) == 2
    assert result['finance_effects'] == [] and result['claim_effects'] == []


def test_deferred_confirmation_resolves_only_its_owned_reference_repair():
    parsed = _parsed_fixture()
    parsed['records']['cancellation_activities'] = [r for r in parsed['records']['cancellation_activities']
        if r['values']['Cancellation reference']['value'] == 'TC-SYN-TRIP']
    for record in parsed['records']['cancellation_activities']:
        record['values']['Arrival batch']['value'] = 2 if record['values']['Action']['value'] == 'requested' else 1
    first = _integrate(parsed, 1)
    issue_ids = [key for key in first['domain']['repair_queue']['items'] if key.startswith('cancellation-evidence:')]
    assert issue_ids
    second = _integrate(parsed, 2, previous=first)
    assert second['snapshot']['travel_cancellations'][0]['status'] == 'confirmed'
    assert all(second['domain']['repair_queue']['items'][key]['status'] == 'resolved' for key in issue_ids)
    assert all(first['domain']['repair_queue']['items'][key]['status'] == 'open' for key in issue_ids)


def test_conflicting_first_acceptance_cannot_supply_request_authority_for_cash():
    parsed = _parsed_fixture()
    # Remove independently supplied request identity; a same-batch conflict
    # cannot replace it with an arbitrary first worksheet row.
    parsed['records']['reimbursement_requests'] = []
    accepted = deepcopy(parsed['records']['finance_events'][0])
    accepted['values']['Activity reference']['value'] = 'SYN-ACCEPT-CONFLICT'
    accepted['values']['Activity type']['value'] = 'accepted'
    accepted['values']['Arrival batch']['value'] = 1
    accepted['values']['Obligation (EUR)'] = {'value': 10}
    accepted['values'].pop('Amount (EUR)')
    conflict = deepcopy(accepted); conflict['values']['Payee ID']['value'] = 'SYN-WRONG-PAYEE'
    parsed['records']['finance_events'] += [accepted, conflict]
    first = _integrate(parsed, 1); second = _integrate(parsed, 2, previous=first)
    assert second['finance_reconciliations']['C-SYN-01']['net_confirmed_cents'] == 0
    assert 'F-SYN-01-SETTLED' in second['finance_reconciliations']['C-SYN-01']['unresolved_event_ids']


def test_invalid_arrival_membership_is_owned_and_not_assumed():
    event = payment(); event['values']['Arrival batch']['value'] = 1.5
    result = finance([event])
    assert result['net_confirmed_cents'] == 0 and result['admitted_events'] == {}
    assert 'SYN-PAY' in result['unresolved_event_ids']


def test_source_request_currency_is_not_replaced_with_an_assumed_eur_binding():
    parsed = _parsed_fixture()
    for request in parsed['records']['reimbursement_requests']:
        request['values']['Currency']['value'] = 'USD'
    first = _integrate(parsed, 1); second = _integrate(parsed, 2, previous=first)
    assert second['finance_reconciliations']['C-SYN-01']['net_confirmed_cents'] == 0
    assert second['finance_reconciliations']['C-SYN-01']['unresolved_event_ids']

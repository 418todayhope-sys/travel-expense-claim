"""Actual C01 evidence plus explicitly SYNTHETIC successful closure tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import pytest

from travel_claim.integration import integrate_arrival_batch
from travel_claim.expenses import load_expense_policy
from travel_claim.outputs import load_repair_queue, write_repair_queue

ROOT = Path(__file__).resolve().parents[1]


def native():
    parsed = json.loads((Path(__file__).parent / 'fixtures/ordinary_claim_c01.json').read_text())
    parsed['expense_policy'] = load_expense_policy(ROOT / 'tests/fixtures/POL-2026.2-browser-copy.txt')
    parsed['event_clock'] = {'date': '2026-11-15', 'timezone': 'Europe/Amsterdam'}  # policy line 3; no instant invented
    return parsed


def row(source, locator, **values):
    return dict(source_id=source, source_sha256=hashlib.sha256(source.encode()).hexdigest(), locator=locator,
                values={key.replace('_', ' '): {'value': value} for key, value in values.items()})


def synthetic():
    # Every changed record is explicitly a synthetic source with its own ID.
    parsed = json.loads(json.dumps(native()).replace('C01', 'SYN-C01'))
    parsed.update(evidence_mode='synthetic-test', case_clock='2026-09-15T12:00:00Z', unresolved_issues=[])
    parsed['event_clock'] = parsed['case_clock']
    records = parsed['records']
    all_rows = [r for rows in records.values() for r in rows] + [r for s in parsed['workbook_sheets'] for r in s['records']]
    for r in all_rows:
        r['source_id'] = 'synthetic-' + r['source_id']
        r['source_sha256'] = hashlib.sha256(r['source_id'].encode()).hexdigest()
    for event in records['finance_events']:
        event['values']['Claim revision'] = {'value': 1}
    for packet in next(s['records'] for s in parsed['workbook_sheets'] if s['name'] == 'Review packets'):
        packet['values']['Policy revision']['value'] = 'POL-SYNTHETIC-ONLY'
    records['workflow_policy_rules'] = [row('synthetic-policy', 'SYNTHETIC policy definition', **{
        'Arrival batch': 1, 'Rule set': 'exact-paid-costs-v1', 'Policy revision': 'POL-SYNTHETIC-ONLY',
        'Eligible categories': ['transport'], 'Uncapped categories': ['transport'],
        'Required claim roles': ['administration', 'budget_owner', 'supervisor'],
        'Receipt required': True, 'Settled merchant proof required': True, 'No self review': True,
        'FX date basis': 'paid-date', 'Domestic permit required': False,
        'Closure rule': 'entitlement-authorization-net-cash-no-blockers',
    })]
    decisions = '\n'.join(r['values']['Decision reference']['value'] for r in records['decisions'])
    records['reimbursement_requests'] = [row('synthetic-request', 'SYNTHETIC recorded request', **{
        'Arrival batch': 1, 'Claim reference': 'SYN-C01', 'Revision': 1, 'Request reference': 'REQ-SYN-C01',
        'Currency': 'EUR', 'Amount (EUR)': 100, 'Payee ID': 'EMP-01', 'Decision references': decisions,
    })]
    records['closure_authorities'] = [row('synthetic-facilitator', 'SYNTHETIC completion conditions', **{
        'Arrival batch': 1, 'Claim reference': 'SYN-C01', 'Revision': 1,
        'Confirmation': 'financial-completion-conditions', 'Authority': 'SYNTHETIC facilitator',
        'Case clock': parsed['case_clock'],
    })]
    all_rows += records['workflow_policy_rules'] + records['reimbursement_requests'] + records['closure_authorities']
    parsed['source_observations'] = [dict(source_id=sid, sha256=hashlib.sha256(sid.encode()).hexdigest(),
        status='read', missing_scope=[]) for sid in sorted({r['source_id'] for r in all_rows})]
    return parsed


def batches(parsed):
    prior = None; results = []
    schema = json.loads((ROOT / 'snapshot.schema.json').read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for number in parsed['arrival_batches']:
        prior = integrate_arrival_batch(parsed, arrival_batch=number, run_id='ordinary-test',
            batch_id=f'arrival-{number:03d}', source_binding={'path': 'sources.json', 'sha256': 'a' * 64},
            predecessor={'path': f'batches/arrival-{number-1:03d}.json', 'sha256': 'b' * 64} if prior else None,
            prior_result=prior, source_observations=parsed['source_observations'])
        assert list(validator.iter_errors(prior['snapshot'])) == []
        results.append(prior)
    return results


def workflow(result, claim='SYN-C01'):
    return result['domain']['ordinary_workflows'][claim]


def stages(value):
    return {stage['stage']: stage for stage in value['stages']}


def test_actual_c01_connects_evidence_reviews_and_ledger_but_never_fabricates_closure():
    results = batches(native())
    current = workflow(results[-1], 'C01'); checks = stages(current)
    assert current['claim_id'] == 'C01' and current['revision'] == 1
    assert current['trip_id'] == 'T01' and current['trip_revision'] == 1
    for name in ('claim_trip_link', 'supporting_evidence', 'review_evidence', 'financial_reconciliation'):
        assert checks[name]['status'] == 'PASS'
    for name in ('travel_permission', 'policy_eligibility', 'required_approvals', 'request_obligation', 'financial_closure'):
        assert checks[name]['status'] == 'BLOCKED'
        assert checks[name]['owner'] and checks[name]['next_action']
    assert current['status'] == 'pending' and current['allowed_cents'] is None
    line = current['lines'][0]
    assert line['cost_id'] == 'COST-01' and line['original_cents'] == 10000
    assert line['evidence_status'] == 'PASS' and line['allowed_cents'] is None
    assert any("#tab 'Merchant payments', row 6" in ref for ref in line['source_refs'])
    assert any('#PDF page 1, receipt 1' in ref for ref in line['source_refs'])
    assert len(current['observed_reviews']) == 3
    finance = results[-1]['finance_reconciliations']['C01']
    assert finance['recorded_obligation']['request_id'] == 'REQ-C01'
    assert finance['net_confirmed_cents'] == 10000 and finance['recorded_ledger_balance_cents'] == 0
    assert finance['authorized_obligation'] is None and finance['balance_cents'] is None
    assert results[-1]['snapshot']['requests'] == []


def test_synthetic_connected_path_moves_from_pending_to_supported_closure_and_keeps_history(tmp_path):
    first, second, third, final = batches(synthetic())
    assert workflow(first)['status'] == 'pending'
    assert workflow(first)['allowed_cents'] == 10000 and workflow(first)['balance_cents'] == 10000
    assert stages(workflow(first))['request_obligation']['status'] == 'PASS'
    for result in (second, third, final):
        value = workflow(result)
        assert value['mode'] == 'synthetic-test'
        assert value['status'] == 'closed-reimbursed'
        assert all(stage['status'] == 'PASS' for stage in value['stages'])
        assert value['allowed_cents'] == 10000 and value['balance_cents'] == 0
        assert value['next_owner'] is None
        assert all(stage['source_refs'] for stage in value['stages'])
    assert final['snapshot']['requests'][0]['request_id'] == 'REQ-SYN-C01'
    assert final['snapshot']['requests'][0]['revision'] == 1
    assert final['snapshot']['claims'][0]['paid_cents'] == 10000  # duplicate delivery counts once
    assert len(final['domain']['ordinary_workflow_history']) == 4
    item = final['domain']['repair_queue']['items']['ordinary:SYN-C01:r1:financial_closure']
    assert item['status'] == 'resolved' and item['response_id'] is None
    assert item['request_draft']['sent'] is False
    assert item['history'][-1]['event'] == 'evidence-revalidated'
    path = tmp_path / 'queue.json'
    write_repair_queue(first['domain']['repair_queue'], path)
    write_repair_queue(final['domain']['repair_queue'], path)
    assert load_repair_queue(path)['items'][item['item_id']]['status'] == 'resolved'


@pytest.mark.parametrize('missing', ['receipt', 'settled-proof', 'policy', 'policy-source', 'review',
                                  'request', 'request-amount', 'revision', 'closure-authority', 'clock'])
def test_synthetic_path_cannot_close_when_a_required_condition_is_missing(missing):
    parsed = synthetic(); records = parsed['records']
    if missing == 'receipt': records['receipts'] = []
    elif missing == 'settled-proof':
        next(s for s in parsed['workbook_sheets'] if s['name'] == 'Merchant payments')['records'][0]['values']['Payment status']['value'] = 'pending'
    elif missing == 'policy': records['workflow_policy_rules'] = []
    elif missing == 'policy-source': records['workflow_policy_rules'][0]['source_sha256'] = '0' * 64
    elif missing == 'review': records['decisions'][0]['values']['Outcome']['value'] = 'return'
    elif missing == 'request': records['reimbursement_requests'] = []
    elif missing == 'request-amount': records['reimbursement_requests'][0]['values']['Amount (EUR)']['value'] = 80
    elif missing == 'revision': records['finance_events'][0]['values']['Claim revision']['value'] = 2
    elif missing == 'closure-authority': records['closure_authorities'] = []
    else: parsed['case_clock'] = None
    result = batches(parsed)[-1]
    assert workflow(result)['status'] == 'pending'
    assert any(stage['status'] != 'PASS' for stage in workflow(result)['stages'])
    assert any(item['status'] == 'open' for item in result['domain']['repair_queue']['items'].values())


def test_correction_reopens_path_and_preserves_earlier_closure_cash_and_decisions():
    parsed = synthetic()
    corrected = deepcopy(parsed['records']['claim_revisions'][0])
    for field in corrected['fields']:
        if field['label'] == 'Revision': field['value'] = '2'
        if field['label'] == 'Arrival batch': field['value'] = '3'
    corrected['locator'] = 'SYNTHETIC correction page'
    corrected['text'] = corrected['text'].replace('Revision: 1', 'Revision: 2')
    parsed['records']['claim_revisions'].append(corrected)
    first, second, third, final = batches(parsed)
    assert workflow(second)['status'] == 'closed-reimbursed'
    assert workflow(third)['revision'] == 2 and workflow(third)['status'] == 'pending'
    assert stages(workflow(third))['supporting_evidence']['status'] == 'PASS'
    assert stages(workflow(third))['required_approvals']['status'] == 'BLOCKED'
    assert stages(workflow(third))['request_obligation']['status'] == 'BLOCKED'
    assert final['snapshot']['claims'][0]['paid_cents'] == 10000
    assert final['snapshot']['claims'][0]['balance_cents'] is None
    assert len(final['decision_history']) == 3
    assert all(d['structural_match'] == 'revision_match_historical' for d in final['decision_history'])
    queue = final['domain']['repair_queue']['items']
    assert queue['correction:SYN-C01:r2:expense-evidence']['status'] == 'resolved'
    assert queue['correction:SYN-C01:r2:approvals']['status'] == 'open'
    assert workflow(second)['revision'] == 1  # previous result never mutated


def test_unrelated_cancellation_does_not_block_independent_claim_closure():
    parsed = synthetic()
    native_cancellations = json.loads((Path(__file__).parent / 'fixtures/retained_finance_records.json').read_text())['records']['cancellation_activities']
    parsed['records']['cancellation_activities'] = [r for r in native_cancellations if r['values']['Cancellation reference']['value'] == 'TC122']
    from test_retained_finance import _fixture
    parsed['records']['trips'] += [r for r in _fixture()['records']['trips'] if r['values']['Trip reference']['value'] == 'T122']
    final = batches(parsed)[-1]
    assert workflow(final)['status'] == 'closed-reimbursed'
    cancellation = final['snapshot']['travel_cancellations'][0]
    assert cancellation['cancellation_id'] == 'TC122' and cancellation['affected_claim_ids'] == []
    assert cancellation['financial_status'] == 'unresolved'


def test_current_review_packet_must_match_current_trip_facts():
    parsed = synthetic()
    packet = next(s for s in parsed['workbook_sheets'] if s['name'] == 'Review packets')['records'][0]
    packet['values']['Business purpose']['value'] = 'SYNTHETIC stale business purpose'
    value = workflow(batches(parsed)[-1])
    assert stages(value)['review_evidence']['status'] == 'BLOCKED'
    assert value['status'] == 'pending'


def test_pending_transfer_is_not_ignored_just_because_net_cash_already_balances():
    parsed = synthetic()
    pending = deepcopy(parsed['records']['finance_events'][1])
    pending['values']['Activity reference']['value'] = 'SYNTHETIC-PENDING-TRANSFER'
    pending['values']['Activity type']['value'] = 'mystery-pending'
    pending['values']['Arrival batch']['value'] = 3
    parsed['records']['finance_events'].append(pending)
    result = batches(parsed)[-1]
    assert workflow(result)['status'] == 'pending'
    assert 'SYNTHETIC-PENDING-TRANSFER' in result['finance_reconciliations']['SYN-C01']['unresolved_event_ids']


def test_conflicting_duplicate_review_id_cannot_supply_an_approval():
    parsed = synthetic()
    conflict = deepcopy(parsed['records']['decisions'][0])
    conflict['values']['Outcome']['value'] = 'return'
    parsed['records']['decisions'].append(conflict)
    assert stages(workflow(batches(parsed)[-1]))['required_approvals']['status'] == 'BLOCKED'


def test_synthetic_source_defined_cap_changes_entitlement_without_changing_merchant_cost():
    parsed = synthetic()
    policy = parsed['records']['workflow_policy_rules'][0]['values']
    policy['Eligible categories']['value'] = ['lodging']
    policy['Uncapped categories']['value'] = []
    parsed['records']['receipts'][0]['fields'] = [dict(f, value='lodging') if f['label'] == 'Category' else f for f in parsed['records']['receipts'][0]['fields']]
    cap = row('synthetic-travel-registers-workbook', 'SYNTHETIC cap row', **{
        'Cap reference': 'SYN-CAP', 'Destination': 'NL', 'Category': 'lodging', 'Currency': 'EUR',
        'Effective from': '2026-01-01', 'Effective to': '2026-12-31', 'Amount per unit': 40,
    })
    parsed['workbook_sheets'].append({'name': 'Caps', 'records': [cap]})
    parsed['records']['reimbursement_requests'][0]['values']['Amount (EUR)']['value'] = 40
    for event in parsed['records']['finance_events']:
        for field in ('Amount (EUR)', 'Obligation (EUR)'):
            if field in event['values']: event['values'][field]['value'] = 40
    value = workflow(batches(parsed)[-1])
    assert value['lines'][0]['original_cents'] == 10000
    assert value['allowed_cents'] == 4000 and value['balance_cents'] == 0
    assert value['status'] == 'closed-reimbursed'
    assert any('SYNTHETIC cap row' in ref for ref in value['lines'][0]['source_refs'])


def test_source_defined_director_threshold_does_not_invent_missing_director_approval():
    parsed = synthetic()
    parsed['records']['workflow_policy_rules'][0]['values']['Director threshold cents'] = {'value': 5000}
    value = workflow(batches(parsed)[-1])
    assert stages(value)['required_approvals']['status'] == 'BLOCKED'
    assert value['status'] == 'pending'
    assert all('director' not in d['roles'] for d in value['observed_reviews'])


def test_failed_transfer_requires_a_supported_resolution_even_when_other_cash_balances():
    parsed = synthetic()
    failed = deepcopy(parsed['records']['finance_events'][1])
    failed['values']['Activity reference']['value'] = 'SYNTHETIC-FAILED'
    failed['values']['Activity type']['value'] = 'failed'
    failed['values']['Arrival batch']['value'] = 3
    failed['values'].pop('Amount (EUR)', None)
    parsed['records']['finance_events'].append(failed)
    result = batches(parsed)[-1]
    assert result['finance_reconciliations']['SYN-C01']['balance_cents'] == 0
    assert workflow(result)['status'] == 'pending'
    assert stages(workflow(result))['financial_closure']['status'] == 'BLOCKED'


def test_conflicting_current_claim_revision_blocks_even_if_last_record_looks_complete():
    parsed = synthetic()
    duplicate = deepcopy(parsed['records']['claim_revisions'][0])
    duplicate['locator'] = 'SYNTHETIC conflicting duplicate revision'
    duplicate['text'] += '\nSYNTHETIC conflicting evidence'
    parsed['records']['claim_revisions'].append(duplicate)
    value = workflow(batches(parsed)[-1])
    assert stages(value)['claim_trip_link']['status'] == 'BLOCKED'
    assert value['status'] == 'pending'


def test_finance_or_workbook_source_cannot_be_misrepresented_as_a_policy_definition():
    parsed = synthetic()
    policy = parsed['records']['workflow_policy_rules'][0]
    policy['source_id'] = 'synthetic-travel-registers-workbook'
    policy['source_sha256'] = hashlib.sha256(policy['source_id'].encode()).hexdigest()
    assert stages(workflow(batches(parsed)[-1]))['policy_eligibility']['status'] == 'BLOCKED'


def test_affected_cancellation_holds_eligibility_without_erasing_calculation_or_cash():
    parsed = synthetic()
    native_rows = json.loads((Path(__file__).parent / 'fixtures/retained_finance_records.json').read_text())['records']['cancellation_activities']
    for source in native_rows:
        if source['values']['Cancellation reference']['value'] != 'TC018': continue
        record = deepcopy(source)
        record['source_id'] = 'synthetic-travel-registers-workbook'
        record['source_sha256'] = hashlib.sha256(record['source_id'].encode()).hexdigest()
        record['locator'] = 'SYNTHETIC affected cancellation ' + record['locator']
        record['values']['Trip reference']['value'] = 'T01'
        parsed['records']['cancellation_activities'].append(record)
    final = batches(parsed)[-1]
    value = workflow(final)
    assert stages(value)['travel_permission']['status'] == 'PASS'
    assert value['allowed_cents'] is None
    assert value['lines'][0]['calculated_cents'] == 10000
    assert any(f['issue'] == 'travel_cancellation' and f['status'] == 'unresolved' for f in value['lines'][0]['eligibility_findings'])
    assert final['snapshot']['claims'][0]['paid_cents'] == 10000
    assert value['status'] == 'pending'
    assert stages(value)['financial_closure']['status'] == 'BLOCKED'
    assert final['snapshot']['travel_cancellations'][0]['financial_status'] == 'unresolved'

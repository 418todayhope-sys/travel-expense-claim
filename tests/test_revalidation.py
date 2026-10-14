"""Correction execution and independent cancellation regression evidence."""
from copy import deepcopy
import json

import pytest

from test_ordinary import synthetic, batches, workflow, stages
from test_retained_finance import _fixture, _batches
from travel_claim.revalidation import correction_changes, verification_document
from travel_claim.workflow import reduce_cancellation_activities


def corrected(parsed, *, receipt=None, amount=None):
    record = deepcopy(parsed['records']['claim_revisions'][0])
    for field in record['fields']:
        if field['label'] == 'Revision': field['value'] = '2'
        if field['label'] == 'Arrival batch': field['value'] = '3'
    record['locator'] = 'SYNTHETIC Step157 correction'
    if receipt: record['text'] = record['text'].replace('R-COST-01', receipt)
    if amount: record['text'] = record['text'].replace('100.00', amount)
    parsed['records']['claim_revisions'].append(record)
    return record


@pytest.mark.parametrize('change', ['unchanged', 'receipt', 'amount'])
def test_executed_rechecks_reject_stale_approvals_and_requests_and_preserve_cash(change):
    parsed = synthetic()
    record = corrected(parsed, receipt='SYN-MISSING-RECEIPT' if change == 'receipt' else None,
                       amount='120.00' if change == 'amount' else None)
    before, paid, revised, final = batches(parsed)
    correction = final['domain']['material_corrections'][0]
    assert correction['before_workflow']['status'] == 'closed-reimbursed'
    assert correction['before_finance']['net_confirmed_cents'] == 10000
    assert len(correction['executed_rechecks']) == 2
    checks = {s['stage']: s for s in correction['executed_rechecks'][0]['checks']}
    assert checks['required_approvals']['status'] == 'BLOCKED'
    assert checks['request_obligation']['status'] == 'BLOCKED'
    assert checks['supporting_evidence']['status'] == ('PASS' if change == 'unchanged' else 'BLOCKED')
    assert final['finance_reconciliations']['SYN-C01']['net_confirmed_cents'] == 10000
    assert final['snapshot']['claims'][0]['balance_cents'] is None
    assert workflow(paid)['status'] == 'closed-reimbursed'
    changes = correction_changes(parsed['records']['claim_revisions'][0], record)
    assert changes['expense_lines'][0]['changed'] == (change != 'unchanged')
    assert all(c['source_refs'] for c in checks.values())


def test_retained_correction_moves_trip_but_keeps_historical_cancellation_and_non_cash_event():
    results = _batches(_fixture()); final = results[-1]
    c18 = next(c for c in final['domain']['material_corrections'] if c['claim_id'] == 'C18')
    assert c18['changed_dependencies']['fields']['Trip reference'] == {'before': 'T18', 'after': 'T18B'}
    detail = final['domain']['cancellation_evidence']['TC018']
    assert detail['current_claim_ids'] == []
    cancellation = next(c for c in final['snapshot']['travel_cancellations'] if c['cancellation_id'] == 'TC018')
    assert cancellation['affected_claim_ids'] == ['C18']
    assert cancellation['original_request_ids'] == ['REQ-C18']
    finance = final['finance_reconciliations']['C18']
    assert finance['net_confirmed_cents'] == 10000
    assert any(e['event_id'] == 'F-C18-2' and e['classification'] == 'finance_cancelled' for e in finance['event_history'])
    assert final['finance_reconciliations']['C01']['net_confirmed_cents'] == 10000
    assert not any(c['claim_id'] == 'C01' for c in final['domain']['material_corrections'])


def test_no_claim_cancellation_and_duplicate_confirmation_keep_independent_history():
    final = _batches(_fixture())[-1]
    cancel = next(c for c in final['snapshot']['travel_cancellations'] if c['cancellation_id'] == 'TC122')
    assert cancel['status'] == 'confirmed' and cancel['affected_claim_ids'] == []
    assert cancel['original_request_ids'] == [] and cancel['financial_status'] == 'unresolved'
    assert cancel['admitted_cancellation_event_ids'] == ['TC122-requested', 'TC122-confirmed']
    history = final['domain']['cancellation_evidence']['TC122']['history']
    assert [h['arrival_batch'] for h in history] == [1, 2]
    assert history[0]['actor'] == 'EMP-01'
    assert "row 7" in cancel['source_refs'][1]  # first delivery, not batch-4 redelivery


@pytest.mark.parametrize('fault', ['orphan', 'missing-effective', 'bad-time', 'no-claim-permit'])
def test_partial_and_independent_permit_cancellation(fault):
    parsed = _fixture()
    rows = [r for r in parsed['records']['cancellation_activities']
            if r['values']['Cancellation reference']['value'] == 'TC121']
    parsed['records']['cancellation_activities'] = rows
    if fault == 'orphan': parsed['records']['cancellation_activities'] = rows[1:]
    elif fault == 'missing-effective': rows[1]['values'].pop('Effective time (UTC)', None)
    elif fault == 'bad-time': rows[1]['values']['Activity time (UTC)']['value'] = '2026-09-01T00:00:00'
    else:
        parsed['records']['claim_revisions'] = []
        parsed['records']['finance_events'] = []
    final = _batches(parsed)[-1]
    process = final['domain']['cancellation_state']['processes']['TC121']
    if fault == 'no-claim-permit':
        assert process['state'] == 'confirmed'
        cancel = final['snapshot']['travel_cancellations'][0]
        assert cancel['target_type'] == 'permit' and cancel['affected_claim_ids'] == []
    else:
        assert process['state'] != 'confirmed'
        assert any(k.startswith('cancellation-evidence:') for k in final['domain']['repair_queue']['items'])


def test_verification_is_derived_from_executed_checks_and_labeled_offline():
    parsed = synthetic(); corrected(parsed)
    final = batches(parsed)[-1]
    data, summary = verification_document(final['domain'], final['snapshot']['travel_cancellations'], run_id='test')
    assert data['fresh_native_reads_performed'] is False
    assert 'OFFLINE REPLAY' in summary and 'required_approvals | BLOCKED' in summary
    assert 'SYNTHETIC Step157 correction' in summary
    assert data['corrections'][0]['executed_rechecks']


def test_retained_dispositions_are_exact_revision_bound_observations_not_closure():
    final = _batches(_fixture())[-1]
    for cancellation_id, claim, revision, amount, page in (
            ('TC121', 'C121', 2, '20.00', 'PDF page 6'),
            ('TC019', 'C19', 3, '80.00', 'PDF page 7')):
        detail = final['domain']['cancellation_evidence'][cancellation_id]
        disposition, = detail['dispositions']
        assert (disposition['claim_id'], disposition['revision'], disposition['allowed_original_amount']) == (claim, revision, amount)
        assert disposition['source_ref'].endswith(page)
        assert final['domain']['ordinary_workflows'][claim]['status'] == 'pending'
        item = final['domain']['repair_queue']['items'][f'cancellation-financial:{cancellation_id}']
        assert item['status'] == 'open'
        assert 'disposition recorded' in item['missing_or_return_reason']
    assert final['finance_reconciliations']['C19']['net_confirmed_cents'] == 8000
    assert final['finance_reconciliations']['C121']['net_confirmed_cents'] == 2000

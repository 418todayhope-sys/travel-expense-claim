"""Regression examples transcribed verbatim from the retained native workbook."""

from copy import deepcopy
import json
from pathlib import Path

from travel_claim.finance import reconcile_finance_events
from travel_claim.integration import integrate_arrival_batch

FIXTURE = Path(__file__).parent / "fixtures/retained_finance_records.json"


def _fixture():
    return json.loads(FIXTURE.read_text())


def _batches(parsed):
    prior = None
    results = []
    for batch in parsed['arrival_batches']:
        prior = integrate_arrival_batch(
            parsed, arrival_batch=batch, run_id='retained-regression', batch_id=f'arrival-{batch:03d}',
            source_binding={'path': 'sources.json', 'sha256': 'a' * 64},
            predecessor={'path': f'batches/arrival-{batch-1:03d}.json', 'sha256': 'b' * 64} if prior else None,
            prior_result=prior,
        )
        results.append(prior)
    return results


def test_native_obligation_fields_and_ledger_balances_do_not_become_entitlement():
    parsed = _fixture()
    assert 'Claim revision' not in parsed['provenance']['finance_headers']
    results = _batches(parsed)
    final = results[-1]
    c1 = final['finance_reconciliations']['C01']
    obligation = c1['recorded_obligation']
    assert obligation['event_id'] == 'F-C01-accepted'
    assert obligation['request_id'] == 'REQ-C01'
    assert obligation['finance_officer'] == 'FIN-01'
    assert obligation['payee_id'] == 'EMP-01'
    assert obligation['amount_cents'] == 10000
    assert obligation['claim_revision'] is None
    assert obligation['arrival_revision_context'] == 1
    assert obligation['revision_link_status'] == 'arrival_context_only'
    assert obligation['first_arrival_batch'] == 1
    assert obligation['source_refs'] == [
        'travel-registers-workbook@' + parsed['provenance']['workbook_sha256'] + "#tab 'Finance activity', row 33"
    ]
    assert obligation['claim_source_refs'][0]['locator'] == 'PDF page 1'
    assert c1['net_confirmed_cents'] == 10000  # delivered twice, counted once
    assert c1['duplicate_events'][0]['delivery_batches'] == [2, 4]
    assert c1['recorded_ledger_balance_cents'] == 0
    assert c1['authorized_obligation'] is None
    assert c1['balance_cents'] is None
    assert c1['closure_authority_confirmed'] is False
    projected = next(c for c in final['snapshot']['claims'] if c['claim_id'] == 'C01')
    assert projected['finance_evidence']['recorded_ledger_balance_cents'] == 0
    assert projected['allowed_cents'] is None and projected['status'] == 'pending'


def test_native_corrections_keep_ledger_history_and_revalidate_authority_only_where_affected():
    results = _batches(_fixture())
    first, _, third, final = results
    initial = deepcopy(first)
    c19 = final['finance_reconciliations']['C19']
    assert [(r['event_id'], r['amount_cents'], r['arrival_revision_context']) for r in c19['recorded_obligation_history']] == [
        ('F-C19-accepted', 10000, 1), ('F-C19-2', 8000, 2), ('F-C19-4', 8000, 3),
    ]
    assert c19['confirmed_payment_cents'] == 10000
    assert c19['confirmed_refund_cents'] == 2000
    assert c19['recorded_ledger_balance_cents'] == 0
    assert c19['recorded_obligation']['claim_revision'] is None
    assert c19['invalidated_previous_reconciliation']['claim_revision'] == 2
    assert final['finance_reconciliations']['C09']['recorded_obligation']['arrival_revision_context'] == 2
    assert final['finance_reconciliations']['C12']['recorded_obligation']['amount_cents'] == 7000
    assert final['finance_reconciliations']['C01']['recorded_obligation'] == first['finance_reconciliations']['C01']['recorded_obligation']
    # C18 correction has no newly bound accepted amount. Retain r1 context;
    # neither cancellation nor a fresh payment silently reauthorizes revision 2.
    c18 = final['finance_reconciliations']['C18']
    assert c18['claim_revision'] == 2
    assert c18['recorded_obligation']['arrival_revision_context'] == 1
    assert c18['authorized_obligation'] is None
    assert c18['confirmed_payment_cents'] == 10000
    item = final['domain']['repair_queue']['items']['finance:finance-obligation-missing:C09:1']
    # Historic question remains historic; r2 has its own current authorization question.
    assert item['revision'] == 1
    current = final['domain']['repair_queue']['items']['finance:finance-obligation-missing:C09:2']
    assert current['source_refs']
    assert 'recorded Finance obligation exists' in current['missing_or_return_reason']
    assert current['status'] == 'open'
    assert first == initial


def test_native_refund_and_finance_cancellation_are_independent_of_business_cancellations():
    final = _batches(_fixture())[-1]
    cancellations = {c['cancellation_id']: c for c in final['snapshot']['travel_cancellations']}
    assert cancellations['TC122']['affected_claim_ids'] == []
    assert cancellations['TC122']['target_type'] == 'trip'
    assert cancellations['TC121']['target_type'] == 'permit'
    assert all(c['financial_status'] == 'unresolved' for c in cancellations.values())
    c18 = final['finance_reconciliations']['C18']
    assert c18['recorded_obligation']['amount_cents'] == 10000
    assert c18['confirmed_refund_cents'] == 0  # cancelled transfer is not a refund
    c20 = final['finance_reconciliations']['C20']
    assert c20['recorded_obligation']['amount_cents'] == 10000
    assert c20['confirmed_refund_cents'] == 1000
    assert c20['recorded_ledger_balance_cents'] == 0


def test_duplicate_refund_and_accepted_redelivery_keep_identity_and_original_revision_context():
    parsed = _fixture()
    accepted = deepcopy(next(r for r in parsed['records']['finance_events'] if r['values']['Activity reference']['value'] == 'F-C18-accepted'))
    accepted['row'] = 998
    accepted['locator'] = "tab 'Finance activity', row 998 (synthetic redelivery)"
    accepted['values']['Arrival batch']['value'] = 4
    refund = deepcopy(next(r for r in parsed['records']['finance_events'] if r['values']['Activity reference']['value'] == 'F-C20-2'))
    refund['row'] = 999
    refund['locator'] = "tab 'Finance activity', row 999 (synthetic redelivery)"
    refund['values']['Arrival batch']['value'] = 4
    parsed['records']['finance_events'].extend([accepted, refund])
    final = _batches(parsed)[-1]
    c18 = final['finance_reconciliations']['C18']
    assert len(c18['recorded_obligation_history']) == 1
    assert c18['recorded_obligation']['delivery_batches'] == [1, 4]
    assert c18['recorded_obligation']['arrival_revision_context'] == 1
    assert len(c18['recorded_obligation']['source_refs']) == 2
    assert final['finance_reconciliations']['C20']['confirmed_refund_cents'] == 1000


def _accepted_and_revision():
    parsed = _fixture()
    result = _batches(parsed)[0]
    event = deepcopy(next(r for r in parsed['records']['finance_events'] if r['values']['Activity reference']['value'] == 'F-C01-accepted'))
    return event, result['revision_history']['claim']['C01']['revisions']


def test_explicit_revision_link_is_distinct_from_arrival_context_and_does_not_approve():
    event, revisions = _accepted_and_revision()
    event['values']['Claim revision'] = {'value': 1}  # synthetic explicit field
    result = reconcile_finance_events([event], claim_id='C01', current_revision=1, revision_history=revisions)
    assert result['recorded_obligation']['claim_revision'] == 1
    assert result['recorded_obligation']['revision_link_status'] == 'explicit_current'
    assert result['authorized_obligation'] is None
    assert result['balance_cents'] is None
    assert result['recorded_ledger_balance_cents'] == 10000


def test_missing_amount_and_conflicting_obligation_events_do_not_produce_known_ledger_balance():
    event, revisions = _accepted_and_revision()
    missing = deepcopy(event)
    missing['values'].pop('Obligation (EUR)')
    result = reconcile_finance_events([missing], claim_id='C01', current_revision=1, revision_history=revisions)
    assert result['recorded_obligation'] is None
    assert result['recorded_ledger_balance_cents'] is None
    conflict = deepcopy(event)
    conflict['values']['Obligation (EUR)']['value'] = 999
    result = reconcile_finance_events([event, conflict], claim_id='C01', current_revision=1, revision_history=revisions)
    assert result['recorded_obligation'] is None
    assert result['net_confirmed_cents'] == 0
    assert result['conflicting_events'][0]['event_id'] == 'F-C01-accepted'


def test_unknown_reversal_semantics_are_unresolved_and_never_turned_into_cash():
    event, revisions = _accepted_and_revision()
    reversal = deepcopy(event)
    reversal['values']['Activity reference']['value'] = 'SYNTHETIC-REVERSAL'
    reversal['values']['Activity type']['value'] = 'reversal'
    reversal['values']['Amount (EUR)'] = {'value': 100}
    result = reconcile_finance_events([event, reversal], claim_id='C01', current_revision=1, revision_history=revisions)
    assert result['net_confirmed_cents'] == 0
    assert result['recorded_ledger_balance_cents'] is None
    assert result['unresolved_event_ids'] == ['SYNTHETIC-REVERSAL']


def test_cash_request_mismatch_keeps_ledger_difference_unresolved_with_owned_repair():
    parsed = _fixture()
    for row in parsed['records']['finance_events']:
        if row['values']['Activity reference']['value'] == 'F-C01-1':
            row['values']['Request reference']['value'] = 'SYNTHETIC-WRONG-REQUEST'
    final = _batches(parsed)[-1]['finance_reconciliations']['C01']
    assert final['net_confirmed_cents'] == 10000  # still an observed claim payment
    assert final['recorded_ledger_balance_cents'] is None
    assert 'finance-recorded-cash-link:C01:1' in {i['record_id'] for i in final['repair_issues']}


def test_queue_updates_missing_evidence_question_without_erasing_its_history():
    parsed = _fixture()
    # Synthetic delayed delivery of an unchanged native amount tests a later
    # evidence arrival for the same revision, without inventing authority.
    for row in parsed['records']['finance_events']:
        if row['values']['Activity reference']['value'] == 'F-C01-accepted':
            row['values']['Arrival batch']['value'] = 2
    results = _batches(parsed)
    first, second, _, final = results
    item_id = 'finance:finance-obligation-missing:C01:1'
    item = first['domain']['repair_queue']['items'][item_id]
    assert item['source_refs'] == []
    updated = second['domain']['repair_queue']['items'][item_id]
    assert updated['source_refs']
    assert updated['status'] == 'open'  # recorded commitment is not approval
    assert updated['history'][0]['previous']['source_refs'] == []
    assert updated['history'][0]['changes']['source_refs'] == updated['source_refs']
    assert updated['request_draft'] == {'status': 'draft', 'sent': False}
    assert first['domain']['repair_queue']['items'][item_id] == item
    assert final['finance_reconciliations']['C19']['financial_revalidation_history'][0]['claim_revision'] == 1
    assert final['finance_reconciliations']['C19']['financial_revalidation_history'][1]['claim_revision'] == 2


def test_finance_report_separates_observed_ledger_difference_from_authority(tmp_path):
    from travel_claim.offline_replay import _report

    parsed = _fixture()
    results = _batches(parsed)
    run = tmp_path / 'report-fixture'
    batches = run / 'batches'
    batches.mkdir(parents=True)
    (run / 'sources.json').write_text(json.dumps({'files': [
        {'source_id': 'travel-registers-workbook', 'status': 'read'},
        {'source_id': 'policy-pol-2026-2', 'status': 'unavailable'},
    ]}))
    (run / 'parsed-records.json').write_text(json.dumps(parsed))
    snapshots = []
    for result in results:
        path = batches / (result['snapshot']['batch_id'] + '.json')
        path.write_text(json.dumps(result['snapshot']))
        snapshots.append(path)
    report = _report(run_id='retained-regression', parsed=parsed, snapshots=snapshots,
                     latest=results[-1], output_paths={
                         'queue': run / 'repair-queue.json', 'state': run / 'offline-replay-state.json',
                         'claims': run / 'claims.csv', 'drafts': run / 'follow-up-drafts.md',
                     })
    section = report.split('## Recorded Finance obligations and cash', 1)[1].split('## Claim-specific', 1)[0]
    assert 'Claim `C19` current revision 3; request `REQ-C19`' in section
    assert 'recorded obligation **8000 cents**' in section
    assert 'confirmed net cash **8000 cents**' in section
    assert 'recorded ledger difference **0** cents' in section
    assert 'arrival revision context 3; explicit claim revision None' in section
    assert "#tab 'Finance activity', row 25" in section
    assert 'Exact revision authority and closure remain unconfirmed' in section
    assert 'not a payment or approved reimbursement entitlement' in section
    assert 'OFFLINE REPLAY' in report

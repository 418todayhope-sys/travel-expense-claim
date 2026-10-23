"""Scope A increment 5. Verified offline replay, sealed batches, and owned work.

No authority repair or external action is performed. Explicitly selected ordinary
closures require a verified, unique source-backed revision/cost join.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import csv
from io import StringIO
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from acquisition.retain import verify_run
from reconciliation import reconcile as r
from validation import validate as v
from operator_delivery import containment as d

ROOT = v.ROOT
SCHEMA = ROOT / 'snapshot.schema.json'
CSV_FIELDS = ['claim_id', 'revision', 'trip_id', 'status', 'allowed_cents', 'paid_cents', 'balance_cents', 'next_owner', 'reason']


def relative(path):
    path = path.resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def safe_path(root, name):
    path = root / name
    if Path(name).is_absolute() or '..' in Path(name).parts or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe output/binding path: ' + name)
    return path


def reconciliation_summary(result):
    events = result['finance_events']
    admitted = [e for e in events if e['admission_status'] == 'admitted']
    requests = result['requests']
    settled = sum(e['amount_cents'] for e in admitted if e['kind'] == 'settled')
    refunded = sum(e['amount_cents'] for e in admitted if e['kind'] == 'refund')
    total = lambda name: sum(q[name] for q in requests) if all(q[name] is not None for q in requests) else None
    return {'finance_deliveries': len(result['finance_deliveries']), 'distinct_finance_events': len(events),
        'admitted_finance_events': len(admitted), 'admitted_event_type_counts': dict(Counter(e['kind'] for e in admitted)),
        'repeated_finance_deliveries': sum(d['classification'] == 'repeated_delivery' for d in result['finance_deliveries']),
        'unresolved_finance_events': len(events) - len(admitted),
        'accepted_requests': sum(q['acceptance_status'] == 'admitted' for q in requests), 'observed_request_references': len(requests),
        'original_accepted_cents': total('original_accepted_cents'), 'current_accepted_cents': total('accepted_cents'),
        'admitted_settled_cents': settled, 'admitted_refund_cents': refunded, 'admitted_net_cents': settled - refunded,
        'claim_revisions': len(result['claims']), 'current_claims': sum(c['current_at_batch'] for c in result['claims']),
        'expense_occurrences': sum(len(c['expenses']) for c in result['claims']), 'finance_batch_views': len(result['batch_views']),
        'business_cancellation_processes': len(result['travel_cancellations']),
        'normalization_diagnostic_count': len(result['normalization_diagnostics']), 'unresolved_item_count': len(result['unresolved_items'])}


def load_verified(acquisition, normalized, validated, reconciled):
    doc, report, validation = r.load_verified(acquisition, normalized, validated)
    saved = json.loads((reconciled / 'reconciliation.v1.json').read_bytes())
    expected_paths = {(ROOT / b['path']).resolve() for b in validation['input_bindings']}
    expected_paths.update({(validated / 'findings.v1.json').resolve(), ROOT / 'reconciliation/reconcile.py'})
    seen = set()
    for item in saved['input_bindings']:
        path = (ROOT / item['path']).resolve()
        if path in seen or v.digest(path.read_bytes()) != item['sha256']:
            raise ValueError('Reconciliation input binding mismatch/duplicate: ' + item['path'])
        seen.add(path)
    if seen != expected_paths:
        raise ValueError('Reconciliation is not bound to all selected stage inputs')
    fresh = r.evaluate(doc, report, validation, saved['through_batch'])
    if {k: value for k, value in saved.items() if k not in ('input_bindings', 'summary')} != fresh:
        raise ValueError('Reconciliation evidence differs from deterministic replay')
    if saved['summary'] != reconciliation_summary(fresh):
        raise ValueError('Reconciliation summary differs from verified facts')
    return doc, report, validation, saved


def owned_item(scope, subject, revision, code, reason, owner, refs, expense_id=None):
    key = [scope, subject, revision, expense_id, code]
    return {'record_id': 'repair:' + v.digest(v.encoded(key)), 'subject_type': scope, 'subject_id': subject,
            'revision': revision, 'expense_id': expense_id, 'code': code, 'reason': reason,
            'owner': owner or 'Administration', 'resolution_needed': reason,
            'source_refs': sorted(set(refs)), 'state': 'open'}


def actor_for(doc, claim, owner):
    source = next((c for c in doc['claims'] if c['claim_id'] == claim.get('claim_id') and c['revision'] == claim.get('revision')), None)
    person = v.unique([p for p in v.rows(doc, 'People') if source and p['values']['Employee ID'] == source['employee_id']])
    fields = {'Finance': 'Finance officer', 'Administration': 'Administration reviewer',
              'source-data reviewer': 'Administration reviewer', 'Budget owner': 'Budget owner', 'Supervisor': 'Supervisor'}
    return person['values'][fields[owner]] if person and owner in fields else owner


def cancellation_projection(doc, result, previous):
    projected, work = [], []
    prior = {c['cancellation_id']: c for c in previous}
    for process in result['travel_cancellations']:
        ident = process['cancellation_id']
        rows = [row for row in v.rows(doc, 'Travel cancellations') if v.visible(row, result['through_batch']) and row['values']['Cancellation reference'] == ident]
        requests = [row for row in rows if row['values']['Action'] == 'requested']
        # Exact redelivery has one immutable identity. Conflicting initiations
        # cannot establish a process by choosing the first source row.
        signatures = {v.encoded({k: val for k, val in row['values'].items() if k != 'Arrival batch'}) for row in requests}
        request = requests[0] if len(signatures) == 1 else None
        trip = v.unique([t for t in v.rows(doc, 'Trips') if (t['values']['Trip reference'], t['values']['Trip revision']) == (process['trip_id'], process['trip_revision'])])
        person = v.unique([p for p in v.rows(doc, 'People') if trip and p['values']['Employee ID'] == trip['values']['Employee ID']])
        valid_request = False
        if request and trip and person:
            f, tv = request['values'], trip['values']
            when = v.local_day(f['Activity time (UTC)'])
            valid_request = (f['Acting employee or supervisor'] == tv['Employee ID'] and f['Cancelled subject'] in ('trip', 'permit')
                and f['Permit reference'] == tv['Permit reference'] and f['Permit revision'] == tv['Permit revision']
                and (f['Cancelled subject'] != 'permit' or bool(tv['International'] and tv['Permit reference']))
                and f['Initiation activity reference'] is None and f['Effective time (UTC)'] is None
                and bool(f['Business reason']) and when is not None and when <= v.CASE_DATE)
        refs = [row['record_id'] for row in rows]
        if not valid_request and ident not in prior:
            work.append(owned_item('cancellation', ident, process['trip_revision'], 'invalid_cancellation_initiation',
                'No unique valid employee initiation establishes this process; orphan/invalid deliveries retained for supervisor clarification.',
                person['values']['Supervisor'] if person else 'Supervisor', refs))
            continue
        if process['business_state'] == 'confirmed':
            confirmed = next(row for row in rows if row['values']['Action'] == 'confirmed')
            state, confirmed_at = 'confirmed', confirmed['values']['Activity time (UTC)']
            ids = [request['values']['Cancellation activity reference'], confirmed['values']['Cancellation activity reference']]
        elif ident in prior and prior[ident]['status'] == 'confirmed':
            state, confirmed_at = 'confirmed', prior[ident]['confirmed_at']
            ids = prior[ident]['admitted_cancellation_event_ids']
        else:
            state, confirmed_at = 'requested', None
            ids = [request['values']['Cancellation activity reference']]
        if process['business_state'] == 'unresolved':
            work.append(owned_item('cancellation', ident, process['trip_revision'], 'contested_cancellation',
                'Invalid/conflicting confirmation cannot overwrite prior lawful history or establish new authority; inspect all bound deliveries.',
                person['values']['Supervisor'] if person else 'Supervisor', refs))
        if state == 'requested':
            work.append(owned_item('cancellation', ident, process['trip_revision'], 'supervisor_confirmation',
                'Await exact supervisor confirmation; initiation pauses affected work but changes no Finance money.',
                person['values']['Supervisor'] if person else 'Supervisor', refs))
        affected = sorted({c['claim_id'] for c in result['claims'] if (c['trip_id'], c['trip_revision']) == (process['trip_id'], process['trip_revision'])})
        purchase = any(x['trip_id'] == process['trip_id'] for x in doc['receipts']) or any(p['values']['Trip reference'] == process['trip_id'] for p in v.rows(doc, 'Merchant payments'))
        no_effect = (state == 'confirmed' and process['business_state'] == 'confirmed' and trip and
                     trip['values']['First commitment date'] is None and not affected and not purchase and not process['candidate_original_request_ids'])
        financial = 'no-financial-effect' if no_effect else 'unresolved'
        if financial == 'unresolved' and state == 'confirmed':
            work.append(owned_item('cancellation', ident, process['trip_revision'], 'cancellation_financial_consequence',
                'Obtain exact current cost disposition, review context and original-request Finance attribution/resolution where required; business confirmation is not financial closure.',
                person['values']['Finance officer'] if person else 'Finance', refs))
        requested_at = request['values']['Activity time (UTC)'] if request else prior[ident]['requested_at']
        projected.append({'cancellation_id': ident, 'target_type': process['target_type'], 'trip_id': process['trip_id'],
            'trip_revision': process['trip_revision'], 'permit_id': process['permit_id'], 'permit_revision': process['permit_revision'],
            'status': state, 'admitted_cancellation_event_ids': sorted(set(ids)), 'requested_at': requested_at,
            'confirmed_at': confirmed_at, 'effective_at': confirmed_at,
            'affected_claim_ids': affected, 'original_request_ids': process['candidate_original_request_ids'],
            'financial_status': financial, 'next_owner': None if no_effect else person['values']['Supervisor' if state == 'requested' else 'Finance officer'] if person else 'Supervisor/Finance',
            'reason': 'No commitment, claim, purchase or request observed for this exact trip in retained inputs.' if no_effect else 'Business state retained separately from unresolved monetary consequences.',
            'issue_record_ids': [], 'source_refs': sorted(set(refs)), 'request_link_status': 'candidate-only',
            'separate_finance_resolution_requirement': process['separate_finance_resolution_requirement']})
    return projected, work


def active_work(doc, result, cancellations_work):
    work = list(cancellations_work)
    for claim in result['claims']:
        if not claim['current_at_batch']:
            continue
        original_claim = next(c for c in doc['claims'] if (c['claim_id'], c['revision']) == (claim['claim_id'], claim['revision']))
        for f in claim['diagnostics'] + claim['policy_diagnostics']:
            expense = v.unique([e['expense_id'] for e in original_claim['expenses'] if e['record_id'] in f['source_refs']])
            work.append(owned_item('claim', claim['claim_id'], claim['revision'], f['code'], f['reason'],
                actor_for(doc, claim, f['owner']), f['source_refs'], expense))
        for f in claim['normalization_diagnostics']:
            work.append(owned_item('claim', claim['claim_id'], claim['revision'], 'normalization:' + f['record_id'],
                f['reason'], actor_for(doc, claim, f['owner']), [f['record_id']]))
    for request in result['requests']:
        claim_context = {'claim_id': request['claim_id'], 'revision': request['basis_links'].get('candidate_revision')}
        for f in request['diagnostics'] + request['basis_links']['diagnostics']:
            work.append(owned_item('request', request['request_id'], None, f['code'], f['reason'], actor_for(doc, claim_context, 'Finance'), f['source_refs']))
    for event in result['finance_events']:
        for f in event['diagnostics']:
            work.append(owned_item('finance_event', event['event_id'], None, f['code'], f['reason'], 'Finance', f['source_refs']))
    for f in result['validation_global_findings']:
        work.append(owned_item('package', 'policy-inputs', None, f['code'], f['reason'], f['owner'], f['source_refs']))
    work += [owned_item('package', 'snapshot-schema', None, 'unknown_paid_representation',
        'Public schema requires integer paid_cents. It records only a proven revision-attributed subtotal, not complete net. Read paid_cents_complete and known_paid_cents; CSV leaves unknown paid money blank. Facilitator should clarify nullable payment representation.',
        'Facilitator', []), owned_item('package', 'snapshot-schema', None, 'unknown_request_revision',
        'Public requests require a known revision. Unattributed original requests are preserved in request_facts, not projected into requests by guessing a revision.', 'Finance', [])]
    merged = {}
    for item in work:
        if item['record_id'] in merged:
            item['source_refs'] = sorted(set(item['source_refs'] + merged[item['record_id']]['source_refs']))
        merged[item['record_id']] = item
    return merged


def update_queue(previous, active, result, run_id):
    batch = result['through_batch']
    current = {c['claim_id']: c['revision'] for c in result['claims'] if c['current_at_batch']}
    state, changes = deepcopy(previous), []
    for ident, item in sorted(active.items()):
        before = state.get(ident)
        history = deepcopy(before['history']) if before else []
        changed = not before or any(before[k] != item[k] for k in ('state', 'reason', 'owner', 'source_refs'))
        if changed:
            history.append({'batch': batch, 'state': 'open', 'source_refs': item['source_refs'], 'owner': item['owner'], 'reason': item['reason']})
            changes.append({'record_id': ident, 'change': 'opened' if not before else 'reopened_or_updated'})
        state[ident] = dict(item, run_id=run_id, first_seen_batch=before['first_seen_batch'] if before else batch,
                           last_seen_batch=batch, history=history)
    for ident, item in sorted(state.items()):
        if ident in active or item['state'] != 'open':
            continue
        superseded = item['subject_type'] == 'claim' and current.get(item['subject_id'], 0) > (item['revision'] or 0)
        item['state'] = 'superseded' if superseded else 'cleared_by_recheck'
        item['disposition'] = ('Historical revision retained; current revision and original requests have independent repairs.' if superseded else
            'This item is no longer reported by deterministic recheck; this is not approval, payment authority or financial closure.')
        item['history'].append({'batch': batch, 'state': item['state'], 'reason': item['disposition']})
        changes.append({'record_id': ident, 'change': item['state']})
    return state, changes


def project_claim(claim, issues, doc):
    refs = sorted(i['record_id'] for i in issues if i['subject_type'] == 'claim' and i['subject_id'] == claim['claim_id'] and i['revision'] == claim['revision'])
    reason = 'Held: revision/cost payment attribution and current approval evidence are insufficient; request-level money is separate.'
    if claim['payment_readiness'] == 'blocked':
        reason = 'Held: policy/review block or Decision 001 original-request hold; see owned repairs.'
    disposition = claim['business_disposition']
    if disposition['value']:
        reason = ('Business disposition: ' + disposition['value'] + ': ' + disposition['reason']
                  + ' Financial processing held; see owned repairs. Evidence: '
                  + ', '.join(disposition['source_refs']))
    lines = []
    for e in claim['expenses']:
        receipt = v.unique([receipt for receipt in doc['receipts'] if receipt['receipt_id'] == e['receipt_id']])
        personal = bool(receipt and receipt['category'] == 'personal' and e['policy_allowed_cents'] == 0)
        line_status = 'supported' if e['eligibility_status'] == 'supported' else 'excluded' if personal else 'unresolved'
        lines.append({'cost_id': e['expense_id'], 'source_ids': e['source_refs'], 'status': line_status,
            'allowed_cents': e['policy_allowed_cents'] if line_status in ('supported', 'excluded') else None,
            'reason': 'Expense eligibility only; no payment allocation or approval inferred.' if line_status == 'supported' else 'Eligibility unresolved or explicitly zero; inspect bound policy diagnostics.',
            'gross_original': e['gross_original'], 'currency': e['currency'],
            'policy_calculated_cents': e['policy_allowed_cents'], 'accepted_cents': None, 'known_paid_cents': None})
    owner = next((i['owner'] for i in issues if i['record_id'] in refs and i['code'] == 'decision_001_original_request_hold'), None)
    owner = owner or next((i['owner'] for i in issues if i['record_id'] in refs and i['code'] in ('merchant_payment', 'receipt_identity')), None)
    owner = owner or next((i['owner'] for i in issues if i['record_id'] in refs), 'Administration')
    result = {'claim_id': claim['claim_id'], 'revision': claim['revision'], 'trip_id': claim['trip_id'], 'trip_revision': claim['trip_revision'],
        'status': 'held', 'lines': lines, 'business_disposition': deepcopy(disposition),
        'allowed_cents': sum(line['allowed_cents'] for line in lines) if lines and all(line['allowed_cents'] is not None for line in lines) else None,
        'allowed_cents_scope': 'supported expense arithmetic/exclusion only; not reviewed payment authority',
        'paid_cents': 0, 'paid_cents_complete': False, 'paid_cents_semantics': 'proven revision-attributed subtotal only; not a confirmed zero payment',
        'known_paid_cents': None, 'balance_cents': None, 'authorized_allowed_cents': None,
        'decision_ids': sorted(set(claim['selected_current_review_ids'].values())), 'decision_ids_are_authorization': False,
        'next_owner': owner, 'reason': reason, 'issue_record_ids': refs,
        'gross_original_by_currency': claim['gross_original_by_currency'], 'gross_purchase_cents': claim['gross_purchase_cents'],
        'policy_calculated_allowed_cents': claim['policy_allowed_cents'], 'eligibility_status': claim['eligibility_status'],
        'review_evidence_status': claim['approval_status'], 'financial_closure_status': 'unresolved',
        'original_request_ids': claim['related_original_request_ids'], 'source_refs': claim['source_refs'],
        'incremental_policy_candidate_cents': claim['incremental_policy_candidate_cents'],
        'travel_cancellation_scope': claim['travel_cancellation_scope']}
    proof = claim.get('ordinary_closure')
    if proof and not refs and not claim['diagnostics'] and not claim['policy_diagnostics']:
        amount = proof['amount_cents']
        result.update(status='closed-reimbursed', ordinary_closure=deepcopy(proof),
                      allowed_cents=amount, authorized_allowed_cents=amount,
                      allowed_cents_scope='Reviewed entitlement derived from exact current source approvals.',
                      paid_cents=amount, known_paid_cents=amount, paid_cents_complete=True,
                      paid_cents_semantics='Unique unchanged source-backed request/cost attribution; retained evidence only.',
                      balance_cents=0, decision_ids_are_authorization=True, next_owner=None,
                      financial_closure_status='supported_retained_evidence',
                      reason='Closed within retained evidence: current approvals, unique unchanged cost/request basis, accepted obligation and confirmed net settlement agree. Native-policy completeness remains unverified.')
        result['lines'][0].update(accepted_cents=amount, known_paid_cents=amount)
    return result


def snapshot(result, doc, report, run_id, source_binding, predecessor, queue_binding, active, projected_cancellations):
    batch = result['through_batch']
    issues = [active[k] for k in sorted(active)]
    for process in projected_cancellations:
        process['issue_record_ids'] = sorted(i['record_id'] for i in issues if i['subject_type'] == 'cancellation' and i['subject_id'] == process['cancellation_id'])
    current = [project_claim(c, issues, doc) for c in result['claims'] if c['current_at_batch']]
    visible_sources = {ref for c in result['claims'] for ref in c['source_refs']}
    diagnostics = [f for f in report['issues'] if any(f['record_id'] == ref or f['record_id'].startswith(ref + ':') for ref in visible_sources)]
    decisions = [deepcopy(row) for row in v.rows(doc, 'Review ledger') if v.visible(row, batch)]
    result_snapshot = {'schema_version': 'travel-claim-snapshot/2', 'run_id': run_id, 'batch_id': f'{batch:03}',
        'predecessor': predecessor, 'source_binding': source_binding, 'claims': current,
        'requests': [], 'request_projection_complete': False, 'request_facts': result['requests'],
        'travel_cancellations': projected_cancellations, 'admitted_event_ids': sorted(e['event_id'] for e in result['finance_events'] if e['admission_status'] == 'admitted'),
        'issues': issues, 'queue_binding': queue_binding, 'mode': 'offline-retained-replay', 'case_clock': result['case_clock'],
        'claim_revision_history': result['claims'], 'finance_deliveries': result['finance_deliveries'], 'finance_events': result['finance_events'],
        'decision_deliveries': decisions, 'cancellation_deliveries': [deepcopy(row) for row in v.rows(doc, 'Travel cancellations') if v.visible(row, batch)],
        'normalization_diagnostics': diagnostics, 'validation_global_findings': result['validation_global_findings'],
        'source_index': result['source_index'], 'actual_financial_closure_count': sum(c['status'] == 'closed-reimbursed' for c in current),
        'claim_arrival_boundaries': [{'claim_id': c['claim_id'], 'revision': c['revision'], 'arrival_batch': c['arrival_batch']}
                for c in doc['claims'] if c['arrival_batch'] <= batch],
        'summary': {'current_claims': len(current), 'claim_revisions': len(result['claims']),
                    'expense_occurrences': sum(len(c['expenses']) for c in result['claims']),
                    'request_facts': len(result['requests']), 'admitted_finance_events': sum(e['admission_status'] == 'admitted' for e in result['finance_events']),
                    'admitted_settled_cents': sum(q['admitted_settled_cents'] for q in result['requests']),
                    'admitted_refund_cents': sum(q['admitted_refund_cents'] for q in result['requests']),
                    'admitted_net_cents': sum(q['admitted_net_cents'] for q in result['requests']),
                    'open_repairs': len(issues), 'normalization_diagnostics': len(diagnostics)}}
    if result.get('ordinary_claim_ids'):
        result_snapshot['ordinary_claim_ids'] = result['ordinary_claim_ids']
    check_snapshot(result_snapshot)
    return result_snapshot


def check_snapshot(value):
    schema = json.loads(SCHEMA.read_bytes())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    ids = {i['record_id'] for i in value['issues']}
    if len(ids) != len(value['issues']):
        raise ValueError('Duplicate issue identity')
    if len({c['claim_id'] for c in value['claims']}) != len(value['claims']):
        raise ValueError('Duplicate current claim')
    finance = set(value['admitted_event_ids'])
    if len(finance) != len(value['admitted_event_ids']):
        raise ValueError('Duplicate admitted Finance identity')
    event_ids = [e['event_id'] for e in value['finance_events']]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError('Duplicate Finance business event')
    batch = int(value['batch_id'])
    if any(d['values']['Arrival batch'] > batch for d in value['decision_deliveries'] + value['cancellation_deliveries']):
        raise ValueError('Future decision/cancellation consumed')
    if any(e['first_arrival_batch'] > batch or (e['admitted_in_batch'] is not None and e['admitted_in_batch'] > batch) for e in value['finance_events']):
        raise ValueError('Future Finance event consumed')
    current = {}
    for c in value['claim_arrival_boundaries']:
        if c['arrival_batch'] > batch:
            raise ValueError('Future claim revision consumed')
        current[c['claim_id']] = max(c['revision'], current.get(c['claim_id'], 0))
    if {(c['claim_id'], c['revision']) for c in value['claims']} != set(current.items()):
        raise ValueError('Stale/missing current claim revision')
    for c in value['claims']:
        closed = c['status'] == 'closed-reimbursed'
        if not set(c['issue_record_ids']) <= ids or (not closed and (c['status'] != 'held' or c['financial_closure_status'] != 'unresolved')):
            raise ValueError('Unsupported closure/state or dangling claim issues')
        historical = next(h for h in value['claim_revision_history'] if (h['claim_id'], h['revision']) == (c['claim_id'], c['revision']))
        disposition = c['business_disposition']
        if (disposition != historical['business_disposition']
                or (disposition['value'] is not None) != (disposition['evidence_status'] == 'supported')
                or not set(disposition['source_refs']) <= set(value['source_index'])
                or not set(disposition['decision_ids']) <= set(c['decision_ids'])):
            raise ValueError('Unsupported business disposition or dangling evidence')
        if closed:
            proof = c.get('ordinary_closure')
            q = v.unique([q for q in value['request_facts'] if proof and q['request_id'] == proof['request_id']])
            if (not proof or c['claim_id'] not in value.get('ordinary_claim_ids', [])
                    or historical.get('ordinary_closure') != proof or c['issue_record_ids']
                    or c['financial_closure_status'] != 'supported_retained_evidence'
                    or not q or q['basis_links'].get('ordinary_closure') != proof
                    or q['diagnostics'] or q['uncertain_event_ids']
                    or c['review_evidence_status'] != 'supported' or c['eligibility_status'] != 'supported'
                    or not c['decision_ids_are_authorization']
                    or sorted(c['decision_ids']) != proof['decision_ids']
                    or c['allowed_cents'] != proof['amount_cents'] or c['paid_cents'] != proof['amount_cents']
                    or c['authorized_allowed_cents'] != proof['amount_cents']
                    or c['known_paid_cents'] != proof['amount_cents'] or c['paid_cents_complete'] is not True
                    or c['balance_cents'] != 0 or q['accepted_cents'] != proof['amount_cents']
                    or q['net_confirmed_settled_cents'] != proof['amount_cents']
                    or not set(proof['source_refs']) <= set(value['source_index'])
                    or not {proof['accepted_event_id'], proof['settlement_event_id']} <= finance):
                raise ValueError('Unsupported ordinary closure or inconsistent attributed money')
        elif c['paid_cents'] != 0 or c['known_paid_cents'] is not None or c['paid_cents_complete'] is not False or c['balance_cents'] is not None:
            raise ValueError('Unproven revision-attributed payment or balance')
        for ident in c['decision_ids']:
            decision = v.unique([d['values'] for d in value['decision_deliveries'] if d['values']['Decision reference'] == ident])
            if not decision or (decision['Subject type'], decision['Subject reference'], decision['Revision']) != ('claim', c['claim_id'], c['revision']) or decision['Outcome'] not in ('approve', 'return', 'reject'):
                raise ValueError('Stale/wrong-subject decision projected onto current claim')
    for process in value['travel_cancellations']:
        if not set(process['issue_record_ids']) <= ids or finance.intersection(process['admitted_cancellation_event_ids']):
            raise ValueError('Dangling cancellation issues or mixed event namespaces')
    actual_ids = {e['event_id'] for e in value['finance_events'] if e['admission_status'] == 'admitted'}
    if finance != actual_ids:
        raise ValueError('Admission set differs from Finance evidence')
    if value['requests'] or value['request_projection_complete'] is not False:
        raise ValueError('Unproven revision-specific request projection')
    facts = value['request_facts']
    if len({q['request_id'] for q in facts}) != len(facts):
        raise ValueError('Duplicate request facts')
    for q in facts:
        admitted = [e for e in value['finance_events'] if e['request_id'] == q['request_id'] and e['admission_status'] == 'admitted']
        settled = sum(e['amount_cents'] for e in admitted if e['kind'] == 'settled')
        refunded = sum(e['amount_cents'] for e in admitted if e['kind'] == 'refund')
        if (q['admitted_settled_cents'], q['admitted_refund_cents'], q['admitted_net_cents']) != (settled, refunded, settled - refunded):
            raise ValueError('Request money differs from admitted events')
    x = value['summary']
    expected = {'current_claims': len(value['claims']), 'claim_revisions': len(value['claim_revision_history']),
        'expense_occurrences': sum(len(c['expenses']) for c in value['claim_revision_history']),
        'request_facts': len(facts), 'admitted_finance_events': len(finance),
        'admitted_settled_cents': sum(q['admitted_settled_cents'] for q in facts),
        'admitted_refund_cents': sum(q['admitted_refund_cents'] for q in facts),
        'admitted_net_cents': sum(q['admitted_net_cents'] for q in facts), 'open_repairs': len(ids),
        'normalization_diagnostics': len(value['normalization_diagnostics'])}
    if x != expected or value['actual_financial_closure_count'] != sum(c['status'] == 'closed-reimbursed' for c in value['claims']):
        raise ValueError('Snapshot summary/closure count differs from evidence')


def claims_csv(final):
    buffer = StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    for claim in final['claims']:
        row = {k: claim[k] for k in CSV_FIELDS}
        row['paid_cents'] = claim['known_paid_cents']
        writer.writerow(row)
    return buffer.getvalue().encode()


def markdown_report(run_id, snapshots, queue):
    final = snapshots[-1]
    summary = final['summary']
    lines = [f'# Operator handoff — {run_id}', '',
        'Mode: offline retained-source replay. No fresh acquisition, financial closure, external request or submission is asserted.', '',
        (f"Final batch: {final['batch_id']}; {len(final['claims'])} current claims; {final['actual_financial_closure_count']} supported ordinary closure(s) within retained evidence. All other claims remain held."
         if final['actual_financial_closure_count'] else f"Final batch: {final['batch_id']}; {len(final['claims'])} current claims, all held. Actual financial closures: 0."),
        'Supported expense eligibility, supplied review replies, admitted request-level money and actual closure are separate facts.',
        'Business dispositions are retained independently: withdrawal/rejection does not authorize payment, clear repairs, or establish financial closure.',
        ('Selected supported closures have known paid/balance money; all other unknown paid/balance amounts remain blank in CSV. Their snapshot zero is an incomplete subtotal, not proof of zero payment.' if final.get('ordinary_claim_ids') else
         'Unknown paid/balance amounts are blank in claims.csv. Snapshot paid_cents is only the proven attributed subtotal (0), with paid_cents_complete=false and known_paid_cents=null; it is not proof of zero payment.'),
        'Finance has no revision/cost columns: original requests are fully retained in request_facts; schema requests stays empty rather than inventing a required revision.', '',
        '## Retained evidence and replay', '',
        'See [sources.json](sources.json), [original acquisition manifest](acquisition-manifest.original.json) and [sealed manifest](operator-manifest.v1.json).',
        'Native policy remains unavailable. The October 20 browser copy is supplemental, with its provenance preserved; semantic source completeness is unverified.',
        'The four snapshots bind their predecessor and derived replay source manifest. No historical execution times were invented.', '',
        '| Batch | Claims | Finance events | Settled cents | Refund cents | Net cents | Open repairs |', '|---|---:|---:|---:|---:|---:|---:|']
    for s in snapshots:
        x = s['summary']
        lines.append(f"| [{s['batch_id']}](batches/{s['batch_id']}.json) | {x['current_claims']} | {x['admitted_finance_events']} | {x['admitted_settled_cents']} | {x['admitted_refund_cents']} | {x['admitted_net_cents']} | {x['open_repairs']} |")
    lines += ['', f"Final request ledger: {summary['request_facts']} original request facts; admitted settlements {summary['admitted_settled_cents']} cents, linked refunds {summary['admitted_refund_cents']} cents, net {summary['admitted_net_cents']} cents.",
        'These totals are not revision-attributed employee paid totals and do not authorize or close claims.', '',
        '## Claims and owners', '', '| Claim/revision | Eligibility | Review evidence | Gross EUR cents | Policy calculation cents | Owner | Snapshot issues |', '|---|---|---|---:|---:|---|---|']
    for c in final['claims']:
        money = lambda x: '' if x is None else str(x)
        lines.append(f"| {c['claim_id']}/r{c['revision']} | {c['eligibility_status']} | {c['review_evidence_status']} | {money(c['gross_purchase_cents'])} | {money(c['policy_calculated_allowed_cents'])} | {c['next_owner']} | {len(c['issue_record_ids'])} |")
    if final.get('ordinary_claim_ids'):
        lines += ['', '## Explicitly selected ordinary closure checks', '',
                  'This is a retained-evidence conclusion, not an external completeness certificate, a new approval, or an instruction to pay again. Package-wide unknowns remain in the repair queue. Unselected claims retain their existing financial holds.']
        for c in final['claims']:
            if c.get('ordinary_closure'):
                p = c['ordinary_closure']
                lines.append(f"- {c['claim_id']}/r{c['revision']}: {c['status']}; reviewed/accepted/net {p['amount_cents']} cents; balance 0. Request {p['request_id']}; acceptance {p['accepted_event_id']}; settlement {p['settlement_event_id']}. Evidence: {', '.join(p['source_refs'])}.")
    lines += ['', '## Supported business dispositions (financial status remains held)', '']
    for c in final['claims']:
        disposition = c['business_disposition']
        if disposition['value']:
            lines.append(f"- {c['claim_id']}/r{c['revision']}: {disposition['value']} — {disposition['reason']} Evidence: {', '.join(disposition['source_refs'])}.")
    lines += ['', '## Independent cancellations', '', '| Process | Trip/revision | Target | Business state | Financial consequence | Owner |', '|---|---|---|---|---|---|']
    for c in final['travel_cancellations']:
        lines.append(f"| {c['cancellation_id']} | {c['trip_id']}/r{c['trip_revision']} | {c['target_type']} | {c['status']} | {c['financial_status']} | {c['next_owner'] or 'No current action'} |")
    lines += ['', 'No claim row is invented for a cancellation with no claim. Business cancellation changes no Finance money.', '',
        '## Owned repairs and partial updates', '',
        'Use [repair-queue.json](repair-queue.json) for item-level subject/revision, owner, exact evidence/action, source references and history. [repair-queue.csv](repair-queue.csv) contains open items.',
        'A response clears only its matching item after deterministic recheck. Superseded claim reviews remain history; original-request money and holds remain separately active.', '']
    for q in queue:
        changes = Counter(change['change'] for change in q['changes'])
        lines.append(f"- Batch [{q['batch_id']}](queue/{q['batch_id']}.json): {dict(changes)}; {sum(i['state'] == 'open' for i in q['items'])} open repairs.")
    lines += ['', '## Completion boundary and handoff', '',
        'Finance must supply exact request/revision/cost allocation and scoped resolution evidence. Current reviewers must supply verifiable amount/exception context and current decisions. Employees own missing merchant payment proof. The facilitator owns native policy/package-version/schema clarification.',
        'C18 corrections after original acceptance remain subject to Decision 001. Equal request/net amounts, a cancellation status, a refund promise, or an earlier approval never substitutes for current authorization.',
        f"All {len(final['normalization_diagnostics'])} visible normalization diagnostics remain in batch {final['batch_id']}. Policy/approval/Finance repairs are independent; no missing fact is silently waived.",
        'The original assignment is a preserved historical capture. No live source refresh or capture checkpoint was fabricated. This directory is an operator replay/handoff, not a certified-complete submission.', '']
    if 'dependency_summary' in final:
        before, after = final['prior_operator'], final['dependency_summary']
        lines += ['', '## Decision 002: dependency-based containment', '',
            f"Evidence work and financial closure have separate states. See [dependency graph](dependencies/{final['batch_id']}.json) for proven directed edges, unsatisfied roots, deterministic impact paths, executed checks and candidate-only Finance links.",
            f"Current evidence-processing states: {after['current_evidence_states']}. Graph: {after['nodes']} nodes, {after['edges']} edges, {after['hold_roots']} unsatisfied roots, {after['impacted_nodes']} impacted nodes.",
            f"Package requirements: {after['global_requirements']}, separately owned; no blanket inherited_validation_limits claim defect. Before: {before['summary']['open_repairs']} open repairs; active scoped presentation: {summary['open_repairs']}. Earlier register still has {before['open_repairs']} open items, preserved unchanged in prior-repair-queue.original.json. No item in it was cleared by this decision.",
            'The 121 removed blanket claim presentations are reclassified, not resolved. Global policy/package certification remains unresolved, and every existing financial hold remains. Prior artifacts bind historical code, not current code; historical file integrity was checked separately.',
            'Independent processing means executed receipt/payment and policy checks with per-operation holds; it never means approval, dispatch or financial closure. C18/r2 remains held under Decision 001 while T18B evidence checks continue. C08/C114 merchant-proof gaps remain owned and unresolved.',
            'Limitations: global requirement applicability is unresolved; full current-revision rechecks remain conservative. No certified Finance revision/cost attribution or current review basis was supplied. Base source tables have no arrival labels. No prior evidence is overwritten.', '']
    return '\n'.join(lines).encode()


def write_once(root, path, data):
    target = safe_path(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(data)
    return {'path': path, 'sha256': v.digest(data)}


def build(acquisition, normalized, validated, reconciled, output, run_id, through_batch=4, replay_of=None, dependency_containment=False, prior_operator=None):
    acquisition, normalized, validated, reconciled, output = [p.resolve() for p in (acquisition, normalized, validated, reconciled, output)]
    if output.exists():
        raise FileExistsError('Refusing existing operator output: ' + str(output))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', run_id):
        raise ValueError('Use a nonempty filesystem-safe run ID')
    if any(output.is_relative_to(p) for p in (acquisition, normalized, validated, reconciled)):
        raise ValueError('Operator output must be outside retained stage directories')
    replay_binding = None
    if replay_of:
        verify(replay_of.resolve())
        replay_binding = {'path': relative(replay_of / 'operator-manifest.v1.json'), 'sha256': v.digest((replay_of / 'operator-manifest.v1.json').read_bytes())}
    doc, report, validation, recon = load_verified(acquisition, normalized, validated, reconciled)
    if dependency_containment and recon.get('ordinary_claim_ids'):
        raise ValueError('Ordinary closure projection is not enabled for containment/shared-blocker builds')
    if through_batch < 1 or through_batch > recon['through_batch']:
        raise ValueError('Batch horizon exceeds verified reconciliation')
    legacy = None
    if dependency_containment:
        prior_operator = (prior_operator or ROOT / 'artifacts/runs/omega4-attempt002-operator-v1').resolve()
        # Historical outputs bind historical code hashes. Verify their retained
        # bytes, not equality of historical code to today's implementation.
        old = json.loads((prior_operator / 'operator-manifest.v1.json').read_bytes())
        for item in old['files']:
            if v.digest(safe_path(prior_operator, item['path']).read_bytes()) != item['sha256']:
                raise ValueError('Prior output binding mismatch: ' + item['path'])
        legacy = {'manifest': {'path': relative(prior_operator / 'operator-manifest.v1.json'),
                              'sha256': v.digest((prior_operator / 'operator-manifest.v1.json').read_bytes())},
                  'summary': old['summary'], 'open_repairs': sum(i['state'] == 'open' for i in json.loads((prior_operator / 'repair-queue.json').read_bytes())['items']),
                  'meaning': 'Earlier repairs remain open historical obligations; presentation reclassification is not resolution.'}
    original = (acquisition / 'sources.json').read_bytes()
    manifest = json.loads(original)
    replay_sources = deepcopy(manifest)
    replay_sources.update(run_id=run_id, scope='Offline replay of retained inputs; no fresh native access or completeness certification.',
        replay_mode='offline-retained-replay', acquisition_run_id=manifest['run_id'],
        original_manifest={'path': 'acquisition-manifest.original.json', 'sha256': v.digest(original)}, policy_case_clock=validation['case_clock'])
    # Compute all batch states before creating the destination. A verification or
    # replay failure cannot leave a misleading partial operator directory.
    results = [r.evaluate(doc, report, validation, batch) if batch != recon['through_batch'] else recon for batch in range(1, through_batch + 1)]
    output.mkdir(parents=True, exist_ok=False)
    write_once(output, 'acquisition-manifest.original.json', original)
    for path in sorted(acquisition.rglob('*')):
        if path.is_file() and path.name != 'sources.json':
            write_once(output, str(path.relative_to(acquisition)), path.read_bytes())
    source_binding = write_once(output, 'sources.json', v.encoded(replay_sources))
    if legacy:
        write_once(output, 'prior-repair-queue.original.json', (prior_operator / 'repair-queue.json').read_bytes())
        write_once(output, 'prior-operator-manifest.original.json', (prior_operator / 'operator-manifest.v1.json').read_bytes())
    previous, queue_state, snapshots, queues, prior_cancellations = None, {}, [], [], []
    for result in results:
        batch = result['through_batch']
        graph = d.evaluate(doc, report, result) if dependency_containment else None
        if graph:
            result = d.project(result)
        projected, cancellation_work = cancellation_projection(doc, result, prior_cancellations)
        active = active_work(doc, result, cancellation_work)
        queue_state, changes = update_queue(queue_state, active, result, run_id)
        queue = {'schema_version': 'omega4-repair-queue/1', 'run_id': run_id, 'batch_id': f'{batch:03}',
                 'items': [queue_state[k] for k in sorted(queue_state)], 'changes': changes}
        queue_binding = write_once(output, f'queue/{batch:03}.json', v.encoded(queue))
        snap = snapshot(result, doc, report, run_id, source_binding, previous, queue_binding, active, projected)
        if graph:
            snap['dependency_binding'] = write_once(output, f'dependencies/{batch:03}.json', v.encoded(graph))
            snap['dependency_summary'] = graph['summary']
            snap['prior_operator'] = legacy
            for claim in snap['claims']:
                claim['evidence_work'] = next(w for w in graph['claim_work'] if w['current_at_batch'] and (w['claim_id'], w['revision']) == (claim['claim_id'], claim['revision']))
            check_snapshot(snap)
        previous = write_once(output, f'batches/{batch:03}.json', v.encoded(snap))
        snapshots.append(snap); queues.append(queue); prior_cancellations = projected
    write_once(output, 'claims.csv', claims_csv(snapshots[-1]))
    write_once(output, 'repair-queue.json', v.encoded(queues[-1]))
    buffer = StringIO(newline='')
    fields = ['record_id', 'subject_type', 'subject_id', 'revision', 'expense_id', 'owner', 'code', 'reason', 'resolution_needed', 'first_seen_batch', 'last_seen_batch', 'source_refs']
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator='\n'); writer.writeheader()
    for item in queues[-1]['items']:
        if item['state'] == 'open':
            row = {k: item[k] for k in fields}; row['source_refs'] = json.dumps(row['source_refs'])
            writer.writerow(row)
    write_once(output, 'repair-queue.csv', buffer.getvalue().encode())
    write_once(output, 'report.md', markdown_report(run_id, snapshots, queues))
    paths = [reconciled / 'reconciliation.v1.json', ROOT / 'operator_delivery/build.py', ROOT / 'operator_delivery/requirements.txt', ROOT / 'operator_delivery/README.md',
             ROOT / 'skills/travel-expense-claim/SKILL.md', ROOT / 'README.md', ROOT / 'operator_delivery/business-dispositions.md']
    if dependency_containment:
        paths += [ROOT / d.DECISION, ROOT / 'operator_delivery/containment.py']
    bindings = deepcopy(recon['input_bindings']) + [{'path': relative(p), 'sha256': v.digest(p.read_bytes())} for p in paths]
    sealed = {'schema_version': 'omega4-operator-manifest/1', 'run_id': run_id, 'mode': 'offline-retained-replay',
        'through_batch': through_batch, 'acquisition_run_id': manifest['run_id'], 'input_bindings': bindings,
        'replay_of': replay_binding, 'dependency_containment': dependency_containment, 'files': [{'path': str(p.relative_to(output)), 'sha256': v.digest(p.read_bytes())}
                for p in sorted(output.rglob('*')) if p.is_file()], 'final_batch': previous, 'summary': snapshots[-1]['summary']}
    write_once(output, 'operator-manifest.v1.json', v.encoded(sealed))
    verify(output)
    return sealed


def verify(output):
    output = output.resolve()
    sealed = json.loads((output / 'operator-manifest.v1.json').read_bytes())
    files = sealed['files']
    names = [entry['path'] for entry in files]
    if len(set(names)) != len(names) or 'operator-manifest.v1.json' in names:
        raise ValueError('Duplicate bindings or self-hashing manifest')
    actual = {str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()}
    if actual != set(names) | {'operator-manifest.v1.json'}:
        raise ValueError('Missing or unbound operator files')
    hashes = {}
    for item in files:
        path = safe_path(output, item['path'])
        if v.digest(path.read_bytes()) != item['sha256']:
            raise ValueError('Sealed output hash mismatch: ' + item['path'])
        hashes[item['path']] = item['sha256']
    seen_inputs = set()
    for item in sealed['input_bindings']:
        path = (ROOT / item['path']).resolve()
        if path in seen_inputs or v.digest(path.read_bytes()) != item['sha256']:
            raise ValueError('Operator input provenance changed or duplicated: ' + item['path'])
        seen_inputs.add(path)
    verify_run(output)
    sources = json.loads((output / 'sources.json').read_bytes())
    if sources['run_id'] != sealed['run_id'] or v.digest((output / 'acquisition-manifest.original.json').read_bytes()) != sources['original_manifest']['sha256']:
        raise ValueError('Source replay provenance mismatch')
    prior, final, snapshots, queues = None, None, [], []
    for batch in range(1, sealed['through_batch'] + 1):
        name = f'batches/{batch:03}.json'
        snap = json.loads(safe_path(output, name).read_bytes())
        check_snapshot(snap)
        if snap['run_id'] != sealed['run_id'] or snap['batch_id'] != f'{batch:03}' or snap['predecessor'] != prior:
            raise ValueError('Broken snapshot identity/predecessor chain')
        if snap['source_binding'] != {'path': 'sources.json', 'sha256': hashes['sources.json']}:
            raise ValueError('Snapshot source binding mismatch')
        queue_name = f'queue/{batch:03}.json'
        if snap['queue_binding'] != {'path': queue_name, 'sha256': hashes[queue_name]}:
            raise ValueError('Queue binding mismatch')
        queue = json.loads(safe_path(output, queue_name).read_bytes())
        inputs = {Path(i['path']).name: ROOT / i['path'] for i in sealed['input_bindings']}
        doc = json.loads(inputs['records.v1.json'].read_bytes())
        report = json.loads(inputs['parsing-report.v1.json'].read_bytes())
        validated = json.loads(inputs['findings.v1.json'].read_bytes())
        if snap.get('ordinary_claim_ids', []) != validated.get('ordinary_claim_ids', []):
            raise ValueError('Ordinary claim selection differs from bound validation')
        if snap.get('ordinary_claim_ids'):
            replayed = r.evaluate(doc, report, validated, batch)
            expected_claims = {(c['claim_id'], c['revision']): c for c in replayed['claims']}
            for c in snap['claim_revision_history'] + snap['claims']:
                proof = expected_claims[(c['claim_id'], c['revision'])].get('ordinary_closure')
                if c.get('ordinary_closure') != proof:
                    raise ValueError('Ordinary closure differs from source-derived replay')
            for c in snap['claims']:
                if (c['status'] == 'closed-reimbursed') != bool(expected_claims[(c['claim_id'], c['revision'])].get('ordinary_closure')):
                    raise ValueError('Ordinary financial state differs from source-derived replay')
            if snap['request_facts'] != replayed['requests']:
                raise ValueError('Ordinary request facts differ from source-derived replay')
        expected_business = {(c['claim_id'], c['revision']): c['business_disposition']
                             for c in v.evaluate(doc, report, batch)['claims']}
        if any(c['business_disposition'] != expected_business[(c['claim_id'], c['revision'])]
               for c in snap['claims'] + snap['claim_revision_history']):
            raise ValueError('Business disposition differs from source-derived replay')
        if queue['batch_id'] != snap['batch_id'] or queue['run_id'] != snap['run_id'] or {i['record_id'] for i in queue['items'] if i['state'] == 'open'} != {i['record_id'] for i in snap['issues']}:
            raise ValueError('Snapshot/queue disagreement')
        if bool(sealed.get('dependency_containment')) != ('dependency_binding' in snap):
            raise ValueError('Missing/unexpected dependency containment state')
        if 'dependency_binding' in snap:
            binding = snap['dependency_binding']
            if hashes.get(binding['path']) != binding['sha256']:
                raise ValueError('Dependency graph binding mismatch')
            graph = json.loads(safe_path(output, binding['path']).read_bytes())
            d.verify(graph)
            inputs = {Path(i['path']).name: ROOT / i['path'] for i in sealed['input_bindings']}
            doc = json.loads(inputs['records.v1.json'].read_bytes())
            report = json.loads(inputs['parsing-report.v1.json'].read_bytes())
            validated = json.loads(inputs['findings.v1.json'].read_bytes())
            expected_graph = d.evaluate(doc, report, r.evaluate(doc, report, validated, batch))
            if graph != expected_graph or snap['dependency_summary'] != graph['summary']:
                raise ValueError('Dependency graph differs from source-derived replay')
            for claim in snap['claims']:
                expected_work = next(w for w in graph['claim_work'] if w['current_at_batch'] and (w['claim_id'], w['revision']) == (claim['claim_id'], claim['revision']))
                if claim['evidence_work'] != expected_work:
                    raise ValueError('Claim evidence work differs from graph')
            legacy_queue = json.loads((output / 'prior-repair-queue.original.json').read_bytes())
            legacy_manifest = json.loads((output / 'prior-operator-manifest.original.json').read_bytes())
            if snap['prior_operator']['manifest']['sha256'] != v.digest((output / 'prior-operator-manifest.original.json').read_bytes()) or snap['prior_operator']['summary'] != legacy_manifest['summary']:
                raise ValueError('Historical manifest lineage changed')
            old_queue = next(f for f in legacy_manifest['files'] if f['path'] == 'repair-queue.json')
            if old_queue['sha256'] != v.digest((output / 'prior-repair-queue.original.json').read_bytes()) or snap['prior_operator']['open_repairs'] != sum(i['state'] == 'open' for i in legacy_queue['items']):
                raise ValueError('Historical repairs changed or silently cleared')
        snapshots.append(snap); queues.append(queue)
        prior, final = {'path': name, 'sha256': hashes[name]}, snap
    if sealed['final_batch'] != prior or sealed['summary'] != final['summary']:
        raise ValueError('Manifest final snapshot disagreement')
    if (output / 'claims.csv').read_bytes() != claims_csv(final):
        raise ValueError('Claims CSV disagrees with final batch')
    if (output / 'repair-queue.json').read_bytes() != (output / f"queue/{sealed['through_batch']:03}.json").read_bytes():
        raise ValueError('Final repair queue disagreement')
    if (output / 'report.md').read_bytes() != markdown_report(sealed['run_id'], snapshots, queues):
        raise ValueError('Report disagrees with sealed snapshots/queue updates')
    return {'run_id': sealed['run_id'], 'verified_snapshots': sealed['through_batch'], 'verified_files': len(files),
            'current_claims': len(final['claims']), 'actual_financial_closures': final['actual_financial_closure_count'], 'open_repairs': len(final['issues'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build')
    for name in ('acquisition', 'normalized', 'validated', 'reconciled', 'output'):
        create.add_argument('--' + name, type=Path, required=True)
    create.add_argument('--run-id', required=True)
    create.add_argument('--through-batch', type=int, default=4)
    create.add_argument('--replay-of', type=Path)
    create.add_argument('--dependency-containment', action='store_true')
    create.add_argument('--prior-operator', type=Path)
    check = sub.add_parser('verify'); check.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'verify':
            print(json.dumps(verify(args.output), sort_keys=True)); return 0
        sealed = build(args.acquisition, args.normalized, args.validated, args.reconciled, args.output, args.run_id, args.through_batch, args.replay_of, args.dependency_containment, args.prior_operator)
        print(json.dumps(sealed['summary'], sort_keys=True)); return 2
    except (OSError, ValueError, KeyError, SchemaError, ValidationError) as exc:
        print(str(exc)); return 1


if __name__ == '__main__':
    raise SystemExit(main())

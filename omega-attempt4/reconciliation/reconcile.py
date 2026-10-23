"""Scope A increment 4: deterministic offline Finance facts and owned holds.

Admission establishes a reported request-level fact, never approval to pay.
Missing revision/cost columns are not reconstructed from identifier spelling.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from validation import validate as v

ROOT = v.ROOT
KINDS = {'accepted', 'adjustment', 'settled', 'refund', 'failed', 'pending',
         'retry_authorized', 'cancellation_requested', 'cancelled', 'resolution'}
MONEY_KINDS = {'settled', 'refund'}
PRIORITY = {'accepted': 0, 'adjustment': 1, 'settled': 2, 'refund': 3, 'resolution': 5}


def exact_cents(value, positive=False):
    """Finance amounts must already be integer cents; never round an event."""
    n = v.number(value)
    if n is None or n < 0 or (positive and n <= 0) or n * 100 != (n * 100).to_integral_value():
        return None
    return int(n * 100)


def diagnostic(code, reason, refs, owner='Finance', status='unresolved'):
    return {'code': code, 'status': status, 'reason': reason, 'owner': owner,
            'resolution_needed': reason, 'source_refs': sorted(set(refs)),
            'rule_refs': ['policy:finance_admission', 'policy:finance_reconciliation']}


def payload(row, headers):
    # Compare all decoded raw fields, even unrecognized columns. Also compare the
    # typed values so isolated test mutations cannot bypass immutable identity.
    return {'values': {k: val for k, val in row['values'].items() if k != 'Arrival batch'},
            'raw': {headers.get(col, col): cell['value'] for col, cell in row['raw_cells'].items()
                    if headers.get(col, col) != 'Arrival batch'}}


def invalid_arrival_dependencies(finance_rows):
    """Resolve only explicit request/event/payment links, never amount similarity.

    Malformed deliveries have no reliable arrival boundary. Their linked cases
    therefore remain held at every horizon; unrelated cases remain resumable.
    """
    affected = defaultdict(list)
    for bad in finance_rows:
        batch = bad['values'].get('Arrival batch')
        if isinstance(batch, int) and not isinstance(batch, bool) and batch >= 1:
            continue
        linked = [bad]
        requests, activities = set(), set()
        while True:
            for row in linked:
                fields = row['values']
                requests.update([fields.get('Request reference')])
                activities.update([fields.get('Activity reference'), fields.get('Original activity reference')])
            requests.discard(None); requests.discard('')
            activities.discard(None); activities.discard('')
            expanded = [row for row in finance_rows if row is bad or
                        row['values'].get('Request reference') in requests or
                        row['values'].get('Activity reference') in activities or
                        row['values'].get('Original activity reference') in activities]
            if len(expanded) == len(linked):
                break
            linked = expanded
        refs = [row['record_id'] for row in linked]
        for claim in {row['values'].get('Claim reference') for row in linked} - {None, ''}:
            affected[claim].append(diagnostic('finance_arrival_dependency',
                'Malformed Finance arrival retained: explicit claim/request/event/payment links require resolution before closure.', refs))
    return affected


def validation_core(saved):
    return {k: value for k, value in saved.items() if k not in ('input_bindings', 'summary')}


def load_verified(run, normalized, validated):
    doc, report = v.load_verified(run, normalized)
    path = validated / 'findings.v1.json'
    saved = json.loads(path.read_bytes())
    if saved.get('schema_version') != 'omega4-policy-validation/1':
        raise ValueError('Unsupported validation evidence schema')
    required = {str((run / 'sources.json').resolve()): v.digest((run / 'sources.json').read_bytes()),
                str((normalized / 'records.v1.json').resolve()): v.digest((normalized / 'records.v1.json').read_bytes())}
    bound = {}
    for item in saved['input_bindings']:
        p = (ROOT / item['path']).resolve()
        actual = v.digest(p.read_bytes())
        if actual != item['sha256'] or str(p) in bound:
            raise ValueError('Validation input hash mismatch or duplicate binding: ' + item['path'])
        bound[str(p)] = actual
    if any(bound.get(p) != sha for p, sha in required.items()):
        raise ValueError('Validation is not bound to the selected acquisition/normalization')
    expected_paths = {str(p.resolve()) for p in (run / 'sources.json', normalized / 'records.v1.json',
        normalized / 'parsing-report.v1.json', normalized / 'parsing-report.v1.md')}
    expected_paths.update(str((ROOT / p).resolve()) for p in (v.POLICY, v.PROVENANCE, v.INTERVIEW, v.DECISION,
        v.ASSIGNMENT, 'snapshot.schema.json', 'validation/validate.py', 'normalization/normalize.py', 'acquisition/retain.py'))
    if saved.get('ordinary_claim_ids'):
        expected_paths.add(str((ROOT / 'operator_delivery/ordinary-closure.md').resolve()))
    if set(bound) != expected_paths:
        raise ValueError('Validation governing input bindings are missing or unexpected')
    rebuilt = v.evaluate(doc, report, saved['through_batch'], ordinary_claim_ids=saved.get('ordinary_claim_ids', ()))
    if validation_core(saved) != rebuilt:
        raise ValueError('Validation evidence differs from deterministic recomputation')
    expected_summary = {
        'claim_revisions': len(rebuilt['claims']), 'current_claims': sum(c['current_at_batch'] for c in rebuilt['claims']),
        'expense_occurrences': sum(len(c['expenses']) for c in rebuilt['claims']),
        'claim_status_counts': dict(Counter(c['status'] for c in rebuilt['claims'])),
        'current_claim_status_counts': dict(Counter(c['status'] for c in rebuilt['claims'] if c['current_at_batch'])),
        'eligibility_status_counts': dict(Counter(c['eligibility_status'] for c in rebuilt['claims'])),
        'expense_status_counts': dict(Counter(e['status'] for c in rebuilt['claims'] for e in c['expenses'])),
        'normalization_diagnostic_count': len(report['issues']),
        'standalone_permit_reviews': len(rebuilt['standalone_permit_reviews']),
        'cancellation_processes': len(rebuilt['cancellations'])}
    if saved.get('summary') != expected_summary:
        raise ValueError('Validation summary differs from verified records')
    return doc, report, saved


def event_fields(doc, row):
    f, issues = row['values'], []
    refs = [row['record_id']]
    def bad(code, reason):
        issues.append(diagnostic(code, reason, refs))
    ident, request, claim = f.get('Activity reference'), f.get('Request reference'), f.get('Claim reference')
    kind, time = f.get('Activity type'), v.instant(f.get('Activity time (UTC)'))
    if not all(isinstance(x, str) and x.strip() for x in (ident, request, claim)):
        bad('event_identity', 'Nonempty immutable event, request and claim references are required.')
    if kind not in KINDS:
        bad('event_type', 'Unknown Finance event type; no invented effect.')
    if not time or time.astimezone(v.ZONE).date() > v.CASE_DATE:
        bad('event_time', 'Require a valid observed UTC business timestamp within the policy case date.')
    if f.get('Currency') != 'EUR':
        bad('event_currency', 'Finance request/outcome currency must be EUR.')
    if not f.get('Reason'):
        bad('event_reason', 'Finance outcome requires its supplied reason.')
    claim_candidates = [c for c in doc['claims'] if c['claim_id'] == claim and
                        c['arrival_batch'] <= f.get('Arrival batch', 0)]
    people = [p for p in v.rows(doc, 'People') if any(p['values']['Employee ID'] == c['employee_id'] for c in claim_candidates)
              and p['values'].get('Payee ID') == f.get('Payee ID')]
    person = v.unique(people)
    if not person:
        bad('event_payee', 'Claim/request payee must match one applicable employee directory entry.')
    elif person['values'].get('Finance officer') != f.get('Finance officer'):
        bad('event_actor', 'Only the applicable directory Finance officer can supply this outcome.')
    amount, obligation = None, None
    if kind in MONEY_KINDS:
        amount = exact_cents(f.get('Amount (EUR)'), positive=True)
        if amount is None:
            bad('event_amount', 'Settlements/refunds require positive integer cents; no rounding or guessed zero.')
        if f.get('Obligation (EUR)') is not None:
            bad('event_shape', 'A transfer/refund must not also mutate the accepted obligation.')
    elif f.get('Amount (EUR)') is not None:
        bad('event_shape', 'Status/obligation events do not establish a transfer amount.')
    if kind in ('accepted', 'adjustment', 'resolution'):
        obligation = exact_cents(f.get('Obligation (EUR)'))
        if obligation is None:
            bad('event_obligation', 'Accepted/adjusted/resolution amounts need known nonnegative integer cents.')
    elif f.get('Obligation (EUR)') is not None:
        bad('event_shape', 'This status event cannot change the accepted obligation.')
    if kind == 'refund':
        if not f.get('Original activity reference'):
            bad('refund_reference', 'Confirmed refund must identify a prior settled transfer.')
    elif f.get('Original activity reference') is not None:
        bad('event_shape', 'Unexpected original-transfer reference on a non-refund event.')
    return {'event_id': ident, 'request_id': request, 'claim_id': claim, 'kind': kind,
            'business_time': time.isoformat().replace('+00:00', 'Z') if time else f.get('Activity time (UTC)'), 'first_arrival_batch': f.get('Arrival batch'),
            'payee_id': f.get('Payee ID'), 'currency': f.get('Currency'), 'actor': f.get('Finance officer'),
            'amount_cents': amount, 'obligation_cents': obligation,
            'original_event_id': f.get('Original activity reference'),
            'source_refs': refs, 'admission_status': 'unresolved', 'admitted_in_batch': None,
            'diagnostics': issues, 'delivery_record_ids': [row['record_id']],
            'conflicting_delivery_record_ids': [], 'repeated_delivery_record_ids': []}


def new_request(event):
    return {'request_id': event['request_id'], 'claim_id': event['claim_id'],
            'payee_id': event['payee_id'], 'currency': event['currency'], 'finance_actor': event['actor'],
            'first_acceptance_batch': event['first_arrival_batch'], 'accepted_at': event['business_time'],
            'original_accepted_cents': event['obligation_cents'], 'accepted_cents': event['obligation_cents'],
            'admitted_settled_cents': 0, 'admitted_refund_cents': 0,
            'accepted_event_ids': [], 'settlement_event_ids': [], 'refund_event_ids': [],
            'adjustment_event_ids': [], 'resolution_event_ids': [], 'cancellation_event_ids': [],
            'event_ids': [], 'cancel_pending': False, 'cancelled': False,
            'failed_at': None, 'retry_authorized_at': None, 'diagnostics': []}


def apply_event(event, requests, events, batch):
    """Return a missing-dependency diagnostic or admit exactly one fact."""
    kind, rid = event['kind'], event['request_id']
    if kind == 'accepted' and rid not in requests:
        requests[rid] = new_request(event)
    request = requests.get(rid)
    if request is None:
        return diagnostic('request_reference', 'No validated acceptance for this exact original request; recheck when evidence arrives.', event['source_refs'])
    if any(event[k] != request[rk] for k, rk in [('claim_id', 'claim_id'), ('payee_id', 'payee_id'), ('currency', 'currency'), ('actor', 'finance_actor')]):
        return diagnostic('request_identity', 'Outcome claim/payee/currency/actor differs from the original accepted request.', event['source_refs'])
    if v.instant(event['business_time']) < v.instant(request['accepted_at']):
        return diagnostic('request_time', 'Outcome predates original request acceptance; no guessed ordering.', event['source_refs'])
    if kind == 'accepted':
        if request['accepted_event_ids']:
            return diagnostic('repeated_acceptance', 'Another immutable acceptance ID for the same request needs Finance clarification; no duplicate commitment.', event['source_refs'])
        request['accepted_event_ids'].append(event['event_id'])
    elif kind == 'adjustment':
        request['accepted_cents'] = event['obligation_cents']
        request['adjustment_event_ids'].append(event['event_id'])
    elif kind == 'settled':
        request['admitted_settled_cents'] += event['amount_cents']
        request['settlement_event_ids'].append(event['event_id'])
        if request['cancelled'] or request['cancel_pending']:
            request['diagnostics'].append(diagnostic('late_original_request_settlement',
                'Confirmed transfer on the original cancelled/cancel-pending request remains money; Finance must resolve it.', event['source_refs']))
        if request['failed_at'] and (not request['retry_authorized_at'] or request['retry_authorized_at'] <= request['failed_at']):
            request['diagnostics'].append(diagnostic('retry_authority',
                'Transfer is reported, but no intervening Finance retry authorization is present. Preserve money and hold further payment.', event['source_refs']))
    elif kind == 'refund':
        original = events.get(event['original_event_id'])
        if not original or original['admission_status'] != 'admitted' or original['kind'] != 'settled':
            return diagnostic('refund_reference', 'Refund requires an admitted settled original transfer, not a request or promise.', event['source_refs'])
        if original['request_id'] != rid or original['claim_id'] != event['claim_id'] or original['payee_id'] != event['payee_id'] or original['currency'] != event['currency']:
            return diagnostic('refund_identity', 'Refund and original transfer must share exact request, claim, payee and currency.', event['source_refs'] + original['source_refs'])
        if v.instant(event['business_time']) <= v.instant(original['business_time']):
            return diagnostic('refund_time', 'Refund must follow its original settled transfer strictly in business time.', event['source_refs'])
        recovered = sum(e['amount_cents'] for e in events.values() if e['kind'] == 'refund' and
                        e['admission_status'] == 'admitted' and e['original_event_id'] == original['event_id'])
        peers = [e for e in events.values() if e['kind'] == 'refund' and e['admission_status'] != 'admitted' and
                 not e.get('shape_invalid') and e['original_event_id'] == original['event_id'] and
                 e['business_time'] == event['business_time'] and e['first_arrival_batch'] == event['first_arrival_batch']]
        if event['amount_cents'] + recovered > original['amount_cents'] or (len(peers) > 1 and recovered + sum(e['amount_cents'] for e in peers) > original['amount_cents']):
            return diagnostic('refund_exceeds_transfer', 'Refund(s) exceed unrecovered original transfer; no clamping or arbitrary equal-time selection.', event['source_refs'] + original['source_refs'])
        request['admitted_refund_cents'] += event['amount_cents']
        request['refund_event_ids'].append(event['event_id'])
    elif kind == 'failed':
        request['failed_at'] = event['business_time']
    elif kind == 'retry_authorized':
        if not request['failed_at'] or v.instant(event['business_time']) <= v.instant(request['failed_at']):
            return diagnostic('retry_reference', 'Retry authorization needs a prior failed attempt on this request.', event['source_refs'])
        request['retry_authorized_at'] = event['business_time']
    elif kind == 'cancellation_requested':
        request['cancel_pending'] = True
        request['cancellation_event_ids'].append(event['event_id'])
    elif kind == 'cancelled':
        request['cancel_pending'] = False
        request['cancelled'] = True
        request['accepted_cents'] = 0
        request['cancellation_event_ids'].append(event['event_id'])
    elif kind == 'resolution':
        request['resolution_event_ids'].append(event['event_id'])
    request['event_ids'].append(event['event_id'])
    event['admission_status'], event['admitted_in_batch'] = 'admitted', batch
    return None


def request_view(request, events):
    result = deepcopy(request)
    associated = [e for e in events.values() if e['request_id'] == request['request_id'] or
                  request['request_id'] in e.get('conflicting_request_ids', [])]
    uncertain = [e for e in associated if e['admission_status'] != 'admitted' or e['conflicting_delivery_record_ids']]
    observed = request['admitted_settled_cents'] - request['admitted_refund_cents']
    result['admitted_net_cents'] = observed
    effects = [events[x] for x in request['event_ids'] if events[x]['kind'] in ('accepted', 'adjustment', 'cancelled')]
    last_time = max(e['business_time'] for e in effects)
    latest_effects = [e for e in effects if e['business_time'] == last_time]
    targets = {0 if e['kind'] == 'cancelled' else e['obligation_cents'] for e in latest_effects}
    result['accepted_cents'] = targets.pop() if len(targets) == 1 else None
    result['cancelled'] = any(e['kind'] == 'cancelled' for e in latest_effects)
    if result['accepted_cents'] is None:
        result['diagnostics'].append(diagnostic('ambiguous_obligation_time', 'Different accepted targets at the same business instant cannot be ordered by row or event-ID spelling.', [ref for e in latest_effects for ref in e['source_refs']]))
    # Absence of a transfer report is not affirmative evidence of a paid zero.
    complete = not uncertain and bool(request['settlement_event_ids'])
    result['net_confirmed_settled_cents'] = observed if complete else None
    result['accepted_minus_net_cents'] = result['accepted_cents'] - observed if complete and result['accepted_cents'] is not None else None
    result['remaining_commitment_cents'] = max(result['accepted_cents'] - observed, 0) if result['accepted_cents'] is not None else None
    result['uncertain_event_ids'] = sorted(e['event_id'] for e in uncertain)
    resolutions = [events[x] for x in request['resolution_event_ids']]
    latest = max(resolutions, key=lambda e: (e['admitted_in_batch'], e['business_time'], e['event_id']), default=None)
    result['resolution_assessment'] = {'event_id': latest['event_id'] if latest else None,
        'request_amounts_agree': bool(latest and complete and latest['obligation_cents'] == result['accepted_cents'] == observed),
        'current_claim_scope': 'unresolved: Finance resolution has no claim-revision, cost, correction or cancellation-context columns'}
    if latest:
        later_money = [e for e in associated if e['admission_status'] == 'admitted' and e['kind'] in MONEY_KINDS and
                       (e['admitted_in_batch'] > latest['admitted_in_batch'] or e['business_time'] > latest['business_time'])]
        if later_money:
            result['resolution_assessment']['request_amounts_agree'] = False
            result['diagnostics'].append(diagnostic('resolution_reopened', 'A later-observed transfer/refund requires renewed reconciliation and Finance resolution.', latest['source_refs'] + [ref for e in later_money for ref in e['source_refs']]))
    if not complete or result['accepted_cents'] is None:
        state = 'unresolved'
    elif result['accepted_minus_net_cents'] < 0:
        state = 'overpaid_against_request'
    elif result['accepted_minus_net_cents'] > 0:
        state = 'partial_settlement'
    else:
        state = 'request_amounts_aligned'
    result['reconciliation_state'] = state
    result['source_refs'] = sorted({ref for e in associated for ref in e['source_refs']})
    if not request['settlement_event_ids']:
        result['diagnostics'].append(diagnostic('missing_settlement_evidence', 'Acceptance/status is not a confirmed transfer or affirmative zero-payment evidence; exact net remains unknown.', result['source_refs']))
    elif state in ('partial_settlement', 'overpaid_against_request'):
        result['diagnostics'].append(diagnostic(state, 'Accepted request target and confirmed net differ; retain the signed difference and obtain Finance evidence.', result['source_refs']))
    if latest and not result['resolution_assessment']['request_amounts_agree']:
        result['diagnostics'].append(diagnostic('resolution_not_reconciled', 'Supplied resolution cannot establish even request-level agreement with current accepted target and known net.', latest['source_refs']))
    result['acceptance_status'] = 'admitted'
    return result


def orphan_request_views(events, requests):
    """Keep original request references even when their acceptance is missing."""
    result = []
    ids = {rid for e in events.values() for rid in [e['request_id']] + e.get('conflicting_request_ids', []) if rid and rid not in requests}
    for rid in sorted(ids):
        associated = [e for e in events.values() if e['request_id'] == rid or rid in e.get('conflicting_request_ids', [])]
        claim_ids = {e['claim_id'] if e['request_id'] == rid else None for e in associated}
        refs = sorted({ref for e in associated for ref in e['source_refs']})
        result.append({'request_id': rid, 'claim_id': next(iter(claim_ids)) if len(claim_ids) == 1 else None,
            'first_acceptance_batch': None, 'accepted_at': None, 'acceptance_status': 'unresolved',
            'original_accepted_cents': None, 'accepted_cents': None, 'admitted_settled_cents': 0,
            'admitted_refund_cents': 0, 'admitted_net_cents': 0, 'net_confirmed_settled_cents': None,
            'remaining_commitment_cents': None, 'accepted_minus_net_cents': None,
            'accepted_event_ids': [], 'settlement_event_ids': [], 'refund_event_ids': [],
            'adjustment_event_ids': [], 'resolution_event_ids': [], 'cancellation_event_ids': [], 'event_ids': [],
            'cancelled': False, 'reconciliation_state': 'unresolved', 'source_refs': refs,
            'uncertain_event_ids': sorted(e['event_id'] for e in associated),
            'diagnostics': [diagnostic('missing_request_acceptance', 'Original request reference retained, but no valid Finance acceptance establishes its target, basis or settled amount.', refs)]})
    return result


def ordinary_certificate(doc, policy, claim, request, events):
    """Prove only a selected, unchanged single-cost ordinary settlement.

    Package certification remains unresolved. No correction/exception/refund/
    cancellation can enter this path, with or without a matching total.
    """
    if (not claim or claim['approval_status'] != 'supported' or claim['status'] != 'supported'
            or claim['eligibility_status'] != 'supported' or claim['normalization_diagnostics']
            or claim['cancellation_ids'] or claim['travel_cancellation_scope'] != 'no_observed_cancellation'
            or len(claim['expenses']) != 1 or request['diagnostics'] or request['uncertain_event_ids']
            or request['acceptance_status'] != 'admitted' or request['cancel_pending'] or request['cancelled']
            or len(request['event_ids']) != 2 or len(request['accepted_event_ids']) != 1
            or len(request['settlement_event_ids']) != 1
            or request['original_accepted_cents'] != request['accepted_cents']
            or request['net_confirmed_settled_cents'] != request['accepted_cents']
            or request['accepted_cents'] != claim['calculated_allowed_cents']):
        return None
    if invalid_arrival_dependencies(v.rows(doc, 'Finance activity')).get(claim['claim_id']):
        return None
    family = [c for c in doc['claims'] if c['claim_id'] == claim['claim_id']]
    if len(family) != 1 or family[0].get('finance_exception') or family[0].get('related_claim_ids'):
        return None
    # A second request, even unresolved, is a competing original obligation.
    deliveries = [r for r in v.rows(doc, 'Finance activity') if r['values'].get('Claim reference') == claim['claim_id']]
    if {r['values'].get('Request reference') for r in deliveries} != {request['request_id']}:
        return None
    accepted = events[request['accepted_event_ids'][0]]
    settled = events[request['settlement_event_ids'][0]]
    if (accepted['admission_status'] != 'admitted' or settled['admission_status'] != 'admitted'
            or v.instant(settled['business_time']) < v.instant(accepted['business_time'])):
        return None
    # Unknown package scope is disclosed separately, never silently certified.
    known_package = {'policy_provenance', 'review_version_token', 'budget_completeness', 'assignment_access'}
    if any(f['code'] not in known_package or f['status'] != 'unresolved' for f in policy['global_findings']):
        return None
    reviewed = claim['claim_review']
    when = min(v.instant(e['decision_time']) for e in reviewed['imports'])
    source = family[0]
    person = v.unique([r for r in v.rows(doc, 'People') if r['values']['Employee ID'] == source['employee_id']])
    if not person:
        return None
    pv = person['values']
    budget = v.unique([b for b in policy['supplied_budget_context'] if
                      (b['department'], b['project'], b['period']) == (pv['Department'], pv['Project'], pv['Budget period'])])
    if not budget or budget['supplied_ledger_available_cents'] is None or budget['supplied_ledger_available_cents'] < request['accepted_cents']:
        return None
    # Do not reconstruct an unreviewed dynamic budget in this narrow path.
    for row in v.rows(doc, 'Finance activity'):
        x = row['values']
        if x.get('Activity type') == 'accepted' and v.instant(x.get('Activity time (UTC)')) and v.instant(x['Activity time (UTC)']) < when:
            other = v.unique([c for c in doc['claims'] if c['claim_id'] == x.get('Claim reference')])
            directory = v.unique([p for p in v.rows(doc, 'People') if other and p['values']['Employee ID'] == other['employee_id']])
            if not directory or all(directory['values'].get(k) == pv.get(k) for k in ('Department', 'Project', 'Budget period')):
                return None
    refs = set(request['source_refs'] + [claim['source_ref'], 'interview:ordinary_entitlement',
                                       'policy:finance_admission', 'policy:finance_reconciliation'])
    for f in (claim['findings'] + reviewed['findings']
              + [f for e in reviewed['imports'] for f in e['findings']]
              + [f for e in claim['expenses'] for f in e['findings']]):
        refs.update(f['source_refs'])
    return {'schema_version': 'omega4-ordinary-closure/1', 'claim_id': claim['claim_id'], 'revision': claim['revision'],
            'expense_id': claim['expenses'][0]['expense_id'], 'request_id': request['request_id'],
            'amount_cents': request['accepted_cents'], 'decision_ids': sorted(set(reviewed['selected_decisions'].values())),
            'accepted_event_id': accepted['event_id'], 'settlement_event_id': settled['event_id'],
            'source_refs': sorted(refs), 'scope': 'Derived closure within retained evidence; no new payment or external completeness certification.',
            'package_certification': 'unresolved'}


def basis_links(doc, policy_at_acceptance, request, events=None, ordinary_claim_ids=()):
    """Retain potential bases separately from source-explicit request identity."""
    candidates = [c for c in policy_at_acceptance['claims'] if c['claim_id'] == request['claim_id']]
    current = v.unique([c for c in candidates if c['current_at_batch']])
    refs = request['source_refs'] + [c['source_ref'] for c in candidates]
    result = {'candidate_revision': current['revision'] if current else None,
            'observed_revision_candidates': [c['revision'] for c in candidates],
            'candidate_trip_id': current['trip_id'] if current else None,
            'candidate_trip_revision': current['trip_revision'] if current else None,
            'candidate_expenses': [e['expense_id'] for e in current['expenses']] if current else [],
            'attributed_revision': None, 'attributed_expenses': None, 'status': 'unresolved',
            'authorization_at_acceptance': current['approval_status'] if current else 'unresolved',
            'selected_review_ids_at_acceptance': current['claim_review']['selected_decisions'] if current and current['claim_review'] else {},
            'diagnostics': [diagnostic('request_revision_cost_binding',
                'Source-explicit request/claim link exists, but Finance has no claim-revision/expense fields. Current-at-acceptance candidates are not certified attribution or authority.', refs)]}
    certificate = (ordinary_certificate(doc, policy_at_acceptance, current, request, events)
                   if request['claim_id'] in ordinary_claim_ids else None)
    if certificate:
        result.update(attributed_revision=current['revision'], attributed_expenses=result['candidate_expenses'],
                      status='supported', diagnostics=[], ordinary_closure=certificate)
    return result


def gross_amounts(doc, claim):
    by_currency = defaultdict(Decimal)
    total, known = 0, True
    for e in claim['expenses']:
        amount = v.number(e['original_amount'])
        if amount is None:
            known = False; continue
        by_currency[e['currency']] += amount
        rate = Decimal(1) if e['currency'] == 'EUR' else None
        if rate is None:
            matches = [r for r in v.rows(doc, 'Merchant payments') if all(r['values'].get(k) == value for k, value in {
                'Employee ID': claim['employee_id'], 'Trip reference': claim['trip_id'], 'Expense reference': e['expense_id'],
                'Receipt reference': e['receipt_id'], 'Currency': e['currency']}.items()) and v.number(r['values'].get('Gross amount')) == amount]
            payment = v.unique(matches)
            rates = [r for r in v.rows(doc, 'FX') if payment and r['values'].get('Currency') == e['currency'] and
                     r['values'].get('Rate date') == payment['values'].get('Paid date')]
            fx = v.unique(rates)
            rate = v.number(fx['values']['EUR per currency unit']) if fx else None
        if rate is None or rate <= 0:
            known = False
        else:
            total += v.cents(amount, rate)
    return {currency: str(amount) for currency, amount in sorted(by_currency.items())}, total if known else None


def shared_cost_candidates(doc, claim, policy_claim, requests, policy_cache):
    """Compute a conditional incremental calculation without inventing allocation."""
    exclusions, diagnostics = [], []
    for e in claim['expenses']:
        identity = (claim['employee_id'], claim['trip_id'], e['expense_id'], e['receipt_id'], e['currency'], v.number(e['original_amount']))
        matches = []
        for req in requests:
            if req['claim_id'] == claim['claim_id'] or req['first_acceptance_batch'] is None or req['first_acceptance_batch'] >= claim['arrival_batch']:
                continue
            candidate = v.unique([c for c in policy_cache[req['first_acceptance_batch']]['claims'] if c['claim_id'] == req['claim_id'] and c['current_at_batch']])
            original = v.unique([c for c in doc['claims'] if candidate and (c['claim_id'], c['revision']) == (candidate['claim_id'], candidate['revision'])])
            if not original:
                continue
            for old in original['expenses']:
                other = (original['employee_id'], original['trip_id'], old['expense_id'], old['receipt_id'], old['currency'], v.number(old['original_amount']))
                if identity == other:
                    matches.append((req, candidate, old))
        if not matches:
            continue
        req, basis, old = matches[0]
        line = next(x for x in policy_claim['expenses'] if x['expense_id'] == e['expense_id'])
        # A fully settled entire candidate bundle permits a conditional exclusion;
        # partial settlements have no supplied per-line allocation.
        full_bundle = (len(matches) == 1 and req['net_confirmed_settled_cents'] is not None and
                       req['net_confirmed_settled_cents'] == req['original_accepted_cents'] == basis['calculated_allowed_cents'] and
                       not req['adjustment_event_ids'] and not req['cancelled'])
        exclusions.append({'expense_id': e['expense_id'], 'prior_request_ids': sorted({m[0]['request_id'] for m in matches}),
                           'candidate_excluded_cents': line['calculated_allowed_cents'] if full_bundle else None,
                           'status': 'unresolved', 'source_refs': sorted(set([claim['record_id'], old['record_id']] + req['source_refs']))})
        diagnostics.append(diagnostic('shared_cost_allocation', 'Same purchase identity occurs in an earlier accepted request. Conditional full-bundle exclusion is shown; explicit request/cost binding remains needed, and partial payments are never allocated by guess.', exclusions[-1]['source_refs']))
    amounts = [e['candidate_excluded_cents'] for e in exclusions]
    incremental = policy_claim['calculated_allowed_cents']
    if incremental is not None:
        incremental = incremental - sum(amounts) if all(x is not None for x in amounts) else None
    return exclusions, incremental, diagnostics


def evaluate(doc, report, validated, through_batch=None):
    horizon = validated['through_batch'] if through_batch is None else through_batch
    if not isinstance(horizon, int) or isinstance(horizon, bool) or not 1 <= horizon <= validated['through_batch']:
        raise ValueError('Reconciliation batch must be within the verified validation horizon')
    targets = validated.get('ordinary_claim_ids', ())
    policy_cache = {batch: v.evaluate(doc, report, batch, ordinary_claim_ids=targets) for batch in range(1, horizon + 1)}
    finance_rows = v.rows(doc, 'Finance activity')
    headers = doc['workbook']['Finance activity']['headers']
    events, requests, deliveries, batch_views, global_issues = {}, {}, [], [], []
    for batch in range(1, horizon + 1):
        arriving = [r for r in finance_rows if not isinstance(r['values'].get('Arrival batch'), bool) and r['values'].get('Arrival batch') == batch]
        groups = defaultdict(list)
        for row in arriving:
            ident = row['values'].get('Activity reference') or 'missing-id:' + row['record_id']
            groups[ident].append(row)
        for ident, copies in sorted(groups.items()):
            canonical = payload(copies[0], headers)
            first_conflict = any(payload(r, headers) != canonical for r in copies)
            fresh = ident not in events
            if fresh:
                event = event_fields(doc, copies[0]); event['event_id'] = ident
                event['payload'] = canonical
                event['shape_invalid'] = bool(event['diagnostics']) or first_conflict
                events[ident] = event
            event = events[ident]
            if first_conflict and fresh:
                event['diagnostics'].append(diagnostic('conflicting_first_delivery', 'Different immutable payloads first arrive together; no arbitrary first-payload admission.', [r['record_id'] for r in copies]))
            for index, row in enumerate(copies):
                same = payload(row, headers) == event['payload']
                if row['record_id'] not in event['delivery_record_ids']:
                    event['delivery_record_ids'].append(row['record_id'])
                event['source_refs'] = sorted(set(event['source_refs'] + [row['record_id']]))
                if not same or (fresh and first_conflict):
                    classification = 'conflicting_delivery'
                    event['conflicting_delivery_record_ids'].append(row['record_id'])
                    event.setdefault('conflicting_request_ids', []).append(row['values'].get('Request reference'))
                    global_issues.append(diagnostic('conflicting_finance_delivery', 'Conflicting immutable event payload: retain prior admitted money and hold every affected request.', [row['record_id']] + event['source_refs']))
                elif not fresh or index > 0:
                    classification = 'repeated_delivery'
                    event['repeated_delivery_record_ids'].append(row['record_id'])
                else:
                    classification = 'first_delivery'
                deliveries.append({'record_id': row['record_id'], 'source': row['source'], 'values': deepcopy(row['values']),
                                   'raw_cells': deepcopy(row['raw_cells']), 'arrival_batch': batch,
                                   'event_id': ident, 'classification': classification})
        # Retry dependencies when new evidence arrives, without rewriting earlier
        # batch views. Business time orders effects within an arrival boundary.
        pending = sorted([e for e in events.values() if e['admission_status'] != 'admitted' and not e['shape_invalid']],
                         key=lambda e: (e['business_time'], PRIORITY.get(e['kind'], 1), e['event_id']))
        for _ in range(len(pending) + 1):
            changed = False
            for event in pending:
                if event['admission_status'] == 'admitted':
                    continue
                issue = apply_event(event, requests, events, batch)
                event['dependency_diagnostic'] = issue
                if issue is None:
                    changed = True
            if not changed:
                break
        batch_views.append({'batch': batch, 'admitted_event_ids': sorted(e['event_id'] for e in events.values() if e['admission_status'] == 'admitted'),
                            'requests': [request_view(r, events) for _, r in sorted(requests.items())] + orphan_request_views(events, requests)})
    # Invalid batch labels cannot silently disappear from the delivery inventory.
    for row in finance_rows:
        value = row['values'].get('Arrival batch')
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            deliveries.append({'record_id': row['record_id'], 'source': row['source'], 'values': deepcopy(row['values']),
                               'raw_cells': deepcopy(row['raw_cells']), 'arrival_batch': value, 'event_id': row['values'].get('Activity reference'), 'classification': 'invalid_arrival'})
            global_issues.append(diagnostic('finance_arrival', 'Invalid arrival batch; delivery retained without admission.', [row['record_id']]))
    invalid_dependencies = invalid_arrival_dependencies(finance_rows)
    request_results = [request_view(r, events) for _, r in sorted(requests.items())] + orphan_request_views(events, requests)
    acceptance_policy = {}
    for request in request_results:
        if request['first_acceptance_batch'] is None:
            request['basis_links'] = {'candidate_revision': None, 'candidate_trip_id': None, 'candidate_trip_revision': None,
                'attributed_revision': None, 'attributed_expenses': None, 'status': 'unresolved',
                'diagnostics': [diagnostic('missing_request_basis', 'Cannot reconstruct a request basis without valid acceptance evidence.', request['source_refs'])]}
            continue
        key = (request['first_acceptance_batch'], request['accepted_at'])
        if key not in acceptance_policy:
            historical_doc = deepcopy(doc)
            # Review/cancellation evidence after the acceptance's business instant
            # cannot retroactively authorize that acceptance, even in the same batch.
            for tab, field in [('Review ledger', 'Decision time (UTC)'), ('Travel cancellations', 'Activity time (UTC)')]:
                historical_doc['workbook'][tab]['rows'] = [r for r in v.rows(historical_doc, tab) if
                    not v.instant(r['values'].get(field)) or v.instant(r['values'][field]) <= v.instant(request['accepted_at'])]
            acceptance_policy[key] = v.evaluate(historical_doc, report, request['first_acceptance_batch'], ordinary_claim_ids=targets)
        request['basis_links'] = basis_links(doc, acceptance_policy[key], request, events, targets)
    final_policy = policy_cache[horizon]
    claim_results = []
    for policy_claim in final_policy['claims']:
        claim = next(c for c in doc['claims'] if c['record_id'] == policy_claim['source_ref'])
        related = [r for r in request_results if r['claim_id'] == claim['claim_id']]
        fs = [diagnostic('approval_evidence', 'Current revision role/packet/amount evidence must be fully supported before further payment; Finance acceptance is not an approval substitute.', [claim['record_id']], 'Administration')]
        if policy_claim['approval_status'] == 'supported' and policy_claim['eligibility_status'] == 'supported':
            fs = []
        if policy_claim['eligibility_status'] == 'blocked' or (policy_claim['claim_review'] and any(f['status'] == 'blocked' for f in policy_claim['claim_review']['findings'])):
            fs.append(diagnostic('current_policy_or_review_block', 'Current eligibility or supplied review outcome blocks further payment; money observations do not override that finding.', [claim['record_id']], 'Administration', 'blocked'))
        if final_policy['global_findings']:
            fs.append(diagnostic('inherited_validation_limits', 'Preserved policy/version/budget and packet-definition gaps still prevent certified payment readiness.', [claim['record_id']], 'Facilitator'))
        earlier_requests = [r for r in related if r['first_acceptance_batch'] is not None and any(c['claim_id'] == claim['claim_id'] and c['revision'] < claim['revision'] and
                                                    c['arrival_batch'] <= r['first_acceptance_batch'] < claim['arrival_batch'] for c in doc['claims'])]
        if earlier_requests:
            fs.append(diagnostic('decision_001_original_request_hold',
                'Corrected claim follows an original acceptance. Require explicit Finance resolution of original-request consequences and valid current reviews; request-only resolution does not prove current revision/cost scope.',
                [claim['record_id'], 'decision:001'] + [ref for r in earlier_requests for ref in r['source_refs']], 'Finance', 'blocked'))
        if not related:
            fs.append(diagnostic('missing_finance_request', 'No accepted Finance request or confirmed outcome for this claim; accepted/net amounts remain unknown.', [claim['record_id']]))
        for req in related:
            fs.extend(req['diagnostics'])
            fs.extend(req['basis_links']['diagnostics'])
            if req['uncertain_event_ids']:
                fs.append(diagnostic('unresolved_request_events', 'One or more original-request deliveries remain unresolved/conflicting; admitted money is preserved separately.', req['source_refs']))
        if claim['claim_id'] in targets:
            fs.extend(invalid_dependencies.get(claim['claim_id'], []))
        exclusions, incremental, shared_diagnostics = shared_cost_candidates(doc, claim, policy_claim, request_results, policy_cache)
        fs.extend(shared_diagnostics)
        gross, gross_eur = gross_amounts(doc, claim)
        policy_diagnostics = [f for line in policy_claim['expenses'] for f in line['findings'] if f['status'] != 'supported']
        policy_diagnostics += [f for f in (policy_claim['claim_review']['findings'] if policy_claim['claim_review'] else []) if f['status'] != 'supported']
        expense_results = []
        for line in policy_claim['expenses']:
            expense = next(e for e in claim['expenses'] if e['record_id'] == line['expense_record_id'])
            expense_results.append({'expense_id': expense['expense_id'], 'expense_record_id': expense['record_id'],
                'receipt_id': expense['receipt_id'], 'gross_original': expense['original_amount'], 'currency': expense['currency'],
                'base_allowed_original': line['base_allowed_original'], 'policy_allowed_original': line['allowed_original'],
                'policy_allowed_cents': line['calculated_allowed_cents'], 'eligibility_status': line['status'],
                'accepted_cents': None, 'net_confirmed_settled_cents': None,
                'attribution_status': 'unresolved: no source-explicit request/cost allocation',
                'candidate_request_ids': [req['request_id'] for req in related if expense['expense_id'] in req['basis_links'].get('candidate_expenses', [])],
                'source_refs': sorted({expense['record_id']} | {ref for finding in line['findings'] for ref in finding['source_refs']})})
        closure = related[0]['basis_links'].get('ordinary_closure') if len(related) == 1 else None
        if (closure and policy_claim['status'] == 'supported' and policy_claim['current_at_batch']
                and not exclusions and not policy_diagnostics
                and all(f['code'] == 'inherited_validation_limits' for f in fs)):
            # The old blanket inheritance is not a proven local business defect.
            # Keep every global finding in validation_global_findings and package work.
            fs = []
            for expense in expense_results:
                expense.update(accepted_cents=closure['amount_cents'], net_confirmed_settled_cents=closure['amount_cents'],
                               attribution_status='supported: unique unchanged source-backed join')
        else:
            closure = None
        claim_results.append({**({'ordinary_closure': closure} if closure else {}),
            'claim_id': claim['claim_id'], 'revision': claim['revision'], 'current_at_batch': policy_claim['current_at_batch'],
            'trip_id': claim['trip_id'], 'trip_revision': claim['trip_revision'], 'source_refs': [claim['record_id']],
            'gross_original_by_currency': gross, 'gross_purchase_cents': gross_eur,
            'expenses': expense_results,
            'policy_allowed_cents': policy_claim['calculated_allowed_cents'], 'eligibility_status': policy_claim['eligibility_status'],
            'approval_status': policy_claim['approval_status'], 'selected_current_review_ids': policy_claim['claim_review']['selected_decisions'] if policy_claim['claim_review'] else {},
            'business_disposition': deepcopy(policy_claim['business_disposition']),
            'related_original_request_ids': [r['request_id'] for r in related],
            'revision_accepted_cents': closure['amount_cents'] if closure else None,
            'revision_net_confirmed_settled_cents': closure['amount_cents'] if closure else None,
            'revision_attribution_status': 'supported: unique unchanged source-backed join' if closure else 'unresolved: explicit request/revision/cost lineage missing',
            'prior_cost_candidates': exclusions, 'incremental_policy_candidate_cents': incremental,
            'incremental_authorized_cents': 0 if closure else None,
            'payment_readiness': 'settled_no_new_payment' if closure else 'blocked' if any(f['status'] == 'blocked' for f in fs) else 'unresolved',
            'travel_cancellation_scope': policy_claim['travel_cancellation_scope'], 'cancellation_ids': policy_claim['cancellation_ids'],
            'normalization_diagnostics': policy_claim['normalization_diagnostics'], 'policy_diagnostics': policy_diagnostics, 'diagnostics': fs})
    cancellation_results = []
    for cancel in final_policy['cancellations']:
        affected = [c for c in claim_results if (c['trip_id'], c['trip_revision']) == (cancel['trip_id'], cancel['trip_revision'])]
        linked = [r for r in request_results if (r['basis_links']['candidate_trip_id'], r['basis_links']['candidate_trip_revision']) == (cancel['trip_id'], cancel['trip_revision'])]
        before_acceptance = bool(linked and cancel['confirmed_at'] and all(v.instant(cancel['confirmed_at']) < v.instant(r['accepted_at']) for r in linked))
        cancellation_results.append({**deepcopy(cancel),
            'affected_claim_revisions': [{'claim_id': c['claim_id'], 'revision': c['revision']} for c in affected],
            'candidate_original_request_ids': [r['request_id'] for r in linked],
            'finance_event_ids': sorted({ident for r in linked for ident in r['event_ids']}),
            'separate_finance_resolution_requirement': 'not_imposed_by_business_cancellation_before_observed_acceptance' if before_acceptance else 'required_for_post_acceptance_consequences' if linked else 'no_observed_request',
            'financial_consequence_status': 'unresolved' if affected or linked else 'no_observed_claim_or_request',
            'money_effect_from_business_cancellation_cents': 0})
    source_index = deepcopy(validated['source_index'])
    source_index['policy:finance_admission'] = {'path': v.POLICY, 'sha256': v.POLICY_HASH, 'lines': [24, 25]}
    source_index['policy:finance_reconciliation'] = {'path': v.POLICY, 'sha256': v.POLICY_HASH, 'lines': [23, 26, 30, 31]}
    for event in events.values():
        if event.get('dependency_diagnostic'):
            event['diagnostics'].append(event['dependency_diagnostic'])
        event.pop('dependency_diagnostic', None)
    all_unresolved = global_issues + [issue for e in events.values() for issue in e['diagnostics']] + [issue for r in request_results for issue in r['diagnostics']] + [issue for c in claim_results for issue in c['diagnostics']]
    for claim in claim_results:
        all_unresolved += [diagnostic('policy_' + f['code'], f['reason'], f['source_refs'], f['owner'], f['status']) for f in claim['policy_diagnostics']]
    unique_issues = {v.digest(v.encoded(item)): item for item in all_unresolved}
    all_unresolved = [dict(unique_issues[key], item_id='finance-issue:' + key) for key in sorted(unique_issues)]
    return {**({'ordinary_claim_ids': list(targets)} if targets else {}),
        'schema_version': 'omega4-finance-reconciliation/1', 'mode': 'offline-retained-replay',
        'case_clock': validated['case_clock'], 'through_batch': horizon, 'finance_deliveries': deliveries,
        'finance_events': [e for _, e in sorted(events.items())], 'requests': request_results, 'claims': claim_results,
        'travel_cancellations': cancellation_results, 'batch_views': batch_views,
        'normalization_diagnostics': report['issues'], 'validation_global_findings': validated['global_findings'],
        'validation_unmatched_reviews': validated['unmatched_review_imports'],
        'unresolved_items': all_unresolved, 'source_index': source_index,
        'limitations': [
            'Finance fact admission validates immutable identity, actor/payee, request, currency, cents, time and refund linkage; it does not certify discretionary approval or authorize new payment.',
            ('Only explicitly selected unique unchanged ordinary bases can receive derived revision/cost attribution after full matching settlement. All other bases remain conditional and unknown.' if targets else
             'No explicit claim revision or expense columns occur in Finance. Candidate historical/current bases and shared-cost exclusions remain conditional; revision-level accepted/net money is null.'),
            'Net-confirmed amounts cover the admitted retained request ledger only; they do not certify external bank completeness. With unresolved/conflicting deliveries or no settlement report, exact net is null and admitted subtotals remain visible.',
            'All increment 3 policy/packet/version/completeness gaps are preserved. No historical approval or request-level resolution creates current authorization.',
            'Confirmed Finance cancellation releases the accepted request target to zero, preserves its original acceptance, and never erases a later reported transfer or changes gross/policy-allowed costs.',
            ('Selected ordinary closure certificates record existing retained settlement only. Global certification stays unresolved; no new request, payment or external action is authorized.' if targets else
             'Resolution amounts are assessed at request level; no claim closure, new request, actual transfer, claims.csv, report.md, Skill or submission output is produced.')]}


def reconcile(run, normalized, validated, output, through_batch=None):
    run, normalized, validated, output = [p.resolve() for p in (run, normalized, validated, output)]
    if output.exists():
        raise FileExistsError('Refusing existing reconciliation output: ' + str(output))
    if any(output.is_relative_to(p) for p in (run, normalized, validated)):
        raise ValueError('Output must be outside retained evidence directories')
    doc, report, validation = load_verified(run, normalized, validated)
    result = evaluate(doc, report, validation, through_batch)
    result['input_bindings'] = deepcopy(validation['input_bindings']) + [
        {'path': str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p), 'sha256': v.digest(p.read_bytes())}
        for p in (validated / 'findings.v1.json', ROOT / 'reconciliation/reconcile.py')]
    admitted = [e for e in result['finance_events'] if e['admission_status'] == 'admitted']
    settled = sum(e['amount_cents'] for e in admitted if e['kind'] == 'settled')
    refunded = sum(e['amount_cents'] for e in admitted if e['kind'] == 'refund')
    result['summary'] = {'finance_deliveries': len(result['finance_deliveries']), 'distinct_finance_events': len(result['finance_events']),
        'admitted_finance_events': len(admitted), 'admitted_event_type_counts': dict(Counter(e['kind'] for e in admitted)),
        'repeated_finance_deliveries': sum(d['classification'] == 'repeated_delivery' for d in result['finance_deliveries']),
        'unresolved_finance_events': len(result['finance_events']) - len(admitted), 'accepted_requests': sum(r['acceptance_status'] == 'admitted' for r in result['requests']),
        'observed_request_references': len(result['requests']),
        'original_accepted_cents': sum(r['original_accepted_cents'] for r in result['requests']) if all(r['original_accepted_cents'] is not None for r in result['requests']) else None,
        'current_accepted_cents': sum(r['accepted_cents'] for r in result['requests']) if all(r['accepted_cents'] is not None for r in result['requests']) else None,
        'admitted_settled_cents': settled, 'admitted_refund_cents': refunded, 'admitted_net_cents': settled - refunded,
        'claim_revisions': len(result['claims']), 'current_claims': sum(c['current_at_batch'] for c in result['claims']),
        'expense_occurrences': sum(len(c['expenses']) for c in result['claims']),
        'finance_batch_views': len(result['batch_views']), 'business_cancellation_processes': len(result['travel_cancellations']),
        'normalization_diagnostic_count': len(report['issues']), 'unresolved_item_count': len(result['unresolved_items'])}
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'reconciliation.v1.json').open('xb') as stream:
        stream.write(v.encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('run', 'normalized', 'validated', 'output'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--through-batch', type=int)
    args = parser.parse_args()
    try:
        result = reconcile(args.run, args.normalized, args.validated, args.output, args.through_batch)
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc)); return 1
    print(json.dumps(result['summary'], sort_keys=True))
    return 2 if result['unresolved_items'] or result['validation_global_findings'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

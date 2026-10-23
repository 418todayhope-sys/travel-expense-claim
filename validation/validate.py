"""Deterministic Scope A increment 3 over verified retained normalization.

Public evaluate() evaluates in memory, also reading the preserved Decision 001
for its source hash; callers may use isolated synthetic documents in tests.
The CLI always verifies all retained inputs before evaluating or writing findings.
"""
from __future__ import annotations

import argparse
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
POLICY = 'user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.txt'
PROVENANCE = 'user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.provenance.json'
INTERVIEW = 'interviews/project-d-travel-expense-claim-20261020-1419(1).md'
DECISION = 'decisions/decision-001-correction-finance-hold.md'
ASSIGNMENT = 'validation/references/assignment-captured-20261016.txt'
POLICY_HASH = '04d8121a91986dc0839094b5e7f574c44f6261c60c1c3ba9aeeee1c279ee5993'
CASE_DATE = date(2026, 11, 15)
ZONE = ZoneInfo('Europe/Amsterdam')
ROLE_FIELDS = {'administration': 'Administration reviewer', 'budget_owner': 'Budget owner',
               'supervisor': 'Supervisor', 'director': 'Director'}
RULE_LINES = {'evidence': [12], 'arithmetic': list(range(13, 19)), 'permit': [19], 'filing': [20],
              'roles': [19, 21, 22], 'freshness': [22, 23], 'shared_cost': [24],
              'cancellation': [28, 29, 30, 31], 'finance_hold': [23, 26, 31], 'clock': [11]}


def digest(body):
    return hashlib.sha256(body).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def number(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except InvalidOperation:
        return None


def day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def instant(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt if dt.utcoffset() is not None and dt.utcoffset().total_seconds() == 0 else None
    except (AttributeError, ValueError):
        return None


def local_day(value):
    dt = instant(value)
    return dt.astimezone(ZONE).date() if dt else None


def deadline(end):
    """Two calendar months, inclusive, clamping the day to month end."""
    end = day(end)
    if end is None:
        return None
    index = end.year * 12 + end.month - 1 + 2
    year, month = index // 12, index % 12 + 1
    return date(year, month, min(end.day, monthrange(year, month)[1]))


def cents(amount, rate):
    return int((amount * rate).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) * 100)


def status(findings):
    values = {f['status'] for f in findings}
    return 'blocked' if 'blocked' in values else 'unresolved' if 'unresolved' in values else 'supported'


def finding(code, state, reason, refs, rule, owner='Administration', **extra):
    return {'code': code, 'status': state, 'reason': reason, 'owner': owner,
            'source_refs': sorted(set(refs)), 'rule_ref': 'policy:' + rule,
            'resolution_needed': None if state == 'supported' else reason, **extra}


def rows(doc, tab):
    return doc['workbook'][tab]['rows']


def unique(items):
    return items[0] if len(items) == 1 else None


def visible(row, batch):
    value = row['values'].get('Arrival batch')
    return isinstance(value, int) and 1 <= value <= batch


def cancellations(doc, batch):
    """Validate business scope and authority, retaining deliveries; no event admission."""
    processes, global_events = defaultdict(list), defaultdict(list)
    for row in rows(doc, 'Travel cancellations'):
        if visible(row, batch):
            processes[row['values'].get('Cancellation reference')].append(row)
            global_events[row['values'].get('Cancellation activity reference')].append(row)
    result = []
    for ident, deliveries in sorted(processes.items(), key=lambda p: str(p[0])):
        fs, events = [], defaultdict(list)
        refs = [r['record_id'] for r in deliveries]
        for row in deliveries:
            events[row['values'].get('Cancellation activity reference')].append(row)
        distinct = []
        for event, copies in sorted(events.items(), key=lambda p: str(p[0])):
            payloads = [{k: v for k, v in r['values'].items() if k != 'Arrival batch'} for r in global_events[event]]
            if not event or any(p != payloads[0] for p in payloads):
                fs.append(finding('cancellation_replay', 'unresolved', 'Missing event ID or conflicting immutable payload.',
                                  [r['record_id'] for r in copies], 'cancellation', 'Supervisor'))
            distinct.append(copies[0])
        requests = [r for r in distinct if r['values'].get('Action') == 'requested']
        confirms = [r for r in distinct if r['values'].get('Action') == 'confirmed']
        base = (requests or distinct)[0]['values']
        targets = [r for r in rows(doc, 'Trips') if r['values']['Trip reference'] == base.get('Trip reference')
                   and r['values']['Trip revision'] == base.get('Trip revision')]
        trip = unique(targets)
        person = unique([r for r in rows(doc, 'People') if trip and
                         r['values']['Employee ID'] == trip['values']['Employee ID']])
        target_keys = ['Cancelled subject', 'Trip reference', 'Trip revision', 'Permit reference', 'Permit revision']
        target_ok = bool(trip and person and base.get('Cancelled subject') in ('trip', 'permit'))
        if target_ok:
            tv = trip['values']
            target_ok = (base.get('Permit reference') == tv['Permit reference'] and
                         base.get('Permit revision') == tv['Permit revision'] and
                         (base['Cancelled subject'] != 'permit' or bool(tv['International'] and tv['Permit reference'])))
        if not target_ok or any(any(r['values'].get(k) != base.get(k) for k in target_keys) for r in distinct):
            fs.append(finding('cancellation_target', 'unresolved', 'Target must match one exact trip and associated permit revision.', refs, 'cancellation', 'Supervisor'))
        if len(requests) != 1 or len(confirms) > 1 or len(requests) + len(confirms) != len(distinct):
            fs.append(finding('cancellation_process', 'unresolved', 'Require one initiation and at most one distinct confirmation.', refs, 'cancellation', 'Supervisor'))
        request = unique(requests)
        confirm = unique(confirms)
        valid_request = False
        if request and person:
            v = request['values']
            when = local_day(v.get('Activity time (UTC)'))
            valid_request = (v.get('Acting employee or supervisor') == person['values']['Employee ID']
                             and not v.get('Initiation activity reference') and not v.get('Effective time (UTC)')
                             and bool(v.get('Business reason')) and when is not None and when <= CASE_DATE)
            if not valid_request:
                fs.append(finding('cancellation_initiation', 'unresolved', 'Initiation actor, UTC time, reason or empty confirmation fields invalid.', refs, 'cancellation', 'Supervisor'))
        if confirm:
            v = confirm['values']
            ct, rt = instant(v.get('Activity time (UTC)')), instant(request['values'].get('Activity time (UTC)')) if request else None
            valid_confirm = (valid_request and person and ct and rt and ct > rt
                             and ct.astimezone(ZONE).date() <= CASE_DATE
                             and v.get('Effective time (UTC)') == v.get('Activity time (UTC)')
                             and v.get('Initiation activity reference') == request['values']['Cancellation activity reference']
                             and v.get('Acting employee or supervisor') == person['values']['Supervisor']
                             and bool(v.get('Business reason')))
            if not valid_confirm:
                fs.append(finding('cancellation_confirmation', 'unresolved', 'Confirmation requires the directory supervisor, matching initiation, strictly later UTC time and own-time effect.', refs, 'cancellation', 'Supervisor'))
        state = 'unresolved' if fs else 'confirmed' if confirm else 'requested'
        fs.append(finding('cancellation_scope', 'supported' if state != 'unresolved' else 'unresolved',
                          'Business scope only: permit-only leaves trip active; trip cancellation retires its linked permit. No Finance effect.', refs, 'cancellation', 'Supervisor'))
        result.append({'cancellation_id': ident, 'business_state': state,
                       'trip_id': base.get('Trip reference'), 'trip_revision': base.get('Trip revision'),
                       'permit_id': base.get('Permit reference'), 'permit_revision': base.get('Permit revision'),
                       'target_type': base.get('Cancelled subject'),
                       'confirmed_at': confirm['values'].get('Activity time (UTC)') if confirm and state == 'confirmed' else None,
                       'source_refs': refs, 'delivery_count': len(deliveries), 'event_count': len(distinct), 'findings': fs})
    return result


def business_disposition(doc, claim, claim_review):
    """Retained business evidence only; never payment or closure authority.

    Use the existing exact-revision/actor/packet admission and role selection.
    Missing replies, invalid imports and ambiguous current replies supply no
    disposition. Withdrawal is scoped to the explicitly observed revision.
    """
    selected = set((claim_review or {}).get('selected_decisions', {}).values())
    imports = (claim_review or {}).get('imports', [])
    rejected = [e for e in imports if e['status'] == 'supported'
                and e['outcome'] == 'reject' and e['decision_id'] in selected]
    ambiguous = any(e['status'] == 'supported' and e['outcome'] == 'reject'
                    and any(role not in (claim_review or {}).get('selected_decisions', {}) for role in e['roles'])
                    for e in imports)
    withdrawn = claim.get('status_observed') == 'withdrawn'
    reason = claim.get('raw_fields', {}).get('Claim reason')
    refs = {claim['record_id']}
    decisions = []
    for entry in rejected:
        decisions.append(entry['decision_id'])
        refs.add(entry['record_id'])
        refs.update(ref for f in entry['findings'] for ref in f['source_refs'])
    value = None
    explanation = 'No unambiguous explicit withdrawal or admitted current rejection; no disposition inferred from missing evidence.'
    if ambiguous or (withdrawn and rejected):
        explanation = 'Conflicting or ambiguous business-disposition evidence requires clarification; no terminal disposition selected.'
        refs.update(e['record_id'] for e in imports if e['status'] == 'supported')
    elif withdrawn and isinstance(reason, str) and reason.strip():
        value, explanation = 'withdrawn', reason
    elif rejected:
        value = 'rejected'
        explanation = '; '.join(sorted({r['values']['Reason'] for r in rows(doc, 'Review ledger')
                                       if r['record_id'] in {e['record_id'] for e in rejected}}))
    return {'value': value, 'evidence_status': 'supported' if value else 'unresolved',
            'reason': explanation, 'source_refs': sorted(refs), 'decision_ids': sorted(decisions),
            'scope': 'This claim revision in retained evidence; not payment authorization or financial closure.'}


def review(doc, claim, trip, person, batch, subject_type, amount, cancel_context=(), evidence_dates=()):
    """Validate supplied decisions and packets; never supply discretionary judgment."""
    tv, pv = trip['values'], person['values']
    subject = claim['claim_id'] if subject_type == 'claim' else tv['Permit reference']
    revision = claim['revision'] if subject_type == 'claim' else tv['Permit revision']
    required = ['administration', 'budget_owner', 'supervisor']
    if amount is not None and amount > Decimal('1000'):
        required.append('director')
    relevant = [r for r in rows(doc, 'Review ledger') if visible(r, batch)
                and r['values'].get('Subject type') == subject_type and r['values'].get('Subject reference') == subject]
    imports, candidates = [], defaultdict(list)
    scoped_budget = [r for r in rows(doc, 'Budget') if all(r['values'].get(k) == pv.get(k) for k in ('Department', 'Project', 'Budget period'))]
    expected_budget = {r['values']['Ledger reference'] for r in scoped_budget}
    for row in relevant:
        v, fs = row['values'], []
        refs = [row['record_id'], trip['record_id'], person['record_id']]
        def add(code, state, reason, rule='roles', more=()):
            fs.append(finding(code, state, reason, refs + list(more), rule, v.get('Reviewer') or 'Administration'))
        if v.get('Revision') != revision:
            add('review_revision', 'blocked', 'Historical revision cannot authorize this subject/version.', 'freshness')
        if subject_type == 'claim' and v.get('Arrival batch', 0) < claim['arrival_batch']:
            add('review_arrival', 'blocked', 'Reply arrived before this claim revision.', 'freshness')
        roles = v.get('Review roles') or []
        role_ok = (bool(roles) and len(set(roles)) == len(roles)
                   and all(role in ROLE_FIELDS and pv.get(ROLE_FIELDS[role]) == v.get('Reviewer') for role in roles)
                   and (len(roles) == 1 or set(roles) == {'budget_owner', 'supervisor'}))
        add('review_authority', 'supported' if role_ok else 'blocked',
            'Only directory actors may fill their roles; only budget owner/supervisor may share a response.')
        time = instant(v.get('Decision time (UTC)'))
        if time is None or time.astimezone(ZONE).date() > CASE_DATE:
            add('review_time', 'unresolved', 'Decision time missing, non-UTC or future.', 'clock')
        if evidence_dates:
            fresh = time is not None and all(date is not None and date <= time.astimezone(ZONE).date()
                                             for date, _ in evidence_dates)
            add('review_evidence_freshness', 'supported' if fresh else 'blocked',
                'Receipt and settled merchant evidence must be dated on or before this review; subsequent valid reviews are required for later evidence.',
                'freshness', [ref for _, ref in evidence_dates])
        versions = v.get('Source revisions') or []
        if not {'POL-2026.2', 'SRC-D-3'}.issubset(versions) or any(t.startswith('POL-') and t != 'POL-2026.2' for t in versions) or any(t.startswith('SRC-') and t != 'SRC-D-3' for t in versions):
            add('review_sources', 'blocked', 'Policy or retained business-source revision is missing or stale.', 'freshness')
        else:
            add('review_sources', 'supported', 'Policy and printed source revision match retained text; opaque package tokens remain a global unresolved definition.', 'freshness')
        duplicates = [r for r in rows(doc, 'Review ledger') if visible(r, batch) and r['values'].get('Decision reference') == v.get('Decision reference')]
        if len(duplicates) != 1:
            add('review_identity', 'unresolved', 'Decision reference is not unique; no silent selection.', 'freshness')
        packets = [r for r in rows(doc, 'Review packets') if r['values'].get('Decision reference') == v.get('Decision reference')]
        packet = unique(packets)
        if not packet:
            add('review_packet', 'unresolved', 'Exactly one bound review packet is required.', more=[r['record_id'] for r in packets])
        else:
            p = packet['values']; refs.append(packet['record_id'])
            expected = {'Employee ID': claim['employee_id'], 'Trip reference': claim['trip_id'],
                        'Trip revision': claim['trip_revision'], 'Permit reference': tv['Permit reference'],
                        'Permit revision': tv['Permit revision'], 'Policy revision': 'POL-2026.2'}
            bad = [k for k, value in expected.items() if p.get(k) != value]
            for field in ('Business purpose', 'Client', 'Schedule coverage', 'Alternatives considered'):
                if p.get(field) != tv.get(field) or not p.get(field):
                    bad.append(field)
            if subject_type == 'claim' and set(p.get('Expense references') or []) != {e['expense_id'] for e in claim['expenses']}:
                bad.append('Expense references')
            if subject_type == 'permit' and number(p.get('Reviewed estimate (EUR)')) != number(tv.get('Estimate (EUR)')):
                bad.append('Reviewed estimate (EUR)')
            if 'budget_owner' in roles and (not expected_budget or set(p.get('Budget record references') or []) != expected_budget):
                bad.append('Budget record references')
            if 'director' in roles and not p.get('Budget owner position'):
                bad.append('Budget owner position')
            for cancel in cancel_context:
                if cancel['cancellation_id'] not in (p.get('Travel cancellation references') or []) or not time or time <= instant(cancel['confirmed_at']):
                    bad.append('Travel cancellation references/post-confirmation time')
            # References to an unrelated or unconfirmed cancellation cannot establish context.
            if set(p.get('Travel cancellation references') or []) != {c['cancellation_id'] for c in cancel_context}:
                bad.append('Travel cancellation references')
            add('review_packet', 'blocked' if bad else 'supported',
                'Packet differs from current evidence: ' + ', '.join(sorted(set(bad))) if bad else 'Packet matches exact current subject evidence and role context.', 'freshness')
        outcome = v.get('Outcome')
        if outcome not in ('approve', 'return', 'reject') or not v.get('Reason') or (outcome == 'return' and not v.get('Repair requested')):
            add('review_outcome', 'unresolved', 'Outcome needs an explicit reason and a concrete repair request for return.')
        usable = status(fs) == 'supported'
        entry = {'decision_id': v.get('Decision reference'), 'record_id': row['record_id'],
                 'revision': v.get('Revision'), 'outcome': outcome, 'roles': roles,
                 'source_revisions': versions,
                 'decision_time': v.get('Decision time (UTC)'), 'status': status(fs), 'findings': fs}
        imports.append(entry)
        if usable:
            for role in roles:
                candidates[role].append(entry)
    findings, selections = [], {}
    for role in required:
        items = candidates[role]
        latest_time = max((e['decision_time'] for e in items), default=None)
        latest = [e for e in items if e['decision_time'] == latest_time]
        chosen = unique(latest)
        if chosen:
            selections[role] = chosen['decision_id']
            state = 'supported' if chosen['outcome'] == 'approve' else 'blocked'
            reason = 'Supplied current approve response.' if state == 'supported' else 'Supplied ' + chosen['outcome'] + ' response; retain reason/repair in bound ledger.'
            refs = [chosen['record_id']]
        else:
            state, reason, refs = 'unresolved', 'Missing or ambiguous valid current response; old revisions and invalid packets satisfy no role.', [r['record_id'] for r in relevant]
        findings.append(finding('review_' + role, state, reason, refs + [claim['record_id'], person['record_id']], 'roles', pv.get(ROLE_FIELDS[role]) or 'Administration'))
    if amount is None:
        findings.append(finding('director_threshold', 'unresolved', 'Reviewed amount unknown: director requirement cannot be determined.', [claim['record_id']], 'roles', pv['Director']))
    if subject_type == 'claim':
        findings.append(finding('reviewed_entitlement_binding', 'unresolved', 'Packets have no reviewed claim entitlement field or exception-reference field; amount/exception seen by reviewers cannot be independently matched.', [e['record_id'] for e in imports] + [claim['record_id']], 'freshness'))
    return {'subject_type': subject_type, 'subject_id': subject, 'revision': revision,
            'required_roles': required, 'selected_decisions': selections, 'findings': findings,
            'imports': imports, 'status': status(findings)}


def exception_for(claim, expense, person):
    ex = claim.get('finance_exception')
    if not ex or ex.get('expense_id') != expense['expense_id']:
        return None, []
    raw = ex['raw_fields']
    tokens = re.split(r'[,;\n]+', ex.get('covered_issues_observed') or '')
    coverage = [re.sub(r'\s+', '_', t.strip().lower()) for t in tokens if t.strip().lower() != 'none' and t.strip()]
    allowed = number(ex.get('allowed_original_amount_observed'))
    valid = (person and ex.get('actor') == person['values'].get('Finance officer')
             and ex.get('claim_id') == claim['claim_id'] and ex.get('revision') == claim['revision']
             and allowed is not None and allowed >= 0 and bool(raw.get('Exception reason'))
             and 'Covered issues' in raw and set(coverage) <= {'late_filing', 'late_permit', 'permit_unapproved', 'travel_cancellation'})
    f = finding('finance_exception', 'supported' if valid else 'blocked',
                'Explicit Finance replacement amount, reason, cost and exact claim/revision binding.' if valid else 'Exception actor, binding, amount, reason or coverage invalid.',
                [claim['record_id']] + ([person['record_id']] if person else []), 'arithmetic', 'Finance',
                coverage=coverage, replacement_allowed_original=str(allowed) if allowed is not None else None)
    return (dict(ex, coverage=coverage) if valid else None), [f]


def expense_findings(doc, claim, e, trip, person, permission, affected):
    refs, fs = [claim['record_id'], e['record_id']], []
    def add(code, state, reason, rule='evidence', more=(), **extra):
        item = finding(code, state, reason, refs + list(more), rule, claim['employee_id'], **extra)
        fs.append(item); return item
    gross = number(e['original_amount'])
    receipts = [r for r in doc['receipts'] if r['receipt_id'] == e['receipt_id']]
    receipt = unique(receipts)
    receipt_ok = receipt and all(receipt.get(k) == value for k, value in {
        'expense_id': e['expense_id'], 'employee_id': claim['employee_id'], 'trip_id': claim['trip_id'], 'currency': e['currency']}.items()) and number(receipt['gross_amount']) == gross
    add('receipt_identity', 'supported' if receipt_ok else 'unresolved', 'One matching receipt with employee/trip/cost/currency/gross identity required.', more=[r['record_id'] for r in receipts])
    if receipt:
        issued = day(receipt.get('issued_date'))
        add('receipt_date', 'supported' if issued and issued <= CASE_DATE else 'unresolved',
            'Receipt issue date must be known and observed by the supplied case date.', 'clock', [receipt['record_id']])
    payments = [r for r in rows(doc, 'Merchant payments') if all(r['values'].get(k) == v for k, v in {
        'Expense reference': e['expense_id'], 'Receipt reference': e['receipt_id'], 'Employee ID': claim['employee_id'],
        'Trip reference': claim['trip_id'], 'Currency': e['currency']}.items()) and number(r['values'].get('Gross amount')) == gross]
    payment = unique(payments)
    paid = day(payment['values'].get('Paid date')) if payment else None
    paid_ok = bool(payment and payment['values'].get('Payment status') == 'settled' and paid and paid.year == 2026 and paid <= CASE_DATE)
    add('merchant_payment', 'supported' if paid_ok else 'unresolved',
        'Matching settled merchant evidence with a 2026 payment date.' if paid_ok else 'Missing, ambiguous, unsettled or invalid-date merchant-payment evidence; Finance cannot waive it.', more=[r['record_id'] for r in payments])
    category = receipt['category'] if receipt_ok else None
    allowed = None
    if category == 'personal':
        allowed = Decimal(0)
        add('category', 'blocked', 'Personal purchase has zero entitlement; preserve gross purchase.', 'arithmetic')
    elif category in ('transport', 'conference', 'lodging', 'meals'):
        add('category', 'supported', 'Eligible category; no automatic allowance.', 'arithmetic')
        units = receipt['units']
        unit_ok = isinstance(units, int) and not isinstance(units, bool) and units > 0
        add('documented_units', 'supported' if unit_ok else 'unresolved', 'Documented units must be positive integers.', 'arithmetic', [receipt['record_id']])
        if gross is not None and gross >= 0 and unit_ok:
            if category in ('transport', 'conference'):
                allowed = gross
                add('category_cap', 'supported', 'Transport/conference use supported gross with no category cap.', 'arithmetic')
            else:
                caps = [r for r in rows(doc, 'Caps') if trip and paid and
                        r['values'].get('Destination') == trip['values']['Destination'] and
                        r['values'].get('Category') == category and r['values'].get('Currency') == e['currency'] and
                        day(r['values'].get('Effective from')) and day(r['values'].get('Effective to')) and
                        day(r['values']['Effective from']) <= paid <= day(r['values']['Effective to'])]
                cap = unique(caps)
                limit = number(cap['values']['Amount per unit']) if cap else None
                if limit is not None and limit >= 0:
                    allowed = min(gross, limit * units)
                add('category_cap', 'supported' if allowed is not None else 'unresolved', 'Cap × documented units, matched on destination, currency and inclusive payment date; missing/overlapping cap is unresolved.', 'arithmetic', [r['record_id'] for r in caps])
    else:
        add('category', 'unresolved', 'Unknown or unsupported category; no invented zero.', 'arithmetic')
    if gross is None or gross < 0:
        add('gross_amount', 'unresolved', 'Gross purchase must be a known nonnegative decimal.', 'arithmetic')
    ex, exfs = exception_for(claim, e, person); fs.extend(exfs)
    base_allowed = allowed
    # An exception does not define an unknown category/cap/rate or replace missing evidence.
    if ex and allowed is not None and category != 'personal':
        allowed = number(ex['allowed_original_amount_observed'])
    original_date = day(e['first_submitted_date'])
    earlier = [(c, old) for c in doc['claims'] for old in c['expenses']
               if c['claim_id'] == claim['claim_id'] and c['revision'] < claim['revision'] and old['expense_id'] == e['expense_id']
               and (old['receipt_id'], number(old['original_amount']), old['currency'], c['trip_id'], c['employee_id']) ==
               (e['receipt_id'], number(e['original_amount']), e['currency'], claim['trip_id'], claim['employee_id'])]
    original_dates = {old['first_submitted_date'] for c, old in earlier}
    if original_dates and original_dates != {e['first_submitted_date']}:
        add('initial_filing_preserved', 'blocked', 'Unchanged expense must retain its original first-submission date.', 'filing', [c['record_id'] for c, old in earlier])
    due = deadline(trip['values']['End date']) if trip else None
    date_ok = bool(original_date and due and paid and paid <= original_date <= CASE_DATE and day(claim['submitted_date']) and original_date <= day(claim['submitted_date']))
    add('filing_dates', 'supported' if date_ok else 'unresolved', 'Use line first submission after payment, never import time; future or inconsistent dates remain unresolved.', 'filing', [trip['record_id']] if trip else [])
    def issue(code, original_state, reason, rule, cancellation_id=None):
        covered = bool(ex and code in ex['coverage'] and (code != 'travel_cancellation' or ex.get('cancellation_id') == cancellation_id))
        return add(code, 'supported' if covered else original_state,
                   reason + (' Explicit bound Finance exception covers reimbursement eligibility only.' if covered else ''),
                   rule, original_status=original_state, exception_ref=claim['record_id'] if covered else None,
                   cancellation_id=cancellation_id)
    if original_date and due:
        if original_date > due:
            issue('late_filing', 'blocked', 'Submission exceeds inclusive two-calendar-month deadline.', 'filing')
        else:
            add('late_filing', 'supported', 'Within inclusive filing deadline.', 'filing')
    if permission['code'] != 'domestic_permit':
        code, state, reason = permission['code'], permission['status'], permission['reason']
        if code in ('late_permit', 'permit_unapproved') and state != 'supported':
            issue(code, state, reason, 'permit')
        else:
            add(code, state, reason, 'permit', permission['source_refs'])
    for cancel in affected:
        refs.extend(cancel['source_refs'])
        if cancel['business_state'] == 'confirmed':
            issue('travel_cancellation', 'blocked', 'Confirmed business cancellation requires exact Finance cost disposition and fresh cancellation-aware claim reviews.', 'cancellation', cancel['cancellation_id'])
            cancel_day = local_day(cancel['confirmed_at'])
            if paid and paid >= cancel_day:
                add('payment_cancellation_order', 'unresolved', 'Payment is on/after cancellation day; date-only payment cannot establish valid pre-cancellation arrangement authority.', 'cancellation')
        else:
            add('travel_cancellation_pending', 'blocked' if cancel['business_state'] == 'requested' else 'unresolved', 'Affected cancellation awaits valid supervisor determination.', 'cancellation')
    rate = Decimal(1) if e['currency'] == 'EUR' else None
    rates = []
    if e['currency'] != 'EUR':
        rates = [r for r in rows(doc, 'FX') if paid and r['values'].get('Rate date') == paid.isoformat() and r['values'].get('Currency') == e['currency']]
        fx = unique(rates)
        rate = number(fx['values']['EUR per currency unit']) if fx else None
    if rate is not None and rate <= 0:
        rate = None
    add('fx_rounding', 'supported' if rate is not None else 'unresolved', 'EUR uses 1; other currencies require one exact payment-date Finance rate. Round each converted line half-up to cents.', 'arithmetic', [r['record_id'] for r in rates])
    supported_amount = paid_ok and receipt_ok and allowed is not None and rate is not None
    return {'expense_id': e['expense_id'], 'expense_record_id': e['record_id'], 'gross_original': e['original_amount'],
            'currency': e['currency'], 'category': category, 'paid_date': paid.isoformat() if paid else None,
            'first_submitted_date': e['first_submitted_date'],
            'filing_deadline': due.isoformat() if due else None,
            'base_allowed_original': str(base_allowed) if base_allowed is not None else None,
            'allowed_original': str(allowed) if supported_amount else None,
            'calculated_allowed_cents': cents(allowed, rate) if supported_amount else None,
            'status': status(fs), 'findings': fs}


def permit_findings(doc, claim, trip, person, batch, affected):
    tv = trip['values']; refs = [trip['record_id'], person['record_id']]
    if tv['International'] is False:
        return finding('domestic_permit', 'supported', 'Domestic travel requires no permit.', refs, 'permit'), None
    if tv['International'] is not True or not tv.get('Permit reference') or not tv.get('Permit revision'):
        return finding('permit_unapproved', 'blocked', 'International travel needs an explicitly identified exact permit revision.', refs, 'permit'), None
    reviewed = review(doc, claim, trip, person, batch, 'permit', number(tv.get('Estimate (EUR)')))
    rolefs = reviewed['findings']
    if any(f['status'] != 'supported' for f in rolefs):
        return finding('permit_unapproved', 'blocked', 'No complete valid approved permit role set; claim approvals cannot substitute.', refs, 'permit'), reviewed
    selected = set(reviewed['selected_decisions'].values())
    times = [e['decision_time'] for e in reviewed['imports'] if e['decision_id'] in selected]
    commitment = day(tv.get('First commitment date'))
    payment_days = [day(r['values'].get('Paid date')) for r in rows(doc, 'Merchant payments')
                    if r['values'].get('Trip reference') == claim['trip_id'] and r['values'].get('Employee ID') == claim['employee_id']
                    and r['values'].get('Payment status') == 'settled']
    commitments = [d for d in [commitment] + payment_days if d]
    first = min(commitments) if commitments else None
    approved_day = max(local_day(t) for t in times)
    code, state = ('late_permit', 'blocked') if first and approved_day > first else ('permit_timing', 'unresolved') if first and approved_day == first else ('permit_timing', 'supported')
    reason = 'Permit role approvals must precede first arrangement/payment commitment; same-day date-only ordering is unresolved.'
    # Later cancellations do not retrospectively turn timely permission into permit_unapproved.
    for cancel in affected:
        if cancel['business_state'] == 'confirmed' and any(instant(t) >= instant(cancel['confirmed_at']) for t in times):
            state, code, reason = 'blocked', 'permit_unapproved', 'Approval after retirement cannot restore this cancelled travel basis.'
    return finding(code, state, reason, refs + [e['record_id'] for e in reviewed['imports']], 'permit'), reviewed


def ordinary_review_binding(doc, claim, reviewed, expenses, findings, diagnostics):
    """Narrow retained-evidence join, not a new human decision or package waiver.

    Interview 294/302 confirms entitlement through current role approvals.
    Restrict this path to one unchanged domestic purchase with no exception.
    Corrections, shared costs, ambiguous/invalid replies and returns fail closed.
    """
    family = [c for c in doc['claims'] if c['claim_id'] == claim['claim_id']]
    costs = claim['expenses']
    if (len(family) != 1 or claim['revision'] != 1 or len(costs) != 1 or claim.get('finance_exception')
            or claim.get('related_claim_ids') or claim.get('status_observed') != 'submitted'
            or not reviewed or diagnostics or status(findings) != 'supported'
            or not any(f['code'] == 'domestic_permit' for f in findings)
            or any(e['status'] != 'supported' for e in expenses)
            or expenses[0]['calculated_allowed_cents'] is None
            or expenses[0]['calculated_allowed_cents'] <= 0):
        return False
    if sum(e['expense_id'] == costs[0]['expense_id'] for c in doc['claims'] for e in c['expenses']) != 1:
        return False
    roles = reviewed['required_roles']
    # Retain earlier reviews as history, excluding only otherwise-valid approvals
    # that are provably stale against the supporting evidence dates.
    imports = [e for e in reviewed['imports'] if not (
        e['revision'] == claim['revision'] and e['outcome'] == 'approve'
        and any(f['code'] == 'review_evidence_freshness' and f['status'] == 'blocked' for f in e['findings'])
        and all(f['status'] == 'supported' for f in e['findings'] if f['code'] != 'review_evidence_freshness'))]
    return (all(e['revision'] == claim['revision'] and e['status'] == 'supported'
                and e['outcome'] == 'approve' for e in imports)
            and all(sum(role in e['roles'] for e in imports) == 1 for role in roles)
            and status([f for f in reviewed['findings'] if f['code'] != 'reviewed_entitlement_binding']) == 'supported')


def evaluate(doc, normalization_report, through_batch=4, *, ordinary_claim_ids=()):
    ordinary_claim_ids = sorted(set(ordinary_claim_ids))
    if set(ordinary_claim_ids) - {c['claim_id'] for c in doc['claims']}:
        raise ValueError('Ordinary review selection names an unknown claim')
    if not isinstance(through_batch, int) or isinstance(through_batch, bool) or through_batch < 1:
        raise ValueError('through_batch must be a positive integer')
    supplied_batches = {c['arrival_batch'] for c in doc['claims']}
    supplied_batches.update(r['values']['Arrival batch'] for tab in ('Review ledger', 'Travel cancellations', 'Finance activity')
                            for r in rows(doc, tab) if isinstance(r['values'].get('Arrival batch'), int))
    if through_batch not in supplied_batches:
        raise ValueError('Requested batch is not present in the retained package')
    cancel_records = cancellations(doc, through_batch)
    available = [c for c in doc['claims'] if c['arrival_batch'] <= through_batch]
    latest = {c['claim_id']: max(x['revision'] for x in available if x['claim_id'] == c['claim_id']) for c in available}
    claim_results = []
    for c in available:
        fs = []
        trips = [r for r in rows(doc, 'Trips') if (r['values'].get('Trip reference'), r['values'].get('Trip revision'), r['values'].get('Employee ID')) == (c['trip_id'], c['trip_revision'], c['employee_id'])]
        people = [r for r in rows(doc, 'People') if r['values']['Employee ID'] == c['employee_id']]
        trip, person = unique(trips), unique(people)
        fs.append(finding('claim_identity', 'supported' if trip and person else 'unresolved', 'Require one employee directory entry and exact trip/employee/revision.', [c['record_id']] + [r['record_id'] for r in trips + people], 'evidence'))
        if c.get('finance_exception') and c['finance_exception'].get('expense_id') not in {e['expense_id'] for e in c['expenses']}:
            fs.append(finding('exception_cost_binding', 'blocked', 'Exception references no expense in this claim revision.', [c['record_id']], 'arithmetic', 'Finance'))
        affected = [r for r in cancel_records if (r['trip_id'], r['trip_revision']) == (c['trip_id'], c['trip_revision'])]
        confirmed = [r for r in affected if r['business_state'] == 'confirmed']
        arrangement = ('unresolved' if any(r['business_state'] == 'unresolved' for r in affected)
                       else 'retired_trip' if any(r['target_type'] == 'trip' for r in confirmed)
                       else 'retired_permit_trip_active' if confirmed
                       else 'paused' if affected else 'no_observed_cancellation')
        permission, permit = (permit_findings(doc, c, trip, person, through_batch, affected) if trip and person else
                              (finding('permit_unapproved', 'unresolved', 'Trip/directory identity unresolved.', [c['record_id']], 'permit'), None))
        fs.append(permission)
        if trip:
            start, end = day(trip['values'].get('Start date')), day(trip['values'].get('End date'))
            fs.append(finding('trip_dates', 'supported' if start and end and start <= end else 'unresolved', 'Trip dates must be present and ordered; filing uses original planned end.', [trip['record_id']], 'filing'))
        lines = [expense_findings(doc, c, e, trip, person, permission, affected) for e in c['expenses']]
        total = sum(e['calculated_allowed_cents'] for e in lines) if lines and all(e['calculated_allowed_cents'] is not None for e in lines) else None
        evidence_dates = []
        if c['claim_id'] in ordinary_claim_ids:
            for expense in c['expenses']:
                evidence_dates.extend((day(receipt.get('issued_date')), receipt['record_id'])
                                      for receipt in doc['receipts'] if receipt['receipt_id'] == expense['receipt_id'])
                evidence_dates.extend((day(row['values'].get('Paid date')), row['record_id'])
                                      for row in rows(doc, 'Merchant payments')
                                      if row['values'].get('Expense reference') == expense['expense_id'])
        claim_review = review(doc, c, trip, person, through_batch, 'claim', Decimal(total) / 100 if total is not None else None, confirmed, evidence_dates) if trip and person else None
        prior = [x for x in available if x['claim_id'] == c['claim_id'] and x['revision'] < c['revision']]
        fs.append(finding('correction_recheck', 'supported', 'Full current-revision dependency recheck; no prior claim approval is inherited, including unchanged totals.', [c['record_id']] + [x['record_id'] for x in prior], 'freshness'))
        shared = {e['expense_id']: [x['record_id'] for x in available if x['claim_id'] != c['claim_id'] and any(old['expense_id'] == e['expense_id'] for old in x['expenses'])] for e in c['expenses']}
        for expense_id, others in shared.items():
            if others:
                fs.append(finding('prior_cost_obligation', 'unresolved', 'Shared cost identity ' + expense_id + ': retain gross eligibility; Finance obligation admission must establish exclusion before any incremental reimbursement.', [c['record_id']] + others, 'shared_cost', 'Finance'))
        finance_candidates = [r for r in rows(doc, 'Finance activity') if visible(r, through_batch) and r['values'].get('Claim reference') == c['claim_id']]
        if prior and finance_candidates:
            fs.append(finding('original_request_finance_hold', 'blocked', 'Correction with original-request Finance observations: hold pending explicit original-request resolution validation and current reviews. Candidate rows are not admitted or attributed to a revision.', [c['record_id'], 'decision:001'] + [r['record_id'] for r in finance_candidates], 'finance_hold', person['values']['Finance officer'] if person else 'Finance'))
        claim_diagnostics = [i for i in normalization_report['issues'] if i['record_id'] == c['record_id'] or i['record_id'].startswith(c['record_id'] + ':')]
        if (c['claim_id'] in ordinary_claim_ids and not affected
                and ordinary_review_binding(doc, c, claim_review, lines, fs, claim_diagnostics)):
            for f in claim_review['findings']:
                if f['code'] == 'reviewed_entitlement_binding':
                    f.update(status='supported', resolution_needed=None,
                             reason='Derived reviewed entitlement: sole unchanged purchase, exact current role approvals and matching packets; no exception or competing basis. No redundant numeric packet field is required.',
                             source_refs=sorted(set(f['source_refs'] + ['interview:ordinary_entitlement'] +
                                                   [ref for line in lines for x in line['findings'] for ref in x['source_refs']])))
            claim_review['status'] = status(claim_review['findings'])
        allfs = fs + [f for line in lines for f in line['findings']] + (claim_review['findings'] if claim_review else [])
        eligibility = [f for f in fs if f['code'] in ('claim_identity', 'trip_dates', 'exception_cost_binding')] + [f for line in lines for f in line['findings']]
        claim_results.append({'claim_id': c['claim_id'], 'revision': c['revision'], 'arrival_batch': c['arrival_batch'],
                              'current_at_batch': c['revision'] == latest[c['claim_id']], 'trip_id': c['trip_id'], 'trip_revision': c['trip_revision'],
                              'source_ref': c['record_id'], 'status': status(allfs), 'calculated_allowed_cents': total,
                              'business_disposition': business_disposition(doc, c, claim_review),
                              'eligibility_status': status(eligibility),
                              'approval_status': claim_review['status'] if claim_review else 'unresolved',
                              'travel_cancellation_scope': arrangement,
                              'amount_semantics': 'Gross policy calculation before prior-obligation exclusion; not an authorized or payable amount.',
                              'findings': fs, 'expenses': lines, 'claim_review': claim_review, 'permit_review': permit,
                              'cancellation_ids': [r['cancellation_id'] for r in affected],
                              'normalization_diagnostics': [i for i in normalization_report['issues'] if i['record_id'] == c['record_id'] or i['record_id'].startswith(c['record_id'] + ':')]})
    index = {}
    for c in doc['claims']:
        index[c['record_id']] = c['source']
        for e in c['expenses']:
            index[e['record_id']] = e['source']
    for r in doc['receipts']:
        index[r['record_id']] = r['source']
    for tab in doc['workbook'].values():
        for r in tab['rows']:
            index[r['record_id']] = r['source']
    for name, lines in RULE_LINES.items():
        index['policy:' + name] = {'path': POLICY, 'sha256': POLICY_HASH, 'lines': lines}
    index['decision:001'] = {'path': DECISION, 'sha256': digest((ROOT / DECISION).read_bytes())}
    global_findings = [
        finding('policy_provenance', 'unresolved', 'User-attested browser copy only; native Notion completeness and semantic source versions remain unverified.', ['policy:clock'], 'clock', 'Facilitator'),
        finding('review_version_token', 'unresolved', 'DW-D-2 is preserved as a supplied opaque decision-package token; no independent package-version definition is retained. POL-2026.2 and SRC-D-3 are checked against retained text, not certified native versions.', ['policy:freshness'], 'freshness', 'Facilitator'),
        finding('budget_completeness', 'unresolved', 'Packets must name the entire supplied scoped ledger. Completeness including accepted new Finance requests cannot be certified without the deferred Finance admission stage. Adequate funds never invent approval.', [r['record_id'] for r in rows(doc, 'Budget')], 'roles', 'Budget owner'),
        finding('assignment_access', 'unresolved', 'Original Notion assignment inaccessible; historical October 16 captured task used with current repository README/schema and explicit increment scope.', [], 'clock', 'Facilitator')]
    known_subjects = {('claim', c['claim_id'], c['revision']) for c in available}
    known_subjects.update(('permit', r['values']['Permit reference'], r['values']['Permit revision']) for r in rows(doc, 'Trips') if r['values']['Permit reference'])
    unmatched = [finding('unmatched_review', 'unresolved', 'Reply has no exact observed subject/revision; retained without authorization.', [r['record_id']], 'freshness')
                 for r in rows(doc, 'Review ledger') if visible(r, through_batch) and
                 (r['values'].get('Subject type'), r['values'].get('Subject reference'), r['values'].get('Revision')) not in known_subjects]
    standalone_permits = []
    claim_trips = {(c['trip_id'], c['trip_revision']) for c in available}
    for trip in rows(doc, 'Trips'):
        tv = trip['values']
        if tv.get('International') is not True or not tv.get('Permit reference') or (tv['Trip reference'], tv['Trip revision']) in claim_trips:
            continue
        person = unique([p for p in rows(doc, 'People') if p['values']['Employee ID'] == tv['Employee ID']])
        if person:
            # A trip context is sufficient for permit review; no claim ID/row is invented.
            context = {'record_id': trip['record_id'], 'employee_id': tv['Employee ID'],
                       'trip_id': tv['Trip reference'], 'trip_revision': tv['Trip revision']}
            standalone_permits.append(review(doc, context, trip, person, through_batch, 'permit', number(tv.get('Estimate (EUR)'))))
    budget_context = []
    scopes = sorted({tuple(r['values'].get(k) for k in ('Department', 'Project', 'Budget period')) for r in rows(doc, 'Budget')})
    for scope in scopes:
        scoped = [r for r in rows(doc, 'Budget') if tuple(r['values'].get(k) for k in ('Department', 'Project', 'Budget period')) == scope]
        allocation, net, remaining = Decimal(0), Decimal(0), Decimal(0)
        valid = True
        for row in scoped:
            v = row['values']
            amount, settled, refunded = [number(v.get(k)) for k in ('Allocation or commitment (EUR)', 'Settled (EUR)', 'Refunded (EUR)')]
            if None in (amount, settled, refunded) or min(amount, settled, refunded) < 0 or refunded > settled:
                valid = False; continue
            if v['Entry type'] == 'allocation':
                allocation += amount
            elif v['Entry type'] == 'obligation':
                net += settled - refunded
                remaining += max(amount - settled, Decimal(0))
            else:
                valid = False
        budget_context.append({'department': scope[0], 'project': scope[1], 'period': scope[2],
                               'supplied_ledger_available_cents': cents(allocation - net - remaining, Decimal(1)) if valid else None,
                               'scope': 'Supplied Budget rows only; excludes deferred accepted-request admission. Not funding approval.',
                               'source_refs': [r['record_id'] for r in scoped]})
    if ordinary_claim_ids:
        index['interview:ordinary_entitlement'] = {'path': INTERVIEW, 'sha256': digest((ROOT / INTERVIEW).read_bytes()), 'lines': [294, 302, 454]}
    return {**({'ordinary_claim_ids': ordinary_claim_ids} if ordinary_claim_ids else {}),
            'schema_version': 'omega4-policy-validation/1', 'mode': 'offline-retained-normalization',
            'case_clock': {'date': CASE_DATE.isoformat(), 'timezone': 'Europe/Amsterdam', 'source_ref': 'policy:clock'},
            'through_batch': through_batch, 'claims': claim_results, 'cancellations': cancel_records,
            'normalization_diagnostics': normalization_report['issues'], 'global_findings': global_findings,
            'unmatched_review_imports': unmatched, 'supplied_budget_context': budget_context,
            'standalone_permit_reviews': standalone_permits,
            'source_index': index,
            'limitations': ['No Finance event admission, request creation, transfers, net paid, balance, financial closure, batch-state snapshots or final operations report.',
                            ('Explicitly selected unchanged single-cost claims may derive reviewed entitlement from exact current approvals; all other packet/exception bindings remain unresolved.' if ordinary_claim_ids else
                             'Claim packet schema lacks reviewed-entitlement/exception identifiers; arithmetic/exception visibility to reviewers remains unresolved.'),
                            'Findings on historical revisions are rechecked against facts visible at the selected batch, not reconstructed execution snapshots.',
                            'Merchant/receipt/trip/cap/FX/directory rows have no arrival batches; retained base tables are used as supplied without inventing availability times.',
                            ('Selected ordinary review joins use supplied human approvals, never arithmetic alone. Package-wide unresolved findings remain disclosed and uncertified.' if ordinary_claim_ids else
                             'No policy or amount authorization is inferred from otherwise supported arithmetic; global unresolved findings remain applicable.')]}


def load_verified(run, normalized):
    from normalization.normalize import build
    fresh, report = build(run)
    raw = (normalized / 'records.v1.json').read_bytes()
    saved = json.loads(raw)
    saved_report = json.loads((normalized / 'parsing-report.v1.json').read_bytes())
    if (saved != fresh or saved_report.get('normalized_records_sha256') != digest(raw)
            or {k: v for k, v in saved_report.items() if k != 'normalized_records_sha256'} != report):
        raise ValueError('Normalized evidence does not match retained acquisition and deterministic parser')
    policy = (ROOT / POLICY).read_bytes()
    provenance = json.loads((ROOT / PROVENANCE).read_bytes())
    if digest(policy) != POLICY_HASH or provenance.get('sha256') != POLICY_HASH or provenance.get('native_automated_access') is not False:
        raise ValueError('Preserved browser policy/provenance binding mismatch')
    if ((run / 'supplemental' / Path(POLICY).name).read_bytes() != policy or
            (run / 'supplemental' / Path(PROVENANCE).name).read_bytes() != (ROOT / PROVENANCE).read_bytes()):
        raise ValueError('Local policy/provenance differs from retained supplemental evidence')
    return saved, saved_report


def validate(run, normalized, output, through_batch=4, *, ordinary_claim_ids=()):
    run, normalized, output = run.resolve(), normalized.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError('Refusing existing validation output: ' + str(output))
    if output.is_relative_to(run) or output.is_relative_to(normalized):
        raise ValueError('Validation output must be outside retained acquisition/normalization evidence')
    doc, report = load_verified(run, normalized)
    result = evaluate(doc, report, through_batch, ordinary_claim_ids=ordinary_claim_ids)
    paths = [run / 'sources.json', normalized / 'records.v1.json', normalized / 'parsing-report.v1.json',
             normalized / 'parsing-report.v1.md'] + [ROOT / p for p in (POLICY, PROVENANCE, INTERVIEW, DECISION, ASSIGNMENT, 'snapshot.schema.json', 'validation/validate.py', 'normalization/normalize.py', 'acquisition/retain.py')]
    if ordinary_claim_ids:
        paths.append(ROOT / 'operator_delivery/ordinary-closure.md')
    result['input_bindings'] = [{'path': str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p), 'sha256': digest(p.read_bytes())} for p in paths]
    result['summary'] = {'claim_revisions': len(result['claims']), 'current_claims': sum(c['current_at_batch'] for c in result['claims']),
                         'expense_occurrences': sum(len(c['expenses']) for c in result['claims']),
                         'claim_status_counts': dict(Counter(c['status'] for c in result['claims'])),
                         'current_claim_status_counts': dict(Counter(c['status'] for c in result['claims'] if c['current_at_batch'])),
                         'eligibility_status_counts': dict(Counter(c['eligibility_status'] for c in result['claims'])),
                         'expense_status_counts': dict(Counter(e['status'] for c in result['claims'] for e in c['expenses'])),
                         'normalization_diagnostic_count': len(result['normalization_diagnostics']),
                         'standalone_permit_reviews': len(result['standalone_permit_reviews']),
                         'cancellation_processes': len(result['cancellations'])}
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'findings.v1.json').open('xb') as stream:
        stream.write(encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--normalized', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--through-batch', type=int, default=4)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--ordinary-claim', action='append', default=[], help='Explicitly selected claim for the guarded unchanged-purchase path; does not enable other claims')
    selection.add_argument('--ordinary-v3', dest='ordinary_claim', action='store_const',
                           const=['C01', 'C04', 'C05', 'C06'],
                           help='Select only C01/C04/C05/C06 through the unchanged ordinary-closure guards')
    args = parser.parse_args()
    try:
        result = validate(args.run.resolve(), args.normalized.resolve(), args.output.resolve(), args.through_batch, ordinary_claim_ids=args.ordinary_claim)
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc)); return 1
    print(json.dumps(result['summary'], sort_keys=True))
    return 2 if result['global_findings'] or any(c['status'] != 'supported' for c in result['claims']) else 0


if __name__ == '__main__':
    raise SystemExit(main())

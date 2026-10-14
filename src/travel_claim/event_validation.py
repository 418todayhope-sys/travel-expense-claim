"""Shared evidence checks for Finance and business-cancellation admissions.

A calendar-date clock never implies midnight or an end-of-day instant. Events
on that same local date need an explicit cutoff before admission.
"""
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo


def utc_time(value):
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('missing explicit UTC event date/time')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    # Native columns explicitly name UTC; offsetless serialization is UTC.
    if stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() != 0:
        raise ValueError('event timestamp is not UTC')
    return stamp.replace(tzinfo=timezone.utc)


def observation_error(stamp, clock):
    try:
        if isinstance(clock, str):
            cutoff = datetime.fromisoformat(clock.replace('Z', '+00:00'))
            if cutoff.utcoffset() is None:
                return 'case cutoff lacks timezone'
            return 'future observation' if stamp > cutoff else None
        if isinstance(clock, dict):
            local = stamp.astimezone(ZoneInfo(clock['timezone'])).date()
            case_date = date.fromisoformat(clock['date'])
            if local > case_date:
                return 'future observation'
            if local == case_date:
                return 'same-day cutoff is unknown; no time of day inferred'
            return None
    except (KeyError, TypeError, ValueError):
        return 'invalid authoritative event cutoff'
    return 'authoritative event cutoff is unavailable'


def text_id(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def source_values(row):
    return {k: v.get('value') for k, v in row.get('values', {}).items()}


def finance_context(parsed, revisions, events, claim_id, arrival_batch=None):
    """Bind source-observed request IDs to historical claim employees/directory.

    Acceptance is request identity evidence, never reimbursement entitlement.
    A cash row cannot manufacture its own request binding.
    """
    records = parsed.get('records', {})
    people = records.get('people', next((s['records'] for s in parsed.get('workbook_sheets', []) if s['name'] == 'People'), []))
    bindings = {}
    seen = set()
    for event in events:
        value = source_values(event)
        if value.get('Activity reference') in seen:
            continue
        seen.add(value.get('Activity reference'))
        if value.get('Claim reference') != claim_id or value.get('Activity type') != 'accepted':
            continue
        occurrences = [source_values(r) for r in events if source_values(r).get('Activity reference') == value.get('Activity reference')]
        try:
            first_batch = min(int(v['Arrival batch']) for v in occurrences)
            first = [v for v in occurrences if int(v['Arrival batch']) == first_batch]
            immutable = lambda v: {k: x for k, x in v.items() if k != 'Arrival batch'}
            if any(immutable(v) != immutable(first[0]) for v in first):
                continue  # A conflicted first delivery cannot establish a request.
            value = first[0]
            if observation_error(utc_time(value.get('Activity time (UTC)')), parsed.get('event_clock') or parsed.get('case_clock')):
                continue
            batch = int(value['Arrival batch'])
            available = [r for r in revisions if r.get('arrival_batch') is not None and int(r['arrival_batch']) <= batch]
            revision = max(available, key=lambda r: r['revision'])
        except (TypeError, ValueError, KeyError):
            continue
        employee = next((f['value'] for f in revision['record'].get('fields', []) if f['label'] == 'Employee'), None)
        directory = [r for r in people if source_values(r).get('Employee ID') == employee]
        if len(directory) != 1:
            continue
        person = source_values(directory[0])
        if value.get('Finance officer') != person.get('Finance officer') or value.get('Payee ID') != person.get('Payee ID'):
            continue
        if value.get('Currency') != 'EUR':
            continue
        request = value.get('Request reference')
        if not all(text_id(x) for x in (request, person.get('Payee ID'), person.get('Finance officer'))):
            continue
        binding = dict(claim_id=claim_id, payee_id=person['Payee ID'], actor=person['Finance officer'], currency='EUR')
        # Conflicting request ownership is unresolved rather than last-wins.
        if request in bindings and bindings[request] != binding:
            bindings[request] = None
        else:
            bindings.setdefault(request, binding)
    for request_row in records.get('reimbursement_requests', []):
        value = source_values(request_row)
        batch = value.get('Arrival batch')
        try:
            if isinstance(batch, bool) or int(batch) != float(batch) or int(batch) < 1 or arrival_batch is not None and int(batch) > arrival_batch:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        matches = [r for r in revisions if r['revision'] == value.get('Revision')]
        if value.get('Claim reference') != claim_id or len(matches) != 1 or value.get('Currency') != 'EUR':
            continue
        employee = next((f['value'] for f in matches[0]['record'].get('fields', []) if f['label'] == 'Employee'), None)
        directory = [r for r in people if source_values(r).get('Employee ID') == employee]
        if len(directory) != 1:
            continue
        person = source_values(directory[0]); request = value.get('Request reference')
        if not text_id(request) or value.get('Payee ID') != person.get('Payee ID'):
            continue
        binding = dict(claim_id=claim_id, payee_id=person.get('Payee ID'), actor=person.get('Finance officer'), currency='EUR')
        if request in bindings and bindings[request] != binding:
            bindings[request] = None
        else:
            bindings.setdefault(request, binding)
    return {'requests': bindings, 'clock': parsed.get('event_clock') or parsed.get('case_clock')}


def finance_errors(value, classification, context, cents):
    errors = []
    if not all(text_id(value.get(k)) for k in ('Activity reference', 'Claim reference', 'Request reference', 'Payee ID', 'Finance officer')):
        errors.append('missing or malformed event/request/claim/payee/actor identity')
    binding = (context or {}).get('requests', {}).get(value.get('Request reference'))
    if not binding:
        errors.append('request has no unambiguous source-bound directory authority')
    elif any(value.get(field) != binding.get(key) for field, key in (
            ('Claim reference', 'claim_id'), ('Payee ID', 'payee_id'), ('Finance officer', 'actor'), ('Currency', 'currency'))):
        errors.append('request/claim/payee/currency/Finance actor does not match authority')
    if value.get('Currency') != 'EUR':
        errors.append('unsupported Finance currency')
    if classification in {'confirmed_payment', 'confirmed_refund', 'pending_transfer'} or value.get('Amount (EUR)') is not None:
        amount = cents(value.get('Amount (EUR)'))
        if amount is None or amount <= 0:
            errors.append('cash amount must be positive integer cents')
    if classification in {'obligation_accepted', 'finance_adjustment', 'finance_resolution'} and cents(value.get('Obligation (EUR)')) is None:
        errors.append('obligation amount lacks exact nonnegative cents')
    try:
        error = observation_error(utc_time(value.get('Activity time (UTC)')), (context or {}).get('clock'))
        if error:
            errors.append(error)
    except (ValueError, TypeError):
        errors.append('invalid UTC event time')
    return errors

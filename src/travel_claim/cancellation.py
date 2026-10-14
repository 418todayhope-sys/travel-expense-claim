"""Validated, append-preserving independent business cancellation admissions."""
from copy import deepcopy
from collections import defaultdict

from .event_validation import source_values, text_id, utc_time, observation_error


def revision(value):
    try:
        return int(value) if not isinstance(value, bool) and int(value) > 0 and float(value) == int(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def payload(record):
    return {k: v for k, v in source_values(record).items() if k != 'Arrival batch'}


def target(value):
    return (value.get('Cancelled subject'), value.get('Trip reference'), revision(value.get('Trip revision')),
            value.get('Permit reference') or None, revision(value.get('Permit revision')))


def reduce_cancellations(records, *, trips=(), people=(), clock=None, arrival_batch=None, previous_state=None):
    """Only admitted records change authority; invalid deliveries remain visible."""
    deliveries = []
    for record in (previous_state or {}).get('delivery_history', []) + list(records):
        if record not in deliveries:
            deliveries.append(deepcopy(record))
    records = deliveries
    prior = deepcopy((previous_state or {}).get('admitted_records', {}))
    admitted = deepcopy(prior)
    issues, duplicates, conflicts = [], [], []
    groups = defaultdict(list)
    def issue(record, reason):
        value = source_values(record)
        issues.append({'event_id': value.get('Cancellation activity reference'),
                       'cancellation_id': value.get('Cancellation reference'), 'reason': reason,
                       'source_ref': {k: record.get(k) for k in ('source_id', 'source_sha256', 'locator')}})
    for record in records:
        value = source_values(record); identity = value.get('Cancellation activity reference')
        if not text_id(identity):
            issue(record, 'missing immutable cancellation event identity'); continue
        groups[identity].append(record)
    candidates = []
    for identity, occurrences in groups.items():
        variants = [payload(r) for r in occurrences] + ([payload(prior[identity])] if identity in prior else [])
        conflict = any(v != variants[0] for v in variants[1:])
        if conflict:
            conflicts.append({'event_id': identity, 'payloads': variants,
                              'occurrences': [{k: r.get(k) for k in ('source_id', 'source_sha256', 'locator')} for r in occurrences]})
            for r in occurrences: issue(r, 'conflicting immutable cancellation replay; admitted history preserved')
        elif len(occurrences) > 1:
            duplicates.append({'event_id': identity, 'delivery_batches': [source_values(r).get('Arrival batch') for r in occurrences]})
        if identity in admitted:
            continue
        batches = [revision(source_values(r).get('Arrival batch')) for r in occurrences]
        first = min((b for b in batches if b is not None), default=None)
        earliest = [r for r in occurrences if first is not None and revision(source_values(r).get('Arrival batch')) == first]
        if not earliest or any(payload(r) != payload(earliest[0]) for r in earliest):
            continue
        candidates.append(earliest[0])
    processes = {}
    def apply(record):
        value = source_values(record); identity = value['Cancellation activity reference']
        process_id = value['Cancellation reference']; kind = value['Cancelled subject']
        process = processes.setdefault(process_id, {'cancellation_id': process_id,
            'target': {'subject_type': kind, 'subject_id': value['Trip reference'] if kind == 'trip' else value['Permit reference'],
                       'revision': revision(value['Trip revision'] if kind == 'trip' else value['Permit revision'])},
            'state': 'unseen', 'activity_ids': [], 'history': [], 'next_action': None})
        process['state'] = 'requested' if value['Action'] == 'requested' else 'confirmed'
        process['activity_ids'].append(identity)
        process['history'].append({'event_id': identity, 'action': value['Action'], 'arrival_batch': value['Arrival batch'],
            'effective_time': value.get('Effective time (UTC)'), 'activity_time_utc': value['Activity time (UTC)'],
            'actor': value['Acting employee or supervisor'],
            'source_ref': {k: record.get(k) for k in ('source_id', 'source_sha256', 'locator')}})
        process['next_action'] = 'await a linked confirmation activity' if process['state'] == 'requested' else None
    for record in sorted(prior.values(), key=lambda r: (source_values(r)['Action'] != 'requested', utc_time(source_values(r)['Activity time (UTC)']))):
        apply(record)
    repeated = defaultdict(list)
    for record in candidates:
        value = source_values(record)
        repeated[(value.get('Cancellation reference'), value.get('Action'), revision(value.get('Arrival batch')))].append(record)
    # Resolve dependencies, not spreadsheet row order. Initiations are admitted
    # before confirmations, including a request delivered in a later batch.
    candidates.sort(key=lambda r: (source_values(r).get('Action') != 'requested', revision(source_values(r).get('Arrival batch')) or 0,
                                   source_values(r).get('Cancellation activity reference', '')))
    for record in candidates:
        value = source_values(record); identity = value['Cancellation activity reference']
        process_id, action, kind = value.get('Cancellation reference'), value.get('Action'), value.get('Cancelled subject')
        batch = revision(value.get('Arrival batch'))
        if not text_id(process_id) or kind not in {'trip', 'permit'} or action not in {'requested', 'confirmed'} or batch is None:
            issue(record, 'invalid cancellation identity, action, target type or arrival batch'); continue
        if arrival_batch is not None and batch > arrival_batch:
            issue(record, 'delivery belongs to a future arrival batch'); continue
        if len(repeated[(process_id, action, batch)]) > 1:
            issue(record, 'different repeated actions for one process in the same batch; no authority order supplied'); continue
        process = processes.get(process_id)
        if process and any(h['action'] == action for h in process['history']):
            issue(record, 'different repeated action for an admitted process; history retained'); continue
        trip_id, trip_rev = value.get('Trip reference'), revision(value.get('Trip revision'))
        known_trips = [r for r in trips if source_values(r).get('Trip reference') == trip_id
                       and (source_values(r).get('Arrival batch') is None or revision(source_values(r)['Arrival batch']) is not None
                            and (arrival_batch is None or revision(source_values(r)['Arrival batch']) <= arrival_batch))]
        matching = [r for r in known_trips if revision(source_values(r).get('Trip revision')) == trip_rev]
        latest = max((revision(source_values(r).get('Trip revision')) or 0 for r in known_trips), default=0)
        if not text_id(trip_id) or trip_rev is None or len(matching) != 1 or trip_rev != latest:
            issue(record, 'unmatched, conflicting or stale trip target revision'); continue
        trip = source_values(matching[0])
        def permit_tuple(v):
            return v.get('Permit reference') or None, revision(v.get('Permit revision'))
        if permit_tuple(value) != permit_tuple(trip) or (kind == 'permit' and not all(permit_tuple(value))):
            issue(record, 'associated permit target does not match exact trip/permit revisions'); continue
        if (bool(value.get('Permit reference')) != bool(revision(value.get('Permit revision')))
                or value.get('Permit revision') not in (None, '') and revision(value.get('Permit revision')) is None):
            issue(record, 'incomplete permit identity/revision'); continue
        employee = trip.get('Employee ID')
        directory = [r for r in people if source_values(r).get('Employee ID') == employee]
        expected_actor = employee if action == 'requested' else source_values(directory[0]).get('Supervisor') if len(directory) == 1 else None
        if len(directory) != 1 or not text_id(expected_actor) or value.get('Acting employee or supervisor') != expected_actor:
            issue(record, 'cancellation actor is not the trip employee or authorized directory supervisor'); continue
        try:
            stamp = utc_time(value.get('Activity time (UTC)'))
            error = observation_error(stamp, clock)
            if error: raise ValueError(error)
            if action == 'requested':
                if value.get('Initiation activity reference') or value.get('Effective time (UTC)'):
                    raise ValueError('initiation cannot name an initiation or effective time')
            else:
                initiation = admitted.get(value.get('Initiation activity reference'))
                if not initiation:
                    raise ValueError('confirmation has an unresolved initiation reference; recheck on arrival')
                start = source_values(initiation)
                if start.get('Action') != 'requested' or start.get('Cancellation reference') != process_id or target(start) != target(value):
                    raise ValueError('confirmation does not match the exact initiation/process/target')
                if stamp <= utc_time(start.get('Activity time (UTC)')):
                    raise ValueError('confirmation must occur strictly after initiation')
                if utc_time(value.get('Effective time (UTC)')) != stamp:
                    raise ValueError('scheduled or backdated effective time is not cancellation authority')
        except (ValueError, TypeError) as exc:
            issue(record, str(exc)); continue
        admitted[identity] = deepcopy(record); apply(record)
    for record in records:
        value = source_values(record); process_id = value.get('Cancellation reference'); kind = value.get('Cancelled subject')
        if text_id(process_id) and kind in {'trip', 'permit'} and process_id not in processes:
            processes[process_id] = {'cancellation_id': process_id,
                'target': {'subject_type': kind, 'subject_id': value.get('Trip reference') if kind == 'trip' else value.get('Permit reference'),
                           'revision': revision(value.get('Trip revision') if kind == 'trip' else value.get('Permit revision'))},
                'state': 'unseen', 'activity_ids': [], 'history': [], 'next_action': 'resolve invalid or incomplete initiation evidence'}
    return {'processes': processes, 'issues': issues, 'duplicate_events': duplicates, 'conflicting_events': conflicts,
            'admitted_records': admitted, 'delivery_history': deepcopy(records), 'finance_effects': [], 'claim_effects': []}

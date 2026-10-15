"""POL-2026.2 financial completion dependencies, separate from event admission."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .event_validation import utc_time
from .finance import _cents
from .workflow import _revision


def supported_clock(parsed):
    clock = parsed.get('event_clock') or parsed.get('case_clock')
    try:
        if isinstance(clock, dict):
            return date.fromisoformat(clock['date']).isoformat() == clock['date'] and bool(ZoneInfo(clock['timezone']))
        return isinstance(clock, str) and datetime.fromisoformat(clock.replace('Z', '+00:00')).utcoffset() is not None
    except (ValueError, TypeError, KeyError):
        return False


def financial_dependencies(*, finance, revision, allowed, cancellations, review):
    """Require current, admitted, request-bound resolutions; never turn them into cash.

    Native rows lacking explicit revision/resolution links stay unresolved. Arrival
    revision context is historical evidence, never current human authorization.
    """
    events = list(finance.get('admitted_events', {}).values())
    accepted = [e for e in events if e['classification'] == 'obligation_accepted']
    resolutions = [e for e in events if e['classification'] == 'finance_resolution'
                   and _revision(e['source_record'].get('Claim revision')) == revision]
    requirements = []
    def need(event, reason, cancellation=None, after=None):
        requirements.append(dict(event_id=event['event_id'], request_id=event['source_record']['Request reference'],
            reason=reason, cancellation_id=cancellation, after=after or event['source_record']['Activity time (UTC)'],
            source_ref=event['source_ref']))
    controls = {'failed_transfer','retry_authorization','finance_cancellation_requested','finance_cancelled','pending_transfer'}
    for event in events:
        if event['classification'] in controls:
            need(event, 'Finance attempt/status requires explicit disposition')
        if event['classification'] == 'finance_adjustment' and any(
                p['classification']=='confirmed_payment' and utc_time(p['source_record']['Activity time (UTC)']) <= utc_time(event['source_record']['Activity time (UTC)'])
                for p in events):
            need(event, 'Post-payment adjustment requires Finance resolution even if cash matches')
    contexts = {r['event_id']: r.get('arrival_revision_context') for r in finance.get('recorded_obligation_history', [])}
    for event in accepted:
        old = _revision(event['source_record'].get('Claim revision')) or contexts.get(event['event_id'])
        if old is not None and old != revision or review.get('material_same_revision'):
            need(event, 'Material correction of an accepted obligation requires current Finance resolution')
    cancellation_clear = True
    for cancellation in cancellations:
        if cancellation['status'] != 'confirmed' or cancellation.get('validation_status','PASS') != 'PASS':
            cancellation_clear = False
            continue
        confirmed = cancellation['confirmed_at']
        for event in accepted:
            # Equality cannot prove the pre-acceptance branch. A bound resolution
            # can resolve it without fabricating an ordering.
            if utc_time(confirmed) >= utc_time(event['source_record']['Activity time (UTC)']):
                need(event, 'Cancellation after acceptance/dispatch requires Finance resolution',
                     cancellation=cancellation['cancellation_id'], after=confirmed)
    for requirement in requirements:
        requirement['resolved_by'] = []
        for resolution in resolutions:
            value = resolution['source_record']
            named = set(str(value.get('Resolved activity references') or '').splitlines())
            cancellations_named = set(str(value.get('Travel cancellation references') or value.get('Travel cancellation reference') or '').splitlines())
            named_cancel = requirement['cancellation_id'] in (named | cancellations_named)
            linked = named_cancel if requirement['cancellation_id'] else requirement['event_id'] in named
            if (linked and value.get('Request reference') == requirement['request_id']
                    and resolution['obligation_cents'] == allowed
                    and utc_time(value['Activity time (UTC)']) >= utc_time(requirement['after'])):
                requirement['resolved_by'].append(resolution['event_id'])
    return dict(status='PASS' if cancellation_clear and all(r['resolved_by'] for r in requirements) else 'BLOCKED',
                cancellation_clear=cancellation_clear, requirements=requirements,
                source_refs=list(dict.fromkeys(f"{e['source_ref']['source_id']}@{e['source_ref']['source_sha256']}#{e['source_ref']['locator']}"
                    for e in events if e['classification'] in controls | {'finance_resolution','finance_adjustment','obligation_accepted'})))


def no_claim_financial_effect_refs(parsed, domain, cancellation, observations, arrival_batch):
    """Prove absence only from a complete, observed four-batch native-shaped package.

    A filtered fixture, missing page, unclassified delivery, known cost or unmatched
    Finance record cannot establish absence. Blank Trips commitment cells have
    the explicit policy meaning 'no commitment yet'. No claim is synthesized.
    """
    from .exceptions import source_bound
    from .ordinary import fields, ref, table
    from .expenses import policy_valid

    if (cancellation['affected_claim_ids'] or cancellation['status'] != 'confirmed'
            or cancellation.get('validation_status') != 'PASS'
            or not policy_valid(parsed.get('expense_policy')) or not supported_clock(parsed)
            or parsed.get('arrival_batches') != [1, 2, 3, 4] or arrival_batch != 4
            or parsed.get('transcription_issues') != []):
        return []
    prefix = 'synthetic-' if parsed.get('evidence_mode') == 'synthetic-test' else ''
    required = {prefix + name for name in ('initial-claim-binder', 'claim-updates-binder',
                                         'receipt-binder', 'travel-registers-workbook')}
    inventory = [i for i in parsed.get('source_inventory', []) if i['source_id'] in required]
    if len(inventory) != 4 or {i['source_id'] for i in inventory} != required:
        return []
    refs = []
    for item in inventory:
        sid = item['source_id']
        matches = [o for o in observations if o.get('source_id') == sid]
        if len(matches) != 1 or matches[0].get('status') != 'read' or matches[0].get('missing_scope'):
            return []
        if item['kind'] == 'pdf':
            rows = [r for r in parsed.get('pdf_pages', []) if r.get('source_id') == sid]
            if (not rows or len(rows) != item.get('page_count')
                    or {r.get('page') for r in rows} != set(range(1, len(rows) + 1))
                    or not all(source_bound(r, observations) for r in rows)):
                return []
            refs.extend(ref(r) for r in rows)
        elif item['kind'] == 'xlsx':
            sheets = [s for s in parsed.get('workbook_sheets', []) if s.get('source_id') == sid]
            names = {'People', 'Trips', 'Merchant payments', 'FX', 'Caps', 'Budget',
                     'Review ledger', 'Review packets', 'Finance activity', 'Travel cancellations'}
            if (len(sheets) != item.get('sheet_count') or len(sheets) != len(names)
                    or {s.get('name') for s in sheets} != names
                    or any(s.get('source_sha256') != matches[0].get('sha256') for s in sheets)):
                return []
            refs.append(f"{sid}@{matches[0]['sha256']}#complete workbook inventory")
        else:
            return []
    trips = [r for r in table(parsed, 'trips', 'Trips') if fields(r).get('Trip reference') == cancellation['trip_id']
             and _revision(fields(r).get('Trip revision')) == cancellation['trip_revision']]
    if (len(trips) != 1 or not source_bound(trips[0], observations)
            or fields(trips[0]).get('First commitment date') not in (None, '')):
        return []
    for key, name in [('receipts', 'Receipts'), ('merchant_payments', 'Merchant payments')]:
        rows = table(parsed, key, name)
        if any(not source_bound(r, observations) or not fields(r).get('Trip reference')
               or fields(r)['Trip reference'] == cancellation['trip_id'] for r in rows):
            return []
    claims = domain['revision_history'].get('claim', {})
    if any(not source_bound(r, observations) or fields(r).get('Claim reference') not in claims for r in domain['finance_records']):
        return []
    if any(f.get('unresolved_event_ids') or f.get('conflicting_events') for f in domain['finance_reconciliations'].values()):
        return []
    if any(not source_bound(r, observations) or fields(r).get('Claim reference') not in claims for r in table(parsed, 'reimbursement_requests', 'Reimbursement requests')):
        return []
    return list(dict.fromkeys(refs + [ref(trips[0])] + cancellation['source_refs']))

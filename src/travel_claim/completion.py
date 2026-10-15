"""POL-2026.2 financial completion dependencies, separate from event admission."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from zoneinfo import ZoneInfo

from .event_validation import utc_time
from .workflow import _revision


def supported_clock(parsed):
    clock = parsed.get('event_clock') or parsed.get('case_clock')
    try:
        if isinstance(clock, dict):
            return date.fromisoformat(clock['date']).isoformat() == clock['date'] and bool(ZoneInfo(clock['timezone']))
        return isinstance(clock, str) and datetime.fromisoformat(clock.replace('Z', '+00:00')).utcoffset() is not None
    except (ValueError, TypeError, KeyError):
        return False


def financial_evidence_basis(*, rows, record, policy, prior_workflow, prior_finance, revision, arrival_batch):
    """Track claim-local material evidence, never observation time as business time.

    Source hashes/locators and material row facts identify the basis. Reviewer
    deliveries and Finance status events are deliberately not basis changes.
    """
    from .approvals import evidence_digest, fields, ref
    from .ordinary import expense_lines
    signatures = {ref(row): evidence_digest([row], None) for row in rows}
    costs = [{k: v for k, v in line.items() if k != 'source_refs'} for line in expense_lines(record)]
    payload = dict(sources=signatures, costs=costs, policy_sha256=policy.get('sha256'))
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    previous = (prior_workflow or {}).get('financial_basis')
    changes = deepcopy((previous or {}).get('changes', []))
    changed = bool(previous and previous['digest'] != digest)
    # Old sidecars cannot establish that an already flagged correction was resolved.
    legacy = bool(prior_workflow and not previous and
                  (prior_workflow.get('revision') != revision or
                   prior_workflow.get('claim_approval', {}).get('material_same_revision')))
    if changed or legacy:
        refs = [r for r, signature in signatures.items()
                if not previous or previous['sources'].get(r) != signature]
        if not previous or previous.get('costs') != costs:
            refs.append(ref(record))
        # Retain unresolved changed sources across successive same-revision edits.
        if changes and changes[-1]['revision'] == revision:
            refs += [r for r in changes[-1]['source_refs'] if r in signatures]
        changes.append(dict(digest=digest, revision=revision, arrival_batch=arrival_batch,
            same_revision=prior_workflow.get('revision') == revision,
            source_refs=list(dict.fromkeys(refs)), submitted_date=fields(record).get('Submitted date'),
            committed_event_ids=[e['event_id'] for e in (prior_finance or {}).get('admitted_events', {}).values()
                                 if e['classification'] in {'obligation_accepted', 'confirmed_payment', 'pending_transfer'}],
            legacy_basis_unknown=legacy))
    return dict(digest=digest, sources=signatures, costs=costs,
                revision=revision, changes=changes, latest_change=changes[-1] if changes else None)


def _resolution_covers_basis(resolution, change, finance):
    """An old immutable delivery cannot become authority through redelivery.

    Explicit claim revision identifies a new claim version. Changes *within* a
    revision additionally need supplied exact source-version links. Native rows
    lacking these fields remain held; no Finance authority is synthesized.
    """
    from .expenses import local_date
    value = resolution['source_record']
    if not change.get('arrival_batch'):
        return False  # Missing latest-change evidence is not current Finance authority.
    batches = [_revision(e['source_record'].get('Arrival batch')) for e in finance['event_history']
               if e['event_id'] == resolution['event_id']]
    batches = [b for b in batches if b is not None]
    if not batches or min(batches) < change['arrival_batch']:
        return False
    if change['same_revision'] or change.get('legacy_basis_unknown'):
        supplied = set(str(value.get('Source revisions') or '').splitlines())
        if not change['source_refs'] or not all(r in supplied or r.split('@', 1)[1].split('#', 1)[0] in supplied
                                               for r in change['source_refs']):
            return False
    try:
        # A local submission date supplies a day, never a fabricated instant.
        if utc_time(value['Activity time (UTC)']).astimezone(ZoneInfo('Europe/Amsterdam')).date() < local_date(change['submitted_date']):
            return False
    except (ValueError, TypeError):
        return False
    return True


def financial_dependencies(*, finance, revision, allowed, cancellations, review, basis=None):
    """Require current, admitted, request-bound resolutions; never turn them into cash.

    Native rows lacking explicit revision/resolution links stay unresolved. Arrival
    revision context is historical evidence, never current human authorization.
    """
    events = list(finance.get('admitted_events', {}).values())
    accepted = [e for e in events if e['classification'] == 'obligation_accepted']
    resolutions = [e for e in events if e['classification'] == 'finance_resolution'
                   and _revision(e['source_record'].get('Claim revision')) == revision]
    requirements = []
    def need(event, reason, cancellation=None, after=None, change=None):
        requirements.append(dict(event_id=event['event_id'], request_id=event['source_record']['Request reference'],
            reason=reason, cancellation_id=cancellation, after=after or event['source_record']['Activity time (UTC)'],
            source_ref=event['source_ref'], evidence_change=change))
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
        change = (basis or {}).get('latest_change')
        affected_basis = bool(change and (change['committed_event_ids'] or change.get('legacy_basis_unknown')))
        if ((old is not None and old != revision) or affected_basis
                or basis is None and review.get('material_same_revision')):
            if change is None:
                change = dict(arrival_batch=None, source_refs=[], legacy_basis_unknown=True)
            need(event, 'Material correction of an accepted obligation requires current Finance resolution', change=change)
    cancellation_clear = True
    for cancellation in cancellations:
        if cancellation['status'] != 'confirmed' or cancellation.get('validation_status','PASS') != 'PASS':
            cancellation_clear = False
            continue
        confirmed = cancellation['confirmed_at']
        for event in events:
            if event['classification'] not in {'obligation_accepted', 'confirmed_payment', 'pending_transfer', 'failed_transfer', 'finance_adjustment'}:
                continue
            # Equality cannot prove the pre-acceptance branch. A bound resolution
            # can resolve it without fabricating an ordering.
            if utc_time(confirmed) >= utc_time(event['source_record']['Activity time (UTC)']):
                need(event, 'Cancellation after acceptance/dispatch/payment requires Finance resolution',
                     cancellation=cancellation['cancellation_id'], after=confirmed)
    for requirement in requirements:
        requirement['resolved_by'] = []
        for resolution in resolutions:
            value = resolution['source_record']
            named = set(str(value.get('Resolved activity references') or '').splitlines())
            cancellations_named = set(str(value.get('Travel cancellation references') or value.get('Travel cancellation reference') or '').splitlines())
            named_cancel = requirement['cancellation_id'] in (named | cancellations_named)
            request_events = {e['event_id'] for e in accepted
                              if e['source_record']['Request reference'] == requirement['request_id']} | {requirement['event_id']}
            linked = (named_cancel and bool(named & request_events)) if requirement['cancellation_id'] else requirement['event_id'] in named
            if (linked and value.get('Request reference') == requirement['request_id']
                    and resolution['obligation_cents'] == allowed
                    and utc_time(value['Activity time (UTC)']) >= utc_time(requirement['after'])
                    and (not requirement['evidence_change'] or _resolution_covers_basis(resolution, requirement['evidence_change'], finance))):
                requirement['resolved_by'].append(resolution['event_id'])
    return dict(status='PASS' if cancellation_clear and all(r['resolved_by'] for r in requirements) else 'BLOCKED',
                cancellation_clear=cancellation_clear, requirements=requirements,
                source_refs=list(dict.fromkeys(f"{e['source_ref']['source_id']}@{e['source_ref']['source_sha256']}#{e['source_ref']['locator']}"
                    for e in events if e['classification'] in controls | {'finance_resolution','finance_adjustment','obligation_accepted','confirmed_payment'})))


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

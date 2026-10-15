"""Source-bound POL-2026.2 reimbursement exceptions, never travel authority.

Native PDF display labels are mapped explicitly, not by substring or fuzzy
matching. Currency comes from the exception's exact claim/revision/cost line:
POL-2026.2 line 7 defines the replacement as an original-currency amount.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo

ISSUES = {'late_filing', 'late_permit', 'permit_unapproved', 'travel_cancellation'}
NATIVE_ISSUES = {'Late filing': 'late_filing', 'Late permit': 'late_permit',
                 'Permit unapproved': 'permit_unapproved', 'Travel cancellation': 'travel_cancellation'}
EXCEPTION_FIELDS = ('Authorizing Finance officer', 'Applies to claim', 'Applies to revision',
                    'Expense reference', 'Allowed original amount', 'Exception reason', 'Covered issues')


def source_bound(row, observations):
    return bool(row.get('source_id') and row.get('source_sha256') and row.get('locator')) and any(
        o.get('source_id') == row['source_id'] and o.get('sha256') == row['source_sha256']
        and o.get('status') == 'read' and not o.get('missing_scope') for o in observations)


def covered_issues(raw):
    if raw == 'None':  # Exact native PDF wording for an amount-only exception.
        return []
    if isinstance(raw, str) and raw:
        raw = raw.splitlines()
    if not isinstance(raw, list) or any(not isinstance(v, str) for v in raw):
        raise ValueError('Missing or malformed covered_issues list')
    result = [NATIVE_ISSUES.get(v, v) for v in raw]
    if any(v not in ISSUES for v in result) or len(set(result)) != len(result):
        raise ValueError('Unknown or duplicate covered_issues; exact matching required')
    return sorted(result)


def validate_exception(*, record, line, employee, people, observations, fields, ref):
    value = fields(record)
    supplied = any(key in value for key in EXCEPTION_FIELDS)
    result = dict(status='absent', source_refs=[], covered_issues=[], raw_fields={})
    if not supplied:
        return result
    result.update(status='BLOCKED', source_refs=[ref(record)],
                  raw_fields={k: value.get(k) for k in EXCEPTION_FIELDS + ('Travel cancellation reference',)})
    try:
        labels = [f.get('label', '').strip() for f in record.get('fields', [])]
        if any(labels.count(key) > 1 for key in EXCEPTION_FIELDS + ('Claim reference', 'Revision', 'Travel cancellation reference')):
            raise ValueError('Repeated Finance exception authority field requires source resolution')
        if any(key not in value for key in EXCEPTION_FIELDS):
            raise ValueError('Missing required Finance exception field')
        directory = [r for r in people if fields(r).get('Employee ID') == employee]
        if not source_bound(record, observations) or len(directory) != 1 or not source_bound(directory[0], observations):
            raise ValueError('Exception or Finance directory source binding is unverified')
        actor = fields(directory[0]).get('Finance officer')
        if not actor or value['Authorizing Finance officer'] != actor or actor == employee:
            raise ValueError('Exception actor is not the directory Finance officer')
        from .workflow import _revision
        revision = _revision(value.get('Revision'))
        if (not value.get('Claim reference') or value['Applies to claim'] != value['Claim reference']
                or revision is None or _revision(value['Applies to revision']) != revision
                or value['Expense reference'] != line['cost_id']):
            raise ValueError('Exception claim/revision/cost authority does not match current expense')
        if not isinstance(value['Exception reason'], str) or not value['Exception reason'].strip():
            raise ValueError('Exception requires a documented reason')
        amount = value['Allowed original amount']
        if isinstance(amount, bool) or amount is None:
            raise ValueError('Invalid replacement original amount')
        replacement = Decimal(str(amount).replace(',', ''))
        if not replacement.is_finite() or replacement < 0:
            raise ValueError('Invalid replacement original amount')
        coverage = covered_issues(value['Covered issues'])
        cancellation = value.get('Travel cancellation reference')
        if 'travel_cancellation' in coverage and (not isinstance(cancellation, str) or not cancellation):
            raise ValueError('Travel cancellation exception requires exact travel_cancellation_id')
        result.update(status='valid', actor=actor, claim_id=value['Applies to claim'], revision=revision,
                      cost_id=line['cost_id'], currency=line['currency'], replacement_original_amount=str(replacement),
                      reason=value['Exception reason'], covered_issues=coverage, travel_cancellation_id=cancellation,
                      source_refs=[ref(record), ref(directory[0])])
    except (ValueError, TypeError, InvalidOperation) as exc:
        result['reason'] = str(exc)
    return result


def finding(issue, reason, refs, cancellation_id=None):
    return dict(issue=issue, original_finding=reason, source_refs=refs, status='unresolved',
                travel_cancellation_id=cancellation_id, exception_source_refs=[])


def apply_coverage(findings, exception):
    for item in findings:
        if (exception['status'] == 'valid' and item['issue'] in exception['covered_issues']
                and (item['issue'] != 'travel_cancellation'
                     or item['travel_cancellation_id'] == exception.get('travel_cancellation_id'))):
            item.update(status='covered_for_reimbursement', exception_source_refs=exception['source_refs'])
    return findings


def travel_findings(*, trip, employee, decisions, people, cancellations, fields, ref, observations, trip_source_refs=()):
    """Find eligibility defects without granting or retiring arrangement authority."""
    result = []
    directory = [fields(r) for r in people if fields(r).get('Employee ID') == employee]
    if trip.get('International') is True:
        permit = trip.get('Permit reference'); revision = trip.get('Permit revision')
        from .workflow import _revision
        rows = [r for r in decisions if fields(r).get('Subject type') == 'permit'
                and fields(r).get('Subject reference') == permit and _revision(fields(r).get('Revision')) == _revision(revision)]
        # Exact redelivery is inert; conflicting immutable decision IDs cannot establish permission.
        unique = {}; conflict = False
        for r in rows:
            v = fields(r); identity = v.get('Decision reference')
            payload = {k: val for k, val in v.items() if k != 'Arrival batch'}
            if not identity or identity in unique and unique[identity][1] != payload:
                conflict = True
            unique[identity] = (r, payload)
        rows = [v[0] for v in unique.values()]
        refs = list(trip_source_refs) + [ref(r) for r in rows] + [ref(r) for r in people if fields(r).get('Employee ID') == employee]
        roles = {'administration': 'Administration reviewer', 'budget_owner': 'Budget owner', 'supervisor': 'Supervisor'}
        try:
            estimate = Decimal(str(trip.get('Estimate (EUR)')))
            if not estimate.is_finite() or estimate < 0:
                raise ValueError('Invalid reviewed estimate')
            if estimate > 1000:
                roles['director'] = 'Director'
            approved = bool(permit and _revision(revision) and len(directory) == 1 and not conflict
                            and all(source_bound(r, observations) for r in people if fields(r).get('Employee ID') == employee))
            times = []
            for role, label in roles.items():
                matching = [r for r in rows if role in str(fields(r).get('Review roles', '')).splitlines()]
                if len(matching) != 1:
                    approved = False; continue
                r = matching[0]; v = fields(r)
                review_roles = str(v.get('Review roles') or '').splitlines()
                roles_valid = (bool(review_roles) and len(set(review_roles)) == len(review_roles)
                    and set(review_roles) <= set(roles)
                    and (len(review_roles) == 1 or set(review_roles) == {'budget_owner', 'supervisor'}))
                valid = (roles_valid and v.get('Outcome') == 'approve' and v.get('Reviewer') == directory[0].get(label)
                         and v.get('Reviewer') != employee and source_bound(r, observations)) if len(directory) == 1 else False
                approved = approved and valid
                if valid:
                    # XLSX column explicitly says UTC, though Excel serialization lacks an offset.
                    time = v.get('Decision time (UTC)')
                    if not isinstance(time, str):
                        raise ValueError('Missing permit decision UTC time')
                    stamp = datetime.fromisoformat(time.replace('Z', '+00:00'))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=ZoneInfo('UTC'))
                    times.append(stamp)
            if not approved:
                result.append(finding('permit_unapproved', 'Matching approved permit roles are missing or invalid; cancellation does not revoke historical approvals', refs))
            else:
                from .expenses import local_date
                commitment = local_date(trip.get('First commitment date'))
                approval_day = max(times).astimezone(ZoneInfo('Europe/Amsterdam')).date()
                if approval_day >= commitment:
                    result.append(finding('late_permit', 'Permit approved after first commitment' if approval_day > commitment
                                          else 'Same-day permit/commitment ordering is unconfirmed', refs))
        except (ValueError, TypeError, InvalidOperation, KeyError) as exc:
            result.append(finding('late_permit', f'Permit timing/amount evidence unresolved: {exc}', refs))
    elif trip.get('International') is not False:
        result.append(finding('permit_unapproved', 'International/permit requirement is missing', []))
    for cancellation in cancellations:
        from .workflow import _revision
        current_target = (bool(trip.get('Trip reference') and _revision(trip.get('Trip revision')))
                          and cancellation.get('trip_id') == trip.get('Trip reference')
                          and _revision(cancellation.get('trip_revision')) == _revision(trip.get('Trip revision')))
        if cancellation.get('target_type') == 'permit':
            current_target = (current_target and cancellation.get('permit_id') == trip.get('Permit reference')
                              and _revision(cancellation.get('permit_revision')) == _revision(trip.get('Permit revision')))
        if current_target:
            result.append(finding('travel_cancellation', 'Current travel basis has a requested or confirmed business cancellation',
                                  list(trip_source_refs) + cancellation.get('source_refs', []), cancellation['cancellation_id']))
    return result


def review_binds_exception(decision, record, *, same_revision_change, fields, ref):
    """Require current version evidence when a replacement changes the review basis.

    Native Source revisions may name the binder's printed SRC-D-* version. A
    same-revision source replacement needs the exact retained page/hash instead;
    the unchanged binder label cannot establish review of changed content.
    """
    versions = str(fields(decision).get('Source revisions') or '').splitlines()
    exact = ref(record) in versions or record.get('source_sha256') in versions
    printed = re.findall(r'\bSRC-D-\d+\b', record.get('text', ''))
    return exact or (not same_revision_change and any(v in versions for v in printed))

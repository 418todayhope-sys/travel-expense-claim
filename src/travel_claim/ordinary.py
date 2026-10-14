"""Connected claim evaluation from retained facts and explicitly sourced rules.

No native policy definitions are inferred from interview descriptions, caps,
review outcomes, or Finance acceptance. Missing authority remains blocked.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re

from .finance import _cents, reconcile_finance_events
from .workflow import row_values

ROLE_FIELDS = {"administration": "Administration reviewer", "budget_owner": "Budget owner",
               "supervisor": "Supervisor", "director": "Director"}


def ref(row):
    return f"{row.get('source_id')}@{row.get('source_sha256')}#{row.get('locator')}"


def fields(row):
    return {f['label'].strip(): f['value'] for f in row.get('fields', [])} if 'fields' in row else row_values(row)


def table(parsed, key, tab):
    return parsed.get('records', {}).get(key, next((s['records'] for s in parsed.get('workbook_sheets', []) if s['name'] == tab), []))


def expense_lines(record):
    """Read complete rows from the retained PDF layout; never guess a row."""
    pattern = re.compile(r'^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\d{4}-\d{2}-\d{2})\s+([\d,]+\.\d{2})\s+([A-Z]{3})\s*$', re.M)
    return [dict(line=int(m[1]), cost_id=m[2], receipt_id=m[3], first_submitted_date=m[4],
                 original_cents=_cents(m[5].replace(',', '')), currency=m[6], source_refs=[ref(record)])
            for m in pattern.finditer(record.get('text', ''))]


def connect_claim(*, parsed, claim, decisions, finance_events, finance, cancellations,
                  arrival_batch, source_observations, prior_finance=None, source_classifications=None):
    """Evaluate an ordinary path; each result keeps its evidence and owner."""
    record = claim['record']; values = fields(record)
    claim_id, revision = claim['subject_id'], claim['revision']
    employee, trip_id = values.get('Employee'), claim.get('trip_id')
    stages = []
    def stage(name, condition, refs, detail, owner, action, fail=False):
        row = dict(stage=name, status='PASS' if condition else 'FAIL' if fail else 'BLOCKED',
                   source_refs=list(dict.fromkeys([ref(record)] + refs)), detail=detail, owner=owner, next_action=action)
        stages.append(row)
        return bool(condition)
    def trusted(row):
        return bool(row.get('locator')) and any(o.get('source_id') == row.get('source_id') and
            o.get('sha256') == row.get('source_sha256') and o.get('status') == 'read' and not o.get('missing_scope')
            for o in source_observations)
    def visible(row):
        try:
            batch = fields(row).get('Arrival batch')
            return not isinstance(batch, bool) and int(batch) == float(batch) and 0 < int(batch) <= arrival_batch
        except (ValueError, TypeError, OverflowError):
            return False

    trips = [r for r in table(parsed, 'trips', 'Trips') if fields(r).get('Trip reference') == trip_id
             and str(fields(r).get('Trip revision')) in {str(claim.get('trip_revision')), f"{claim.get('trip_revision')}.0"}]
    trip = fields(trips[0]) if len(trips) == 1 else {}
    linked = stage('claim_trip_link', len(trips) == 1 and trip.get('Employee ID') == employee
                   and len([r for r in finance['revision_history'] if r['revision'] == revision]) == 1,
                   [ref(record)] + [ref(r) for r in trips], 'Exact claim, trip revision and employee linkage',
                   'Travel Administration Lead', 'Verify the exact employee, trip ID and trip revision binding')
    people = [r for r in table(parsed, 'people', 'People') if fields(r).get('Employee ID') == employee]
    person = fields(people[0]) if len(people) == 1 else {}
    lead = person.get('Administration reviewer') or 'Travel Administration Lead'
    finance_owner = person.get('Finance officer') or 'Finance'

    policy_source_ids = {'synthetic-policy'} if parsed.get('evidence_mode') == 'synthetic-test' else {'policy-pol-2026-2'}
    rules = [r for r in table(parsed, 'workflow_policy_rules', 'Workflow policy rules')
             if r.get('source_id') in policy_source_ids and trusted(r) and visible(r)]
    policy_record = rules[0] if len(rules) == 1 else None
    policy = fields(policy_record) if policy_record else {}
    policy_supported = (policy.get('Rule set') == 'exact-paid-costs-v1'
                        and isinstance(policy.get('Policy revision'), str) and bool(policy.get('Policy revision'))
                        and isinstance(policy.get('Eligible categories'), list)
                        and isinstance(policy.get('Uncapped categories'), list)
                        and isinstance(policy.get('Required claim roles'), list) and bool(policy.get('Required claim roles'))
                        and set(policy.get('Required claim roles')) <= set(ROLE_FIELDS)
                        and policy.get('Receipt required') is True and policy.get('Settled merchant proof required') is True
                        and policy.get('No self review') is True and policy.get('FX date basis') == 'paid-date'
                        and policy.get('Closure rule') == 'entitlement-authorization-net-cash-no-blockers'
                        and isinstance(policy.get('Domestic permit required'), bool))
    policy_refs = [ref(policy_record)] if policy_record else []
    affected = [c for c in cancellations if claim_id in c['affected_claim_ids']]
    permission = False
    permission_refs = [ref(r) for r in trips] + policy_refs
    if linked and policy_supported:
        if trip.get('International') is False and policy.get('Domestic permit required') is False:
            permission = True
        else:
            # UTC timing must be expressly supplied; local calendar dates do
            # not establish an exact commitment instant.
            permit_roles = policy.get('Required permit roles')
            commitment = trip.get('First commitment time (UTC)')
            relevant = [r for r in decisions if fields(r).get('Subject type') == 'permit'
                        and fields(r).get('Subject reference') == trip.get('Permit reference')
                        and fields(r).get('Revision') == trip.get('Permit revision')]
            permission_refs += [ref(r) for r in relevant]
            try:
                stamp = lambda text: datetime.fromisoformat(text.replace('Z', '+00:00'))
                commit = stamp(commitment)
                permission = bool(trip.get('Permit reference') and permit_roles and set(permit_roles) <= set(ROLE_FIELDS)
                                  and commit.utcoffset() is not None)
                for role in permit_roles or []:
                    matching = [fields(r) for r in relevant if fields(r).get('Review roles') == role]
                    permission = permission and len(matching) == 1 and matching[0].get('Outcome') == 'approve'
                    if permission:
                        permission = (matching[0].get('Reviewer') == person.get(ROLE_FIELDS[role])
                                      and matching[0].get('Reviewer') != employee
                                      and stamp(matching[0].get('Decision time (UTC)')).utcoffset() is not None
                                      and stamp(matching[0]['Decision time (UTC)']) < commit)
            except (ValueError, TypeError, AttributeError):
                permission = False
    stage('travel_permission', permission, permission_refs,
          'Travel permission requires sourced policy and exact permit authority/timing where required; affected cancellations block the ordinary path',
          lead, 'Obtain the policy-defined permission requirement and matching permit approvals/timing; resolve affected cancellations')

    lines = expense_lines(record)
    receipts = parsed.get('records', {}).get('receipts', [])
    merchants = table(parsed, 'merchant_payments', 'Merchant payments')
    evidence_ok = bool(lines) and len({line['cost_id'] for line in lines}) == len(lines)
    for line in lines:
        rs = [r for r in receipts if fields(r).get('Receipt reference') == line['receipt_id']]
        ms = [r for r in merchants if fields(r).get('Expense reference') == line['cost_id']]
        # Stable merchant transaction identity: duplicates are not extra proof
        # or additional money; conflicting payloads cannot pass validation.
        unique = {}; conflict = False
        for row in ms:
            mv = fields(row); identity = mv.get('Transaction reference')
            if not identity or identity in unique and fields(unique[identity]) != mv:
                conflict = True
            unique[identity] = row
        ms = list(unique.values())
        rv = fields(rs[0]) if len(rs) == 1 else {}
        receipt_ok = (len(rs) == 1 and rv.get('Expense reference') == line['cost_id']
                      and rv.get('Employee') == employee and rv.get('Trip reference') == trip_id
                      and rv.get('Currency') == line['currency'] and _cents(rv.get('Gross amount')) == line['original_cents'])
        merchant_ok = bool(ms) and not conflict and all(
            fields(m).get('Employee ID') == employee and fields(m).get('Trip reference') == trip_id
            and fields(m).get('Receipt reference') == line['receipt_id']
            and fields(m).get('Currency') == line['currency'] and fields(m).get('Payment status') == 'settled'
            and _cents(fields(m).get('Gross amount')) is not None and fields(m).get('Paid date') for m in ms)
        merchant_ok = merchant_ok and sum(_cents(fields(m)['Gross amount']) for m in ms) == line['original_cents']
        line.update(evidence_status='PASS' if receipt_ok and merchant_ok else 'BLOCKED',
                    category=rv.get('Category'), documented_units=rv.get('Documented units'),
                    paid_dates=sorted({str(fields(m).get('Paid date'))[:10] for m in ms}),
                    allowed_cents=None, status='unresolved',
                    reason='Evidence matched; policy eligibility remains separate' if receipt_ok and merchant_ok else 'Receipt or settled merchant proof is missing, conflicting or mismatched')
        line['source_refs'] += [ref(r) for r in rs + ms]
        evidence_ok = evidence_ok and receipt_ok and merchant_ok
    evidence_refs = [ref(record)] + [r for line in lines for r in line['source_refs']]
    stage('supporting_evidence', evidence_ok, evidence_refs,
          'Current revision expense IDs, receipts, settled merchant transactions, identities, currencies and amounts',
          employee or 'Employee', 'Supply matching receipts and settled merchant proof for each current-revision expense line')

    policy_ok = policy_supported and evidence_ok and linked and permission
    rates = table(parsed, 'fx_rates', 'FX'); caps = table(parsed, 'caps', 'Caps')
    for line in lines:
        if not policy_ok:
            break
        if line['category'] not in policy['Eligible categories'] or len(line['paid_dates']) != 1:
            policy_ok = False; break
        date = line['paid_dates'][0]; original = line['original_cents']
        if line['category'] not in policy['Uncapped categories']:
            cs = [c for c in caps if fields(c).get('Destination') == trip.get('Destination')
                  and fields(c).get('Category') == line['category'] and fields(c).get('Currency') == line['currency']
                  and str(fields(c).get('Effective from'))[:10] <= date <= str(fields(c).get('Effective to'))[:10]]
            try:
                units = Decimal(str(line['documented_units']))
                limit = _cents(fields(cs[0]).get('Amount per unit')) if len(cs) == 1 else None
                total_limit = units * limit if limit is not None else None
                if not units.is_finite() or units <= 0 or total_limit is None or total_limit != total_limit.to_integral_value():
                    policy_ok = False; break
                original = min(original, int(total_limit)); line['source_refs'] += [ref(cs[0])]
            except (InvalidOperation, TypeError):
                policy_ok = False; break
        fx = [r for r in rates if fields(r).get('Currency') == line['currency'] and str(fields(r).get('Rate date'))[:10] == date]
        try:
            rate = Decimal(str(fields(fx[0]).get('EUR per currency unit'))) if len(fx) == 1 else None
            converted = Decimal(original) * rate if rate is not None else None
            if rate is None or not rate.is_finite() or rate <= 0 or converted != converted.to_integral_value():
                policy_ok = False; break
            line['allowed_cents'] = int(converted); line['status'] = 'supported'
            line['source_refs'] += [ref(fx[0])]
        except (InvalidOperation, TypeError):
            policy_ok = False; break
    if not policy_ok:
        for line in lines:
            line.update(allowed_cents=None, status='unresolved')
    allowed = sum(line['allowed_cents'] for line in lines) if policy_ok else None
    stage('policy_eligibility', policy_ok, policy_refs + evidence_refs,
          'Eligibility and exact-cent entitlement require a verified source-backed rule definition; interview summaries and Finance acceptance are insufficient',
          lead, 'Obtain complete native policy and a reviewed source-referenced rule definition; verify dates, FX, caps and exceptions')

    current = [r for r in decisions if fields(r).get('Subject type') == 'claim'
               and fields(r).get('Subject reference') == claim_id and fields(r).get('Revision') == revision]
    unique_decisions = {}; decision_conflict = False
    for decision in current:
        identity = fields(decision).get('Decision reference')
        payload = {k: v for k, v in fields(decision).items() if k != 'Arrival batch'}
        if not identity or identity in unique_decisions and unique_decisions[identity][1] != payload:
            decision_conflict = True
        unique_decisions[identity] = (decision, payload)
    current = [pair[0] for pair in unique_decisions.values()]
    packets = table(parsed, 'review_packets', 'Review packets')
    budget_ids = {fields(r).get('Ledger reference') for r in table(parsed, 'budget', 'Budget')}
    observed = []; reviews_ok = bool(current) and len(people) == 1 and not decision_conflict
    for decision in current:
        dv = fields(decision)
        ps = [p for p in packets if fields(p).get('Decision reference') == dv.get('Decision reference')]
        pv = fields(ps[0]) if len(ps) == 1 else {}
        roles = str(dv.get('Review roles') or '').splitlines()
        valid = (len(ps) == 1 and pv.get('Employee ID') == employee and pv.get('Trip reference') == trip_id
                 and pv.get('Trip revision') == claim.get('trip_revision')
                 and all(pv.get(key) == trip.get(key) for key in ('Business purpose', 'Client', 'Schedule coverage', 'Alternatives considered', 'Permit reference', 'Permit revision'))
                 and set(str(pv.get('Expense references') or '').splitlines()) == {l['cost_id'] for l in lines}
                 and bool(pv.get('Policy revision')) and bool(str(pv.get('Budget record references') or '').splitlines())
                 and set(str(pv.get('Budget record references') or '').splitlines()) <= budget_ids
                 and roles and all(role in ROLE_FIELDS and dv.get('Reviewer') == person.get(ROLE_FIELDS[role])
                                   and dv.get('Reviewer') != employee for role in roles))
        if policy_record:
            valid = valid and pv.get('Policy revision') == policy.get('Policy revision')
        observed.append(dict(decision_id=dv.get('Decision reference'), outcome=dv.get('Outcome'), roles=roles,
                             evidence_valid=bool(valid), source_refs=[ref(decision)] + [ref(p) for p in ps]))
        reviews_ok = reviews_ok and valid
    review_refs = [r for d in observed for r in d['source_refs']] + [ref(p) for p in people]
    stage('review_evidence', reviews_ok, review_refs, 'Observed current-revision human decisions matched to reviewers and preserved review packets; completeness is checked separately',
          lead, 'Provide exact-revision decisions and packets matching the employee, trip, expense list, policy and budget references')
    required = policy.get('Required claim roles', []) if policy_supported else []
    if policy_supported and policy.get('Director threshold cents') is not None:
        threshold = policy['Director threshold cents']
        if isinstance(threshold, int) and not isinstance(threshold, bool) and threshold >= 0 and allowed is not None:
            required = list(required) + (['director'] if allowed > threshold else [])
        else:
            reviews_ok = False
    approvals = reviews_ok and policy_supported and all(
        len([d for d in observed if role in d['roles'] and d['outcome'] == 'approve']) == 1
        and all(d['outcome'] == 'approve' for d in observed if role in d['roles']) for role in required)
    stage('required_approvals', approvals, review_refs + policy_refs,
          'All policy-required roles must have matching current-revision approvals; no decisions are created',
          lead, 'Confirm policy-required review roles and obtain their current-revision human approvals')

    requests = [r for r in table(parsed, 'reimbursement_requests', 'Reimbursement requests')
                if trusted(r) and visible(r) and fields(r).get('Claim reference') == claim_id and fields(r).get('Revision') == revision]
    request = fields(requests[0]) if len(requests) == 1 else {}
    obligation = finance.get('recorded_obligation')
    approved_ids = {d['decision_id'] for d in observed if d['outcome'] == 'approve' and d['evidence_valid']}
    request_ok = bool(linked and permission and policy_ok and approvals and obligation and len(requests) == 1
                      and request.get('Request reference') == obligation['request_id']
                      and request.get('Payee ID') == person.get('Payee ID') == obligation['payee_id']
                      and request.get('Currency') == 'EUR' and _cents(request.get('Amount (EUR)')) == allowed == obligation['amount_cents']
                      and obligation['claim_revision'] == revision and obligation['finance_officer'] == finance_owner
                      and set(str(request.get('Decision references') or '').splitlines()) == approved_ids
                      and bool(approved_ids))
    request_refs = [ref(r) for r in requests] + (obligation['source_refs'] if obligation else [])
    stage('request_obligation', request_ok, request_refs,
          'Recorded request/obligation linkage requires explicit claim revision, payee, amount and approval references; ledger arrival context is not authorization',
          finance_owner, 'Provide the exact-revision reimbursement request and Finance acceptance linked to its approvals and authorized amount')
    if request_ok:
        authorization = dict(amount_cents=allowed, claim_revision=revision, source_refs=request_refs + review_refs + policy_refs)
        finance = reconcile_finance_events(finance_events, claim_id=claim_id, current_revision=revision,
            revision_history=finance['revision_history'], previous_reconciliation=prior_finance,
            authorized_obligation=authorization, source_classifications=source_classifications)
    reconciled = finance.get('recorded_ledger_balance_cents') is not None and not finance['unresolved_event_ids'] and not finance['conflicting_events']
    stage('financial_reconciliation', reconciled,
          [ref(e) for e in finance_events if fields(e).get('Claim reference') == claim_id],
          f"Confirmed net cash {finance['net_confirmed_cents']} cents; recorded ledger difference {finance.get('recorded_ledger_balance_cents')}; authorized balance {finance['balance_cents']}",
          finance_owner, 'Resolve missing obligations, conflicting or unclassified events, request/payee links and outstanding balances')

    authorities = [r for r in table(parsed, 'closure_authorities', 'Closure authorities') if trusted(r) and visible(r)
                   and fields(r).get('Claim reference') == claim_id and fields(r).get('Revision') == revision]
    clock_ok = False
    try:
        clock_ok = datetime.fromisoformat(parsed['case_clock'].replace('Z', '+00:00')).utcoffset() is not None
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    closure_authority = (len(authorities) == 1 and fields(authorities[0]).get('Confirmation') == 'financial-completion-conditions'
                         and bool(fields(authorities[0]).get('Authority')) and fields(authorities[0]).get('Case clock') == parsed.get('case_clock'))
    external = [i for i in parsed.get('unresolved_issues', []) if i.get('status', 'open') == 'open'
                and (i.get('subject_type') in {'policy', 'scenario'} or i.get('subject_id') in {claim_id, trip_id, trip.get('Permit reference')})]
    control_events = [e for e in finance['event_history'] if e['classification'] in {
        'failed_transfer', 'retry_authorization', 'finance_cancellation_requested', 'finance_cancelled'}]
    resolved_controls = set()
    def event_stamp(event):
        stamp = datetime.fromisoformat(event['source_record']['Activity time (UTC)'].replace('Z', '+00:00'))
        return stamp.replace(tzinfo=timezone.utc) if stamp.utcoffset() is None else stamp
    for event in finance['event_history']:
        value = event['source_record']
        if (event['classification'] == 'finance_resolution' and value.get('Claim revision') == revision
                and obligation and value.get('Request reference') == obligation['request_id']
                and value.get('Finance officer') == finance_owner):
            named = set(str(value.get('Resolved activity references') or '').splitlines())
            for control in control_events:
                try:
                    if (control['event_id'] in named
                            and control['source_record'].get('Request reference') == value['Request reference']
                            and event_stamp(event) >= event_stamp(control)):
                        resolved_controls.add(control['event_id'])
                except (KeyError, ValueError, TypeError, AttributeError):
                    pass
    controls_clear = not finance['pending_transfer_event_ids'] and all(e['event_id'] in resolved_controls for e in control_events)
    closed = (all(s['status'] == 'PASS' for s in stages) and controls_clear and request_ok and finance['balance_cents'] == 0
              and not finance['repair_issues'] and not affected and clock_ok and closure_authority and not external)
    stage('financial_closure', closed, [ref(r) for r in authorities] + request_refs + policy_refs,
          'Closure requires supported completion conditions, authoritative clock, current evidence/approvals, entitlement/obligation/net cash agreement and no affected unresolved issue',
          finance_owner, 'Confirm completion conditions and the authoritative clock; resolve every affected approval, Finance or cancellation dependency')
    pending = next((s for s in stages if s['status'] != 'PASS'), None)
    return dict(claim_id=claim_id, revision=revision, trip_id=trip_id, trip_revision=claim.get('trip_revision'),
                mode=parsed.get('evidence_mode', 'offline-replay'), status=('closed-reimbursed' if allowed else 'closed-no-payment') if closed else 'pending',
                allowed_cents=allowed, balance_cents=finance['balance_cents'], lines=lines, stages=stages,
                observed_reviews=observed, request=deepcopy(requests[0]) if request_ok else None,
                source_refs=list(dict.fromkeys([ref(record)] + [r for s in stages for r in s['source_refs']])),
                next_owner=None if closed else pending['owner'], reason='Supported financial closure' if closed else pending['detail'],
                finance=finance)


def ordinary_demo(workflows):
    """Render one observed claim with every stage, owner and retained reference."""
    claim_id = "C01" if "C01" in workflows else next(iter(sorted(workflows)), None)
    lines = ["# Connected ordinary claim workflow — OFFLINE REPLAY", "",
             "Retained-input evaluation; no fresh reads, requests, approvals or payments were generated.", ""]
    if not claim_id:
        return "\n".join(lines + ["No retained claim available for demonstration.", ""])
    workflow = workflows[claim_id]
    lines += [f"Claim `{claim_id}` revision {workflow['revision']}; trip `{workflow['trip_id']}` revision {workflow['trip_revision']}; status **{workflow['status']}**.", ""]
    for stage in workflow['stages']:
        lines += [f"## {stage['stage']} — {stage['status']}", "", stage['detail'], "",
                  f"Owner: {stage['owner']}. Next action: {stage['next_action']}", ""]
        lines.extend(f"- `{reference}`" for reference in stage['source_refs'])
        lines.append("")
    return "\n".join(lines) + "\n"

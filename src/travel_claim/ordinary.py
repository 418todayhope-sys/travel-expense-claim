"""Connected claim evaluation from retained facts and explicitly sourced rules.

No native policy definitions are inferred from interview descriptions, caps,
review outcomes, or Finance acceptance. Missing authority remains blocked.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import re

from .finance import _cents, reconcile_finance_events
from .workflow import row_values
from .expenses import evaluate_expenses, policy_valid
from .exceptions import travel_findings, review_binds_exception, source_bound
from .approvals import evaluate_reviews, evaluate_permit

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
    lines = []
    for raw in record.get('text', '').splitlines():
        if not re.match(r'^\s*\d+\s+', raw):
            continue
        tokens = raw.split()
        if len(tokens) == 6:
            number, cost, receipt, submitted, amount, currency = tokens
        else:
            number = tokens[0]; cost = tokens[1] if len(tokens) > 1 else 'unknown'
            receipt = submitted = amount = currency = None
        lines.append(dict(line=int(number), cost_id=cost, receipt_id=receipt,
            first_submitted_date=submitted, original_amount=amount.replace(',', '') if amount else None,
            original_cents=_cents(amount.replace(',', '')) if amount else None,
            currency=currency, source_refs=[ref(record)]))
    return lines


def connect_claim(*, parsed, claim, decisions, finance_events, finance, cancellations,
                  arrival_batch, source_observations, prior_finance=None, source_classifications=None, prior_workflow=None):
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
    permit_review = evaluate_permit(parsed=parsed, trip_record=trips[0] if len(trips)==1 else {},
        decisions=decisions, arrival_batch=arrival_batch, observations=source_observations,
        prior=(prior_workflow or {}).get('permit_approval'),
        cost_ids=[line['cost_id'] for line in expense_lines(record)],cancellations=cancellations)
    permission = linked and permit_review['arrangement_authorized']
    permission_refs = [ref(r) for r in trips] + policy_refs + permit_review['source_refs']
    stage('travel_permission', permission, permission_refs,
          'Travel permission requires sourced policy and exact permit authority/timing where required; affected cancellations block the ordinary path',
          lead, 'Obtain the policy-defined permission requirement and matching permit approvals/timing; resolve affected cancellations')

    lines = expense_lines(record)
    eligibility = travel_findings(trip=trip, employee=employee, decisions=decisions, people=table(parsed, 'people', 'People'),
        cancellations=cancellations, fields=fields, ref=ref, observations=source_observations,
        trip_source_refs=[ref(r) for r in trips]) if policy_valid(parsed.get('expense_policy')) else []
    if trip.get('International') is True and not permit_review['approved'] and not any(f['issue']=='permit_unapproved' for f in eligibility):
        from .exceptions import finding
        eligibility.append(finding('permit_unapproved', 'Current permit replies/packets do not establish required approval authority', permit_review['source_refs']))
    calculation = evaluate_expenses(lines=lines, parsed=parsed, employee=employee, trip_id=trip_id,
        trip=trip, record=record, history=finance['revision_history'], fields=fields, ref=ref, table=table,
        eligibility_findings=eligibility, observations=source_observations)
    evidence_ok = bool(lines) and len({line['cost_id'] for line in lines}) == len(lines) and all(
        line['evidence_status'] == 'PASS' for line in lines)
    evidence_refs = [ref(record)] + [r for line in lines for r in line['source_refs']]
    stage('supporting_evidence', evidence_ok, evidence_refs,
          'Current revision receipts and settled merchant proof must match employee, trip, cost, currency and gross',
          employee or 'Employee', 'Supply matching receipts and settled merchant proof for every expense')
    filing_ok = bool(lines) and all(line['filing_status'] == 'PASS' for line in lines)
    stage('filing_deadline', filing_ok, evidence_refs,
          '; '.join(f"{line['cost_id']}: {line['reason']}" for line in lines) or 'Missing expense submissions',
          finance_owner, 'Verify cost-specific original submission dates, trip end and employee payment; obtain explicit Finance exception for late filing')
    waived_permission = bool(eligibility and any(f['issue'] in {'late_permit', 'permit_unapproved'} for f in eligibility)
        and lines and all(l['eligibility_status'] == 'PASS' for l in lines))
    reimbursement_permission = permission or (linked and permit_review.get('arrangements_at_commitment_supported',False)) or (linked and policy_supported and waived_permission)
    policy_ok = policy_supported and evidence_ok and linked and reimbursement_permission and calculation['status'] == 'PASS'
    for line in lines:
        line['allowed_cents'] = line['calculated_cents'] if policy_ok else None
        if not policy_ok:
            line['status'] = 'unresolved'
    allowed = calculation['calculated_cents'] if policy_ok else None
    stage('policy_eligibility', policy_ok, policy_refs + evidence_refs,
          'Expense calculation and filing are separate from travel permission, reviewed policy definitions and approvals',
          lead, 'Resolve line findings and remaining policy/permission evidence before treating calculated amounts as entitlement')

    for line in lines:
        exception = line['exception']
        if exception['status'] != 'absent':
            stage(f"finance_exception:{line['cost_id']}", exception['status'] == 'valid', line['source_refs'],
                  exception.get('reason', 'Source-bound Finance exception'), finance_owner,
                  'Supply exact Finance actor, current claim/revision/cost, replacement amount, reason and covered issues')
        for item in line['eligibility_findings']:
            name = f"eligibility:{line['cost_id']}:{item['issue']}" + (f":{item['travel_cancellation_id']}" if item.get('travel_cancellation_id') else '')
            stage(name, item['status'] == 'covered_for_reimbursement', item['source_refs'] + item['exception_source_refs'],
                  item['original_finding'] + '; ' + item['status'], finance_owner,
                  'Obtain explicit Finance coverage for this exact eligibility finding and affected expense; retain original arrangement history')

    prior_lines = {l['cost_id']: l for l in (prior_workflow or {}).get('lines', [])}
    def changed_exception_amount(line):
        old = prior_lines.get(line['cost_id'], {})
        before = old.get('conversion', {}).get('allowed_original_amount')
        after = line.get('conversion', {}).get('allowed_original_amount')
        # Unknown-to-known evidence and decimal display precision are not proof
        # of a material replacement-amount change.
        return bool(before is not None and after is not None
            and (line.get('exception', {}).get('status') == 'valid' or old.get('exception', {}).get('status') == 'valid')
            and Decimal(before) != Decimal(after))
    same_revision_change = bool(prior_workflow and prior_workflow.get('revision') == revision and (
        any(changed_exception_amount(line) for line in lines)
        or prior_workflow.get('exception_revalidation', {}).get('same_revision_change')))
    replacement_review = same_revision_change or any(
        line.get('replacement_amount_changed') or changed_exception_amount(line) for line in lines)
    line_refs={r for line in lines for r in line['source_refs']}
    dependencies=[r for key,tab in [('receipts','Receipts'),('merchant_payments','Merchant payments'),('caps','Caps'),('fx_rates','FX')]
                  for r in table(parsed,key,tab) if ref(r) in line_refs]
    claim_review=evaluate_reviews(parsed=parsed,kind='claim',subject_id=claim_id,revision=revision,
        trip_record=trips[0] if len(trips)==1 else {},employee=employee,subject_record=record,
        amount_cents=calculation['calculated_cents'],decisions=decisions,arrival_batch=arrival_batch,
        observations=source_observations,cost_ids=[line['cost_id'] for line in lines],
        dependency_rows=dependencies,prior=(prior_workflow or {}).get('claim_approval'),
        withdrawn=linked and values.get('Status')=='withdrawn' and trusted(record),
        cancellation_ids=[f['travel_cancellation_id'] for f in eligibility if f['issue']=='travel_cancellation'])
    observed=claim_review['deliveries']
    # Preserve Step 175's extra binding requirement on material Finance replacements.
    for decision in observed:
        decision['exception_binding_valid']=(not replacement_review or review_binds_exception(
            decision['raw_record'],record,same_revision_change=same_revision_change,fields=fields,ref=ref))
        if not decision['exception_binding_valid']:
            decision['evidence_valid']=False
    approvals=claim_review['approved'] and all(d['evidence_valid'] for d in observed if d['active'])
    review_refs=claim_review['source_refs']
    reviews_ok=all(claim_review['role_states'].get(role) not in {'missing','conflicting'} for role in claim_review['required_roles']) and all(d['evidence_valid'] for d in observed if d['active'])
    stage('review_evidence',reviews_ok,review_refs,
          'Current subject/version/role/actor/source/reason and complete review packets; rejected imports remain in history',
          lead,'Supply current source-bound replies and complete packets; answer the concrete return repair requests')
    stage('required_approvals',approvals,review_refs + policy_refs,
          f"Claim approval state: {claim_review['state']}; required roles: {', '.join(claim_review['required_roles'])}",
          lead,'Obtain the outstanding current-version human decisions; permit replies never approve a claim')

    for reply in observed:
        if reply['outcome']=='return' and reply['evidence_valid']:
            stage(f"review_return:{reply['decision_id']}",not reply['active'],reply['source_refs'],
                  f"{reply['reason']}; repair requested: {reply['repair_requested']}",employee or 'Employee',reply['repair_requested'])

    exception_revalidated = not replacement_review or approvals
    stage('exception_revalidation', exception_revalidated, evidence_refs + review_refs,
          'Replacement amounts require current claim reviews bound to the replacement source version; earlier reviews remain historical',
          lead, 'Obtain current revision/source-bound reviews of the Finance replacement amount and a matching reimbursement authorization')

    requests = [r for r in table(parsed, 'reimbursement_requests', 'Reimbursement requests')
                if trusted(r) and visible(r) and fields(r).get('Claim reference') == claim_id and fields(r).get('Revision') == revision]
    request = fields(requests[0]) if len(requests) == 1 else {}
    obligation = finance.get('recorded_obligation')
    approved_ids = {d['decision_id'] for d in observed if d['outcome'] == 'approve' and d['evidence_valid'] and d['active']}
    request_ok = bool(linked and reimbursement_permission and policy_ok and approvals and obligation and len(requests) == 1
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
            authorized_obligation=authorization, source_classifications=source_classifications, event_context=finance.get("event_context"))
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
    cancellation_refs = [source for c in affected for source in c.get("source_refs", [])]
    stage('cancellation_readiness', not affected, cancellation_refs,
          'Linked current or historical trip/permit cancellation requires specific Finance disposition and resolution; prior permission and money history are preserved' if affected else 'No linked cancellation dependency',
          finance_owner, 'Verify cancellation-bound disposition, current request authority and monetary resolution before releasing payment readiness')
    closed = (all(s['status'] == 'PASS' for s in stages) and controls_clear and request_ok and finance['balance_cents'] == 0
              and not finance['repair_issues'] and not affected and clock_ok and closure_authority and not external)
    stage('financial_closure', closed, [ref(r) for r in authorities] + request_refs + policy_refs,
          'Closure requires supported completion conditions, authoritative clock, current evidence/approvals, entitlement/obligation/net cash agreement and no affected unresolved issue',
          finance_owner, 'Confirm completion conditions and the authoritative clock; resolve every affected approval, Finance or cancellation dependency')
    business_state=claim_review['state']
    financial_clean=(len(trips)==1 and trusted(trips[0]) and not finance.get('recorded_obligation') and not finance['net_confirmed_cents']
        and not finance['event_history'] and not requests and not affected)
    disposition=business_state if business_state in {'rejected','withdrawn'} and financial_clean else None
    if business_state in {'rejected','withdrawn'} and not financial_clean:
        stage('nonpayment_disposition',False,review_refs + request_refs,
              'Rejection/withdrawal recorded; existing Finance effects require disposition and are not erased',
              finance_owner,'Confirm cancellation/status of dispatched obligations and resolve existing cash before financial completion')
    pending = next((s for s in stages if s['status'] != 'PASS'), None)
    return dict(claim_id=claim_id, revision=revision, trip_id=trip_id, trip_revision=claim.get('trip_revision'),
                mode=parsed.get('evidence_mode', 'offline-replay'), status=disposition or ('held' if business_state in {'rejected','withdrawn'} else ('closed-reimbursed' if allowed else 'closed-no-payment') if closed else 'pending'),
                claim_approval=claim_review,permit_approval=permit_review,
                expense_calculation=calculation, exception_revalidation=dict(required=replacement_review, same_revision_change=same_revision_change, status='PASS' if exception_revalidated else 'BLOCKED'), allowed_cents=allowed, balance_cents=finance['balance_cents'], lines=lines, stages=stages,
                observed_reviews=observed, request=deepcopy(requests[0]) if request_ok else None,
                source_refs=list(dict.fromkeys([ref(record)] + [r for s in stages for r in s['source_refs']])),
                next_owner=None if closed or disposition else (finance_owner if business_state in {'rejected','withdrawn'} else pending['owner']),
                reason=f"Clean business {disposition}: " + (values.get('Claim reason','') if disposition=='withdrawn' else '; '.join(d['reason'] for d in observed if d['active'] and d['outcome']=='reject')) if disposition else 'Supported financial closure' if closed else pending['detail'],
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

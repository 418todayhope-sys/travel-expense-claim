"""Source-traceable Finance reconciliation primitives.

Only explicit, source-classified settled and refund events affect confirmed
cash. Finance obligations remain separate from caller-supplied authorized
obligations. No policy entitlement or approval decision is made here.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from datetime import datetime
from .event_validation import finance_errors, utc_time
from typing import Any


_NATIVE_EVENT_CLASSES = {
    "accepted": "obligation_accepted",
    "settled": "confirmed_payment",
    "refund": "confirmed_refund",
    "failed": "failed_transfer",
    "retry_authorized": "retry_authorization",
    "cancellation_requested": "finance_cancellation_requested",
    "cancelled": "finance_cancelled",
    # These are retained as non-cash Finance records; their amount describes
    # an obligation, not a payment.
    "adjustment": "finance_adjustment",
    "resolution": "finance_resolution",
}


def _values(record: dict[str, Any]) -> dict[str, Any]:
    return {key: cell.get("value") for key, cell in record.get("values", {}).items()}


def _source_ref(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("source_id", "source_sha256", "locator")}


def _cents(value: Any) -> int | None:
    """Convert exact EUR decimal input to integer cents; reject rounding."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    scaled = amount * 100
    if scaled != scaled.to_integral_value() or scaled < 0:
        return None
    return int(scaled)


def _payload(values: dict[str, Any]) -> dict[str, Any]:
    return {key: values[key] for key in sorted(values) if key != "Arrival batch"}


def _reference_text(ref: dict[str, Any]) -> str:
    return f"{ref.get('source_id')}@{ref.get('source_sha256')}#{ref.get('locator')}"


def _positive_integer(value: Any) -> int | None:
    try:
        return int(value) if not isinstance(value, bool) and int(value) > 0 and float(value) == int(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _recorded_obligations(history: list[dict], *, claim_id: str, current_revision: int,
                          revisions: list[dict]) -> tuple[list[dict], dict | None, str | None]:
    """Read ledger observations, without deriving reimbursement authorization.

    Obligation (EUR) is a recorded amount, not a cash delta. Native rows omit
    claim revision; arrival context is retained separately from explicit links.
    Only the first delivery establishes context; redelivery cannot rebind it.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for event in history:
        if event['classification'] in {'obligation_accepted', 'finance_adjustment', 'finance_resolution'}:
            groups[event['event_id']].append(event)
    records = []
    problem = None
    for event_id, occurrences in groups.items():
        event = occurrences[0]
        values = event['source_record']
        batches = [e['source_record'].get('Arrival batch') for e in occurrences]
        first_batch = min((_positive_integer(b) for b in batches if _positive_integer(b)), default=None)
        context_rows = [r for r in revisions if first_batch is not None
                        and _positive_integer(r.get('arrival_batch')) is not None
                        and _positive_integer(r['arrival_batch']) <= first_batch]
        context = max((r['revision'] for r in context_rows), default=None)
        explicit = _positive_integer(values.get('Claim revision'))
        matches = [r for r in revisions if r['revision'] == explicit] if explicit else []
        link = ('explicit_current' if explicit == current_revision else 'explicit_historical') if matches else 'arrival_context_only' if context else 'unmatched'
        refs = [_reference_text(e['source_ref']) for e in occurrences]
        record = {
            'event_id': event_id, 'event_type': event['event_type'], 'claim_id': claim_id,
            'request_id': values.get('Request reference'), 'finance_officer': values.get('Finance officer'),
            'payee_id': values.get('Payee ID'), 'currency': event['currency'],
            'amount_cents': event['obligation_cents'], 'activity_time_utc': values.get('Activity time (UTC)'),
            'claim_revision': explicit if matches else None, 'arrival_revision_context': context,
            'revision_link_status': link, 'first_arrival_batch': first_batch,
            'delivery_batches': batches, 'source_refs': list(dict.fromkeys(refs)),
            'claim_source_refs': [deepcopy(r['source_ref']) for r in (matches or context_rows)
                                  if r['revision'] == (explicit if matches else context)],
        }
        records.append(record)
        if (event['currency'] != 'EUR' or event['obligation_cents'] is None or not first_batch
                or not all(isinstance(values.get(key), str) and values[key].strip()
                           for key in ('Request reference', 'Finance officer', 'Payee ID'))
                or not all(all(e['source_ref'].get(key) for key in ('source_id', 'source_sha256', 'locator')) for e in occurrences)
                or (values.get('Claim revision') is not None and not matches)):
            problem = 'Obligation record lacks supported amount, request/payee/officer, source identity, arrival, or explicit revision match'
    if not records:
        return [], None, None
    if len({(r['request_id'], r['payee_id'], r['currency']) for r in records}) != 1:
        problem = 'Multiple request/payee/currency ledgers cannot be combined as one obligation'
    # A single observation needs no ordering assumption. Multiple observations
    # require explicit UTC event times; arrival numbers do not define business time.
    if len(records) > 1:
        try:
            def stamp(record):
                dt = datetime.fromisoformat(record['activity_time_utc'].replace('Z', '+00:00'))
                # The retained header explicitly names UTC even when the cell
                # serialization omits an offset.
                if dt.utcoffset() is not None and dt.utcoffset().total_seconds() != 0:
                    raise ValueError('not UTC')
                return dt.replace(tzinfo=None)
            records.sort(key=lambda r: (stamp(r), r['event_id']))
            for left, right in zip(records, records[1:]):
                if stamp(left) == stamp(right) and left['amount_cents'] != right['amount_cents']:
                    problem = 'Conflicting obligation amounts have the same event time'
        except (ValueError, TypeError, AttributeError):
            problem = 'Multiple obligation observations lack unambiguous UTC ordering'
    return records, deepcopy(records[-1]) if not problem else None, problem


def reconcile_finance_events(
    events: list[dict[str, Any]],
    *,
    claim_id: str,
    current_revision: int,
    authorized_obligation: dict[str, Any] | None = None,
    revision_history: list[dict[str, Any]] | None = None,
    previous_reconciliation: dict[str, Any] | None = None,
    owner: str = "Finance",
    source_classifications: dict[str, str] | None = None,
    event_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile source events for a claim without making policy decisions.

    `authorized_obligation` is an independent, already-authorized input of
    `{amount_cents, claim_revision, source_refs}`. This function neither
    derives nor authorizes it. `source_classifications` may extend the native
    workbook vocabulary when a retained source defines another event type;
    unrecognized types otherwise remain unresolved.
    """
    if not claim_id or isinstance(current_revision, bool) or not isinstance(current_revision, int) or current_revision < 1:
        raise ValueError("claim_id and a positive current_revision are required")
    if not owner:
        raise ValueError("owner is required for reconciliation issues")
    if (previous_reconciliation and 'admitted_events' not in previous_reconciliation
            and any(previous_reconciliation.get(k) for k in ('confirmed_payment_event_ids', 'confirmed_refund_event_ids',
                'confirmed_payment_cents', 'confirmed_refund_cents', 'net_confirmed_cents'))):
        raise ValueError('Legacy admission state requires explicit verified migration; refusing to erase or invent admitted money')

    classes = dict(_NATIVE_EVENT_CLASSES)
    if source_classifications:
        allowed_classes = {
            "confirmed_payment", "confirmed_refund", "pending_transfer",
            "obligation_accepted", "failed_transfer", "retry_authorization",
            "finance_cancellation_requested", "finance_cancelled",
            "finance_adjustment", "finance_resolution",
        }
        for event_type, classification in source_classifications.items():
            if not isinstance(event_type, str) or classification not in allowed_classes:
                raise ValueError(f"unsupported source event classification: {event_type!r} -> {classification!r}")
            classes[event_type] = classification

    # Accept full-history or delta calls without dropping earlier raw deliveries.
    retained = [{**deepcopy(h['source_ref']), 'values': {k: {'value': v} for k, v in h['source_record'].items()}}
                for h in (previous_reconciliation or {}).get('event_history', []) if isinstance(h.get('source_ref'), dict) and 'source_record' in h]
    deliveries = []
    for record in retained + events:
        if not any(_source_ref(r) == _source_ref(record) and _values(r) == _values(record) for r in deliveries):
            deliveries.append(record)
    events = deliveries
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_id_records: list[dict[str, Any]] = []
    for record in events:
        event_id = _values(record).get("Activity reference")
        if not isinstance(event_id, str) or not event_id:
            if _values(record).get("Claim reference") == claim_id:
                missing_id_records.append(record)
        else:
            by_id[event_id].append(record)

    prior = deepcopy((previous_reconciliation or {}).get('admitted_events', {}))
    admitted = deepcopy(prior)
    history, duplicate_events, conflicting_events, unresolved = [], [], [], []
    event_issue_by_id = {}

    def item_for(record):
        values = _values(record)
        return {"event_id": values.get("Activity reference"), "source_ref": _source_ref(record),
                "source_record": deepcopy(values), "event_type": values.get("Activity type"),
                "classification": classes.get(values.get("Activity type"), "unresolved"),
                "amount_cents": _cents(values.get("Amount (EUR)")),
                "obligation_cents": _cents(values.get("Obligation (EUR)")),
                "currency": values.get("Currency"), "original_activity_id": values.get("Original activity reference")}

    for event_id, occurrences in by_id.items():
        relevant = [r for r in occurrences if _values(r).get('Claim reference') == claim_id]
        if not relevant and event_id not in prior:
            continue
        payloads = [_payload(_values(r)) for r in occurrences]
        if event_id in prior:
            payloads.append(_payload(prior[event_id]['source_record']))
        conflict = any(v != payloads[0] for v in payloads[1:])
        if conflict:
            conflicting_events.append({'event_id': event_id, 'source_refs': [_source_ref(r) for r in occurrences], 'payloads': payloads})
            event_issue_by_id[event_id] = {
                'record_id': f'finance-event-conflict:{event_id}', 'event_id': event_id,
                'subject_type': 'claim', 'subject_id': claim_id, 'revision': current_revision,
                'missing_or_return_reason': 'Conflicting immutable event replay; admitted history retained, new payload held',
                'source_refs': [_source_ref(r) for r in occurrences], 'owner': owner,
                'next_action': 'Finance to resolve the conflicting delivery without erasing admitted money'}
        elif len(occurrences) > 1:
            duplicate_events.append({'event_id': event_id, 'source_refs': [_source_ref(r) for r in occurrences],
                                     'delivery_batches': [_values(r).get('Arrival batch') for r in occurrences]})
        if event_id not in admitted:
            batches = [_positive_integer(_values(r).get('Arrival batch')) for r in occurrences]
            first_batch = min((v for v in batches if v is not None), default=None)
            first = [r for r in occurrences if first_batch is not None and _positive_integer(_values(r).get('Arrival batch')) == first_batch]
            if not first:
                candidate = item_for(relevant[0])
                candidate['validation_errors'] = ['missing or invalid positive integer arrival batch']
                unresolved.append(candidate)
            # Same-batch conflicting payloads have no supplied authority order.
            if first and all(_payload(_values(r)) == _payload(_values(first[0])) for r in first):
                candidate = item_for(first[0])
                values = candidate['source_record']
                reasons = finance_errors(values, candidate['classification'], event_context, _cents)
                if candidate['classification'] == 'unresolved':
                    reasons.append('unknown Finance event vocabulary')
                if values.get('Claim reference') == claim_id and not reasons:
                    candidate['validation_context'] = deepcopy(event_context)
                    admitted[event_id] = candidate
                elif values.get('Claim reference') == claim_id:
                    candidate['validation_errors'] = reasons
                    unresolved.append(candidate)
        for record in relevant:
            item = item_for(record)
            canonical = admitted.get(event_id)
            same = canonical is not None and _payload(item['source_record']) == _payload(canonical['source_record'])
            item['admission_status'] = 'admitted-or-exact-replay' if same else 'held'
            if not same:
                item['classification'] = 'conflicting_event_id' if conflict else 'unresolved'
            history.append(item)
    for record in missing_id_records:
        item = item_for(record); item['classification'] = 'missing_event_id'
        item['validation_errors'] = ['immutable event identity missing']; history.append(item); unresolved.append(item)
    # Previously admitted facts remain observable even on a delta-only invocation.
    for event_id, item in prior.items():
        if not any(h['event_id'] == event_id and _payload(h['source_record']) == _payload(item['source_record']) for h in history):
            history.append(deepcopy(item))
    typed = list(admitted.values())
    payments = {item['event_id']: item for item in typed if item['classification'] == 'confirmed_payment'}
    confirmed_refunds = [deepcopy(item) for item in prior.values() if item['classification'] == 'confirmed_refund']
    recovered = defaultdict(int)
    for item in confirmed_refunds:
        recovered[item['original_activity_id']] += item['amount_cents']
    refund_candidates = [item for item in typed if item['classification'] == 'confirmed_refund' and item['event_id'] not in prior]
    refund_candidates.sort(key=lambda h: (_positive_integer(h['source_record'].get('Arrival batch')) or 0,
                                         utc_time(h['source_record']['Activity time (UTC)']), h['event_id']))
    for item in refund_candidates:
        original = payments.get(item['original_activity_id'])
        valid = original is not None and all(item['source_record'].get(k) == original['source_record'].get(k)
                                             for k in ('Request reference', 'Payee ID', 'Currency', 'Claim reference'))
        if valid:
            valid = (utc_time(item['source_record']['Activity time (UTC)']) >= utc_time(original['source_record']['Activity time (UTC)'])
                     and recovered[item['original_activity_id']] + item['amount_cents'] <= original['amount_cents'])
        if not valid:
            item['validation_errors'] = ['refund lacks matching settled request/payee/time or exceeds unrecovered transfer']
            unresolved.append(item); admitted.pop(item['event_id'], None)
        else:
            confirmed_refunds.append(item); recovered[item['original_activity_id']] += item['amount_cents']
    typed = list(admitted.values())
    invalid_ids = {item['event_id'] for item in unresolved}
    for item in history:
        if item['event_id'] in invalid_ids and item['event_id'] not in admitted:
            item['classification'] = 'unresolved'; item['admission_status'] = 'held'
    invalid_payments = [item for item in payments.values() if item["amount_cents"] is None]
    unresolved.extend(invalid_payments)
    confirmed_payment_cents = sum(item["amount_cents"] for item in payments.values() if item["amount_cents"] is not None)
    confirmed_refund_cents = sum(item["amount_cents"] for item in confirmed_refunds)
    net_confirmed_cents = confirmed_payment_cents - confirmed_refund_cents

    issues = list(event_issue_by_id.values())
    for number, item in enumerate(unresolved, 1):
        issue_id = f"finance-unresolved:{item['event_id'] or number}"
        issue = {
            "record_id": issue_id,
            "event_id": item["event_id"],
            "subject_type": "claim",
            "subject_id": claim_id,
            "revision": current_revision,
            "source_refs": [item["source_ref"]],
            "missing_or_return_reason": (
                f"Finance event {item['event_id']!r} held: {', '.join(item.get('validation_errors', ['unmatched event']))}"
            ),
            "owner": owner,
            "next_action": "Finance to confirm event meaning, amount, currency, or refund link from the native ledger",
        }
        issues.append(issue)
    obligation_history, recorded_obligation, recorded_problem = _recorded_obligations(
        history, claim_id=claim_id, current_revision=current_revision, revisions=revision_history or [],
    )
    if recorded_problem:
        issues.append({
            "record_id": f"finance-recorded-obligation:{claim_id}:{current_revision}",
            "subject_type": "claim", "subject_id": claim_id, "revision": current_revision,
            "source_refs": [e["source_ref"] for e in history if e["event_id"] in {r["event_id"] for r in obligation_history}],
            "owner": owner, "missing_or_return_reason": recorded_problem,
            "next_action": "Finance to confirm the obligation's request, amount, chronology and exact claim revision from retained source evidence",
        })
    obligation = None
    obligation_issue = None
    if authorized_obligation is not None:
        amount = authorized_obligation.get("amount_cents")
        obligation_revision = authorized_obligation.get("claim_revision")
        refs = authorized_obligation.get("source_refs")
        if (isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0
                and obligation_revision == current_revision and isinstance(refs, list)
                and refs and all(isinstance(ref, str) and ref for ref in refs)):
            obligation = {"amount_cents": amount, "claim_revision": obligation_revision, "source_refs": list(dict.fromkeys(refs))}
        else:
            obligation_issue = {
                "record_id": f"finance-obligation-invalid:{claim_id}:{current_revision}",
                "event_id": None,
                "subject_type": "claim",
                "subject_id": claim_id,
                "revision": current_revision,
                "source_refs": list(refs) if isinstance(refs, list) else [],
                "missing_or_return_reason": "authorized obligation is missing exact cents, current-revision match, or supporting source reference",
                "owner": owner,
                "next_action": "Finance to provide or confirm the authorized obligation for this claim revision",
            }
    else:
        obligation_issue = {
            "record_id": f"finance-obligation-missing:{claim_id}:{current_revision}",
            "event_id": None,
            "subject_type": "claim",
            "subject_id": claim_id,
            "revision": current_revision,
            "source_refs": [e["source_ref"] for e in history if e["event_id"] in {r["event_id"] for r in obligation_history}],
            "missing_or_return_reason": ("recorded Finance obligation exists, but current-revision reimbursement authorization and entitlement remain unconfirmed"
                                         if recorded_obligation else "no supported authorized obligation was supplied for this claim revision"),
            "owner": owner,
            "next_action": "Finance to provide or confirm the authorized obligation for this claim revision",
        }
    if obligation_issue is not None:
        issues.append(obligation_issue)

    has_unclassified_cash_event = any(item["classification"] == "unresolved" for item in history)
    event_set_complete = not unresolved and not conflicting_events and not missing_id_records and not has_unclassified_cash_event
    balance = None
    if obligation is not None and event_set_complete:
        balance = obligation["amount_cents"] - net_confirmed_cents

    ledger_balance = None
    if recorded_obligation is not None and event_set_complete and not recorded_problem:
        # Cash for a different/missing request cannot be silently applied to this ledger.
        cash_rows = [e for e in history if e['classification'] in {'confirmed_payment', 'confirmed_refund'}]
        if all(e['source_record'].get('Request reference') == recorded_obligation['request_id']
               and e['source_record'].get('Payee ID') == recorded_obligation['payee_id'] for e in cash_rows):
            ledger_balance = recorded_obligation['amount_cents'] - net_confirmed_cents
    if recorded_obligation is not None and event_set_complete and ledger_balance is None:
        issues.append({
            "record_id": f"finance-recorded-cash-link:{claim_id}:{current_revision}",
            "subject_type": "claim", "subject_id": claim_id, "revision": current_revision,
            "source_refs": [e["source_ref"] for e in history if e['classification'] in {'confirmed_payment', 'confirmed_refund', 'obligation_accepted'}],
            "owner": owner,
            "missing_or_return_reason": "Confirmed claim cash cannot be matched to the recorded obligation's request and payee",
            "next_action": "Finance to verify each cash event's request and payee link before calculating a ledger difference",
        })
    issues_by_owner = {}
    for issue in issues:
        issues_by_owner.setdefault(issue['owner'], []).append(issue)
    issues_by_owner = {key: sorted(value, key=lambda row: row['record_id']) for key, value in sorted(issues_by_owner.items())}
    invalidated = None
    if previous_reconciliation is not None:
        previous_revision = previous_reconciliation.get("claim_revision")
        if previous_revision != current_revision:
            invalidated = {
                "claim_revision": previous_revision,
                "reason": "material revision change invalidates the prior reconciliation basis",
                "prior_net_confirmed_cents": previous_reconciliation.get("net_confirmed_cents"),
                "prior_balance_cents": previous_reconciliation.get("balance_cents"),
                "prior_recorded_obligation": deepcopy(previous_reconciliation.get("recorded_obligation")),
                "next_action": "Revalidate exact revision authorization; historical ledger and cash remain retained",
            }
    revalidation_history = deepcopy((previous_reconciliation or {}).get("financial_revalidation_history", []))
    if invalidated is not None:
        revalidation_history.append(deepcopy(invalidated))
    return {
        "admitted_events": deepcopy(admitted),
        "event_context": deepcopy(event_context),
        "admitted_event_ids": list(admitted),
        "claim_id": claim_id,
        "claim_revision": current_revision,
        "revision_history": deepcopy(revision_history or []),
        "event_history": history,
        "event_ids": [item["event_id"] for item in history if item["event_id"] is not None],
        "duplicate_events": duplicate_events,
        "conflicting_events": conflicting_events,
        "confirmed_payment_event_ids": [item["event_id"] for item in payments.values() if item["amount_cents"] is not None],
        "confirmed_refund_event_ids": [item["event_id"] for item in confirmed_refunds],
        "pending_transfer_event_ids": [item["event_id"] for item in typed if item["classification"] == "pending_transfer"],
        "unresolved_event_ids": list(dict.fromkeys(item["event_id"] for item in unresolved if item["event_id"] is not None)),
        "finance_obligation_events": [item for item in history if item["classification"] == "obligation_accepted"],
        "recorded_obligation_history": obligation_history,
        "recorded_obligation": recorded_obligation,
        "recorded_ledger_balance_cents": ledger_balance,
        "reimbursement_entitlement_confirmed": False,
        "closure_authority_confirmed": False,
        "authorized_obligation": obligation,
        "confirmed_payment_cents": confirmed_payment_cents,
        "confirmed_refund_cents": confirmed_refund_cents,
        "net_confirmed_cents": net_confirmed_cents,
        "balance_cents": balance,
        "inputs_complete": balance is not None,
        "repair_issues": issues,
        "repair_issues_by_owner": issues_by_owner,
        "invalidated_previous_reconciliation": invalidated,
        "financial_revalidation_history": revalidation_history,
    }

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

    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_id_records: list[dict[str, Any]] = []
    for record in events:
        event_id = _values(record).get("Activity reference")
        if not isinstance(event_id, str) or not event_id:
            if _values(record).get("Claim reference") == claim_id:
                missing_id_records.append(record)
        else:
            by_id[event_id].append(record)

    relevant_occurrences: list[tuple[str | None, dict[str, Any], dict[str, Any], bool]] = []
    duplicate_events = []
    conflicting_events = []
    for event_id, occurrences in by_id.items():
        relevant = [record for record in occurrences if _values(record).get("Claim reference") == claim_id]
        if not relevant:
            continue
        payloads = [_payload(_values(record)) for record in occurrences]
        conflict = any(payload != payloads[0] for payload in payloads[1:])
        for record in relevant:
            relevant_occurrences.append((event_id, record, _values(record), conflict))
        if conflict:
            conflicting_events.append({
                "event_id": event_id,
                "source_refs": [_source_ref(record) for record in occurrences],
                "payloads": payloads,
            })
        elif len(occurrences) > 1:
            duplicate_events.append({
                "event_id": event_id,
                "source_refs": [_source_ref(record) for record in occurrences],
                "delivery_batches": [_values(record).get("Arrival batch") for record in occurrences],
            })
    relevant_occurrences.extend((None, record, _values(record), True) for record in missing_id_records)
    relevant_occurrences.sort(key=lambda row: (
        _positive_integer(row[2].get("Arrival batch")) or 0,
        int(row[1].get("row") or 0),
        row[0] or "",
    ))

    history = []
    event_issue_by_id: dict[str, dict[str, Any]] = {}
    typed = []
    unresolved = []
    for event_id, record, values, conflict in relevant_occurrences:
        event_type = values.get("Activity type")
        classification = classes.get(event_type, "unresolved")
        item = {
            "event_id": event_id,
            "source_ref": _source_ref(record),
            "source_record": deepcopy(values),
            "event_type": event_type,
            "classification": (
                "conflicting_event_id" if conflict and event_id else
                "missing_event_id" if conflict else classification
            ),
            "amount_cents": _cents(values.get("Amount (EUR)")),
            "obligation_cents": _cents(values.get("Obligation (EUR)")),
            "currency": values.get("Currency"),
            "original_activity_id": values.get("Original activity reference"),
        }
        history.append(item)
        if conflict:
            if event_id:
                event_issue_by_id[event_id] = {
                    "record_id": f"finance-event-conflict:{event_id}",
                    "event_id": event_id,
                    "subject_type": "claim",
                    "subject_id": claim_id,
                    "revision": current_revision,
                    "missing_or_return_reason": "same Finance event ID has conflicting source content; none of its occurrences were counted",
                    "source_refs": [_source_ref(row) for row in by_id[event_id]],
                    "owner": owner,
                    "next_action": "Finance to resolve the source record conflict",
                }
            else:
                event_issue_by_id[f"missing:{record.get('locator')}"] = {
                    "record_id": f"finance-event-missing-id:{record.get('row') or len(event_issue_by_id) + 1}",
                    "event_id": None,
                    "subject_type": "claim",
                    "subject_id": claim_id,
                    "revision": current_revision,
                    "missing_or_return_reason": "Finance event has no activity reference and cannot be safely deduplicated or counted",
                    "source_refs": [_source_ref(record)],
                    "owner": owner,
                    "next_action": "Finance to identify this ledger event and provide its native activity reference",
                }
            continue
        if classification == "unresolved":
            unresolved.append(item)
            continue
        if classification in {"confirmed_payment", "confirmed_refund"}:
            if values.get("Currency") != "EUR" or item["amount_cents"] is None:
                unresolved.append(item)
                continue
        typed.append(item)

    payments = {item["event_id"]: item for item in typed if item["classification"] == "confirmed_payment"}
    confirmed_refunds: list[dict[str, Any]] = []
    refund_candidates = list({item["event_id"]: item for item in typed if item["classification"] == "confirmed_refund"}.values())
    refund_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in refund_candidates:
        original_id = item["original_activity_id"]
        original = payments.get(original_id) if isinstance(original_id, str) else None
        if original is None or original.get("currency") != item.get("currency"):
            unresolved.append(item)
            continue
        refund_groups[original_id].append(item)
    for original_id, refunds in refund_groups.items():
        original = payments[original_id]
        refund_total = sum(item["amount_cents"] for item in refunds)
        if refund_total > original["amount_cents"]:
            unresolved.extend(refunds)
            continue
        confirmed_refunds.extend(refunds)

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
                f"Finance event {item['event_id']!r} is not sufficiently classified or linked for cash reconciliation"
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

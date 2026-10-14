"""Synthetic fixtures for policy-independent financial reconciliation."""

from copy import deepcopy

from travel_claim.finance import reconcile_finance_events


def _finance_row(row, event_id, event_type, *, batch=1, claim="C-SYN-01", amount=None,
                 obligation=None, original=None, currency="EUR"):
    values = {
        "Activity reference": event_id,
        "Arrival batch": batch,
        "Activity type": event_type,
        "Claim reference": claim,
        "Currency": currency,
        "Reason": f"SYNTHETIC fixture {event_type}",
    }
    if amount is not None:
        values["Amount (EUR)"] = amount
    if obligation is not None:
        values["Obligation (EUR)"] = obligation
    if original is not None:
        values["Original activity reference"] = original
    return {
        "source_id": "synthetic-finance-ledger",
        "source_sha256": "c" * 64,
        "locator": f"synthetic tab 'Finance activity', row {row}",
        "row": row,
        "values": {
            key: {"value": value, "source_text": str(value), "cell": f"A{row}"}
            for key, value in values.items()
        },
    }


def _obligation(amount=15_000, revision=1):
    return {"amount_cents": amount, "claim_revision": revision, "source_refs": ["synthetic:authorization#1"]}


def test_payments_refunds_obligations_and_pending_transfers_are_separate():
    events = [
        _finance_row(1, "F-SYN-ACCEPT", "accepted", obligation=150.00),
        _finance_row(2, "F-SYN-PAY-1", "settled", amount=100.01),
        _finance_row(3, "F-SYN-PAY-2", "settled", amount=50.00),
        _finance_row(4, "F-SYN-REFUND", "refund", amount=20.00, original="F-SYN-PAY-1"),
        _finance_row(5, "F-SYN-PENDING", "transfer_pending", amount=79.99),
    ]
    result = reconcile_finance_events(
        events,
        claim_id="C-SYN-01",
        current_revision=1,
        authorized_obligation=_obligation(),
        source_classifications={"transfer_pending": "pending_transfer"},
    )
    assert result["finance_obligation_events"][0]["obligation_cents"] == 15_000
    assert result["authorized_obligation"]["amount_cents"] == 15_000
    assert result["confirmed_payment_cents"] == 15_001
    assert result["confirmed_refund_cents"] == 2_000
    assert result["net_confirmed_cents"] == 13_001
    assert result["balance_cents"] == 1_999
    assert result["pending_transfer_event_ids"] == ["F-SYN-PENDING"]
    assert "F-SYN-PENDING" not in result["confirmed_payment_event_ids"]
    assert result["event_history"][0]["source_record"]["Activity type"] == "accepted"
    assert result["event_history"][3]["original_activity_id"] == "F-SYN-PAY-1"


def test_replay_is_idempotent_and_keeps_each_occurrence_source_trace():
    payment = _finance_row(5, "F-SYN-PAY", "settled", batch=1, amount=10.00)
    replay = _finance_row(22, "F-SYN-PAY", "settled", batch=4, amount=10.00)
    result = reconcile_finance_events(
        [payment, replay], claim_id="C-SYN-01", current_revision=1,
        authorized_obligation=_obligation(amount=1_000),
    )
    assert result["event_ids"] == ["F-SYN-PAY", "F-SYN-PAY"]
    assert len(result["event_history"]) == 2
    assert len(result["confirmed_payment_event_ids"]) == 1
    assert result["confirmed_payment_cents"] == 1_000
    assert result["duplicate_events"][0]["delivery_batches"] == [1, 4]
    assert [item["source_ref"]["locator"] for item in result["event_history"]] == [
        "synthetic tab 'Finance activity', row 5",
        "synthetic tab 'Finance activity', row 22",
    ]


def test_conflicting_duplicate_ids_and_unknown_events_open_owner_grouped_issues():
    events = [
        _finance_row(1, "F-SYN-CONFLICT", "settled", amount=10.00),
        _finance_row(2, "F-SYN-CONFLICT", "settled", amount=11.00, batch=2),
        _finance_row(3, "F-SYN-UNKNOWN", "mystery_state", amount=20.00),
    ]
    result = reconcile_finance_events(
        events, claim_id="C-SYN-01", current_revision=1,
        authorized_obligation=_obligation(), owner="FIN-SYN-01",
    )
    assert result["conflicting_events"][0]["event_id"] == "F-SYN-CONFLICT"
    assert len(result["conflicting_events"][0]["source_refs"]) == 2
    assert result["confirmed_payment_cents"] == 0
    assert result["balance_cents"] is None
    assert result["unresolved_event_ids"] == ["F-SYN-UNKNOWN"]
    assert list(result["repair_issues_by_owner"]) == ["FIN-SYN-01"]
    assert {issue["record_id"] for issue in result["repair_issues_by_owner"]["FIN-SYN-01"]} == {
        "finance-event-conflict:F-SYN-CONFLICT", "finance-unresolved:F-SYN-UNKNOWN",
    }
    assert all(issue["source_refs"] for issue in result["repair_issues"])


def test_refund_must_link_to_known_payment_and_cannot_exceed_it():
    events = [
        _finance_row(1, "F-SYN-PAY", "settled", amount=10.00),
        _finance_row(2, "F-SYN-REFUND", "refund", amount=10.01, original="F-SYN-PAY"),
        _finance_row(3, "F-SYN-REFUND-ORPHAN", "refund", amount=1.00, original="F-NOT-FOUND"),
    ]
    result = reconcile_finance_events(
        events, claim_id="C-SYN-01", current_revision=1,
        authorized_obligation=_obligation(amount=1_000),
    )
    assert result["confirmed_payment_cents"] == 1_000
    assert result["confirmed_refund_cents"] == 0
    assert result["net_confirmed_cents"] == 1_000
    assert result["balance_cents"] is None
    assert set(result["unresolved_event_ids"]) == {"F-SYN-REFUND", "F-SYN-REFUND-ORPHAN"}


def test_revision_correction_preserves_history_invalidates_prior_and_rejects_stale_authorization():
    prior = {
        "claim_revision": 1,
        "net_confirmed_cents": 10_000,
        "balance_cents": 5_000,
        "event_history": [{"event_id": "F-SYN-PAY", "source_ref": "prior"}],
    }
    prior_copy = deepcopy(prior)
    revisions = [
        {"revision": 1, "source_ref": "synthetic:claim#1"},
        {"revision": 2, "source_ref": "synthetic:claim#2"},
    ]
    result = reconcile_finance_events(
        [_finance_row(1, "F-SYN-PAY", "settled", amount=100.00)],
        claim_id="C-SYN-01",
        current_revision=2,
        authorized_obligation=_obligation(amount=15_000, revision=1),
        revision_history=revisions,
        previous_reconciliation=prior,
    )
    assert result["revision_history"] == revisions
    assert result["confirmed_payment_cents"] == 10_000
    assert result["authorized_obligation"] is None
    assert result["balance_cents"] is None
    assert result["invalidated_previous_reconciliation"]["claim_revision"] == 1
    assert result["repair_issues_by_owner"]["Finance"][0]["record_id"] == "finance-obligation-invalid:C-SYN-01:2"
    assert prior == prior_copy


def test_unknown_or_missing_authorized_obligation_never_yields_a_balance():
    result = reconcile_finance_events(
        [_finance_row(1, "F-SYN-PAY", "settled", amount=10.00)],
        claim_id="C-SYN-01", current_revision=1,
    )
    assert result["net_confirmed_cents"] == 1_000
    assert result["balance_cents"] is None
    assert result["repair_issues_by_owner"]["Finance"][0]["record_id"] == "finance-obligation-missing:C-SYN-01:1"

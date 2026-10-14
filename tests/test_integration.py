"""Synthetic end-to-end integration tests; no real arrival batch is consumed."""

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import pytest

from travel_claim.integration import integrate_arrival_batch


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "snapshot.schema.json").read_text(encoding="utf-8"))


def _claim(claim_id, revision, *, trip_id, trip_revision=1, batch=1, employee="EMP-SYN-01"):
    return {
        "source_id": "synthetic-claim-binder",
        "source_sha256": "a" * 64,
        "locator": f"PDF page {revision} (SYNTHETIC {claim_id} revision {revision})",
        "page": revision,
        "fields": [
            {"label": "Claim reference", "value": claim_id},
            {"label": "Revision", "value": str(revision)},
            {"label": "Arrival batch", "value": str(batch)},
            {"label": "Employee", "value": employee},
            {"label": "Trip reference", "value": trip_id},
            {"label": "Trip revision", "value": str(trip_revision)},
            {"label": "Claim reason", "value": "SYNTHETIC fixture"},
        ],
        "text": f"SYNTHETIC TEST FIXTURE ONLY: {claim_id} revision {revision}",
    }


def _row(row, source_id, tab, **values):
    return {
        "source_id": source_id,
        "source_sha256": "b" * 64,
        "locator": f"tab '{tab}', row {row} (SYNTHETIC)",
        "row": row,
        "values": {
            key: {"value": value, "source_text": str(value), "cell": f"A{row}"}
            for key, value in values.items()
        },
    }


def _decision(row, decision_id, claim_id, revision, batch=1):
    return _row(
        row, "synthetic-review-ledger", "Review ledger",
        **{
            "Decision reference": decision_id,
            "Arrival batch": batch,
            "Subject type": "claim",
            "Subject reference": claim_id,
            "Revision": revision,
            "Review roles": "administration",
            "Reviewer": "ADMIN-SYN-01",
            "Outcome": "approve",
            "Reason": "SYNTHETIC observed decision; no policy conclusion",
            "Decision time (UTC)": "2026-09-01T12:00:00",
        },
    )


def _finance(row, event_id, claim_id, batch, event_type, *, amount=None, obligation=None):
    values = {
        "Activity reference": event_id,
        "Arrival batch": batch,
        "Activity type": event_type,
        "Request reference": f"REQ-{claim_id}",
        "Claim reference": claim_id,
        "Finance officer": "FIN-SYN-01",
        "Payee ID": "EMP-SYN-01",
        "Currency": "EUR",
        "Reason": f"SYNTHETIC Finance fixture: {event_type}",
    }
    if amount is not None:
        values["Amount (EUR)"] = amount
    if obligation is not None:
        values["Obligation (EUR)"] = obligation
    return _row(row, "synthetic-finance-register", "Finance activity", **values)


def _cancel(row, event_id, cancellation_id, action, subject_type, *, batch, initiation=None):
    is_permit = subject_type == "permit"
    values = {
        "Cancellation activity reference": event_id,
        "Cancellation reference": cancellation_id,
        "Action": action,
        "Cancelled subject": subject_type,
        "Trip reference": "T-SYN-01",
        "Trip revision": 1,
        "Permit reference": "P-SYN-01",
        "Permit revision": 1,
        "Acting employee or supervisor": "EMP-SYN-01",
        "Activity time (UTC)": f"2026-09-0{batch}T09:00:00",
        "Arrival batch": batch,
        "Business reason": "SYNTHETIC client rescheduling",
    }
    if action == "confirmed":
        values["Initiation activity reference"] = initiation
        values["Effective time (UTC)"] = f"2026-09-0{batch}T09:30:00"
    return _row(row, "synthetic-travel-register", "Travel cancellations", **values)


def _parsed_fixture():
    return {
        "run_id": "run-synthetic-integration",
        "case_clock": None,
        "unresolved_issues": [
            {
                "record_id": "scenario-case-clock",
                "subject_type": "scenario",
                "subject_id": "arrival-batch-clock",
                "affected_scope": "all batches",
                "reason": "SYNTHETIC fixture: clock withheld",
                "owner": "Exercise facilitator",
                "next_action": "provide the scenario clock",
                "evidence_needed": "explicit date, time, and zone",
            },
            {
                "record_id": "reimbursement-policy-pol-2026-2",
                "subject_type": "policy",
                "subject_id": "POL-2026.2",
                "affected_scope": "eligibility and entitlement",
                "reason": "SYNTHETIC fixture: policy withheld",
                "owner": "Travel Administration Lead",
                "next_action": "provide an authorized native policy export",
                "evidence_needed": "complete policy content",
            },
        ],
        "records": {
            "claim_revisions": [
                _claim("C-SYN-01", 1, trip_id="T-SYN-01", batch=1),
                _claim("C-SYN-02", 1, trip_id="T-SYN-02", batch=1, employee="EMP-SYN-02"),
                _claim("C-SYN-01", 2, trip_id="T-SYN-01", batch=3),
            ],
            "trips": [
                _row(6, "synthetic-travel-register", "Trips", **{
                    "Trip reference": "T-SYN-01", "Trip revision": 1,
                    "Permit reference": "P-SYN-01", "Permit revision": 1,
                }),
                _row(7, "synthetic-travel-register", "Trips", **{
                    "Trip reference": "T-SYN-02", "Trip revision": 1,
                    "Permit reference": "P-SYN-02", "Permit revision": 1,
                }),
            ],
            "decisions": [
                _decision(6, "D-SYN-01-R1", "C-SYN-01", 1),
                _decision(7, "D-SYN-02-R1", "C-SYN-02", 1),
            ],
            "finance_events": [
                _finance(6, "F-SYN-01-SETTLED", "C-SYN-01", 2, "settled", amount=10.00),
                _finance(7, "F-SYN-01-PENDING", "C-SYN-01", 2, "transfer_pending", amount=5.00),
                _finance(8, "F-SYN-02-SETTLED", "C-SYN-02", 2, "settled", amount=4.00),
            ],
            "cancellation_activities": [
                _cancel(6, "TC-SYN-TRIP-REQ", "TC-SYN-TRIP", "requested", "trip", batch=1),
                _cancel(7, "TC-SYN-PERMIT-REQ", "TC-SYN-PERMIT", "requested", "permit", batch=1),
                _cancel(8, "TC-SYN-TRIP-CFM", "TC-SYN-TRIP", "confirmed", "trip", batch=2,
                        initiation="TC-SYN-TRIP-REQ"),
                _cancel(9, "TC-SYN-PERMIT-CFM", "TC-SYN-PERMIT", "confirmed", "permit", batch=2,
                        initiation="TC-SYN-PERMIT-REQ"),
            ],
        },
    }


def _integrate(parsed, batch, *, previous=None, authorization_revision=1, include_unaffected_authorization=True):
    return integrate_arrival_batch(
        parsed,
        arrival_batch=batch,
        run_id="run-synthetic-integration",
        batch_id=f"arrival-{batch:03}",
        source_binding={"path": "sources.json", "sha256": "d" * 64},
        predecessor=(
            {"path": f"batches/arrival-{batch - 1:03}.json", "sha256": "e" * 64}
            if batch > 1 else None
        ),
        prior_result=previous,
        authorized_obligations=dict(
            {"C-SYN-01": {
                "amount_cents": 2_000, "claim_revision": authorization_revision,
                "source_refs": ["synthetic:authorization#C-SYN-01"],
            }}
            | ({"C-SYN-02": {
                "amount_cents": 1_000, "claim_revision": 1,
                "source_refs": ["synthetic:authorization#C-SYN-02"],
            }} if include_unaffected_authorization else {})
        ),
        source_classifications={"transfer_pending": "pending_transfer"},
    )


def _assert_snapshot_shape(result):
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    assert list(validator.iter_errors(result["snapshot"])) == []
    issue_ids = {issue["record_id"] for issue in result["snapshot"]["issues"]}
    for cancellation in result["snapshot"]["travel_cancellations"]:
        assert set(cancellation["issue_record_ids"]) <= issue_ids
    cancellation_ids = {
        event_id for row in result["snapshot"]["travel_cancellations"]
        for event_id in row["admitted_cancellation_event_ids"]
    }
    assert cancellation_ids.isdisjoint(result["snapshot"]["admitted_event_ids"])


def test_integrates_batches_revisions_decisions_finance_and_independent_cancellations():
    parsed = _parsed_fixture()
    first = _integrate(parsed, 1)
    _assert_snapshot_shape(first)
    assert first["snapshot"]["batch_id"] == "arrival-001"
    assert [row["status"] for row in first["snapshot"]["travel_cancellations"]] == ["requested", "requested"]
    assert {row["target_type"] for row in first["snapshot"]["travel_cancellations"]} == {"trip", "permit"}
    assert first["snapshot"]["admitted_event_ids"] == []
    assert {row["record_id"] for row in first["snapshot"]["issues"]} >= {
        "scenario-case-clock", "reimbursement-policy-pol-2026-2",
    }
    decisions = first["decision_history"]
    assert len(decisions) == 2
    assert all(row["applied"] is False for row in decisions)
    assert {row["structural_match"] for row in decisions} == {"revision_match_current"}

    second = _integrate(parsed, 2, previous=first)
    _assert_snapshot_shape(second)
    cancellations = second["snapshot"]["travel_cancellations"]
    assert all(row["status"] == "confirmed" for row in cancellations)
    assert cancellations[0]["confirmed_at"].endswith("Z")
    assert cancellations[0]["effective_at"].endswith("Z")
    cancellation_ids = {event_id for row in cancellations for event_id in row["admitted_cancellation_event_ids"]}
    assert cancellation_ids.isdisjoint(second["snapshot"]["admitted_event_ids"])
    assert {"F-SYN-01-SETTLED", "F-SYN-02-SETTLED"} <= set(second["snapshot"]["admitted_event_ids"])
    c1 = second["finance_reconciliations"]["C-SYN-01"]
    assert c1["confirmed_payment_cents"] == 1_000
    assert c1["pending_transfer_event_ids"] == ["F-SYN-01-PENDING"]
    assert c1["balance_cents"] == 1_000
    assert all(row["financial_status"] == "unresolved" for row in cancellations)
    assert len(second["domain"]["decision_records"]) == 2
    assert len(second["domain"]["finance_records"]) == 3
    assert len(second["domain"]["cancellation_records"]) == 4

    third = _integrate(parsed, 3, previous=second, authorization_revision=1,
                       include_unaffected_authorization=False)
    _assert_snapshot_shape(third)
    claims = {row["claim_id"]: row for row in third["snapshot"]["claims"]}
    assert claims["C-SYN-01"]["revision"] == 2
    assert claims["C-SYN-01"]["decision_ids"] == []
    assert claims["C-SYN-01"]["balance_cents"] is None  # revision-1 authorization is stale
    assert claims["C-SYN-02"]["revision"] == 1
    assert claims["C-SYN-02"]["decision_ids"] == ["D-SYN-02-R1"]
    assert claims["C-SYN-02"]["balance_cents"] == 600  # unaffected authorization is carried forward
    assert third["domain"]["material_corrections"][0]["invalidated_decision_ids"] == ["D-SYN-01-R1"]
    assert third["domain"]["material_corrections"][0]["preserved_finance_event_ids"] == [
        "F-SYN-01-SETTLED", "F-SYN-01-PENDING",
    ]
    assert [ref["source_id"] for ref in third["domain"]["material_corrections"][0]["source_refs"]] == [
        "synthetic-claim-binder", "synthetic-claim-binder",
    ]
    assert all(ref["source_sha256"] for ref in third["domain"]["material_corrections"][0]["source_refs"])
    tasks = {item["item_id"] for owner_items in third["repair_queue_by_owner"].values() for item in owner_items}
    assert {f"correction:C-SYN-01:r2:{area}" for area in (
        "expense-evidence", "calculations", "trip-permit", "approvals", "finance-authorization",
    )} <= tasks
    assert "TC-SYN-TRIP-CFM" not in third["snapshot"]["admitted_event_ids"]
    assert "TC-SYN-PERMIT-CFM" not in third["snapshot"]["admitted_event_ids"]


def test_batch_order_and_replay_are_enforced_without_rewriting_prior_state():
    parsed = _parsed_fixture()
    with pytest.raises(ValueError, match="expected 1, got 2"):
        _integrate(parsed, 2)
    first = _integrate(parsed, 1)
    serialized = json.dumps(first, sort_keys=True)
    assert _integrate(parsed, 1, previous=first) == first
    assert json.dumps(first, sort_keys=True) == serialized
    changed = deepcopy(parsed)
    changed["records"]["decisions"][0]["values"]["Outcome"]["value"] = "return"
    with pytest.raises(ValueError, match="conflicting replay"):
        _integrate(changed, 1, previous=first)


def test_decisions_with_missing_subject_revisions_create_traceable_repairs():
    parsed = _parsed_fixture()
    parsed["records"]["decisions"].append(_decision(8, "D-SYN-UNKNOWN", "C-UNKNOWN", 4))
    result = _integrate(parsed, 1)
    issue = next(item for item in result["domain"]["repair_queue"]["items"].values()
                 if item["item_id"] == "decision-match:D-SYN-UNKNOWN")
    assert issue["subject_type"] == "claim"
    assert issue["subject_id"] == "C-UNKNOWN"
    assert issue["revision"] == 4
    assert issue["source_refs"] == [
        "synthetic-review-ledger@" + "b" * 64 + "#tab 'Review ledger', row 8 (SYNTHETIC)"
    ]
    assert issue["owner"] == "Travel Administration Lead"


def test_serialized_projection_preserves_blockers_events_timestamps_and_queue_trace():
    parsed = _parsed_fixture()
    first = _integrate(parsed, 1)
    second = _integrate(parsed, 2, previous=first)
    serialized = json.dumps(second, ensure_ascii=False, indent=2)
    loaded = json.loads(serialized)
    assert loaded["snapshot"]["schema_version"] == "travel-claim-snapshot/2"
    assert loaded["domain"]["cancellation_records"][2]["values"]["Activity time (UTC)"]["value"] == "2026-09-02T09:00:00"
    assert loaded["snapshot"]["travel_cancellations"][0]["confirmed_at"] == "2026-09-02T09:00:00Z"
    assert loaded["snapshot"]["issues"]
    assert loaded["repair_queue_by_owner"]["Finance"]
    assert list(Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(loaded["snapshot"])) == []

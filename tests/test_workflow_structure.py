"""Structural workflow tests use conspicuously synthetic records unless noted."""

import json
from pathlib import Path

import pytest

from partial_response_fixtures import retained_response

from travel_claim.outputs import (
    add_repair_item,
    apply_partial_response,
    load_repair_queue,
    new_repair_queue,
    owner_grouped_view,
    update_repair_item,
    write_repair_queue,
)
from travel_claim.parsing import parse_retained_run
from travel_claim.workflow import (
    build_revision_history,
    deduplicate_activity_records,
    match_decisions_to_subjects,
    reduce_cancellation_activities,
)


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "artifacts/runs/source-capture-20261014T100034Z"


def _claim(claim_id, revision, trip_id="T-SYN-01", trip_revision="1", batch="1"):
    return {
        "source_id": "synthetic-claims",
        "source_sha256": "a" * 64,
        "locator": f"synthetic fixture claim {claim_id} revision {revision}",
        "claim_id": claim_id,
        "fields": [
            {"label": "Claim reference", "value": claim_id},
            {"label": "Revision", "value": str(revision)},
            {"label": "Trip reference", "value": trip_id},
            {"label": "Trip revision", "value": trip_revision},
            {"label": "Arrival batch", "value": batch},
        ],
        "text": f"SYNTHETIC TEST FIXTURE ONLY: {claim_id} revision {revision}",
    }


def _workbook_record(row, **values):
    return {
        "source_id": "synthetic-register",
        "source_sha256": "b" * 64,
        "locator": f"synthetic tab 'Fixture', row {row}",
        "row": row,
        "values": {key: {"value": value, "source_text": str(value), "cell": f"A{row}"}
                   for key, value in values.items()},
    }


def _cancellation_row(row, *, event_id, cancellation_id, action, target_type="permit",
                      target_id="P-SYN-01", target_revision=1, batch=1, initiation=None,
                      effective=None):
    return _workbook_record(
        row,
        **{
            "Cancellation activity reference": event_id,
            "Cancellation reference": cancellation_id,
            "Action": action,
            "Cancelled subject": target_type,
            "Trip reference": "T-SYN-01",
            "Trip revision": 1,
            "Permit reference": target_id if target_type == "permit" else "P-SYN-01",
            "Permit revision": target_revision if target_type == "permit" else 1,
            "Initiation activity reference": initiation,
            "Arrival batch": batch,
            "Acting employee or supervisor": "EMP-SYN-01" if action == "requested" else "SUP-SYN-01",
            "Activity time (UTC)": "2026-11-13T08:00:00" if action == "requested" else "2026-11-14T08:00:00",
            "Effective time (UTC)": effective,
        },
    )


def test_revision_history_and_decision_matching_are_structural_only():
    # Synthetic revisions deliberately separate claim, trip, and permit version numbers.
    parsed = {
        "records": {
            "claim_revisions": [_claim("C-SYN-01", 1), _claim("C-SYN-01", 2, trip_revision="1", batch="3")],
            "trips": [
                _workbook_record(6, **{"Trip reference": "T-SYN-01", "Trip revision": 1,
                                      "Permit reference": "P-SYN-01", "Permit revision": 1}),
                _workbook_record(7, **{"Trip reference": "T-SYN-01", "Trip revision": 2,
                                      "Permit reference": "P-SYN-01", "Permit revision": 1}),
            ],
        }
    }
    history = build_revision_history(parsed)
    assert [row["revision"] for row in history["claim"]["C-SYN-01"]["revisions"]] == [1, 2]
    assert history["claim"]["C-SYN-01"]["current_revision"] == 2
    assert history["trip"]["T-SYN-01"]["current_revision"] == 2
    assert history["permit"]["P-SYN-01"]["current_revision"] == 1
    assert history["claim"]["C-SYN-01"]["revisions"][1]["trip_revision"] == 1

    decisions = [
        _workbook_record(10, **{"Decision reference": "D-SYN-OLD", "Subject type": "claim",
                                "Subject reference": "C-SYN-01", "Revision": 1, "Outcome": "approve"}),
        _workbook_record(11, **{"Decision reference": "D-SYN-UNKNOWN", "Subject type": "trip",
                                "Subject reference": "T-SYN-01", "Revision": 9, "Outcome": "return"}),
    ]
    matches = match_decisions_to_subjects(decisions, history)
    assert [row["structural_match"] for row in matches] == ["revision_match_historical", "revision_not_found"]
    assert [row["applied"] for row in matches] == [False, False]
    assert matches[0]["observed_outcome"] == "approve"  # preserved observation; no approval is performed


def test_cancellation_state_machine_keeps_trip_and_permit_processes_independent():
    events = [
        _cancellation_row(6, event_id="TC-SYN-P-REQ", cancellation_id="TC-SYN-P",
                          action="requested", target_type="permit", target_id="P-SYN-01", batch=1),
        _cancellation_row(7, event_id="TC-SYN-T-REQ", cancellation_id="TC-SYN-T",
                          action="requested", target_type="trip", target_id="T-SYN-01", batch=1),
        _cancellation_row(8, event_id="TC-SYN-P-CFM", cancellation_id="TC-SYN-P",
                          action="confirmed", target_type="permit", target_id="P-SYN-01", batch=2,
                          initiation="TC-SYN-P-REQ", effective="2026-11-14T08:00:00Z"),
    ]
    result = reduce_cancellation_activities(events,
        trips=[_workbook_record(1, **{"Trip reference": "T-SYN-01", "Trip revision": 1,
            "Employee ID": "EMP-SYN-01", "Permit reference": "P-SYN-01", "Permit revision": 1})],
        people=[_workbook_record(1, **{"Employee ID": "EMP-SYN-01", "Supervisor": "SUP-SYN-01"})],
        clock={"date": "2026-11-15", "timezone": "Europe/Amsterdam"})
    assert result["processes"]["TC-SYN-P"]["state"] == "confirmed"
    assert result["processes"]["TC-SYN-T"]["state"] == "requested"
    assert result["processes"]["TC-SYN-T"]["next_action"] == "await a linked confirmation activity"
    assert result["finance_effects"] == []
    assert result["claim_effects"] == []
    assert result["processes"]["TC-SYN-P"]["target"] == {
        "subject_type": "permit", "subject_id": "P-SYN-01", "revision": 1,
    }


def test_event_deduplication_is_replay_safe_and_flags_same_id_payload_conflicts():
    # Synthetic Finance-like event IDs; arrival batch is delivery metadata.
    first = _workbook_record(6, **{"Activity reference": "F-SYN-01", "Arrival batch": 2,
                                  "Activity type": "settled", "Amount (EUR)": 100.0,
                                  "Claim reference": "C-SYN-01"})
    replay = _workbook_record(31, **{"Activity reference": "F-SYN-01", "Arrival batch": 4,
                                    "Activity type": "settled", "Amount (EUR)": 100.0,
                                    "Claim reference": "C-SYN-01"})
    changed = _workbook_record(32, **{"Activity reference": "F-SYN-01", "Arrival batch": 4,
                                      "Activity type": "settled", "Amount (EUR)": 120.0,
                                      "Claim reference": "C-SYN-01"})
    exact = deduplicate_activity_records([first, replay], id_field="Activity reference")
    assert len(exact["unique_events"]) == 1
    assert exact["duplicates"][0]["delivery_batches"] == [2, 4]
    assert exact["conflicts"] == []
    conflict = deduplicate_activity_records([first, changed], id_field="Activity reference")
    assert conflict["unique_events"] == []
    assert conflict["conflicts"][0]["event_id"] == "F-SYN-01"


def test_actual_retained_activity_replays_are_deduplicated_and_cancellation_ids_are_separate(tmp_path):
    parsed = parse_retained_run(CAPTURE, output_path=tmp_path / "parsed.json")
    history = build_revision_history(parsed)
    c09 = history["claim"]["C09"]
    assert [(row["revision"], row["trip_id"], row["trip_revision"])
            for row in c09["revisions"]] == [(1, "T09", 1), (2, "T09B", 1)]
    assert c09["current_revision"] == 2
    matched = match_decisions_to_subjects(parsed["records"]["decisions"], history)
    assert len(matched) == 307
    assert all(row["applied"] is False for row in matched)
    assert {row["structural_match"] for row in matched} == {
        "revision_match_current", "revision_match_historical",
    }

    finance = deduplicate_activity_records(parsed["records"]["finance_events"], id_field="Activity reference")
    assert len(finance["unique_events"]) == 219
    assert finance["conflicts"] == []
    assert finance["duplicates"][0]["event_id"] == "F-C01-1"
    assert finance["duplicates"][0]["delivery_batches"] == [2.0, 4.0]

    cancellations = reduce_cancellation_activities(parsed["records"]["cancellation_activities"],
        trips=parsed['records']['trips'],
        people=next(s['records'] for s in parsed['workbook_sheets'] if s['name'] == 'People'),
        clock={'date': '2026-11-15', 'timezone': 'Europe/Amsterdam'})
    assert len(cancellations["duplicate_events"]) == 1
    assert cancellations["duplicate_events"][0]["event_id"] == "TC122-confirmed"
    assert len(cancellations["processes"]) == 4
    assert {process["target"]["subject_type"] for process in cancellations["processes"].values()} == {"trip", "permit"}
    assert all(process["state"] == "confirmed" for process in cancellations["processes"].values())
    assert cancellations["issues"] == []
    assert cancellations["finance_effects"] == [] and cancellations["claim_effects"] == []


def test_repair_item_updates_reopen_new_revision_and_keep_owner_history(tmp_path):
    queue = new_repair_queue()
    add_repair_item(
        queue, item_id="repair-C-SYN-01-receipt", subject_type="claim", subject_id="C-SYN-01",
        revision=1, source_refs=["synthetic/receipt-register#row-1"],
        missing_or_return_reason="SYNTHETIC FIXTURE: receipt needed", owner="EMP-SYN-01",
        next_action="provide the identified receipt", run_id="run-synthetic", batch_id="batch-synthetic-1",
    )
    outcomes = retained_response(tmp_path / "response-evidence", queue, "response-synthetic-1",
                                 {"repair-C-SYN-01-receipt": {"outcome": "supported"}})
    apply_partial_response(
        queue, response_id="response-synthetic-1", evidence_directory=tmp_path / "response-evidence",
        item_outcomes=outcomes,
        run_id="run-synthetic", batch_id="batch-synthetic-2",
    )
    path = tmp_path / "repair-queue.json"
    write_repair_queue(queue, path)

    update_repair_item(
        queue, item_id="repair-C-SYN-01-receipt", update_id="update-synthetic-1",
        run_id="run-synthetic", batch_id="batch-synthetic-3", revision=2,
        source_refs=["synthetic/receipt-register#row-1", "synthetic/correction#C-SYN-01-r2"],
        missing_or_return_reason="SYNTHETIC FIXTURE: corrected revision requires evidence recheck",
        owner="ADMIN-SYN-01", next_action="recheck receipt against revision 2",
    )
    before_replay = json.dumps(queue, sort_keys=True)
    update_repair_item(
        queue, item_id="repair-C-SYN-01-receipt", update_id="update-synthetic-1",
        run_id="run-synthetic", batch_id="batch-synthetic-3", revision=2,
        source_refs=["synthetic/receipt-register#row-1", "synthetic/correction#C-SYN-01-r2"],
        missing_or_return_reason="SYNTHETIC FIXTURE: corrected revision requires evidence recheck",
        owner="ADMIN-SYN-01", next_action="recheck receipt against revision 2",
    )
    assert json.dumps(queue, sort_keys=True) == before_replay
    with pytest.raises(ValueError, match="conflicting replay"):
        update_repair_item(
            queue, item_id="repair-C-SYN-01-receipt", update_id="update-synthetic-1",
            run_id="run-synthetic", batch_id="batch-synthetic-3", owner="FIN-SYN-01",
        )
    assert queue["items"]["repair-C-SYN-01-receipt"]["status"] == "open"
    assert queue["items"]["repair-C-SYN-01-receipt"]["response_id"] is None
    assert queue["items"]["repair-C-SYN-01-receipt"]["history"][0]["response_id"] == "response-synthetic-1"
    assert set(owner_grouped_view(queue)) == {"ADMIN-SYN-01"}

    write_repair_queue(queue, path)
    loaded = load_repair_queue(path)
    assert loaded["items"]["repair-C-SYN-01-receipt"]["revision"] == 2
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["by_owner"] == {"ADMIN-SYN-01": ["repair-C-SYN-01-receipt"]}


def test_partial_repair_response_validation_is_atomic():
    queue = new_repair_queue()
    add_repair_item(
        queue, item_id="receipt-one", subject_type="claim", subject_id="C-SYN-02", revision=1,
        source_refs=["synthetic/claim#1"], missing_or_return_reason="SYNTHETIC FIXTURE: receipt missing",
        owner="EMP-SYN-02", next_action="provide receipt one", run_id="run-synthetic", batch_id="b1",
    )
    before = json.dumps(queue, sort_keys=True)
    with pytest.raises(KeyError, match="unknown repair item"):
        apply_partial_response(
            queue, response_id="response-synthetic-invalid",
            item_outcomes={
                "receipt-one": {"outcome": "supported", "source_refs": ["synthetic/receipt#1"]},
                "not-a-repair-item": {"outcome": "supported", "source_refs": ["synthetic/receipt#2"]},
            },
            run_id="run-synthetic", batch_id="b2",
        )
    assert json.dumps(queue, sort_keys=True) == before


def test_actual_parse_keeps_both_blockers_owned_and_scoped(tmp_path):
    parsed = parse_retained_run(CAPTURE, output_path=tmp_path / "parsed.json")
    issues = {row["record_id"]: row for row in parsed["unresolved_issues"]}
    assert set(issues) == {"scenario-case-clock", "reimbursement-policy-pol-2026-2"}
    assert issues["scenario-case-clock"]["owner"] == "Exercise facilitator"
    assert issues["scenario-case-clock"]["revision"] is None
    assert issues["reimbursement-policy-pol-2026-2"]["owner"] == "Travel Administration Lead / exercise facilitator"
    assert issues["reimbursement-policy-pol-2026-2"]["evidence_needed"].startswith("Complete policy content")

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from travel_claim.outputs import (
    CLAIMS_COLUMNS,
    add_repair_item,
    apply_partial_response,
    load_repair_queue,
    new_repair_queue,
    owner_grouped_view,
    write_claims_csv,
    write_repair_queue,
)
from travel_claim.snapshots import seal_batch_snapshot, verify_snapshot
from source_fixtures import pdf_bytes, xlsx_bytes
from travel_claim.sources import SOURCES, capture_sources, verify_source_manifest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "snapshot.schema.json"


def _xlsx_bytes():
    return xlsx_bytes()

def _source_bodies():
    return {
        "policy-pol-2026-2": b"<!doctype html><title>Travel reimbursement policy POL-2026.2 Alderbridge</title>",
        "initial-claim-binder": pdf_bytes(),
        "claim-updates-binder": pdf_bytes(),
        "receipt-binder": pdf_bytes(),
        "travel-registers-workbook": _xlsx_bytes(),
    }


def _capture(tmp_path, *, bodies=None, case_clock="2026-09-01T00:00:00Z"):
    bodies = bodies or _source_bodies()
    attempts = []

    def fetch(url, timeout):
        attempts.append(url)
        source = next(s for s in SOURCES if (s.export_url or s.url) == url)
        return bodies[source.source_id], {"ETag": f'"{source.source_id}-v1"'}, url

    run_dir = tmp_path / "run-1"
    manifest = capture_sources(
        run_dir,
        run_id="run-1",
        case_clock=case_clock,
        fetch=fetch,
        observed_at=iter([f"2026-09-01T00:00:0{i}Z" for i in range(10)]).__next__,
    )
    return run_dir, manifest, attempts


def _empty_state():
    return {
        "claims": [],
        "requests": [],
        "travel_cancellations": [],
        "admitted_event_ids": [],
        "issues": [],
    }


def _current_claim(**updates):
    row = {
        "claim_id": "C100",
        "revision": 1,
        "trip_id": "T100",
        "status": "held",
        "allowed_cents": None,
        "paid_cents": 0,
        "balance_cents": None,
        "next_owner": "employee",
        "reason": "receipt missing",
    }
    row.update(updates)
    return row


def test_fresh_capture_attempts_all_five_retains_read_bytes_and_marks_unavailable(tmp_path):
    bodies = _source_bodies()
    bodies["policy-pol-2026-2"] = b"<!doctype html><title>Notion</title><p>generic shell</p>"
    run_dir, manifest, attempts = _capture(tmp_path, bodies=bodies, case_clock=None)

    assert len(attempts) == 5
    assert len(set(attempts)) == 5
    assert len(manifest["files"]) == 5
    assert set(manifest) == {"run_id", "source_version", "case_clock", "files"}
    assert manifest["case_clock"] is None
    policy = manifest["files"][0]
    assert policy["status"] == "unavailable"
    assert policy["path"] is policy["sha256"] is policy["version"] is None
    assert policy["error"] and policy["missing_scope"]
    for record in manifest["files"][1:]:
        retained = (run_dir / record["path"]).read_bytes()
        assert record["status"] == "read"
        assert hashlib.sha256(retained).hexdigest() == record["sha256"]
    assert verify_source_manifest(run_dir) == []


def test_capture_refuses_to_overwrite_run_manifest(tmp_path):
    run_dir, _, _ = _capture(tmp_path)
    before = (run_dir / "sources.json").read_bytes()
    with pytest.raises(FileExistsError):
        capture_sources(run_dir, run_id="run-1", case_clock=None, fetch=lambda *_: pytest.fail("must not fetch"))
    assert (run_dir / "sources.json").read_bytes() == before


def test_manifest_verification_detects_retained_source_corruption(tmp_path):
    run_dir, manifest, _ = _capture(tmp_path)
    read_record = next(row for row in manifest["files"] if row["status"] == "read")
    (run_dir / read_record["path"]).write_bytes(b"changed")
    assert any("hash mismatch" in error for error in verify_source_manifest(run_dir))


def test_snapshot_seals_source_and_predecessor_hashes_and_is_immutable(tmp_path):
    run_dir, _, _ = _capture(tmp_path)
    first = seal_batch_snapshot(
        run_dir,
        run_id="run-1",
        batch_id="arrival-001",
        schema_path=SCHEMA,
        **_empty_state(),
    )
    first_bytes = first.read_bytes()
    first_obj = json.loads(first_bytes)
    assert first_obj["predecessor"] is None
    assert first_obj["source_binding"]["path"] == "sources.json"
    assert first_obj["source_binding"]["sha256"] == hashlib.sha256((run_dir / "sources.json").read_bytes()).hexdigest()
    assert verify_snapshot(first, run_dir, SCHEMA) == []

    second = seal_batch_snapshot(
        run_dir,
        run_id="run-1",
        batch_id="arrival-002",
        schema_path=SCHEMA,
        predecessor_path=first,
        **_empty_state(),
    )
    second_obj = json.loads(second.read_bytes())
    assert second_obj["predecessor"] == {
        "path": f"batches/{first.name}",
        "sha256": hashlib.sha256(first_bytes).hexdigest(),
    }
    assert verify_snapshot(second, run_dir, SCHEMA) == []
    with pytest.raises(ValueError, match="complete retained snapshot chain"):
        seal_batch_snapshot(
            run_dir,
            run_id="run-1",
            batch_id="fork",
            schema_path=SCHEMA,
            predecessor_path=first,
            **_empty_state(),
        )
    with pytest.raises(FileExistsError):
        seal_batch_snapshot(
            run_dir,
            run_id="run-1",
            batch_id="arrival-001",
            schema_path=SCHEMA,
            **_empty_state(),
        )
    assert first.read_bytes() == first_bytes


def test_snapshot_verification_detects_corrupt_predecessor_and_source_manifest(tmp_path):
    run_dir, _, _ = _capture(tmp_path)
    first = seal_batch_snapshot(run_dir, run_id="run-1", batch_id="a1", schema_path=SCHEMA, **_empty_state())
    second = seal_batch_snapshot(
        run_dir, run_id="run-1", batch_id="a2", schema_path=SCHEMA, predecessor_path=first, **_empty_state()
    )
    first.write_text("corrupt", encoding="utf-8")
    assert any("predecessor SHA-256" in e for e in verify_snapshot(second, run_dir, SCHEMA))
    first.write_bytes(json.dumps(json.loads(second.read_text(encoding="utf-8"))).encode())
    with (run_dir / "sources.json").open("ab") as stream:
        stream.write(b" ")
    assert any("source_binding SHA-256" in e for e in verify_snapshot(second, run_dir, SCHEMA))


def test_snapshot_checks_issue_references_and_finance_cancellation_separation(tmp_path):
    run_dir, _, _ = _capture(tmp_path)
    bad = _empty_state()
    bad["travel_cancellations"] = [{
        "cancellation_id": "X1",
        "target_type": "trip",
        "trip_id": "T1",
        "trip_revision": 1,
        "permit_id": None,
        "permit_revision": None,
        "status": "requested",
        "admitted_cancellation_event_ids": ["CANCEL-EVENT"],
        "requested_at": "2026-09-01T00:00:00Z",
        "confirmed_at": None,
        "effective_at": None,
        "affected_claim_ids": [],
        "original_request_ids": [],
        "financial_status": "unresolved",
        "next_owner": "Finance",
        "reason": "source-recorded cancellation",
        "issue_record_ids": ["missing-issue"],
    }]
    bad["admitted_event_ids"] = ["CANCEL-EVENT"]
    with pytest.raises(ValueError, match="Refusing to seal invalid snapshot"):
        seal_batch_snapshot(run_dir, run_id="run-1", batch_id="bad", schema_path=SCHEMA, **bad)


def test_snapshot_sealing_requires_supplied_scenario_clock(tmp_path):
    run_dir, _, _ = _capture(tmp_path, case_clock=None)
    with pytest.raises(ValueError, match="case_clock"):
        seal_batch_snapshot(run_dir, run_id="run-1", batch_id="no-clock", schema_path=SCHEMA, **_empty_state())


def test_claim_csv_exact_header_null_money_and_one_current_row(tmp_path):
    path = tmp_path / "claims.csv"
    write_claims_csv([_current_claim(), _current_claim(claim_id="C101", paid_cents=0, allowed_cents=0)], path)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == CLAIMS_COLUMNS
        rows = list(reader)
    assert [row["claim_id"] for row in rows] == ["C100", "C101"]
    assert rows[0]["allowed_cents"] == ""
    assert rows[1]["allowed_cents"] == "0"
    assert rows[1]["paid_cents"] == "0"


def test_claim_csv_rejects_duplicate_claim_id_and_non_integer_cents(tmp_path):
    with pytest.raises(ValueError, match="unique current row"):
        write_claims_csv([_current_claim(), _current_claim()], tmp_path / "dup.csv")
    with pytest.raises(ValueError, match="integer cents"):
        write_claims_csv([_current_claim(allowed_cents=1.5)], tmp_path / "bad.csv")


def test_owner_grouped_queue_preserves_item_identity_and_partial_resolution(tmp_path):
    queue = new_repair_queue()
    for item_id, source in (("receipt-a", "receipt/card-a"), ("receipt-b", "receipt/card-b")):
        add_repair_item(
            queue,
            item_id=item_id,
            subject_type="claim",
            subject_id="C9",
            revision=2,
            source_refs=[source],
            missing_or_return_reason=f"missing {item_id}",
            owner="employee-17",
            next_action="provide the identified receipt",
            run_id="run-1",
            batch_id="arrival-002",
        )
    add_repair_item(
        queue,
        item_id="permit-cancel",
        subject_type="permit",
        subject_id="P2",
        revision=1,
        source_refs=["registers/Travel cancellations"],
        missing_or_return_reason="supervisor confirmation missing",
        owner="supervisor-4",
        next_action="supply a current confirmation record",
        run_id="run-1",
        batch_id="arrival-002",
    )
    assert set(owner_grouped_view(queue)) == {"employee-17", "supervisor-4"}

    apply_partial_response(
        queue,
        response_id="employee-response-actual-id",
        item_outcomes={"receipt-a": {"outcome": "supported", "source_refs": ["receipt/card-a"]}},
        run_id="run-1",
        batch_id="arrival-003",
    )
    items = queue["items"]
    assert items["receipt-a"]["status"] == "resolved"
    assert items["receipt-b"]["status"] == "open"
    assert items["permit-cancel"]["status"] == "open"
    assert items["receipt-a"]["history"][0]["batch_id"] == "arrival-003"
    path = tmp_path / "repair-queue.json"
    write_repair_queue(queue, path)
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["items"]["receipt-b"]["request_draft"] == {"status": "draft", "sent": False}
    assert reloaded["by_owner"] == {
        "employee-17": ["receipt-a", "receipt-b"],
        "supervisor-4": ["permit-cancel"],
    }
    reloaded_queue = load_repair_queue(path)
    apply_partial_response(
        reloaded_queue,
        response_id="employee-response-second-receipt",
        item_outcomes={"receipt-b": {"outcome": "insufficient", "source_refs": ["reply/partial"]}},
        run_id="run-1",
        batch_id="arrival-004",
    )
    assert reloaded_queue["items"]["receipt-b"]["status"] == "open"
    assert reloaded_queue["items"]["receipt-a"]["status"] == "resolved"
    write_repair_queue(reloaded_queue, path)
    with pytest.raises(ValueError, match="remove prior events"):
        write_repair_queue(new_repair_queue(), path)


def test_partial_queue_response_needs_source_evidence_to_resolve(tmp_path):
    queue = new_repair_queue()
    add_repair_item(
        queue,
        item_id="missing-fact",
        subject_type="trip",
        subject_id="T5",
        revision=3,
        source_refs=["trips/T5/r3"],
        missing_or_return_reason="date conflict",
        owner="employee-2",
        next_action="provide trip confirmation",
        run_id="run-1",
        batch_id="b1",
    )
    with pytest.raises(ValueError, match="requires source references"):
        apply_partial_response(
            queue,
            response_id="response-1",
            item_outcomes={"missing-fact": {"outcome": "supported", "source_refs": []}},
            run_id="run-1",
            batch_id="b2",
        )
    apply_partial_response(
        queue,
        response_id="response-2",
        item_outcomes={"missing-fact": {"outcome": "conflicting", "source_refs": ["reply/r1"], "note": "date still conflicts"}},
        run_id="run-1",
        batch_id="b2",
    )
    assert queue["items"]["missing-fact"]["status"] == "open"


def test_repair_response_replay_is_idempotent_and_conflicts_are_rejected():
    queue = new_repair_queue()
    add_repair_item(
        queue,
        item_id="item-1",
        subject_type="claim",
        subject_id="C1",
        revision=1,
        source_refs=["claims/C1"],
        missing_or_return_reason="missing receipt",
        owner="employee-1",
        next_action="provide receipt",
        run_id="run-1",
        batch_id="b1",
    )
    outcome = {"item-1": {"outcome": "supported", "source_refs": ["receipts/R1"]}}
    apply_partial_response(queue, response_id="reply-1", item_outcomes=outcome, run_id="run-1", batch_id="b2")
    event_count = len(queue["events"])
    apply_partial_response(queue, response_id="reply-1", item_outcomes=outcome, run_id="run-1", batch_id="b2")
    assert len(queue["events"]) == event_count
    with pytest.raises(ValueError, match="conflicting replay"):
        apply_partial_response(
            queue,
            response_id="reply-1",
            item_outcomes={"item-1": {"outcome": "conflicting", "source_refs": ["receipts/R2"]}},
            run_id="run-1",
            batch_id="b2",
        )

"""Synthetic CLI coverage for the explicitly labelled retained-input replay."""

import hashlib
import io
import json
import zipfile
import csv
from pathlib import Path

from travel_claim.cli import main
from travel_claim.outputs import CLAIMS_COLUMNS
from travel_claim.snapshots import verify_snapshot
from travel_claim.sources import SOURCES, capture_sources


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "snapshot.schema.json"


def _xlsx_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook><sheets/></workbook>")
    return buffer.getvalue()


def _capture(tmp_path):
    run_id = "offline-synthetic"
    run_dir = tmp_path / run_id
    bodies = {
        "policy-pol-2026-2": b"generic policy shell",
        "initial-claim-binder": b"%PDF-1.4\nsynthetic\n%%EOF",
        "claim-updates-binder": b"%PDF-1.4\nsynthetic\n%%EOF",
        "receipt-binder": b"%PDF-1.4\nsynthetic\n%%EOF",
        "travel-registers-workbook": _xlsx_bytes(),
    }
    attempts = []

    def fetch(url, timeout):
        attempts.append(url)
        source = next(row for row in SOURCES if (row.export_url or row.url) == url)
        return bodies[source.source_id], {"ETag": "synthetic-fixture"}, url

    manifest = capture_sources(
        run_dir, run_id=run_id, case_clock=None, fetch=fetch,
        observed_at=iter([f"2026-09-01T00:00:{i:02d}Z" for i in range(10)]).__next__,
    )
    manifest_hash = hashlib.sha256((run_dir / "sources.json").read_bytes()).hexdigest()

    def claim(revision, batch):
        return {
            "source_id": "synthetic-claim-binder",
            "source_sha256": "a" * 64,
            "locator": f"PDF page {revision} synthetic",
            "page": revision,
            "fields": [
                {"label": "Claim reference", "value": "C-SYN-RUN"},
                {"label": "Revision", "value": str(revision)},
                {"label": "Arrival batch", "value": str(batch)},
                {"label": "Trip reference", "value": "T-SYN-RUN"},
                {"label": "Trip revision", "value": "1"},
            ],
            "text": "SYNTHETIC TEST DATA ONLY",
        }

    parsed = {
        "schema_version": "travel-claim-parsed-records/1",
        "run_id": run_id,
        "source_manifest": {"path": "sources.json", "sha256": manifest_hash},
        "case_clock": None,
        "case_clock_issue": {"owner": "Exercise facilitator", "next_action": "provide clock"},
        "arrival_batches": [1, 2],
        "unresolved_issues": [
            {
                "record_id": "scenario-case-clock", "subject_type": "scenario",
                "subject_id": "clock", "reason": "synthetic clock withheld",
                "owner": "Exercise facilitator", "next_action": "provide clock",
                "evidence_needed": "scenario clock",
            },
            {
                "record_id": "reimbursement-policy-pol-2026-2", "subject_type": "policy",
                "subject_id": "POL-2026.2", "reason": "synthetic policy withheld",
                "owner": "Travel Administration Lead", "next_action": "provide native policy",
                "evidence_needed": "complete policy content",
            },
        ],
        "records": {
            "claim_revisions": [claim(1, 1), claim(2, 2)],
            "trips": [{
                "source_id": "synthetic-trips", "source_sha256": "b" * 64,
                "locator": "Trips tab row 2 synthetic", "row": 2,
                "values": {
                    "Trip reference": {"value": "T-SYN-RUN"},
                    "Trip revision": {"value": 1},
                    "Permit reference": {"value": "P-SYN-RUN"},
                    "Permit revision": {"value": 1},
                },
            }],
            "decisions": [{
                "source_id": "synthetic-review-ledger", "source_sha256": "c" * 64,
                "locator": "Review ledger row 2 synthetic", "row": 2,
                "values": {
                    "Decision reference": {"value": "D-SYN-RUN-R1"},
                    "Arrival batch": {"value": 1}, "Subject type": {"value": "claim"},
                    "Subject reference": {"value": "C-SYN-RUN"}, "Revision": {"value": 1},
                    "Outcome": {"value": "approve"},
                },
            }],
            "finance_events": [{
                "source_id": "synthetic-finance-ledger", "source_sha256": "d" * 64,
                "locator": "Finance activity row 2 synthetic", "row": 2,
                "values": {
                    "Activity reference": {"value": "F-SYN-RUN-SETTLED"},
                    "Arrival batch": {"value": 1}, "Activity type": {"value": "settled"},
                    "Claim reference": {"value": "C-SYN-RUN"}, "Currency": {"value": "EUR"},
                    "Amount (EUR)": {"value": 12.5},
                },
            }],
            "cancellation_activities": [],
        },
    }
    (run_dir / "parsed-records.json").write_text(json.dumps(parsed), encoding="utf-8")
    return run_dir, attempts


def test_offline_replay_cli_seals_ordered_batches_and_writes_traceable_outputs(tmp_path):
    run_dir, attempts = _capture(tmp_path)
    attempts_before_replay = list(attempts)

    assert main(["offline-replay", str(run_dir), "--schema", str(SCHEMA)]) == 0
    assert attempts == attempts_before_replay

    first = run_dir / "batches/arrival-001.json"
    second = run_dir / "batches/arrival-002.json"
    first_obj = json.loads(first.read_text(encoding="utf-8"))
    second_obj = json.loads(second.read_text(encoding="utf-8"))
    assert verify_snapshot(first, run_dir, SCHEMA) == []
    assert verify_snapshot(second, run_dir, SCHEMA) == []
    assert first_obj["predecessor"] is None
    assert second_obj["predecessor"] == {
        "path": "batches/arrival-001.json",
        "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
    }
    assert "offline-replay-mode" in {row["record_id"] for row in first_obj["issues"]}
    replay_state = json.loads((run_dir / "offline-replay-state.json").read_text(encoding="utf-8"))
    assert [row["revision"] for row in replay_state["revision_history"]["claim"]["C-SYN-RUN"]["revisions"]] == [1, 2]
    assert [row["decision_id"] for row in replay_state["decision_history"]] == ["D-SYN-RUN-R1"]
    assert [row["values"]["Activity reference"]["value"] for row in replay_state["source_record_history"]["finance_events"]] == ["F-SYN-RUN-SETTLED"]

    with (run_dir / "claims.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
        assert tuple(rows[0].keys()) == CLAIMS_COLUMNS
        assert len(rows) == 1
        assert rows[0]["claim_id"] == "C-SYN-RUN"
        assert rows[0]["revision"] == "2"
        assert rows[0]["allowed_cents"] == ""
        assert rows[0]["paid_cents"] == "1250"
        assert rows[0]["balance_cents"] == ""
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "OFFLINE REPLAY" in report
    assert "Fresh native reads in this run: **no**" in report
    assert "Case clock: **unresolved**" in report
    assert "POL-2026.2: **unavailable**" in report
    queue = json.loads((run_dir / "repair-queue.json").read_text(encoding="utf-8"))
    assert "by_owner" in queue


def test_offline_replay_cli_refuses_to_overwrite_outputs(tmp_path):
    run_dir, _ = _capture(tmp_path)
    assert main(["offline-replay", str(run_dir), "--schema", str(SCHEMA)]) == 0
    first = (run_dir / "batches/arrival-001.json").read_bytes()
    assert main(["offline-replay", str(run_dir), "--schema", str(SCHEMA)]) == 1
    assert (run_dir / "batches/arrival-001.json").read_bytes() == first


def test_report_separates_owner_grouped_open_repairs_and_external_blockers(tmp_path):
    from travel_claim.offline_replay import _report, run_offline_replay
    from travel_claim.outputs import add_repair_item

    run_dir, _ = _capture(tmp_path)
    parsed_path = run_dir / "parsed-records.json"
    parsed = json.loads(parsed_path.read_text())
    # A second claim has an unresolved trip binding. The first claim's cash
    # evidence and both revisions must still survive the complete replay.
    independent = json.loads(json.dumps(parsed["records"]["claim_revisions"][0]))
    independent["fields"][0]["value"] = "C-UNRESOLVED"
    independent["fields"][3]["value"] = "T-MISSING"
    parsed["records"]["claim_revisions"].append(independent)
    parsed_path.write_text(json.dumps(parsed))
    result = run_offline_replay(run_dir, schema_path=SCHEMA)
    claims = {row["claim_id"]: row for row in result["state"]["snapshot"]["claims"]}
    assert set(claims) == {"C-SYN-RUN", "C-UNRESOLVED"}
    assert claims["C-SYN-RUN"]["revision"] == 2
    assert claims["C-SYN-RUN"]["paid_cents"] == 1250
    assert claims["C-SYN-RUN"]["allowed_cents"] is None
    queue = result["state"]["domain"]["repair_queue"]
    report = result["outputs"]["report"].read_text()
    claim_section = report.split("## Claim-specific actionable repairs by owner\n", 1)[1].split("## Trip and permit", 1)[0]
    blockers = report.split("## Run-level external blockers\n", 1)[1].split("## Outputs", 1)[0]
    assert "offline replay" in blockers
    assert "scenario-case-clock" in blockers
    assert "reimbursement-policy-pol-2026-2" in blockers
    assert "scenario-case-clock" not in claim_section
    assert "reimbursement-policy-pol-2026-2" not in claim_section
    assert "Independent valid records continue" in report
    for item in queue["items"].values():
        if item["subject_type"] != "claim" or item["status"] != "open":
            continue
        owner_section = claim_section.split(f"### {item['owner']}\n", 1)[1].split("\n### ", 1)[0]
        assert f"Repair `{item['item_id']}`" in owner_section
        assert f"subject claim `{item['subject_id']}`, revision {item['revision']}" in owner_section
        assert f"Next action: {item['next_action']}" in owner_section
        assert f"run `{item['run_id']}`, batch `{item['batch_id']}`" in owner_section
        for ref in item["source_refs"]:
            assert f"`{ref}`" in owner_section
    assert claim_section.count("### ") == len({item["owner"] for item in queue["items"].values() if item["subject_type"] == "claim" and item["status"] == "open"})

    # Report filtering must leave persisted queue history untouched and must
    # keep non-claim repairs in their own section, even with the same owner.
    resolved_id = next(iter(queue["items"]))
    queue["items"][resolved_id]["status"] = "resolved"
    add_repair_item(
        queue, item_id="permit-repair", subject_type="permit", subject_id="P-SYN",
        revision=1, source_refs=["retained-permit@hash#row 2"],
        missing_or_return_reason="missing permit evidence", owner="Travel Administration Lead",
        next_action="obtain permit evidence", run_id=parsed["run_id"], batch_id="arrival-002",
    )
    rendered = _report(run_id=parsed["run_id"], parsed=parsed,
                       snapshots=result["snapshots"], latest=result["state"],
                       output_paths=result["outputs"])
    assert f"Repair `{resolved_id}`" not in rendered
    assert queue["items"][resolved_id]["status"] == "resolved"
    claim_section = rendered.split("## Claim-specific", 1)[1].split("## Trip and permit", 1)[0]
    permit_section = rendered.split("## Trip and permit", 1)[1].split("## Run-level", 1)[0]
    assert "permit-repair" not in claim_section
    assert "subject permit `P-SYN`, revision 1" in permit_section
    assert "Next action: obtain permit evidence" in permit_section


def test_replay_writes_human_review_drafts_linked_from_report(tmp_path):
    from travel_claim.offline_replay import run_offline_replay

    run_dir, attempts = _capture(tmp_path)
    before = list(attempts)
    result = run_offline_replay(run_dir, schema_path=SCHEMA)
    assert attempts == before
    draft_path = result["outputs"]["drafts"]
    assert draft_path.name == "follow-up-drafts.md"
    drafts = draft_path.read_text()
    assert result["draft_count"] == drafts.count("## Draft for ")
    assert "HUMAN REVIEW REQUIRED — NOT SENT" in drafts
    assert "scenario-case-clock" in drafts
    assert "reimbursement-policy-pol-2026-2" in drafts
    assert "follow-up-drafts.md" in result["outputs"]["report"].read_text()
    for item in result["state"]["domain"]["repair_queue"]["items"].values():
        assert item["request_draft"] == {"status": "draft", "sent": False}
        if item["status"] == "open":
            assert f"Item `{item['item_id']}`" in drafts


def test_replay_refuses_existing_drafts_before_sealing_any_batches(tmp_path):
    run_dir, _ = _capture(tmp_path)
    draft_path = run_dir / "follow-up-drafts.md"
    draft_path.write_text("existing reviewed draft")
    assert main(["offline-replay", str(run_dir), "--schema", str(SCHEMA)]) == 1
    assert draft_path.read_text() == "existing reviewed draft"
    assert not (run_dir / "batches").exists()

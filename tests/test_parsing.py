import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from travel_claim.parsing import parse_retained_run
from travel_claim.sources import verify_source_manifest


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "artifacts/runs/source-capture-20261014T100034Z"


def test_actual_native_records_parse_with_page_tab_and_hash_references(tmp_path):
    assert verify_source_manifest(CAPTURE) == []
    output = tmp_path / "parsed.json"
    parsed = parse_retained_run(CAPTURE, output_path=output)
    reread = json.loads(output.read_text(encoding="utf-8"))

    assert parsed == reread
    assert parsed["arrival_batches"] == [1, 2, 3, 4]
    assert parsed["arrival_batch_contents"] == {
        "1": {"claim_revisions": 120, "decisions": 289, "finance_events": 100, "cancellation_activities": 2},
        "2": {"finance_events": 100, "cancellation_activities": 4},
        "3": {"claim_revisions": 6, "decisions": 15, "finance_events": 10, "cancellation_activities": 2},
        "4": {"claim_revisions": 1, "decisions": 3, "finance_events": 10, "cancellation_activities": 1},
    }
    assert parsed["case_clock"] is None
    assert parsed["case_clock_state"] == "not_in_accessible_retained_sources"
    assert parsed["case_clock_issue"]["owner"] == "Exercise facilitator"
    assert "before consuming any arrival batch" in parsed["case_clock_issue"]["next_action"]
    assert parsed["missing_sources"][0]["source_id"] == "policy-pol-2026-2"
    assert parsed["processing_boundary"]["policy_dependent_conclusions"] == "unresolved"

    records = parsed["records"]
    assert len(records["claim_revisions"]) == 127
    assert len(records["trips"]) == 123
    assert len(records["permits"]) == 5
    assert len(records["receipts"]) == 203
    assert len(records["decisions"]) == 307
    assert len(records["finance_events"]) == 220
    assert len(records["cancellation_activities"]) == 9

    c09 = [r for r in records["claim_revisions"] if r["claim_id"] == "C09"]
    c09_facts = [{field["label"]: field["value"] for field in row["fields"]} for row in c09]
    assert {(row["Revision"], row["Arrival batch"]) for row in c09_facts} == {("1", "1"), ("2", "3")}
    assert all(row["source_sha256"] for row in c09)
    assert all(row["locator"].startswith("PDF page ") for row in c09)

    assert {row["name"] for row in parsed["workbook_sheets"]} == {
        "People", "Trips", "Merchant payments", "FX", "Caps", "Budget",
        "Review ledger", "Review packets", "Finance activity", "Travel cancellations",
    }
    cancellation_subjects = Counter(row["values"]["Cancelled subject"]["value"] for row in records["cancellation_activities"])
    assert cancellation_subjects == {"trip": 7, "permit": 2}
    assert all("source_sha256" in row and "tab '" in row["locator"] for row in records["finance_events"])
    assert hashlib.sha256((CAPTURE / "sources.json").read_bytes()).hexdigest() == parsed["source_manifest"]["sha256"]


def test_source_corruption_blocks_parsing(tmp_path):
    copied = tmp_path / CAPTURE.name
    shutil.copytree(CAPTURE, copied, ignore=shutil.ignore_patterns("parsed-records.json"))
    manifest = json.loads((copied / "sources.json").read_text(encoding="utf-8"))
    first_read = next(row for row in manifest["files"] if row["status"] == "read")
    with (copied / first_read["path"]).open("ab") as stream:
        stream.write(b"corrupt")
    assert any("hash mismatch" in error for error in verify_source_manifest(copied))
    with pytest.raises(ValueError, match="unverified retained sources"):
        parse_retained_run(copied, output_path=tmp_path / "should-not-exist.json")


def test_policy_dependent_outputs_are_not_inferred(tmp_path):
    parsed = parse_retained_run(CAPTURE, output_path=tmp_path / "parsed.json")
    assert parsed["processing_boundary"] == {
        "policy_dependent_conclusions": "unresolved",
        "reason": "Native reimbursement policy content is unavailable; parsed source values are not eligibility, entitlement, approval-readiness, or closure decisions.",
        "owner": "Travel Administration Lead / facilitator for source access",
        "next_action": "Provide an authorized native export or enable read access to the original Notion policy, then perform a fresh native read.",
    }

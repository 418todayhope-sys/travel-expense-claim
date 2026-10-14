"""Readiness preserves the distinction between evidence integrity and authority."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from test_offline_replay import _capture, SCHEMA
from travel_claim.cli import main
from travel_claim.offline_replay import run_offline_replay
from travel_claim.readiness import validate_readiness


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "synthetic@example.invalid")
    (repo / ".entire").mkdir()
    (repo / ".entire/settings.json").write_text('{"enabled": true}')
    (repo / "metadata.json").write_text('{"synthetic_fixture": true}')
    git("add", ".")
    git("commit", "-m", "Synthetic evidence\n\nEntire-Checkpoint: TEST-CHECKPOINT")
    git("update-ref", "refs/entire/checkpoints/NT/TEST-CHECKPOINT", "HEAD")
    return repo


def _run(tmp_path, *, complete=False, repairs=False):
    run, _ = _capture(tmp_path)
    manifest_path = run / "sources.json"
    manifest = json.loads(manifest_path.read_text())
    parsed_path = run / "parsed-records.json"
    parsed = json.loads(parsed_path.read_text())
    if complete:
        # Synthetic fixture values only; never used for the real retained run.
        policy_path = run / "sources/policy-pol-2026-2.html"
        body = b"<html>POL-2026.2 synthetic reimbursement fixture</html>"
        policy_path.write_bytes(body)
        manifest["files"][0].update(path="sources/policy-pol-2026-2.html", sha256=hashlib.sha256(body).hexdigest(),
                                    status="read", error=None, missing_scope=[], version="synthetic")
        manifest["case_clock"] = "2026-09-01T00:00:00Z"
        parsed.update(case_clock=manifest["case_clock"], case_clock_issue=None, unresolved_issues=[])
    manifest_path.write_text(json.dumps(manifest))
    parsed["source_manifest"]["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if not repairs:
        parsed["records"] = {name: [] for name in parsed["records"]}
    else:
        # Give fixture records authentic bindings to fixture retained bytes.
        for kind, rows in parsed["records"].items():
            source = manifest["files"][1 if kind == "claim_revisions" else 4]
            for row in rows:
                row.update(source_id=source["source_id"], source_sha256=source["sha256"])
    parsed_path.write_text(json.dumps(parsed))
    run_offline_replay(run, schema_path=SCHEMA)
    return run


def _checks(result):
    return {row["check"]: row["status"] for row in result["checks"]}


def test_complete_structural_package_passes_integrity_but_offline_is_never_live_compliance(tmp_path):
    run = _run(tmp_path, complete=True)
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    assert result["status"] == "BLOCKED"
    assert result["integrity_status"] == "PASS"
    assert result["final_live_source_compliance"] is False
    assert _checks(result)["authoritative-case-clock"] == "PASS"
    assert all(_checks(result)[f"source-completeness:{row['source_id']}"] == "PASS"
               for row in json.loads((run / "sources.json").read_text())["files"])
    assert _checks(result)["execution-scope"] == "BLOCKED"
    assert _checks(result)["entire-local-evidence"] == "PASS"
    assert result["entire_remote_sync"] == "not_checked"
    assert all(row["evidence_paths"] and row["next_action"] for row in result["checks"])


def test_policy_clock_and_unresolved_repairs_are_blocked_not_passed(tmp_path):
    run = _run(tmp_path, repairs=True)
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    checks = _checks(result)
    assert result["status"] == "BLOCKED"
    assert checks["source-completeness:policy-pol-2026-2"] == "BLOCKED"
    assert checks["authoritative-case-clock"] == "BLOCKED"
    assert checks["external-blocker:scenario-case-clock"] == "BLOCKED"
    assert checks["external-blocker:reimbursement-policy-pol-2026-2"] == "BLOCKED"
    assert checks["unresolved-repairs"] == "BLOCKED"
    assert checks["repair-evidence-availability"] == "BLOCKED"
    assert checks["repair-queue-traceability"] == "PASS"


@pytest.mark.parametrize("missing", ["report.md", "claims.csv", "sources.json", "offline-replay-state.json", "batches/arrival-002.json"])
def test_incomplete_package_fails_with_evidence_and_next_action(tmp_path, missing):
    run = _run(tmp_path)
    (run / missing).unlink()
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    assert result["status"] == "FAIL"
    assert result["integrity_status"] == "FAIL"
    assert any(row["status"] == "FAIL" and row["evidence_paths"] and row["next_action"] for row in result["checks"])


@pytest.mark.parametrize("target,expected", [
    ("source", "manifest-integrity"), ("snapshot", "snapshot-chain"),
    ("orphan", "snapshot-chain"), ("terminal-snapshot", "snapshot-content-evidence"), ("header", "claims-csv-contract"),
    ("csv-money", "claims-csv-contract"), ("report", "report-traceability"),
    ("draft", "follow-up-draft-status"), ("queue", "repair-queue-traceability"),
    ("reference", "repair-queue-traceability"), ("locator", "repair-queue-traceability"),
    ("fresh-marker", "input-bindings"),
    ("parsed", "input-bindings"),
])
def test_tampered_evidence_fails(tmp_path, target, expected):
    run = _run(tmp_path, repairs=True)
    if target == "source":
        (run / "sources/initial-claim-binder.pdf").write_bytes(b"tampered")
    elif target == "snapshot":
        path = run / "batches/arrival-001.json"
        path.write_text(path.read_text() + "\n")
    elif target == "terminal-snapshot":
        path = run / "batches/arrival-002.json"
        snapshot = json.loads(path.read_text())
        snapshot["issues"][0]["reason"] = "tampered but schema-valid issue"
        path.write_text(json.dumps(snapshot))
    elif target == "orphan":
        (run / "batches/orphan.json").write_text('{}')
    elif target == "header":
        path = run / "claims.csv"
        path.write_text(path.read_text().replace("claim_id,revision", "revision,claim_id", 1))
    elif target == "csv-money":
        path = run / "claims.csv"
        path.write_text(path.read_text().replace("1250", "9999"))
    elif target == "report":
        path = run / "report.md"
        path.write_text(path.read_text().replace("Exercise facilitator", "Invented owner"))
    elif target == "draft":
        path = run / "follow-up-drafts.md"
        path.write_text(path.read_text().replace("HUMAN REVIEW REQUIRED", "READY TO SEND"))
    elif target in {"queue", "reference", "locator"}:
        path = run / "repair-queue.json"
        queue = json.loads(path.read_text())
        item = next(iter(queue["items"].values()))
        if target == "queue":
            item["request_draft"]["sent"] = True
        elif target == "locator":
            manifest = json.loads((run / "sources.json").read_text())
            item["source_refs"] = ["initial-claim-binder@" + manifest["files"][1]["sha256"] + "#invented page 999"]
        else:
            item["source_refs"] = ["initial-claim-binder@" + "0" * 64 + "#page 1"]
        path.write_text(json.dumps(queue))
        if target in {"reference", "locator"}:
            path = run / "offline-replay-state.json"
            state = json.loads(path.read_text())
            state["repair_queue"] = {key: value for key, value in queue.items() if key != "by_owner"}
            path.write_text(json.dumps(state))
    elif target == "fresh-marker":
        path = run / "offline-replay-state.json"
        obj = json.loads(path.read_text()); obj["fresh_native_reads_performed"] = True
        path.write_text(json.dumps(obj))
    else:
        path = run / "parsed-records.json"
        path.write_text(path.read_text() + "\n")
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=_repo(tmp_path))
    assert result["status"] == "FAIL"
    assert _checks(result)[expected] == "FAIL"


def test_entire_absence_is_blocked_and_cli_preserves_existing_evidence(tmp_path):
    run = _run(tmp_path)
    before = {str(path): path.read_bytes() for path in run.rglob('*') if path.is_file()}
    output = tmp_path / "validation"
    assert main(["validate-readiness", str(run), "--repo", str(tmp_path), "--output-dir", str(output)]) == 2
    report = json.loads((output / "readiness.json").read_text())
    assert _checks(report)["entire-local-evidence"] == "BLOCKED"
    assert "**BLOCKED**" in (output / "readiness.md").read_text()
    prior = (output / "readiness.json").read_bytes()
    assert main(["validate-readiness", str(run), "--output-dir", str(output)]) == 1
    assert (output / "readiness.json").read_bytes() == prior
    assert main(["validate-readiness", str(run), "--output-dir", str(run / "validation")]) == 1
    assert before == {str(path): path.read_bytes() for path in run.rglob('*') if path.is_file()}


@pytest.mark.parametrize("filename,value", [("sources.json", {"files": None}), ("parsed-records.json", {"unresolved_issues": None}), ("repair-queue.json", {"items": []}), ("offline-replay-state.json", [])])
def test_malformed_inputs_produce_fail_report_instead_of_crashing(tmp_path, filename, value):
    run = _run(tmp_path)
    (run / filename).write_text(json.dumps(value))
    result = validate_readiness(run, schema_path=SCHEMA, repo_dir=tmp_path)
    assert result["status"] == "FAIL"


def test_cli_failed_validation_still_writes_both_readiness_reports(tmp_path):
    run = _run(tmp_path)
    (run / "claims.csv").write_text("wrong,header\n")
    output = tmp_path / "failed-validation"
    assert main(["validate-readiness", str(run), "--repo", str(tmp_path), "--output-dir", str(output)]) == 1
    assert json.loads((output / "readiness.json").read_text())["status"] == "FAIL"
    assert "**FAIL**" in (output / "readiness.md").read_text()

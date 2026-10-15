"""Read-only structural readiness checks; never certify live business compliance."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .follow_up import render_follow_up_drafts
from .integration import integrate_arrival_batch
from .offline_replay import OFFLINE_MARKER, _report
from .revalidation import verification_document
from .ordinary import ordinary_demo
from .outputs import CLAIMS_COLUMNS, load_repair_queue
from .snapshots import verify_snapshot
from .sources import SOURCES, verify_source_manifest

REQUIRED_FILES = (
    "sources.json", "parsed-records.json", "offline-replay-state.json",
    "claims.csv", "report.md", "repair-queue.json", "follow-up-drafts.md",
    "ordinary-workflow.json", "ordinary-workflow-demo.md",
    "correction-cancellation-verification.json", "correction-cancellation-verification.md",
)


def validate_readiness(run_dir: Path, *, schema_path: Path, repo_dir: Path) -> dict[str, Any]:
    """Inspect existing artifacts and local Git evidence without changing either."""
    run_dir, repo_dir = run_dir.resolve(), repo_dir.resolve()
    checks: list[dict[str, Any]] = []
    objects: dict[str, dict] = {}

    def add(name, status, detail, evidence, action):
        checks.append(dict(check=name, status=status, detail=detail,
                           evidence_paths=[str(path) for path in evidence], next_action=action))

    def check(name, paths, operation):
        try:
            operation()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, AssertionError) as exc:
            add(name, "FAIL", str(exc) or "Evidence is inconsistent", paths,
                "Investigate the listed evidence; preserve this run and regenerate corrected outputs in a new run.")
        else:
            add(name, "PASS", "Local structural evidence verified", paths, "No structural repair required.")

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    for name in REQUIRED_FILES:
        path = run_dir / name
        def read(path=path, name=name):
            require(path.is_file(), f"Required output missing: {name}")
            if name.endswith(".json"):
                obj = json.loads(path.read_text(encoding="utf-8"))
                require(isinstance(obj, dict), f"{name} must contain an object")
                objects[name] = obj
        check(f"required:{name}", [path], read)

    manifest = objects.get("sources.json", {})
    parsed = objects.get("parsed-records.json", {})
    state = objects.get("offline-replay-state.json", {})
    def manifest_integrity():
        errors = verify_source_manifest(run_dir)
        require(not errors, "; ".join(errors))
        require(manifest.get("source_version") in {"native-source-manifest/1", "native-source-manifest/2"}, "Unsupported manifest version")
        rows = manifest["files"]
        require(len(rows) == len(SOURCES), "Expected exactly five source entries")
        require({r["source_id"]: r["url"] for r in rows} == {s.source_id: s.url for s in SOURCES},
                "Source IDs do not match configured native URLs")
    check("manifest-integrity", [run_dir / "sources.json"], manifest_integrity)
    source_rows = manifest.get("files", [])
    if not isinstance(source_rows, list):
        source_rows = []
    for source in SOURCES:
        row = next((r for r in source_rows if isinstance(r, dict) and r.get("source_id") == source.source_id), {})
        complete = row.get("status") == "read" and row.get("missing_scope") == []
        add(f"source-completeness:{source.source_id}", "PASS" if complete else "BLOCKED",
            "Complete retained scope recorded" if complete else row.get("error") or "Source scope missing or partial",
            [run_dir / "sources.json"], "No source-access repair required." if complete else
            f"Obtain authorized access to {source.url}, perform a fresh native read, and retain complete scope in a new run.")

    supplemental_binding = None
    def supplemental_evidence():
        nonlocal supplemental_binding
        from .policy_evidence import verify_policy_evidence, CLOCK
        verified_binding = verify_policy_evidence(run_dir, parsed)
        require(state.get('supplemental_policy_binding') == verified_binding and state.get('event_clock') == CLOCK,
                'Replay state supplemental policy/clock binding mismatch')
        supplemental_binding = verified_binding
    supplemental_present = bool(parsed.get('supplemental_policy') or state.get('supplemental_policy_binding') or (run_dir / 'supplemental-policy.json').exists())
    if supplemental_present:
        check('supplemental-policy-evidence', [run_dir / 'supplemental-policy.json', run_dir / 'supplemental', run_dir / 'retained-input-lineage.json'], supplemental_evidence)
    else:
        add('supplemental-policy-evidence', 'BLOCKED', 'No supplemental browser policy supplied',
            [run_dir / 'parsed-records.json'], 'Supply verified browser policy explicitly in a new policy-replay run if required.')

    clock = manifest.get("case_clock")
    clock_confirmed = False
    if clock:
        try:
            clock_confirmed = datetime.fromisoformat(clock.replace("Z", "+00:00")).utcoffset() is not None
        except (ValueError, TypeError, AttributeError):
            pass
    clock_confirmed = clock_confirmed and parsed.get("case_clock") == clock and state.get("case_clock") == clock and not parsed.get("case_clock_issue")
    clock_confirmed = clock_confirmed or bool(supplemental_binding)
    add("authoritative-case-clock", "PASS" if clock_confirmed else "BLOCKED",
        "Verified browser policy supplies 2026-11-15 Europe/Amsterdam, calendar-date precision; same-day cutoff unknown" if supplemental_binding else
        "Consistent supplied timestamp recorded; authority is caller supplied" if clock_confirmed else "Authoritative scenario clock is unconfirmed or inconsistent",
        [run_dir / "sources.json", run_dir / "parsed-records.json"],
        "Retain the supplied authority evidence." if clock_confirmed else "Obtain authoritative scenario clock evidence at its actual precision; do not infer time from observation timestamps.")

    mode = state.get("mode", "unverified")
    offline = mode == "offline-replay" and state.get("fresh_native_reads_performed") is False
    add("execution-scope", "BLOCKED", "Retained-input offline replay; no fresh native-source execution" if offline else
        "Fresh native-source execution is not established by the supported replay artifacts",
        [run_dir / "offline-replay-state.json"], "Perform a separately authorized fresh native-source execution; this validator certifies only structural evidence, never final policy or financial compliance.")

    def bindings():
        manifest_hash = hashlib.sha256((run_dir / "sources.json").read_bytes()).hexdigest()
        parsed_hash = hashlib.sha256((run_dir / "parsed-records.json").read_bytes()).hexdigest()
        require(parsed["source_manifest"] == {"path": "sources.json", "sha256": manifest_hash}, "Parsed manifest binding mismatch")
        require(state["source_manifest_sha256"] == manifest_hash and state["parsed_records_sha256"] == parsed_hash,
                "Replay state input hash mismatch")
        require(state["parsed_records_path"] == "parsed-records.json", "Unexpected parsed input path")
        require(manifest["run_id"] == parsed["run_id"] == state["run_id"] == run_dir.name, "Run identities disagree")
        require(offline, "Replay mode/fresh-read markers disagree or are unsupported")
    check("input-bindings", [run_dir / name for name in ("sources.json", "parsed-records.json", "offline-replay-state.json")], bindings)

    snapshots: list[Path] = []
    def chain():
        batches = parsed["arrival_batches"]
        require(isinstance(batches, list) and batches and batches == list(range(1, len(batches) + 1)), "Arrival sequence is incomplete")
        expected = [f"batches/arrival-{n:03d}.json" for n in batches]
        require(state["sealed_batches"] == expected, "Sealed batch list does not match arrival sequence")
        require({p.name for p in (run_dir / "batches").glob("*.json")} == {Path(p).name for p in expected}, "Missing or orphaned snapshots")
        previous = None
        for relative in expected:
            path = run_dir / relative
            errors = verify_snapshot(path, run_dir, schema_path)
            require(not errors, f"{relative}: {'; '.join(errors)}")
            obj = json.loads(path.read_text())
            require(obj["batch_id"] == path.stem, "Snapshot batch identity mismatch")
            require(obj["predecessor"] == previous, "Snapshot chain order mismatch")
            require(any(i["record_id"] == "offline-replay-mode" for i in obj["issues"]), "Snapshot offline marker missing")
            previous = {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            snapshots.append(path)
    check("snapshot-chain", [run_dir / "batches", schema_path], chain)

    revalidation_expected = {}
    def snapshot_evidence():
        require(snapshots and checks[-1]["status"] == "PASS", "Verified complete snapshot chain required")
        prior_result = None
        for number, path in enumerate(snapshots, start=1):
            observed = json.loads(path.read_text())
            current = integrate_arrival_batch(
                parsed, arrival_batch=number, run_id=state["run_id"], batch_id=path.stem,
                source_binding=observed["source_binding"], predecessor=observed["predecessor"],
                prior_result=prior_result, source_observations=manifest['files'],
            )
            if supplemental_binding:
                current['snapshot']['supplemental_policy_binding'] = supplemental_binding
                current['snapshot']['event_clock'] = parsed['event_clock']
            current["snapshot"]["issues"].append(dict(OFFLINE_MARKER))
            require(current["snapshot"] == observed, f"{path.name} content differs from retained evidence replay")
            prior_result = current
        require(state.get('budget_reconciliation') == current['domain']['budget'], 'Budget state differs from evidence replay')
        require(state.get('budget_history') == current['domain']['budget_history'], 'Budget history differs from evidence replay')
        data, summary = verification_document(current['domain'], current['snapshot']['travel_cancellations'], run_id=state['run_id'])
        revalidation_expected.update(data=data, summary=summary)
    check("snapshot-content-evidence", [run_dir / "batches", run_dir / "parsed-records.json"], snapshot_evidence)

    def correction_trace():
        require(revalidation_expected, "Deterministic retained evidence replay required")
        require(objects['correction-cancellation-verification.json'] == revalidation_expected['data'],
                "Correction/cancellation checks differ from executed retained evidence replay")
        require((run_dir / 'correction-cancellation-verification.md').read_text() == revalidation_expected['summary'],
                "Correction/cancellation summary differs from executed checks")
    check('correction-cancellation-traceability', [run_dir / 'correction-cancellation-verification.json',
          run_dir / 'correction-cancellation-verification.md'], correction_trace)

    # Collect only references actually present in retained parsed evidence.
    parsed_refs: set[str] = set()
    def collect_refs(value):
        if isinstance(value, dict):
            if all(key in value for key in ("source_id", "source_sha256", "locator")):
                parsed_refs.add(f"{value['source_id']}@{value['source_sha256']}#{value['locator']}")
            for child in value.values():
                collect_refs(child)
        elif isinstance(value, list):
            for child in value:
                collect_refs(child)
    collect_refs(parsed)
    queue: dict = {}
    def queue_trace():
        queue.update(load_repair_queue(run_dir / "repair-queue.json"))
        require(queue == state["repair_queue"], "Queue differs from replay state")
        retained = {r["source_id"]: r for r in manifest["files"] if r["status"] == "read"}
        for item in queue["items"].values():
            if item.get("status") == "superseded": continue
            require(item["subject_type"] in {"claim", "trip", "permit"} and isinstance(item["revision"], int) and not isinstance(item["revision"], bool) and item["revision"] > 0, "Invalid repair subject/revision")
            require(all(isinstance(item[f], str) and item[f].strip() for f in ("subject_id", "owner", "missing_or_return_reason", "next_action")), "Missing repair trace fields")
            require(item["run_id"] == state["run_id"] and f"batches/{item['batch_id']}.json" in state["sealed_batches"], "Repair run/batch reference mismatch")
            require(item["request_draft"] == {"status": "draft", "sent": False}, "Repair request is not an unsent draft")
            require(isinstance(item["source_refs"], list), "Repair source_refs must be an array")
            for ref in item["source_refs"]:
                if supplemental_binding:
                    from .policy_evidence import metadata
                    if ref in metadata()['source_refs']:
                        continue
                sid_hash, locator = ref.split("#", 1)
                sid, digest = sid_hash.split("@", 1)
                require(sid in retained and retained[sid]["sha256"] == digest and bool(locator), "Repair source reference does not bind retained evidence")
                require(ref in parsed_refs, "Repair locator is not present in retained parsed evidence")
    check("repair-queue-traceability", [run_dir / "repair-queue.json", run_dir / "offline-replay-state.json"], queue_trace)

    missing_refs = [item["item_id"] for item in queue.get("items", {}).values()
                    if item.get("status") == "open" and not item.get("source_refs")]
    add("repair-evidence-availability", "BLOCKED" if missing_refs else "PASS",
        f"{len(missing_refs)} open repairs have no retained supporting evidence references; no evidence is invented",
        [run_dir / "repair-queue.json"], "Obtain the evidence requested in each referenced queue item's next_action; preserve unanswered items." if missing_refs else "No missing repair evidence references.")
    checks[-1]["affected_item_ids"] = missing_refs
    open_items = [item["item_id"] for item in queue.get("items", {}).values() if item.get("status") == "open"]
    add("unresolved-repairs", "BLOCKED" if open_items else "PASS", f"{len(open_items)} repair items remain open",
        [run_dir / "repair-queue.json", run_dir / "follow-up-drafts.md"],
        "Human owners must review the unsent drafts and supply item-specific supported responses; continue independent valid work." if open_items else "No open repairs.")
    checks[-1]["affected_item_ids"] = open_items

    def csv_contract():
        require(snapshots, "No verified snapshot chain")
        with (run_dir / "claims.csv").open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            require(tuple(reader.fieldnames or []) == CLAIMS_COLUMNS, "claims.csv header must match the exact required columns")
            rows = list(reader)
        claims = json.loads(snapshots[-1].read_text())["claims"]
        require(len(rows) == len(claims) and len({r['claim_id'] for r in rows}) == len(rows), "Missing or duplicated claim rows")
        by_id = {c["claim_id"]: c for c in claims}
        for row in rows:
            require(None not in row and all(v is not None for v in row.values()), "Malformed CSV row")
            claim = by_id[row["claim_id"]]
            for field in ("revision", "trip_id", "paid_cents", "balance_cents"):
                require(row[field] == ("" if claim[field] is None else str(claim[field])), f"CSV {field} differs from latest snapshot")
            require(row["allowed_cents"] == ("" if claim["allowed_cents"] is None else str(claim["allowed_cents"]))
                    and row["status"] == claim["status"], "CSV entitlement/status differs from evidence-derived snapshot")
            open_claim_repairs = [item for item in queue.get("items", {}).values()
                                 if item["subject_type"] == "claim" and item["subject_id"] == row["claim_id"] and item["status"] == "open"]
            owner = open_claim_repairs[0]["owner"] if open_claim_repairs else claim["next_owner"]
            reason = open_claim_repairs[0]["missing_or_return_reason"] if open_claim_repairs else "Offline structural replay; policy eligibility and reimbursement entitlement remain unresolved."
            owner = None if claim['status'].startswith('closed-') else owner
            require(row["next_owner"] == (owner or "") and row["reason"] == reason, "CSV owner/reason differs from current repair evidence")
    check("claims-csv-contract", [run_dir / "claims.csv"], csv_contract)

    def ordinary_trace():
        require(snapshots, "Verified snapshots required")
        obj = objects['ordinary-workflow.json']
        require(obj['mode'] == 'offline-replay' and obj['fresh_native_reads_performed'] is False
                and obj['run_id'] == state['run_id'], "Ordinary workflow run/mode mismatch")
        current = {c['claim_id']: c['ordinary_workflow'] for c in json.loads(snapshots[-1].read_text())['claims']}
        require(obj['claims'] == state['ordinary_workflows'] == current, "Ordinary current workflow differs from sealed claims")
        expected = {(path.stem, c['claim_id']): c['ordinary_workflow'] for path in snapshots
                    for c in json.loads(path.read_text())['claims']}
        history = obj['history']
        observed = {(r['batch_id'], r['workflow']['claim_id']): r['workflow'] for r in history}
        require(len(history) == len(observed) and observed == expected and history == state['ordinary_workflow_history'],
                "Ordinary workflow history differs from the complete sealed batch chain")
        require((run_dir / 'ordinary-workflow-demo.md').read_text() == ordinary_demo(current), "Ordinary demonstration differs from retained stage evidence")
    check('ordinary-workflow-traceability', [run_dir / 'ordinary-workflow.json', run_dir / 'ordinary-workflow-demo.md'], ordinary_trace)

    def report_trace():
        require(snapshots and queue, "Verified snapshots and queue required")
        paths = {"claims": run_dir / "claims.csv", "state": run_dir / "offline-replay-state.json",
                 "queue": run_dir / "repair-queue.json", "drafts": run_dir / "follow-up-drafts.md"}
        expected = _report(run_id=state["run_id"], parsed=parsed, snapshots=snapshots,
                           latest={"domain": {"repair_queue": queue}}, output_paths=paths)
        require((run_dir / "report.md").read_text() == expected, "Report differs from evidence-derived handoff (sections, references, owners or actions)")
    check("report-traceability", [run_dir / "report.md"], report_trace)

    def drafts_status():
        require(queue, "Verified queue required")
        expected, _ = render_follow_up_drafts(run_id=state["run_id"], queue=queue, blockers=parsed.get("unresolved_issues", []))
        require((run_dir / "follow-up-drafts.md").read_text() == expected, "Drafts differ from unresolved evidence or human-review/unsent labels")
    check("follow-up-draft-status", [run_dir / "follow-up-drafts.md"], drafts_status)
    issues = parsed.get("unresolved_issues", [])
    def blocker_shape():
        require(isinstance(issues, list), "unresolved_issues must be an array")
        for issue in issues:
            require(isinstance(issue, dict) and all(isinstance(issue.get(field), str) and issue[field] for field in
                    ("record_id", "subject_type", "subject_id", "owner", "reason", "next_action")), "Malformed external blocker")
    check("external-blocker-traceability", [run_dir / "parsed-records.json"], blocker_shape)
    for issue in issues if isinstance(issues, list) else []:
        if not isinstance(issue, dict) or not all(field in issue for field in ("record_id", "reason", "next_action")):
            continue
        if issue.get("status", "open") == "open" and issue.get("status") != "superseded":
            add(f"external-blocker:{issue['record_id']}", "BLOCKED", issue["reason"],
                [run_dir / "parsed-records.json"], issue["next_action"])

    def git(*args):
        result = subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    try:
        settings = json.loads((repo_dir / ".entire/settings.json").read_text())
        head = git("rev-parse", "HEAD")
        message = git("log", "-1", "--format=%B")
        worktree_status = git("status", "--short")
        ids = [line.split(":", 1)[1].strip() for line in message.splitlines() if line.startswith("Entire-Checkpoint:")]
        refs = git("for-each-ref", "--format=%(refname) %(objectname)", "refs/entire/checkpoints").splitlines()
        matches = [line for line in refs if any(line.split()[0].endswith('/' + identity) for identity in ids)]
        require(settings.get("enabled") is True and ids and matches, "Enabled Entire.io and HEAD checkpoint reference required")
        for match in matches:
            git("cat-file", "-e", match.split()[1])
            metadata = json.loads(git("show", match.split()[1] + ":metadata.json"))
            require(isinstance(metadata, dict) and metadata, "Checkpoint metadata is empty or invalid")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        add("entire-local-evidence", "BLOCKED", str(exc), [repo_dir / ".entire/settings.json", repo_dir / ".git"],
            "Enable Entire.io and preserve a commit-linked local checkpoint; verify remote synchronization separately.")
        head, matches, worktree_status = None, [], "not_checked"
    else:
        add("entire-local-evidence", "PASS", f"HEAD {head}; local checkpoint refs: {'; '.join(matches)}. Remote synchronization is not checked.",
            [repo_dir / ".entire/settings.json", repo_dir / ".git"], "Verify remote refs separately before submission; local evidence does not prove remote synchronization.")

    status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "BLOCKED" if any(c["status"] == "BLOCKED" for c in checks) else "PASS"
    return dict(report_version="project-d-readiness/1", run_id=manifest.get("run_id"), run_dir=str(run_dir),
                status=status, integrity_status="FAIL" if status == "FAIL" else "PASS", execution_mode=mode,
                final_live_source_compliance=False, assignment_scope="Retained README, skill, schema and interview only; full native assignment page not verified",
                entire_remote_sync="not_checked", git_head=head, worktree_status=worktree_status,
                checkpoint_scope="Local HEAD checkpoint only; uncommitted changes are not certified as submitted", checks=checks)


def readiness_summary(report: dict[str, Any]) -> str:
    lines = ["# Project D submission readiness", "", f"**{report['status']}** — mode: `{report['execution_mode']}`.", "",
             "Structural evidence only. Final live-source compliance: **not established**.", "",
             report["assignment_scope"], "", report["checkpoint_scope"], ""]
    for row in report["checks"]:
        lines.extend([f"- **{row['status']}** `{row['check']}`: {row['detail']}",
                      "  - Evidence: " + "; ".join(f"`{path}`" for path in row["evidence_paths"]),
                      f"  - Next action: {row['next_action']}"])
    return "\n".join(lines) + "\n"


def write_readiness_reports(report: dict[str, Any], output_dir: Path) -> None:
    """Exclusive directory creation prevents overwriting prior validation evidence."""
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "readiness.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "readiness.md").write_text(readiness_summary(report), encoding="utf-8")

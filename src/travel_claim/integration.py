"""Arrival-ordered, policy-neutral integration of Project D records.

This module prepares schema-shaped batch state but never seals snapshots,
infers eligibility, applies review decisions, or authorizes obligations.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from .finance import reconcile_finance_events
from .event_validation import finance_context
from .ordinary import connect_claim, fields, table
from .revalidation import record_executed_rechecks
from .outputs import add_repair_item, new_repair_queue, update_repair_item, record_evidence_validation
from .workflow import (
    build_revision_history,
    match_decisions_to_subjects,
    reduce_cancellation_activities,
    row_values,
)


_REVALIDATION_AREAS = (
    ("expense-evidence", "recheck expense evidence against the corrected claim revision", "employee"),
    ("calculations", "recalculate and verify amounts for the corrected claim revision", "Travel Administration Lead"),
    ("trip-permit", "recheck trip and permit identity and revision consistency", "Travel Administration Lead"),
    ("approvals", "obtain current-revision decisions; prior decisions remain historical only", "Travel Administration Lead"),
    ("finance-authorization", "revalidate Finance authorization for the corrected claim revision", "Finance"),
)


def _page_values(record: dict[str, Any]) -> dict[str, Any]:
    return {field.get("label", "").strip(): field.get("value") for field in record.get("fields", [])}


def _page_batch(record: dict[str, Any]) -> int | None:
    value = _page_values(record).get("Arrival batch")
    return _as_batch(value)


def _as_batch(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if number > 0 and float(value) == number else None


def _ref(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("source_id", "source_sha256", "locator")}


def _ref_text(reference: dict[str, Any]) -> str:
    return f"{reference.get('source_id')}@{reference.get('source_sha256')}#{reference.get('locator')}"


def _stamp(value: Any) -> str | None:
    """Project an explicitly UTC source field into the schema's date-time form."""
    if not isinstance(value, str) or not value:
        return None
    if value.endswith("Z") or "+" in value[10:] or "-" in value[10:]:
        return value
    return f"{value}Z"


def _delta(parsed: dict[str, Any], arrival_batch: int) -> dict[str, list[dict[str, Any]]]:
    records = parsed.get("records", {})
    selected = {
        "claim_revisions": [row for row in records.get("claim_revisions", []) if _page_batch(row) == arrival_batch],
        "decisions": [row for row in records.get("decisions", []) if _as_batch(row_values(row).get("Arrival batch")) == arrival_batch],
        "finance_events": [row for row in records.get("finance_events", []) if _as_batch(row_values(row).get("Arrival batch")) == arrival_batch],
        "cancellation_activities": [row for row in records.get("cancellation_activities", []) if _as_batch(row_values(row).get("Arrival batch")) == arrival_batch],
    }
    selected["claim_revisions"].sort(key=lambda row: (row.get("page", 0), _ref(row).get("locator") or ""))
    for kind in ("decisions", "finance_events", "cancellation_activities"):
        selected[kind].sort(key=lambda row: (row.get("row", 0), _ref(row).get("locator") or ""))
    return selected


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _domain_seed() -> dict[str, Any]:
    return {
        "processed_batches": [],
        "batch_input_hashes": {},
        "claim_records": [],
        "decision_records": [],
        "finance_records": [],
        "cancellation_records": [],
        "revision_history": None,
        "decision_history": [],
        "finance_reconciliations": {},
        "ordinary_workflows": {},
        "ordinary_workflow_history": [],
        "authorized_obligations": {},
        "source_classifications": {},
        "cancellation_state": {},
        "material_corrections": [],
        "repair_queue": new_repair_queue(),
        "policy_clock_blockers": [],
        "structural_blockers": [],
        "projection_issues": [],
    }


def _issue_from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": item["item_id"],
        "reason": item["missing_or_return_reason"],
        "owner": item["owner"],
        "resolution_needed": item["next_action"],
        "subject_type": item["subject_type"],
        "subject_id": item["subject_id"],
        "revision": item["revision"],
        "source_refs": item["source_refs"],
        "run_id": item["run_id"],
        "batch_id": item["batch_id"],
    }


def _open_issue_for_subject(
    queue: dict[str, Any], *, item_id: str, subject_type: str, subject_id: str,
    revision: int, refs: list[str], reason: str, owner: str, next_action: str,
    run_id: str, batch_id: str,
) -> None:
    if item_id not in queue["items"]:
        add_repair_item(
            queue, item_id=item_id, subject_type=subject_type, subject_id=subject_id,
            revision=revision, source_refs=refs, missing_or_return_reason=reason,
            owner=owner, next_action=next_action, run_id=run_id, batch_id=batch_id,
        )


def _sync_finance_repairs(domain: dict[str, Any], reconciliations: dict[str, Any], *, run_id: str, batch_id: str) -> None:
    queue = domain["repair_queue"]
    for claim_id, result in reconciliations.items():
        for issue in result["repair_issues"]:
            item_id = f"finance:{issue['record_id']}"
            refs = list(dict.fromkeys(_ref_text(ref) for ref in issue.get("source_refs", []) if isinstance(ref, dict)))
            if item_id in queue["items"]:
                item = queue["items"][item_id]
                changes = {key: value for key, value in {
                    "source_refs": refs,
                    "missing_or_return_reason": issue["missing_or_return_reason"],
                    "next_action": issue["next_action"],
                }.items() if item[key] != value}
                if changes:
                    update_repair_item(queue, item_id=item_id,
                                       update_id=f"finance-evidence:{item_id}:{batch_id}",
                                       run_id=run_id, batch_id=batch_id, **changes)
                continue
            _open_issue_for_subject(
                queue, item_id=item_id, subject_type="claim", subject_id=claim_id,
                revision=result["claim_revision"], refs=refs,
                reason=issue.get("missing_or_return_reason", issue.get("reason", "Finance evidence unresolved")),
                owner=issue["owner"],
                next_action=issue.get("next_action", "Finance to resolve the identified item"),
                run_id=run_id, batch_id=batch_id,
            )


def _sync_ordinary_repairs(domain: dict[str, Any], *, run_id: str, batch_id: str) -> None:
    queue = domain["repair_queue"]
    for claim_id, workflow in domain["ordinary_workflows"].items():
        revision = workflow["revision"]
        stages = {s["stage"]: s for s in workflow["stages"]}
        for stage in workflow["stages"]:
            item_id = f"ordinary:{claim_id}:r{revision}:{stage['stage']}"
            if stage["status"] != "PASS":
                _open_issue_for_subject(queue, item_id=item_id, subject_type="claim", subject_id=claim_id,
                    revision=revision, refs=stage["source_refs"], reason=stage["detail"], owner=stage["owner"],
                    next_action=stage["next_action"], run_id=run_id, batch_id=batch_id)
            if item_id in queue["items"]:
                item = queue["items"][item_id]
                changes = {key: value for key, value in {"source_refs": stage["source_refs"],
                    "missing_or_return_reason": stage["detail"], "owner": stage["owner"],
                    "next_action": stage["next_action"]}.items() if item[key] != value}
                if changes:
                    update_repair_item(queue, item_id=item_id, update_id=f"ordinary-evidence:{item_id}:{batch_id}",
                                       run_id=run_id, batch_id=batch_id, **changes)
                record_evidence_validation(queue, item_id=item_id, supported=stage["status"] == "PASS",
                    source_refs=stage["source_refs"], run_id=run_id, batch_id=batch_id)
        for area, stage_name in (("expense-evidence", "supporting_evidence"), ("calculations", "policy_eligibility"),
                                 ("trip-permit", "travel_permission"), ("approvals", "required_approvals"),
                                 ("finance-authorization", "request_obligation")):
            item_id = f"correction:{claim_id}:r{revision}:{area}"
            if item_id in queue["items"]:
                stage = stages[stage_name]
                record_evidence_validation(queue, item_id=item_id, supported=stage["status"] == "PASS",
                    source_refs=stage["source_refs"], run_id=run_id, batch_id=batch_id)
        current_issues = {f"finance:{i['record_id']}" for i in domain["finance_reconciliations"][claim_id]["repair_issues"]}
        finance_refs = (domain["finance_reconciliations"][claim_id].get("authorized_obligation") or {}).get("source_refs", [])
        if finance_refs:
            for item_id, item in queue["items"].items():
                if item_id.startswith("finance:") and item["subject_id"] == claim_id and item["revision"] == revision and item_id not in current_issues:
                    record_evidence_validation(queue, item_id=item_id, supported=True, source_refs=finance_refs,
                                               run_id=run_id, batch_id=batch_id)


def _subject_claim_revisions(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return history.get("claim", {})


def _material_correction_tasks(
    domain: dict[str, Any], *, history: dict[str, Any], run_id: str, batch_id: str,
    previous_revisions: dict[str, int],
) -> None:
    queue = domain["repair_queue"]
    for claim_id, claim in _subject_claim_revisions(history).items():
        revision = claim["current_revision"]
        old_revision = previous_revisions.get(claim_id)
        if old_revision is None or revision <= old_revision:
            continue
        current = next(row for row in reversed(claim["revisions"]) if row["revision"] == revision)
        prior = [row for row in claim["revisions"] if row["revision"] == old_revision]
        refs = [_ref_text(row["source_ref"]) for row in prior + [current]]
        old_decisions = [
            decision for decision in domain["decision_history"]
            if decision.get("subject_type") == "claim" and decision.get("subject_id") == claim_id
            and decision.get("revision") == old_revision
        ]
        refs.extend(_ref_text(row["decision_source_ref"]) for row in old_decisions)
        affected_finance = [row for row in domain["finance_records"] if row_values(row).get("Claim reference") == claim_id]
        refs.extend(_ref_text(_ref(row)) for row in affected_finance)
        refs = list(dict.fromkeys(refs))
        invalidated = {
            "claim_id": claim_id,
            "from_revision": old_revision,
            "to_revision": revision,
            "invalidated_decision_ids": [row.get("decision_id") for row in old_decisions if row.get("decision_id")],
            "preserved_finance_event_ids": [row_values(row).get("Activity reference") for row in affected_finance if row_values(row).get("Activity reference")],
            "revalidate": [area for area, _, _ in _REVALIDATION_AREAS],
            "source_refs": [deepcopy(row["source_ref"]) for row in prior + [current]],
            "arrival_batch": batch_id,
        }
        domain["material_corrections"].append(invalidated)
        for area, next_action, owner_role in _REVALIDATION_AREAS:
            if owner_role == "employee":
                owner = str(current["record"].get("employee") or _page_values(current["record"]).get("Employee") or "Employee")
            elif owner_role == "Finance":
                finance_owners = [row_values(row).get("Finance officer") for row in affected_finance]
                owner = str(next((value for value in reversed(finance_owners) if value), "Finance"))
            else:
                owner = owner_role
            item_id = f"correction:{claim_id}:r{revision}:{area}"
            _open_issue_for_subject(
                queue, item_id=item_id, subject_type="claim", subject_id=claim_id,
                revision=revision, refs=refs,
                reason=f"Material correction from revision {old_revision} to {revision} requires dependency revalidation: {area}",
                owner=owner, next_action=next_action, run_id=run_id, batch_id=batch_id,
            )


def _cancellation_rows(
    domain: dict[str, Any], *, history: dict[str, Any], run_id: str, batch_id: str, parsed: dict[str, Any],
) -> list[dict[str, Any]]:
    reduced = reduce_cancellation_activities(domain["cancellation_records"],
        trips=parsed.get("records", {}).get("trips", []), people=table(parsed, "people", "People"),
        clock=parsed.get("event_clock") or parsed.get("case_clock"), arrival_batch=domain["processed_batches"][-1],
        previous_state=domain.get("cancellation_state"))
    domain["cancellation_state"] = reduced
    raw_by_id = {}
    for record in domain["cancellation_records"]:
        raw_by_id.setdefault(row_values(record).get("Cancellation activity reference"), record)
    domain["cancellation_evidence"] = {}
    for index, issue in enumerate(reduced["issues"]):
        event = next((r for r in domain["cancellation_records"] if _ref(r) == issue.get("source_ref")),
                     raw_by_id.get(issue.get("event_id")))
        value = row_values(event) if event else {}
        kind = value.get("Cancelled subject")
        subject = value.get("Trip reference") if kind == "trip" else value.get("Permit reference")
        revision = _as_batch(value.get("Trip revision") if kind == "trip" else value.get("Permit revision"))
        if kind in {"trip", "permit"} and subject and revision:
            _open_issue_for_subject(domain["repair_queue"], item_id=f"cancellation-evidence:{issue.get('event_id')}:{index}",
                subject_type=kind, subject_id=subject, revision=revision, refs=[_ref_text(_ref(event))],
                reason=issue["reason"], owner="Travel Administration Lead",
                next_action="Obtain a consistent employee initiation and linked supervisor confirmation with explicit UTC times",
                run_id=run_id, batch_id=batch_id)
    current_invalid = {i.get('event_id') for i in reduced['issues']}
    for item_id, item in domain['repair_queue']['items'].items():
        if item_id.startswith('cancellation-evidence:'):
            for event_id, record in reduced['admitted_records'].items():
                if item_id.startswith(f'cancellation-evidence:{event_id}:') and event_id not in current_invalid:
                    record_evidence_validation(domain['repair_queue'], item_id=item_id, supported=True,
                        source_refs=[_ref_text(_ref(record))], run_id=run_id, batch_id=batch_id)
    claim_revisions = _subject_claim_revisions(history)
    snapshot_rows = []
    for cancellation_id, process in sorted(reduced["processes"].items()):
        target = process["target"]
        target_revision = target.get("revision")
        if (target.get("subject_type") not in {"trip", "permit"} or not target.get("subject_id")
                or isinstance(target_revision, bool) or not isinstance(target_revision, int) or target_revision < 1):
            domain["projection_issues"].append({
                "record_id": f"cancellation-projection:{cancellation_id}",
                "reason": "cancellation process lacks a supported target identity and revision; process remains in the integration sidecar",
                "owner": "Travel Administration Lead",
                "resolution_needed": "verify the cancellation target and revision in the native workbook",
            })
            continue
        record_order = process["activity_ids"]
        if not record_order:
            continue  # Orphan evidence remains in cancellation_state and owned issues.
        request_id = record_order[0]
        request = raw_by_id[request_id]
        request_values = row_values(request)
        confirmation = next((raw_by_id[event_id] for event_id in record_order
                             if row_values(raw_by_id[event_id]).get("Action") == "confirmed"), None)
        confirmation_values = row_values(confirmation) if confirmation else {}
        trip_id = request_values.get("Trip reference")
        trip_revision = _as_batch(request_values.get("Trip revision"))
        permit_id = request_values.get("Permit reference")
        permit_revision = request_values.get("Permit revision")
        permit_revision = _as_batch(permit_revision) if permit_revision is not None else None
        affected = []
        current_affected = []
        for claim_id, claim in claim_revisions.items():
            for claim_rev in claim["revisions"]:
                if target["subject_type"] == "trip":
                    matches = claim_rev.get("trip_id") == target["subject_id"] and claim_rev.get("trip_revision") == target["revision"]
                else:
                    trip_index = history.get("trip", {}).get(str(claim_rev.get("trip_id")), {})
                    matches = any(
                        trip_rev.get("revision") == claim_rev.get("trip_revision")
                        and trip_rev.get("permit_id") == target["subject_id"]
                        and trip_rev.get("permit_revision") == target["revision"]
                        for trip_rev in trip_index.get("revisions", [])
                    )
                if matches:
                    affected.append(claim_id)
                    if claim_rev["revision"] == claim["current_revision"]:
                        current_affected.append(claim_id)
        affected = sorted(set(affected))
        task_id = f"cancellation-financial:{cancellation_id}"
        refs = [_ref_text(_ref(raw_by_id[event_id])) for event_id in record_order]
        reason = "Finance effect of the independent travel cancellation has not been resolved from an authorized Finance record"
        next_action = "Finance to record whether this cancellation affects an accepted obligation, transfer, payment, or refund"
        queue = domain["repair_queue"]
        if task_id not in queue["items"]:
            _open_issue_for_subject(
                queue, item_id=task_id,
                subject_type=target["subject_type"], subject_id=str(target["subject_id"]),
                revision=target_revision, refs=refs, reason=reason,
                owner="Finance", next_action=next_action, run_id=run_id, batch_id=batch_id,
            )
        else:
            item = queue["items"][task_id]
            additions = list(dict.fromkeys(item["source_refs"] + refs))
            changes = {}
            if additions != item["source_refs"]:
                changes["source_refs"] = additions
            if changes:
                update_repair_item(
                    queue, item_id=task_id,
                    update_id=f"cancellation-update:{cancellation_id}:batch-{batch_id}",
                    run_id=run_id, batch_id=batch_id, **changes,
                )
        cancellation_issue = task_id
        requested_at = _stamp(request_values.get("Activity time (UTC)"))
        if not trip_id or not trip_revision or not requested_at:
            domain.setdefault("projection_issues", []).append({
                "record_id": f"cancellation-projection:{cancellation_id}",
                "reason": "cancellation source lacks the trip binding or requested time required by snapshot.schema.json; process remains in the integration sidecar",
                "owner": "Travel Administration Lead",
                "resolution_needed": "verify the cancellation subject and original UTC request time from the retained workbook",
            })
            continue
        snapshot_rows.append({
            "cancellation_id": cancellation_id,
            "target_type": target["subject_type"],
            "trip_id": str(trip_id),
            "trip_revision": trip_revision,
            "permit_id": str(permit_id) if permit_id else None,
            "permit_revision": int(permit_revision) if permit_revision is not None else None,
            "status": "confirmed" if process["state"] == "confirmed" else "requested",
            "admitted_cancellation_event_ids": list(dict.fromkeys(record_order)),
            "requested_at": requested_at,
            "confirmed_at": _stamp(confirmation_values.get("Activity time (UTC)")) if confirmation else None,
            "effective_at": _stamp(confirmation_values.get("Effective time (UTC)")) if confirmation else None,
            "affected_claim_ids": affected,
            "source_refs": refs,
            "original_request_ids": sorted({row_values(r).get("Request reference") for r in domain["finance_records"]
                if row_values(r).get("Claim reference") in affected and row_values(r).get("Request reference")}),
            "financial_status": "unresolved",
            "validation_status": "BLOCKED" if any(i.get("cancellation_id")==cancellation_id for i in reduced["issues"]) else "PASS",
            "next_owner": "Finance",
            "reason": str(request_values.get("Business reason") or "Travel cancellation recorded; financial effect remains unresolved"),
            "issue_record_ids": [cancellation_issue],
        })
        # Finance dispositions are explicit claim/revision/cancellation-bound source
        # statements. They do not establish the missing policy or closure authority.
        dispositions = []
        for claim_id in affected:
            for revision in claim_revisions[claim_id]["revisions"]:
                value = _page_values(revision["record"])
                if (value.get("Travel cancellation reference") == cancellation_id
                        and value.get("Applies to claim") == claim_id
                        and str(value.get("Applies to revision")) == str(revision["revision"])
                        and value.get("Authorizing Finance officer")
                        and value.get("Allowed original amount") is not None):
                    dispositions.append({"claim_id": claim_id, "revision": revision["revision"],
                        "finance_officer": value["Authorizing Finance officer"],
                        "expense_reference": value.get("Expense reference"),
                        "allowed_original_amount": value["Allowed original amount"],
                        "reason": value.get("Exception reason"), "source_ref": _ref_text(revision["source_ref"])})
        if dispositions:
            disposition_refs = [d["source_ref"] for d in dispositions]
            changes = {
                "source_refs": list(dict.fromkeys(queue["items"][task_id]["source_refs"] + disposition_refs)),
                "missing_or_return_reason": "Cancellation-bound Finance disposition recorded; current eligibility, request authorization and financial completion remain unverified",
                "next_action": "Revalidate the cancellation-bound Finance disposition against current approvals, request revision and confirmed net cash; obtain completion authority"}
            changes = {k: v for k, v in changes.items() if queue["items"][task_id][k] != v}
            if changes:
                update_repair_item(queue, item_id=task_id,
                    update_id=f"cancellation-disposition:{cancellation_id}:{batch_id}", run_id=run_id, batch_id=batch_id, **changes)
        trips = [r for r in parsed.get("records", {}).get("trips", [])
                 if row_values(r).get("Trip reference") == trip_id
                 and _as_batch(row_values(r).get("Trip revision")) == trip_revision]
        employee = row_values(trips[0]).get("Employee ID") if len(trips) == 1 else None
        people = [r for r in table(parsed, "people", "People") if fields(r).get("Employee ID") == employee]
        supervisor = fields(people[0]).get("Supervisor") if len(people) == 1 else None
        actors_ok = bool(employee and supervisor
            and request_values.get("Acting employee or supervisor") == employee
            and confirmation_values.get("Acting employee or supervisor") == supervisor)
        actor_refs = [_ref_text(_ref(r)) for r in trips + people]
        if not actors_ok:
            _open_issue_for_subject(queue, item_id=f"cancellation-authority:{cancellation_id}",
                subject_type=target["subject_type"], subject_id=str(target["subject_id"]), revision=target_revision,
                refs=refs + actor_refs, reason="Employee initiation and supervisor confirmation not fully verified",
                owner="Travel Administration Lead", next_action="Verify the actors against the exact trip employee and People supervisor record",
                run_id=run_id, batch_id=batch_id)
        actor_item = f"cancellation-authority:{cancellation_id}"
        if actor_item in queue["items"]:
            record_evidence_validation(queue, item_id=actor_item, supported=actors_ok,
                source_refs=refs + actor_refs, run_id=run_id, batch_id=batch_id)
        domain["cancellation_evidence"][cancellation_id] = {
            "current_claim_ids": sorted(set(current_affected)),
            "source_refs": refs + actor_refs + [d["source_ref"] for d in dispositions],
            "history": deepcopy(process["history"]),
            "actor_status": "PASS" if actors_ok else "BLOCKED: verify employee and supervisor against the trip register",
            "dispositions": dispositions,
            "disposition_status": "recorded; eligibility and financial completion require recheck" if dispositions else "BLOCKED: no cancellation-bound Finance disposition",
            "request_effect": "hold payment readiness; retain obligation and cash history",
        }
    return snapshot_rows


def _sync_decision_and_revision_issues(
    domain: dict[str, Any], *, history: dict[str, Any], run_id: str, batch_id: str,
) -> None:
    queue = domain["repair_queue"]
    blockers = []
    for conflict in history.get("issues", {}).get("repeated_subject_revisions", []):
        kind = conflict["kind"]
        subject_id = conflict["subject_id"]
        revision = conflict["revision"]
        refs = [_ref_text(ref) for ref in conflict.get("occurrences", [])]
        item_id = f"revision-conflict:{kind}:{subject_id}:r{revision}"
        _open_issue_for_subject(
            queue, item_id=item_id, subject_type=kind, subject_id=subject_id,
            revision=revision, refs=refs,
            reason=f"multiple retained source records use {kind} {subject_id} revision {revision}; their business content requires review",
            owner="Travel Administration Lead", next_action="compare the source occurrences and establish the supported revision record",
            run_id=run_id, batch_id=batch_id,
        )
    for malformed in history.get("issues", {}).get("malformed_revision_records", []):
        blockers.append({
            "record_id": f"malformed-revision:{_digest(malformed)[:16]}",
            "reason": malformed["reason"],
            "owner": "Travel Administration Lead",
            "resolution_needed": "identify the subject and revision from the native source record",
            "source_ref": malformed.get("source_ref"),
        })
    for decision in domain["decision_history"]:
        if decision["structural_match"] in {"revision_match_current", "revision_match_historical"}:
            continue
        kind, subject_id, revision = decision.get("subject_type"), decision.get("subject_id"), decision.get("revision")
        decision_id = decision.get("decision_id") or _digest(decision)[:16]
        if kind in {"claim", "trip", "permit"} and isinstance(subject_id, str) and isinstance(revision, int) and revision > 0:
            item_id = f"decision-match:{decision_id}"
            _open_issue_for_subject(
                queue, item_id=item_id, subject_type=kind, subject_id=subject_id,
                revision=revision, refs=[_ref_text(decision["decision_source_ref"])],
                reason=f"recorded decision {decision_id} does not structurally match an available {kind} revision ({decision['structural_match']})",
                owner="Travel Administration Lead", next_action="resolve the decision subject or revision against the native review ledger",
                run_id=run_id, batch_id=batch_id,
            )
        else:
            blockers.append({
                "record_id": f"decision-match:{decision_id}",
                "reason": f"recorded decision has no traceable supported subject/revision ({decision['structural_match']})",
                "owner": "Travel Administration Lead",
                "resolution_needed": "identify its subject and revision in the native review ledger",
                "source_ref": decision["decision_source_ref"],
            })
    domain["structural_blockers"] = blockers


def integrate_arrival_batch(
    parsed: dict[str, Any],
    *,
    arrival_batch: int,
    run_id: str,
    batch_id: str,
    source_binding: dict[str, str],
    predecessor: dict[str, str] | None = None,
    prior_result: dict[str, Any] | None = None,
    authorized_obligations: dict[str, dict[str, Any]] | None = None,
    source_classifications: dict[str, str] | None = None,
    source_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Integrate exactly the next arrival batch into a schema-shaped projection.

    The function retains raw subject/activity rows in a sidecar `domain`,
    carries earlier state forward, and supports exact same-batch replay. It
    does not consume or seal a scenario snapshot; callers must separately
    verify access, case clock, policy, and authorities before doing that.
    """
    if isinstance(arrival_batch, bool) or not isinstance(arrival_batch, int) or arrival_batch < 1:
        raise ValueError("arrival_batch must be a positive integer")
    if not run_id or not batch_id or not isinstance(source_binding, dict):
        raise ValueError("run_id, batch_id, and source_binding are required")
    delta = _delta(parsed, arrival_batch)
    digest = _digest({
        "delta": delta,
        "run_id": run_id,
        "batch_id": batch_id,
        "source_binding": source_binding,
        "predecessor": predecessor,
        "authorized_obligations": authorized_obligations or {},
        "source_classifications": source_classifications or {},
        "trip_reference_records": parsed.get("records", {}).get("trips", []),
        "unresolved_issues": parsed.get("unresolved_issues", []),
        "ordinary_evidence": {key: parsed.get(key) for key in ("records", "workbook_sheets", "case_clock", "event_clock", "evidence_mode", "expense_policy")},
        "source_observations": source_observations or [],
    })
    previous_domain = deepcopy(prior_result["domain"]) if prior_result else _domain_seed()
    processed = previous_domain["processed_batches"]
    if processed and arrival_batch == processed[-1]:
        if previous_domain["batch_input_hashes"].get(str(arrival_batch)) == digest:
            return deepcopy(prior_result)
        raise ValueError(f"conflicting replay for arrival batch {arrival_batch}")
    expected_batch = processed[-1] + 1 if processed else 1
    if arrival_batch != expected_batch:
        raise ValueError(f"arrival batches must be integrated in explicit order; expected {expected_batch}, got {arrival_batch}")
    if prior_result is None and predecessor is not None:
        raise ValueError("the first integrated batch must have a null predecessor")
    if prior_result is not None:
        if prior_result.get("snapshot", {}).get("run_id") != run_id:
            raise ValueError("prior integration state belongs to a different run")
        if predecessor is None:
            raise ValueError("a later integrated batch must carry a predecessor binding")

    before_batch = deepcopy(previous_domain)
    domain = previous_domain
    if authorized_obligations:
        domain["authorized_obligations"].update(deepcopy(authorized_obligations))
    if source_classifications:
        domain["source_classifications"].update(deepcopy(source_classifications))
    previous_claim_revisions = {
        subject_id: value["current_revision"]
        for subject_id, value in (domain.get("revision_history") or {}).get("claim", {}).items()
    }
    for name in ("claim_revisions", "decisions", "finance_events", "cancellation_activities"):
        target_name = {
            "claim_revisions": "claim_records", "decisions": "decision_records",
            "finance_events": "finance_records", "cancellation_activities": "cancellation_records",
        }[name]
        domain[target_name].extend(deepcopy(delta[name]))
    domain["processed_batches"].append(arrival_batch)
    domain["batch_input_hashes"][str(arrival_batch)] = digest

    history = build_revision_history({
        "records": {"claim_revisions": domain["claim_records"], "trips": parsed.get("records", {}).get("trips", [])}
    })
    domain["revision_history"] = history
    domain["decision_history"] = match_decisions_to_subjects(domain["decision_records"], history)
    for decision, raw in zip(domain["decision_history"], domain["decision_records"]):
        decision["arrival_batch"] = row_values(raw).get("Arrival batch")
        decision["applied"] = False
    _sync_decision_and_revision_issues(domain, history=history, run_id=run_id, batch_id=batch_id)
    _material_correction_tasks(
        domain, history=history, run_id=run_id, batch_id=batch_id,
        previous_revisions=previous_claim_revisions,
    )

    current_claims = {}
    for claim_id, record_set in history.get("claim", {}).items():
        current_revision = record_set["current_revision"]
        claim_revision = next(row for row in reversed(record_set["revisions"]) if row["revision"] == current_revision)
        current_claims[claim_id] = claim_revision
    cancellation_rows = _cancellation_rows(domain, history=history, run_id=run_id, batch_id=batch_id, parsed=parsed)
    finance_results = {}
    for claim_id, claim_revision in current_claims.items():
        record_set = history["claim"][claim_id]
        prior_finance = domain["finance_reconciliations"].get(claim_id)
        finance_results[claim_id] = reconcile_finance_events(
            domain["finance_records"], claim_id=claim_id,
            current_revision=claim_revision["revision"],
            authorized_obligation=domain["authorized_obligations"].get(claim_id),
            revision_history=record_set["revisions"],
            previous_reconciliation=prior_finance,
            source_classifications=domain["source_classifications"],
            event_context=finance_context(parsed, record_set["revisions"], domain["finance_records"], claim_id, arrival_batch),
        )
    from .budget import reconcile_budgets, attribute_costs
    budgets=reconcile_budgets(parsed=parsed,history=history,finances=finance_results,arrival_batch=arrival_batch,
        observations=source_observations or [],cancellations=cancellation_rows,prior=before_batch.get('budget'),raw_finance=domain['finance_records'])
    attribution=attribute_costs(parsed=parsed,history=history,budgets=budgets,arrival_batch=arrival_batch,
        observations=source_observations or [],cancellations=cancellation_rows)
    budgets['cost_attribution']=attribution;budgets['claim_views']={}
    domain['budget']=budgets
    from .approvals import evaluate_permit
    from .budget import permit_budget_context
    domain['permit_approvals']={}
    for permit_id,subject in history.get('permit',{}).items():
        current=next(r for r in reversed(subject['revisions']) if r['revision']==subject['current_revision'])
        key=f"{permit_id}:r{current['revision']}"
        budget_context=permit_budget_context(parsed=parsed,trip_record=current['record'],budgets=budgets,
            prior=(before_batch.get('permit_approvals',{}).get(key) or {}).get('budget_context'),arrival_batch=arrival_batch)
        review=evaluate_permit(parsed=parsed,trip_record=current['record'],decisions=domain['decision_records'],
            arrival_batch=arrival_batch,observations=source_observations or [],
            prior=before_batch.get('permit_approvals',{}).get(key),cancellations=cancellation_rows,budget_context=budget_context)
        domain['permit_approvals'][key]=review
        if not review['approved'] or not review['arrangement_authorized']:
            item_id=f"permit-approval:{key}"
            _open_issue_for_subject(domain['repair_queue'],item_id=item_id,subject_type='permit',subject_id=permit_id,
                revision=current['revision'],refs=review['source_refs'],reason=f"Permit review state: {review['state']}; arrangement authority/timing requires current evidence",
                owner='Travel Administration Lead',next_action='Obtain current permit-role decisions and resolve timing or cancellation holds',run_id=run_id,batch_id=batch_id)
        if f"permit-approval:{key}" in domain['repair_queue']['items']:
            record_evidence_validation(domain['repair_queue'],item_id=f"permit-approval:{key}",
                supported=review['approved'] and review['arrangement_authorized'],source_refs=review['source_refs'],run_id=run_id,batch_id=batch_id)
    domain.setdefault('permit_approval_history',[]).append({'batch_id':batch_id,'permits':deepcopy(domain['permit_approvals'])})
    for claim_id,claim_revision in current_claims.items():
        prior_finance=before_batch.get('finance_reconciliations',{}).get(claim_id)
        workflow = connect_claim(parsed=parsed, claim=claim_revision, decisions=domain["decision_records"],
            finance_events=domain["finance_records"], finance=finance_results[claim_id],
            cancellations=cancellation_rows, arrival_batch=arrival_batch,
            source_observations=source_observations or [], prior_finance=prior_finance,
            source_classifications=domain["source_classifications"],
            prior_workflow=before_batch.get("ordinary_workflows", {}).get(claim_id),
            budget_data=budgets,prepaid_data=attribution,prior_budget_view=before_batch.get("budget",{}).get("claim_views",{}).get(claim_id))
        finance_results[claim_id] = workflow.pop("finance")
        budgets["claim_views"][claim_id]=deepcopy(workflow["budget_view"])
        domain["ordinary_workflows"][claim_id] = workflow
        domain["ordinary_workflow_history"].append({"batch_id": batch_id, "workflow": deepcopy(workflow)})
    domain["finance_reconciliations"] = finance_results
    # Projection only: never alter admitted cancellation or Finance history.
    from .expenses import policy_valid
    domain['completion_evidence'] = {'clock': deepcopy(parsed.get('event_clock') or parsed.get('case_clock')),
        'policy_verified': policy_valid(parsed.get('expense_policy'))}
    for cancellation in cancellation_rows:
        linked = cancellation['affected_claim_ids']
        resolved = (bool(linked) and cancellation['status']=='confirmed'
            and cancellation.get('validation_status')=='PASS'
            and all(domain['ordinary_workflows'][cid]['status'].startswith('closed-') for cid in linked))
        if resolved:
            cancellation.update(financial_status='resolved', next_owner=None)
        from .completion import no_claim_financial_effect_refs
        absence_refs = no_claim_financial_effect_refs(parsed, domain, cancellation, source_observations or [], arrival_batch)
        if absence_refs:
            cancellation.update(financial_status='no-financial-effect', next_owner=None)
            resolved = True
        cancellation['financial_source_refs'] = list(dict.fromkeys(absence_refs + [r for cid in linked
            for r in domain['ordinary_workflows'][cid]['source_refs']]))
        record_evidence_validation(domain['repair_queue'], item_id=f"cancellation-financial:{cancellation['cancellation_id']}",
            supported=resolved, source_refs=cancellation['source_refs'] + absence_refs + [r for cid in linked
                for r in domain['ordinary_workflows'][cid]['source_refs']], run_id=run_id, batch_id=batch_id)
    domain.setdefault('cancellation_financial_history', []).append({'batch_id': batch_id, 'cancellations': deepcopy(cancellation_rows)})
    for scope in budgets['scopes'].values():
        for request in scope['requests'].values():
            result=finance_results.get(request['claim_id'],{})
            matching=(result.get('recorded_obligation') or {}).get('request_id')==request['request_id']
            authorization=result.get('authorized_obligation') if matching else None
            request['authorized_obligation_cents']=authorization['amount_cents'] if authorization else None
            request['authorized_balance_cents']=result.get('balance_cents') if authorization else None
    domain.setdefault('budget_history',[]).append({'batch_id':batch_id,'budget':deepcopy(budgets)})
    for claim_id,workflow in domain['ordinary_workflows'].items():
        for n,issue in enumerate(workflow['budget_view']['issues']):
            item_id=f"budget-detail:{claim_id}:r{workflow['revision']}:{_digest(issue['reason'])[:12]}"
            _open_issue_for_subject(domain['repair_queue'],item_id=item_id,subject_type='claim',subject_id=claim_id,
                revision=workflow['revision'],refs=issue['source_refs'],reason=issue['reason'],owner=issue['owner'],
                next_action=issue['next_action'],run_id=run_id,batch_id=batch_id)
        current={_digest(i['reason'])[:12] for i in workflow['budget_view']['issues']}
        for item_id,item in domain['repair_queue']['items'].items():
            if item_id.startswith(f"budget-detail:{claim_id}:r{workflow['revision']}:") and item_id.rsplit(':',1)[-1] not in current:
                record_evidence_validation(domain['repair_queue'],item_id=item_id,supported=True,
                    source_refs=workflow['budget_view']['source_refs'],run_id=run_id,batch_id=batch_id)
    record_executed_rechecks(domain, before_batch, batch_id=batch_id)
    _sync_finance_repairs(domain, finance_results, run_id=run_id, batch_id=batch_id)

    # Policy and case-clock blockers are copied from parser/source evidence and
    # deliberately remain outside any fabricated claim/decision outcome.
    blockers = []
    for row in parsed.get("unresolved_issues", []):
        blocker = {
            "record_id": row["record_id"],
            "reason": row.get("reason", "Unresolved source issue"),
            "owner": row.get("owner", "Exercise facilitator"),
            "resolution_needed": row.get("next_action", "Obtain the missing authoritative evidence"),
            "subject_type": row.get("subject_type"),
            "subject_id": row.get("subject_id"),
            "affected_scope": row.get("affected_scope"),
            "evidence_needed": row.get("evidence_needed"),
        }
        blockers.append(blocker)
    domain["policy_clock_blockers"] = blockers

    _sync_ordinary_repairs(domain, run_id=run_id, batch_id=batch_id)
    schema_issues = list(blockers) + list(domain.get("structural_blockers", []))
    schema_issues.extend(_issue_from_item(item) for item in domain["repair_queue"]["items"].values() if item["status"] == "open")
    # Every cancellation issue reference must resolve in issues[].record_id.
    known_issue_ids = {issue["record_id"] for issue in schema_issues}
    for cancellation in cancellation_rows:
        cancellation["issue_record_ids"] = [
            issue_id for issue_id in cancellation["issue_record_ids"] if issue_id in known_issue_ids
        ]

    snapshot_claims = []
    projection_issues = []
    for claim_id, revision_row in sorted(current_claims.items()):
        revision = revision_row["revision"]
        record = revision_row["record"]
        values = _page_values(record)
        trip_id = revision_row.get("trip_id")
        trip_revision = revision_row.get("trip_revision")
        if not trip_id or not trip_revision:
            projection_issues.append({
                "record_id": f"snapshot-claim-link:{claim_id}:r{revision}",
                "reason": "claim source lacks the trip identity or revision required by snapshot.schema.json; claim omitted from snapshot projection",
                "owner": "Travel Administration Lead",
                "resolution_needed": "obtain and verify the current claim-to-trip revision binding",
            })
            continue
        trip_record_set = history.get("trip", {}).get(str(trip_id), {})
        linked_trip = any(row["revision"] == trip_revision for row in trip_record_set.get("revisions", []))
        if not linked_trip:
            item_id = f"trip-link:{claim_id}:r{revision}"
            _open_issue_for_subject(
                domain["repair_queue"], item_id=item_id, subject_type="claim", subject_id=claim_id,
                revision=revision, refs=[_ref_text(revision_row["source_ref"])],
                reason=f"claim references trip {trip_id} revision {trip_revision}, which is not present in the retained trip register",
                owner="Travel Administration Lead", next_action="verify the trip revision from an accessible native travel register",
                run_id=run_id, batch_id=batch_id,
            )
            schema_issues.append(_issue_from_item(domain["repair_queue"]["items"][item_id]))
        matches = [row for row in domain["decision_history"]
                   if row.get("subject_type") == "claim" and row.get("subject_id") == claim_id
                   and row.get("revision") == revision and row.get("structural_match") == "revision_match_current"]
        finance = finance_results[claim_id]
        workflow = domain["ordinary_workflows"][claim_id]
        snapshot_claims.append({
            "claim_id": claim_id,
            "revision": revision,
            "trip_id": str(trip_id),
            "trip_revision": trip_revision,
            "status": workflow["status"],
            "ordinary_workflow": deepcopy(workflow),
            "lines": [{"cost_id": line["cost_id"], "source_ids": list(dict.fromkeys(ref.split('@', 1)[0] for ref in line["source_refs"])),
                       "status": line["status"], "allowed_cents": line["allowed_cents"], "reason": line["reason"],
                       "source_refs": line["source_refs"], "original_cents": line["original_cents"],
                       "currency": line["currency"], "evidence_status": line["evidence_status"]} for line in workflow["lines"]],
            "allowed_cents": workflow["allowed_cents"],
            "finance_evidence": {
                "recorded_obligation": deepcopy(finance["recorded_obligation"]),
                "recorded_ledger_balance_cents": finance["recorded_ledger_balance_cents"],
                "basis": "Recorded request ledger only; not reviewed entitlement or current-revision authorization",
                "current_revision_authority_confirmed": workflow["request"] is not None,
                "closure_authority_confirmed": workflow["status"].startswith('closed-'),
            },
            "paid_cents": finance["net_confirmed_cents"],
            "balance_cents": finance["balance_cents"],
            "decision_ids": list(dict.fromkeys(row["decision_id"] for row in matches if row.get("decision_id"))),
            "next_owner": workflow["next_owner"],
            "reason": workflow["reason"],
        })

    schema_issues.extend(projection_issues)
    schema_issues.extend(domain.get("projection_issues", []))
    # Deduplicate by record_id while preserving issue order.
    unique_issues = {}
    for issue in schema_issues:
        unique_issues.setdefault(issue["record_id"], issue)
    schema_issues = list(unique_issues.values())

    finance_ids = list(dict.fromkeys(event_id for result in finance_results.values()
                                     for event_id in result['admitted_event_ids']))
    domain['unmatched_finance_records'] = [deepcopy(r) for r in domain['finance_records']
        if row_values(r).get('Claim reference') not in current_claims]
    for record in domain['unmatched_finance_records']:
        schema_issues.append({'record_id': f"finance-unmatched:{_digest(record)[:16]}",
            'reason': 'Finance event has no matching claim; retained without admission', 'owner': 'Finance',
            'resolution_needed': 'Resolve source claim/request identity before admission', 'source_ref': _ref(record)})

    snapshot = {
        "schema_version": "travel-claim-snapshot/2",
        "run_id": run_id,
        "batch_id": batch_id,
        "predecessor": deepcopy(predecessor),
        "source_binding": deepcopy(source_binding),
        "claims": snapshot_claims,
        "permit_approvals": deepcopy(domain["permit_approvals"]),
        "budget_reconciliation": deepcopy(budgets),
        "requests": [{"request_id": row_values(w["request"])["Request reference"], "claim_id": w["claim_id"],
                      "revision": w["revision"], "amount_cents": w["allowed_cents"],
                      "payee": row_values(w["request"])["Payee ID"], "currency": "EUR", "status": "held" if any(w["claim_id"] in c["affected_claim_ids"] and c["financial_status"]=="unresolved" for c in cancellation_rows) else "accepted",
                      "decision_ids": list(dict.fromkeys(d["decision_id"] for d in w["observed_reviews"] if d["outcome"] == "approve" and d.get('active') and d.get('evidence_valid'))),
                      "source_refs": [_ref_text(_ref(w["request"]))], "origin": "observed source request; no request sent"}
                     for w in domain["ordinary_workflows"].values() if w["request"] is not None],
        "travel_cancellations": cancellation_rows,
        "admitted_event_ids": finance_ids,
        "issues": schema_issues,
    }
    domain["processed_batches"] = list(domain["processed_batches"])
    return {
        "snapshot": snapshot,
        "domain": domain,
        "decision_history": deepcopy(domain["decision_history"]),
        "finance_reconciliations": deepcopy(finance_results),
        "revision_history": deepcopy(history),
        "repair_queue_by_owner": _owner_view(domain["repair_queue"]),
        "batch_delta_counts": {key: len(value) for key, value in delta.items()},
        "input_sha256": digest,
    }


def _owner_view(queue: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in queue["items"].values():
        grouped.setdefault(item["owner"], []).append(item)
    return {owner: sorted(items, key=lambda row: row["item_id"]) for owner, items in sorted(grouped.items())}

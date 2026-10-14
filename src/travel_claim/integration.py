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
from .outputs import add_repair_item, new_repair_queue, update_repair_item
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
            refs = [_ref_text(ref) for ref in issue.get("source_refs", []) if isinstance(ref, dict)]
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
    domain: dict[str, Any], *, history: dict[str, Any], run_id: str, batch_id: str,
) -> list[dict[str, Any]]:
    reduced = reduce_cancellation_activities(domain["cancellation_records"])
    domain["cancellation_state"] = reduced
    raw_by_id = {
        row_values(record).get("Cancellation activity reference"): record
        for record in domain["cancellation_records"]
    }
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
        request_id = record_order[0]
        request = raw_by_id[request_id]
        request_values = row_values(request)
        confirmation = next((raw_by_id[event_id] for event_id in record_order
                             if row_values(raw_by_id[event_id]).get("Action") == "confirmed"), None)
        confirmation_values = row_values(confirmation) if confirmation else {}
        trip_id = request_values.get("Trip reference")
        trip_revision = _as_batch(request_values.get("Trip revision"))
        permit_id = request_values.get("Permit reference") if target["subject_type"] == "permit" else None
        permit_revision = request_values.get("Permit revision") if target["subject_type"] == "permit" else None
        permit_revision = _as_batch(permit_revision) if permit_revision is not None else None
        affected = []
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
                    break
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
            if process["state"] == "confirmed" and item["next_action"] != next_action:
                changes["next_action"] = next_action
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
            "original_request_ids": [],
            "financial_status": "unresolved",
            "next_owner": "Finance",
            "reason": str(request_values.get("Business reason") or "Travel cancellation recorded; financial effect remains unresolved"),
            "issue_record_ids": [cancellation_issue],
        })
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
        )
    domain["finance_reconciliations"] = finance_results
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

    cancellation_rows = _cancellation_rows(domain, history=history, run_id=run_id, batch_id=batch_id)
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
        snapshot_claims.append({
            "claim_id": claim_id,
            "revision": revision,
            "trip_id": str(trip_id),
            "trip_revision": trip_revision,
            "status": "pending",
            "lines": [],
            "allowed_cents": None,
            "finance_evidence": {
                "recorded_obligation": deepcopy(finance["recorded_obligation"]),
                "recorded_ledger_balance_cents": finance["recorded_ledger_balance_cents"],
                "basis": "Recorded request ledger only; not reviewed entitlement or current-revision authorization",
                "current_revision_authority_confirmed": False,
                "closure_authority_confirmed": False,
            },
            "paid_cents": finance["net_confirmed_cents"],
            "balance_cents": finance["balance_cents"],
            "decision_ids": list(dict.fromkeys(row["decision_id"] for row in matches if row.get("decision_id"))),
            "next_owner": "Travel Administration Lead",
            "reason": "Structural integration only; reimbursement policy and current-revision compliance remain unresolved.",
        })

    schema_issues.extend(projection_issues)
    schema_issues.extend(domain.get("projection_issues", []))
    # Deduplicate by record_id while preserving issue order.
    unique_issues = {}
    for issue in schema_issues:
        unique_issues.setdefault(issue["record_id"], issue)
    schema_issues = list(unique_issues.values())

    finance_ids = []
    unresolved_ids = set()
    conflicting_ids = set()
    for result in finance_results.values():
        unresolved_ids.update(result["unresolved_event_ids"])
        conflicting_ids.update(issue["event_id"] for issue in result["conflicting_events"])
        for event in result["event_history"]:
            event_id = event["event_id"]
            if (event_id and event_id not in unresolved_ids and event_id not in conflicting_ids
                    and event["classification"] not in {"unresolved", "conflicting_event_id", "missing_event_id"}):
                finance_ids.append(event_id)
    finance_ids = list(dict.fromkeys(event_id for event_id in finance_ids if event_id not in unresolved_ids | conflicting_ids))

    snapshot = {
        "schema_version": "travel-claim-snapshot/2",
        "run_id": run_id,
        "batch_id": batch_id,
        "predecessor": deepcopy(predecessor),
        "source_binding": deepcopy(source_binding),
        "claims": snapshot_claims,
        "requests": [],
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

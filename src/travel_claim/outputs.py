"""Deterministic claim summary CSV and owner-grouped local repair queue."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any


CLAIMS_COLUMNS = (
    "claim_id",
    "revision",
    "trip_id",
    "status",
    "allowed_cents",
    "paid_cents",
    "balance_cents",
    "next_owner",
    "reason",
)

CLAIM_STATUSES = {
    "pending", "held", "ready", "closed-reimbursed", "closed-no-payment", "rejected", "withdrawn"
}


def clean_business_disposition(claim: dict) -> bool:
    """Use the workflow's financial-clean disposition, never a raw source label."""
    return claim.get('status') in {'withdrawn', 'rejected'} and claim.get('next_owner') is None


def reimbursement_only_stage(name: str) -> bool:
    # Independent linkage, arrangements, budget facts and cancellations remain actionable.
    return name in {'supporting_evidence', 'filing_deadline', 'policy_eligibility',
        'budget_owner_authorization', 'review_evidence', 'required_approvals',
        'exception_revalidation', 'request_obligation', 'financial_reconciliation',
        'finance_resolution', 'financial_closure'} or name.startswith(
            ('finance_exception:', 'eligibility:', 'review_return:'))


def project_claim_outputs(claims: list[dict], queue: dict) -> list[dict]:
    """Preserve final dispositions; select repairs only for unfinished claims."""
    owners, reasons = {}, {}
    for item in queue['items'].values():
        if item['subject_type'] == 'claim' and item['status'] == 'open':
            owners.setdefault(item['subject_id'], item['owner'])
            reasons.setdefault(item['subject_id'], item['missing_or_return_reason'])
    rows = []
    for claim in claims:
        final = clean_business_disposition(claim) or claim['status'].startswith('closed-')
        rows.append({**{key: claim[key] for key in CLAIMS_COLUMNS[:7]},
            'next_owner': None if final else owners.get(claim['claim_id'], claim['next_owner']),
            'reason': claim['reason'] if final else reasons.get(claim['claim_id'],
                'Offline structural replay; policy eligibility and reimbursement entitlement remain unresolved.')})
    return rows


def mark_repair_inapplicable(queue: dict, *, item_id: str, workflow: dict,
                             run_id: str, batch_id: str) -> None:
    """Retire pursuit tasks with evidence, without asserting approval or payment."""
    item = queue['items'].get(item_id)
    if item is None or item['status'] != 'open':
        return
    event = dict(event='repair-inapplicable', item_id=item_id, previous_status=item['status'],
        status='superseded', source_refs=list(workflow['source_refs']),
        reason=workflow['reason'], run_id=run_id, batch_id=batch_id,
        origin='local disposition scope check; no approval or Finance resolution created')
    item['history'].append(dict(event))
    queue['events'].append(event)
    item['status'] = 'superseded'

REPAIR_ITEM_FIELDS = (
    "item_id",
    "subject_type",
    "subject_id",
    "revision",
    "source_refs",
    "missing_or_return_reason",
    "owner",
    "next_action",
)


def _money(value: Any, field: str, allow_negative: bool = False) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be integer cents or null")
    if not allow_negative and value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def write_claims_csv(claims: list[dict], path: Path) -> None:
    """Write one row per supplied current claim with the required exact header."""
    ids = [claim.get("claim_id") for claim in claims]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("claims must contain one nonempty, unique current row per claim_id")
    prepared = []
    for claim in sorted(claims, key=lambda row: row["claim_id"]):
        missing = set(CLAIMS_COLUMNS) - set(claim)
        if missing:
            raise ValueError(f"claim {claim.get('claim_id')} is missing CSV fields: {sorted(missing)}")
        row = {key: claim[key] for key in CLAIMS_COLUMNS}
        if isinstance(row["revision"], bool) or not isinstance(row["revision"], int) or row["revision"] < 1:
            raise ValueError(f"claim {claim['claim_id']} revision must be a positive integer")
        for key in ("claim_id", "trip_id", "status"):
            if not isinstance(row[key], str) or not row[key]:
                raise ValueError(f"{key} must be a nonempty string")
        if row["status"] not in CLAIM_STATUSES:
            raise ValueError(f"unsupported claim status {row['status']!r}")
        row["allowed_cents"] = _money(row["allowed_cents"], "allowed_cents")
        row["paid_cents"] = _money(row["paid_cents"], "paid_cents")
        row["balance_cents"] = _money(row["balance_cents"], "balance_cents", allow_negative=True)
        for key in ("next_owner", "reason"):
            if row[key] is not None and not isinstance(row[key], str):
                raise ValueError(f"{key} must be a string or null")
            row[key] = "" if row[key] is None else row[key]
        prepared.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CLAIMS_COLUMNS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(prepared)


def new_repair_queue() -> dict:
    return {"queue_version": "owner-queue/1", "items": {}, "events": []}


def add_repair_item(
    queue: dict,
    *,
    item_id: str,
    subject_type: str,
    subject_id: str,
    revision: int,
    source_refs: list[str],
    missing_or_return_reason: str,
    owner: str,
    next_action: str,
    run_id: str,
    batch_id: str,
) -> None:
    """Add a distinct open item. Request content is a local draft only."""
    if not item_id or item_id in queue["items"]:
        raise ValueError(f"repair item ID is empty or already exists: {item_id!r}")
    if subject_type not in {"claim", "trip", "permit"}:
        raise ValueError("subject_type must be claim, trip, or permit")
    if not subject_id or not owner or not missing_or_return_reason or not next_action:
        raise ValueError("subject, owner, reason, and next action are required")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer")
    if not isinstance(source_refs, list) or not all(isinstance(ref, str) and ref for ref in source_refs):
        raise ValueError("source_refs must be a list of nonempty references")
    item = {
        "item_id": item_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "revision": revision,
        "source_refs": list(dict.fromkeys(source_refs)),
        "missing_or_return_reason": missing_or_return_reason,
        "owner": owner,
        "next_action": next_action,
        "status": "open",
        "run_id": run_id,
        "batch_id": batch_id,
        "response_id": None,
        "resolution_source_refs": [],
        "history": [],
        "request_draft": {"status": "draft", "sent": False},
    }
    queue["items"][item_id] = item
    queue["events"].append({
        "event": "item-opened",
        "item_id": item_id,
        "run_id": run_id,
        "batch_id": batch_id,
        "status": "open",
    })


def apply_partial_response(
    queue: dict,
    *,
    response_id: str,
    item_outcomes: dict[str, dict],
    run_id: str,
    batch_id: str,
) -> None:
    """Record a supplied response against explicitly matched repair item IDs.

    Only `supported` plus at least one retained source reference resolves an
    item. Every other outcome remains open. Unmentioned items are untouched.
    """
    allowed = {"supported", "insufficient", "conflicting", "unanswered"}
    if not response_id:
        raise ValueError("response_id is required")
    if not isinstance(item_outcomes, dict):
        raise ValueError("item_outcomes must map repair item IDs to outcomes")
    planned: list[tuple[str, dict, str, list[str], dict | None]] = []
    for item_id, outcome in item_outcomes.items():
        if item_id not in queue["items"]:
            raise KeyError(f"response references unknown repair item {item_id}")
        if not isinstance(outcome, dict):
            raise ValueError(f"response outcome for {item_id} must be an object")
        kind = outcome.get("outcome")
        if kind not in allowed:
            raise ValueError(f"invalid response outcome for {item_id}: {kind!r}")
        refs = outcome.get("source_refs", [])
        if not isinstance(refs, list) or not all(isinstance(ref, str) and ref for ref in refs):
            raise ValueError(f"response source_refs must be a list of references for {item_id}")
        if kind == "supported" and not refs:
            raise ValueError(f"supported response {item_id} requires source references")
        item = queue["items"][item_id]
        if outcome.get("note") is not None and not isinstance(outcome.get("note"), str):
            raise ValueError(f"response note must be a string or null for {item_id}")
        prior_event = next(
            (event for event in reversed(queue["events"])
             if event.get("event") == "response-recorded"
             and event.get("response_id") == response_id
             and event.get("item_id") == item_id),
            None,
        )
        normalized_refs = list(dict.fromkeys(refs))
        if prior_event is not None:
            same = (
                prior_event.get("outcome") == kind
                and prior_event.get("source_refs") == normalized_refs
                and prior_event.get("note") == outcome.get("note")
            )
            if same:
                planned.append((item_id, item, kind, normalized_refs, prior_event))
                continue
            raise ValueError(f"conflicting replay for repair response {response_id}/{item_id}")
        planned.append((item_id, item, kind, normalized_refs, None))

    # Mutate only after every item in this partial response passed validation.
    for item_id, item, kind, normalized_refs, prior_event in planned:
        if prior_event is not None:
            continue
        prior = {
            "response_id": response_id,
            "outcome": kind,
            "note": item_outcomes[item_id].get("note"),
            "source_refs": normalized_refs,
            "run_id": run_id,
            "batch_id": batch_id,
            "previous_status": item["status"],
        }
        item["history"].append(prior)
        item["response_id"] = response_id
        if kind == "supported":
            item["status"] = "resolved"
            item["resolution_source_refs"] = normalized_refs
        else:
            item["status"] = "open"
        queue["events"].append({
            "event": "response-recorded",
            "item_id": item_id,
            "response_id": response_id,
            "outcome": kind,
            "note": outcome.get("note"),
            "source_refs": normalized_refs,
            "run_id": run_id,
            "batch_id": batch_id,
            "status": item["status"],
        })


def update_repair_item(
    queue: dict,
    *,
    item_id: str,
    update_id: str,
    run_id: str,
    batch_id: str,
    revision: int | None = None,
    source_refs: list[str] | None = None,
    missing_or_return_reason: str | None = None,
    owner: str | None = None,
    next_action: str | None = None,
) -> None:
    """Update a repair item's mutable trace fields without losing its history.

    Item and subject identity never change. Advancing its subject revision
    reopens the item and clears the prior resolution pointer while preserving
    the prior response and fields in the append-only history.
    """
    if not update_id:
        raise ValueError("update_id is required")
    if item_id not in queue.get("items", {}):
        raise KeyError(f"unknown repair item {item_id}")
    item = queue["items"][item_id]
    changes = {}
    if revision is not None:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("revision must be a positive integer")
        if revision < item["revision"]:
            raise ValueError("repair item revision cannot move backwards")
        changes["revision"] = revision
    if source_refs is not None:
        if not isinstance(source_refs, list) or not all(isinstance(ref, str) and ref for ref in source_refs):
            raise ValueError("source_refs must be a list of nonempty references")
        changes["source_refs"] = list(dict.fromkeys(source_refs))
    for field, value in (("missing_or_return_reason", missing_or_return_reason),
                         ("owner", owner), ("next_action", next_action)):
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a nonempty string")
            changes[field] = value
    replay = next((event for event in queue["events"] if event.get("event") == "item-updated"
                   and event.get("update_id") == update_id), None)
    normalized = {key: changes[key] for key in sorted(changes)}
    if replay is not None:
        if replay.get("item_id") == item_id and replay.get("changes") == normalized:
            return
        raise ValueError(f"conflicting replay for repair update {update_id}")
    if not changes:
        raise ValueError("repair item update contains no field changes")
    before = {key: item[key] for key in changes}
    if all(before[key] == changes[key] for key in changes):
        raise ValueError("repair item update does not change any field")
    history = {
        "event": "item-updated", "update_id": update_id,
        "previous": before, "changes": normalized,
        "previous_status": item["status"], "previous_response_id": item["response_id"],
        "previous_resolution_source_refs": list(item["resolution_source_refs"]),
        "run_id": run_id, "batch_id": batch_id,
    }
    item["history"].append(history)
    item.update(changes)
    if "revision" in changes and changes["revision"] != before["revision"]:
        item["status"] = "open"
        item["response_id"] = None
        item["resolution_source_refs"] = []
    queue["events"].append({
        "event": "item-updated", "item_id": item_id, "update_id": update_id,
        "changes": normalized, "run_id": run_id, "batch_id": batch_id,
        "status": item["status"],
    })


def owner_grouped_view(queue: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in queue["items"].values():
        grouped.setdefault(item["owner"], []).append(item)
    return {owner: sorted(items, key=lambda row: row["item_id"]) for owner, items in sorted(grouped.items())}


def load_repair_queue(path: Path) -> dict:
    """Load the persisted queue, validating individual item and audit structure."""
    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read repair queue: {exc}") from exc
    if not isinstance(persisted, dict):
        raise ValueError("repair queue must contain an object")
    if persisted.get("queue_version") != "owner-queue/1":
        raise ValueError("unsupported repair queue version")
    queue = {key: value for key, value in persisted.items() if key != "by_owner"}
    if not isinstance(queue.get("items"), dict) or not isinstance(queue.get("events"), list):
        raise ValueError("repair queue must contain item map and event history")
    for item_id, item in queue["items"].items():
        if item.get("item_id") != item_id or item.get("status") not in {"open", "resolved", "superseded"}:
            raise ValueError(f"invalid repair queue item {item_id}")
        if any(field not in item for field in REPAIR_ITEM_FIELDS):
            raise ValueError(f"repair queue item {item_id} is missing trace fields")
    expected_grouping = {
        owner: [item["item_id"] for item in items]
        for owner, items in owner_grouped_view(queue).items()
    }
    if persisted.get("by_owner") != expected_grouping:
        raise ValueError("persisted owner grouping does not match item owners")
    return queue


def write_repair_queue(queue: dict, path: Path) -> None:
    """Persist queue and history atomically without dropping prior item events."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old.get("queue_version") != queue.get("queue_version"):
            raise ValueError("cannot replace repair queue with an incompatible version")
        # The caller passes the updated in-memory queue; enforce prefix-preserved
        # audit history rather than allowing a rewrite to erase previous events.
        old_events = old.get("events", [])
        if queue.get("events", [])[: len(old_events)] != old_events:
            raise ValueError("repair queue update would rewrite or remove prior events")
        for item_id, prior in old.get("items", {}).items():
            current = queue.get("items", {}).get(item_id)
            if current is None or current.get("history", [])[: len(prior.get("history", []))] != prior.get("history", []):
                raise ValueError(f"repair queue update would remove history for {item_id}")
            for key in ("item_id", "subject_type", "subject_id"):
                if current.get(key) != prior.get(key):
                    raise ValueError(f"repair queue update would rewrite {key} for {item_id}")
            mutable = ("revision", "source_refs", "missing_or_return_reason", "owner", "next_action")
            appended_updates = [event for event in current.get("history", [])[len(prior.get("history", [])):]
                                if event.get("event") == "item-updated"]
            for key in mutable:
                expected = prior.get(key)
                for event in appended_updates:
                    if key in event.get("changes", {}):
                        expected = event["changes"][key]
                if current.get(key) != expected:
                    raise ValueError(f"repair queue update changed {key} without matching item history for {item_id}")
    persisted = dict(queue)
    persisted["by_owner"] = {
        owner: [item["item_id"] for item in items]
        for owner, items in owner_grouped_view(queue).items()
    }
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(persisted, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def record_evidence_validation(queue: dict, *, item_id: str, supported: bool,
                               source_refs: list[str], run_id: str, batch_id: str) -> None:
    """Record a local evidence recheck, not a fabricated human response."""
    item = queue['items'][item_id]
    status = 'resolved' if supported else 'open'
    if supported and not source_refs:
        raise ValueError('Evidence-supported resolution requires retained references')
    if item['status'] == status:
        return
    event = dict(event='evidence-revalidated', item_id=item_id, previous_status=item['status'],
                 status=status, source_refs=list(dict.fromkeys(source_refs)), run_id=run_id,
                 batch_id=batch_id, origin='local-evidence-check; no human response created')
    item['history'].append(dict(event))
    queue['events'].append(event)
    item['status'] = status

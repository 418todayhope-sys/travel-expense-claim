"""Deterministic claim summary CSV and owner-grouped local repair queue."""

from __future__ import annotations

import csv
import hashlib
import re
import json
import os
import tempfile
from datetime import datetime
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


def verify_response_evidence(item: dict, outcome: dict, response_id: str,
                             evidence_directory: Path | None) -> dict:
    """Verify a retained, explicit sufficiency assessment, never infer one.

    Retain supplemental replies under <run>/response-evidence/ with a separate
    sources.json manifest (files: source_id, path, sha256, status, missing_scope,
    observed_at, version). This does not append to the five native sources.
    Assessment references
    address retained JSON records with JSON pointers. Supporting references can
    also address native parsed rows/pages bound to that exact manifest. A caller
    must retain a supplied assessment with item/subject/revision, response_id,
    sufficient=true, reason, provenance and evidence_refs; raw receipts or an
    importer-provided `supported` label alone do not establish sufficiency.
    This supplemental evidence contract never changes native acquisition status.
    """
    if evidence_directory is None:
        raise ValueError("retained response evidence directory is required")
    root = Path(evidence_directory).resolve()
    manifest_bytes = (root / "sources.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ValueError("response manifest must contain a files array")
    if not all(isinstance(row, dict) for row in manifest["files"]):
        raise ValueError("response manifest source entries must be objects")

    def resolve(ref):
        if not isinstance(ref, str):
            raise ValueError("response source reference must be text")
        sid_hash, locator = ref.split("#", 1)
        sid, digest = sid_hash.split("@", 1)
        if not sid or re.fullmatch(r"[0-9a-f]{64}", digest) is None or not locator:
            raise ValueError("malformed response source reference")
        rows = [r for r in manifest["files"] if r.get("source_id") == sid]
        if len(rows) != 1:
            raise ValueError("response source is missing or ambiguous")
        row = rows[0]
        if (row.get("status") != "read" or row.get("sha256") != digest
                or row.get("missing_scope") != [] or not row.get("observed_at")
                or not isinstance(row.get("version"), str) or not row["version"].strip()
                or row.get("error") is not None):
            raise ValueError("response source is unobserved, incomplete or mismatched")
        observed = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
        if observed.utcoffset() is None:
            raise ValueError("response observation must include a timezone")
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("response source escapes retained directory")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("response source bytes do not match hash")
        if path.suffix == ".json" and locator.startswith("/"):
            value = json.loads(data)
            for component in locator[1:].split("/"):
                if re.search(r"~(?![01])", component):
                    raise ValueError("invalid response JSON pointer escape")
                key = component.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    if not key.isdecimal() or str(int(key)) != key:
                        raise ValueError("invalid response array pointer")
                    value = value[int(key)]
                else:
                    value = value[key]
            return value
        parsed = json.loads((root / "parsed-records.json").read_bytes())
        if parsed.get("source_manifest") != {
                "path": "sources.json", "sha256": hashlib.sha256(manifest_bytes).hexdigest()}:
            raise ValueError("response parsed evidence has a different manifest")

        def find(value):
            if isinstance(value, dict):
                if (value.get("source_id"), value.get("source_sha256"), value.get("locator")) == (sid, digest, locator):
                    return True
                return any(find(v) for v in value.values())
            return isinstance(value, list) and any(find(v) for v in value)
        if not find(parsed):
            raise ValueError("response locator is not retained")
        return None

    assessment = resolve(outcome.get("assessment_ref", ""))
    if not isinstance(assessment, dict):
        raise ValueError("response requires an explicit retained sufficiency assessment")
    for field in ("item_id", "subject_type", "subject_id", "revision"):
        if type(assessment.get(field)) is not type(item[field]) or assessment[field] != item[field]:
            raise ValueError(f"response assessment does not match repair {field}")
    refs = list(dict.fromkeys(outcome.get("source_refs", [])))
    if (assessment.get("response_id") != response_id or assessment.get("sufficient") is not True
            or not isinstance(assessment.get("reason"), str) or not assessment["reason"].strip()
            or not isinstance(assessment.get("provenance"), str) or not assessment["provenance"].strip()
            or not refs or assessment.get("evidence_refs") != refs):
        raise ValueError("response assessment does not establish matched evidence sufficiency")
    for ref in refs:
        resolve(ref)
    return assessment


def apply_partial_response(
    queue: dict,
    *,
    response_id: str,
    item_outcomes: dict[str, dict],
    run_id: str,
    batch_id: str,
    evidence_directory: Path | None = None,
) -> None:
    """Record a supplied response against explicitly matched repair item IDs.

    Only a verified, item-specific retained sufficiency assessment resolves an
    item. Unsupported deliveries are held in history. Unmentioned items and
    previously valid resolutions are untouched; material updates reopen items.
    """
    allowed = {"supported", "insufficient", "conflicting", "unanswered"}
    if not response_id:
        raise ValueError("response_id is required")
    if not isinstance(item_outcomes, dict):
        raise ValueError("item_outcomes must map repair item IDs to outcomes")
    planned = []
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
                and prior_event.get("assessment_ref") == outcome.get("assessment_ref")
            )
            if same:
                planned.append((item_id, item, kind, normalized_refs, prior_event, None))
                continue
            raise ValueError(f"conflicting replay for repair response {response_id}/{item_id}")
        admission_error = None
        if kind == "supported":
            try:
                verify_response_evidence(item, outcome, response_id, evidence_directory)
            except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
                admission_error = f"Response evidence held: {exc}"
        planned.append((item_id, item, kind, normalized_refs, None, admission_error))

    # Mutate only after every item in this partial response passed validation.
    for item_id, item, kind, normalized_refs, prior_event, admission_error in planned:
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
            "subject_type": item["subject_type"], "subject_id": item["subject_id"],
            "revision": item["revision"], "item_id": item_id,
            "assessment_ref": item_outcomes[item_id].get("assessment_ref"),
            "admission_status": "held" if admission_error else "accepted",
            "admission_reason": admission_error,
        }
        item["history"].append(prior)
        if kind == "supported" and admission_error is None and item["status"] != "superseded":
            item["response_id"] = response_id
            item["status"] = "resolved"
            item["resolution_source_refs"] = normalized_refs
        elif item["status"] not in {"resolved", "superseded"}:
            item["response_id"] = response_id
            item["status"] = "open"
        queue["events"].append({
            "event": "response-recorded",
            "item_id": item_id,
            "response_id": response_id,
            "outcome": kind,
            "note": prior["note"],
            "assessment_ref": prior["assessment_ref"],
            "admission_status": prior["admission_status"],
            "admission_reason": admission_error,
            "subject_type": item["subject_type"], "subject_id": item["subject_id"],
            "revision": item["revision"],
            "source_refs": normalized_refs,
            "run_id": run_id,
            "batch_id": batch_id,
            "status": item["status"],
        })


def validate_partial_response_journal(queue: dict, evidence_directory: Path) -> None:
    """Check per-item journal consistency and reverify admitted resolution proof.

    Historical assessments use their original subject revision. Held deliveries
    remain visible and do not supersede a previously admitted resolution.
    """
    seen = set()
    for event in queue["events"]:
        if event.get("event") != "response-recorded":
            continue
        key = (event["response_id"], event["item_id"])
        if key in seen:
            raise ValueError("duplicate response journal entry")
        seen.add(key)
        item = queue["items"][event["item_id"]]
        histories = [h for h in item["history"] if h.get("response_id") == event["response_id"]
                     and "outcome" in h]
        if len(histories) != 1:
            raise ValueError("response journal has no unique item history")
        history = histories[0]
        for field in ("response_id", "outcome", "note", "source_refs", "run_id", "batch_id",
                      "assessment_ref", "admission_status", "admission_reason",
                      "subject_type", "subject_id", "revision"):
            if event.get(field) != history.get(field):
                raise ValueError(f"response journal/history mismatch: {field}")
        if event.get("admission_status") not in {"accepted", "held"}:
            raise ValueError("response admission status is missing")
        if event["outcome"] == "supported" and event["admission_status"] == "accepted":
            historical_item = dict(item, revision=event["revision"],
                subject_type=event["subject_type"], subject_id=event["subject_id"])
            verify_response_evidence(historical_item, event, event["response_id"], evidence_directory)
    for item in queue["items"].values():
        for history in item["history"]:
            if "outcome" in history and "response_id" in history:
                if (history["response_id"], item["item_id"]) not in seen:
                    raise ValueError("item response history is missing from the journal")
        if item["status"] != "resolved" or not item.get("response_id"):
            continue
        events = [e for e in queue["events"] if e.get("event") == "response-recorded"
                  and e.get("item_id") == item["item_id"] and e.get("response_id") == item["response_id"]]
        if (len(events) != 1 or events[0].get("outcome") != "supported"
                or events[0].get("admission_status") != "accepted"
                or events[0].get("revision") != item["revision"]
                or events[0].get("source_refs") != item["resolution_source_refs"]):
            raise ValueError("resolved repair does not match its admitted current response")


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

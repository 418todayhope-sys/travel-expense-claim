"""Policy-neutral structural workflow primitives.

These helpers preserve submitted revisions and identify linked events. They do
not evaluate policy, recommend/record approval, calculate entitlement, or
declare any claim ready or reimbursed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


def row_values(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one parsed workbook row to its recorded cell values."""
    return {key: cell.get("value") for key, cell in record.get("values", {}).items()}


def _revision(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if number < 1 or float(value) != number:
        return None
    return number


def _source_ref(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("source_id", "source_sha256", "locator")}


def build_revision_history(parsed: dict[str, Any]) -> dict[str, Any]:
    """Build complete claim/trip/permit revision indexes with source refs.

    `current_revision` is only the greatest source-observed revision number.
    It is not a judgement that the record is complete, valid, or policy-ready.
    """
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "claim": defaultdict(list), "trip": defaultdict(list), "permit": defaultdict(list)
    }
    malformed = []
    for record in parsed["records"].get("claim_revisions", []):
        values = {field["label"].strip(): field["value"] for field in record.get("fields", [])}
        subject_id = values.get("Claim reference")
        revision = _revision(values.get("Revision"))
        if not subject_id or revision is None:
            malformed.append({"kind": "claim", "source_ref": _source_ref(record), "reason": "missing subject ID or positive revision"})
            continue
        groups["claim"][str(subject_id)].append({
            "subject_id": str(subject_id), "revision": revision,
            "trip_id": values.get("Trip reference"),
            "trip_revision": _revision(values.get("Trip revision")),
            "arrival_batch": values.get("Arrival batch"),
            "record": record, "source_ref": _source_ref(record),
        })
    for record in parsed["records"].get("trips", []):
        values = row_values(record)
        subject_id = values.get("Trip reference")
        revision = _revision(values.get("Trip revision"))
        if not subject_id or revision is None:
            malformed.append({"kind": "trip", "source_ref": _source_ref(record), "reason": "missing subject ID or positive revision"})
            continue
        groups["trip"][str(subject_id)].append({
            "subject_id": str(subject_id), "revision": revision,
            "permit_id": values.get("Permit reference"),
            "permit_revision": _revision(values.get("Permit revision")),
            "record": record, "source_ref": _source_ref(record),
        })
        permit_id = values.get("Permit reference")
        if permit_id is not None and permit_id != "":
            permit_revision = _revision(values.get("Permit revision"))
            if permit_revision is None:
                malformed.append({"kind": "permit", "source_ref": _source_ref(record), "reason": "permit reference has no positive permit revision"})
            else:
                groups["permit"][str(permit_id)].append({
                    "subject_id": str(permit_id), "revision": permit_revision,
                    "trip_id": str(subject_id), "trip_revision": revision,
                    "record": record, "source_ref": _source_ref(record),
                })

    result: dict[str, Any] = {"revision_semantics": "source-observed maximum only; no business readiness conclusion"}
    conflicts = []
    for kind, subjects in groups.items():
        indexed = {}
        for subject_id, revisions in subjects.items():
            revisions.sort(key=lambda item: (item["revision"], item["source_ref"].get("locator") or ""))
            seen: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for item in revisions:
                seen[item["revision"]].append(item)
            for rev, same in seen.items():
                if len(same) > 1:
                    # Repeated records can be source retransmissions. Retain
                    # every occurrence and surface it for later comparison.
                    conflicts.append({"kind": kind, "subject_id": subject_id, "revision": rev,
                                      "occurrences": [item["source_ref"] for item in same]})
            indexed[subject_id] = {
                "current_revision": max(item["revision"] for item in revisions),
                "revisions": revisions,
            }
        result[kind] = indexed
    result["issues"] = {"malformed_revision_records": malformed, "repeated_subject_revisions": conflicts}
    return result


def match_decisions_to_subjects(decisions: list[dict[str, Any]], history: dict[str, Any]) -> list[dict[str, Any]]:
    """Match review ledger identities and revisions without applying outcomes."""
    matches = []
    for record in decisions:
        values = row_values(record)
        decision_id = values.get("Decision reference")
        kind = values.get("Subject type")
        subject_id = values.get("Subject reference")
        revision = _revision(values.get("Revision"))
        target_kind = str(kind) if kind in {"claim", "trip", "permit"} else None
        target = history.get(target_kind, {}).get(str(subject_id)) if target_kind and subject_id else None
        if target is None:
            result = "unsupported_subject_type" if target_kind is None else "subject_not_found"
            source_refs = []
        elif revision is None:
            result = "invalid_revision"
            source_refs = []
        else:
            occurrences = [item for item in target["revisions"] if item["revision"] == revision]
            if not occurrences:
                result = "revision_not_found"
                source_refs = []
            else:
                result = "revision_match_current" if revision == target["current_revision"] else "revision_match_historical"
                source_refs = [item["source_ref"] for item in occurrences]
        matches.append({
            "decision_id": decision_id,
            "subject_type": kind,
            "subject_id": subject_id,
            "revision": revision,
            "observed_outcome": values.get("Outcome"),
            "structural_match": result,
            "matched_source_refs": source_refs,
            "decision_source_ref": _source_ref(record),
            "applied": False,
        })
    return matches


def _business_payload(record: dict[str, Any], id_field: str, ignore_fields: set[str]) -> dict[str, Any]:
    values = row_values(record)
    return {key: values[key] for key in sorted(values) if key != id_field and key not in ignore_fields}


def deduplicate_activity_records(
    records: list[dict[str, Any]], *, id_field: str, ignore_fields: tuple[str, ...] = ("Arrival batch",)
) -> dict[str, Any]:
    """Deduplicate immutable event IDs, ignoring only declared delivery fields.

    All source occurrences remain cited. A differing business payload for an
    existing ID is reported as a conflict and never replaces the first event.
    """
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_id = []
    for record in records:
        event_id = row_values(record).get(id_field)
        if not isinstance(event_id, str) or not event_id:
            missing_id.append({"source_ref": _source_ref(record), "reason": f"missing {id_field}"})
        else:
            by_id[event_id].append(record)
    admitted, duplicates, conflicts = [], [], []
    for event_id, occurrences in by_id.items():
        first = occurrences[0]
        first_payload = _business_payload(first, id_field, set(ignore_fields))
        disagree = [row for row in occurrences[1:]
                    if _business_payload(row, id_field, set(ignore_fields)) != first_payload]
        refs = [_source_ref(row) for row in occurrences]
        if disagree:
            conflicts.append({"event_id": event_id, "id_field": id_field,
                              "occurrences": refs,
                              "payloads": [first_payload] + [_business_payload(row, id_field, set(ignore_fields)) for row in disagree]})
            continue
        admitted.append(first)
        if len(occurrences) > 1:
            duplicates.append({"event_id": event_id, "id_field": id_field,
                               "source_occurrences": refs,
                               "delivery_batches": [row_values(row).get("Arrival batch") for row in occurrences]})
    return {"unique_events": admitted, "duplicates": duplicates, "conflicts": conflicts, "missing_ids": missing_id}


def reduce_cancellation_activities(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Track independent trip/permit cancellation requests and confirmations.

    Ordering uses supplied arrival batch then workbook row, never activity
    timestamps. A confirmed action is structural only; it does not settle any
    claim or Finance obligation.
    """
    dedup = deduplicate_activity_records(records, id_field="Cancellation activity reference")
    conflicting_ids = {issue["event_id"] for issue in dedup["conflicts"]}
    events = [record for record in dedup["unique_events"]
              if row_values(record).get("Cancellation activity reference") not in conflicting_ids]
    events.sort(key=lambda row: (
        _revision(row_values(row).get("Arrival batch")) or 0,
        row.get("row", 0),
    ))
    processes: dict[str, dict[str, Any]] = {}
    issues = list(dedup["conflicts"])
    id_lookup: dict[str, tuple[str, dict[str, Any]]] = {}
    for record in events:
        values = row_values(record)
        event_id = values.get("Cancellation activity reference")
        cancellation_id = values.get("Cancellation reference")
        action = values.get("Action")
        subject_type = values.get("Cancelled subject")
        if not cancellation_id or subject_type not in {"trip", "permit"}:
            issues.append({"event_id": event_id, "source_ref": _source_ref(record), "reason": "missing cancellation ID or unsupported target type"})
            continue
        target_id = values.get("Trip reference") if subject_type == "trip" else values.get("Permit reference")
        target_revision = _revision(values.get("Trip revision") if subject_type == "trip" else values.get("Permit revision"))
        target = {"subject_type": subject_type, "subject_id": target_id, "revision": target_revision}
        process = processes.setdefault(str(cancellation_id), {
            "cancellation_id": cancellation_id, "target": target, "state": "unseen",
            "activity_ids": [], "history": [], "next_action": "await request activity",
        })
        if process["target"] != target:
            issues.append({"cancellation_id": cancellation_id, "event_id": event_id,
                           "source_ref": _source_ref(record), "reason": "cancellation target identity/revision conflicts with prior activity"})
            continue
        if action == "requested":
            if process["state"] != "unseen":
                issues.append({"cancellation_id": cancellation_id, "event_id": event_id,
                               "source_ref": _source_ref(record), "reason": f"request is not valid after state {process['state']}"})
                continue
            process["state"] = "requested"
            process["next_action"] = "await a linked confirmation activity"
        elif action == "confirmed":
            initiation = values.get("Initiation activity reference")
            linked = id_lookup.get(str(initiation)) if initiation else None
            if process["state"] != "requested" or not linked or linked[0] != cancellation_id or row_values(linked[1]).get("Action") != "requested":
                issues.append({"cancellation_id": cancellation_id, "event_id": event_id,
                               "source_ref": _source_ref(record), "reason": "confirmation does not link to a prior request activity"})
                continue
            if not values.get("Effective time (UTC)"):
                process["state"] = "requested"
                process["next_action"] = "obtain the missing effective time or confirmation record"
                issues.append({"cancellation_id": cancellation_id, "event_id": event_id,
                               "source_ref": _source_ref(record), "reason": "confirmation has no effective time"})
                continue
            # Explicitly UTC columns give timezone context, but never a case clock.
            stamps = [row_values(linked[1]).get("Activity time (UTC)"),
                      values.get("Activity time (UTC)"), values.get("Effective time (UTC)")]
            try:
                times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in stamps]
                if times[1] < times[0] or times[2] < times[0]:
                    raise ValueError("confirmation precedes initiation")
            except (TypeError, ValueError, AttributeError):
                # Older structural-only inputs may omit all activity timestamps;
                # they remain structural observations, not verified authority.
                if any(stamps[:2]):
                    issues.append({"cancellation_id": cancellation_id, "event_id": event_id,
                                   "source_ref": _source_ref(record), "reason": "missing, invalid or inconsistent UTC cancellation chronology"})
                    continue
            process["state"] = "confirmed"
            process["next_action"] = None
        else:
            issues.append({"cancellation_id": cancellation_id, "event_id": event_id,
                           "source_ref": _source_ref(record), "reason": f"unsupported action {action!r}"})
            continue
        process["activity_ids"].append(event_id)
        process["history"].append({
            "event_id": event_id, "action": action,
            "arrival_batch": values.get("Arrival batch"),
            "effective_time": values.get("Effective time (UTC)"),
            "activity_time_utc": values.get("Activity time (UTC)"),
            "actor": values.get("Acting employee or supervisor"),
            "source_ref": _source_ref(record),
        })
        id_lookup[str(event_id)] = (str(cancellation_id), record)
    return {"processes": processes, "issues": issues,
            "duplicate_events": dedup["duplicates"], "conflicting_events": dedup["conflicts"],
            "finance_effects": [], "claim_effects": []}

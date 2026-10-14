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


def reduce_cancellation_activities(records: list[dict[str, Any]], **validation_context) -> dict[str, Any]:
    """Validate independent cancellation authority, retaining invalid deliveries."""
    from .cancellation import reduce_cancellations
    return reduce_cancellations(records, **validation_context)

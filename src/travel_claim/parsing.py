"""Loss-aware parsing of retained Project D source files.

Parsing here transcribes source material and adds locators. It does not decide
policy eligibility, entitlement, approval readiness, or payment completion.
Original retained files remain authoritative; extracted values always carry a
source ID and a page or workbook-cell locator.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from pypdf import PdfReader

from .sources import verify_source_manifest

OUTPUT_NAME = "parsed-records.json"
RECORD_SCHEMA = "travel-claim-parsed-records/1"


def _scalar(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _extract_labels(text: str) -> list[dict[str, str]]:
    """Keep every colon-labelled line verbatim as a field/value occurrence."""
    found = []
    for line_no, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^\s*([^:\n]+):\s?(.*)$", line)
        if match:
            found.append({"line": str(line_no), "label": match.group(1), "value": match.group(2)})
    return found


def _pdf_pages(path: Path, source_id: str, sha256: str) -> list[dict[str, Any]]:
    reader = PdfReader(path, strict=True)
    pages: list[dict[str, Any]] = []
    for page_no, page in enumerate(reader.pages, 1):
        text = (page.extract_text(extraction_mode="layout") or "") if "/Contents" in page else ""
        claim = re.search(r"^\s*Claim reference:\s*(.+)$", text, re.M)
        receipt_refs = re.findall(r"^\s*Receipt reference:\s*(.+)$", text, re.M)
        pages.append({
            "source_id": source_id,
            "source_sha256": sha256,
            "locator": f"PDF page {page_no}",
            "page": page_no,
            "record_types": (["claim_revision"] if claim else []) + (["receipt"] if receipt_refs else []),
            "claim_id": claim.group(1).strip() if claim else None,
            "receipt_ids": [item.strip() for item in receipt_refs],
            "fields": _extract_labels(text),
            "text": text,
        })
    return pages


def _workbook_sheets(path: Path, source_id: str, sha256: str) -> list[dict[str, Any]]:
    workbook = load_workbook(path, data_only=False, read_only=False)
    sheets: list[dict[str, Any]] = []
    for sheet in workbook.worksheets:
        rows = list(sheet.iter_rows())
        header_row = next((i for i, row in enumerate(rows) if any(cell.value is not None for cell in row)), None)
        if header_row is None:
            continue
        headers = [cell.value for cell in rows[header_row]]
        # Workbook tabs begin with a title, notes, and a blank row. The row
        # whose first cell names an ID/reference is the native table header.
        table_row = next((i for i, row in enumerate(rows)
                          if any(str(c.value).strip().lower() in {"employee id", "trip reference",
                             "transaction reference", "rate reference", "cap reference",
                             "ledger reference", "decision reference", "activity reference",
                             "cancellation activity reference"} for c in row if c.value is not None)), None)
        if table_row is None:
            table_row = header_row
        headers = [cell.value for cell in rows[table_row]]
        records: list[dict[str, Any]] = []
        for row_idx, row in enumerate(rows[table_row + 1:], table_row + 2):
            if not any(cell.value is not None for cell in row):
                continue
            values = {}
            for col_idx, cell in enumerate(row):
                if col_idx >= len(headers) or headers[col_idx] is None or cell.value is None:
                    continue
                header = str(headers[col_idx])
                values[header] = {
                    "value": _scalar(cell.value),
                    "source_text": str(cell.value),
                    "number_format": cell.number_format,
                    "data_type": cell.data_type,
                    "cell": cell.coordinate,
                }
            if values:
                first = next(iter(values.values()))
                # The complete row map, including exact sheet/row references,
                # is retained even when a workbook row carries multiple IDs.
                records.append({
                    "source_id": source_id,
                    "source_sha256": sha256,
                    "locator": f"tab {sheet.title!r}, row {row_idx}",
                    "row": row_idx,
                    "values": values,
                })
        sheets.append({
            "source_id": source_id,
            "source_sha256": sha256,
            "name": sheet.title,
            "header_row": table_row + 1,
            "headers": [str(h) if h is not None else None for h in headers],
            "records": records,
        })
    workbook.close()
    return sheets


def _receipt_records(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for page in pages:
        if "receipt" not in page["record_types"]:
            continue
        text = page["text"]
        starts = list(re.finditer(r"^\s*Receipt reference:\s*(.+)$", text, re.M))
        for i, match in enumerate(starts):
            end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
            block = text[match.start():end].strip()
            records.append({
                "source_id": page["source_id"],
                "source_sha256": page["source_sha256"],
                "locator": f"{page['locator']}, receipt {i + 1}",
                "receipt_id": match.group(1).strip(),
                "fields": _extract_labels(block),
                "text": block,
            })
    return records


def _value(row: dict[str, Any], key: str) -> Any:
    return row.get("values", {}).get(key, {}).get("value")


def parse_retained_run(run_dir: Path, *, output_path: Path | None = None) -> dict[str, Any]:
    """Parse all readable retained sources after verifying their manifest hashes."""
    errors = verify_source_manifest(run_dir)
    if errors:
        raise ValueError("Cannot parse unverified retained sources: " + "; ".join(errors))
    manifest = json.loads((run_dir / "sources.json").read_text(encoding="utf-8"))
    read = {row["source_id"]: row for row in manifest["files"] if row["status"] in {"read", "partial"}}
    parsed_sources: list[dict[str, Any]] = []
    transcription_issues = []
    pages: list[dict[str, Any]] = []
    sheets: list[dict[str, Any]] = []
    for source_id, meta in read.items():
        source_path = run_dir / meta["path"]
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != meta["sha256"]:
            raise ValueError(f"Retained-source hash changed during parse: {source_id}")
        try:
            if source_path.suffix.lower() == ".pdf":
                extracted = _pdf_pages(source_path, source_id, meta["sha256"])
                pages.extend(extracted)
                parsed_sources.append({"source_id": source_id, "kind": "pdf", "page_count": len(extracted)})
            elif source_path.suffix.lower() == ".xlsx":
                extracted_sheets = _workbook_sheets(source_path, source_id, meta["sha256"])
                sheets.extend(extracted_sheets)
                parsed_sources.append({"source_id": source_id, "kind": "xlsx", "sheet_count": len(extracted_sheets)})

            elif source_path.suffix.lower() == ".html":
                parsed_sources.append({"source_id": source_id, "kind": "html", "path": meta["path"],
                    "sha256": meta["sha256"], "status": meta["status"],
                    "interpretation": "Raw HTML retained verbatim; no policy rules inferred or normalized"})
        except Exception as exc:
            transcription_issues.append({"source_id": source_id, "source_sha256": meta["sha256"],
                "path": meta["path"], "error": f"{type(exc).__name__}: {exc}",
                "owner": "Travel Administration Lead", "next_action": "Obtain readable native content and retry in a new run"})

    # Preserve separate record categories. These are source transcriptions,
    # not assessments; trip and permit revisions remain independent fields.
    claim_revisions = [p for p in pages if p["claim_id"]]
    receipt_records = _receipt_records(pages)
    tab_by_name = {sheet["name"]: sheet for sheet in sheets}
    trips = tab_by_name.get("Trips", {}).get("records", [])
    decisions = tab_by_name.get("Review ledger", {}).get("records", [])
    finance = tab_by_name.get("Finance activity", {}).get("records", [])
    cancellations = tab_by_name.get("Travel cancellations", {}).get("records", [])
    permits = []
    for row in trips:
        permit_id = _value(row, "Permit reference")
        if permit_id:
            permits.append({
                "permit_id": permit_id,
                "trip_id": _value(row, "Trip reference"),
                "trip_revision": _value(row, "Trip revision"),
                "permit_revision": _value(row, "Permit revision"),
                "source_id": row["source_id"], "source_sha256": row["source_sha256"],
                "locator": row["locator"], "source_record": row["values"],
            })

    batch_ids: set[int] = set()
    invalid_batches = set()
    def explicit_batch(value, record):
        try:
            number = Decimal(str(value))
            if isinstance(value, bool) or not number.is_finite() or number < 1 or number != number.to_integral_value():
                raise ValueError("not a positive integer batch")
            return int(number)
        except (InvalidOperation, ValueError, TypeError):
            key = (record.get('source_id'), record.get('locator'), str(value))
            if key not in invalid_batches:
                invalid_batches.add(key)
                transcription_issues.append({'source_id': record.get('source_id'),
                    'source_sha256': record.get('source_sha256'), 'path': record.get('locator'),
                    'error': f"Arrival batch is not an explicit positive integer: {value!r}; raw value preserved",
                    'owner': 'Travel Administration Lead', 'next_action': 'Obtain the authoritative arrival membership without rounding or defaulting'})
            return None
    for record in claim_revisions + decisions + finance + cancellations:
        value = (next((f['value'] for f in record['fields'] if f['label'].strip().lower() == 'arrival batch'), None)
                 if 'fields' in record else _value(record, 'Arrival batch'))
        batch = explicit_batch(value, record)
        if batch is not None:
            batch_ids.add(batch)

    batch_contents: dict[str, dict[str, int]] = {str(batch): {} for batch in sorted(batch_ids)}
    def count_batch(category: str, records: list[dict[str, Any]], getter) -> None:
        for record in records:
            value = getter(record)
            batch = explicit_batch(value, record)
            if batch is None:
                continue
            key = str(batch)
            bucket = batch_contents.setdefault(key, {})
            bucket[category] = bucket.get(category, 0) + 1
    count_batch("claim_revisions", claim_revisions,
                lambda row: next((f["value"] for f in row["fields"] if f["label"].strip().lower() == "arrival batch"), None))
    count_batch("decisions", decisions, lambda row: _value(row, "Arrival batch"))
    count_batch("finance_events", finance, lambda row: _value(row, "Arrival batch"))
    count_batch("cancellation_activities", cancellations, lambda row: _value(row, "Arrival batch"))

    result = {
        "schema_version": RECORD_SCHEMA,
        "run_id": manifest["run_id"],
        "source_manifest": {"path": "sources.json", "sha256": hashlib.sha256((run_dir / "sources.json").read_bytes()).hexdigest()},
        "case_clock": manifest["case_clock"],
        "case_clock_state": "supplied" if manifest["case_clock"] else "not_in_accessible_retained_sources",
        "case_clock_issue": None if manifest["case_clock"] else {
            "reason": "No authoritative scenario case clock was supplied to this invocation; retrieval timestamps do not establish it.",
            "owner": "Exercise facilitator",
            "next_action": "Provide the authoritative scenario case clock before consuming any arrival batch.",
        },
        "arrival_batches": sorted(batch_ids),
        "arrival_batch_contents": batch_contents,
        "transcription_issues": transcription_issues,
        "missing_sources": [
            {"source_id": row["source_id"], "url": row["url"], "locator": row["locator"],
             "error": row["error"], "missing_scope": row.get("missing_scope", [])}
            for row in manifest["files"] if row["status"] != "read"
        ],
        "source_inventory": parsed_sources,
        "pdf_pages": pages,
        "workbook_sheets": sheets,
        "records": {
            "claim_revisions": claim_revisions,
            "trips": trips,
            "permits": permits,
            "receipts": receipt_records,
            "decisions": decisions,
            "finance_events": finance,
            "cancellation_activities": cancellations,
        },
        "processing_boundary": {
            "policy_dependent_conclusions": "unresolved",
            "reason": "Native reimbursement policy content is unavailable; parsed source values are not eligibility, entitlement, approval-readiness, or closure decisions.",
            "owner": "Travel Administration Lead / facilitator for source access",
            "next_action": "Provide an authorized native export or enable read access to the original Notion policy, then perform a fresh native read.",
        },
        "unresolved_issues": [
            {
                "record_id": "scenario-case-clock",
                "subject_type": "scenario",
                "subject_id": "arrival-batch-clock",
                "revision": None,
                "affected_scope": "all batch cutoff decisions and arrival-state consumption",
                "reason": "No authoritative scenario date, time and timezone was supplied for this run; obtain the explicit case clock before batch consumption.",
                "owner": "Exercise facilitator",
                "next_action": "Provide the authoritative scenario case clock before consuming any arrival batch.",
                "evidence_needed": "Explicit scenario date, time, and timezone from the facilitator or original task material.",
            },
            {
                "record_id": "reimbursement-policy-pol-2026-2",
                "subject_type": "policy",
                "subject_id": "POL-2026.2",
                "revision": None,
                "affected_scope": "eligibility, entitlement, approval readiness, reimbursement caps and final closure",
                "reason": "Native policy content is incomplete or unverified; consult this run's source observation.",
                "owner": "Travel Administration Lead / exercise facilitator",
                "next_action": "Provide an authorized native export or enable read access to the original Notion page, then perform a fresh native read.",
                "evidence_needed": "Complete policy content from the original Notion page or authorized native export, with observed URL/version and retained-content hash.",
            },
        ],
    }
    policy_meta = next(row for row in manifest["files"] if row["source_id"] == "policy-pol-2026-2")
    result['unresolved_issues'] = [issue for issue in result['unresolved_issues']
        if issue['record_id'] != 'scenario-case-clock' or not manifest['case_clock']]
    policy_issue = next(i for i in result['unresolved_issues'] if i['record_id'] == 'reimbursement-policy-pol-2026-2')
    policy_issue['reason'] = policy_meta.get('error') or 'Policy bytes retained; policy rule interpretation and completeness for decision processing remain unverified'
    policy_issue['source_observation'] = policy_meta
    result['processing_boundary']['reason'] = policy_issue['reason']
    result['unresolved_issues'].extend({
        'record_id': f"source-access:{row['source_id']}", 'subject_type': 'source', 'subject_id': row['source_id'],
        'revision': None, 'reason': row['error'], 'owner': 'Travel Administration Lead',
        'affected_scope': row['missing_scope'], 'next_action': 'Obtain complete native access and retry in a new run',
        'evidence_needed': row['missing_scope'],
    } for row in manifest['files'] if row['status'] != 'read' and row['source_id'] != 'policy-pol-2026-2')
    destination = output_path or (run_dir / OUTPUT_NAME)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite parsed output: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result

"""Deterministically normalize verified, retained Scope A business sources."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from pypdf import PdfReader, __version__ as PDF_VERSION

from acquisition.retain import TABS, sha256, verify_run, write_new

VERSION = "omega4-normalized/1"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DATE_HEADERS = {"Start date", "End date", "First commitment date", "Paid date", "Rate date",
                "Effective from", "Effective to"}
TIME_HEADERS = {"Decision time (UTC)", "Activity time (UTC)", "Effective time (UTC)"}
INTEGER_HEADERS = {"Revision", "Trip revision", "Permit revision", "Arrival batch"}
DECIMAL_HEADERS = {"Estimate (EUR)", "Gross amount", "EUR per currency unit", "Amount per unit",
                   "Allocation or commitment (EUR)", "Settled (EUR)", "Refunded (EUR)",
                   "Reviewed estimate (EUR)", "Amount (EUR)", "Obligation (EUR)"}
LIST_HEADERS = {"Review roles", "Source revisions", "Affected fields", "Expense references",
                "Budget record references", "Travel cancellation references"}
REQUIRED_HEADERS = {
    "People": ["Employee ID", "Payee ID", "Administration reviewer", "Budget owner", "Supervisor", "Director", "Finance officer"],
    "Trips": ["Trip reference", "Employee ID", "International", "Start date", "End date", "Trip revision"],
    "Merchant payments": ["Transaction reference", "Expense reference", "Employee ID", "Trip reference", "Currency", "Gross amount", "Paid date", "Payment status", "Receipt reference"],
    "FX": ["Rate reference", "Rate date", "Currency", "EUR per currency unit"],
    "Caps": ["Cap reference", "Destination", "Category", "Currency", "Effective from", "Effective to", "Amount per unit"],
    "Budget": ["Ledger reference", "Department", "Project", "Budget period", "Entry type"],
    "Review ledger": ["Decision reference", "Arrival batch", "Subject type", "Subject reference", "Revision", "Review roles", "Reviewer", "Outcome", "Reason", "Source revisions", "Decision time (UTC)"],
    "Review packets": ["Decision reference", "Employee ID", "Trip reference", "Policy revision", "Trip revision"],
    "Finance activity": ["Activity reference", "Arrival batch", "Activity type", "Request reference", "Claim reference", "Finance officer", "Payee ID", "Currency", "Activity time (UTC)"],
    "Travel cancellations": ["Cancellation activity reference", "Cancellation reference", "Action", "Cancelled subject", "Trip reference", "Trip revision", "Acting employee or supervisor", "Activity time (UTC)", "Arrival batch", "Business reason"],
}


def issue(issues, record_id, reason, field=None, severity="repair"):
    issues.append({"record_id": record_id, "field": field, "reason": reason, "severity": severity,
                   "owner": "source-data reviewer", "resolution_needed": "Inspect bound source; supply or clarify the fact without changing retained evidence."})


def decimal_text(value):
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError("Non-finite number")
    return format(number, "f")


def typed(value, kind, record_id, field, issues, epoch="1900"):
    if value == "":
        return None
    try:
        if kind == "integer":
            n = Decimal(value)
            if not n.is_finite() or n != n.to_integral_value():
                raise ValueError("Non-integral identifier/revision/batch")
            return int(n)
        if kind == "decimal":
            return decimal_text(value)
        if kind == "boolean":
            if value not in ("0", "1"):
                raise ValueError("Not an XLSX Boolean")
            return value == "1"
        if kind in ("date", "timestamp"):
            # ISO PDF dates remain dates; numeric workbook dates retain raw serials separately.
            if kind == "date" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return date.fromisoformat(value).isoformat()
            serial = Decimal(value)
            if not serial.is_finite() or serial < 0 or (epoch == "1900" and 60 <= serial < 61):
                raise ValueError("Invalid/ambiguous Excel date serial")
            origin = datetime(1904, 1, 1) if epoch == "1904" else datetime(1899, 12, 30)
            if epoch == "1900" and serial < 60:
                origin = datetime(1899, 12, 31)
            if kind == "date":
                if serial != serial.to_integral_value():
                    raise ValueError("Fractional day in date-only field")
                return (origin + timedelta(days=int(serial))).date().isoformat()
            seconds = serial * 86400
            whole = seconds.to_integral_value(rounding=ROUND_HALF_UP)
            if abs(seconds - whole) > Decimal("0.001"):
                raise ValueError("Timestamp has subsecond precision not represented by displayed seconds")
            return (origin + timedelta(seconds=int(whole))).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        if kind == "list":
            return value.splitlines()
        return value
    except (InvalidOperation, ValueError, OverflowError) as exc:
        issue(issues, record_id, f"Cannot normalize {kind}: {exc}; raw value retained", field)
        return None


def fields(text):
    """Read labelled fields with wrapped continuation; retain the full original text too."""
    result = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z /()-]+):\s*(.*)$", line)
        if match:
            current = match[1]
            if current in result:
                raise ValueError(f"Repeated labelled field {current}")
            result[current] = match[2]
        elif current and line.strip():
            result[current] += "\n" + line
    return result


def require(raw, keys, rid, issues):
    for key in keys:
        if raw.get(key, "") == "":
            issue(issues, rid, "Required structural field missing", key)


def parse_claim(text, ref, issues):
    rid = ref["source_id"] + f":page:{ref['page']}:claim"
    head, separator, rest = text.partition("Expense details\n")
    raw = fields(head)
    require(raw, ["Claim reference", "Revision", "Arrival batch", "Employee", "Trip reference",
                  "Trip revision", "Submitted date", "Status", "Related earlier claims"], rid, issues)
    claim = {"record_id": rid, "source": ref, "raw_text": text, "raw_fields": raw,
             "claim_id": raw.get("Claim reference"), "revision": typed(raw.get("Revision", ""), "integer", rid, "Revision", issues),
             "arrival_batch": typed(raw.get("Arrival batch", ""), "integer", rid, "Arrival batch", issues),
             "employee_id": raw.get("Employee"), "trip_id": raw.get("Trip reference"),
             "trip_revision": typed(raw.get("Trip revision", ""), "integer", rid, "Trip revision", issues),
             "submitted_date": typed(raw.get("Submitted date", ""), "date", rid, "Submitted date", issues),
             "status_observed": raw.get("Status"), "related_claim_ids": [], "expenses": [], "finance_exception": None}
    related = raw.get("Related earlier claims", "")
    if related and related != "None":
        claim["related_claim_ids"] = re.findall(r"\bC\d+\b", related)
        if not claim["related_claim_ids"]:
            issue(issues, rid, "Unrecognized earlier-claim reference", "Related earlier claims")
    if not separator:
        issue(issues, rid, "Missing expense section")
        return claim
    expense_text, has_exception, exception_text = rest.partition("Finance exception")
    lines = expense_text.strip().splitlines()
    headers = ["Line", "Expense reference", "Receipt reference", "First submitted date", "Original amount", "Currency"]
    if lines[:6] != headers:
        issue(issues, rid, "Unexpected expense table header; table retained unparsed")
        claim["unparsed_expense_text"] = expense_text
    else:
        values = lines[6:]
        if len(values) % 6:
            issue(issues, rid, "Expense cell count is not divisible by six; ambiguous rows retained unparsed")
            claim["unparsed_expense_text"] = expense_text
        else:
            for index in range(0, len(values), 6):
                line, cost, receipt, submitted, amount, currency = values[index:index+6]
                eid = rid + f":expense:{index//6+1}"
                expense = {"record_id": eid, "source": {**ref, "line_index": index//6+1},
                           "raw_values": dict(zip(headers, values[index:index+6])),
                           "line": typed(line, "integer", eid, "Line", issues), "expense_id": cost,
                           "receipt_id": receipt, "first_submitted_date": typed(submitted, "date", eid, "First submitted date", issues),
                           "original_amount": typed(amount, "decimal", eid, "Original amount", issues), "currency": currency}
                require(expense["raw_values"], headers, eid, issues)
                if not re.fullmatch(r"COST-[A-Za-z0-9-]+", cost) or not re.fullmatch(r"R-COST-[A-Za-z0-9-]+", receipt):
                    issue(issues, eid, "Unexpected expense/receipt identity syntax")
                claim["expenses"].append(expense)
    if not has_exception:
        issue(issues, rid, "Missing explicit Finance exception section")
    elif exception_text.strip() != ": Not supplied":
        ex = fields(exception_text)
        require(ex, ["Authorizing Finance officer", "Applies to claim", "Applies to revision", "Expense reference",
                     "Allowed original amount", "Covered issues", "Exception reason"], rid, issues)
        claim["finance_exception"] = {"raw_fields": ex,
            "actor": ex.get("Authorizing Finance officer"), "claim_id": ex.get("Applies to claim"),
            "revision": typed(ex.get("Applies to revision", ""), "integer", rid, "Exception revision", issues),
            "expense_id": ex.get("Expense reference"), "allowed_original_amount_observed": typed(ex.get("Allowed original amount", ""), "decimal", rid, "Allowed original amount", issues),
            "covered_issues_observed": ex.get("Covered issues"), "cancellation_id": ex.get("Travel cancellation reference")}
    return claim


def parse_pdfs(entries, issues):
    claims, receipts, pages, counts = [], [], [], {}
    for entry, body in entries:
        reader = PdfReader(io.BytesIO(body))
        before = len(claims) if entry["source_id"] != "receipts" else len(receipts)
        extracted = 0
        for number, page in enumerate(reader.pages, 1):
            ref = {"source_id": entry["source_id"], "sha256": entry["sha256"], "page": number}
            rid = ref["source_id"] + f":page:{number}"
            try:
                text = page.extract_text() or ""
                extracted += bool(text.strip())
                pages.append({"source": ref, "raw_text": text, "characters": len(text)})
                if not text.strip():
                    issue(issues, rid, "Page has no extractable text")
                elif entry["source_id"] != "receipts":
                    claims.append(parse_claim(text, ref, issues))
                else:
                    parts = re.split(r"(?m)(?=^Receipt reference:)", text)
                    if len(parts) < 2:
                        issue(issues, rid, "No receipt record boundary found")
                    for index, part in enumerate(parts[1:], 1):
                        raw = fields(part)
                        receipt_rid = rid + f":receipt:{index}"
                        require(raw, ["Receipt reference", "Expense reference", "Employee", "Trip reference", "Category",
                                      "Currency", "Gross amount", "Documented units", "Issued date"], receipt_rid, issues)
                        receipts.append({"record_id": receipt_rid, "source": {**ref, "receipt_index": index},
                            "raw_text": part, "raw_fields": raw, "receipt_id": raw.get("Receipt reference"),
                            "expense_id": raw.get("Expense reference"), "employee_id": raw.get("Employee"),
                            "trip_id": raw.get("Trip reference"), "category": raw.get("Category"), "currency": raw.get("Currency"),
                            "gross_amount": typed(raw.get("Gross amount", ""), "decimal", receipt_rid, "Gross amount", issues),
                            "units": typed(raw.get("Documented units", ""), "integer", receipt_rid, "Documented units", issues),
                            "issued_date": typed(raw.get("Issued date", ""), "date", receipt_rid, "Issued date", issues)})
            except (ValueError, KeyError) as exc:
                issue(issues, rid, f"Page parsing failure: {exc}; original bytes retained")
        after = len(claims) if entry["source_id"] != "receipts" else len(receipts)
        counts[entry["source_id"]] = {"pages": len(reader.pages), "pages_with_text": extracted,
                                       "records": after-before}
    return claims, receipts, pages, counts


def parse_workbook(entry, body, issues):
    tabs = {}
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [''.join(x.text or '' for x in si.findall('.//s:t', NS))
                       for si in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        props = book.find("s:workbookPr", NS)
        epoch = "1904" if props is not None and props.get("date1904") in ("1", "true") else "1900"
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        styles = archive.read("xl/styles.xml").decode("utf-8") if "xl/styles.xml" in archive.namelist() else None
        for sheet in book.findall("s:sheets/s:sheet", NS):
            name = sheet.get("name")
            target = rels[sheet.get("{" + REL + "}id")]
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            tree = ET.fromstring(archive.read(path))
            headers, rows, preamble = {}, [], []
            for row in tree.findall("s:sheetData/s:row", NS):
                rn = int(row.get("r"))
                rid = f"travel-registers:{name}:row:{rn}"
                cells = {}
                for cell in row.findall("s:c", NS):
                    address = cell.get("r")
                    col = re.sub(r"\d", "", address)
                    element = cell.find("s:v", NS)
                    raw = element.text if element is not None and element.text is not None else ""
                    ctype = cell.get("t", "n")
                    value = strings[int(raw)] if ctype == "s" and raw else raw
                    if ctype == "inlineStr":
                        value = ''.join(t.text or '' for t in cell.findall('.//s:t', NS))
                    formula = cell.find("s:f", NS)
                    cells[col] = {"cell": address, "type": ctype, "style": cell.get("s"),
                                  "raw_xml_value": raw, "value": value,
                                  "formula": formula.text if formula is not None else None}
                    if formula is not None:
                        issue(issues, rid, "Formula present: cached value retained, not recalculated", address)
                if not any(c["value"] or c["formula"] for c in cells.values()):
                    continue  # Formatting-only rows are not business records.
                if rn < 5:
                    preamble.append({"row": rn, "cells": cells})
                    continue
                if rn == 5:
                    headers = {col: c["value"] for col, c in cells.items() if c["value"]}
                    if len(set(headers.values())) != len(headers):
                        raise ValueError(f"Duplicate headers on {name}")
                    continue
                if not headers:
                    raise ValueError(f"Missing row-5 header on {name}")
                values = {}
                for col, header in headers.items():
                    cell = cells.get(col, {"value": "", "type": "n"})
                    kind = ("date" if header in DATE_HEADERS else "timestamp" if header in TIME_HEADERS
                            else "integer" if header in INTEGER_HEADERS else "decimal" if header in DECIMAL_HEADERS
                            else "list" if header in LIST_HEADERS else "boolean" if header == "International" else "text")
                    if cell["type"] == "e":
                        issue(issues, rid, "Excel error cell", header)
                    values[header] = typed(cell["value"], kind, rid, header, issues, epoch)
                extras = [col for col in cells if col not in headers and cells[col]["value"]]
                if extras:
                    issue(issues, rid, "Values outside named headers; raw cells retained")
                first_header = next(iter(headers.values()))
                if not values.get(first_header):
                    issue(issues, rid, "Primary row identifier missing", first_header)
                for required in REQUIRED_HEADERS.get(name, []):
                    if values.get(required) is None or values.get(required) == []:
                        issue(issues, rid, "Required structural workbook field missing or invalid", required)
                rows.append({"record_id": rid, "source": {"source_id": "travel-registers", "sha256": entry["sha256"],
                             "sheet": name, "row": rn}, "values": values, "raw_cells": cells})
            tabs[name] = {"headers": headers, "preamble": preamble, "rows": rows}
    if tuple(tabs) != TABS:
        raise ValueError("Workbook tab inventory mismatch")
    return tabs, {"date_system": epoch, "styles_xml": styles,
                  "timestamp_conversion": "UTC-labelled numeric cells rounded to displayed seconds only within 1ms; raw serial preserved"}


def repeated_deliveries(tabs, issues):
    result = []
    for name, id_header in [("Finance activity", "Activity reference"),
                            ("Travel cancellations", "Cancellation activity reference")]:
        groups = defaultdict(list)
        for row in tabs[name]["rows"]:
            groups[row["values"].get(id_header)].append(row)
        for event_id, rows in groups.items():
            payloads = []
            for row in rows:
                raw = {tabs[name]["headers"].get(col, col): cell["value"] for col, cell in row["raw_cells"].items()}
                payloads.append({key: raw.get(key, "") for key in tabs[name]["headers"].values() if key != "Arrival batch"})
            same = all(p == payloads[0] for p in payloads)
            result.append({"source_id": "travel-registers", "sheet": name, "event_id": event_id,
                           "delivery_record_ids": [r["record_id"] for r in rows], "delivery_count": len(rows),
                           "classification": "distinct_event" if len(rows) == 1 else "repeated_delivery" if same else "conflicting_delivery",
                           "payload_comparison": "decoded raw field values; only Arrival batch excluded; no admission/effects applied"})
            if not same:
                issue(issues, rows[0]["record_id"], "Conflicting event payloads; all deliveries retained")
    return result


def identity_checks(claims, receipts, tabs, issues):
    receipts_by_id = defaultdict(list)
    for r in receipts:
        receipts_by_id[r["receipt_id"]].append(r)
    payments = tabs["Merchant payments"]["rows"]
    finance = tabs["Finance activity"]["rows"]
    trips = tabs["Trips"]["rows"]
    employees = {r["values"]["Employee ID"] for r in tabs["People"]["rows"]}
    checks = []
    claim_keys = Counter((c["claim_id"], c["revision"]) for c in claims)
    for c in claims:
        rid = c["record_id"]
        if claim_keys[(c["claim_id"], c["revision"])] > 1:
            issue(issues, rid, "Repeated claim/revision; originals retained")
        if c["employee_id"] not in employees:
            issue(issues, rid, "Employee missing from People directory")
        trip_matches = [r["record_id"] for r in trips if r["values"].get("Trip reference") == c["trip_id"]
                        and r["values"].get("Trip revision") == c["trip_revision"]
                        and r["values"].get("Employee ID") == c["employee_id"]]
        if len(trip_matches) != 1:
            issue(issues, rid, "Trip/employee/exact-revision match missing or ambiguous")
        current_review_matches = [r["record_id"] for r in tabs["Review ledger"]["rows"]
                                  if r["values"].get("Subject type") == "claim"
                                  and r["values"].get("Subject reference") == c["claim_id"]
                                  and r["values"].get("Revision") == c["revision"]]
        if not current_review_matches:
            issue(issues, rid, "No review-ledger row for this exact claim/revision; no review validity inferred",
                  severity="observation")
        for e in c["expenses"]:
            receipt_candidates = receipts_by_id[e["receipt_id"]]
            mismatch = []
            for r in receipt_candidates:
                pairs = {"expense_id": (e["expense_id"], r["expense_id"]), "employee_id": (c["employee_id"], r["employee_id"]),
                         "trip_id": (c["trip_id"], r["trip_id"]), "currency": (e["currency"], r["currency"]),
                         "gross_amount": (e["original_amount"], r["gross_amount"])}
                mismatch.extend(k for k, (a, b) in pairs.items() if not equal_value(a, b, k == "gross_amount"))
            candidates = [r for r in payments if r["values"].get("Expense reference") == e["expense_id"]]
            exact = []
            for row in candidates:
                v = row["values"]
                if (v.get("Employee ID") == c["employee_id"] and v.get("Trip reference") == c["trip_id"]
                        and v.get("Receipt reference") == e["receipt_id"] and v.get("Currency") == e["currency"]
                        and equal_value(v.get("Gross amount"), e["original_amount"], True)):
                    exact.append(row)
            if len(receipt_candidates) != 1 or mismatch:
                issue(issues, e["record_id"], "Receipt identity missing/ambiguous/mismatched: " + ', '.join(sorted(set(mismatch))))
            if len(exact) != 1:
                issue(issues, e["record_id"], "Merchant-payment identity match missing or ambiguous")
            elif exact[0]["values"].get("Payment status") != "settled":
                issue(issues, e["record_id"], "Matching merchant payment is not reported settled; receipt does not prove payment")
            checks.append({"expense_record_id": e["record_id"], "claim_id": c["claim_id"], "claim_revision": c["revision"],
                           "expense_id": e["expense_id"], "trip_matches": trip_matches,
                           "review_exact_subject_revision_matches": current_review_matches,
                           "receipt_matches": [r["record_id"] for r in receipt_candidates], "receipt_mismatched_fields": sorted(set(mismatch)),
                           "merchant_candidates": [r["record_id"] for r in candidates],
                           "merchant_identity_matches": [r["record_id"] for r in exact],
                           "merchant_statuses_observed": [r["values"].get("Payment status") for r in exact],
                           "finance_claim_reference_matches": [r["record_id"] for r in finance if r["values"].get("Claim reference") == c["claim_id"]],
                           "finance_link_limit": "Claim-reference candidates only: no expense/revision attribution or payment admission inferred"})
    return checks


def equal_value(a, b, numeric=False):
    if a is None or b is None:
        return False
    return Decimal(a) == Decimal(b) if numeric else a == b


def build(run: Path):
    verify_run(run)  # Fail before parsing any source on corrupt identity/hash evidence.
    manifest_bytes = (run / "sources.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    by_id = {e["source_id"]: e for e in manifest["files"]}
    entries = []
    for source_id in ("initial-claims", "claim-updates", "receipts", "travel-registers"):
        e = by_id[source_id]
        if e["status"] != "read":
            raise ValueError(f"Required native business source unavailable: {source_id}")
        body = (run / e["path"]).read_bytes()
        if sha256(body) != e["sha256"]:
            raise ValueError("Source changed after initial verification")
        entries.append((e, body))
    issues = []
    claims, receipts, pages, counts = parse_pdfs(entries[:3], issues)
    tabs, workbook_meta = parse_workbook(*entries[3], issues)
    counts["travel-registers"] = {name: len(tab["rows"]) for name, tab in tabs.items()}
    events = repeated_deliveries(tabs, issues)
    checks = identity_checks(claims, receipts, tabs, issues)
    expense_groups = defaultdict(list)
    for c in claims:
        for e in c["expenses"]:
            expense_groups[e["expense_id"]].append({"claim_id": c["claim_id"], "revision": c["revision"],
                                                    "expense_record_id": e["record_id"]})
    # Visible structural limits, never fabricate revision links or missing native policy.
    limitations = ["Native policy remains unavailable; supplemental browser policy is not native access.",
                   "Finance rows have claim/request references but no explicit claim revision or expense ID; candidates are not attributed to current revisions.",
                   "PDF text extraction is not a visual-fidelity guarantee. Full page text and raw table/field values remain available.",
                   "No reimbursement eligibility, review validity, event admission, obligation calculation, Finance closure or final operations report is performed."]
    document = {"schema_version": VERSION, "acquisition_run_id": manifest["run_id"],
                "acquisition_manifest_sha256": sha256(manifest_bytes),
                "parser": {"version": "1", "pypdf": PDF_VERSION},
                "sources": [{"source_id": e["source_id"], "url": e["url"], "path": e["path"], "sha256": e["sha256"]} for e, _ in entries],
                "source_counts": counts, "claims": claims, "receipts": receipts,
                "pdf_pages": pages, "workbook": tabs, "workbook_metadata": workbook_meta,
                "event_delivery_groups": events, "cross_source_checks": checks}
    document["expense_identity_occurrences"] = dict(expense_groups)
    repair = {"schema_version": "omega4-parsing-report/1", "normalized_schema_version": VERSION,
              "source_counts": counts, "claim_records": len(claims), "expense_occurrences": sum(len(c["expenses"]) for c in claims),
              "receipt_records": len(receipts), "workbook_rows": sum(len(t["rows"]) for t in tabs.values()),
              "issues": issues, "issue_count": len(issues), "limitations": limitations,
              "repeated_events": [e for e in events if e["delivery_count"] > 1],
              "result": "parsed-with-repairs" if issues else "parsed"}
    return document, repair


def normalize(run: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"Refusing existing normalization output: {output}")
    doc, report = build(run)
    output.mkdir(parents=True, exist_ok=False)
    normalized = (json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode()
    report["normalized_records_sha256"] = sha256(normalized)
    write_new(output / 'records.v1.json', normalized)
    write_new(output / 'parsing-report.v1.json', (json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode())
    lines = ["# Parsing and repair report — normalization v1", "", f"Result: {report['result']}",
             f"Claims: {report['claim_records']}; expense occurrences: {report['expense_occurrences']}; receipts: {report['receipt_records']}; workbook rows: {report['workbook_rows']}.",
             "", "## Source counts", "", '```json', json.dumps(report['source_counts'], indent=2), '```',
             "", "## Missing fields, ambiguities and cross-source checks", ""]
    lines += [f"- {i['record_id']} ({i['field'] or 'record'}): {i['reason']}" for i in report['issues']] or ["No structural repairs identified."]
    lines += ["", "## Limitations", ""] + ['- ' + item for item in report['limitations']]
    lines += ["", "Repeated deliveries are preserved individually; see event_delivery_groups in records and repeated_events in the JSON report."]
    write_new(output / 'parsing-report.v1.md', ('\n'.join(lines) + '\n').encode())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = normalize(args.run, args.output)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Normalization failed: {exc}\n")
    print(json.dumps({k: report[k] for k in ('result', 'claim_records', 'expense_occurrences', 'receipt_records', 'workbook_rows', 'issue_count')}))
    return 2 if report['issues'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

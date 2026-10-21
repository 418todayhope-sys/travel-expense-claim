# Parsing and repair report — normalization v1

Result: parsed-with-repairs
Claims: 127; expense occurrences: 208; receipts: 203; workbook rows: 1188.

## Source counts

```json
{
  "initial-claims": {
    "pages": 120,
    "pages_with_text": 120,
    "records": 120
  },
  "claim-updates": {
    "pages": 7,
    "pages_with_text": 7,
    "records": 7
  },
  "receipts": {
    "pages": 102,
    "pages_with_text": 102,
    "records": 203
  },
  "travel-registers": {
    "People": 14,
    "Trips": 123,
    "Merchant payments": 201,
    "FX": 2,
    "Caps": 2,
    "Budget": 3,
    "Review ledger": 307,
    "Review packets": 307,
    "Finance activity": 220,
    "Travel cancellations": 9
  }
}
```

## Missing fields, ambiguities and cross-source checks

- initial-claims:page:8:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:8:claim:expense:1 (record): Merchant-payment identity match missing or ambiguous
- initial-claims:page:10:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:12:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:13:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:15:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:22:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:23:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:24:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:25:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:111:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:112:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:113:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:113:claim:expense:2 (record): Merchant-payment identity match missing or ambiguous
- initial-claims:page:115:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:116:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- initial-claims:page:117:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred
- claim-updates:page:4:claim (record): No review-ledger row for this exact claim/revision; no review validity inferred

## Limitations

- Native policy remains unavailable; supplemental browser policy is not native access.
- Finance rows have claim/request references but no explicit claim revision or expense ID; candidates are not attributed to current revisions.
- PDF text extraction is not a visual-fidelity guarantee. Full page text and raw table/field values remain available.
- No reimbursement eligibility, review validity, event admission, obligation calculation, Finance closure or final operations report is performed.

Repeated deliveries are preserved individually; see event_delivery_groups in records and repeated_events in the JSON report.

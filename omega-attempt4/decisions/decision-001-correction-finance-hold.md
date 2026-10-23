# Decision 001 — Correction and original-request Finance hold

Date: 2026-10-20  
Project: D, Omega Attempt 4  
Status: Decision A explicitly authorized by Max Gabel; implementation pending.

## Authorized implementation decision — Decision A

Corrected claims with unresolved original-request payments must be held pending explicit Finance resolution and current reviews, preserving all original request, cancellation, transfer, and refund history.

This is the user's implementation constraint, adopted before implementation. It is not a new Finance decision, payment authorization, or claim-closure finding. Replacement payment readiness must remain blocked while either original-request financial resolution or required current reviews are missing. Finance resolves the financial consequences; applicable human reviewers supply current decisions. The Skill may validate and record authorized scenario facts, but must not invent approvals, refunds, or resolution events.

## Source observations — policy and interview

- [October 20 POL-2026.2 browser copy](../user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.txt), lines 22–26: reject stale authorization, invalidate dependent approvals after material corrections, retain history, hold replacements after dispatch, preserve stable obligation identity, and require explicit Finance resolution before applicable financial closure. Lines 29–31 distinguish cancelled travel bases from reassigned trips and require continued observation of original requests, including late transfers.
- Policy SHA-256: `04d8121a91986dc0839094b5e7f574c44f6261c60c1c3ba9aeeee1c279ee5993`.
- [Separate policy provenance](../user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.provenance.json): user-confirmed live-browser copying on October 20, 2026; source version POL-2026.2. This is a browser-visible copy, not native automated access or independently verified Notion completeness. Exact browser retrieval time is unknown.
- [October 20 interview](<../interviews/project-d-travel-expense-claim-20261020-1419(1).md>), lines 414–438: repeat dependent reviews even when amounts do not change. Line 841: preserve old-version Finance events, hold payment, and obtain Finance clarification of the replaced request/current payment basis. Lines 849–865: corrections invalidate dependent prior approvals and rebuild readiness. Line 294: closure requires current approvals, matching entitlement/net payments, and required Finance resolutions.
- Interview SHA-256: `c308181fc8b79ea07f57172b196513d8494b98121de02b46640dd39619539d9f`.

## Source observations — verified C18 lineage

These observations come from the preceding read-only fresh-source audit in the real coding conversation. PDF/workbook responses were inspected in memory, not retained as a sealed run. Source locators and response hashes identify the observations; this record does not substitute for future retained source evidence or full event-admission validation.

| Source locator | Observed fact |
| --- | --- |
| [Initial claims PDF](https://drive.google.com/file/d/13sRj6s_kMeP1hsYGstWWmfkb6SCN1YOS/view), page 18 | C18 revision 1, batch 1, EMP-01, T18/trip revision 1, COST-18, R-COST-18, EUR 100.00. |
| [Updates PDF](https://drive.google.com/file/d/16829RwrGrMCK9oq5TnWuytFewGk_8xQP/view), page 4 | C18 revision 2, batch 3, EMP-01, T18B/trip revision 1, COST-18B, R-COST-18B, EUR 100.00; reassignment while cancellation awaits Finance. |
| [Receipts PDF](https://drive.google.com/file/d/1Ynn1VLH-faRIy91xy95rOWwCBhy5mjjM/view), pages 9 and 13 | Separate receipts match the original and replacement expense identities, employee, trip, EUR currency, and EUR 100.00 gross amounts. Receipt presence alone is not payment proof. |
| [Travel registers](https://docs.google.com/spreadsheets/d/1338nvKD6rgAdLgGRhYCMMlQyDNLK0sE8pvFWrZAaaxg/edit), Merchant payments rows 22 and 30 | M-COST-18 and M-COST-18B separately match those expense/receipt identities and each report settled employee payment of EUR 100.00. |
| Travel registers, Finance activity rows 43 and 19–21 | REQ-C18 has F-C18-accepted (batch 1, obligation EUR 100.00), F-C18-1 cancellation_requested (batch 2), F-C18-2 cancelled (batch 3), then F-C18-3 settled EUR 100.00 (batch 4). Rows identify FIN-01, EMP-01 payee, and EUR. |
| Travel registers, Travel cancellations rows 10–11 | TC018-requested and TC018-confirmed target T18/revision 1, initiated by EMP-01 and confirmed by SUP-01. They do not target T18B. |
| Travel registers, Review ledger/Review packets rows 47–49 | C18 revision 1 has administration, budget-owner, and supervisor approvals bound to T18/COST-18. No C18 revision 2 claim reviews were found in the inspected ledger. |

No corresponding C18 refund, explicit financial resolution, or replacement request was observed. Finance activity has no explicit claim-revision or expense column; the late transfer retains its original REQ-C18 identity and cannot automatically establish payment for COST-18B. Missing observations must not be manufactured as completed work.

Fresh response SHA-256 identifiers from that audit:

```text
Initial PDF: b42a28754b1877363e1a25ed4fa1f3865915f44ec9995f7ed15fc9b6eefb08b7
Updates PDF: 03c15787d18e2928457cd0164b573dc03a3baade0ed26a391ba79c73a568da3b
Receipts PDF: 4c3dc47f187ccc5cdd0112e18afaadd3b6363bbb4d96793205ef8f3d4c06fcc8
Workbook, initial lineage inspection: 8d95a670c97fd54e322b5351abf5e3c78758e9af9231de5fb04d9975e9182a50
Workbook, focused Finance/review inspection: 13eb6e367d9fbcf26304bcf36c24ed321c5500672f7528f30b5ce74ece96f80b
```

Workbook export byte variation was not explained; these are distinct observations, not interchangeable byte bindings.

## Measurable acceptance criteria — not yet executed

1. **Late original-request settlement remains visible.** After batches 1–4, retain F-C18-3 exactly once with REQ-C18, EUR 100.00 (10,000 cents), payee EMP-01, and its source/batch references. Prior cancellation must not suppress the transfer or relabel it as a replacement payment. Preserve acceptance, cancellation-request, cancellation-confirmation, and any subsequently supplied refund history.
2. **Replacement payment readiness stays blocked.** C18/r2 must not become ready or produce a dispatch-ready replacement while original-request financial consequences remain unresolved or required current reviews are missing. The report/queue must identify the blocking fact, responsible Finance/reviewer owner, and evidence needed to resume. TC018 must not cancel the different T18B travel basis.
3. **Current reviews cannot be substituted by stale approvals.** C18/r1 approvals must remain historical and satisfy zero required review positions for C18/r2. Required r2 reviews must validate subject, revision, actor/role, and current evidence; an unchanged EUR 100.00 amount must not bypass revalidation.
4. **Finance resolution is required before financial closure.** Without an explicit authorized Finance resolution of the affected original-request consequences and valid current reviews, the affected work must not be declared financially closed. Cancellation status alone, equal amounts, or a hypothetical refund must not satisfy this gate. Any eventual closure must also satisfy all other applicable policy conditions.
5. **Replay must not duplicate transfers.** Replaying unchanged batches must preserve the admitted transfer-ID set, request/obligation identity, and monetary totals: F-C18-3 occurs once and contributes 10,000 cents once, not 20,000. Conflicting redelivery must create an owned hold without erasing previously admitted money. Only an actual admitted linked refund may reduce net paid.

## Validation and remaining scope

Full closure validation is not yet complete. Acceptance criteria are authorized requirements, not passing test results. No code, run snapshots, event-admission implementation, or closure decision is created by this record. Current C18/r2 reviews and Finance resolution remain evidence to obtain from authorized scenario inputs; no real request is sent. This decision does not impose an extra resolution event on unrelated pre-acceptance cancellation cases where policy does not require one.

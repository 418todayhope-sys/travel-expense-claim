# Operator handoff — omega4-attempt002-ordinary-closure-operator-v3

Mode: offline retained-source replay. No fresh acquisition, financial closure, external request or submission is asserted.

Final batch: 004; 121 current claims; 4 supported ordinary closure(s) within retained evidence. All other claims remain held.
Supported expense eligibility, supplied review replies, admitted request-level money and actual closure are separate facts.
Business dispositions are retained independently: withdrawal/rejection does not authorize payment, clear repairs, or establish financial closure.
Selected supported closures have known paid/balance money; all other unknown paid/balance amounts remain blank in CSV. Their snapshot zero is an incomplete subtotal, not proof of zero payment.
Finance has no revision/cost columns: original requests are fully retained in request_facts; schema requests stays empty rather than inventing a required revision.

## Retained evidence and replay

See [sources.json](sources.json), [original acquisition manifest](acquisition-manifest.original.json) and [sealed manifest](operator-manifest.v1.json).
Native policy remains unavailable. The October 20 browser copy is supplemental, with its provenance preserved; semantic source completeness is unverified.
The four snapshots bind their predecessor and derived replay source manifest. No historical execution times were invented.

| Batch | Claims | Finance events | Settled cents | Refund cents | Net cents | Open repairs |
|---|---:|---:|---:|---:|---:|---:|
| [001](batches/001.json) | 120 | 100 | 0 | 0 | 0 | 886 |
| [002](batches/002.json) | 120 | 200 | 1153915 | 0 | 1153915 | 692 |
| [003](batches/003.json) | 121 | 210 | 1164415 | 1000 | 1163415 | 698 |
| [004](batches/004.json) | 121 | 219 | 1206415 | 3000 | 1203415 | 683 |

Final request ledger: 104 original request facts; admitted settlements 1206415 cents, linked refunds 3000 cents, net 1203415 cents.
These totals are not revision-attributed employee paid totals and do not authorize or close claims.

## Claims and owners

| Claim/revision | Eligibility | Review evidence | Gross EUR cents | Policy calculation cents | Owner | Snapshot issues |
|---|---|---|---:|---:|---|---|
| C01/r1 | supported | supported | 10000 | 10000 | None | 0 |
| C02/r1 | supported | unresolved | 54000 | 54000 | ADMIN-01 | 4 |
| C03/r1 | supported | unresolved | 20000 | 20000 | ADMIN-01 | 4 |
| C04/r1 | supported | supported | 10000 | 10000 | None | 0 |
| C05/r1 | supported | supported | 100000 | 100000 | None | 0 |
| C06/r1 | supported | supported | 100001 | 100001 | None | 0 |
| C07/r1 | supported | unresolved | 36000 | 30000 | ADMIN-01 | 4 |
| C08/r1 | unresolved | unresolved | 12000 |  | EMP-01 | 12 |
| C10/r1 | blocked | unresolved | 9000 | 9000 | ADMIN-01 | 10 |
| C11/r1 | supported | unresolved | 6000 | 6000 | ADMIN-01 | 4 |
| C13/r1 | supported | unresolved | 5000 | 5000 | ADMIN-01 | 8 |
| C14/r1 | supported | blocked | 4000 | 4000 | FIN-01 | 7 |
| C15/r1 | blocked | unresolved | 3000 | 0 | LEAD-01 | 10 |
| C16/r1 | supported | unresolved | 10000 | 10000 | FIN-01 | 4 |
| C17/r1 | supported | unresolved | 10000 | 10000 | Facilitator | 4 |
| C20/r1 | supported | unresolved | 10000 | 10000 | FIN-01 | 4 |
| C21/r1 | supported | blocked | 8000 | 8000 | SUP-01 | 7 |
| C22/r1 | unresolved | unresolved |  |  | FIN-01 | 10 |
| C23/r1 | unresolved | unresolved | 17000 |  | ADMIN-01 | 10 |
| C25/r1 | blocked | unresolved | 10000 | 10000 | LEAD-01 | 10 |
| C26/r1 | supported | unresolved | 10000 | 10000 | ADMIN-01 | 8 |
| C27/r1 | supported | unresolved | 3500 | 3500 | Facilitator | 4 |
| C28/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 4 |
| C29/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 4 |
| C30/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 4 |
| C31/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 4 |
| C32/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 4 |
| C33/r1 | supported | unresolved | 3500 | 3500 | Facilitator | 4 |
| C34/r1 | supported | unresolved | 4500 | 4500 | FIN-01 | 4 |
| C35/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 4 |
| C36/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 4 |
| C37/r1 | supported | unresolved | 7500 | 7500 | Facilitator | 4 |
| C38/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 4 |
| C39/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 4 |
| C40/r1 | supported | unresolved | 4500 | 4500 | Facilitator | 4 |
| C41/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 4 |
| C42/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 4 |
| C43/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 4 |
| C44/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 4 |
| C45/r1 | supported | unresolved | 3500 | 3500 | FIN-01 | 4 |
| C46/r1 | supported | unresolved | 4500 | 4500 | Facilitator | 4 |
| C47/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 4 |
| C48/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 4 |
| C49/r1 | supported | unresolved | 7500 | 7500 | FIN-01 | 4 |
| C50/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 4 |
| C51/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 4 |
| C52/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 4 |
| C53/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 4 |
| C54/r1 | supported | unresolved | 6500 | 6500 | Facilitator | 4 |
| C55/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 4 |
| C56/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 4 |
| C57/r1 | supported | unresolved | 3500 | 3500 | Facilitator | 4 |
| C58/r1 | supported | unresolved | 4500 | 4500 | FIN-01 | 4 |
| C59/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 4 |
| C60/r1 | supported | unresolved | 6500 | 6500 | Facilitator | 4 |
| C61/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 4 |
| C62/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 4 |
| C63/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 4 |
| C64/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 4 |
| C65/r1 | supported | unresolved | 5500 | 5500 | Facilitator | 4 |
| C66/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 4 |
| C67/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 4 |
| C68/r1 | supported | unresolved | 8500 | 8500 | Facilitator | 4 |
| C69/r1 | supported | unresolved | 3500 | 3500 | Facilitator | 4 |
| C70/r1 | supported | unresolved | 4500 | 4500 | FIN-01 | 4 |
| C71/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 4 |
| C72/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 4 |
| C73/r1 | supported | unresolved | 7500 | 7500 | Facilitator | 4 |
| C74/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 4 |
| C75/r1 | supported | unresolved | 3500 | 3500 | Facilitator | 4 |
| C76/r1 | supported | unresolved | 4500 | 4500 | FIN-01 | 4 |
| C77/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 4 |
| C78/r1 | supported | unresolved | 6500 | 6500 | Facilitator | 4 |
| C79/r1 | supported | unresolved | 7500 | 7500 | FIN-01 | 4 |
| C80/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 4 |
| C81/r1 | supported | unresolved | 3500 | 3500 | FIN-01 | 4 |
| C82/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 4 |
| C83/r1 | supported | unresolved | 5500 | 5500 | Facilitator | 4 |
| C84/r1 | supported | unresolved | 6500 | 6500 | Facilitator | 4 |
| C85/r1 | supported | unresolved | 7500 | 7500 | Facilitator | 4 |
| C86/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 4 |
| C87/r1 | supported | unresolved | 3500 | 3500 | FIN-01 | 4 |
| C88/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 4 |
| C89/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 4 |
| C90/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 4 |
| C91/r1 | supported | unresolved | 7500 | 7500 | FIN-01 | 4 |
| C92/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 4 |
| C93/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 4 |
| C94/r1 | supported | unresolved | 4500 | 4500 | Facilitator | 4 |
| C95/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 4 |
| C96/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 4 |
| C97/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 4 |
| C98/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 4 |
| C99/r1 | supported | unresolved | 99999 | 99999 | FIN-01 | 4 |
| C100/r1 | supported | unresolved | 100000 | 100000 | FIN-01 | 4 |
| C101/r1 | supported | unresolved | 100001 | 100001 | ADMIN-01 | 4 |
| C102/r1 | supported | unresolved | 14999 | 14999 | ADMIN-01 | 4 |
| C103/r1 | supported | unresolved | 15000 | 15000 | ADMIN-01 | 4 |
| C104/r1 | supported | unresolved | 15001 | 15000 | FIN-01 | 4 |
| C105/r1 | supported | unresolved | 3999 | 3999 | FIN-01 | 4 |
| C106/r1 | supported | unresolved | 4000 | 4000 | ADMIN-01 | 4 |
| C107/r1 | supported | unresolved | 4001 | 4000 | Facilitator | 4 |
| C108/r1 | supported | unresolved | 208 | 208 | ADMIN-01 | 4 |
| C109/r1 | supported | unresolved | 208 | 208 | ADMIN-01 | 4 |
| C110/r1 | supported | unresolved | 2500 | 2500 | ADMIN-01 | 4 |
| C111/r1 | supported | unresolved | 2500 | 2500 | FIN-01 | 4 |
| C112/r1 | blocked | unresolved | 2500 | 2500 | ADMIN-01 | 10 |
| C113/r1 | unresolved | unresolved | 2500 | 2500 | ADMIN-01 | 9 |
| C114/r1 | unresolved | unresolved | 3500 |  | EMP-03 | 13 |
| C115/r1 | blocked | unresolved | 2500 | 1500 | FIN-01 | 6 |
| C116/r1 | unresolved | unresolved |  |  | Facilitator | 11 |
| C117/r1 | unresolved | unresolved | 5000 |  | EMP-03 | 10 |
| C118/r1 | blocked | unresolved | 2500 | 0 | LEAD-01 | 11 |
| C119/r1 | supported | unresolved | 100001 | 100001 | ADMIN-01 | 5 |
| C120/r1 | supported | unresolved | 7500 | 7500 | Facilitator | 4 |
| C09/r2 | supported | unresolved | 8000 | 8000 | ADMIN-01 | 4 |
| C24/r1 | supported | unresolved | 25000 | 25000 | Facilitator | 5 |
| C18/r2 | supported | unresolved | 10000 | 10000 | FIN-01 | 11 |
| C12/r2 | supported | unresolved | 7000 | 7000 | Facilitator | 4 |
| C121/r2 | supported | unresolved | 3000 | 2000 | ADMIN-01 | 4 |
| C19/r3 | supported | unresolved | 10000 | 8000 | FIN-01 | 5 |

## Explicitly selected ordinary closure checks

This is a retained-evidence conclusion, not an external completeness certificate, a new approval, or an instruction to pay again. Package-wide unknowns remain in the repair queue. Unselected claims retain their existing financial holds.
- C01/r1: closed-reimbursed; reviewed/accepted/net 10000 cents; balance 0. Request REQ-C01; acceptance F-C01-accepted; settlement F-C01-1. Evidence: initial-claims:page:1:claim, initial-claims:page:1:claim:expense:1, interview:ordinary_entitlement, policy:finance_admission, policy:finance_reconciliation, receipts:page:1:receipt:1, travel-registers:Finance activity:row:31, travel-registers:Finance activity:row:33, travel-registers:Finance activity:row:6, travel-registers:Merchant payments:row:6, travel-registers:People:row:6, travel-registers:Review ledger:row:6, travel-registers:Review ledger:row:7, travel-registers:Review ledger:row:8, travel-registers:Review packets:row:6, travel-registers:Review packets:row:7, travel-registers:Review packets:row:8, travel-registers:Trips:row:6.
- C04/r1: closed-reimbursed; reviewed/accepted/net 10000 cents; balance 0. Request REQ-C04; acceptance F-C04-accepted; settlement F-C04-1. Evidence: initial-claims:page:4:claim, initial-claims:page:4:claim:expense:1, interview:ordinary_entitlement, policy:finance_admission, policy:finance_reconciliation, receipts:page:2:receipt:2, travel-registers:Finance activity:row:36, travel-registers:Finance activity:row:9, travel-registers:Merchant payments:row:9, travel-registers:People:row:7, travel-registers:Review ledger:row:19, travel-registers:Review ledger:row:20, travel-registers:Review packets:row:19, travel-registers:Review packets:row:20, travel-registers:Trips:row:9.
- C05/r1: closed-reimbursed; reviewed/accepted/net 100000 cents; balance 0. Request REQ-C05; acceptance F-C05-accepted; settlement F-C05-1. Evidence: initial-claims:page:5:claim, initial-claims:page:5:claim:expense:1, interview:ordinary_entitlement, policy:finance_admission, policy:finance_reconciliation, receipts:page:3:receipt:1, travel-registers:Finance activity:row:10, travel-registers:Finance activity:row:37, travel-registers:Merchant payments:row:10, travel-registers:People:row:6, travel-registers:Review ledger:row:21, travel-registers:Review ledger:row:22, travel-registers:Review ledger:row:23, travel-registers:Review packets:row:21, travel-registers:Review packets:row:22, travel-registers:Review packets:row:23, travel-registers:Trips:row:10.
- C06/r1: closed-reimbursed; reviewed/accepted/net 100001 cents; balance 0. Request REQ-C06; acceptance F-C06-accepted; settlement F-C06-1. Evidence: initial-claims:page:6:claim, initial-claims:page:6:claim:expense:1, interview:ordinary_entitlement, policy:finance_admission, policy:finance_reconciliation, receipts:page:3:receipt:2, travel-registers:Finance activity:row:11, travel-registers:Finance activity:row:38, travel-registers:Merchant payments:row:11, travel-registers:People:row:6, travel-registers:Review ledger:row:24, travel-registers:Review ledger:row:25, travel-registers:Review ledger:row:26, travel-registers:Review ledger:row:27, travel-registers:Review packets:row:24, travel-registers:Review packets:row:25, travel-registers:Review packets:row:26, travel-registers:Review packets:row:27, travel-registers:Trips:row:11.

## Supported business dispositions (financial status remains held)

- C13/r1: withdrawn — Employee withdrew before review. Evidence: initial-claims:page:13:claim.
- C14/r1: rejected — Client work was cancelled. Evidence: initial-claims:page:14:claim, travel-registers:People:row:6, travel-registers:Review ledger:row:40, travel-registers:Review packets:row:40, travel-registers:Trips:row:19.

## Independent cancellations

| Process | Trip/revision | Target | Business state | Financial consequence | Owner |
|---|---|---|---|---|---|
| TC018 | T18/r1 | trip | confirmed | unresolved | FIN-01 |
| TC019 | T19/r1 | trip | confirmed | unresolved | FIN-01 |
| TC121 | T121/r1 | permit | confirmed | unresolved | FIN-01 |
| TC122 | T122/r1 | trip | confirmed | no-financial-effect | No current action |

No claim row is invented for a cancellation with no claim. Business cancellation changes no Finance money.

## Owned repairs and partial updates

Use [repair-queue.json](repair-queue.json) for item-level subject/revision, owner, exact evidence/action, source references and history. [repair-queue.csv](repair-queue.csv) contains open items.
A response clears only its matching item after deterministic recheck. Superseded claim reviews remain history; original-request money and holds remain separately active.

- Batch [001](queue/001.json): {'opened': 886}; 886 open repairs.
- Batch [002](queue/002.json): {'reopened_or_updated': 196, 'opened': 17, 'cleared_by_recheck': 211}; 692 open repairs.
- Batch [003](queue/003.json): {'opened': 52, 'reopened_or_updated': 13, 'superseded': 40, 'cleared_by_recheck': 6}; 698 open repairs.
- Batch [004](queue/004.json): {'opened': 9, 'reopened_or_updated': 16, 'cleared_by_recheck': 13, 'superseded': 11}; 683 open repairs.

## Completion boundary and handoff

Finance must supply exact request/revision/cost allocation and scoped resolution evidence. Current reviewers must supply verifiable amount/exception context and current decisions. Employees own missing merchant payment proof. The facilitator owns native policy/package-version/schema clarification.
C18 corrections after original acceptance remain subject to Decision 001. Equal request/net amounts, a cancellation status, a refund promise, or an earlier approval never substitutes for current authorization.
All 18 visible normalization diagnostics remain in batch 004. Policy/approval/Finance repairs are independent; no missing fact is silently waived.
The original assignment is a preserved historical capture. No live source refresh or capture checkpoint was fabricated. This directory is an operator replay/handoff, not a certified-complete submission.

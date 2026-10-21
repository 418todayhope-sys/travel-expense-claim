# Operator handoff — omega4-attempt002-containment-v2

Mode: offline retained-source replay. No fresh acquisition, financial closure, external request or submission is asserted.

Final batch: 004; 121 current claims, all held. Actual financial closures: 0.
Supported expense eligibility, supplied review replies, admitted request-level money and actual closure are separate facts.
Unknown paid/balance amounts are blank in claims.csv. Snapshot paid_cents is only the proven attributed subtotal (0), with paid_cents_complete=false and known_paid_cents=null; it is not proof of zero payment.
Finance has no revision/cost columns: original requests are fully retained in request_facts; schema requests stays empty rather than inventing a required revision.

## Retained evidence and replay

See [sources.json](sources.json), [original acquisition manifest](acquisition-manifest.original.json) and [sealed manifest](operator-manifest.v1.json).
Native policy remains unavailable. The October 20 browser copy is supplemental, with its provenance preserved; semantic source completeness is unverified.
The four snapshots bind their predecessor and derived replay source manifest. No historical execution times were invented.

| Batch | Claims | Finance events | Settled cents | Refund cents | Net cents | Open repairs |
|---|---:|---:|---:|---:|---:|---:|
| [001](batches/001.json) | 120 | 100 | 0 | 0 | 0 | 774 |
| [002](batches/002.json) | 120 | 200 | 1153915 | 0 | 1153915 | 592 |
| [003](batches/003.json) | 121 | 210 | 1164415 | 1000 | 1163415 | 597 |
| [004](batches/004.json) | 121 | 219 | 1206415 | 3000 | 1203415 | 582 |

Final request ledger: 104 original request facts; admitted settlements 1206415 cents, linked refunds 3000 cents, net 1203415 cents.
These totals are not revision-attributed employee paid totals and do not authorize or close claims.

## Claims and owners

| Claim/revision | Eligibility | Review evidence | Gross EUR cents | Policy calculation cents | Owner | Snapshot issues |
|---|---|---|---:|---:|---|---|
| C01/r1 | supported | unresolved | 10000 | 10000 | ADMIN-01 | 3 |
| C02/r1 | supported | unresolved | 54000 | 54000 | ADMIN-01 | 3 |
| C03/r1 | supported | unresolved | 20000 | 20000 | ADMIN-01 | 3 |
| C04/r1 | supported | unresolved | 10000 | 10000 | ADMIN-01 | 3 |
| C05/r1 | supported | unresolved | 100000 | 100000 | ADMIN-01 | 3 |
| C06/r1 | supported | unresolved | 100001 | 100001 | FIN-01 | 3 |
| C07/r1 | supported | unresolved | 36000 | 30000 | ADMIN-01 | 3 |
| C08/r1 | unresolved | unresolved | 12000 |  | EMP-01 | 11 |
| C10/r1 | blocked | unresolved | 9000 | 9000 | ADMIN-01 | 9 |
| C11/r1 | supported | unresolved | 6000 | 6000 | ADMIN-01 | 3 |
| C13/r1 | supported | unresolved | 5000 | 5000 | ADMIN-01 | 7 |
| C14/r1 | supported | blocked | 4000 | 4000 | FIN-01 | 6 |
| C15/r1 | blocked | unresolved | 3000 | 0 | LEAD-01 | 9 |
| C16/r1 | supported | unresolved | 10000 | 10000 | FIN-01 | 3 |
| C17/r1 | supported | unresolved | 10000 | 10000 | FIN-01 | 3 |
| C20/r1 | supported | unresolved | 10000 | 10000 | FIN-01 | 3 |
| C21/r1 | supported | blocked | 8000 | 8000 | SUP-01 | 6 |
| C22/r1 | unresolved | unresolved |  |  | FIN-01 | 9 |
| C23/r1 | unresolved | unresolved | 17000 |  | ADMIN-01 | 9 |
| C25/r1 | blocked | unresolved | 10000 | 10000 | LEAD-01 | 9 |
| C26/r1 | supported | unresolved | 10000 | 10000 | ADMIN-01 | 7 |
| C27/r1 | supported | unresolved | 3500 | 3500 | FIN-01 | 3 |
| C28/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 3 |
| C29/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 3 |
| C30/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 3 |
| C31/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 3 |
| C32/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 3 |
| C33/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 3 |
| C34/r1 | supported | unresolved | 4500 | 4500 | FIN-01 | 3 |
| C35/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 3 |
| C36/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 3 |
| C37/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 3 |
| C38/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 3 |
| C39/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 3 |
| C40/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 3 |
| C41/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 3 |
| C42/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 3 |
| C43/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 3 |
| C44/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 3 |
| C45/r1 | supported | unresolved | 3500 | 3500 | FIN-01 | 3 |
| C46/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 3 |
| C47/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 3 |
| C48/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 3 |
| C49/r1 | supported | unresolved | 7500 | 7500 | FIN-01 | 3 |
| C50/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 3 |
| C51/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 3 |
| C52/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 3 |
| C53/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 3 |
| C54/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 3 |
| C55/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 3 |
| C56/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 3 |
| C57/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 3 |
| C58/r1 | supported | unresolved | 4500 | 4500 | FIN-01 | 3 |
| C59/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 3 |
| C60/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 3 |
| C61/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 3 |
| C62/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 3 |
| C63/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 3 |
| C64/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 3 |
| C65/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 3 |
| C66/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 3 |
| C67/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 3 |
| C68/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 3 |
| C69/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 3 |
| C70/r1 | supported | unresolved | 4500 | 4500 | FIN-01 | 3 |
| C71/r1 | supported | unresolved | 5500 | 5500 | FIN-01 | 3 |
| C72/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 3 |
| C73/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 3 |
| C74/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 3 |
| C75/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 3 |
| C76/r1 | supported | unresolved | 4500 | 4500 | FIN-01 | 3 |
| C77/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 3 |
| C78/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 3 |
| C79/r1 | supported | unresolved | 7500 | 7500 | FIN-01 | 3 |
| C80/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 3 |
| C81/r1 | supported | unresolved | 3500 | 3500 | FIN-01 | 3 |
| C82/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 3 |
| C83/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 3 |
| C84/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 3 |
| C85/r1 | supported | unresolved | 7500 | 7500 | FIN-01 | 3 |
| C86/r1 | supported | unresolved | 8500 | 8500 | ADMIN-01 | 3 |
| C87/r1 | supported | unresolved | 3500 | 3500 | FIN-01 | 3 |
| C88/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 3 |
| C89/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 3 |
| C90/r1 | supported | unresolved | 6500 | 6500 | FIN-01 | 3 |
| C91/r1 | supported | unresolved | 7500 | 7500 | FIN-01 | 3 |
| C92/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 3 |
| C93/r1 | supported | unresolved | 3500 | 3500 | ADMIN-01 | 3 |
| C94/r1 | supported | unresolved | 4500 | 4500 | ADMIN-01 | 3 |
| C95/r1 | supported | unresolved | 5500 | 5500 | ADMIN-01 | 3 |
| C96/r1 | supported | unresolved | 6500 | 6500 | ADMIN-01 | 3 |
| C97/r1 | supported | unresolved | 7500 | 7500 | ADMIN-01 | 3 |
| C98/r1 | supported | unresolved | 8500 | 8500 | FIN-01 | 3 |
| C99/r1 | supported | unresolved | 99999 | 99999 | FIN-01 | 3 |
| C100/r1 | supported | unresolved | 100000 | 100000 | FIN-01 | 3 |
| C101/r1 | supported | unresolved | 100001 | 100001 | ADMIN-01 | 3 |
| C102/r1 | supported | unresolved | 14999 | 14999 | ADMIN-01 | 3 |
| C103/r1 | supported | unresolved | 15000 | 15000 | ADMIN-01 | 3 |
| C104/r1 | supported | unresolved | 15001 | 15000 | FIN-01 | 3 |
| C105/r1 | supported | unresolved | 3999 | 3999 | FIN-01 | 3 |
| C106/r1 | supported | unresolved | 4000 | 4000 | ADMIN-01 | 3 |
| C107/r1 | supported | unresolved | 4001 | 4000 | FIN-01 | 3 |
| C108/r1 | supported | unresolved | 208 | 208 | ADMIN-01 | 3 |
| C109/r1 | supported | unresolved | 208 | 208 | ADMIN-01 | 3 |
| C110/r1 | supported | unresolved | 2500 | 2500 | ADMIN-01 | 3 |
| C111/r1 | supported | unresolved | 2500 | 2500 | FIN-01 | 3 |
| C112/r1 | blocked | unresolved | 2500 | 2500 | ADMIN-01 | 9 |
| C113/r1 | unresolved | unresolved | 2500 | 2500 | ADMIN-01 | 8 |
| C114/r1 | unresolved | unresolved | 3500 |  | EMP-03 | 12 |
| C115/r1 | blocked | unresolved | 2500 | 1500 | FIN-01 | 5 |
| C116/r1 | unresolved | unresolved |  |  | ADMIN-01 | 10 |
| C117/r1 | unresolved | unresolved | 5000 |  | EMP-03 | 9 |
| C118/r1 | blocked | unresolved | 2500 | 0 | LEAD-01 | 10 |
| C119/r1 | supported | unresolved | 100001 | 100001 | ADMIN-01 | 4 |
| C120/r1 | supported | unresolved | 7500 | 7500 | FIN-01 | 3 |
| C09/r2 | supported | unresolved | 8000 | 8000 | ADMIN-01 | 3 |
| C24/r1 | supported | unresolved | 25000 | 25000 | FIN-01 | 4 |
| C18/r2 | supported | unresolved | 10000 | 10000 | FIN-01 | 10 |
| C12/r2 | supported | unresolved | 7000 | 7000 | ADMIN-01 | 3 |
| C121/r2 | supported | unresolved | 3000 | 2000 | ADMIN-01 | 3 |
| C19/r3 | supported | unresolved | 10000 | 8000 | FIN-01 | 4 |

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

- Batch [001](queue/001.json): {'opened': 774}; 774 open repairs.
- Batch [002](queue/002.json): {'reopened_or_updated': 204, 'opened': 17, 'cleared_by_recheck': 199}; 592 open repairs.
- Batch [003](queue/003.json): {'opened': 46, 'reopened_or_updated': 13, 'superseded': 35, 'cleared_by_recheck': 6}; 597 open repairs.
- Batch [004](queue/004.json): {'opened': 8, 'reopened_or_updated': 18, 'cleared_by_recheck': 13, 'superseded': 10}; 582 open repairs.

## Completion boundary and handoff

Finance must supply exact request/revision/cost allocation and scoped resolution evidence. Current reviewers must supply verifiable amount/exception context and current decisions. Employees own missing merchant payment proof. The facilitator owns native policy/package-version/schema clarification.
C18 corrections after original acceptance remain subject to Decision 001. Equal request/net amounts, a cancellation status, a refund promise, or an earlier approval never substitutes for current authorization.
All 18 visible normalization diagnostics remain in batch 004. Policy/approval/Finance repairs are independent; no missing fact is silently waived.
The original assignment is a preserved historical capture. No live source refresh or capture checkpoint was fabricated. This directory is an operator replay/handoff, not a certified-complete submission.


## Decision 002: dependency-based containment

Evidence work and financial closure have separate states. See [dependency graph](dependencies/004.json) for proven directed edges, unsatisfied roots, deterministic impact paths, executed checks and candidate-only Finance links.
Current evidence-processing states: {'independently_resumable': 119, 'partial': 2}. Graph: 3873 nodes, 3770 edges, 621 unsatisfied roots, 901 impacted nodes.
Package requirements: 4, separately owned; no blanket inherited_validation_limits claim defect. Before: 703 open repairs; active scoped presentation: 582. Earlier register still has 703 open items, preserved unchanged in prior-repair-queue.original.json. No item in it was cleared by this decision.
The 121 removed blanket claim presentations are reclassified, not resolved. Global policy/package certification remains unresolved, and every existing financial hold remains. Prior artifacts bind historical code, not current code; historical file integrity was checked separately.
Independent processing means executed receipt/payment and policy checks with per-operation holds; it never means approval, dispatch or financial closure. C18/r2 remains held under Decision 001 while T18B evidence checks continue. C08/C114 merchant-proof gaps remain owned and unresolved.
Limitations: global requirement applicability is unresolved; full current-revision rechecks remain conservative. No certified Finance revision/cost attribution or current review basis was supplied. Base source tables have no arrival labels. No prior evidence is overwritten.

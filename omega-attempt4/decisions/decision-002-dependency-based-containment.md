# Decision 002 — Dependency-based containment

Date: 2026-10-21  
Project: D, Omega Attempt 4  
Status: Explicitly authorized by Max Gabel in the coding conversation; documented here. General implementation and acceptance verification remain pending.

## Authorized selection

> Hold work affected by missing or changed evidence and its proven dependencies; allow unrelated evidence processing and verification to continue.

Max Gabel selected dependency-based containment. The unit of containment is affected work and its evidenced dependency path, which can cross claim boundaries. It is neither automatically one whole claim nor automatically the whole arrival batch. Independent processing means preparing, parsing, checking, and retaining evidence and findings; it does not itself establish approval, readiness, payment, or closure.

This record adopts the constraint for subsequent implementation. It does not retroactively certify the existing runs as implementing it. [Decision 001](decision-001-correction-finance-hold.md) remains unchanged and binding: corrected claims with unresolved original-request payments remain held pending explicit Finance resolution and current reviews. Decision 002 cannot narrow away that hold.

## Supporting evidence and its limits

All references below are preserved local evidence. Line numbers refer to the existing files, not new interpretations supplied by stakeholders.

| Evidence | Source support and consequence |
| --- | --- |
| [Historical assignment](../validation/references/assignment-captured-20261016.txt#L11), lines 11–13 | Cover every record and arrival batch; unresolved work needs an affected subject, reason, owner, and evidence to resume. Repair work remains individually traceable through partial responses. Containment must not silently drop assigned work. |
| Assignment, lines 18–23 | Human authority is retained. The participant must choose how incomplete claims affect independent work and what corrections invalidate, adopt constraints before they govern work, and verify material branches and identities. This decision records the participant's choice; it is not a stakeholder approval. |
| Assignment, lines 16 and 42 | Label source-access failures and offline replay; preserve source bindings, arrival boundaries, and immutable predecessor snapshots. New behavior requires a new run rather than replacement of sealed evidence. |
| [POL-2026.2 browser copy](../user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.txt#L27), line 27 | Missing/conflicting information holds affected claims; independent processing or conservative batch containment is permitted with its business cost explained. Neither may claim unperformed work as complete. This supports the choice, without declaring dependency-based containment mandatory company policy. |
| Policy, lines 22–24 | Reviews bind exact subjects, revisions, actors, roles, and source versions. Material changes invalidate dependent reviews/readiness even with unchanged totals; full recheck or justified dependency recheck is allowed. Prior cost obligations must be linked and excluded from duplicate reimbursement. |
| Policy, lines 21 and 25–26 | Whole-ledger budget context and immutable Finance events can create dependencies beyond one claim. Finance facts, current approvals, attribution, and required resolutions remain separate closure requirements. |
| Policy, lines 28–31 | Cancellation has exact trip/permit targets and independent history. Cancelling an old trip does not cancel a different reassigned trip. Business cancellation does not erase a Finance request or transfer. |
| [October 20 interview](<../interviews/project-d-travel-expense-claim-20261020-1419(1).md>), lines 170–182 | The lead permits independent claims to continue while affected incomplete claims wait, with the business cost explained; track exact claim version, missing fact, and responsible owner. |
| Interview, lines 286 and 414–438 | Recheck affected dependencies after correction, including changed evidence with unchanged amounts; dependent reviews must be repeated. |
| Interview, lines 334–350 and 374–390 | Track and update individual missing facts; unresolved access/evidence cannot be erased or waived. |
| Interview, lines 841–865 | Preserve old-version Finance replies but do not use them to authorize the corrected version. Obtain Finance clarification and rebuild current readiness. Missing receipts or settled-payment proof require actual evidence. |

The assignment is the historical October 16 capture, not a newly retrieved original. The policy is the user-provided October 20 browser-visible copy; [its provenance](../user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.provenance.json) records non-native copying, unknown exact retrieval time, and unverified completeness. Native policy access remains unresolved. No network verification was performed for this decision. The original interview has not been rewritten.

Preserved SHA-256 bindings:

```text
Historical assignment: 20cca989d5b18e96f83ce08c455959b8f9b36ed951b87d294ff17abdb95db803
Policy browser copy: 04d8121a91986dc0839094b5e7f574c44f6261c60c1c3ba9aeeee1c279ee5993
Policy provenance: 8e0d9fb0e30a6c5468e36ddc785842841eca8d6d922ecc1bd3baa90267c1359f
Original interview: c308181fc8b79ea07f57172b196513d8494b98121de02b46640dd39619539d9f
Decision 001: acb1e7dd37e118e07f25e1c017418f05213f1ed9461bf0020c0bf5f500fc1c8d
```

## Alternatives considered and rationale

| Alternative | Defensible use and limitation | Selection |
| --- | --- | --- |
| Claim-level isolation | Simple ownership and continued work on other claims. Sufficient when the evidence establishes no relevant cross-claim dependencies; insufficient when claims reuse one purchase or share a budget/obligation basis. | Not the general rule. |
| Whole-batch containment | Conservative when an inaccessible source, corrupt input, or shared definition genuinely prevents establishing independence. Delays unrelated verification and repair preparation; an arrival batch alone is not evidence that all work is dependent. | Not the default. Retain a wider hold when its scope cannot yet be established, with an owned explanation. |
| Dependency-based containment | Holds affected checks and downstream work, including links across claims, while permitting unrelated evidence work. Requires traceable scope and explicit handling of uncertain dependencies. | Authorized selection. |

The benefit is earlier independent verification and repair preparation without permitting stale evidence to authorize downstream work. The cost is maintaining evidence-backed dependency scope and explaining uncertainty. A common employee, equal amount, neighboring spreadsheet row, or common arrival batch alone does not prove the relevant dependency. Conversely, different claim IDs do not prove independence.

## Operational interpretation and restrictions

1. Identify the missing or changed fact, source version, affected subject/revision, and operation whose basis depends on it. Follow proven dependency paths into expense findings, review packets/decisions, travel authority, requests, or reconciliation. Record direction, source references, reason, and scope; do not turn a possible association into certified financial attribution.
2. Hold the affected operation and its dependent authorization/readiness. Continue independent evidence acquisition where otherwise authorized, parsing, arithmetic, verification, and preparation with honest partial/unresolved labels. A held payment process may still accumulate verified evidence and preserve incoming Finance facts.
3. Recheck material corrections even if money totals match. A dependency-limited recheck requires justification for what remains valid; use a full affected-subject recheck when independence is not established. Historical approvals remain history. No stale approval becomes current because an unrelated check passed.
4. If dependency scope is uncertain, retain an owned unresolved scope item and the necessary conservative hold. Establish independence before releasing affected work; absence of a recorded edge alone is insufficient when a shared source, ledger, or obligation may govern it. Do not invent a connection or declare a universal dependency without explaining the uncertainty.
5. Preserve gross purchase amounts, policy-calculated amounts, reviewed entitlement, Finance request facts, and attributed settlement separately. Missing evidence is unknown, not zero or paid. Continue observing original requests, late transfers, cancellations, refunds, and conflicts while held.
6. This decision grants no approval, exception, permit, Finance resolution, dispatch, booking, payment, or closure authority. It waives no review, receipt, merchant-payment proof, or cancellation-aware review requirement. It clears no existing repair item. Owners remain those evidenced by the directory/policy and existing queue; questions of rule or scope go to the lead/facilitator, financial attribution/resolution to authorized Finance, and missing employee evidence to its evidenced owner. No request is sent by this record.
7. Preserve arrival order, source hashes, rejected imports, immutable event identities, previous snapshots, and repair history. Later implementation must bind this decision in new versioned outputs. Do not add it retroactively to existing manifests or rewrite earlier evidence.

## Concrete dependency examples

### C03/C24 — shared purchase, separate claim and request facts

The retained [normalized records](../artifacts/normalizations/omega4-attempt002-normalization-v1/records.v1.json) identify:

- `initial-claims:page:3:claim`: C03/r1, batch 1, EMP-01, T03/r1, COST-03, R-COST-03, EUR 200.00.
- `claim-updates:page:3:claim`: C24/r1, batch 3, explicitly related to C03, same employee/trip and COST-03/R-COST-03/EUR 200.00, plus COST-24/R-COST-24/EUR 50.00.
- `travel-registers:Merchant payments:row:8`: M-COST-03 reports settled purchase EUR 200.00 with matching employee/trip/cost/receipt/currency. Row 29 separately reports M-COST-24 for EUR 50.00.
- Finance activity rows 35/8: F-C03-accepted/F-C03-1 bind REQ-C03 to C03 with accepted/settled EUR 200.00. Rows 48/30 separately bind F-C24-accepted/F-C24-1 to REQ-C24/C24 with accepted/settled EUR 50.00.

**Verified link:** both claim occurrences use the same identified COST-03 purchase evidence, and C24 explicitly names C03 as an earlier claim. Missing or changed COST-03 proof affects both occurrences and their dependent reviews/readiness, even though the claim IDs differ. A COST-24-only defect does not automatically invalidate C03; any wider propagation needs another evidenced path, such as a shared ledger or review basis.

**Unresolved attribution:** request-to-claim identities and request-level amounts are source facts, but the Finance sheet supplies no explicit claim-revision/cost allocation fields. Equal totals and current-at-acceptance candidates do not certify the transfer's allocation or current approvals. The [reconciliation](../artifacts/reconciliations/omega4-attempt002-finance-reconciliation-v1/reconciliation.v1.json), `claims[claim_id=C24,revision=1].incremental_policy_candidate_cents`, shows 5,000 cents as a conditional incremental calculation. Preserve C24's 25,000-cent gross and policy calculation separately; do not describe the candidate 5,000 cents as authorized entitlement, certified cost allocation, or closure. Sharing purchase evidence does not merge REQ-C03 and REQ-C24 into one event or permit duplicate payment.

### C18 — original trip cancellation and replacement-trip work

Exact retained record locators in the same normalized file:

| Locator | Verified observation |
| --- | --- |
| `initial-claims:page:18:claim` | C18/r1, T18/r1, COST-18/R-COST-18, EUR 100.00. |
| `claim-updates:page:4:claim` | C18/r2, batch 3, T18B/r1, COST-18B/R-COST-18B, EUR 100.00. |
| `travel-registers:Merchant payments:row:22` and `:row:30` | Separate settled purchases M-COST-18 and M-COST-18B for the two distinct trip/cost/receipt identities. |
| `travel-registers:Travel cancellations:row:10` and `:row:11` | TC018-requested/confirmed target T18/r1; EMP-01 initiates, SUP-01 confirms. Neither targets T18B. |
| `travel-registers:Finance activity:row:43`, `:row:19`, `:row:20`, `:row:21` | REQ-C18 acceptance, cancellation request, cancellation confirmation, then F-C18-3 settlement EUR 100.00 in batch 4. |
| `travel-registers:Review ledger:row:47` through `:row:49` | C18/r1 review decisions only. No C18/r2 claim reviews appear in the retained ledger. |

**Verified scope:** TC018 retires T18/r1, not T18B/r1. Replacement receipt/payment-evidence verification can continue. C18/r2 payment readiness nevertheless remains held under Decision 001 because original-request consequences and required current reviews remain unresolved. The admitted original-request settlement stays visible once; cancellation does not erase it.

**Do not assume:** the same employee, claim number, or EUR 100.00 amount does not make COST-18 and COST-18B the same purchase, transfer F-C18-3 to the replacement expense, cancel T18B, prove replacement permission, supply r2 approvals, or resolve Finance consequences. Independent replacement evidence processing is not permission to dispatch a replacement reimbursement.

The PDFs/workbook above are retained locally under [the acquisition run](../artifacts/runs/omega4-live-20261020-attempt002/sources.json) and copied in [the operator source bindings](../artifacts/runs/omega4-attempt002-operator-v1/source-bindings.json). PDF locators are pages; workbook locators are tab and original row, also encoded in normalized record IDs. Current retained workbook SHA-256 is `b90c7cf0db738ed186d9a2302752eb8ded3c326aa9894f736c21d426814fb898`; it is distinct from the earlier in-memory workbook observations preserved in Decision 001. Those observations are not interchangeable byte bindings.

## Read-only implementation assessment

Assessment is static inspection of current code, retained results, and existing test assertions; no code was changed or behavior newly certified.

| Area | Existing support | Gap relative to this decision |
| --- | --- | --- |
| Continued processing | [validation/validate.py](../validation/validate.py#L447), `evaluate`, processes available claims; [reconciliation/reconcile.py](../reconciliation/reconcile.py#L377), `evaluate`, reconstructs arrival-bounded views and preserves request facts. | Processing continues, but no general reusable impact calculation identifies which operations may resume independently. |
| Revision and trip scope | Validation lines 461–483 match exact trip/revision and recheck current claim evidence without inherited claim approvals; cancellation selection is exact-trip scoped. | The implementation performs full claim rechecks rather than emitting a justified dependency-scoped invalidation path. Full recheck is policy-permitted, but does not demonstrate general cross-claim containment. |
| Shared costs | Validation lines 484–487 flag shared cost identities; reconciliation lines 340–373 compare purchase identities and preserve conditional exclusion separately. | This detects important links, but does not implement a general transitive dependency model or propagate a changed shared evidence item through all dependent work with an auditable scope. Cost-ID matching alone at validation is less specific than reconciliation's purchase tuple. |
| Financial uncertainty and Decision 001 | Reconciliation lines 298–312 distinguish candidates from certified attribution; lines 475–480 retain the corrected-claim hold. | Missing explicit revision/cost attribution remains unresolved; containment cannot fill that evidence gap. |
| Global findings | Reconciliation lines 473–474 attach `inherited_validation_limits` to every claim whenever any global finding exists. | No per-finding applicability scope establishes which claims/operations depend on each global defect. A genuinely shared policy/ledger gap may warrant broad containment, but the current fan-out does not prove scope individually. |
| Operator state and queue | [operator_delivery/build.py](../operator_delivery/build.py#L165), lines 165–220, maintains fact-level repairs and queue histories; lines 224–259 distinguish eligibility from authority and attribution. | `project_claim` sets every claim to `held` (line 243); snapshot checking requires that state (line 317). There is no tested independently resumable state backed by a dependency proof. Queue retirement at lines 212–219 follows disappearance from deterministic recheck, without an explicit dependency-resolution proof. Adoption of this decision must not invoke that mechanism to clear existing items. |
| Existing regression coverage | [tests/test_operator_delivery.py](../tests/test_operator_delivery.py) covers C03/C24 conditional arithmetic, C18 old-request money/missing r2 reviews, stale evidence, and replay; [tests/test_reconciliation.py](../tests/test_reconciliation.py) checks request-level cases. | These are useful fragments, not acceptance evidence for a general containment rule. Dedicated shared-evidence propagation, uncertain-scope, and unrelated-work noninterference checks remain to add. No tests were run for this documentation-only change. |

The existing [report](../artifacts/runs/omega4-attempt002-operator-v1/report.md), [repair queue](../artifacts/runs/omega4-attempt002-operator-v1/repair-queue.json), and [snapshot-chain manifest](../artifacts/runs/omega4-attempt002-operator-v1/operator-manifest.v1.json) remain the unchanged earlier result: 121 current claims, all held; 703 open repairs; 18 normalization diagnostics; 104 original request facts; 219 admitted Finance events; zero financial closures. These counts do not establish that all claims have one proven common dependency. They also do not justify releasing any hold. C18/r2's missing reviews remain visible.

## Unknowns and implementation consequences

- The preserved package does not yet establish certified request-to-revision/cost attribution or all review-packet/source-definition and whole-ledger budget facts. Containment scope for those shared defects needs evidence from the appropriate lead/facilitator or Finance owner; this decision supplies none.
- Policy permits both full and justified dependency rechecks but does not prescribe a graph format or exhaustively enumerate dependency edges. A future implementation must document its evidence-based dependency vocabulary, direction, versioning, and uncertainty representation. A graph or equivalent auditable structure is an implementation choice, not a new policy requirement.
- Separate proven subject/evidence links from candidate financial links. Emit affected operation/revision, root missing/changed fact, dependency path, source references, owner, next action, and reason for any broader unresolved scope. Recompute dependent reviews/readiness without changing historical approvals or admitted money.
- Continue independent verification under explicit partial-result labels. Do not equate a successful parser/check with an approved claim or a resumed payment. Shared budget context may block review/readiness while allowing receipt checks.
- A subsequent authorized implementation must add focused tests and new versioned outputs binding Decision 002. Existing snapshots/manifests predate it and must remain unchanged. The current globally held projection and blanket global-finding inheritance need assessment and changes before claiming complete operational support.

## Measurable acceptance criteria — future verification, not executed

1. **Shared evidence crosses claim IDs.** In an isolated mutation of COST-03 proof, identify both C03/r1 and C24/r1 affected expense occurrences and dependent review/readiness operations, with source-backed paths. Retain both gross amounts and the two original request identities. Do not duplicate, erase, or allocate settlements by guess.
2. **A local defect does not spread without justification.** In an isolated COST-24-only mutation, identify C24's affected work. Preserve C03's otherwise unchanged evidence findings and admitted request-event facts unless a separate demonstrated dependency requires recheck. Record that path if broader scope is asserted.
3. **Independent checks continue.** With an unrelated claim's merchant proof removed, produce an owned missing-proof item and hold its dependent work while still executing identifiable unrelated receipt/arithmetic checks. Existing global holds may remain; demonstrate continuation by executed checks and preserved findings, not by falsely making another claim ready.
4. **C18 containment respects both bases.** TC018 affects T18/r1 and does not cancel T18B/r1. Verify replacement purchase evidence independently, satisfy zero current review positions with r1 decisions, retain missing r2 reviews, and keep Decision 001's hold. F-C18-3 remains once, contributing 10,000 cents once to REQ-C18; no replacement allocation, refund, or resolution is invented.
5. **Same-total corrections invalidate dependencies.** Change material evidence while preserving the amount. Reject dependent old reviews for current readiness, retain historical decisions, and identify affected paths and the evidence needed to resume. Any retained unaffected decision requires a documented dependency justification and all applicable current-version rules.
6. **Uncertain scope stays explicit.** A missing shared policy/ledger definition produces an owned unresolved scope item, explains the business delay and any wider hold, and does not fabricate independence. Supplied clarification triggers a scoped recheck; this decision alone clears zero repairs.
7. **Partial repair cannot over-release.** Supply one missing fact for a subject with multiple repairs. Recheck only as justified, retain every unsatisfied repair and its owner, and require actual evidence plus current reviews/Finance facts for any state transition. Preserve all 18 prior normalization diagnostics as history, including C18/r2's missing-review diagnostic.
8. **Replay and history remain reproducible.** Unchanged replay preserves event/request identity and money. New authorized behavior produces new versioned snapshots/source and decision bindings with valid predecessor hashes; earlier evidence bytes remain unchanged. A conflict creates an owned hold without erasing admitted money. No containment-only transition marks a claim paid or closed.

## Documentation boundary

This change creates only this decision document. Decision 001, original interviews, workflow code, generated artifacts, and existing repairs are preserved. Acceptance criteria above are requirements for later work, not test results. No workflow implementation, regeneration, network access, commit, push, deployment, or submission is authorized or performed by this record.

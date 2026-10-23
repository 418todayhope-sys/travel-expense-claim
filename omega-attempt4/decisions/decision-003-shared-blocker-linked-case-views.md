# Decision 003 — Shared blocker plus linked case views

Date: 2026-10-21  
Project: D, Omega Attempt 4  
Status: Explicitly authorized by Max Gabel in the coding conversation. Documentation adopted; implementation and acceptance verification pending.

## Authorized selection

Use a shared blocker with a central identity, owner, evidence references, and linked affected cases, while retaining every claim/revision's own repair requirements and history. Case views expose their shared dependencies alongside their independent missing facts, responsible people, and next actions.

Resolving a shared blocker must never automatically clear case-specific missing approvals, merchant-payment proof, Finance allocation, or financial holds. It supplies evidence for a scoped recheck; it is not blanket case resolution. A partial response updates only the facts it actually establishes.

This is Max Gabel's workflow-organization choice, not a newly supplied stakeholder answer or a company-mandated data model. [Decision 001](decision-001-correction-finance-hold.md) and [Decision 002](decision-002-dependency-based-containment.md) remain unchanged and binding. Dependency-based containment determines which work is affected; this decision determines how shared repair work and its case views are represented. Neither changes financial authority or closure conditions. Existing artifacts predate this authorization and are not retroactively certified as implementing it.

## Assignment, policy, and interview evidence

| Preserved local reference | Supporting fact and implication |
| --- | --- |
| [Historical assignment](../validation/references/assignment-captured-20261016.txt#L11), line 11 | Unresolved work must identify its affected work, reason, responsible person, and evidence needed to resume. Missing rules/access are escalated rather than guessed. A central blocker cannot obscure an individual case. |
| Assignment, line 13 | Choose queue organization and partial-response handling; preserve subject, revision, source, missing fact/return reason, responsible person, next action, and significant run/batch updates. Central organization must retain these item-level properties. Later supplied batches are fixed inputs, not replies caused by local drafts. |
| Assignment, lines 18, 20, 23 | Humans retain authority; the participant adopts source-grounded repair-organization constraints before implementation and verifies identities and transitions. This record adopts the selected organization, with future acceptance criteria below. |
| Assignment, line 42 | Preserve sealed source/predecessor bindings and use new versioned runs for changed results. Do not rewrite earlier queue history to introduce this decision. |
| [October 20 POL-2026.2 browser copy](../user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.txt#L22), line 22 | Exact subject/revision, role, stable actor, source versions, and reason govern replies. Missing responses differ from undefined policy/input packages. A shared package repair cannot stand in for a case approval. |
| Policy, lines 21, 23–24 | Whole-ledger context and prior cost obligations can be shared dependencies. Material evidence changes invalidate dependent reviews/readiness even with unchanged amounts. Preserve historical versions, decisions, and obligation identities. |
| Policy, lines 25–27 | Finance evidence alone establishes financial events; closure requires current approvals, obligation, net payments, and required resolutions to agree. Missing/conflicting information holds affected work. Queue grouping supplies no authority. |
| Policy, lines 28–31 | Trip/permit targets and business/Finance cancellations remain distinct. A shared cancellation repair cannot silently affect another trip or erase money. |
| [Original October 20 interview](<../interviews/project-d-travel-expense-claim-20261020-1419(1).md>), lines 334, 342, 350 | Track each missing fact, claim version, required evidence, and owner; update items individually. Per-claim or person-grouped organization is acceptable if status/source relationships remain clear and no authority is bypassed. These statements permit an organizational choice; they do not prescribe this central-blocker design. |
| Interview, lines 366, 374, 382, 390 | Receipt repair belongs to the employee; recheck after actual evidence arrives. Incomplete claims/access requirements stay unresolved. Each missing fact/version/owner remains independently identifiable. |
| Interview, lines 414–438 and 841–865 | Dependent reviews repeat after evidence changes, even with unchanged amounts. Retain old Finance replies but do not use them to authorize corrected claims; missing receipt/payment proof requires actual evidence. |

The assignment is the preserved October 16 historical capture, not a newly retrieved original. The policy is a user-provided October 20 browser copy; [its provenance](../user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.provenance.json) does not certify native completeness or an exact retrieval time. The original interview remains unchanged. No new stakeholder response, native source access, or waiver is asserted here.

## Current artifact evidence

The assessed run is `omega4-attempt002-containment-v2`, batch `004`. References into JSON use field selectors or exact record IDs, rather than unstable pretty-print line numbers.

- [Snapshot-chain manifest](../artifacts/runs/omega4-attempt002-containment-v2/operator-manifest.v1.json): `final_batch`, `files`, `input_bindings`, and `summary` bind the retained artifacts and governing inputs. Summary: 121 current claims, 127 claim revisions, 208 expense occurrences, 104 request facts, 219 admitted Finance events, 582 active repairs, and 18 normalization diagnostics.
- [Final snapshot](../artifacts/runs/omega4-attempt002-containment-v2/batches/004.json): `claims[].evidence_work` and `financial_closure_status` separate evidence work from closure; all 121 claims are financially held and `actual_financial_closure_count` is 0. `claim_revision_history`, decision deliveries, and predecessor links preserve historical context.
- [Containment graph](../artifacts/runs/omega4-attempt002-containment-v2/dependencies/004.json): `summary` contains 3,873 nodes, 3,770 edges, 621 unsatisfied roots, 901 impacted nodes, and four global requirements. Current evidence states are 119 `independently_resumable` and two `partial`. These counts describe checks and graph roots, not a count of central actionable blockers or completed claims.
- Graph `nodes[node_id=requirement:review_version_token]`: unresolved `DW-D-2` definition, owner `Facilitator`, source `policy:freshness`. The corresponding queue entry is `repair:366aa44e5685ec698cd7ddd892a628b653ebdcd615bdc429e7d49c5fa62482cf`, code `review_version_token`, package `policy-inputs`. This is an existing shared requirement, but the graph and queue do not explicitly cross-reference one another by blocker identity.
- Graph `global_requirement_ids` also contains `requirement:policy_provenance`, `requirement:assignment_access`, and `requirement:budget_completeness`. Their scope is `unresolved_package_requirement`; edges go to `workflow:certification`, not proven case-specific defects. The assignment-access node has empty `source_refs`; absence of native content is not a reason to invent a source or all-case dependency. A future blocker should point to retained failed-access/provenance evidence and state what remains unavailable.
- [Final repair queue](../artifacts/runs/omega4-attempt002-containment-v2/repair-queue.json): `items` has 845 historical entries: 582 open, 218 `cleared_by_recheck`, and 45 `superseded`. Open scopes are 467 claim, 106 request, three cancellation, and six package entries. The six package entries include the four global requirements plus two schema/representation gaps; four graph requirements do not represent all shared package work.
- [Current report](../artifacts/runs/omega4-attempt002-containment-v2/report.md), sections “Owned repairs and partial updates,” “Completion boundary and handoff,” and “Decision 002: dependency-based containment,” records the independent repair/authority boundary and the 703-to-582 active-presentation change. The [earlier repair register](../artifacts/runs/omega4-attempt002-containment-v2/prior-repair-queue.original.json) still preserves 703 open items unchanged. Reclassification of 121 blanket global presentations was not resolution. The current queue's 218 historical rechecks and 45 supersessions must not be confused with clearing that earlier register or with this decision resolving anything.

### Concrete linked-case examples

**C03/r1 and C24/r1:** The graph's shared purchase prefix is `purchase:ac4849305a26dc8e64053778a42c712b011d9d3c862e807a42e589962390bbcc`. Its `:receipt_identity`, `:receipt_date`, and `:merchant_payment` nodes appear in both case views' `executed_check_ids`. They cite `initial-claims:page:3:claim:expense:1`, `claim-updates:page:3:claim:expense:1`, `receipts:page:2:receipt:1`, and `travel-registers:Merchant payments:row:8` as applicable. EMP-01 is the recorded evidence-check owner. These nodes are currently supported, not open blockers; a future missing/conflicting fact may create a shared repair with both cases linked. Shared purchase evidence does not merge REQ-C03/REQ-C24, certify Finance cost allocation, or resolve either case's current approvals. COST-24 remains a distinct requirement unless another proven dependency applies.

**C08/r1 and C114/r1:** In the current queue, merchant proof remains separately open:

| Case/cost | Exact queue record ID | Recorded owner and evidence locator |
| --- | --- | --- |
| C08/r1, COST-08 | `repair:e01c35b3499c395ca87596c656ee94987f654c4ddd96a976eef4bfb0760cd46e` | EMP-01; `initial-claims:page:8:claim:expense:1`. |
| C114/r1, COST-114-2 | `repair:50451613997671ffee3c70a04d3b34a5d773ad2eb7512c449bc8d6b10eef2430` | EMP-03; `initial-claims:page:113:claim:expense:2`. |

The shared diagnostic code `merchant_payment` is not proof of a shared missing purchase fact. These items must remain distinct. Resolving a policy/version-definition blocker cannot supply either employee's settled-payment proof.

**C18/r2:** Queue record `repair:7ef019a11b71bdbc71142cefd5cf605259212dc8545a2dd0e01b66f9995826f6` is the open Decision 001 original-request hold, owned by FIN-01, with `claim-updates:page:4:claim` and Finance rows 19–21/43 among its references. The separate `approval_evidence` item is `repair:9b33d6197325b356b608dfa73c4b7b31420ca00dded926dcd4b95582e112f0fb`, owner ADMIN-01. Neither disappears when a shared package definition is supplied. TC018 targets T18/r1; C18/r2 uses T18B/r1. A cancellation-linked view must preserve that exact distinction and the missing r2 reviews, original-request money, and unresolved Finance attribution.

## Alternatives and rationale

| Approach | Benefit | Limitation and decision |
| --- | --- | --- |
| Claim/revision-first | Strong local accountability and straightforward revision history. | Repeats common package/evidence requests and may obscure one shared root. Retain as a case view, not the sole organizing identity. |
| Owner-first | Useful for handoff, workload, and collecting one person's outstanding evidence. | One owner may have unrelated facts and cases; owner changes must not merge requirements or erase history. Retain as an optional derived view, not the primary blocker identity. |
| Shared blocker plus linked case views | One central missing fact/definition and accountable owner, with evidence-backed impact links and independent case requirements. | Selected. Requires explicit scope, stable identities, bidirectional traceability, and careful partial-response/recheck handling. |

The selected approach reduces duplicate repair coordination while retaining the exact case/revision requirements needed for safe resumption. Grouping by similar wording, diagnostic code, actor, amount, or batch alone cannot establish that two items share a blocker. The central repair owner coordinates provision/clarification of that fact; ownership does not grant approval, exception, payment, or cancellation authority.

## Restrictions and intended implementation consequences

1. A future central blocker must retain a stable identity, exact missing fact or conflict, accountable evidence/rule owner, current state, source/version references, required evidence/next action, applicability scope, and run/batch lifecycle history. If ownership or scope is unknown, record that uncertainty and its clarification step; do not invent a named actor or global case linkage.
2. Affected-case links must identify claim and revision, relevant expense/trip/permit/request where applicable, the case repair identity, dependency/path evidence, and the operation held. Support central-to-case and case-to-central navigation. Unknown applicability is explicitly unresolved; do not manufacture proven graph edges to populate a view.
3. Every observed claim/revision retains its local requirements and history, including superseded versions. A case with no active repair can show that fact without creating one. Requests and cancellation processes without claims remain visible without fabricated claim rows.
4. Keep central fact state, link/recheck state, local repair state, and financial closure distinct. New shared evidence triggers only evidenced dependent rechecks under Decision 002. Each local requirement needs its own supported disposition; a blocker becoming resolved is never a blanket case-clear operation. A case may legitimately remain held after its shared blocker is resolved.
5. Record partial responses against the exact fact/scope they establish. Conflicting, stale, wrong-role, wrong-subject, or wrong-revision replies remain visible and unresolved for applicable authorization. Preserve raw replies and prior versions; unchanged totals do not excuse current reviews.
6. Preserve all case-specific merchant-proof, approval, Finance allocation/resolution, and Decision 001 holds. No approval, permit, refund, payment proof, financial authority, paid status, or closure can be inferred from grouping or ownership. Gross purchase, allowed arithmetic, request facts, and attributed settlement remain separate.
7. Version the central register and derived views in a new output directory with source hashes, decision binding, predecessor/run links, and repair-history migration mappings. Earlier repair IDs and states remain traceable. Do not retroactively add Decision 003 to existing manifests or clear the earlier register by migration.

## Read-only implementation assessment: support and gaps

| Existing implementation | Support | Specific remaining gap |
| --- | --- | --- |
| [containment.py](../operator_delivery/containment.py#L40), lines 40–66 | Nodes carry central IDs, owners, reasons, states, and source references; package requirements are separate from claim defects. | Nodes are not an owned shared-blocker lifecycle register. No response/resolution event or queue-item cross-reference is recorded. Some owners remain roles, and assignment-access references are empty. |
| Containment, lines 79–95 and 125–142 | Purchase identity deduplicates common evidence checks; exact cancellation targets and request/claim-family links preserve relevant scope. | Supported shared checks are not automatically blockers. Candidate financial associations cannot be promoted to certified allocation. Missing scope cannot be replaced with all-case links. |
| Containment, lines 17–33 and 143–166 | Deterministic impact paths and claim/revision work views provide a basis for derived affected-case links. | Case views have executed-check/operation IDs, not explicit shared-blocker-to-local-repair links. Global requirements currently link only to workflow certification; detailed case applicability is unknown. |
| [build.py](../operator_delivery/build.py#L82), lines 82–95 and 166–197 | Stable repair keys include subject/revision/cost/code; entries carry evidence, owner, next-evidence reason, and state. Current case/request/package items remain distinct. | Queue items have no `shared_blocker_id`, graph-node reference, or central affected-case index. Shared code/owner cannot safely serve as the join key. |
| Build, lines 200–222 | Queue histories preserve owner/reason/source changes, first/last batches, supersessions, and recheck dispositions. | Retirement follows absence from deterministic active findings; it does not record a shared-resolution-to-case-specific-recheck proof. A future shared resolution must not make dependent items disappear wholesale. Explicit local dispositions and auditable partial updates are needed. |
| Current snapshots/queue/report | Preserve 127 observed revisions, 582 active repairs, historical entries, global uncertainty, and separate financial/evidence states. | There is no combined central blocker register with complete bidirectional case views, cross-batch blocker history, or tests demonstrating shared resolution leaves independent case holds open. Existing containment tests do not certify Decision 003. |

This assessment identifies reusable foundations, not completed implementation. No workflow code or generated output changes are made by this record.

## Unknowns requiring future evidence or design

- The exact case/review scope of opaque `DW-D-2`, native policy completeness, assignment-access gaps, and shared budget completeness remains unresolved. Existing role owners do not establish a named person's authority to answer every package question.
- Stable blocker identity across changed facts, splits/merges, corrections, and owner handoffs needs a documented implementation rule and migration lineage. The policy does not prescribe a database schema or central-ID algorithm.
- The source/version and scope of an eventual resolving response must be established from retained authorized evidence; none is supplied by this decision. No automatic linkage by diagnostic code is authorized.
- Case-specific current reviews, merchant proof, and Finance revision/cost allocation remain missing as recorded. A shared definition may make rechecks possible; it does not predict that they pass.

## Measurable acceptance criteria — future work, not executed

1. **One fact, one central identity:** An isolated shared missing fact produces one central blocker with owner, reason, evidence/version references, required next action, and history. C03/C24 can both link to a defect in their verified shared COST-03 proof. Supported checks remain supported evidence, not invented open blockers.
2. **Complete case traceability:** Every observed claim/revision has a case view retaining its own repair identities, sources, state/history, and linked blockers. Against the current fixture, cover all 127 observed revisions and 121 current claims; all 582 currently active entries remain traceable with a reasoned migration mapping, with zero silently dropped repairs. Preserve cancellation/request work without fabricating claims.
3. **No fabricated applicability:** Package blockers with unknown case scope remain centrally owned and explicitly unresolved. Every asserted case impact resolves to retained dependency evidence; unknown scope is not counted as a proven edge or treated as permission to release work.
4. **Shared resolution does not clear local requirements:** In an isolated supplied package-definition response, resolve only the evidenced shared fact and recheck applicable links. With no additional evidence, C08/C114 merchant-proof repairs, C18/r2 missing reviews and Decision 001 hold, and case-specific Finance allocation remain open. Zero cases become paid or financially closed solely from that response.
5. **Partial response is bounded:** Supply only one of multiple missing facts. Show exactly which central fact/link/local check changed, retain all unsatisfied requirements and owners, and preserve before/after batch history. Identical redelivery adds no second obligation or monetary effect; a conflicting response remains visible and cannot overwrite the accepted basis.
6. **Grouping does not manufacture dependencies:** C08/COST-08 and C114/COST-114-2 remain separate proof repairs despite sharing `merchant_payment` as a code. Owner-first filtering, similar amounts, or a common batch does not merge unrelated facts. A COST-24-only defect does not reach C03 without another proven path.
7. **Freshness and cancellation remain exact:** Correction invalidates dependent old reviews even with unchanged totals. TC018 remains scoped to T18/r1, not T18B/r1. C18 original-request settlement and missing r2 reviews remain independently visible; resolving a central cancellation/package blocker is not a Finance resolution or current review.
8. **History and financial invariants survive:** Owner handoff, blocker split/merge, supersession, and recheck retain predecessor identities and evidence. Preserve all 18 normalization diagnostics as history. With unchanged Finance inputs, retain 104 request facts, 219 admitted events, and 1,203,415 admitted net cents; the original 703-open-item register remains unchanged. New outputs bind this decision in a new versioned directory, preserving earlier hashes and snapshots.

## Documentation boundary and preservation

Only this decision document is created. No repair is resolved, no stakeholder reply invented, no workflow implemented, and no artifact regenerated. Tests were not run for this documentation-only assessment; the criteria above are prospective requirements, not passing results. No network access, commit, or push is performed.

Preserved earlier-decision SHA-256 values:

```text
Decision 001: acb1e7dd37e118e07f25e1c017418f05213f1ed9461bf0020c0bf5f500fc1c8d
Decision 002: 33e9ca83e01299e6d4ba5d9f86685b991291c2bf89773970865a038904ec22a2
```

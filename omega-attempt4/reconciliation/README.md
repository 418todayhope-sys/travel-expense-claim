# Scope A increment 4 — Finance admission and reconciliation

This module performs deterministic **offline replay** of the retained acquisition,
normalization and policy-validation evidence. It records supplied Finance facts;
admission is not discretionary approval, payment readiness or financial closure.
It creates only versioned reconciliation JSON, with all deliveries, event/request
identities, amounts, candidate lineage, source references and owned unresolved
items. No requests are sent and no real transfers occur.

## Run and verify

Use the same Python 3.10+ / `pypdf==6.20.1` environment as normalization and
validation. No additional dependencies or network access are needed. From the
repository root:

```sh
/home/maxg/travel-expense-claim/.venv/bin/python -B -m unittest discover -s tests -v
/home/maxg/travel-expense-claim/.venv/bin/python -B -m reconciliation.reconcile --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated artifacts/validations/omega4-attempt002-policy-validation-v1 --through-batch 4 --output artifacts/reconciliations/omega4-attempt002-finance-reconciliation-v1
```

The command writes `reconciliation.v1.json` into a new directory. Existing
directories and destinations inside the three retained evidence directories are
refused before processing. Prior evidence is never rewritten. Choose a different
directory for another replay. Exit 0 means no unresolved work, 2 means the artifact
was retained with unresolved work, and 1 means verification/local failure. The
present evidence returns 2. Preserve a partial directory after any write failure
and choose a new destination.

Before admission, verification rechecks acquisition identities, source hashes and
lengths, supplemental policy/provenance, and the complete normalized records and
parsing report against an in-memory parse. It verifies every increment 3 input
binding, the full recomputed validation content, and its summary. Missing governing
bindings, corrupt records, changed code, or tampered summaries fail verification.
Output bindings include the verified validation artifact and reconciliation code.
The case clock remains November 15, 2026, Europe/Amsterdam, from preserved policy
line 11; machine time does not affect execution.

## Admission and replay

All deliveries visible at the selected arrival horizon retain their normalized
values, decoded raw cells and source locators. Finance event IDs form a separate
namespace from business cancellation activity IDs. Immutable Finance payloads
compare all decoded raw fields and normalized values except arrival batch.

An exact redelivery has no additional monetary or commitment effect. A later
conflicting payload cannot replace the earlier admitted event or erase its money;
all affected requests are held and exact net becomes unresolved. Conflicting
payloads that first arrive together are not arbitrarily selected. Missing IDs,
invalid arrival labels and rejected/unmatched events remain visible.

Admission checks supplied event type, immutable ID, original request/claim,
directory Finance actor/payee, EUR currency, UTC business time, reason and event
shape. Settlements/refunds must already be positive integer cents: Finance events
are never rounded. Accepted, adjustment and resolution targets must be known
nonnegative integer cents. Status events with blank amounts have no monetary
effect; blanks do not become confirmed zero payments.

Events are consumed by arrival batch. Business time and reference dependencies
order effects within each batch; source row order is not authority. Missing
acceptance/original-transfer references are retried when evidence arrives.
Earlier batch views remain unchanged when a later batch resolves a reference.
Accepted-target effects use business chronology, so a late earlier adjustment
does not revive a subsequently cancelled request. Equal-time conflicting targets
remain unresolved. No new acceptance ID can create a duplicate commitment for
the same request.

A refund needs an admitted settled original transfer on the same request, claim,
payee and currency; it must occur later and cannot exceed that transfer's
unrecovered amount. Promises and request/status events never reduce net paid.
Competing equal-time refunds exceeding the original transfer are all held rather
than selected by identifier spelling. Failed attempts have no monetary effect;
retry authority remains distinct. A reported settled transfer is retained even
when retry authority is missing, with a hold identifying that authorization gap.

Finance cancellation releases the accepted request target to zero while retaining
the original accepted amount and every transfer/refund. This is request accounting,
not zero employee entitlement. A late transfer is still admitted to the original
request and creates a Finance reconciliation issue. A resolution records Finance's
supplied request-level target; it does not itself change a commitment. Its target,
current accepted target and known net must agree. Later-observed money reopens
the assessment even if a previous resolution exists.

## Amount and attribution semantics

Claims and every expense occurrence retain gross original-currency amounts,
base caps/allowed amounts from validation, policy-allowed amounts, and eligibility
status. Converted gross and policy arithmetic use line rounding already specified
by policy. Request amounts are separate:

- `original_accepted_cents`: immutable first accepted amount.
- `accepted_cents`: current request target after admitted adjustment/cancellation.
- `admitted_settled_cents`, `admitted_refund_cents`, `admitted_net_cents`: the exact
  sum of admitted retained facts, counting each business event once.
- `net_confirmed_settled_cents`: known request-level net when settlement evidence
  exists and no delivery uncertainty remains; otherwise null. Admitted subtotals
  remain visible when exact net is unknown.
- `accepted_minus_net_cents`: a request-level comparison, not a current authorized
  claim balance. A negative value requires Finance attention.

Finance explicitly supplies request and claim references, but **no claim-revision
or expense columns**. The validator retains candidates as of original acceptance,
including the available revisions, current candidate trip/costs, and supplied
reviews available by the acceptance's business instant. These are transparent
derived candidates, not certified attribution. Revision/expense accepted and net
amounts remain null, and no payment authority is inferred from equal amounts.

C03/C24's same employee/trip/cost/receipt/currency/gross identity links the repeated
purchase. If the earlier candidate bundle is fully settled, a conditional excluded
amount and incremental policy calculation are shown. Partial settlements are
never allocated among costs by guess. The conditional calculation does not create
a new obligation or authorize payment: explicit request/cost allocation remains
an owned unresolved item.

## Freshness, cancellation and Decision 001

Policy validation is recomputed for each selected batch and at original acceptance
with later business-time reviews/cancellations filtered out. Original acceptance
does not turn a historical approval into current authority. Current role decisions,
packet identity, cancellation context and all increment 3 evidence gaps still
govern further payment readiness. The artifact retains the 18 normalization
diagnostics and current policy/review diagnostics.

Decision 001 creates a blocked hold when a correction follows an already observed
original acceptance. It requires Finance resolution of the original-request
consequences and valid current reviews. A request-only resolution does not prove
its scope covers the current revision/cost/cancellation. C18/r2 remains blocked;
its original EUR 100 late transfer is not attributed to COST-18B. C19's request-level
EUR 80 agreement and supplied resolution remain separate from current claim
authorization.

C09's first acceptance is in its corrected revision's arrival batch, so no earlier
accepted original request is invented. C121's permit-only business cancellation
precedes its first observed acceptance; it does not automatically require a
separate post-acceptance Finance resolution. Its trip remains active and its permit
retired. Cancellation confirmation on T18 never targets T18B. All four business
processes remain separate, including TC122 with no observed claim/request. Business
cancellation itself changes no Finance money or accepted commitment.

## Limits and handoff

The artifact is partial. Finance owns uncertain request/revision/cost allocation,
missing or conflicting events, refunds and resolution scope. Reviewers own valid
current decisions and missing packet amount/exception evidence. The facilitator
owns the undefined independent `DW-D-2` binding and native source completeness.
The preserved browser policy's provenance limitations remain applicable; there is
no fresh-source acquisition claim or independent bank completeness assertion.

All factual amounts can be reconciled at request level without certifying that
the corresponding claim was authorized. Inherited unknown categories, missing
merchant payment proof, missing rates/caps and reviewed-entitlement/exception
packet fields are never waived by Finance acceptance or equal net amounts.
The historical assignment-access limitation remains visible in validation.

No new payment-ready state, request draft, final `claims.csv`, `report.md`, Skill,
submission output, financial closure or public snapshot-schema state is emitted.
`batch_views` are internal replay evidence, not final submission snapshots. Keep
this stage separate from later authority repair, closure and delivery increments.

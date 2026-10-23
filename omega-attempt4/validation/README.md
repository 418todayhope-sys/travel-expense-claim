# Scope A increment 3 — deterministic policy and approval validation

This stage reads verified normalized records and produces reusable findings for
each observed claim/revision, expense occurrence, review import and business
cancellation process. It consumes synthetic human decisions; it does not make
them. It is an **offline replay**, not a fresh acquisition or an operations report.

Use Python 3.10+ with the increment 2 `pypdf==6.20.1` environment. No additional
dependencies or network access are needed. From the repository root:

```sh
/home/maxg/travel-expense-claim/.venv/bin/python -B -m unittest discover -s tests -v
/home/maxg/travel-expense-claim/.venv/bin/python -B -m validation.validate --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --through-batch 4 --output artifacts/validations/omega4-attempt002-policy-validation-v1
```

The second command creates `findings.v1.json` once. Choose a new output directory
for another execution. Existing directories are refused before input processing;
neither acquisition nor normalization is written. Exit 0 means no outstanding
findings, 2 means findings retained with blocked/unresolved work, and 1 means a
verification/local failure. The present evidence returns 2. A write failure may
leave a partial new directory; preserve it and select another directory.

## Governing evidence and verification

The validator rechecks fixed acquisition identities, every retained response and
source hash/length, and supplemental policy/provenance. It rebuilds normalization
in memory and compares the complete document and JSON report to the saved
evidence, including the report's records hash. The local browser copy and its
provenance must exactly match the retained supplement. No normalized outputs are
regenerated on disk. Output input bindings include governing documents and code.

Policy rules cite physical lines in the preserved October 20 POL-2026.2 copy,
whose SHA-256 is `04d8121a91986dc0839094b5e7f574c44f6261c60c1c3ba9aeeee1c279ee5993`.
The original October 20 stakeholder export and Decision 001 remain unchanged.
The case date is November 15, 2026, Europe/Amsterdam, from policy line 11; computer
time never changes it. UTC event timestamps are converted to local dates only
when comparing with date-only commitments/payments. Same-day ordering remains
unresolved where exact ordering matters.

The live original assignment link in the root README was inaccessible during
implementation. [The preserved assignment text](references/assignment-captured-20261016.txt)
is an exact copy of the historical file at
`/home/maxg/travel-expense-claim/artifacts/verification/project-d-stage7-coverage-c2bee74-20261016/assignment-from-captured-prompt.txt`.
It was read with the current repository README and snapshot schema. Its provenance
is a historical captured prompt, not freshly verified Notion content; no code or
old implementation was copied from that project. This remains an explicit global
unresolved finding. Full Skill/batch-snapshot/queue/reconciliation deliverables
belong to subsequent increments, under the user's explicit scope restriction.

## Finding semantics

`supported` means the stated rule is established by the referenced evidence.
`blocked` means an observed rule failure, supplied return/rejection, or an explicit
hold. `unresolved` means missing, ambiguous or unverifiable evidence/definitions.
Every finding records a rule, reason, owner, source references and required repair.
The source index resolves record IDs to source hashes and PDF pages or workbook
sheet/rows. Rule references resolve to policy lines. The original 18 normalization
diagnostics are preserved globally and attached to their claim revisions.

Gross purchase, base capped amount, explicit replacement allowed amount and
converted cents are separate fields. Unknown paid evidence, category, cap or FX
never becomes zero. Personal purchases have known zero entitlement. Monetary
outputs in EUR are integer cents; original-currency decimals remain strings.
Each converted line is rounded decimal half-up before summing. Calculated totals
are gross policy calculations, **not authorized or incrementally payable amounts**.
Shared costs such as C03/C24 retain both occurrences and an owned unresolved
prior-obligation link; exclusion requires the deferred Finance stage.

`eligibility_status` aggregates expense eligibility and identity/date checks.
`approval_status` covers supplied current role responses and packet limitations.
Overall claim `status` also includes historical arrangement failures and original
request holds. `current_at_batch` distinguishes current from historical revisions.
All revisions are rechecked against the selected batch's visible facts; these are
not execution-time snapshots of earlier batches. Global unresolved findings apply
even where individual eligibility or role checks are supported.

Corrections use a full dependency recheck, allowed by policy line 23 and the
stakeholder interview. No claim review is inherited from another revision, even
when totals match. Exact claim and permit subjects/revisions are independent.
Packets must match employee, trip/permit revisions, expense IDs, policy and business
context. Role authority comes from the employee's directory row. Only the joint
budget-owner/supervisor response may cover two roles. Director thresholds use
strictly more than EUR 1,000: trip estimate for permit, calculated entitlement for
claim. Missing entitlement leaves the director requirement unresolved.

Visible valid replies are ordered by business decision time for each role; an
equal-time ambiguity is held. Returns require a concrete repair request; rejects
retain their reason. Invalid, stale and wrong-role imports remain visible and
satisfy no required role. Rejection here does not close a claim or erase money.

Cancellation deliveries are checked for immutable payload conflicts, unique
initiation/confirmation, exact trip/permit targets, directory employee/supervisor
authority, arrival visibility, strictly later confirmation, and own-time effect.
All four observed processes, including no-claim TC122, remain separate. A permit
cancellation leaves its trip active; an old trip cancellation does not affect a
replacement trip. Timely historical permission is retained after cancellation.
Spent costs need an exact `travel_cancellation` Finance exception plus fresh,
post-confirmation cancellation-aware packets. An amount-only exception does not
cover it. Exceptions never approve arrangements or supply payment evidence.

The supplied Budget ledger context subtracts net settled expenditure and only the
unsettled portion of commitments, avoiding double subtraction. Packets must name
the entire supplied department/project/period ledger. Accepted new Finance
requests remain outside this calculation, so budget completeness is unresolved.
Adequate funds do not substitute for a budget-owner response.

## Unresolved definitions and limits

- Native policy completeness and native business-source semantic versions are not
  certified by acquisition. The browser copy remains supplemental.
- `DW-D-2` is an opaque supplied decision-package version. `POL-2026.2` and the
  printed `SRC-D-3` are checked; the independent meaning/binding of `DW-D-2` needs
  the facilitator. No new version meaning is invented.
- Claim packets lack reviewed-entitlement and exception-reference fields. Their
  subject/evidence/role checks can pass, but arithmetic and exception visibility
  to reviewers cannot be independently established. Every claim review retains
  that unresolved finding rather than inferring approval of a calculated number.
- Full budget completeness requires accepted-request admission, deferred here.
  No additional funding threshold or budget approval is invented.
- Unknown categories (including `entertainment`) and missing caps/rates stay
  unresolved. No unsupported policy default is introduced.
- Merchant, receipt, trip, directory, cap and FX tables have no arrival batches.
  They are treated as retained base tables. Claims, decisions, Finance candidates
  and cancellation deliveries are filtered by the selected batch.
- Decision 001 is represented as an original-request hold on corrected claims
  with Finance candidates. Those rows are references only; no event is admitted,
  attributed to an expense/revision, or taken as a validated resolution. Thus C18
  remains blocked; C19's observed resolution cannot clear the deferred check.
- No Finance event admission, payment request, transfer, net-paid/balance,
  financial closure, final report or public snapshot-schema state is emitted.

These definitions/evidence gaps require the indicated humans or later validation
stage. A successful test run establishes implemented checks, not policy validity,
source completeness or financial completion of the exercise.

# Business dispositions and financial holds

The current interim result is
[the business-disposition shared-blocker report](../artifacts/runs/omega4-attempt002-business-disposition-shared-blockers-v1/report.md),
with [case views](../artifacts/runs/omega4-attempt002-business-disposition-shared-blockers-v1/cases.md)
and [the unchanged-column CSV](../artifacts/runs/omega4-attempt002-business-disposition-shared-blockers-v1/claims.csv).
Decisions 001–004 remain binding and unchanged. This correction supplies no new
stakeholder answer, review, Finance authority, payment or financial closure.

`business_disposition` accompanies each claim/revision through validation,
reconciliation, snapshots and case views. Its value is `withdrawn`, `rejected`,
or null (unresolved). It contains an explicit reason, exact normalized source
references, admitted decision IDs and scope. Snapshot/source indexes resolve
references to retained source hashes and pages or workbook rows. C13/r1's binder
page 13 records withdrawal; C14/r1's admitted budget-owner decision and matching
packet at workbook row 40 record rejection. No later retained revision reverses
either. These are current within retained evidence, not independently verified
external completeness. The October 20 policy copy, lines 22–26, separates such
business evidence from financial closure.

Withdrawal requires an explicit revision-specific source status and reason.
Rejection requires existing current-subject/revision, actor/role, source-version
and packet admission, followed by unambiguous current role selection. Conflicting
business evidence remains unresolved. A new revision does not inherit an old
withdrawal/rejection. Missing reviews or Finance events supply no disposition.
A generic submitted status is not converted into approval or a terminal result.

Financial `status` stays `held` in snapshots and CSV. CSV reasons and reports show
supported dispositions separately. Missing merchant proof, reviews, Finance
allocation and Decision 001 holds stay visible, with the same repair IDs/history
and owners. Gross/policy arithmetic is unchanged, unknown money stays unknown,
and neither rejection nor withdrawal is proof of a zero financial effect.

## Current verification and replay

From the repository root, select a locally provisioned Python 3.10+ interpreter
as `OPERATOR_PYTHON`, with `operator_delivery/requirements.txt` and its transitive
dependencies installed. No downloads or network are needed. See
[offline environment instructions](shared-blockers.md#offline-python-environment).
Current outputs bind current code/schema/documentation and verify directly:

```sh
"$OPERATOR_PYTHON" -B -m unittest discover -s tests -v
"$OPERATOR_PYTHON" -B -m operator_delivery.build verify artifacts/runs/omega4-attempt002-business-disposition-operator-v1
"$OPERATOR_PYTHON" -B -m operator_delivery.build verify artifacts/runs/omega4-attempt002-business-disposition-containment-v1
"$OPERATOR_PYTHON" -B -m operator_delivery.shared_blockers verify artifacts/runs/omega4-attempt002-business-disposition-shared-blockers-v1
```

For a new replay, choose a fresh external temporary directory. Never reuse a
sealed artifact path. Run these commands sequentially: build exit 2 means a
successfully retained partial result with unresolved work, not a failure to write;
exit 1 means failure. Verification exit 0 certifies implemented checks only.

```sh
DISPOSITION_REPLAY=$(mktemp -d)
"$OPERATOR_PYTHON" -B -m validation.validate --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --output "$DISPOSITION_REPLAY/validation"
"$OPERATOR_PYTHON" -B -m reconciliation.reconcile --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated "$DISPOSITION_REPLAY/validation" --output "$DISPOSITION_REPLAY/reconciliation"
"$OPERATOR_PYTHON" -B -m operator_delivery.build build --acquisition artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated "$DISPOSITION_REPLAY/validation" --reconciled "$DISPOSITION_REPLAY/reconciliation" --output "$DISPOSITION_REPLAY/containment" --run-id disposition-replay --dependency-containment --prior-operator artifacts/runs/omega4-attempt002-containment-v2
"$OPERATOR_PYTHON" -B -m operator_delivery.shared_blockers build --source-run "$DISPOSITION_REPLAY/containment" --output "$DISPOSITION_REPLAY/shared-blockers" --run-id disposition-shared-replay
"$OPERATOR_PYTHON" -B -m operator_delivery.shared_blockers verify "$DISPOSITION_REPLAY/shared-blockers"
```

Prior runs remain immutable, with their original snapshot links and hashes.
Their historical code/schema/documentation bindings differ from current ones;
restoring old documentation alone is insufficient to execute historical replay.
Use matching historical implementation versions for semantic verification.
New containment output retains the preceding containment repair register and
manifest byte-for-byte as historical evidence. New runs replay all four arrival
boundaries; they do not append a fictitious fifth delivery to an earlier chain.

Native Notion completeness, package definitions, packet entitlement evidence,
financial allocation and existing repairs remain unresolved. A successful local
verification is neither external operator acceptance nor financial completion.

# Selected ordinary closure within retained evidence

This correction implements the participant-authorized C01 audit outcome. It
does not change Decisions 001–004 or any historical source, snapshot or repair
record. It records an existing reimbursement, never a new payment instruction.

The policy browser copy at `user-provided-sources/20261020/`, lines 19–26,
requires current subject/revision/role approvals, reviewed entitlement and
matching admitted Finance facts. The original October 20 interview, lines
122, 294, 302 and 454, supports reconciling supplied request/payee facts and
confirming policy-calculated entitlement through current approvals. Neither
requires redundant entitlement fields in every packet or revision/cost columns
on every Finance event when the preserved relationship is unambiguous.

Validation's `--ordinary-claim ID` is an explicit selection, not permission to
approve that claim. The default remains unchanged. It admits only a single
unchanged domestic claim revision containing one uniquely owned purchase, no
exception or cancellation, supported eligibility, and exactly one valid current
response for each required role. Invalid, duplicate, conflicting, stale or
missing responses prevent this path. New evidence is always re-evaluated.

Reconciliation also requires one unique request, a matching positive accepted
obligation and one matching confirmed settlement, no uncertain events or
additional financial activity, and approvals predating acceptance. Exact
redeliveries count once. Budget references must match the supplied scoped ledger,
with adequate supplied funds and no earlier accepted request requiring dynamic
budget reconstruction. Corrections, shared/multiple costs, adjustments, refunds,
exceptions and unresolved original requests remain outside this narrow path;
matching totals cannot waive their Finance resolutions or Decision 001 holds.

The resulting evidence certificate identifies the claim/revision/cost/request,
source approvals, acceptance, settlement, money and exact source references.
`package_certification` remains `unresolved`. Native Notion completeness,
assignment/package definitions and other global requirements remain visible in
the package repair queue; no external completeness or grading claim is made.
The ordinary operator projection is deliberately not enabled for containment
or shared-blocker builds. Their historical runs remain preserved.

## Reproduce in new directories

Use a locally provisioned Python with `operator_delivery/requirements.txt`,
selected as `OPERATOR_PYTHON`. The following paths identify the new correction
run. Every builder refuses an existing destination; use new IDs for a replay.

```sh
"$OPERATOR_PYTHON" -B -m validation.validate --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --output artifacts/validations/omega4-attempt002-ordinary-closure-validation-v1 --ordinary-claim C01
"$OPERATOR_PYTHON" -B -m reconciliation.reconcile --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated artifacts/validations/omega4-attempt002-ordinary-closure-validation-v1 --output artifacts/reconciliations/omega4-attempt002-ordinary-closure-reconciliation-v1
"$OPERATOR_PYTHON" -B -m operator_delivery.build build --acquisition artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated artifacts/validations/omega4-attempt002-ordinary-closure-validation-v1 --reconciled artifacts/reconciliations/omega4-attempt002-ordinary-closure-reconciliation-v1 --output artifacts/runs/omega4-attempt002-ordinary-closure-operator-v1 --run-id omega4-attempt002-ordinary-closure-operator-v1
```

Processing still exits 2 for the partial package. Exit 2 is not permission to
skip verification. Verify the existing correction output without rebuilding:

```sh
"$OPERATOR_PYTHON" -B -m operator_delivery.build verify artifacts/runs/omega4-attempt002-ordinary-closure-operator-v1
"$OPERATOR_PYTHON" -B -m unittest discover -s tests -p test_ordinary_closure.py -v
```

C01 remains held before its batch-2 settlement. From batch 2, the retained
ordinary evidence supports `closed-reimbursed`, 10,000 cents allowed/accepted/
net settled, zero balance and zero additional payment. All unselected claims
remain held. CSV columns are unchanged. Original repair registers remain
untouched; the new run records its own evidence rechecks and queue history.

Historical manifests bind the earlier code/documentation. Their verification
must use the corresponding historical checkout or the documented isolated
binding procedure; never patch their hashes to accept current code.

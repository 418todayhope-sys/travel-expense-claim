# Ordinary-closure v3 — retained operator handoff and verification

This is the authoritative **selected ordinary-closure v3** handoff. The new selection is exactly C01, C04, C05 and C06, enabled with `--ordinary-v3`. It reuses the unchanged certificate. Earlier v1/v2 runs, source records, original interviews, Decisions 001–004 and their repair histories remain preserved. No new human approval, Finance resolution, payment instruction, external operator acceptance or grading result is created.

## Versioned outputs

* [Validation](../../validations/omega4-attempt002-ordinary-closure-validation-v3/findings.v1.json)
* [Reconciliation](../../reconciliations/omega4-attempt002-ordinary-closure-reconciliation-v3/reconciliation.v1.json)
* [Operator manifest](../../runs/omega4-attempt002-ordinary-closure-operator-v3/operator-manifest.v1.json), [four snapshots](../../runs/omega4-attempt002-ordinary-closure-operator-v3/batches/004.json), [claims.csv](../../runs/omega4-attempt002-ordinary-closure-operator-v3/claims.csv), [report](../../runs/omega4-attempt002-ordinary-closure-operator-v3/report.md) and [repair register](../../runs/omega4-attempt002-ordinary-closure-operator-v3/repair-queue.json)
* [Independent integrity/business comparison](verification.json), [standalone verification](standalone-verification.json) and [v2 repair crosswalk](repair-crosswalk.json)

The `v1` filenames inside v3 directories identify schema formats, not execution versions. Four snapshots and 22 bound operator files verify. There are 121 current claims: four `closed-reimbursed`, 117 held. Batch 1 has no closure; batches 2–4 close exactly the four selected claims.

| Claim/revision | Allowed = accepted = net confirmed settled | Request | Acceptance / settlement |
|---|---:|---|---|
| C01/r1 | 10,000 cents (€100.00) | REQ-C01 | F-C01-accepted / F-C01-1 |
| C04/r1 | 10,000 cents (€100.00) | REQ-C04 | F-C04-accepted / F-C04-1 |
| C05/r1 | 100,000 cents (€1,000.00) | REQ-C05 | F-C05-accepted / F-C05-1 |
| C06/r1 | 100,001 cents (€1,000.01) | REQ-C06 | F-C06-accepted / F-C06-1 |

The exact selected total is **220,001 cents (€2,200.01)**. All four balances and additional-payment authorizations are zero. C04 uses a valid combined budget-owner/supervisor response. C05's exact €1,000 requires no director; C06's €1,000.01 has the required DIR-01 approval. Supporting receipts/merchant payments predate approvals, which predate acceptance and settlement.

Claim/request, payee, monetary and event facts are explicit source records. Revision/cost attribution is a **derived unique current claim/purchase/request join**; Finance has no explicit claim-revision/cost columns. This result does not claim external bank completeness. Other claims' unknown attribution/payment amounts remain unknown, not zero. Request-ledger totals are not interchangeable with the selected closure total. Admitted Finance events/deliveries and all other claim findings are unchanged versus v2.

## Guards, negative controls and unresolved work

The certificate, reconciliation logic and non-CLI validation functions are unchanged from staged v2. Receipt/payment matching, freshness, exact authority, director threshold, current revision/cost uniqueness, valid arrival handling, duplicate/conflicting deliveries, refund/resolution requirements, cancellation scope and Decision 001 remain enforced. The preset is mutually exclusive with individual `--ordinary-claim` selections; it does not generalize to other claims. No selection remains the conservative default.

C08 remains held: missing matching settled merchant-payment proof, current reviews and Finance request evidence. C18/r2 remains held: missing current reviews, corrected replacement trip/cost, and the original cancelled request's late €100 payment require Finance resolution. That payment cannot be assigned to COST-18B by equal totals. TC018 targets T18/r1, not replacement T18B/r1. The original 18 normalization diagnostics remain visible, including C18/r2's absent review rows.

The four package requirements remain unresolved: policy provenance/native completeness, review-version token definition, budget completeness and assignment access. Date-only evidence cannot prove intraday availability or reveal undated silent changes. Financial closure here is recognition within retained evidence, not external operational certification. Ordinary closure remains disabled for containment/shared-blocker builds.

The v3 register contains **964** records: **683 open, 230 cleared by recheck, 51 superseded**. All v2 repair IDs/history remain in the unchanged v2 register. Common records retain stable identities. Six v2 approval/entitlement repair records for C04–C06 are not emitted in the new run because selection supports those facts from their first evaluated batch. The [970-record crosswalk](repair-crosswalk.json) preserves exact historical references; it does not invent retroactive clearance events. The new register is not a merged replacement for all earlier histories.

## Genuine targeted-test evidence

`step2/` preserves the original completed temporary execution byte-for-byte:

* `existing-tests.log` and `existing-tests.json`: **39/39 existing regressions passed**.
* `supplemental-tests.log` and `supplemental-tests.json`: **49/49 supplemental checks passed**.
* `execution.log`, `commands.json`, `operator-verification.json`, `closure-results.json`, `before.json`, `after.json` and `preservation.json`: original commands/results and preservation of 402 files, the 93-file staged v2 index and unstaged v3 edit.
* `original-runner.py`: exact executed harness, retaining historical checkout and temporary-allowlist locators. It is execution evidence, not a portable post-commit test entry point; it intentionally asserts the original staged-v2/unstaged-v3 state. No mock/human approval is promoted into scenario evidence.

Checks cover each selected claim independently, exact duplicates, valid/invalid-batch conflicts, refunds, post-approval evidence, late approvals, corrections, cancellations, missing merchant proof, the director threshold, wrong/missing director authority, C08/C18 and no other closure. Synthetic mutations were isolated in memory and never changed retained source facts. The 88 tests were **not rerun during packaging**. This step independently rebuilt and verified the exact selection in new canonical directories and compared its business state against that tested execution.

`copied-evidence-provenance.json` binds original temporary locators to copied bytes. These paths are provenance, not dependencies for verifying the new v3 outputs. `approved-v2-staged-hashes.json` preserves the reviewed index inventory. `v2-inputs/validate.py` preserves the exact staged v2 validator that earlier manifests bind. Do not alter older manifests to accept the unstaged v3 validator.

## Operator commands

Run from the repository root with a locally provisioned `OPERATOR_PYTHON` matching `operator_delivery/requirements.txt`. No installation, downloads or fresh network acquisition are part of this offline procedure.

Verify existing outputs without writing them:

```sh
"$OPERATOR_PYTHON" -B -m operator_delivery.build verify artifacts/runs/omega4-attempt002-ordinary-closure-operator-v3
"$OPERATOR_PYTHON" -B artifacts/verifications/omega4-attempt002-ordinary-closure-verification-v3/verify-package.py
```

For a **new labelled offline replay**, allocate a fresh destination; never reuse the existing v3 directories:

```sh
OMEGA_V3_REPLAY_DIR=$(mktemp -d "${TMPDIR:-/tmp}/omega4-v3-replay.XXXXXX")
"$OPERATOR_PYTHON" -B -m validation.validate --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --output "$OMEGA_V3_REPLAY_DIR/validation" --ordinary-v3
"$OPERATOR_PYTHON" -B -m reconciliation.reconcile --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated "$OMEGA_V3_REPLAY_DIR/validation" --output "$OMEGA_V3_REPLAY_DIR/reconciliation"
"$OPERATOR_PYTHON" -B -m operator_delivery.build build --acquisition artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated "$OMEGA_V3_REPLAY_DIR/validation" --reconciled "$OMEGA_V3_REPLAY_DIR/reconciliation" --output "$OMEGA_V3_REPLAY_DIR/operator" --run-id omega4-v3-offline-replay
"$OPERATOR_PYTHON" -B -m operator_delivery.build verify "$OMEGA_V3_REPLAY_DIR/operator"
```

All three build commands return **2** for the retained partial package; verify returns **0**. Record each result rather than chaining with `&&` or treating partial exit 2 as data loss. On actual failure preserve the partial output, inspect its error and select a new destination. Never weaken bindings, overwrite a seal or invent missing evidence. This is offline replay, not a fresh native-source attempt. For new authorized deliveries use a fresh acquisition and preserve all five attempted sources and source changes before evaluation; the preset cannot supply missing facts or authority.

The 39 existing tests can be rerun with:

```sh
"$OPERATOR_PYTHON" -B -m unittest discover -s tests -p 'test_ordinary_closure*.py' -v
```

Full-suite adaptation and the original 192-test v2 result are documented in the separately preserved v2 full-regression package. No new full-suite or relocated clean-environment execution is claimed here.

## Historical wording and preservation

Earlier root README, Skill and v2 handoff links remain historical. The generated v3 `report.md:3` inherits the generator's blanket denial of financial closure; its precise selected-closure count and the table above govern this retained-evidence interpretation. The header was not edited or resealed. See the [v2 addendum](../../../operator_delivery/ordinary-closure-v2-handoff.md) for the earlier wording audit. This README supplies the current v3 route without changing hash-bound documentation.

`packaging-preservation.json` reports before/after file hashes, staged inventory hash, unchanged index/HEAD/refs and the unchanged unstaged selection edit. Native source copies and original acquisition manifest match the retained acquisition bytes. No peer interview interpretations, credentials, environments, Entire transcripts or synthetic checkpoints are added. Ordinary local/temporary path locators remain in genuine historical logs; they are not access credentials. No staging, commit, push, publication, deployment or submission is performed by this packaging step.

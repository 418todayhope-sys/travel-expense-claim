# Ordinary-closure safeguards v2

Only two safeguards were added to the selected ordinary-closure path:

* Malformed Finance arrivals remain unresolved. Explicit claim, request, event and original-payment references identify affected cases; no amount or identifier-spelling join is used. They cannot yield closure certificates. Linked cases receive owned Finance work, while unrelated cases continue independently. Unattributable deliveries remain package-level unresolved evidence.
* Receipt issue dates and merchant-payment dates must precede or share the applicable review date, using the existing case timezone. Earlier otherwise-valid approvals remain visible as stale imports. Every required role needs a valid subsequent response and matching packet before Finance acceptance. Later reviews cannot retroactively authorize acceptance. Other invalid or conflicting replies still fail closed.

Policy support: `user-provided-sources/20261020/POL-2026.2-20261020-browser-copy.txt:23` (evidence changes invalidate dependent reviews), lines 25–27 (conflicting Finance evidence and affected-claim holds); `interviews/project-d-travel-expense-claim-20261020-1419(1).md:430` (dependent re-review after evidence changes). Decisions 001–004 are unchanged.

Validation, reconciliation and operator outputs use their existing names ending in `v2`, parallel to the preserved ordinary-closure `v1` directories. Operator output: `artifacts/runs/omega4-attempt002-ordinary-closure-operator-v2`. No prior destination was reused. The selected claim remains C01; containment/shared-blocker outputs are not regenerated or relaxed.

Run from the repository root using a locally provisioned Python matching `operator_delivery/requirements.txt` (no download needed for this check):

```sh
"$OPERATOR_PYTHON" -B -m unittest discover -s tests -p 'test_ordinary_closure*.py' -v
"$OPERATOR_PYTHON" -B -m operator_delivery.build verify artifacts/runs/omega4-attempt002-ordinary-closure-operator-v2
"$OPERATOR_PYTHON" -B artifacts/verifications/omega4-attempt002-ordinary-closure-safeguards-v2/verify-preservation.py
```

39 targeted tests pass, including the original €100 C01 closure, malformed/valid-batch conflicts, explicit dependency links, unrelated-case controls, later supporting evidence, complete/partial subsequent reviews and reviews after acceptance. The original isolated reproduction now reports both unsafe closures NOT REPRODUCED; its baseline and other controls pass. Synthetic test fixtures are never authentic source evidence.

All 345 pre-existing eligible files were checked: 343 unchanged; only `validation/validate.py` and `reconciliation/reconcile.py` changed in this task. Their exact prior bytes are archived under `prior-inputs/`, matching `preservation-baseline.json`. Earlier manifests remain unchanged and bind their original inputs; verifying them requires those original code bytes, rather than changing manifest hashes.

Retained reconciliation claim/request/event facts and totals are identical to v1; claims.csv is identical. All 970 repair identities/history are unchanged except the new run identifier; 698 remain open. Four snapshots verify, with 121 current claims: C01 closed-reimbursed for 10,000 cents, 120 held. All 18 normalization diagnostics remain visible. No new payment is authorized.

Limitations: native policy completeness remains unknown. Date-only evidence cannot establish intraday availability or reveal undated silent changes. An unlinked malformed delivery is not attributed by guesswork. The broader suite's historical input-hash fixture limitation is outside this change; only targeted tests were run. Existing operator report wording about financial closure was not revised by this narrowly scoped task.

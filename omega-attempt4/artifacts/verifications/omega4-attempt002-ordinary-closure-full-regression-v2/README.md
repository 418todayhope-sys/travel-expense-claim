# Preserved full regression — ordinary-closure v2

This package preserves the already completed 192-test run. It does not claim that packaging reran the full suite. Originals were copied byte-for-byte from the completed local temporary run; `manifest.json` records source locators and SHA-256 hashes. Temporary paths are historical provenance, not runtime dependencies.

## Preserved evidence

* `full-regression.log`: complete original stdout/stderr, including individual test outcomes, final counts and checks.
* `tests.json`: 192 passed, zero failures/errors/skips.
* `preservation.json`: 388 eligible files, Git status/index/HEAD/refs unchanged during the original run; 1,313.258 seconds total including fixture setup/final checks. Tests alone took 1,176.998 seconds.
* `before.json`, `after.json`: original full file/hash inventories and Git-state records; retained unchanged.
* `fixture-verification.json`: the fresh conservative-default containment fixture verified four snapshots, 28 files, 121 held claims, zero closures and 582 open repairs.
* `closure-verification.json`: the separately verified selected v2 output had four snapshots, 22 files, one C01 closure for 10,000 cents with zero balance, 120 other claims held and unchanged versus v1, and 698 open repairs.
* `original-runner.py`: exact executed temporary runner, including its original checkout locator. It is historical evidence; use `replay.py` for a relocated checkout.
* `packaging-baseline.json`, `packaging-verification.json`: this later packaging task's separate preservation inventory and findings. They are not records from the earlier test execution.

## Why temporary fixture adaptation was necessary

Historical tests default to validation/reconciliation/containment artifacts whose manifests bind earlier code. Current code must not be accepted against those mismatching historical bindings. The original runner used the unchanged acquisition `artifacts/runs/omega4-live-20261020-attempt002` and normalization `artifacts/normalizations/omega4-attempt002-normalization-v1` to build new conservative-default validation, reconciliation and containment artifacts under a new system temporary directory. Production loaders verified retained hashes and deterministic parsing; the normal builder and standalone verifier checked the new artifacts.

Only these test-module fixture variables were redirected, in memory:

| Module | Variable | Fresh temporary fixture |
|---|---|---|
| `test_reconciliation` | `VALIDATED` | validation-default |
| `test_operator_delivery` | `VALIDATED`, `RECONCILED` | validation-default, reconciliation-default |
| `test_containment` | `V`, `R` | validation-default, reconciliation-default |
| `test_shared_blockers` | `SOURCE` | containment-default |

No validator, provenance check, assertion, test method, retained source or historical manifest was patched. The default containment fixture deliberately has no ordinary-claim opt-in. The separate ordinary-closure and v2 safeguard tests exercise selected C01 closure and adversarial cases. The runner discovers all `test_*.py` tests and blocks `socket.create_connection`; it makes no source/network acquisition. Temporary fixture files themselves are reproducible intermediates and are intentionally not copied here.

## Reproduce without original checkout or temporary paths

Use a Git checkout containing this package and all preserved inputs, with locally provisioned dependencies from `operator_delivery/requirements.txt`. Choose `OPERATOR_PYTHON`; no downloads or environment installation are part of this procedure. The repository should have a stable index/worktree during the run.

```sh
"$OPERATOR_PYTHON" -B artifacts/verifications/omega4-attempt002-ordinary-closure-full-regression-v2/replay.py --check-only
"$OPERATOR_PYTHON" -B artifacts/verifications/omega4-attempt002-ordinary-closure-full-regression-v2/replay.py
```

For another checkout, pass `--repository /path/to/checkout`. The wrapper checks the original runner hash and changes only its `ROOT=Path(...)` locator in memory before executing the same code. It never edits the preserved runner or business code. `--check-only` verifies configuration/compilation only, not test success. A real replay takes approximately 22 minutes and creates a fresh temporary directory printed as `TEMPORARY_EVIDENCE`. Save stdout/stderr in a new external log if desired; do not redirect over any packaged file. A checkout adds packaging files to the measured inventory, so later file counts/times need not equal the original 388/elapsed time.

The adapted suite passed; plain historical-default test discovery is not claimed to work against mismatched code hashes. Original tests use Git-state checks and expect `.git/index`, so this runner requires a normal checkout; linked-worktree `.git` pointer portability is not established. Dependency downloads, a fresh interpreter installation, external source completeness, external operator acceptance and grading were not demonstrated. The historical original run's Entire/Git refs may differ legitimately after a future authorized commit; comparisons are before/after within each replay.

## Privacy and preservation boundaries

The preserved evidence contains repository paths, temporary locators, Git hashes/refs, test identifiers and synthetic scenario claim/actor identifiers. The original runner includes the prior checkout username as provenance; the portable wrapper does not depend on that directory. No credential files, environments, Entire transcripts/capture metadata, interview copies or disposable fixture trees are added. Pattern scans and manual inspection found no secret values in the additions; this is not an exhaustive binary or public-checkpoint privacy audit. Historical evidence is not redacted or rebound.

Native policy completeness remains unknown. Date-only receipt/payment evidence cannot prove intraday availability. Claim closure recognizes retained existing reimbursement and does not authorize a new payment. All Decisions 001–004, other financial holds and package-wide unknowns remain unchanged. See [the standalone v2 handoff](../../../operator_delivery/ordinary-closure-v2-handoff.md) for authoritative paths and retained stale-wording warnings.

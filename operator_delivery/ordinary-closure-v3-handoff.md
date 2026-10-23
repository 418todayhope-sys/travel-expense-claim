# Selected ordinary-closure v3: navigation and replay addendum

This documentation-only addendum supplements the [authoritative sealed v3 verification README](../artifacts/verifications/omega4-attempt002-ordinary-closure-verification-v3/README.md). It corrects that README's replay example by supplying `--replay-of`; it does not modify or reseal any existing artifact. Older README, Skill and handoff descriptions remain historical. Decisions 001–004 and all certificate guards remain applicable.

The authoritative retained run is `artifacts/runs/omega4-attempt002-ordinary-closure-operator-v3`, with validation at `artifacts/validations/omega4-attempt002-ordinary-closure-validation-v3` and reconciliation at `artifacts/reconciliations/omega4-attempt002-ordinary-closure-reconciliation-v3`. Its final `batches/004.json` and verified CSV record exactly C01/r1 (€100.00), C04/r1 (€100.00), C05/r1 (€1,000.00) and C06/r1 (€1,000.01) as `closed-reimbursed`: **220001 cents** total, with **117 claims held**. C08 and C18 remain negative controls. These are selected closures under retained evidence, not package-wide certification, new payment authorization, independent grading improvement or external operator acceptance. Finance revision/cost joins are derived from unique relationships rather than explicit Finance revision/cost fields. Native-policy completeness and other documented unresolved requirements remain unknown.

The sealed operator `report.md`, **line 3**, says “No fresh acquisition, financial closure, external request or submission is asserted.” Its blanket financial-closure wording is stale. The final snapshot's four supported selected closures and the report's more specific line 5 describe the actual v3 result. Do not edit that report or its manifest to resolve this wording conflict.

## Prepare an isolated workspace

The root README and Skill were hash-bound inputs when the v3 outputs were sealed. Their new navigation links intentionally change their working-tree bytes. Direct sealed verification against those updated documents will therefore fail provenance checks. Never update a manifest or bypass a check. The two [preserved reference documents](ordinary-closure-v3-handoff-inputs/) retain their exact pre-navigation bytes outside the sealed 53-file inventory. Restore them **only in a temporary copy** for verification and replay.

Start at the repository root. Set `OPERATOR_PYTHON` to an **absolute path** to an already provisioned Python 3.10+ interpreter with the dependencies pinned in [requirements.txt](requirements.txt) and system Europe/Amsterdam time-zone data. Do not install or download dependencies as part of this offline procedure. The following preparation copies retained evidence without copying Git, Entire sessions, credentials, environments or caches. It writes only to a new temporary workspace and preserves the original checkout and index.

```sh
# Set OPERATOR_PYTHON to your locally provisioned absolute interpreter path first.
: "${OPERATOR_PYTHON:?Set an absolute path to the provisioned interpreter}"
OMEGA_V3_WORKSPACE=$(mktemp -d "${TMPDIR:-/tmp}/omega4-v3-handoff.XXXXXX")
export OMEGA_V3_WORKSPACE
"$OPERATOR_PYTHON" -B - <<'PY'
from pathlib import Path
import hashlib
import json
import os
import shutil

source = Path.cwd()
target = Path(os.environ['OMEGA_V3_WORKSPACE']) / 'repository'
shutil.copytree(source, target, ignore=shutil.ignore_patterns(
    '.git', '.entire', '.codex', '.agents', '.aws', '.ssh', '.venv', 'venv',
    '.env', '.env.*', '__pycache__', '*.pyc', '.pytest_cache', '.mypy_cache',
    '.ruff_cache', 'tmp'))
manifest = json.loads((target / 'artifacts/runs/omega4-attempt002-ordinary-closure-operator-v3/operator-manifest.v1.json').read_text())
expected = {item['path']: item['sha256'] for item in manifest['input_bindings']}
references = target / 'operator_delivery/ordinary-closure-v3-handoff-inputs'
for relative, preserved in (
    ('README.md', 'root-README.md'),
    ('skills/travel-expense-claim/SKILL.md', 'SKILL.md'),
):
    data = (references / preserved).read_bytes()
    assert hashlib.sha256(data).hexdigest() == expected[relative], relative
    (target / relative).write_bytes(data)
print(target)
PY
# Proceed only if preparation succeeds.
cd "$OMEGA_V3_WORKSPACE/repository"
```

## Verify the existing run without creating a replay

Run these in the isolated workspace prepared above. These commands read existing artifacts; they do not create a run. Both must exit **0**. The operator verifier checks four snapshots and 22 bound output files. The package verifier checks the sealed verification bindings as well.

```sh
"$OPERATOR_PYTHON" -B -m operator_delivery.build verify artifacts/runs/omega4-attempt002-ordinary-closure-operator-v3
"$OPERATOR_PYTHON" -B artifacts/verifications/omega4-attempt002-ordinary-closure-verification-v3/verify-package.py
```

## Create a new labelled offline replay

The following commands create three fresh sibling directories under the temporary workspace. They do not overwrite the copied sealed run or anything in the original repository. `--ordinary-v3` selects only C01/C04/C05/C06 using the existing certificate; `--replay-of` records the retained predecessor run and checks replay compatibility. Required CLI arguments were checked against the installed modules' `--help` and parser definitions.

```sh
"$OPERATOR_PYTHON" -B -m validation.validate --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --output "$OMEGA_V3_WORKSPACE/replay-validation" --ordinary-v3
"$OPERATOR_PYTHON" -B -m reconciliation.reconcile --run artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated "$OMEGA_V3_WORKSPACE/replay-validation" --output "$OMEGA_V3_WORKSPACE/replay-reconciliation"
"$OPERATOR_PYTHON" -B -m operator_delivery.build build --acquisition artifacts/runs/omega4-live-20261020-attempt002 --normalized artifacts/normalizations/omega4-attempt002-normalization-v1 --validated "$OMEGA_V3_WORKSPACE/replay-validation" --reconciled "$OMEGA_V3_WORKSPACE/replay-reconciliation" --output "$OMEGA_V3_WORKSPACE/replay-operator" --run-id omega4-v3-offline-replay --replay-of artifacts/runs/omega4-attempt002-ordinary-closure-operator-v3
"$OPERATOR_PYTHON" -B -m operator_delivery.build verify "$OMEGA_V3_WORKSPACE/replay-operator"
```

Each of the three build commands is expected to exit **2** because the package remains partial; verification must exit **0**. Inspect each result before proceeding. Do not use `set -e` or chain builds with `&&`, which would stop on the expected partial result. Any other build result requires investigation; retain failed outputs and choose a new workspace before retrying. Never reuse an existing output directory, weaken bindings, or infer missing approvals, payments or Finance resolutions.

Replay does not rerun the preserved 39+49 test checks or demonstrate fresh native source access. The genuine test logs remain in the sealed verification package; this addendum does not replace them, claim a new full regression, or establish external operator acceptance. Historical test-fixture adapters may retain their documented environment limitations. Successful local command validation establishes only reproducibility with locally available dependencies and retained evidence.

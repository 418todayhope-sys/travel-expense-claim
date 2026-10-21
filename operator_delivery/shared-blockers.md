# Decision 003: shared blockers and linked case views

This output layer consumes a **verified Decision 002 run**. It preserves the
input run, repairs, source bindings, financial states and money. Its new register
organizes facts; it does not supply approvals, payment evidence or Finance
allocation. Decisions 001–003 and original interviews remain unchanged.

## Find the current handoff

The latest run and matching commands are in [business-dispositions.md](business-dispositions.md).
The paths and documentation-restoration procedure below describe the preceding
shared-blockers-v1 handoff. After code/schema changes, restoring documentation
alone cannot verify that historical run: its matching historical code/schema
are also required. Preserve old artifacts and never bypass their bindings.

Open [the report](../artifacts/runs/omega4-attempt002-shared-blockers-v1/report.md),
[blockers](../artifacts/runs/omega4-attempt002-shared-blockers-v1/blockers.md),
[cases](../artifacts/runs/omega4-attempt002-shared-blockers-v1/cases.md), and
[repair register](../artifacts/runs/omega4-attempt002-shared-blockers-v1/repair-queue.json).
[Decision 004](../decisions/decision-004-interim-operator-handoff.md) accepts an
interim participant milestone only. There are 121 financially held current claims,
582 open repairs and zero claim closures. Local verification is not external
operator acceptance, assignment completion, grading or payment authorization.

## Offline Python environment

Run from the repository root. Python 3.10+ needs the two pinned packages in
`operator_delivery/requirements.txt`, their transitive dependencies, and system
time-zone data including Europe/Amsterdam. Use your own interpreter via
`OPERATOR_PYTHON`; no sibling checkout or fixed home-directory path is required.
If a compatible environment already exists, use its interpreter and skip the
bootstrap below. No network or dependency download is part of this procedure.

For a fresh local audit environment, first set `OFFLINE_SITE_PACKAGES` to a trusted
installed site-packages directory with the pinned packages and dependencies.
Copies must match the new interpreter's Python ABI and platform, especially the
compiled `rpds-py` package. This is an offline local-copy check, not an independent
wheel installation or a portable binary distribution. Missing local dependencies
stop the procedure; do not silently fetch them. The top-level requirements do not
lock every transitive version.

```sh
export HANDOFF_SOURCE_ROOT="$PWD"
export HANDOFF_AUDIT_DIR="$(mktemp -d /tmp/omega4-handoff-audit.XXXXXX)"
python3 -m venv --without-pip "$HANDOFF_AUDIT_DIR/venv"
export OPERATOR_PYTHON="$HANDOFF_AUDIT_DIR/venv/bin/python"
"$OPERATOR_PYTHON" -B - <<'PYENV'
import importlib.metadata as metadata
import os
from pathlib import Path
import shutil
import sysconfig
source = Path(os.environ["OFFLINE_SITE_PACKAGES"]).resolve()
target = Path(sysconfig.get_path("purelib"))
needed = {"pypdf", "jsonschema", "attrs", "jsonschema-specifications",
          "referencing", "rpds-py", "typing-extensions"}
found = {d.metadata["Name"].lower().replace("_", "-"): d
         for d in metadata.distributions(path=[str(source)])}
if not needed <= found.keys():
    raise SystemExit("Missing trusted local packages: " + str(sorted(needed - found.keys())))
for name in sorted(needed):
    for entry in found[name].files or []:
        origin = found[name].locate_file(entry).resolve()
        if origin.is_file() and origin.is_relative_to(source) and "__pycache__" not in origin.parts:
            destination = target / origin.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
PYENV
"$OPERATOR_PYTHON" -B - <<'PYCHECK'
from importlib.metadata import version
from jsonschema import FormatChecker
from zoneinfo import ZoneInfo
import pypdf, jsonschema, referencing, rpds
assert version("pypdf") == "6.20.1"
assert version("jsonschema") == "4.26.0"
assert str(ZoneInfo("Europe/Amsterdam")) == "Europe/Amsterdam"
print("Pinned packages and time zone available")
print("Schema date-time checker available:", "date-time" in FormatChecker().checkers)
PYCHECK
```

The audited local environment has no optional JSON Schema `date-time` checker.
Business validators check their own timestamps, but passing schema validation does
not certify every schema date-time format. Optional format support and other
platforms require separate dependency provisioning and verification.

## Restore bound documentation only in a temporary workspace

The historical manifests hash README/Skill instructions as inputs. Their archived
versions are in [bound-documentation.v1.json](bound-documentation.v1.json).
Updating these entry points therefore makes direct verification in the current
working tree fail its documentation hash checks. Do not change historical
manifests or disable checks. Copy the required repository files into a fresh
workspace and restore the four exact documented input versions **there only**:

```sh
"$OPERATOR_PYTHON" -B - <<'PYSTAGE'
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
source = Path(os.environ["HANDOFF_SOURCE_ROOT"]).resolve()
workspace = Path(os.environ["HANDOFF_AUDIT_DIR"]) / "workspace"
workspace.mkdir(exist_ok=False)
for name in ["README.md", "snapshot.schema.json", "acquisition", "normalization",
             "validation", "reconciliation", "operator_delivery", "skills", "tests",
             "decisions", "interviews", "user-provided-sources", "artifacts"]:
    origin, destination = source / name, workspace / name
    if origin.is_dir():
        shutil.copytree(origin, destination, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        shutil.copy2(origin, destination)
bundle = json.loads((source / "operator_delivery/bound-documentation.v1.json").read_bytes())
manifest = json.loads((workspace / bundle["source_manifest"]).read_bytes())
expected = {entry["path"]: entry["sha256"] for entry in manifest["input_bindings"]}
for entry in bundle["files"]:
    target = workspace / entry["path"]
    if not target.resolve().is_relative_to(workspace.resolve()):
        raise SystemExit("Unsafe documentation path")
    data = base64.b64decode(entry["bytes_base64"], validate=True)
    if hashlib.sha256(data).hexdigest() != entry["sha256"] or expected.get(entry["path"]) != entry["sha256"]:
        raise SystemExit("Historical documentation binding mismatch")
    target.write_bytes(data)
print("Historical verification workspace:", workspace)
PYSTAGE
cd "$HANDOFF_AUDIT_DIR/workspace"
```

This restores matching documentation, not missing code or business facts. All
other code, decisions, inputs and retained artifacts must already match their
original bindings; verification still rejects any mismatch. The bundle supports
shared-blockers-v1 and its containment-v2 input, not arbitrary historical versions.
The output is not self-contained without the matching repository inputs/runtime.

## Verify and optionally replay locally

Continue in the temporary workspace using the selected interpreter. Help commands
are safe to inspect and make no native source requests:

```sh
"$OPERATOR_PYTHON" -B -m operator_delivery.shared_blockers --help
"$OPERATOR_PYTHON" -B -m operator_delivery.shared_blockers build --help
"$OPERATOR_PYTHON" -B -m operator_delivery.shared_blockers verify artifacts/runs/omega4-attempt002-shared-blockers-v1
```

To exercise an offline build, use a destination that is absent in this newly
created temporary workspace. Do not reuse an existing run ID/output:

```sh
"$OPERATOR_PYTHON" -B -m operator_delivery.shared_blockers build --source-run artifacts/runs/omega4-attempt002-containment-v2 --run-id operator-audit-replay-001 --output artifacts/runs/operator-audit-replay-001
"$OPERATOR_PYTHON" -B -m operator_delivery.shared_blockers verify artifacts/runs/operator-audit-replay-001
```

Build exit **2** is expected for this verified partial result, not a failed build;
run the verification command separately after observing that status. Verify exit
**0** means implemented integrity/replay checks passed, not financial completion.
Other failures leave work unverified. Keep the temporary workspace for inspection;
retry in another absent destination rather than repair or overwrite sealed files.
The full suite, if desired separately, is
`"$OPERATOR_PYTHON" -B -m unittest discover -s tests -v` in that workspace.

Selected input checks and projection computations happen before destination
creation. **There is no universal preflight guarantee:** late provenance reads,
final verification and disk/I/O failures may occur after files are written. An
existing destination is refused, but that does not make every failure atomic.
The local-copy environment, local relocation and replay checks are not independent
external operator acceptance, a clean download-based installation, or evidence of
native source availability. Native acquisition is a separate authorized operation.

## Files and navigation

- `retained-run/` copies the entire Decision 002 input run byte-for-byte, including
  all source content, graphs, repair history, snapshots and its original manifest.
  Its original run ID and hashes retain their original meaning.
- `shared-blockers/001.json` through `004.json` retain cumulative central fact,
  owner, scope, links and lifecycle observations at each arrival boundary.
- `case-views/001.json` through `004.json` retain all observed claim/revisions,
  exact original requirements/history, remaining local repairs, reverse blocker
  links and a complete repair-ID mapping. Historical revisions remain visible.
- `batches/001.json` through `004.json` are new `travel-claim-snapshot/2` envelopes.
  They retain the input's financial claims, request facts, money, issues and graph
  state, binding the retained source/queue/graph plus new central and case views.
  Their predecessor links bind the new chain; the input chain remains untouched.
- `shared-blockers.json`, `case-views.json`, `blockers.md`, and `cases.md` are final
  views. Markdown links navigate from a blocker to each exact case/revision and
  back. JSON contains path/expense/repair detail and full history.
- `repair-queue.json` and `claims.csv` are unchanged copies of the input outputs.
  Their original IDs/run provenance are retained, not renumbered for this layer.
- `report.md` provides before/after counts, boundaries and remaining limitations.
- `shared-blocker-manifest.v1.json` binds every output, the original input manifest,
  current code/instructions/tests, Decisions 001–003 and all inherited stage inputs.

## Identity, scope and lifecycle

A blocker ID hashes its fact key, not owner, wording, current status or arrival
batch. Graph purchase keys retain the full normalized purchase tuple and check;
request keys retain the exact request ID; cancellation keys retain the process ID;
package keys retain the exact requirement identity. Same diagnostic code, owner,
amount, or batch does not merge facts. Supported shared purchases are checks, not
open blockers. A previously open supported fact retains its central history.

Each graph-derived case link carries a proven prerequisite-to-review/financial
path, exact claim/revision/trip, and affected expense IDs where proved. Request
links are explicitly family reconciliation only, without certified expense or
revision payment attribution. Request repairs remain separately typed. Package
requirements whose applicability is unknown have **no fabricated case links**.
The register includes both four graph package requirements and two schema gaps.
An evidence-artifact reference identifies the exact retained graph/queue; existing
source locators resolve through the bound snapshot's `source_index`. Empty native
source references are explicitly recorded as gaps, with historical assignment or
schema provenance rather than invented native content.

History records one reproducible observation per batch, including owner, sources,
scope, exact links and state. Owner disagreements are unresolved. A missing root
is retained as `not_observed_recheck_required`, not silently resolved or merged.
A confirmed, independently evidenced no-financial-effect process can retain its
history as `clarified_no_case_repair`; this restores no cancelled travel authority.
Changed purchase tuples create new identities and retain old history. Automatic
cross-identity merges/supersessions are deliberately unsupported without evidence.

## Clarifications and case rechecks

The normal input run contains **no supplied clarification deliveries**. Nothing
in this implementation generates stakeholder answers. An optional
`--clarifications <retained-file.json>` accepts a list of delivery notes, retained
and hash-bound separately. Each note must identify `event_id`, positive integer
`arrival_batch`, exact `blocker_id`/`fact_key`, recorded `owner`, nonempty `reason`,
`source_refs`, and matching `source_hashes` for those references in the snapshot.
`partial` defaults to true. Unknown owners, mismatched sources/hashes, unmatched
blockers and immutable-payload conflicts remain visible and unverified. Future
arrivals cannot affect earlier snapshots. Exact business redelivery, ignoring only
arrival batch, is idempotent; conflicts never overwrite an admitted note.

Even a matching note records **clarification only**, not professional authority or
fact certification. `clarification_received_recheck_required` leaves the fact
unresolved until supported by verified graph evidence. A supported check changes
its fact state to supported and requests independent case rechecks; it never
changes any repair record, case financial state, current approval requirement,
merchant-proof requirement, Finance allocation or Decision 001 hold. The linked
case's entire remaining open repair list stays intact until its own verified
source workflow supplies a disposition. Local rechecks are prepared, not executed
by this organizational layer. A package definition requires the responsible
native/source adapter and a newly verified containment run; arbitrary notes cannot
certify unknown package scope or actor authority.

For new actual evidence, corrections or cancellations, first acquire/normalize/
validate/reconcile and produce a new verified containment run with its proper
arrival history. Build a new register in a new directory. A full replay derives
history from those retained batches; earlier register runs remain immutable.
When new source layouts require an adapter, preserve the failed access/input and
owned unresolved step. Do not patch an old graph, queue or manifest to manufacture
completion. This layer sends no requests and moves no money.

# Scope A increment 5 — snapshots and operator handoff

The builder consumes the four verified stage artifacts and writes a new offline
replay run. It verifies source identities/hashes, deterministic normalization,
policy validation and Finance reconciliation before projecting snapshots. The
original stage code and artifacts remain unchanged.

## Environment and commands

The latest [business-disposition correction](business-dispositions.md) preserves
C13/r1 withdrawal and C14/r1 rejection separately from financial holds. Use its
commands for current artifacts. The examples below describe earlier versions.

For the current [shared-blockers-v1 interim handoff](../artifacts/runs/omega4-attempt002-shared-blockers-v1/report.md),
use the [Decision 003 reference and tested offline commands](shared-blockers.md).
Read [Decision 004](../decisions/decision-004-interim-operator-handoff.md) for the
participant acceptance boundary. The older stage descriptions below explain
retained formats; they are not commands to overwrite or regenerate earlier runs.

Use a locally provisioned `OPERATOR_PYTHON` (Python 3.10+, requirements.txt and
transitive dependencies). No machine-specific interpreter location is required.
The reference covers documentation hash bindings and temporary verification/replay
workspaces. Historical runs require their own matching code/input versions; the
current documentation bundle supports shared-blockers-v1 and its containment-v2
input, not every earlier code revision.

Build exit 2 means a retained partial handoff. Verify exit 0 means the implemented
integrity/schema/chain checks passed, not authorization or financial closure.
A nonzero failure leaves the affected work unverified. Preserve an incomplete
output and choose a new ID/directory; no resume operation edits sealed evidence.

## Files and append-only behavior

- `sources.json`: derived replay manifest with a new run ID and explicit offline
  provenance. Native observation times/statuses/versions are unchanged. It binds
  the original acquisition manifest in `acquisition-manifest.original.json`.
- Retained `source-bindings.json`, `sources/`, `responses/`, `supplemental/`: copied
  unchanged, including browser-policy provenance and native access failures.
- `batches/001.json` through `004.json`: `travel-claim-snapshot/2`, checked with the
  original Draft 2020-12 schema and available format checkers. The audited
  environment lacks the optional `date-time` checker; business timestamp validation
  is separate and schema format coverage must not be overstated. Each later file
  binds its predecessor's relative path/hash and the replay's `sources.json`.
- `queue/001.json` through `004.json`: full repair history at each batch, bound by
  that batch's snapshot. Queue entries do not hash their containing snapshot.
- `claims.csv`: one current claim/revision per final batch, using the required
  columns. Unknown monetary values are blank, not zero.
- `report.md`: operator handoff with source/run references, amounts by scope,
  every current claim/owner, independent cancellations and significant queue changes.
- `repair-queue.json`: final full queue history; `repair-queue.csv`: open work only.
- `operator-manifest.v1.json`: input/code bindings and hashes for every other
  output file. It does not hash itself. A hash manifest is an integrity check,
  not a signature or proof against coordinated malicious rewriting.

Every write uses exclusive creation. Existing output directories and destinations
inside retained stage directories are refused before processing. Selected input
verification and batch computations precede destination creation;
late provenance reads, final verification, and I/O can still fail after files have
been written. There is no universal preflight or atomic-write guarantee. Preserve it, diagnose it and choose a new ID/directory. No
resume operation edits a sealed snapshot. A corrected execution creates a new
versioned chain and explains/binds its earlier run.

## Honest schema projection

The public schema has two relevant representation constraints. They are recorded
as owned unresolved items; the schema itself is unchanged:

1. `claims[].paid_cents` must be an integer. It records **only proven
   revision-attributed confirmed money**. With no proven allocation, the subtotal
   is 0, `paid_cents_complete=false`, `known_paid_cents=null`, and balance remains
   null. This is not an assertion of zero actual payment. CSV uses the nullable
   known amount and therefore leaves every unknown paid amount blank.
2. `requests[]` requires a known claim revision. Finance has no revision/cost
   columns, so original request facts cannot be projected there truthfully.
   They are all preserved, including amounts/events/candidates, in `request_facts`.
   `requests=[]` and `request_projection_complete=false` do not mean no requests
   exist. A facilitator/Finance-owned schema/allocation repair explains the gap.

`allowed_cents` is supported expense-policy arithmetic, not approved authority.
`policy_calculated_allowed_cents` also preserves calculable amounts where an
eligibility finding blocks use. Gross amounts, caps, replacement allowances,
Finance acceptance, confirmed request net and actual closure remain separate.
Expense lines can be eligible while claims remain held. A known personal-cost
zero can be excluded without declaring a financially closed claim.

The current verified evidence supports no complete revision-attributed closure.
All current claim statuses are therefore `held`; closure count is 0. Supplied
return/reject/approve references are retained as decisions, not invented current
authorization. `decision_ids_are_authorization=false` makes that boundary explicit.

## Arrival and repair semantics

Each snapshot recomputes only arrivals through its batch. Earlier snapshots do
not incorporate later corrections, review replies, cancellation confirmations,
refunds or duplicate deliveries. Raw decision, cancellation and Finance deliveries
remain visible. Superseded claim revisions remain in `claim_revision_history`.
Base receipt/trip/merchant/role/rate/cap tables lack arrival labels; their inherited
availability limitation remains applicable. Normalization diagnostics enter the
visible state when their claim revision arrives; all 18 are retained at batch 4.

Finance and business cancellation IDs remain in separate admission namespaces.
Only a valid initiation establishes a typed cancellation process; orphan or
invalid confirmations stay in issues. A later conflict cannot overwrite a prior
lawful confirmation. Confirmation and financial consequence are independent.
The no-financial-effect classification requires no observed claim/purchase/request
and an explicitly blank first commitment date in the retained trip source.

The queue is organized by subject, revision, cost where available, and missing
fact/code. Stable item IDs survive additional evidence and ownership changes;
history records significant batch updates. A new revision supersedes its old
review repairs without resolving old request money. A check no longer reported
after re-evaluation is labelled `cleared_by_recheck`, which never grants approval
or financial closure. Partial evidence changes only the affected item.
Queue source references resolve through each snapshot's `source_index` to the
retained source hash and PDF page or workbook sheet/row; the manifest binds the
governing policy, original interview, Decision 001, stage outputs and code.

Independent checks continue while affected claims remain held. Full dependency
rechecks after corrections implement policy line 23. Decision 001 remains the
required original-request hold. Actual completion would require current approvals,
revision/cost allocation and matching admitted money/scoped Finance resolution;
this handoff accepts none of those missing facts as complete.

## New deliveries, failed access and handoff

For a genuinely fresh run, use the root README's acquisition → normalization →
validation → reconciliation → operator commands with new IDs/directories. The
acquisition adapter attempts all five fixed native sources; the conservative
Notion adapter still cannot certify native policy completeness. Do not call the
current offline replay fresh acquisition.

New scenario decisions and corrections must arrive in retained native sources,
with the supplied arrival boundaries and identities. Do not edit an old normalized
JSON or sealed manifest to manufacture a delivery. If a new input uses unsupported
fields/layouts, retain it and obtain the responsible human's definition before
extending the implementation and regenerating a new chain. The current artifacts
cover only their verified four batches.

If any required native business source is unavailable, stop downstream parsing;
retain the acquisition's failure/error bodies and hand off the missing source,
scope and next evidence needed. An explicitly authorized offline replay may still
reuse an earlier verified run with a clear label. Browser policy is supplemental,
never a silent replacement for native completeness. No real messages are sent.

Finance owns request/revision/cost allocation, original-request consequences,
refunds and scoped resolutions. Employees own receipts/settled merchant proof.
Applicable directory reviewers own current decisions and packet context. The
facilitator owns undefined `DW-D-2`, native completeness and schema clarification.
The Skill prepares local work and consumes authorized scenario facts; it does not
conduct the interview, recommend professional approvals, book travel, move money,
commit, push, deploy or submit. Actual capture/checkpoint evidence is not generated
or claimed by these artifacts.

## Decision 002 dependency-based containment

Use the authorized rule in `decisions/decision-002-dependency-based-containment.md`
with the existing verified stage inputs. This is an offline replay; it does not
attempt fresh sources or create financial authority:

For a new containment build, use the exact CLI options shown by
`"$OPERATOR_PYTHON" -B -m operator_delivery.build build --help`, selecting a new
run ID and an absent destination. The retained `omega4-attempt002-containment-v2`
is an input to the current shared-blocker procedure, not a reusable output target.
Verification of that retained input is included in the current verifier.

Build exit 2 still means a verified partial handoff. Choose another run ID and
output directory for every subsequent run. `--dependency-containment` enables the
new projection; omitting it retains the earlier projection for regression/replay.
The verified normalization, validation and Finance stage artifacts are unchanged;
containment derives its graph after checking their exact deterministic replay.

`dependencies/001.json` through `004.json` contain directed prerequisite-to-work
edges with retained record/rule references. Shared receipt/payment checks use the
full employee, trip/revision, expense, receipt, currency and numeric gross tuple.
Exact trip and permit targets constrain cancellation propagation. Request/claim
links affect financial reconciliation only; candidate revision/cost allocations
are annotations, never proof edges. Roots include missing or invalid checks and
unresolved review/financial facts. Every propagated hold has a deterministic
shortest root-to-operation path. Rechecks use full current revisions, so same-total
corrections cannot inherit prior approvals.

Every current claim exposes `evidence_work` independently of its held financial
status. `independently_resumable` means its receipt/payment proof checks executed
and found supported evidence, so independent evidence work can continue. It does
not assert all policy checks, reviews or closure passed. `partial` identifies
missing receipt/payment proof; other independent checks still execute. Each graph
lists all executed expense checks and affected review/eligibility/financial nodes.
No claims become ready, paid or closed through containment.

The four global requirements remain package-level, linked to unresolved workflow
certification rather than copied into every claim as `inherited_validation_limits`.
Their detailed applicability is unknown. Local reviews and financial attribution
still hold all claims; global uncertainty cannot be used to release money. A
future shared-ledger scope definition requires evidence and additional scoped
edges; the implementation does not guess that definition.

The earlier 703-item open repair register and its manifest are copied unchanged as
`prior-repair-queue.original.json` and `prior-operator-manifest.original.json`.
The active scoped view has 582 repairs: 121 blanket global-as-claim presentations
are reclassified, not resolved. Historical items retain their original states and
sources; no repair is cleared simply because Decision 002 was adopted. The new
manifest links the old manifest and binds the new decision and containment code.
Historical file bytes are verified separately from historical code bindings:
previous manifests name older code hashes, which remain recorded rather than
being rewritten to match the current implementation.

Verification checks hashes, schema, four-snapshot predecessor links, graph edges,
impact paths, current claim evidence states, prior repair preservation, and exact
source-derived graph replay. The graph is not a claim that missing approvals,
merchant proof, policy/package definitions or Finance allocation were supplied.
All 18 normalization diagnostics, including C18/r2's missing reviews, stay visible.

The retained containment-v1 run precedes numeric purchase-tuple canonicalization.
Containment-v2 is the current output; earlier artifacts remain unchanged. Numeric
amount spelling (for example 200.0 versus 200.00) does not break a shared purchase
link, while missing gross amounts cannot prove a shared full purchase identity.

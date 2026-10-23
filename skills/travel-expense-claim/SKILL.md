---
name: travel-expense-claim
description: Prepare traceable Alderbridge travel claim reviews, independent trip and permit work, repair drafts, and financial reconciliation from freshly retrieved native sources and authorized batch decisions. Never approve, invent evidence, send requests, book travel, or move money.
---

# Alderbridge Travel Expense Claim Skill

## Updated verified Project D workflow: Omega Attempt 4

Use [`omega-attempt4/`](../../omega-attempt4/) for the updated verified workflow.
Read the [v3 operator handoff](../../omega-attempt4/operator_delivery/ordinary-closure-v3-handoff.md)
and [v3 run report](../../omega-attempt4/artifacts/runs/omega4-attempt002-ordinary-closure-operator-v3/report.md).
Follow the handoff's isolated verification procedure and explanation of the sealed
report's stale blanket wording.

Verified results are **4 supported retained-evidence closures totaling €2,200.01,
with 117 claims held**. Isolated verification passed **589 original tests** and
**39 Omega closure/safeguard tests**. These results do not establish package-wide
certification, external acceptance, a grade or new payment authority.

From the outer repository root, run `cd omega-attempt4` before Omega commands.
Current v3 replay passed. The historical v2 full-regression wrapper requires an
inner `.git` and assumes `.git/index`, so it is not portable in this subtree.
Never patch sealed evidence to bypass this limitation. The original Skill content
below remains preserved for its historical workflow.

## Inputs

- A new run ID and the scenario's supplied case clock.
- The five native source locations listed below, retrieved afresh on every new run.
- The authorized arrival batch and its boundary/version, supplied by the exercise operator.
- Any prior retained snapshot only when performing an explicitly labeled offline replay; this never substitutes for fresh reads on a new run.
- Human reviewer, employee, and Finance responses only when present in supplied records.

Never infer an approval, exception, source value, reply, or payment from a missing record.

## Invocation

For a clean checkout, use Python 3.11+, Git and access to PyPI. Restore the
published evidence before inspecting the oversized JSON outputs or running
retained-data checks. From outside an existing checkout:

```bash
git clone https://github.com/418todayhope-sys/travel-expense-claim.git
cd travel-expense-claim
python3 scripts/restore_submission_evidence.py
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
```

The restoration helper verifies the delivery manifest and restores exact bytes
without overwriting different existing evidence. Allow approximately 1 GB for
the checkout plus space for new replay outputs. See the
[submission guide](../../artifacts/submission/README.md) for the published
inventory and verification commands.

For **fresh native-source acquisition**, perform acquisition and transcription
for a new run with:

```bash
travel-claim live-run <new-run-id> artifacts/runs/<new-run-id> [--case-clock '<authoritative scenario timestamp>']
```

This attempts all five original sources, retains response evidence and emits `live-run.json`/`.md`. It never accepts prior inputs or consumes batches when clock/policy authority is missing. Direct Notion HTML cannot establish a complete policy block-tree read; authenticated native access remains required. Retrieval timestamps are observations, never an invented case clock. Source-only capture is also available:

```bash
travel-claim capture-sources <run-id> artifacts/runs/<run-id> --case-clock '<scenario ISO timestamp>'
```

Inspect the manifest status and verify retained bytes before processing a batch:

```bash
travel-claim verify-sources artifacts/runs/<run-id>
travel-claim parse-retained artifacts/runs/<run-id>
```

Source-only acquisition does not consume a batch. Batch processing must preserve supplied arrival boundaries and use the public [`snapshot.schema.json`](../../snapshot.schema.json). Current foundation helpers are documented in [`travel_claim.sources`](../../src/travel_claim/sources.py), [`travel_claim.parsing`](../../src/travel_claim/parsing.py), [`travel_claim.workflow`](../../src/travel_claim/workflow.py), [`travel_claim.snapshots`](../../src/travel_claim/snapshots.py), and [`travel_claim.outputs`](../../src/travel_claim/outputs.py).

`parse-retained` hash-verifies the run before transcribing the PDFs and workbook into page- and row-referenced records. The extracted source text and workbook values are evidence only. If the case clock or policy source is unavailable, leave it unresolved and do not consume policy-dependent decisions.

Structural workflow helpers preserve every claim, trip and permit revision; identify whether a supplied decision references a found historical or latest source revision without applying its outcome; deduplicate repeated event IDs and report payload conflicts; and track independent trip/permit cancellation states. They do not calculate policy results. Repair items can be updated with new owner, evidence, reason, action, and subject revision while preserving prior updates. Revision advances reopen the item.

## Native sources

1. [Travel reimbursement policy — POL-2026.2](https://private-pecorino-70e.notion.site/Project-D-Alderbridge-travel-reimbursement-policy-POL-2026-1-3d80b700541e81ed93ebd386abc1dcb0)
2. [Initial claim binder](https://drive.google.com/file/d/13sRj6s_kMeP1hsYGstWWmfkb6SCN1YOS/view)
3. [Claim updates binder](https://drive.google.com/file/d/16829RwrGrMCK9oq5TnWuytFewGk_8xQP/view)
4. [Receipt binder](https://drive.google.com/file/d/1Ynn1VLH-faRIy91xy95rOWwCBhy5mjjM/view)
5. [Travel registers workbook](https://docs.google.com/spreadsheets/d/1338nvKD6rgAdLgGRhYCMMlQyDNLK0sE8pvFWrZAaaxg/edit)

Retain complete relevant bytes actually accessed. A response code or URL alone does not establish content access. Record partial and unavailable scopes separately. Never silently reuse a previous run's bytes in a new run.

## Processing and authority boundaries

1. Bind every fact and decision to its source, subject, and revision.
2. Hold only claims or dependent work affected by missing/conflicting facts. Continue independent valid work. Each unresolved item retains subject type and exact ID, revision, missing/conflicting fact, responsible owner, source reference, and next action.
3. Preserve every claim revision. After a material correction, use the corrected revision and revalidate affected evidence, calculations, trip/permit consistency, approvals, and Finance authorization. Preserve unrelated evidence only where it remains valid. Retain historical commitments, transfers, and refunds; do not use stale approvals as current.
4. Keep trip cancellation and permit cancellation as independent processes, including processes without claims. Cancellation does not itself erase entitlement or Finance obligations. Record Finance disposition and monetary resolution separately when required.
5. Use the owner-grouped local repair queue. Keep each item individually traceable. A partial response may resolve only the item(s) explicitly matched and supported by retained source evidence; unanswered, insufficient, or conflicting items stay open. Draft locally; never send requests.
6. Preserve immutable Finance event identifiers. Reconcile only confirmed transfers and refunds. Do not duplicate events or obligations on replay.
7. The provisional financial closure choice is to require current evidence and approvals, agreement between reviewed entitlement and authorized obligation, net confirmed payment equal to the authorized amount, required Finance resolutions, and no blocking issue. After the first actual processing result, pause for the operator to inspect reconciliation and unresolved cases and confirm final completion conditions and delivery scope.

People retain business approval, exception, and payment authority. This Skill prepares work, validates supplied decisions, and records effects; it does not make discretionary approval recommendations, create replies, issue Finance exceptions, book travel, or move funds.

## Outputs

- `artifacts/runs/<run-id>/sources.json` and retained source bytes.
- One immutable schema-valid `batches/<batch-id>.json` per consumed batch, with relative source and predecessor paths plus SHA-256 hashes.
- `claims.csv` with exactly `claim_id,revision,trip_id,status,allowed_cents,paid_cents,balance_cents,next_owner,reason`.
- Owner-grouped local repair queue with individual items and run/batch update history.
- `report.md` describing completed work, obligations, unresolved items, owners, next actions, cancellations without claims, and source/run references.

Unknown money is null in JSON and blank in CSV. Zero is a known amount. Never label incomplete work complete.

## Operator handoff: new deliveries and unresolved work

### Introduce an authorized delivery

Obtain the actual supplied delivery and its authorized arrival membership,
subject revisions, source versions and business authority from the operator or
source owner. Later supplied batches are fixed inputs, not replies caused by
the unsent drafts. Do not manufacture a batch, response, approval or timestamp.

For a fresh attempt against the five disclosed native locations, the following
supported commands create a new acquisition directory without touching history:

```bash
NATIVE_DELIVERY_PARENT=$(mktemp -d /tmp/project-d-delivery-XXXXXXXX)
NATIVE_DELIVERY_RUN_ID=$(basename "$NATIVE_DELIVERY_PARENT")
travel-claim live-run "$NATIVE_DELIVERY_RUN_ID" "$NATIVE_DELIVERY_PARENT/$NATIVE_DELIVERY_RUN_ID"
travel-claim verify-sources "$NATIVE_DELIVERY_PARENT/$NATIVE_DELIVERY_RUN_ID"
```

Run the entire block anew for every delivery or attempt: each requires a unique
run ID. A unique temporary directory alone does not make a fixed run ID unique;
this example derives the ID from the newly allocated directory name.

This omits a case clock intentionally: it is an acquisition/transcription
attempt, not authority to consume clock-dependent decisions. Inspect
`live-run.json`, `live-run.md`, `sources.json` and retained responses even when
acquisition exits `2` (BLOCKED); exit `1` requires investigating the failure.
Do not continue merely because a manifest verifies: completeness, supplied
arrival boundaries and business authority are separate checks. Native Notion
access remains blocked when only a generic shell is retrieved.

If the new capture contains the complete supported native history, the
supplemental browser policy replay procedure below can rebuild a separate run:
use the new capture directory as `source_run`, a new destination whose basename
equals `--run-id`, and the verified browser copy. This is explicitly offline
processing of that capture, not another fresh acquisition. It processes the
complete contiguous arrival sequence starting at 1; it is not a delta importer.
Missing prior records cannot be replaced with inferred history.

An independently supplied attachment, changed source schema or delta-only batch
has no general CLI import adapter. Preserve its original bytes and provenance
in a new evidence location through the authorized operator, then ask a developer
to implement and verify source-manifest binding, parsing, authority checks and
history-preserving integration before consuming it. Do not hand-edit a retained
manifest or parsed records to make a new delivery appear verified.

### Preserve run and snapshot identity

Keep the previous run directory, source observations, outputs and sealed bytes
unchanged. A rebuilt replay has its own run ID and a new chain: first predecessor
null, later predecessors bound to the preceding snapshot's relative path and
SHA-256. It does not append to or relabel the old chain. The policy replay records
its retained-input lineage; any additional cross-run delivery lineage needs
explicit retention by the operator/developer, not an invented predecessor.

`offline-replay` refuses existing outputs or an existing nonempty batch chain.
There is no CLI resume/append command. Internally,
[`integrate_arrival_batch`](../../src/travel_claim/integration.py) accepts the
next batch with the full `prior_result`, same run ID, source observations and
predecessor binding; a sealed snapshot alone is not that integration state.
Exact last-batch replay is inert; changed input under that replay identity is
rejected. A developer must verify source/history continuity and persistence
before exposing this as a resumable operator procedure. `seal-batch` only seals
supplied state; it neither imports a delivery nor executes business rechecks.

### Resume only the affected work

Use each open queue item's `item_id`, subject type/ID/revision,
`missing_or_return_reason`, owner, `source_refs` and `next_action` to request the
specific missing evidence through a human. Keep drafts unsent. Claim corrections
must retain original cost/submission and revision history; cancellations must
retain their own initiation, confirmation, target and Finance dependencies even
without a claim. Rebuild from complete supported history to execute current
evidence, calculation, approval and financial rechecks. Preserve admitted cash
and unaffected evidence; a passed repair does not establish reimbursement or
closure. Review the new report, correction/cancellation verification and queue,
then run the documented readiness command on the new run.

Source-driven rechecks may resolve matching repairs with an
`evidence-revalidated` event. This is not a stakeholder response. A separate
general repair-response journal uses internal APIs in
[`travel_claim.outputs`](../../src/travel_claim/outputs.py). The bounded
`continue-receipt` and `continue-repairs` commands below expose supported slices; `policy-replay` does not import
responses automatically:

- `apply_partial_response(queue, response_id=..., item_outcomes=..., run_id=...,
  batch_id=..., evidence_directory=...)` takes outcomes keyed by exact existing
  repair item IDs. Allowed outcomes are `supported`, `insufficient`,
  `conflicting` and `unanswered`; retain each item's own note and references.
- The response evidence directory has a separate `sources.json` with unique
  source IDs, confined paths, exact SHA-256, `status: read`, empty missing scope,
  no error, timezone-bearing observation and nonempty version. References use
  `source_id@sha256#locator`. JSON assessments use JSON pointers; native page/row
  references also require `parsed-records.json` bound to that response manifest.
  This supplemental contract never changes the five native acquisition statuses.
- A `supported` outcome requires `assessment_ref` pointing to a retained supplied
  assessment matching `item_id`, `subject_type`, `subject_id`, `revision` and
  `response_id`, with `sufficient: true`, reason, provenance and `evidence_refs`
  equal to the outcome's deduplicated `source_refs`. Every reference must verify.
  The operator must establish the responder's actual authority and factual
  sufficiency; this API checks bindings, not independent business authorization.
  Never manufacture an assessment from a raw receipt or an importer's label.
- Unmentioned items are untouched. Unsupported evidence is held visibly;
  insufficient, conflicting or unanswered deliveries do not resolve open work
  or erase valid prior resolutions. Exact per-item response replay is inert;
  conflicting replay is rejected. Unknown item IDs or malformed outcomes reject
  the call. Changed subject revisions require current evidence: the internal
  `update_repair_item` API reopens advanced revisions while retaining history.
- For types outside those commands, a developer must retain authentic evidence/assessments, load the queue, apply
  the API, validate with `validate_partial_response_journal`, and persist a new
  reviewable result without rewriting historical outputs. Queue resolution alone
  does not rerun claim/Finance dependencies or regenerate snapshots, reports and
  drafts; connecting and validating those outputs remains developer work.

These contracts are exercised in `tests/test_integration.py` (batch order and
replay), `tests/test_revalidation.py` (corrections and independent cancellations)
and `tests/test_partial_responses.py` (item-level notes, evidence, revisions and
replay). The response fixtures are synthetic examples, not supplied authority.

### Executable missing-receipt slice

After obtaining an authentic response, the supported operator route is:

```bash
RECEIPT_CHECK_DIR=$(mktemp -d /tmp/project-d-receipt-XXXXXXXX)
travel-claim continue-receipt \
  artifacts/runs/project-d-stage7-terminal-20261016T110919Z-5afc36 \
  response.json "$RECEIPT_CHECK_DIR/receipt-result" \
  --evidence-dir response-evidence --run-id receipt-result
```

Follow the [response format and limits](../../README.md#missing-receipt-continuation-omega-attempt-2).
One exact current supporting-evidence repair may supply a missing receipt PDF;
other matched items stay individually insufficient/conflicting/unanswered. The
source-bound assessment additionally names the same employee `actor_id` as the
response envelope and repair owner. Preserve actual actor provenance; matching
an identifier does not authenticate its speaker. Raw receipt text is re-parsed
and existing expense checks require matching settled merchant evidence.

The command rechecks the affected claim and writes a separate derived state,
queue, report, CSV and unsent drafts with parent/output hashes. Original arrivals,
cash and decisions are preserved. Exact replay is inert; stale/tampered evidence
is rejected. No authorization or financial closure is created. This is not a new
native-source run or sealed arrival batch, a general importer, or support for
chaining derived continuations. Parent evidence must stay available. Verification
is built into this command; full-run readiness expects the original replay layout.

### Resumable evidence and returned-work repairs

Use `continue-repairs` for current claim supporting-evidence repairs, correction
expense-evidence repairs and the evidence requested by a retained reviewer return.
It accepts receipts plus settled merchant proof, multiple matched items and
successive responses. See the [exact contract and invocation](../../README.md#resumable-evidence-and-returned-work-repairs-omega-attempt-3).

```bash
REPAIR_CHECK_DIR=$(mktemp -d /tmp/project-d-repairs-XXXXXXXX)
travel-claim continue-repairs \
  artifacts/runs/project-d-stage7-terminal-20261016T110919Z-5afc36 \
  response.json "$REPAIR_CHECK_DIR/repair-one" \
  --evidence-dir response-evidence --run-id repair-one
travel-claim continue-repairs \
  "$REPAIR_CHECK_DIR/repair-one" later-response.json \
  "$REPAIR_CHECK_DIR/repair-two" \
  --evidence-dir later-response-evidence --run-id repair-two
```

Retain supplied item-specific assessments and explicit replacement references.
Only the verified selected rows enter the active evidence view; superseded rows,
invalid bytes and original snapshots remain retained. Valid independent items
progress; held items retain reasons. Inspect report, state, queue and unsent drafts
even after exit 0. Stale/wrong-employee subjects and integrity failures reject.
Exact replay is inert, including redelivery to an advanced result; conflicting
response IDs cannot change history. Preserve all ancestor directories.

Returned evidence triggers rechecks, never reviewer approval. Finance, policy,
budget, exception, decision and independent cancellation imports are unsupported;
split/shared expense changes need developer integration. No cash or authorization
is changed. This is offline continuation with built-in chain/output checks,
not fresh acquisition, an extra native arrival batch or full-run readiness.
The older receipt-only result cannot be used as a continuation parent.

## Errors, retries, and limitations

- On source failure, retain the attempt URL, locator, UTC observation time, error, and missing scope. Hold only affected work and report its owner and resumption evidence.
- On partial source access, retain usable pieces and explicitly list missing scope. Do not claim the source was fully read.
- On invalid or conflicting batch data, preserve the input evidence, reject admission of unsupported effects, and create an owned issue; do not silently discard it.
- Retry a failed fresh retrieval only by making another live request and recording the new observation. Do not overwrite a prior run's manifest, retained bytes, or sealed snapshot.
- On replay, preserve obligation/event identity and money; detect conflicting content under an existing event ID.
- Implemented paths include fresh HTTP/export acquisition and source-bound transcription, plus explicitly offline connected claim, correction, independent cancellation and Finance replay. New source manifests retain response observations and partial/error bodies. Complete native policy access, rule interpretation, authoritative case clock and supported completion authority remain required for final live business compliance; acquisition or offline integrity alone does not establish it.

## Supplemental browser policy replay (Step 182)

The operator may explicitly supply the exact verified POL-2026.2 browser copy.
This is separate supplemental evidence, never a successful native Notion read.
After the setup and restoration above, run the published retained-input
procedure from the repository root. This reproduces the primary run's workflow
from its published fresh-capture inputs in a new temporary directory:

```bash
SUBMISSION_CHECK_DIR=$(mktemp -d /tmp/project-d-submission-XXXXXXXX)
travel-claim policy-replay \
  artifacts/runs/project-d-final-live-20261016T105352Z-276e92 \
  "$SUBMISSION_CHECK_DIR/reproduced-run" \
  --run-id reproduced-run \
  --browser-policy user-provided-sources/step-167/POL-2026.2-browser-copy.txt
travel-claim validate-readiness "$SUBMISSION_CHECK_DIR/reproduced-run" \
  --repo . --output-dir "$SUBMISSION_CHECK_DIR/readiness"
```

Use a new temporary parent directory each time. Readiness exits `2` for
disclosed BLOCKED checks and `1` for an integrity failure. New run identities
produce different bound snapshot hashes; compare source identities, revisions,
money, histories and dispositions rather than expecting byte-identical snapshots.
The retained native observations record four accessible source contents and an
inaccessible native Notion policy (generic page shell); replay does not retry
acquisition or change those statuses.

Verify SHA-256
`f547ee77729be8ad431a5ddf2e2907f94f29ad50092231191abd2f72c04f54d2`.
Retain the exact browser text and its user attestation separately in
`supplemental-policy.json` and `supplemental/`. Check `retained-input-lineage.json`
and the original native observations: none may be reclassified. This invocation
is offline replay of retained inputs, with no new native reads. It cannot satisfy
the fresh-five-source requirement. `live-run` remains a distinct acquisition path.

Policy line 3 supplies calendar date 2026-11-15, Europe/Amsterdam. Do not request
or invent a generic time of day to replace that precision. Existing event
admission checks hold same-local-day cutoff observations; seek exact timing only
where material. Native Notion access remains separately BLOCKED. Earlier generic
missing-policy/clock statements above describe unsupplemented acquisition paths;
the browser copy supplies wording and a case date, not fresh native acquisition.

Run readiness after replay. Supplemental policy references are verified separately
from native source references. A passing supplemental/date check is not approval,
financial closure or final submission compliance. Legacy closure gates and other
business rules are unchanged by this evidence adapter; report their remaining
gaps rather than constructing missing business authority. Preserve every prior
run and keep repair messages as human-review drafts.

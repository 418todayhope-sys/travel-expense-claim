# Alderbridge travel expense claims

This repository is the Project D implementation for Alderbridge Consulting. The [Project D task](https://private-pecorino-70e.notion.site/Travel-expense-claim-Task-and-submission-3da0b700541e81249039eff895f77c98) and [snapshot schema](snapshot.schema.json) define the deliverables and retained-state contract. The [public template](https://github.com/GitRollTraining/travel-expense-claim) is the repository starting point.

## Interview rule

You conduct the stakeholder interview yourself, and the questions are yours. Do not connect a coding agent or any other AI to the interview to run, script, or automate it. The interview transcript is assessed together with the code; a project whose interview was run by an agent is not scored.

Keep one final complete original Work Sim Markdown export per interview session under `interviews/`. Do not rewrite it. If an export is unavailable, contact the facilitator.

## Setup

Requires Python 3.11 or later and pip.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

## Foundation commands

Every new capture invokes all five native URLs again. The implementation has no cached/offline fallback. The caller supplies a case clock from the authorized scenario inputs; omit it only for source-acquisition-only capture before a batch clock is available.

```bash
travel-claim capture-sources <run-id> artifacts/runs/<run-id> --case-clock '<scenario ISO timestamp>'
travel-claim verify-sources artifacts/runs/<run-id>
travel-claim parse-retained artifacts/runs/<run-id>
```

`capture-sources` writes `sources.json` and retains usable responses under `sources/`. It exits `0` only when all five source scopes were read, `2` when one or more are unavailable/partial, and `1` on a capture or output error. A successful HTTP response is not considered a read unless the expected source content is present and structurally usable. Existing run manifests and retained files are not overwritten. Google Drive PDFs and the workbook use native export routes; the manifest keeps the provided native URL, source locator, observed UTC time/version, retrieval outcome, scope and retained-byte SHA-256.

When source access is partial, record usable pieces as `read` and inaccessible pieces as `unavailable`; unavailable entries have null path/hash/version and a specific error. Do not substitute prior downloads. A replay from retained inputs must be explicitly implemented and labeled as offline replay.

`parse-retained` first verifies the manifest and retained-byte hashes, then writes `parsed-records.json`. PDF text stays grouped by page, workbook data stays grouped by tab and row, and every extracted record includes its source ID, SHA-256 and page/row locator. This is a transcription layer; it does not evaluate policy or infer claim outcomes. Its exit status is `2` for partial inputs or an unavailable case clock and `1` for a verification or parsing error.

### Explicit offline replay

When source retrieval is unavailable, replay only the previously retained and hash-verified inputs with an explicit offline command:

```bash
travel-claim offline-replay artifacts/runs/<retained-run-id>
```

This command does **not** make native-source requests. It checks that parsed records bind the current `sources.json`, integrates arrival batches in numeric order, and writes immutable `batches/arrival-NNN.json` snapshots linked by predecessor hashes. It writes the latest `claims.csv`, `repair-queue.json`, `offline-replay-state.json`, `report.md`, and `follow-up-drafts.md` alongside that run's retained inputs. The report, sidecar, and each snapshot label the result as an offline replay. Existing batch chains or output files are never overwritten; start a separately identified retained run to create a new chain. When the case clock is unresolved, snapshots retain the blocker and are only structural replay projections; no clock-dependent, policy-dependent, approval, or entitlement result is inferred.

The report separates open claim repairs and trip/permit repairs by responsible owner from run-level external blockers. Each repair retains its subject, revision, source references, opening run/batch, and next action. Resolved items remain in the full queue history. `follow-up-drafts.md` contains one unsent message per responsible owner, with separate claim, trip/permit, and external-blocker sections. Only unresolved items produce drafts; every message requires human review and retains reasons, requested actions, and evidence references. Independent valid records continue processing while other claims remain unresolved.

Once authorized batch state has been processed, pass only evidence-derived state to the snapshot sealer. The first batch has no predecessor; every later batch references the previous snapshot and exact SHA-256. Binding paths are relative to the run directory (`sources.json`, `batches/<prior-batch>.json`).

```bash
travel-claim seal-batch artifacts/runs/<run-id> <batch-id> state.json --run-id <run-id> [--predecessor artifacts/runs/<run-id>/batches/<prior-batch>.json]
travel-claim verify-batch artifacts/runs/<run-id> artifacts/runs/<run-id>/batches/<batch-id>.json
travel-claim write-claims-csv current-claims.json artifacts/runs/<run-id>/claims.csv
```

The state input is a JSON object with `claims`, `requests`, `travel_cancellations`, `admitted_event_ids`, and `issues` arrays matching `snapshot.schema.json`. No approval, Finance event, or claim answer is created by these foundation commands. The CSV writer accepts one current row per claim and emits exactly:

```text
claim_id,revision,trip_id,status,allowed_cents,paid_cents,balance_cents,next_owner,reason
```

Unknown money is `null` in state and blank in CSV; zero remains `0`.

The policy-neutral structural APIs are in `travel_claim.workflow`: they retain claim/trip/permit revision histories, match decisions to exact subject revisions without applying outcomes, deduplicate immutable event IDs while surfacing payload conflicts, and reduce independent trip/permit cancellation requests and confirmations. Cancellation reductions have no claim or Finance side effects.

The owner-grouped repair queue API is in `travel_claim.outputs`. Queue items retain their item and subject identity, type/revision, source references, reason, owner, next action, run/batch history, and a local unsent draft marker. Partial response validation is item-specific and atomic; revision updates reopen affected work, preserve prior response history and recalculate the owner grouping. Unsupported, conflicting, insufficient, or unanswered items stay open.

## Verification

```bash
python -m pytest
```

Snapshot validation can also be run directly:

```bash
travel-claim validate-snapshot artifacts/runs/<run-id>/batches/<batch-id>.json
```

`verify-batch` also checks the source-manifest bytes, predecessor bytes, and cancellation-to-issue references. Do not overwrite a sealed snapshot; create a new run with a documented link if later processing changes its content.

## Connected ordinary workflow (Step 152)

Each offline arrival batch now connects exact claim/trip/employee identity, current-revision expense lines, receipts and settled merchant proof, travel permission, eligibility, human review packets, explicit reimbursement requests, Finance obligations, cash reconciliation and financial closure. `ordinary-workflow.json` retains every claim's stage results and all batch transitions; `ordinary-workflow-demo.md` demonstrates C01 when present. `report.md` summarizes the same stages. Every blocked stage produces an owner-specific unsent repair action. Supported rechecks resolve only their matching items, with an explicit local evidence-validation event rather than an invented human reply.

The retained C01 fixture matches trip T01, receipt R-COST-01, merchant transaction M-COST-01, three observed review packets and request ledger REQ-C01. Its recorded ledger balances, but permission, policy eligibility, approval completeness, exact request/revision authority and closure remain blocked. A matched receipt is evidence, not automatic reimbursement eligibility. Every correction starts evaluation of the current revision again and preserves earlier decisions, cash and stage history. Independent cancellations block only affected claims' ordinary closure paths.

Actual native policy content is still unavailable. The evaluator never extracts policy rules from an interview summary, Finance acceptance, a cap table alone, or a keyword in HTML. It accepts only explicitly supplied, source-hash-matched normalized `workflow_policy_rules` records for its supported `exact-paid-costs-v1` rule set. Definitions specify receipt/settlement requirements, eligible/uncapped categories, FX date basis, required human roles (and any explicit director threshold), permission requirements and completion conditions. Unsupported or incomplete definitions remain blocked. International permission additionally needs exact permit revisions, named reviewers and expressly UTC commitment/approval timing; local date-only commitment cells cannot supply a missing timezone.

Closure also needs a source-backed exact-revision `reimbursement_requests` record, a matching explicitly revision-bound Finance obligation, current required approval evidence, exact entitlement/authorized-obligation/net-cash agreement, an authoritative clock and source-backed `closure_authorities` confirmation of completion conditions. Failed/cancelled/pending Finance dependencies cannot silently disappear. The current native records do not supply those missing authorities. Nothing sends requests or makes discretionary human decisions.

`tests/test_ordinary.py` contains an explicitly labeled **synthetic-test** successful path (pending → closed after confirmed payment), missing-condition regressions, correction reopening, and an unrelated cancellation. Its synthetic policy/clock/request/authority records are confined to the test fixture and are never substituted into real replay evidence. The supported rule set does not claim to implement the complete inaccessible native policy, its exceptions, or unprovided rule definitions.

## Recorded Finance obligations

Offline replay connects Finance ledger observations to claim IDs and request IDs, retaining event IDs, arrival deliveries, source cells, and obligation history. The retained `Finance activity` headers mean:

| Retained field | Interpretation used by replay |
| --- | --- |
| Activity reference | Immutable event identity; identical redeliveries count once. |
| Arrival batch | Delivery membership, separate from business event time. |
| Activity type | Recorded event vocabulary; accepted/adjustment/resolution carry obligation observations, while settled/refund carry confirmed cash. |
| Request reference / Claim reference | Explicit request and claim links; neither encodes an explicit revision. |
| Finance officer / Payee ID | Recorded officer and payee identities, not evidence that every required human approval is present. |
| Currency / Amount (EUR) | Currency and cash amount; only sufficiently supported EUR cash is reconciled. |
| Original activity reference | Refund linkage to the original confirmed payment. |
| Obligation (EUR) | Recorded commitment amount; observations are not summed as additional cash or assumed reimbursement entitlement. |
| Reason / Activity time (UTC) | Retained description and UTC event time; neither establishes a scenario case clock. |

The interview's acceptance description is retained at `interviews/project-d-travel-expense-claim-20261013-2210.md:425`; native headers and examples are retained in `Finance activity`, row 5 and rows 23–25/33. Native Finance rows have no claim-revision column. Replay therefore records the source-observed revision context at **first delivery**, leaving the explicit revision null. Redelivery never rebinds an old event to a corrected revision. An explicit `Claim revision` field, if supplied in source records, is checked against retained revision history.

The sidecar and optional claim `finance_evidence` projection expose recorded obligation history and `recorded_ledger_balance_cents` (recorded obligation minus confirmed net cash for the same request/payee). Adjustments record commitment amounts, not additive payments. A resolution must agree with an existing accepted/adjusted commitment; it cannot create or change one. A request-bound Finance cancellation releases that commitment to zero while preserving its history and all cash. Cancellation naming a transfer attempt does not establish release of the request commitment. Unknown ordering, conflicting events, missing links, or undefined reversal semantics leave the affected ledger difference unresolved. Corrections preserve historical cash/commitments and reopen revision-dependent review; unrelated claim evidence remains intact.

This ledger arithmetic is separate from current-revision authorization and reviewed entitlement. Without separately supported authorization, `allowed_cents` and `balance_cents` remain null/blank and claims remain pending. A zero ledger difference does not establish policy eligibility, complete approvals, or closure. The exact CSV header is unchanged; `report.md` explains recorded financial facts separately from unresolved repairs and external blockers.

## Submission-readiness validation

```bash
travel-claim validate-readiness artifacts/runs/<run-id> --output-dir artifacts/verification/<new-validation-id>
```

This read-only command writes `readiness.json` and `readiness.md` in a new directory outside the retained run. It checks source scope and byte hashes, input bindings, the complete snapshot chain, required files, the exact CSV contract, evidence-derived report/queue/draft traceability, and local Entire.io checkpoint references for HEAD. It does not contact native sources or verify remote synchronization. Existing validation directories are never overwritten.

Each check is `PASS`, `BLOCKED`, or `FAIL`; exit codes are 0, 2, and 1 respectively. Integrity failures take precedence over blockers. Missing policy content and an unconfirmed authoritative case clock remain `BLOCKED`, even when retained artifacts are intact. An offline replay always remains blocked for final live-source submission. This validator covers the retained repository requirements and never certifies policy eligibility, approvals, financial closure, full native assignment compliance, or fresh execution from replay artifacts.

## Current implementation boundary

The implementation supports fresh source capture, byte-bound manifests, loss-aware transcription, schema/hash-checked snapshots, policy-neutral arrival-ordered replay, source-classified Finance reconciliation, exact CSV output, and local owner-grouped repair tracking. `offline-replay` is a structural replay only: the inaccessible reimbursement policy and unconfirmed case clock keep policy conclusions, approval readiness, entitlement, and closure unresolved. Human replies are not imported automatically, and the command never sends repair drafts or moves money. Do not treat an offline replay as a fresh source read or completed claim processing.

If native evidence is unavailable or a business definition conflicts, record the affected scope and escalate to the exercise operator. People retain approval, exception, and payment authority. This tooling never sends requests, books travel, or moves money.

## Step 157: correction and independent cancellation rechecks

Every corrected revision executes the connected evidence, calculation, trip/permit, human-review, request and Finance checks again. `material_corrections` retains changed field and expense-line facts, unchanged cost identities, excluded historical decisions, before-state evidence, and each executed batch result. A changed receipt invalidates readiness even when the amount is unchanged. Cash events and prior revision history remain intact; a passed receipt recheck cannot manufacture new approvals or current request authority.

`correction-cancellation-verification.json` and `.md` demonstrate all retained corrections and independent trip/permit processes with source references, before/after cash facts, executed check results and next actions. They are explicitly retained-input offline outputs. The readiness command compares these artifacts with a deterministic replay and checks the sealed snapshot chain.

Cancellation processing preserves the first event delivery, duplicate deliveries, employee/supervisor evidence, initiation/confirmation chronology, historical versus current claim links, and observed Finance request IDs. Orphan or partial confirmations remain unresolved with owned repair actions. Linked requests are held; unrelated claims continue. Explicit cancellation-bound Finance exceptions are recorded separately from policy eligibility and financial completion. A transfer cancellation never counts as a cash refund. Unknown disposition, approval, policy, case clock or closure authority remains blocked; absence of a claim does not imply absence of financial effects.

## Fresh native-source acquisition and transcription

```bash
travel-claim live-run <new-run-id> artifacts/runs/<new-run-id> [--case-clock '<authoritative scenario timestamp>']
```

`live-run` attempts all five original locations using direct HTTP and native Google PDF/XLSX export routes, then verifies the manifest and transcribes accessible content from **this invocation**. It accepts no prior-run or cache input. Every run requires a new empty directory; existing manifests, parsed inputs, response files and snapshots cannot be reused. The optional clock is caller-supplied scenario evidence; retrieval timestamps never become a case clock.

New captures use `native-source-manifest/2`. Each entry records the original source identity/URL, attempted export URL, redirect destination, HTTP status, start/end UTC observations, ETag or Last-Modified when supplied, content hash/version, accessible scope, error and missing scope. Complete response bodies are retained verbatim under `responses/`, including error pages and unusable shells; usable complete or partial documents are also bound under `sources/`. The verifier checks hashes, scope/status consistency and fresh response bindings. Legacy `/1` manifests remain readable for historical replay; they do not gain fresh-access evidence.

A `read` PDF must be structurally readable with extractable text on every page. Scanned or partially readable documents require further verification. XLSX exports must contain all ten known workbook tabs; all returned bytes, tab content, cell values and numeric source evidence remain retained. Partial HTTP responses, mismatched byte counts, corrupt documents and incomplete workbook exports cannot pass complete acquisition. Usable partial sources are transcribed independently, with missing scope retained. Malformed arrival membership is reported without rounding or supplying a default.

Plain HTTP access to a Notion shell does not establish policy access. Even policy-related HTML is marked **partial** because this reader cannot establish the complete authoritative block tree. The current reader has no authenticated Notion API/browser/export adapter. Complete policy access and policy rule interpretation remain required before policy-dependent execution; source bytes are never replaced by interview-derived rules or earlier downloads.

`live-run.json` and `live-run.md` distinguish acquisition status from final business compliance. Exit `2` means **BLOCKED** (source access, transcription, clock or policy processing remains incomplete); exit `1` means **FAIL** for integrity/execution errors. The command performs fresh acquisition and loss-aware transcription, but does not consume arrival batches or certify final live-source claim compliance. The separate `offline-replay` command remains explicitly labeled retained-input evaluation. A successful `verify-sources` establishes integrity of recorded evidence, including failure observations, rather than completeness of all five sources.

## Step 171: event integrity admission

Finance reconciliation now retains an immutable `admitted_events` ledger separately from raw deliveries. Exact replay has no cash effect; later conflicting payloads retain admitted money and event references while opening a Finance hold. New admissions require source-bound request/payee/currency and directory Finance authority, exact positive cash cents, and a valid observed UTC time. Invalid and unmatched deliveries remain visible. Legacy reconciliation state containing counted cash but no admission ledger requires explicit verified migration; it cannot silently become zero.

Independent cancellation admission checks the trip employee and directory supervisor, exact initiation/process/trip/permit binding, current target revision, strictly increasing UTC occurrence and effective time equal to confirmation occurrence. Invalid or conflicting deliveries do not overwrite admitted history, and deferred references are rechecked when initiation arrives. Business cancellation produces no Finance event or cash effect.

Callers supply the admission cutoff explicitly via `event_clock` (an offset-bearing timestamp, or `{"date": "2026-11-15", "timezone": "Europe/Amsterdam"}` from verified POL-2026.2 line 3). A date-only clock permits unambiguously earlier local dates; observations on the case date remain held without a supplied cutoff instant. No current-system-time, midnight or end-of-day default is used. This admission context does not change the separate eligibility, approval or closure rule implementation, and earlier outputs are never rewritten.

## Step 173: paid-expense calculations and filing dates

`travel_claim.expenses.load_expense_policy(path)` verifies the complete, exact
POL-2026.2 browser copy against the user-supplied SHA-256. Explicitly attach its
returned binding as `parsed['expense_policy']` before calling the arrival-batch
integrator. The binding (including original text, hash, path and browser-copy
provenance) participates in replay identity. No policy is silently loaded from
an old run, and failed native Notion observations remain unchanged. The exact
browser copy is also retained byte-for-byte as a regression-test fixture.

Each ordinary workflow now retains `expense_calculation`, line-level conversion
evidence and an owned `filing_deadline` check. Matching receipt and deduplicated,
settled employee merchant payments establish cost; destination/currency/payment-date
caps apply only to lodging and meals with positive integer units. Transport and
conference are uncapped; supported personal purchases yield zero. EUR uses 1;
other currencies require the exact payment-date Finance rate. Decimal half-up
rounding occurs per line before summation. Missing or conflicting evidence,
unknown categories, caps and rates remain unresolved; independent valid line
calculations survive a blocked claim total. Calculated amounts do not establish
approval, entitlement authorization, a payment event or closure.

Deadlines add two calendar months to the trip end, clamp nonexistent days, and
include the final day. Filing must follow established employee payment, but may
precede travel. Unchanged cost history retains its initial source submission;
new costs use their own first-submission evidence, never import time. Late filing
retains its original finding and requires an explicit directory-Finance,
claim/revision/cost-bound exception covering late filing. Amount-only exceptions
cannot waive lateness. An exception changing the calculated amount remains held
for separate replacement-amount review; this milestone does not implement general
exception eligibility. Multiple payment dates for one expense likewise remain
held pending source-supported allocation, rather than choosing an FX date or cap.
Existing permission, human approval and financial closure authority requirements
remain in force. No earlier run is regenerated by loading this module.

## Step 175: Finance exception evidence and revalidation

The verified browser policy binding now supports the native claim-page exception
fields: `Authorizing Finance officer`, `Applies to claim`, `Applies to revision`,
`Expense reference`, `Allowed original amount`, `Exception reason`, and
`Covered issues`. The exception and employee directory must have retained source
hash/locator bindings; the actor must match the directory Finance officer. The
replacement amount is in the exact bound expense's original currency and uses
its established payment-date FX conversion. Original gross, ordinary calculated
amount, exception wording/references and conversion evidence remain available.
Missing, invalid, ambiguous or stale exception authority holds the affected claim.

Only exact policy issue codes or their explicit native PDF display labels are
recognized. Native `None` and an explicit empty list mean amount-only coverage;
a missing field, unknown label or substring match never waives eligibility.
Each cost retains separate original findings for `late_filing`, `late_permit`,
`permit_unapproved`, and each `travel_cancellation_id`. Cancellation coverage
requires `Travel cancellation reference` to identify the exact current process
and affected expense. Independent findings become separate owned repair items.
A covered finding remains recorded as `covered_for_reimbursement`; it does not
become a business approval, a confirmed cancellation, employee payment, or cash.

Replacement amount changes require current revision/source-bound claim reviews
and matching request/Finance authorization. Earlier reviews remain historical.
Same-revision material source changes retain a hold across later batches until
review evidence identifies the changed retained source, rather than its unchanged
printed binder version alone. Admitted Finance events and cancellation history
are preserved. The earlier Step 173 replacement-amount hold is superseded by
these checks; unrelated budget, role and financial closure gates remain in force.
In particular this milestone does not remove the existing blanket closure hold
for linked cancellations or repair the separate native permission/closure paths.
Same-day permit approvals versus date-only commitments retain an unresolved
ordering finding; no time of day is invented.

`tests/fixtures/retained_exception_records.json` contains verbatim selected C12,
C19 and C121 claim/receipt/workbook records from the retained live attempt, with
original hashes and page/row locators. These tests validate exception application,
not new approvals, fresh source retrieval or real claim closure. Synthetic tests
exercise authorization recovery, stale versions, conflicts and exact replay.

## Step 177: separate permit and reimbursement approvals

`travel_claim.approvals` evaluates supplied review ledger replies, packets and
directory actors against the verified POL-2026.2 browser binding. International
permits review the trip estimate; claims independently review calculated
reimbursement entitlement. Administration, budget owner and supervisor are
required; director is additional strictly above EUR 1,000.00. Exactly EUR
1,000.00 does not require a director. Only the directory's same budget owner and
supervisor may combine one reply explicitly naming both roles. Domestic travel
requires no permit. No discretionary decision is generated.

Every considered delivery retains its raw row, source/page/row references and
validation result, including wrong actors, wrong subjects, stale revisions,
missing reasons, conflicting IDs and duplicate deliveries. Current authority
requires matching source versions and review packet facts. Exact replay adds
no authority. Returns retain a concrete employee repair action; later supplied
current approval can supersede a return by decision time, rather than import
order. Rejection reasons and employee withdrawals are business outcomes, not
confirmation of financial closure. Only source-supported clean cases without
requests, obligations or cash history receive `rejected`/`withdrawn`; existing
financial effects stay held for Finance disposition.

Current claim workflows retain `claim_approval` and `permit_approval`. Independent
permit evaluations also appear in `permit_approvals` in new snapshots and replay
state, including permits without claims. Newly parsed workbooks retain exact
preamble cells so printed source versions are evidenced rather than inferred.
Historical parsed inputs without sufficient source-version evidence remain
blocked; earlier captures are not silently enriched or rewritten. The snapshot
writer accepts this optional evidence while preserving legacy snapshots.

Material trip, expense/evidence, amount, policy-source or directory changes
invalidate affected readiness. Same-revision changes require fresh, explicitly
source-bound replies from the changed evidence batch onward; new revisions cannot
reuse historical replies. Source-bound Finance exceptions only resolve their
specified reimbursement findings; they never approve travel arrangements.
Current-basis cancellation holds arrangement authority without deleting timely
historical permit decisions. Same-day approval/commitment ordering remains
unconfirmed when only a commitment date is supplied.

The retained approval fixture includes actual C01/C02/C09/C13/C14/C21/C46
claim, permit, directory and packet records with original references. C02's
EUR 1,100 permit estimate and USD 600 claim illustrate the independent thresholds.
Full budget reconciliation, broader native entitlement/request adaptation and
financial closure remain separate implementation boundaries. No earlier output
is regenerated by these changes.

## Step 179: budget reconciliation and prior-cost obligations

New snapshots and replay state retain `budget_reconciliation` and a budget
history. The native Budget headers explicitly specify EUR. Scope is the exact
People/Budget department, project and budget period. Opening ledger identities
remain source-version bound; missing native row revision or arrival fields stay
null. Exact replay is inert, conflicting identities hold the affected scope and
retain admitted opening facts, and a verified replacement source version retains
prior history. Raw budget deliveries, including invalid entries, remain visible.

Availability is allocation minus net settled expenditure minus remaining
commitments. Remaining commitment is `max(commitment - net paid, 0)`; a commitment
already includes its settled portion. The supplied opening EUR 20,000 allocation,
EUR 3,000 obligation with EUR 2,000 settled, and EUR 2,000 unsettled obligation
therefore leave EUR 15,000 before new requests. Stable accepted request IDs are
counted once, including requests outside the current batch. Overlapping opening
summaries and event histories must agree or remain held. Budget calculations read
only the protected Finance admission ledger: accepted/adjusted request amounts,
confirmed payments and linked refunds stay distinct from current authorized
reimbursement obligations and outstanding balances. Refunds do not silently
cancel an outstanding commitment. Business cancellations release no Finance
commitment; only admitted request-bound Finance controls change it, and late
payments remain expenditure after cancellation.

Cross-claim cost attribution requires matching employee, trip, cost, receipt,
currency and gross evidence, explicit earlier-claim linkage, and an exactly
supported request allocation. No proportional allocation is invented for an
ambiguous aggregate or partial per-cost settlement. Previously committed/paid
costs are excluded from the new request while original gross and conversion
facts remain intact. Retained C24 explicitly links C03: its EUR 200 COST-03 is
already attributed to REQ-C03, leaving EUR 50 for COST-24. An old commitment for
a different cost cannot offset a corrected claim's new cost. These are ledger
and calculation facts, not newly supplied approvals or real claim closure.

Funds alone never constitute budget-owner approval. Budget-role packets must
reference the whole opening scope ledger; later accepted requests, Finance
adjustments and material budget-source changes require a current source-bound
budget-owner response. Other review roles retain their existing validation.
Permit estimates remain forecasts, not invented accepted obligations. Missing
allocations, scope mappings, evidence or cost attribution remain unresolved, and
owner-grouped repair findings retain exact claim/version and source references.
Unrelated scopes continue independently. The report displays scope balances and
prepaid links; readiness compares budget state/history with deterministic replay.
Native request authorization, Finance exceptions and financial closure rules
remain separate gates. Earlier policy/interview files and run artifacts are not
rewritten.

## Step 182: supplemental browser policy and calendar-date clock

The verified POL-2026.2 file is a **user-provided browser-visible copy**, not a
successful native Notion HTTP/API read. Its exact SHA-256 is
`f547ee77729be8ad431a5ddf2e2907f94f29ad50092231191abd2f72c04f54d2`.
It supplies case date **2026-11-15**, **Europe/Amsterdam**; no time of day or UTC
cutoff is inferred. This supersedes the historical “policy wording/clock wholly
unknown” description for supplemented runs, without altering earlier captures.

From the repository root, create a distinct retained-input run with:

```bash
travel-claim policy-replay \
  artifacts/runs/project-d-live-20261014T204849Z \
  artifacts/runs/project-d-step182-policy-replay \
  --run-id project-d-step182-policy-replay \
  --browser-policy user-provided-sources/step-167/POL-2026.2-browser-copy.txt
travel-claim validate-readiness artifacts/runs/project-d-step182-policy-replay \
  --output-dir artifacts/verification/project-d-step182-policy-readiness
```

Both destination directories must be new. `policy-replay` verifies the original
native manifest and parsed-record binding, copies retained source/response bytes,
and preserves every native observation unchanged. The new manifest has a new run
ID, not new retrieval observations. Original manifest and parsed bytes are retained
under `supplemental/`, with hashes in `retained-input-lineage.json`. The exact policy
copy, separate `supplemental-policy.json`, parsed input, replay state and every
snapshot bind provenance, policy version, source references and date precision.
No automatic cached fallback is added to `live-run`.

Readiness checks supplemental bytes/provenance and native access separately.
It can pass the calendar-date evidence check while native Notion access and final
live-source compliance remain BLOCKED. Existing Finance/cancellation admission
checks hold same-local-day cutoff observations; future observations remain held.
No time is manufactured to release them. Legacy approval, budget, cancellation
resolution and financial closure rules are unchanged: their remaining authority
or schema gaps stay pending, even though expense/exception/review calculations
can now consume the explicitly supplied policy evidence. This command does not
create missing normalized business definitions, requests, approvals or closure
authority. Drafts remain unsent and require human review.

## Step 184: expense-source and reviewer-clock admission

Expense eligibility now requires well-formed source IDs, SHA-256 hashes and record
locators bound to complete `read` observations. Claim, trip/directory, receipt,
merchant payment, applicable cap/FX and reused filing-date evidence are checked
before they can support an amount. Native page/row references must agree with
retained page/cell metadata. Missing, partial, mismatched or unobserved bindings
hold the affected work, retaining the evidence and its original references.
Independent valid claims continue, and admitted Finance cash is preserved.

Permit and claim replies use the existing event cutoff checks. An authoritative
calendar date is interpreted in its supplied timezone; later local dates and
ambiguous same-day observations cannot establish current review authority. An
explicit supplied instant permits decisions at or before that instant. Missing
clock authority holds review admission. Raw replies and rejection reasons stay
visible, including exact replays; a valid earlier reply remains available when a
separately identified later reply is inadmissible. No cutoff time is inferred.

These checks do not change Finance event admission, budget accounting, exception
coverage, cancellation resolution or financial closure rules. Passing source
admission is not a new human approval or evidence of final submission compliance.

## Step 186: financial completion and cancellation dependencies

The verified supplemental POL-2026.2 browser policy now supplies the connected
workflow's policy definitions and completion conditions directly. Legacy
synthetic rule and generic closure-authority tables are not required. The
policy's calendar date is sufficient for clock validation; event/review admission
still holds ambiguous same-day observations. Native Notion acquisition remains
separately blocked and an offline replay never certifies fresh execution.

Closure requires current evidence, approvals, request/obligation authorization,
balanced admitted net cash and every required Finance resolution. A material
correction after acceptance or an adjustment after payment requires an admitted,
current-revision resolution naming the affected event/request and agreeing with
the supported amount. Partial settlement, overpayment, conflicting deliveries
and unresolved dependent evidence stay pending. A later transfer reopens the
case without changing an earlier snapshot. Approved zero entitlement with no
request or financial effects can close with an explicit non-payment reason.

Pre-acceptance business cancellation can complete after exact cost disposition,
post-confirmation cancellation-aware claim reviews and settlement of its first
accepted request. Cancellation after acceptance additionally needs explicit
Finance resolution naming the cancellation. Reimbursement completion never
restores retired travel arrangements. Cancellation consequences, requests and
repair items are projected consistently while admitted initiation/confirmation
history remains intact. A no-claim cancellation can be recorded as having no
financial effect only after all four batches and the complete verified source
inventory establish no commitment, cost or unmatched financial effect. Missing
inventory, relevant costs or ambiguous deliveries preserve a pending state.

The retained Finance schema omits explicit claim revision and resolution-link
fields. Arrival context and free-text reasons do not supply that authority.
Synthetic completion tests explicitly supply those fields; they do not authorize
real retained claims. Blank first-commitment cells in the native Trips schema
mean no commitment yet, as the policy states, rather than an invented late permit.

---
name: travel-expense-claim
description: Prepare traceable Alderbridge travel claim reviews, independent trip and permit work, repair drafts, and financial reconciliation from freshly retrieved native sources and authorized batch decisions. Never approve, invent evidence, send requests, book travel, or move money.
---

# Alderbridge Travel Expense Claim Skill

## Inputs

- A new run ID and the scenario's supplied case clock.
- The five native source locations listed below, retrieved afresh on every new run.
- The authorized arrival batch and its boundary/version, supplied by the exercise operator.
- Any prior retained snapshot only when performing an explicitly labeled offline replay; this never substitutes for fresh reads on a new run.
- Human reviewer, employee, and Finance responses only when present in supplied records.

Never infer an approval, exception, source value, reply, or payment from a missing record.

## Invocation

Install as described in the repository [README](../../README.md). Perform fresh acquisition and transcription for a new run with:

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
From the repository root, use new destination names:

```bash
travel-claim policy-replay \
  artifacts/runs/project-d-live-20261014T204849Z \
  artifacts/runs/project-d-step182-policy-replay \
  --run-id project-d-step182-policy-replay \
  --browser-policy user-provided-sources/step-167/POL-2026.2-browser-copy.txt
travel-claim validate-readiness artifacts/runs/project-d-step182-policy-replay \
  --output-dir artifacts/verification/project-d-step182-policy-readiness
```

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

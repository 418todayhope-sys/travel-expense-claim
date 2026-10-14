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

## Current implementation boundary

This foundation implements fresh source capture, byte-bound manifests, loss-aware source transcription, schema/hash-checked snapshot sealing, exact CSV output, and local owner-grouped repair tracking. It does not yet process scenario batches, decide claim status, perform policy/approval calculations, determine reimbursement entitlement or final readiness, reconcile Finance activity, import human replies, or produce the complete operations report. Do not treat source transcription by itself as a consumed batch or as a completed claim run.

If native evidence is unavailable or a business definition conflicts, record the affected scope and escalate to the exercise operator. People retain approval, exception, and payment authority. This tooling never sends requests, books travel, or moves money.

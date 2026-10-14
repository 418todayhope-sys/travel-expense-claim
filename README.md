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

This command does **not** make native-source requests. It checks that parsed records bind the current `sources.json`, integrates arrival batches in numeric order, and writes immutable `batches/arrival-NNN.json` snapshots linked by predecessor hashes. It writes the latest `claims.csv`, `repair-queue.json`, `offline-replay-state.json`, and `report.md` alongside that run's retained inputs. The report, sidecar, and each snapshot label the result as an offline replay. Existing batch chains or output files are never overwritten; start a separately identified retained run to create a new chain. When the case clock is unresolved, snapshots retain the blocker and are only structural replay projections; no clock-dependent, policy-dependent, approval, or entitlement result is inferred.

The report separates open claim repairs and trip/permit repairs by responsible owner from run-level external blockers. Each repair retains its subject, revision, source references, opening run/batch, and next action. Resolved items remain in the full queue history. Independent valid records continue processing while other claims remain unresolved.

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

The implementation supports fresh source capture, byte-bound manifests, loss-aware transcription, schema/hash-checked snapshots, policy-neutral arrival-ordered replay, source-classified Finance reconciliation, exact CSV output, and local owner-grouped repair tracking. `offline-replay` is a structural replay only: the inaccessible reimbursement policy and unconfirmed case clock keep policy conclusions, approval readiness, entitlement, and closure unresolved. Human replies are not imported automatically, and the command never sends repair drafts or moves money. Do not treat an offline replay as a fresh source read or completed claim processing.

If native evidence is unavailable or a business definition conflicts, record the affected scope and escalate to the exercise operator. People retain approval, exception, and payment authority. This tooling never sends requests, books travel, or moves money.

# Project D Stage 7 evidence delivery

The exact publication inventory is [stage7-evidence-manifest.json](stage7-evidence-manifest.json): 53 original files, their original relative paths, byte counts and SHA-256 hashes, and the corresponding published objects. No historical source, snapshot or report was rewritten. These are fictional exercise records and unsent drafts, not real payment or approval authority.

Selected output run: `artifacts/runs/project-d-stage7-terminal-20261016T110919Z-5afc36/` (29 original files). Start with its `report.md`, `claims.csv`, `repair-queue.json` and `follow-up-drafts.md`. Large Markdown/JSON files may exceed GitHub's web preview limit; a normal clone provides their complete content. Four immutable snapshots are under `batches/arrival-001.json` through `arrival-004.json`.

Supporting files:

- `artifacts/runs/project-d-final-live-20261016T105352Z-276e92/`: 13 files retaining all five fresh acquisition attempts, response bodies, manifests, parsed evidence and live-run summaries.
- `artifacts/runs/source-capture-20261014T100034Z/`: the five original files required by retained-data tests (manifest and four PDF/XLSX inputs). These are historical inputs, never fresh acquisition.
- `user-provided-sources/step-167/POL-2026.2-browser-copy.txt` and `.provenance.json`: exact user-provided policy and browser attestation. Policy SHA-256 is `f547ee77729be8ad431a5ddf2e2907f94f29ad50092231191abd2f72c04f54d2`.
- `artifacts/verification/project-d-stage7-terminal-20261016T110919Z-5afc36-readiness/`: four historical readiness/verification records. They retain their historical commit and 531-test count. They are not attestations about later code or this publication commit.

Current pre-publication validation is retained separately in `artifacts/submission/current-readiness/readiness.json` and `.md`: **30 PASS, 5 BLOCKED, 0 FAIL**, evaluated against implementation commit `f2d3bdbf27ae5a43128359264c51b8e225432876`. Snapshot chain/content, CSV, report, repair journal and drafts pass. Native Notion access is reported in two checks; offline scope is a disclosed mode distinction; 813 open repairs (15 without supporting references) require missing business evidence, not an invented zero-backlog submission gate. This report predates the evidence-publication commit and does not certify its future checkpoint. Remote publication and clean-checkout verification are separate checks.

## Large-file delivery and clean checkout

Two original JSON files exceed GitHub's 100 MiB regular-file limit. Their lossless `.json.gz` objects are committed beside their original paths. All remaining 51 inventory entries are committed directly. Gzip is transport encoding only: the restoration helper verifies both published and restored hashes, refuses to overwrite different existing evidence, and restores the exact required JSON paths. No Git LFS, private download link, authentication token, original workstation path or uncommitted local input is required.

```bash
git clone https://github.com/418todayhope-sys/travel-expense-claim.git
cd travel-expense-claim
python3 scripts/restore_submission_evidence.py
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
# Clone does not fetch custom Entire refs by default:
git fetch origin 'refs/entire/checkpoints/*:refs/entire/checkpoints/*'
travel-claim verify-sources artifacts/runs/project-d-stage7-terminal-20261016T110919Z-5afc36
travel-claim verify-batch artifacts/runs/project-d-stage7-terminal-20261016T110919Z-5afc36 artifacts/runs/project-d-stage7-terminal-20261016T110919Z-5afc36/batches/arrival-004.json
# Validates all four snapshots, source and predecessor hashes recursively.
```

Requires Python 3.11+, Git, and access to PyPI for the declared dependencies. Restoration uses Python's standard library only. Approximately 1 GB of free disk space is recommended per checkout; new replay outputs need additional space. Do not add the restored oversized JSON files to regular Git.

## Validate and reproduce without overwriting history

```bash
# Set this to a new temporary parent directory for every verification/replay:
SUBMISSION_CHECK_DIR=$(mktemp -d /tmp/project-d-submission-XXXXXXXX)
travel-claim validate-readiness artifacts/runs/project-d-stage7-terminal-20261016T110919Z-5afc36 --repo . --output-dir "$SUBMISSION_CHECK_DIR/readiness"
# Readiness exits 2 for disclosed BLOCKED checks; 1 means an integrity failure.
travel-claim policy-replay artifacts/runs/project-d-final-live-20261016T105352Z-276e92 "$SUBMISSION_CHECK_DIR/reproduced-run" --run-id reproduced-run --browser-policy user-provided-sources/step-167/POL-2026.2-browser-copy.txt
```

A new run has a new run identity and therefore different bound hashes. Compare source identities, current claim revisions, money, histories, dispositions and owned issues rather than expecting different runs' snapshot bytes to match. Never rerun into a retained output directory.

The primary run is an **offline replay of retained fresh-source evidence**, not a fresh native-source execution. Its original native observations remain: four source contents read, native Notion policy inaccessible (generic HTTP 200 shell). The browser copy is supplemental evidence, not a successful native Notion read. It establishes the case date **2026-11-15, Europe/Amsterdam**, without a time of day. Material same-day ordering remains held. No missing approval, Finance authority, payment, closure decision or interview confirmation is supplied by publication.

Legitimate open repairs do not require an empty backlog for submission. Native access limitations require disclosure and facilitator guidance; final human acceptance of completion conditions/delivery scope and the Classroom handoff remain human actions. Provide the actual final commit, selected run/report path and real Entire checkpoint references in the Classroom private comment. Public object accessibility does not establish that the facilitator has personally reviewed or accepted the submission.

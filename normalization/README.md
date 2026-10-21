# Scope A increment 2 — retained-source normalization

Python 3.10+ and `pypdf==6.20.1` (`requirements.txt`). No network requests occur.
The current workspace already has that library in the original project's virtual
environment; using its interpreter imports the installed library only, not old
implementation code. No environment or historical source is changed. For this
workspace, run from the Omega Attempt 4 root:

```sh
/home/maxg/travel-expense-claim/.venv/bin/python -B -m unittest discover -s tests -v
/home/maxg/travel-expense-claim/.venv/bin/python -B -m normalization.normalize --run artifacts/runs/omega4-live-20261020-attempt002 --output artifacts/normalizations/omega4-attempt002-normalization-v1
```

Other environments need the listed dependency before invoking these commands
with their own Python interpreter. This increment does not install dependencies.

Acquisition identity and hash verification must pass before source parsing.
All four native business sources must be retained as `read`. Their bytes are
checked again as loaded. The immutable acquisition directory is never written.
Use a new output directory for each execution; existing outputs are refused.

Outputs:

- `records.v1.json`: `omega4-normalized/1`; acquisition-manifest hash, source byte
  bindings, original claim revisions, expense occurrences, receipts, every PDF
  page's extracted text, all nonempty workbook rows with sheet/row/cell references,
  raw XML values/styles/formulas, typed values, and source-identity checks.
- `parsing-report.v1.json` and `.md`: counts, structural missing fields, ambiguous
  input, candidate identity mismatches, repeated delivery groups, and limitations.
  These are parsing/repair diagnostics, not an operations or final claim report.

Decimal amounts are strings in their original currencies, with no FX, caps,
entitlement or monetary state calculations. Blank optional cells become null;
numeric zero remains a known value. Integer revisions/batches are validated, not
truncated. Date-only values remain dates. UTC-labelled timestamp serials are
converted using the workbook's 1900/1904 date system and rounded to displayed
seconds only within 1ms (binary-export noise); materially subsecond values are
flagged and retained raw. No timestamps come from execution time.

PDF parsing targets the observed labelled records and six-column expense layout.
Unexpected layouts, missing fields and cell-count ambiguity produce repairs;
raw page text and original bound PDFs remain available. Nonempty raw source
records are never silently deduplicated. Formatting-only empty workbook rows
are excluded. Lists retain order, including multiline source references/roles.

Finance and cancellation deliveries remain individual rows. Event identity groups
compare all decoded raw fields except arrival batch, identifying repeat deliveries
or conflicts without admitting events, merging money, or deleting history. Shared
expense occurrences (including C03/C24) remain separate links to the same ID.
Receipt existence is checked separately from merchant identity and reported
payment status. Finance claim-reference candidates are explicitly not inferred
expense/revision links. Current-review presence is an observation, not approval
validation. Decision 001 is not executed by this layer.

Exit 0 means structural parsing without diagnostics; 2 means output retained with
visible repairs; 1 means fatal verification/parsing/local failure. A crash during
output writing may leave a partial directory; retain it and choose a new output.
No native policy success, visual PDF fidelity, eligibility, approvals, Finance
closure, or complete business validation is asserted.

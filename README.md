# Travel expense claim

Operate Alderbridge Consulting's travel reimbursement workflow using the reusable
[operator Skill](skills/travel-expense-claim/SKILL.md).

Scope A increment 1 now supplies a standard-library Python source-acquisition
module. See [acquisition setup, commands, evidence semantics and limitations](acquisition/README.md).
Run its standard-library-only checks with
`python3 -B -m unittest discover -s tests -p test_acquisition.py -v`.
Scope A increment 2 adds [deterministic retained-source normalization](normalization/README.md)
with parsing/repair diagnostics. Scope A increment 3 adds
[deterministic policy and approval findings](validation/README.md), with preserved
normalization diagnostics and explicit evidence gaps. Scope A increment 4 adds
[Finance event admission and reconciliation](reconciliation/README.md), preserving
all deliveries and original requests with explicit attribution and approval holds.
Scope A increment 5 adds [sealed batch snapshots, CSV, report and owned repair
queue](operator_delivery/README.md). The output is an explicitly partial offline
handoff: current claims remain held where attribution, approvals or evidence are
insufficient. No actual financial closure or submission is asserted.

## Current interim handoff and offline verification

Start with the [v3 handoff addendum](operator_delivery/ordinary-closure-v3-handoff.md)
and [authoritative v3 verification evidence](artifacts/verifications/omega4-attempt002-ordinary-closure-verification-v3/README.md).
Four selected retained-evidence closures total 220001 cents; 117 claims remain held.
The addendum corrects the replay example and explains sealed historical wording
and isolated verification with the original hash-bound documentation.

### Historical interim handoffs

The [selected ordinary-closure correction](operator_delivery/ordinary-closure.md)
adds an explicit opt-in C01 path and a separately versioned operator result.
It records existing retained settlement evidence, leaves every other claim held,
and preserves the earlier interim handoffs and package-wide unknowns below.

An earlier result is the [business-disposition handoff](artifacts/runs/omega4-attempt002-business-disposition-shared-blockers-v1/report.md).
See [historical replay and verification commands](operator_delivery/business-dispositions.md).
C13/r1 remains withdrawn and C14/r1 rejected in retained business evidence; both remain financially held.

The preceding result is [shared-blockers-v1 report](artifacts/runs/omega4-attempt002-shared-blockers-v1/report.md),
with [shared blockers](artifacts/runs/omega4-attempt002-shared-blockers-v1/blockers.md),
[linked case views](artifacts/runs/omega4-attempt002-shared-blockers-v1/cases.md), and
[repair register](artifacts/runs/omega4-attempt002-shared-blockers-v1/repair-queue.json).
[Decision 004](decisions/decision-004-interim-operator-handoff.md) accepts only an
interim participant milestone: 121 current claims remain financially held, with
582 open repairs and zero financial closures. This is no external operator
acceptance, assignment completion, grade or payment authorization.

See the [historical operator commands and offline environment procedure](operator_delivery/shared-blockers.md).
That reference explains Decision 003 case/blocker navigation and Decision 002
containment, exit codes, failure handling, and fresh temporary replay destinations.

Python 3.10+ needs `pypdf==6.20.1` and `jsonschema==4.26.0`, pinned in
[requirements](operator_delivery/requirements.txt), plus their transitive dependencies
and system time-zone data for Europe/Amsterdam. Select a locally provisioned
interpreter as `OPERATOR_PYTHON`; no sibling repository path is assumed. The
reference provides a fresh-environment check using only compatible installed local
packages, with no network or downloaded dependencies. Transitive packages are not
fully locked, and the optional JSON Schema `date-time` checker is absent in the
audited environment; the implementation's own timestamp checks remain separate.

The current business-disposition run verifies directly with its matching current code and documentation.
Historical manifests bind documentation as well as code. These corrected entry
points intentionally differ from those historical hashes. **Do not patch manifests
or bypass input checks.** Follow the reference to copy the repository to a temporary
workspace, restore only the four hash-bound documentation versions from
`operator_delivery/bound-documentation.v1.json`, then verify the unchanged run there.
Direct verification from the updated working tree is expected to reject the
changed documentation. A local relocated verification/replay is not independent
external operator acceptance or a self-contained runtime distribution.

## New source run and later deliveries

These example commands create a genuinely fresh acquisition and separate stage
outputs. They access the five fixed native sources only at acquisition; do not
describe the retained verification/replay procedure as fresh access. Replace each
example ID/directory with a new one before another execution:

```sh
"$OPERATOR_PYTHON" -B -m acquisition.retain --run-id omega4-next-acquisition-001
"$OPERATOR_PYTHON" -B -m normalization.normalize --run artifacts/runs/omega4-next-acquisition-001 --output artifacts/normalizations/omega4-next-normalization-001
"$OPERATOR_PYTHON" -B -m validation.validate --run artifacts/runs/omega4-next-acquisition-001 --normalized artifacts/normalizations/omega4-next-normalization-001 --output artifacts/validations/omega4-next-validation-001 --through-batch 4
"$OPERATOR_PYTHON" -B -m reconciliation.reconcile --run artifacts/runs/omega4-next-acquisition-001 --normalized artifacts/normalizations/omega4-next-normalization-001 --validated artifacts/validations/omega4-next-validation-001 --output artifacts/reconciliations/omega4-next-reconciliation-001 --through-batch 4
"$OPERATOR_PYTHON" -B -m operator_delivery.build build --acquisition artifacts/runs/omega4-next-acquisition-001 --normalized artifacts/normalizations/omega4-next-normalization-001 --validated artifacts/validations/omega4-next-validation-001 --reconciled artifacts/reconciliations/omega4-next-reconciliation-001 --run-id omega4-next-operator-001 --through-batch 4 --output artifacts/runs/omega4-next-operator-001
```

Consume only supplied arrivals. New revisions trigger full dependency rechecks;
old approvals and original-request money remain history. Cancellation targets
exact trip/permit revisions, and failed source access remains an owned unresolved
item. Required business-source failure stops downstream work. Native policy access
is currently partial even when its labelled browser supplement is retained.
Do not invent a reply or alter an old artifact to resume work. Use the queue's
subject/revision/source/owner and missing-evidence action; a partial response clears
only the matching item after recheck. Finance/reviewers/employees/facilitator retain
their respective authority. The historical assignment capture and native policy
completeness limits remain explicit. No commit, push, deployment or submission is
part of these commands.

## Start

1. Read the [full Project D task](https://private-pecorino-70e.notion.site/Travel-expense-claim-Task-and-submission-3da0b700541e81249039eff895f77c98) for the scope, workflow and deliverables.
2. Use **Use this template → Create a new repository** on [GitRollTraining/travel-expense-claim](https://github.com/GitRollTraining/travel-expense-claim), then clone your own repository and work there.

## Supplied files

```text
README.md
snapshot.schema.json
```

The [snapshot schema](snapshot.schema.json) defines the required retained batch-state format. Create the Skill, outputs and checks required by the task, and replace this README with your actual setup, run, replay and handoff instructions while preserving the entry links and Interview rule.

## Before you work

The original template supplied no implementation or runtime; current setup and limitations are documented above. Follow the shared [Setting Up entire.io for a Project](https://classroom.google.com/c/ODcyMjA4NTkwNDk2/m/ODc0NzI2NzQzMzQ2/details) lesson and verify actual session capture before assessed work.

Use [Project D in Work Sim](https://work-sim.catalyte.ai/s/project-d-travel-expense-claim) for your stakeholder interview and obtain relevant business source links and context there. Read native business sources during each new run and retain the content actually used as the task requires.

**Interview rule.** You conduct the stakeholder interview yourself, and the questions are yours. Do not connect a coding agent or any other AI to the interview to run, script, or automate it. The interview transcript is assessed together with the code; a project whose interview was run by an agent is not scored.

- Export your interview as the original Work Sim Markdown, save one final complete file per session under `interviews/`, and commit and push it with your code. Do not rewrite the export. If the export is unavailable, contact the facilitator.

"""One employee receipt response, retained separately from immutable arrival runs.

This is deliberately not an attachment, decision or Finance-event importer.
Native sources and arrival snapshots remain in the hash-bound parent run.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .event_validation import observation_error, utc_time
from .follow_up import render_follow_up_drafts
from .integration import _sync_ordinary_repairs
from .ordinary import connect_claim, fields, ref
from .outputs import (apply_partial_response, load_repair_queue, project_claim_outputs,
                      validate_partial_response_journal, verify_response_evidence,
                      write_claims_csv, write_repair_queue)
from .parsing import _pdf_pages, _receipt_records
from .snapshots import verify_snapshot
from .sources import verify_source_manifest


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, obj):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(obj, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def confined(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError('Evidence path escapes its directory')
    return path


def parent_evidence(root, schema):
    errors = verify_source_manifest(root)
    if errors:
        raise ValueError('; '.join(errors))
    manifest, parsed, state = [read(root / n) for n in
                              ('sources.json', 'parsed-records.json', 'offline-replay-state.json')]
    if state.get('mode') != 'offline-replay':
        raise ValueError('Receipt continuation requires an original offline replay parent')
    if (parsed.get('run_id') != manifest['run_id'] or state.get('run_id') != manifest['run_id']
            or parsed.get('source_manifest') != {'path': 'sources.json', 'sha256': digest(root / 'sources.json')}
            or state.get('source_manifest_sha256') != digest(root / 'sources.json')
            or state.get('parsed_records_sha256') != digest(root / 'parsed-records.json')):
        raise ValueError('Parent manifest/parsed/state binding differs')
    snapshots = [confined(root, p) for p in state['sealed_batches']]
    if not snapshots:
        raise ValueError('Parent has no sealed arrival history')
    errors = verify_snapshot(snapshots[-1], root, schema)
    if errors:
        raise ValueError('; '.join(errors))
    snapshot = read(snapshots[-1])
    queue = load_repair_queue(root / 'repair-queue.json')
    if queue != state['repair_queue']:
        raise ValueError('Parent queue and state disagree')
    if {c['claim_id']: c['ordinary_workflow'] for c in snapshot['claims']} != state['ordinary_workflows']:
        raise ValueError('Parent snapshot and workflows disagree')
    names = {'sources.json', 'parsed-records.json', 'offline-replay-state.json', 'repair-queue.json'}
    names.update(state['sealed_batches'])
    for row in manifest['files']:
        names.update(p for p in (row.get('path'), row.get('observation', {}).get('response_path')) if p)
    if parsed.get('supplemental_policy'):
        from .policy_evidence import verify_policy_evidence
        verify_policy_evidence(root, parsed)
        names.update(p.relative_to(root).as_posix() for p in (root / 'supplemental').rglob('*') if p.is_file())
        names.update(('supplemental-policy.json', 'retained-input-lineage.json'))
    hashes = {p: digest(confined(root, p)) for p in sorted(names)}
    return manifest, parsed, state, snapshot, queue, hashes


def response_evidence(root, staging, clock):
    """Verify supplied bytes; transcribe PDFs ourselves, never trust supplied rows."""
    manifest = read(root / 'sources.json')
    rows = manifest.get('files')
    if not isinstance(rows, list) or not rows or len({r['source_id'] for r in rows}) != len(rows):
        raise ValueError('Response evidence requires unique source entries')
    staging.mkdir()
    receipts, pages, hashes = [], [], {'sources.json': digest(root / 'sources.json')}
    for row in rows:
        path = confined(root, row['path'])
        if (row.get('status') != 'read' or row.get('missing_scope') != [] or row.get('error') is not None
                or not row.get('version') or digest(path) != row.get('sha256')):
            raise ValueError('Response evidence is incomplete, unobserved or hash-mismatched')
        observed = datetime.fromisoformat(str(row.get('observed_at')).replace('Z', '+00:00'))
        if observed.utcoffset() is None:
            raise ValueError('Response observation requires an explicit timezone')
        error = observation_error(utc_time(row.get('observed_at')), clock)
        if error:
            raise ValueError('Response evidence observation: ' + error)
        if path.suffix.lower() not in {'.pdf', '.json'}:
            raise ValueError('Only receipt PDFs and JSON sufficiency assessments are supported')
        target = confined(staging, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or row['path'] in {'sources.json', 'parsed-records.json'}:
            raise ValueError('Response evidence paths conflict')
        shutil.copyfile(path, target)
        hashes[row['path']] = digest(path)
        if path.suffix.lower() == '.pdf':
            pages.extend(_pdf_pages(target, row['source_id'], row['sha256']))
    receipts = _receipt_records(pages)
    shutil.copyfile(root / 'sources.json', staging / 'sources.json')
    write(staging / 'parsed-records.json', dict(source_manifest={
        'path': 'sources.json', 'sha256': digest(staging / 'sources.json')},
        pdf_pages=pages, records={'receipts': receipts}))
    return manifest, receipts, hashes


def _project(claim, workflow, finance):
    claim.update(ordinary_workflow=deepcopy(workflow), status=workflow['status'],
                 allowed_cents=workflow['allowed_cents'], balance_cents=workflow['balance_cents'],
                 paid_cents=finance['net_confirmed_cents'], next_owner=workflow['next_owner'], reason=workflow['reason'])
    claim['lines'] = [{**{k: line[k] for k in ('cost_id', 'status', 'allowed_cents', 'reason',
                      'source_refs', 'original_cents', 'currency', 'evidence_status')},
                      'source_ids': list(dict.fromkeys(r.split('@', 1)[0] for r in line['source_refs']))}
                      for line in workflow['lines']]
    claim['finance_evidence']['current_revision_authority_confirmed'] = workflow['request'] is not None
    claim['finance_evidence']['closure_authority_confirmed'] = workflow['status'].startswith('closed-')


def _report(state):
    lines = ['# Project D receipt continuation — OFFLINE DERIVED RESULT', '',
             'No fresh native reads, approvals, Finance events or arrival batches were created.',
             'Historical snapshots remain in the hash-bound parent run. This is not a new sealed arrival run.', '',
             f"Run: `{state['run_id']}`; parent: `{state['parent_run_id']}`.",
             f"Response: `{state['response']['response_id']}`. Native policy access: separately retained in parent sources.json.",
             'The local revalidation ordinal follows the parent arrivals; it is not an additional supplied arrival batch or a business timestamp.', '',
             '## Response and revalidation', '']
    if state.get('mode') == 'offline-general-repair-continuation':
        lines[0] = '# Project D repair continuation — OFFLINE DERIVED RESULT'
        lines[6] = f"Response: `{state['response']['response_id']}`. Native acquisition observations: [original sources.json]({state['native_source_manifest_path']}); supplemental replies do not change them."
        lines += ['Receipt and merchant evidence may resume checks; reviewer returns require current human re-review.', '']
        for delivery in state.get('repair_deliveries', []):
            lines.append(f"- Response history `{delivery['response_id']}`: run `{delivery['run_id']}`, batch `{delivery['batch_id']}`; admitted items: {[x['item_id'] for x in delivery['admitted']]}; held items: {delivery['holds']}; source holds: {delivery['source_errors']}")
    for item, outcome in state['response']['item_outcomes'].items():
        entry = state['repair_queue']['items'][item]
        lines.append(f"- `{item}`: {outcome['outcome']}; {entry['status']}; note: {outcome.get('note') or ''}; evidence: {outcome.get('source_refs', [])}")
        if item in state.get('response_holds', {}):
            lines.append('  - Held: ' + state['response_holds'][item])
    for cid in state['revalidated_claims']:
        workflow = state['ordinary_workflows'][cid]
        lines += [f"- `{cid}` r{workflow['revision']}: {workflow['status']}; " + '; '.join(
            f"{s['stage']}={s['status']}" for s in workflow['stages']),
            '  - Evidence: ' + '; '.join(workflow['source_refs'])]
    lines += ['', '## Current claims and recorded cash', '']
    for claim in state['claims']:
        lines.append(f"- `{claim['claim_id']}` r{claim['revision']}: {claim['status']}; net cash {claim['paid_cents']} cents; authorized balance {claim['balance_cents']}.")
    lines += ['', '## Open repairs by owner', '']
    for owner in sorted({i['owner'] for i in state['repair_queue']['items'].values() if i['status'] == 'open'}):
        lines += [f'### {owner}', '']
        for item in state['repair_queue']['items'].values():
            if item['status'] == 'open' and item['owner'] == owner:
                lines.append(f"- `{item['item_id']}` — {item['subject_type']} `{item['subject_id']}` r{item['revision']}: {item['missing_or_return_reason']}; next: {item['next_action']}; sources: {item['source_refs']}")
    lines += ['', '## External blockers', '']
    for issue in state['external_blockers']:
        lines.append(f"- `{issue['record_id']}`: {issue['reason']}; owner: {issue['owner']}; next: {issue['next_action']}")
    lines += ['', 'Outputs: `continuation-state.json`, `claims.csv`, `repair-queue.json`, `ordinary-workflow.json`, `follow-up-drafts.md`, `continuation.json`.',
              'Drafts are unsent. Queue resolution is not approval or financial closure. Native Notion failure is not repaired by supplemental evidence.', '']
    return '\n'.join(lines)


def verify_continuation(output, _seen=None):
    """Read-only integrity/consistency check; not submission or business approval."""
    output = Path(output).resolve()
    seen = set() if _seen is None else _seen
    if output in seen:
        raise ValueError('Continuation predecessor cycle')
    seen.add(output)
    binding = read(output / 'continuation.json')
    for path, sha in binding['output_hashes'].items():
        if digest(confined(output, path)) != sha:
            raise ValueError('Continuation output hash differs: ' + path)
    parent = (output / binding['parent_path']).resolve()
    for path, sha in binding['parent_hashes'].items():
        if digest(confined(parent, path)) != sha:
            raise ValueError('Historical parent evidence changed: ' + path)
    if (parent / 'continuation.json').exists():
        verify_continuation(parent, seen)
    state = read(output / 'continuation-state.json')
    if state.get('mode') == 'offline-general-repair-continuation':
        current = read(output / 'continuation-input.json').get('repair_continuation', {})
        if (current.get('mode') != state['mode'] or current.get('run_id') != state['run_id']
                or current.get('evidence_binding') != {'path': 'response-evidence/sources.json',
                    'sha256': digest(output / 'response-evidence/sources.json')}):
            raise ValueError('Continuation input and supplemental evidence binding disagree')
    queue = load_repair_queue(output / 'repair-queue.json')
    if queue != state['repair_queue'] or read(output / 'ordinary-workflow.json')['claims'] != state['ordinary_workflows']:
        raise ValueError('Continuation queue/workflow/state disagree')
    if read(output / 'response.json') != state['response']:
        raise ValueError('Continuation response and state disagree')
    historical = read(parent / ('offline-replay-state.json' if (parent / 'offline-replay-state.json').exists()
                                else 'continuation-state.json'))
    for key in ('finance_reconciliations', 'decision_history', 'revision_history', 'cancellation_state',
                'source_record_history', 'material_corrections'):
        if state[key] != historical[key]:
            raise ValueError('Continuation altered protected financial/decision history: ' + key)
    for claim in state['claims']:
        cid = claim['claim_id']
        if claim['ordinary_workflow'] != state['ordinary_workflows'][cid]:
            raise ValueError('Claim projection and workflow disagree')
        if claim['paid_cents'] != state['finance_reconciliations'][cid]['net_confirmed_cents']:
            raise ValueError('Claim cash projection differs from admitted Finance history')
        if cid not in state['revalidated_claims'] and state['ordinary_workflows'][cid] != historical['ordinary_workflows'][cid]:
            raise ValueError('Continuation altered an unrelated claim')
    validate_partial_response_journal(queue, output / 'response-evidence')
    # CSV writer validates cents/types; compare its projection without changing outputs.
    with tempfile.TemporaryDirectory(prefix='project-d-check-') as temp:
        csv_path = Path(temp) / 'claims.csv'
        write_claims_csv(project_claim_outputs(state['claims'], queue), csv_path)
        if csv_path.read_bytes() != (output / 'claims.csv').read_bytes():
            raise ValueError('Continuation CSV and state disagree')
    drafts, _ = render_follow_up_drafts(run_id=state['run_id'], queue=queue, blockers=state['external_blockers'])
    if drafts != (output / 'follow-up-drafts.md').read_text() or _report(state) != (output / 'report.md').read_text():
        raise ValueError('Continuation report/drafts and state disagree')
    return binding


def continue_receipt(parent_run, response_file, evidence_dir, output, *, run_id, schema_path):
    """Admit one employee's missing receipt and recheck exactly its current claim."""
    parent_run, response_file, evidence_dir, output = [Path(p).resolve() for p in
                                                      (parent_run, response_file, evidence_dir, output)]
    if (not run_id or output.name != run_id or output == parent_run
            or output.is_relative_to(parent_run) or output == evidence_dir or output.is_relative_to(evidence_dir)
            or response_file.is_relative_to(output)):
        raise ValueError('Use a separate new output directory whose name equals run ID')
    manifest, parsed, state, snapshot, queue, hashes = parent_evidence(parent_run, schema_path)
    if run_id == manifest['run_id']:
        raise ValueError('Continuation requires a distinct run ID')
    response = read(response_file)
    if response.get('response_version') != 'missing-receipt-response/1' or not response.get('response_id'):
        raise ValueError('Unsupported receipt response envelope')
    outcomes = response.get('item_outcomes')
    if not isinstance(outcomes, dict) or not outcomes:
        raise ValueError('Response must identify repair items')
    supported = [key for key, value in outcomes.items() if value.get('outcome') == 'supported']
    if len(supported) != 1:
        raise ValueError('This command requires exactly one supported missing-receipt repair')
    response_batch = 'receipt-response:' + response['response_id']
    for key in outcomes:
        item = queue['items'].get(key)
        if not item or item['status'] != 'open' or item['subject_type'] != 'claim':
            raise ValueError('Response item is missing, not open or not a claim')
        workflow = state['ordinary_workflows'].get(item['subject_id'], {})
        if item['revision'] != workflow.get('revision') or key != f"ordinary:{item['subject_id']}:r{item['revision']}:supporting_evidence":
            raise ValueError('Stale or unsupported repair item/revision')
        claim = state['revision_history']['claim'][item['subject_id']]
        record = next(r['record'] for r in claim['revisions'] if r['revision'] == item['revision'])
        if response.get('actor_id') != fields(record).get('Employee') or item['owner'] != response['actor_id']:
            raise ValueError('Response actor does not match the affected employee/owner')
    with tempfile.TemporaryDirectory(prefix='project-d-receipt-') as temp:
        retained = Path(temp) / 'response-evidence'
        evidence, receipts, response_hashes = response_evidence(evidence_dir, retained, parsed.get('event_clock') or parsed.get('case_clock'))
        fingerprint = hashlib.sha256(json.dumps(dict(parent=hashes, response=digest(response_file),
            evidence=response_hashes, run_id=run_id), sort_keys=True).encode()).hexdigest()
        if output.exists():
            existing = verify_continuation(output)
            if existing['input_sha256'] != fingerprint:
                raise ValueError('Conflicting replay; existing continuation is immutable')
            return dict(run_id=run_id, output=output, replayed=True)
        key = supported[0]
        item = queue['items'][key]
        outcome = outcomes[key]
        assessment = verify_response_evidence(item, outcome, response['response_id'], retained)
        if assessment.get('actor_id') != response['actor_id']:
            raise ValueError('Retained assessment does not bind the response employee actor')
        matches = [r for r in receipts if ref(r) == outcome.get('receipt_ref')]
        if len(matches) != 1 or outcome.get('source_refs') != [ref(matches[0])]:
            raise ValueError('Supported repair must reference exactly its retained receipt')
        receipt = matches[0]
        cid, revision = item['subject_id'], item['revision']
        prior = state['ordinary_workflows'][cid]
        if prior['status'] != 'pending' or prior['request'] is not None or state['finance_reconciliations'][cid]['authorized_obligation'] is not None:
            raise ValueError('Only pending claims without current reimbursement authorization are supported')
        claim = next(r for r in state['revision_history']['claim'][cid]['revisions'] if r['revision'] == revision)
        expense = [l for l in prior['lines'] if l.get('receipt_id') == receipt['receipt_id']]
        if len(expense) != 1 or expense[0]['evidence_status'] == 'PASS' or any(
                r.get('receipt_id') == receipt['receipt_id'] for r in parsed['records']['receipts']):
            raise ValueError('This receipt is not the missing receipt of the current claim')
        native_ids = {r['source_id'] for r in manifest['files']}
        if native_ids & {r['source_id'] for r in evidence['files']}:
            raise ValueError('Supplemental evidence cannot replace native source identities')
        parsed['records']['receipts'].append(receipt)
        observations = manifest['files'] + evidence['files']
        before_finance = state['finance_reconciliations'][cid]
        workflow = connect_claim(parsed=parsed, claim=claim, decisions=state['source_record_history']['decisions'],
            finance_events=state['source_record_history']['finance_events'], finance=deepcopy(before_finance),
            cancellations=snapshot['travel_cancellations'], arrival_batch=max(parsed['arrival_batches']) + 1,
            source_observations=observations, prior_finance=before_finance, prior_workflow=prior,
            budget_data=state['budget_reconciliation'], prepaid_data=state['budget_reconciliation']['cost_attribution'],
            prior_budget_view=state['budget_reconciliation']['claim_views'][cid])
        finance = workflow.pop('finance')
        if next(s for s in workflow['stages'] if s['stage'] == 'supporting_evidence')['status'] != 'PASS':
            raise ValueError('Receipt/merchant identity, gross or other evidence does not pass revalidation')
        if workflow['status'] != 'pending' or workflow['request'] is not None or finance != before_finance:
            raise ValueError('Receipt-only continuation must not change Finance history or establish authorization/closure')
        apply_partial_response(queue, response_id=response['response_id'], item_outcomes=outcomes,
            run_id=run_id, batch_id=response_batch, evidence_directory=retained)
        _sync_ordinary_repairs(dict(repair_queue=queue, ordinary_workflows={cid: workflow},
            finance_reconciliations={cid: finance}), run_id=run_id, batch_id=response_batch)
        validate_partial_response_journal(queue, retained)
        state['ordinary_workflows'][cid] = workflow
        state['ordinary_workflow_history'].append(dict(batch_id=response_batch, workflow=deepcopy(workflow)))
        state['budget_reconciliation']['claim_views'][cid] = deepcopy(workflow['budget_view'])
        for c in snapshot['claims']:
            if c['claim_id'] == cid:
                _project(c, workflow, finance)
        state.update(mode='offline-repair-continuation', run_id=run_id, parent_run_id=manifest['run_id'],
            parent_run_path=os.path.relpath(parent_run, output),
            parent_snapshot_hashes={p: h for p, h in hashes.items() if p.startswith('batches/')},
            response=response, revalidated_claims=[cid], repair_queue=queue, claims=snapshot['claims'],
            evaluation_boundary=dict(kind='receipt-response', response_id=response['response_id'],
                local_ordinal=max(parsed['arrival_batches']) + 1, native_arrival_batch=None),
            receipt_response_history=[dict(response_id=response['response_id'], receipt=receipt)],
            external_blockers=parsed.get('unresolved_issues', []))
        state['parent_sealed_batches'] = state.pop('sealed_batches')
        state['parent_parsed_records_path'] = state.pop('parsed_records_path')
        # Publish the bundle only after admission and all business checks succeed.
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(exist_ok=False)
        shutil.copytree(retained, output / 'response-evidence')
        shutil.copyfile(response_file, output / 'response.json')
        write(output / 'continuation-state.json', state)
        write_repair_queue(queue, output / 'repair-queue.json')
        write_claims_csv(project_claim_outputs(state['claims'], queue), output / 'claims.csv')
        write(output / 'ordinary-workflow.json', dict(mode=state['mode'], run_id=run_id, claims=state['ordinary_workflows']))
        drafts, _ = render_follow_up_drafts(run_id=run_id, queue=queue, blockers=state['external_blockers'])
        (output / 'follow-up-drafts.md').write_text(drafts, encoding='utf-8')
        (output / 'report.md').write_text(_report(state), encoding='utf-8')
        output_hashes = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob('*') if p.is_file()}
        write(output / 'continuation.json', dict(version='receipt-continuation/1', run_id=run_id,
            input_sha256=fingerprint, parent_path=os.path.relpath(parent_run, output), parent_hashes=hashes,
            response_hashes=response_hashes, output_hashes=output_hashes, fresh_native_reads_performed=False))
        verify_continuation(output)
    return dict(run_id=run_id, output=output, replayed=False)

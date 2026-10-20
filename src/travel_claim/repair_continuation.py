"""Bounded, resumable expense-evidence repairs; no decision or cash importer."""
from copy import deepcopy
from datetime import datetime
from decimal import InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

from pypdf.errors import PdfReadError
from openpyxl.utils.exceptions import InvalidFileException

from .event_validation import observation_error, utc_time
from .expenses import number, validate_employee_date
from .follow_up import render_follow_up_drafts
from .integration import _sync_ordinary_repairs
from .ordinary import connect_claim, expense_lines, fields, ref, table
from .outputs import (apply_partial_response, validate_partial_response_journal,
                      verify_response_evidence, project_claim_outputs, write_claims_csv, write_repair_queue)
from .parsing import _pdf_pages, _receipt_records, _workbook_sheets
from .receipt_continuation import (confined, digest, read, write, parent_evidence,
                                   verify_continuation, _project, _report)

MODE = 'offline-general-repair-continuation'


def load_parent(parent, schema):
    if (parent / 'offline-replay-state.json').exists():
        manifest, parsed, state, snapshot, queue, hashes = parent_evidence(parent, schema)
        state['claims'] = snapshot['claims']
        state['external_blockers'] = parsed.get('unresolved_issues', [])
        state['parent_sealed_batches'] = state.pop('sealed_batches')
        state['parent_parsed_records_path'] = state.pop('parsed_records_path')
        state['parent_snapshot_hashes'] = {p: h for p, h in hashes.items() if p.startswith('batches/')}
        return parent, manifest, parsed, state, queue, snapshot['travel_cancellations'], hashes
    binding = verify_continuation(parent)
    state = read(parent / 'continuation-state.json')
    if state['mode'] != MODE:
        raise ValueError('Resume requires an original replay or continue-repairs result')
    root = (parent / binding['root_path']).resolve()
    manifest = read(root / 'sources.json')
    parsed = read(parent / 'continuation-input.json')
    hashes = {p: digest(confined(parent, p)) for p in list(binding['output_hashes']) + ['continuation.json']}
    return root, manifest, parsed, state, state['repair_queue'], state['travel_cancellations'], hashes


def retain_delivery(incoming, staging, prior, clock, response_id):
    """Retain even bad bytes; only freshly parsed, verified pieces are admissible."""
    if prior and (prior / 'response-evidence').exists():
        shutil.copytree(prior / 'response-evidence', staging)
        combined = read(staging / 'sources.json')
        parsed = (read(staging / 'parsed-records.json') if (staging / 'parsed-records.json').exists()
                  else {'pdf_pages': [], 'workbook_sheets': [], 'records': {'receipts': []}})
    else:
        staging.mkdir()
        combined = {'files': []}
        parsed = {'pdf_pages': [], 'workbook_sheets': [], 'records': {'receipts': []}}
    supplied = read(incoming / 'sources.json')
    rows = supplied.get('files')
    if (not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows)
            or any(not isinstance(r.get('source_id'), str) or not r['source_id'] for r in rows)
            or len({r['source_id'] for r in rows}) != len(rows)):
        raise ValueError('Delivery requires unique source entries')
    old_ids = {r['source_id'] for r in combined['files']}
    if old_ids & {r['source_id'] for r in rows}:
        raise ValueError('New delivery must use distinct evidence source IDs')
    prefix = 'delivery-' + hashlib.sha256(response_id.encode()).hexdigest()
    copied = staging / prefix
    copied.mkdir()
    shutil.copyfile(incoming / 'sources.json', copied / 'original-manifest.json')
    errors, records = {}, {}
    hashes = {'sources.json': digest(incoming / 'sources.json')}
    for row in rows:
        source = confined(incoming, row['path'])
        target = confined(copied, row['path'])
        if row['path'] in {'original-manifest.json', 'sources.json', 'parsed-records.json'} or target.exists():
            raise ValueError('Conflicting evidence path')
        target.parent.mkdir(parents=True, exist_ok=True)
        retained = dict(row, path=target.relative_to(staging).as_posix())
        combined['files'].append(retained)
        if not source.is_file():
            hashes[row['path']] = None
            errors[row['source_id']] = 'Missing retained evidence bytes'
            continue
        shutil.copyfile(source, target)
        hashes[row['path']] = digest(target)
        try:
            if (row.get('status') != 'read' or row.get('missing_scope') != [] or row.get('error') is not None
                    or not isinstance(row.get('version'), str) or not row['version'].strip()
                    or hashes[row['path']] != row.get('sha256')):
                raise ValueError('Incomplete, unobserved or hash-mismatched evidence')
            observed = datetime.fromisoformat(str(row.get('observed_at')).replace('Z', '+00:00'))
            if observed.utcoffset() is None:
                raise ValueError('Evidence observation requires timezone')
            error = observation_error(utc_time(row['observed_at']), clock)
            if error:
                raise ValueError(error)
            if source.suffix == '.pdf':
                pages = _pdf_pages(target, row['source_id'], row['sha256'])
                rs = _receipt_records(pages)
                if not rs or any(not p['text'].strip() for p in pages):
                    raise ValueError('Receipt PDF is empty or incomplete')
                parsed['pdf_pages'].extend(pages)
                parsed['records']['receipts'].extend(rs)
                records.update({ref(r): ('receipt', r) for r in rs})
            elif source.suffix == '.xlsx':
                sheets = _workbook_sheets(target, row['source_id'], row['sha256'])
                if len(sheets) != 1 or sheets[0]['name'] != 'Merchant payments' or not sheets[0]['records']:
                    raise ValueError('Only a nonempty Merchant payments tab is supported')
                parsed['workbook_sheets'].extend(sheets)
                records.update({ref(r): ('merchant-payment', r) for r in sheets[0]['records']})
            elif source.suffix == '.json':
                read(target)  # Retained assessment, never a trusted parsed-row substitute.
            else:
                raise ValueError('Only receipt PDF, merchant XLSX and assessment JSON are supported')
        except (ValueError, TypeError, KeyError, OSError, BadZipFile, ParseError, PdfReadError, InvalidFileException) as exc:
            errors[row['source_id']] = str(exc)
    (staging / 'sources.json').write_text(json.dumps(combined, indent=2) + '\n')
    parsed['source_manifest'] = {'path': 'sources.json', 'sha256': digest(staging / 'sources.json')}
    (staging / 'parsed-records.json').write_text(json.dumps(parsed, indent=2) + '\n')
    return combined, records, errors, hashes


def match_item(key, item, state, actor):
    if not item or item['subject_type'] != 'claim':
        raise ValueError('Unknown or non-claim repair item')
    cid, revision = item['subject_id'], item['revision']
    workflow = state['ordinary_workflows'].get(cid, {})
    if item['status'] != 'open' or workflow.get('revision') != revision:
        raise ValueError('Stale or non-open repair item/revision')
    claim = next(r for r in state['revision_history']['claim'][cid]['revisions'] if r['revision'] == revision)
    if actor != fields(claim['record']).get('Employee'):
        raise ValueError('Response actor must match the claim employee')
    return cid, claim


def return_context(state, key, cid, revision):
    decision_id = key.split(':review_return:', 1)[1]
    workflows = [state['ordinary_workflows'][cid]] + [x['workflow'] for x in state['ordinary_workflow_history']
                    if x['workflow']['claim_id'] == cid and x['workflow']['revision'] == revision]
    replies = {ref(d['raw_record']): d for wf in workflows for d in wf['observed_reviews']
               if d['decision_id'] == decision_id and d['outcome'] == 'return' and d['evidence_valid']}
    if len(replies) != 1:
        raise ValueError('Return has no unique admitted historical reviewer authority')
    return next(iter(replies.values()))


def admit_records(parsed, state, claim, outcome, records, assessment):
    """Use existing native schemas and exact, assessment-bound replacement intent."""
    repairs = outcome.get('repairs')
    if not isinstance(repairs, list) or not repairs or assessment.get('repairs') != repairs:
        raise ValueError('Assessment must bind the exact repair operations')
    if outcome.get('source_refs') != list(dict.fromkeys(r.get('record_ref') for r in repairs)):
        raise ValueError('Response references must exactly identify supplied repair rows')
    cid = fields(claim['record'])['Claim reference']
    employee = fields(claim['record'])['Employee']
    trip = fields(claim['record'])['Trip reference']
    changed = []
    for repair in repairs:
        kind, record = records.get(repair.get('record_ref'), (None, None))
        if kind != repair.get('kind') or kind not in {'receipt', 'merchant-payment'}:
            raise ValueError('Unsupported or unverified repair record')
        values = fields(record)
        cost = values.get('Expense reference')
        lines = [l for l in expense_lines(claim['record']) if l['cost_id'] == cost]
        if len(lines) != 1:
            raise ValueError('Evidence must match an exact current expense')
        line = lines[0]
        for other, wf in state['ordinary_workflows'].items():
            if other != cid and any(l['cost_id'] == cost or l.get('receipt_id') == line['receipt_id'] for l in wf['lines']):
                raise ValueError('Shared expense/receipt requires broader dependency reconciliation')
        if (values.get('Employee' if kind == 'receipt' else 'Employee ID') != employee
                or values.get('Trip reference') != trip or values.get('Receipt reference') != line['receipt_id']
                or values.get('Currency') != line['currency']
                or number(values.get('Gross amount')) <= 0
                or number(values.get('Gross amount')) != number(line['original_amount'])):
            raise ValueError('Evidence employee/trip/cost/receipt/currency/gross mismatch')
        if kind == 'receipt':
            bucket = parsed['records']['receipts']
            identity, identity_value = 'Receipt reference', line['receipt_id']
        else:
            if values.get('Payment status') != 'settled' or not values.get('Transaction reference'):
                raise ValueError('Merchant proof requires an identified settled transaction')
            validate_employee_date(values.get('Paid date'), 'Employee payment date', parsed,
                                   {'employee_date_checks': [], 'source_refs': []}, [ref(record)])
            # Materialized active view, with every superseded row retained below.
            if 'merchant_payments' not in parsed['records']:
                parsed['records']['merchant_payments'] = deepcopy(table(parsed, 'merchant_payments', 'Merchant payments'))
            bucket = parsed['records']['merchant_payments']
            identity, identity_value = 'Expense reference', cost
            for old in bucket:
                if fields(old).get('Transaction reference') == values['Transaction reference'] and fields(old).get('Expense reference') != cost:
                    raise ValueError('Merchant transaction identity already belongs to a different expense')
        existing = [r for r in bucket if fields(r).get(identity) == identity_value]
        supersedes = repair.get('supersedes_refs', [])
        if (not isinstance(supersedes, list) or len(set(supersedes)) != len(supersedes)
                or set(supersedes) != {ref(r) for r in existing}):
            raise ValueError('Replacement must explicitly name every superseded current row')
        if any(ref(r) == ref(record) for r in existing):
            raise ValueError('Evidence is already current; no repair performed')
        bucket[:] = [r for r in bucket if r not in existing] + [deepcopy(record)]
        changed.append(dict(kind=kind, current=deepcopy(record), superseded=deepcopy(existing)))
    return changed


def continue_repairs(parent_run, response_file, evidence_dir, output, *, run_id, schema_path):
    parent, response_file, incoming, output = [Path(p).resolve() for p in (parent_run, response_file, evidence_dir, output)]
    if (not run_id or output.name != run_id or any(output == p or output.is_relative_to(p) for p in (parent, incoming))
            or response_file.is_relative_to(output)):
        raise ValueError('Use a distinct, new output directory named for the run ID')
    root, manifest, parsed, state, queue, cancellations, hashes = load_parent(parent, schema_path)
    if run_id in {state['run_id'], manifest['run_id']}:
        raise ValueError('Continuation requires a new run ID')
    response = read(response_file)
    if (response.get('response_version') != 'repair-response/1' or not isinstance(response.get('response_id'), str)
            or not response['response_id'].strip() or not isinstance(response.get('item_outcomes'), dict)
            or not response['item_outcomes']):
        raise ValueError('Invalid repair response envelope')
    outcomes = response['item_outcomes']
    response_id = response['response_id']
    delivery = {'response': digest(response_file), 'manifest': digest(incoming / 'sources.json'),
                'files': {r['path']: (digest(confined(incoming, r['path'])) if confined(incoming, r['path']).is_file() else None)
                          for r in read(incoming / 'sources.json')['files']}}
    fingerprint = hashlib.sha256(json.dumps(dict(parent=hashes, delivery=delivery, run_id=run_id), sort_keys=True).encode()).hexdigest()
    if output.exists():
        existing = verify_continuation(output)
        if existing['input_sha256'] != fingerprint:
            raise ValueError('Conflicting replay; result is immutable')
        return dict(run_id=run_id, output=output, replayed=True)
    for prior in state.get('repair_deliveries', []):
        if prior['response_id'] == response_id:
            if prior['delivery'] != delivery:
                raise ValueError('Conflicting response ID replay')
            return dict(run_id=state['run_id'], output=parent, replayed=True)
    if run_id in {d['run_id'] for d in state.get('repair_deliveries', [])}:
        raise ValueError('Run ID already belongs to an earlier continuation')
    matches = {key: match_item(key, queue['items'].get(key), state, response.get('actor_id')) for key in outcomes}
    batch = 'repair-response:' + response_id
    ordinal = state.get('evaluation_boundary', {}).get('local_ordinal', max(parsed['arrival_batches'])) + 1
    with tempfile.TemporaryDirectory(prefix='project-d-repairs-') as temp:
        evidence = Path(temp) / 'response-evidence'
        prior_evidence = parent if (parent / 'response-evidence').exists() else None
        combined, records, source_errors, _ = retain_delivery(incoming, evidence, prior_evidence,
            parsed.get('event_clock') or parsed.get('case_clock'), response_id)
        if {r['source_id'] for r in combined['files']} & {r['source_id'] for r in manifest['files']}:
            raise ValueError('Supplemental source IDs cannot replace native evidence')
        observations = manifest['files'] + combined['files']
        holds, admitted, affected = {}, [], set()
        for key, outcome in outcomes.items():
            if not isinstance(outcome, dict):
                raise ValueError('Outcome must be an object')
            if outcome.get('outcome') != 'supported':
                continue
            cid, claim = matches[key]
            item = queue['items'][key]
            try:
                allowed = {f'ordinary:{cid}:r{claim["revision"]}:supporting_evidence',
                           f'correction:{cid}:r{claim["revision"]}:expense-evidence'}
                returned = key.startswith(f'ordinary:{cid}:r{claim["revision"]}:review_return:')
                if key not in allowed and not returned:
                    raise ValueError('Repair type needs an unsupported authority/import adapter')
                wf = state['ordinary_workflows'][cid]
                if wf['status'] != 'pending' or wf['request'] or state['finance_reconciliations'][cid]['authorized_obligation']:
                    raise ValueError('Only pending, currently unauthorized claims are supported')
                assessment = verify_response_evidence(item, outcome, response_id, evidence)
                refs = outcome['source_refs'] + [outcome['assessment_ref']]
                for source_ref in refs:
                    sid = source_ref.split('@', 1)[0]
                    if sid in source_errors:
                        raise ValueError(source_errors[sid])
                if assessment.get('actor_id') != response.get('actor_id'):
                    raise ValueError('Assessment must bind the response actor')
                if returned:
                    returned_reply = return_context(state, key, cid, claim['revision'])
                    if (assessment.get('return_decision_ref') != ref(returned_reply['raw_record'])
                            or assessment.get('repair_requested') != returned_reply['repair_requested']):
                        raise ValueError('Returned work must bind its exact retained decision and repair request')
                candidate = deepcopy(parsed)
                changes = admit_records(candidate, state, claim, outcome, records, assessment)
                parsed = candidate
                admitted.append(dict(item_id=key, changes=changes))
                affected.add(cid)
            except (ValueError, TypeError, KeyError, IndexError, OSError, InvalidOperation) as exc:
                holds[key] = 'Response evidence held: ' + str(exc)
        for cid in sorted(affected):
            claim = matches[next(k for k, v in matches.items() if v[0] == cid)][1]
            before = state['finance_reconciliations'][cid]
            wf = connect_claim(parsed=parsed, claim=claim, decisions=state['source_record_history']['decisions'],
                finance_events=state['source_record_history']['finance_events'], finance=deepcopy(before),
                cancellations=cancellations, arrival_batch=ordinal, source_observations=observations,
                prior_finance=before, prior_workflow=state['ordinary_workflows'][cid],
                budget_data=state['budget_reconciliation'], prepaid_data=state['budget_reconciliation']['cost_attribution'],
                prior_budget_view=state['budget_reconciliation']['claim_views'][cid])
            if wf.pop('finance') != before or wf['request'] is not None or wf['status'] != 'pending':
                raise ValueError('Evidence continuation must not authorize reimbursement or change financial history')
            # Evidence does not supply the current reviewer response. Retain
            # returned work after its old packet becomes historical authority.
            for key, item in queue['items'].items():
                if item['status'] != 'open' or not key.startswith(f'ordinary:{cid}:r{claim["revision"]}:review_return:'):
                    continue
                reply = return_context(state, key, cid, claim['revision'])
                name = key.split(f'ordinary:{cid}:r{claim["revision"]}:', 1)[1]
                review_stage = next((s for s in wf['stages'] if s['stage'] == name), None)
                if review_stage is None:
                    review_stage = {'stage': name}
                    wf['stages'].append(review_stage)
                review_stage.update(status='BLOCKED', source_refs=reply['source_refs'],
                    detail='Returned evidence rechecked; a current human reviewer response is still required: ' + reply['repair_requested'],
                    owner=fields(reply['raw_record'])['Reviewer'], next_action='Obtain current source-bound reviewer response to the repaired evidence; no approval is inferred')
            state['ordinary_workflows'][cid] = wf
            state['ordinary_workflow_history'].append(dict(batch_id=batch, workflow=deepcopy(wf)))
            state['budget_reconciliation']['claim_views'][cid] = deepcopy(wf['budget_view'])
            _project(next(c for c in state['claims'] if c['claim_id'] == cid), wf, before)
        apply_partial_response(queue, response_id=response_id, item_outcomes=outcomes, run_id=run_id,
            batch_id=batch, evidence_directory=evidence, admission_errors=holds)
        _sync_ordinary_repairs(dict(repair_queue=queue,
            ordinary_workflows={cid: state['ordinary_workflows'][cid] for cid in affected},
            finance_reconciliations={cid: state['finance_reconciliations'][cid] for cid in affected}), run_id=run_id, batch_id=batch)
        validate_partial_response_journal(queue, evidence)
        state.setdefault('repair_deliveries', []).append(dict(response_id=response_id, delivery=delivery,
            run_id=run_id, batch_id=batch, admitted=admitted, holds=holds, source_errors=source_errors))
        state.update(mode=MODE, run_id=run_id, parent_run_id=read(parent / ('sources.json' if parent == root else 'continuation-state.json'))['run_id'],
            response=response, response_holds=holds, repair_queue=queue, revalidated_claims=sorted(affected),
            parent_run_path=os.path.relpath(parent, output),
            native_source_manifest_path=os.path.relpath(root / 'sources.json', output),
            travel_cancellations=cancellations, evaluation_boundary=dict(kind='repair-response', response_id=response_id,
                local_ordinal=ordinal, native_arrival_batch=None))
        parsed['repair_continuation'] = dict(mode=MODE, run_id=run_id,
            native_parent_path=os.path.relpath(root, output),
            evidence_binding={'path': 'response-evidence/sources.json', 'sha256': digest(evidence / 'sources.json')})
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(exist_ok=False)
        shutil.copytree(evidence, output / 'response-evidence')
        shutil.copyfile(response_file, output / 'response.json')
        write(output / 'continuation-state.json', state)
        write(output / 'continuation-input.json', parsed)
        write_repair_queue(queue, output / 'repair-queue.json')
        write_claims_csv(project_claim_outputs(state['claims'], queue), output / 'claims.csv')
        write(output / 'ordinary-workflow.json', dict(mode=MODE, run_id=run_id, claims=state['ordinary_workflows']))
        drafts, _ = render_follow_up_drafts(run_id=run_id, queue=queue, blockers=state['external_blockers'])
        (output / 'follow-up-drafts.md').write_text(drafts, encoding='utf-8')
        (output / 'report.md').write_text(_report(state), encoding='utf-8')
        outputs = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob('*') if p.is_file()}
        write(output / 'continuation.json', dict(version='repair-continuation/1', run_id=run_id,
            input_sha256=fingerprint, parent_path=os.path.relpath(parent, output), root_path=os.path.relpath(root, output),
            parent_hashes=hashes, output_hashes=outputs, fresh_native_reads_performed=False))
        verify_continuation(output)
    return dict(run_id=run_id, output=output, replayed=False)

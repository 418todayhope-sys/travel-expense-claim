"""Executed correction checks, with immutable evidence and monetary history."""
from copy import deepcopy

from .ordinary import expense_lines, fields, ref


def correction_changes(before, after):
    """Compare actual claim facts, including evidence changes with unchanged totals."""
    old, new = fields(before), fields(after)
    changes = {key: {'before': old.get(key), 'after': new.get(key)}
               for key in sorted(set(old) | set(new))
               if old.get(key) != new.get(key) and key not in {'Revision', 'Arrival batch'}}
    previous = {line['cost_id']: line for line in expense_lines(before)}
    current = {line['cost_id']: line for line in expense_lines(after)}
    # Source references change with the revision even when the line facts do not.
    def facts(line):
        return {k: v for k, v in line.items() if k != 'source_refs'} if line else None
    lines = [{'cost_id': key, 'before': facts(previous.get(key)), 'after': facts(current.get(key)),
              'changed': facts(previous.get(key)) != facts(current.get(key))}
             for key in sorted(set(previous) | set(current))]
    return {'fields': changes, 'expense_lines': lines,
            'unchanged_cost_ids': [line['cost_id'] for line in lines if not line['changed']],
            'source_refs': [ref(before), ref(after)]}


def record_executed_rechecks(domain, previous_domain, *, batch_id):
    """Called after connect_claim and Finance reconciliation actually execute."""
    for correction in domain['material_corrections']:
        claim_id = correction['claim_id']
        workflow = domain['ordinary_workflows'][claim_id]
        if workflow['revision'] != correction['to_revision']:
            continue
        if correction['arrival_batch'] == batch_id:
            revisions = domain['revision_history']['claim'][claim_id]['revisions']
            before = next(r['record'] for r in revisions if r['revision'] == correction['from_revision'])
            after = next(r['record'] for r in reversed(revisions) if r['revision'] == correction['to_revision'])
            correction['changed_dependencies'] = correction_changes(before, after)
            old = previous_domain.get('ordinary_workflows', {}).get(claim_id)
            correction['before_workflow'] = deepcopy(old)
            correction['before_finance'] = deepcopy(previous_domain.get('finance_reconciliations', {}).get(claim_id))
        correction.setdefault('executed_rechecks', []).append({
            'batch_id': batch_id, 'revision': workflow['revision'],
            'checks': deepcopy(workflow['stages']),
            'lines': deepcopy(workflow['lines']),
            'observed_reviews': deepcopy(workflow['observed_reviews']),
            'request': deepcopy(workflow['request']),
            'finance': deepcopy(domain['finance_reconciliations'][claim_id]),
            'status': workflow['status'],
            'basis': 'Current-revision ordinary evidence, approval, request and Finance checks executed; no human response created',
        })


def verification_document(domain, cancellations, *, run_id):
    data = {'run_id': run_id, 'mode': 'offline-replay', 'fresh_native_reads_performed': False,
            'corrections': deepcopy(domain['material_corrections']),
            'cancellations': deepcopy(cancellations),
            'cancellation_evidence': deepcopy(domain.get('cancellation_evidence', {})),
            'cancellation_issues': deepcopy(domain['cancellation_state']['issues'])}
    lines = ['# Correction and cancellation verification — OFFLINE REPLAY', '',
             'Retained evidence only. No fresh source execution, approvals, requests or payments generated.',
             'PASS means the stated local evidence check passed; BLOCKED requires the named evidence or authority.', '',
             '## Executed correction rechecks', '']
    for correction in data['corrections']:
        latest = correction['executed_rechecks'][-1]
        lines += [f"### {correction['claim_id']} r{correction['from_revision']} → r{correction['to_revision']}", '',
                  f"Arrival: {correction['arrival_batch']}. Changed facts: `{correction['changed_dependencies']}`", '',
                  f"Historical reviews excluded from current authority: {', '.join(correction['invalidated_decision_ids']) or 'none observed'}.", '',
                  '| Executed check | Result | Next action |', '|---|---|---|']
        for check in latest['checks']:
            lines.append(f"| {check['stage']} | {check['status']} | {check['owner']}: {check['next_action']} |")
        lines += ['', 'Executed check evidence:', '']
        for check in latest['checks']:
            lines.append(f"- {check['stage']}: {'; '.join(check['source_refs'])}")
        old = correction.get('before_finance') or {}
        new = latest['finance']
        lines += ['', f"Known net cash cents: {old.get('net_confirmed_cents')} → {new['net_confirmed_cents']}; "
                  f"recorded ledger difference cents: {old.get('recorded_ledger_balance_cents')} → {new['recorded_ledger_balance_cents']}. "
                  'Recorded ledger agreement does not prove current entitlement or closure.', '']
    lines += ['## Independent cancellation processes', '']
    for cancellation in cancellations:
        detail = data['cancellation_evidence'][cancellation['cancellation_id']]
        lines += [f"### {cancellation['cancellation_id']} — {cancellation['target_type']}", '',
                  f"State history: {' → '.join(h['action'] for h in detail['history'])}. "
                  f"Current linked claims: {detail['current_claim_ids']}; historical linked claims: {cancellation['affected_claim_ids']}. "
                  f"Observed request IDs: {cancellation['original_request_ids']}.", '',
                  f"Actor verification: {detail['actor_status']}. Finance disposition: {detail['disposition_status']}. "
                  f"Financial completion: {cancellation['financial_status']}; next owner: Finance.", '',
                  f"Source references: {'; '.join(detail['source_refs'])}", '',
                  f"Recorded dispositions (not full claim closure): `{detail['dispositions']}`", '']
    lines += ['## Remaining external blockers', '',
              'The native Notion policy remains inaccessible and the authoritative case clock remains unconfirmed. '
              'Policy eligibility, current authorization and final closure remain pending where unsupported. '
              'A cancelled transfer is a noncash event; only confirmed payments and linked refunds affect cash.', '']
    return data, '\n'.join(lines)

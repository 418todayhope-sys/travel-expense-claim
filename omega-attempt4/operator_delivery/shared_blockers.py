"""Decision 003: append-only shared facts and bidirectional case/repair views.

Consumes sealed Decision 002 outputs. It never writes to a repair queue, admits
Finance facts, or changes a case's financial state. No network adapter is used.
"""
from __future__ import annotations
import argparse
from collections import Counter, deque
from copy import deepcopy
import json
from pathlib import Path
import re

from operator_delivery import build as b, containment as d
from validation import validate as v

DECISION = 'decisions/decision-003-shared-blocker-linked-case-views.md'
SELECTED_KINDS = {'global_requirement', 'evidence_check', 'request_attribution', 'cancellation'}


def identity(fact_key):
    return 'blocker:' + v.digest(v.encoded(fact_key))


def paths_from(graph, root):
    adjacent = {n['node_id']: [] for n in graph['nodes']}
    for e in graph['edges']:
        adjacent[e['from']].append(e['to'])
    paths, pending = {root: [root]}, deque([root])
    while pending:
        here = pending.popleft()
        for target in sorted(adjacent[here]):
            if target not in paths:
                paths[target] = paths[here] + [target]
                pending.append(target)
    return paths


def case_id(claim_id, revision):
    return f'case:{claim_id}/r{revision}'


def derive(graph, snapshot, queue, previous=None, deliveries=()):
    """Pure projection; delivery notes cannot mutate financial or repair facts.

    Delivery IDs are immutable. An observed clarification requests rechecks only;
    an actual supported graph check is necessary to establish fact support.
    """
    d.verify(graph)
    batch = int(snapshot['batch_id'])
    if graph['through_batch'] != batch or queue['batch_id'] != snapshot['batch_id']:
        raise ValueError('Mismatched graph, snapshot and queue batch')
    if previous and batch < previous['through_batch']:
        raise ValueError('Shared history cannot move backwards')
    repairs = {i['record_id']: i for i in queue['items']}
    if len(repairs) != len(queue['items']):
        raise ValueError('Duplicate retained repair identity')
    nodes = {n['node_id']: n for n in graph['nodes']}
    previous = previous or {'blockers': [], 'delivery_ledger': []}
    prior = {item['blocker_id']: item for item in previous['blockers']}
    current = {}
    package = [i for i in repairs.values() if i['subject_type'] == 'package']

    def add(fact_key, node_ids, matching, scope, source_refs, reason, owner):
        ident = identity(fact_key)
        refs = sorted(set(source_refs))
        candidates = sorted({i['owner'] for i in matching})
        if len(candidates) == 1:
            owner = candidates[0]
        elif len(candidates) > 1:
            owner = 'Unresolved owner conflict'
        record = {'blocker_id': ident, 'fact_key': fact_key, 'graph_node_ids': sorted(node_ids),
                  'owner': owner, 'owner_candidates': candidates,
                  'owner_status': 'unresolved' if len(candidates) > 1 else 'recorded_role' if owner in ('Finance', 'Facilitator', 'Budget owner', 'Supervisor', 'Administration') else 'recorded_actor',
                  'source_refs': refs, 'evidence_artifacts': ['input:dependency_graph', 'input:repair_queue'],
                  'scope': scope, 'reason': reason, 'next_action': reason,
                  'direct_repair_ids': sorted(i['record_id'] for i in matching), 'case_links': [],
                  'fact_state': 'unresolved', 'clarification_state': 'none',
                  'state': 'open', 'required_recheck_case_ids': []}
        if not refs:
            record['evidence_gap'] = 'No native fact content is asserted; consult retained access/provenance and historical requirement evidence.'
            record['evidence_artifacts'].append('input:historical_assignment' if fact_key == 'graph:requirement:assignment_access' else 'input:snapshot_schema')
        current[ident] = record
        return record

    for n in graph['nodes']:
        key, kind = n['node_id'], n['kind']
        if kind not in SELECTED_KINDS:
            continue
        fact_key = 'graph:' + key
        # Supported shared purchases remain checks, not invented blockers. A
        # previously open fact stays in history when its evidence is supported.
        if n['status'] == 'supported' and identity(fact_key) not in prior:
            continue
        if kind == 'global_requirement':
            matching = [i for i in package if i['code'] == key.split(':', 1)[1]]
        elif kind == 'request_attribution':
            matching = [i for i in repairs.values() if i['subject_type'] == 'request' and i['subject_id'] == key.split(':', 1)[1]]
        elif kind == 'cancellation':
            matching = [i for i in repairs.values() if i['subject_type'] == 'cancellation' and i['subject_id'] == key.split(':', 1)[1]]
            # A no-financial-effect retired target is retained in the snapshot,
            # not invented as a missing-evidence repair or a new claim.
            if not any(i['state'] == 'open' for i in matching):
                process = next((p for p in snapshot['travel_cancellations'] if p['cancellation_id'] == key.split(':', 1)[1]), None)
                if identity(fact_key) in prior and process and process['status'] == 'confirmed' and process['financial_status'] == 'no-financial-effect':
                    record = add(fact_key, [key], matching, 'proven_dependencies', n['source_refs'],
                                 'Confirmed no-financial-effect process; prior repair history retained, cancelled travel authority not restored.', n['owner'])
                    record['state'] = 'clarified_no_case_repair'
                    record['fact_state'] = 'supported_no_financial_effect'
                continue
        else:
            reachable = paths_from(graph, key)
            matching = [i for i in repairs.values() if i['subject_type'] == 'claim' and i['code'] == n['check_code'] and
                        any('eligibility:' + ref in reachable for ref in i['source_refs'] if ':expense:' in ref)]
        record = add(fact_key, [key], matching,
                     'applicability_unknown' if kind == 'global_requirement' else 'proven_dependencies',
                     n['source_refs'], n['reason'], n['owner'])
        record['fact_state'] = 'supported' if n['status'] == 'supported' else 'unresolved'
        record['state'] = 'clarified_recheck_required' if n['status'] == 'supported' else 'open'
        if record['scope'] == 'applicability_unknown':
            continue
        reachable = paths_from(graph, key)
        for work in graph['claim_work']:
            targets = [target for target in (work['review_node'], work['financial_node']) if target in reachable]
            if not targets:
                continue
            claim = next(c for c in snapshot['claim_revision_history'] if (c['claim_id'], c['revision']) == (work['claim_id'], work['revision']))
            local = [i for i in matching if i['subject_type'] == 'claim' and (i['subject_id'], i['revision']) == (work['claim_id'], work['revision'])]
            if kind == 'request_attribution':
                # Exact request/claim-family evidence, never certified allocation.
                local += [i for i in repairs.values() if i['subject_type'] == 'claim' and
                          (i['subject_id'], i['revision']) == (work['claim_id'], work['revision']) and
                          i['code'] in ('request_revision_cost_binding', 'missing_request_basis') and
                          set(n['source_refs']) & set(i['source_refs'])]
            expense_ids = sorted({e['expense_id'] for e in claim['expenses'] if 'eligibility:' + e['expense_record_id'] in reachable})
            # Request-family paths have no expense allocation. Keep that unknown.
            link = {'case_id': case_id(work['claim_id'], work['revision']),
                    'claim_id': work['claim_id'], 'revision': work['revision'],
                    'trip_id': claim['trip_id'], 'trip_revision': claim['trip_revision'],
                    'expense_ids': expense_ids, 'repair_ids': sorted({i['record_id'] for i in local}),
                    'request_ids': [key.split(':', 1)[1]] if kind == 'request_attribution' else [],
                    'relationship': 'request_claim_family_only_no_cost_attribution' if kind == 'request_attribution' else 'proven_dependency',
                    'operation_paths': {target: reachable[target] for target in sorted(targets)},
                    'recheck_state': 'required' if record['fact_state'] == 'supported' else 'awaiting_fact'}
            record['case_links'].append(link)

    represented = {i for item in current.values() for i in item['direct_repair_ids']}
    for item in sorted(package, key=lambda i: i['record_id']):
        if item['record_id'] not in represented:
            add('package:' + item['subject_id'] + ':' + item['code'], [], [item],
                'applicability_unknown', item['source_refs'], item['reason'], item['owner'])

    # Keep absent facts with explicit unknown scope. Disappearance alone cannot
    # establish evidence, case completion, or a supersession/merge relationship.
    for ident, old in sorted(prior.items()):
        if ident not in current:
            record = deepcopy(old)
            record['state'] = 'not_observed_recheck_required'
            record['fact_state'] = 'unresolved'
            record['case_links'] = []
            current[ident] = record

    ledger = {event['event_id']: deepcopy(event) for event in previous['delivery_ledger']}
    for payload in deliveries:
        if type(payload.get('arrival_batch')) is not int or payload['arrival_batch'] < 1 or not isinstance(payload.get('event_id'), str) or not payload['event_id']:
            raise ValueError('Clarification requires positive arrival batch and nonempty event ID')
    for payload in sorted(deliveries, key=lambda e: (e['arrival_batch'], e['event_id'], v.digest(v.encoded(e)))):
        if payload['arrival_batch'] > batch:
            continue
        ident = payload['event_id']
        if not ident:
            raise ValueError('Clarification delivery requires immutable identity')
        # Arrival is observation metadata; exact business redelivery is a no-op.
        canonical = {k: value for k, value in payload.items() if k != 'arrival_batch'}
        fingerprint = v.digest(v.encoded(canonical))
        entry = ledger.setdefault(ident, {'event_id': ident, 'variants': {}, 'first_arrival_batch': payload['arrival_batch']})
        entry['first_arrival_batch'] = min(entry['first_arrival_batch'], payload['arrival_batch'])
        entry['variants'][fingerprint] = canonical
    for entry in ledger.values():
        values = list(entry['variants'].values())
        conflict = len(values) != 1
        entry['classification'] = 'conflicting_delivery' if conflict else 'unverified'
        for event in values:
            record = current.get(event.get('blocker_id'))
            if not record:
                entry['classification'] = 'unmatched_blocker'
                continue
            valid = (event.get('owner') == record['owner'] and record['owner_status'] != 'unresolved' and
                     event.get('fact_key') == record['fact_key'] and bool(event.get('reason')) and
                     bool(event.get('source_refs')) and all(ref in snapshot['source_index'] and
                         bool(snapshot['source_index'][ref].get('sha256')) and
                         event.get('source_hashes', {}).get(ref) == snapshot['source_index'][ref]['sha256']
                         for ref in event['source_refs']))
            if conflict or not valid:
                record['clarification_state'] = 'conflicting_or_unverified'
                record['state'] = 'open'
            else:
                entry['classification'] = 'clarification_recorded_not_case_resolution'
                record['clarification_state'] = 'partial' if event.get('partial', True) else 'received_pending_verification'
                if record['fact_state'] != 'supported':
                    record['state'] = 'clarification_received_recheck_required'
                record['source_refs'] = sorted(set(record['source_refs'] + event['source_refs']))
            record.setdefault('delivery_ids', []).append(entry['event_id'])

    for ident, record in sorted(current.items()):
        record['case_links'].sort(key=lambda link: link['case_id'])
        record['delivery_ids'] = sorted(set(record.get('delivery_ids', [])))
        record['required_recheck_case_ids'] = sorted(link['case_id'] for link in record['case_links'] if
                                                    record['state'] != 'open' or link['recheck_state'] == 'required')
        old = prior.get(ident)
        state = {k: deepcopy(value) for k, value in record.items() if k not in ('history', 'first_seen_batch', 'last_seen_batch')}
        history = deepcopy(old['history']) if old else []
        # One reproducible observation per batch. Same-batch replay replaces its
        # identical observation; it does not append another lifecycle transition.
        history = [event for event in history if event['batch'] != batch]
        history.append({'batch': batch, 'observation': state})
        record['history'] = history
        record['first_seen_batch'] = old['first_seen_batch'] if old else batch
        record['last_seen_batch'] = batch

    cases = []
    for claim in sorted(snapshot['claim_revision_history'], key=lambda c: (c['claim_id'], c['revision'])):
        ident = case_id(claim['claim_id'], claim['revision'])
        local = [deepcopy(i) for i in repairs.values() if i['subject_type'] == 'claim' and
                 (i['subject_id'], i['revision']) == (claim['claim_id'], claim['revision'])]
        links = [{'blocker_id': record['blocker_id'], **deepcopy(link)} for record in current.values() for link in record['case_links'] if link['case_id'] == ident]
        related = sorted({rid for link in links for record in [current[link['blocker_id']]] for rid in record['direct_repair_ids'] if repairs.get(rid, {}).get('subject_type') == 'request'})
        cases.append({'case_id': ident, 'claim_id': claim['claim_id'], 'revision': claim['revision'],
                      'current_at_batch': claim['current_at_batch'], 'trip_id': claim['trip_id'], 'trip_revision': claim['trip_revision'],
                      'expense_ids': [e['expense_id'] for e in claim['expenses']], 'source_refs': claim['source_refs'],
                      'requirements': sorted(local, key=lambda i: i['record_id']), 'blocker_links': sorted(links, key=lambda link: link['blocker_id']),
                      'related_request_repair_ids': related,
                      'remaining_open_repair_ids': sorted(i['record_id'] for i in local if i['state'] == 'open'),
                      'financial_state': 'held' if claim['current_at_batch'] else 'historical_revision_no_current_authority',
                      'financial_closure': 'unresolved',
                      'business_disposition': deepcopy(claim['business_disposition'])})
    mapping = []
    for ident, repair in sorted(repairs.items()):
        mapping.append({'repair_id': ident, 'state': repair['state'], 'subject_type': repair['subject_type'],
                        'case_ids': [c['case_id'] for c in cases if any(i['record_id'] == ident for i in c['requirements'])],
                        'blocker_ids': sorted(item['blocker_id'] for item in current.values() if ident in item['direct_repair_ids'] or any(ident in link['repair_ids'] for link in item['case_links'])),
                        'disposition': 'retained_without_repair_state_change'})
    result = {'schema_version': 'omega4-shared-blockers/1', 'through_batch': batch,
              'blockers': [current[k] for k in sorted(current)], 'cases': cases,
              'evidence_index': {
                  'input:dependency_graph': {'path': f'retained-run/dependencies/{batch:03}.json', 'sha256': v.digest(v.encoded(graph))},
                  'input:repair_queue': {'path': f'retained-run/queue/{batch:03}.json', 'sha256': v.digest(v.encoded(queue))},
                  'input:historical_assignment': {'path': 'validation/references/assignment-captured-20261016.txt',
                      'sha256': v.digest((v.ROOT / 'validation/references/assignment-captured-20261016.txt').read_bytes())},
                  'input:snapshot_schema': {'path': 'snapshot.schema.json', 'sha256': v.digest(b.SCHEMA.read_bytes())}},
              'source_index': {ref: deepcopy(snapshot['source_index'][ref]) for ref in sorted(
                  {ref for item in current.values() for ref in item['source_refs']} |
                  {ref for case in cases for ref in case['business_disposition']['source_refs']})},
              'repair_mapping': mapping, 'delivery_ledger': [ledger[k] for k in sorted(ledger)],
              'unscoped_package_blocker_ids': sorted(i['blocker_id'] for i in current.values() if i['scope'] == 'applicability_unknown'),
              'summary': {'central_records': len(current), 'central_states': dict(Counter(i['state'] for i in current.values())),
                          'case_views': len(cases), 'current_cases': sum(c['current_at_batch'] for c in cases),
                          'case_links': sum(len(i['case_links']) for i in current.values()),
                          'mapped_repairs': len(mapping), 'open_repairs': sum(i['state'] == 'open' for i in repairs.values()),
                          'unscoped_package_records': sum(i['scope'] == 'applicability_unknown' for i in current.values()),
                          'actual_financial_closures': 0}}
    verify_projection(result, graph, snapshot, queue)
    return result


def verify_projection(value, graph, snapshot, queue):
    repairs = {i['record_id']: i for i in queue['items']}
    records = {i['blocker_id']: i for i in value['blockers']}
    cases = {c['case_id']: c for c in value['cases']}
    if len(records) != len(value['blockers']) or len(cases) != len(value['cases']):
        raise ValueError('Duplicate blocker/case identity')
    if set(cases) != {case_id(c['claim_id'], c['revision']) for c in snapshot['claim_revision_history']}:
        raise ValueError('Missing claim/revision view')
    if {i['repair_id'] for i in value['repair_mapping']} != set(repairs):
        raise ValueError('Repair identity dropped or invented')
    pairs = {(e['from'], e['to']) for e in graph['edges']}
    for item in records.values():
        if any(ref not in value['evidence_index'] for ref in item['evidence_artifacts']) or any(ref not in value['source_index'] for ref in item['source_refs']):
            raise ValueError('Unresolved evidence locator')
        if item['blocker_id'] != identity(item['fact_key']) or not set(item['direct_repair_ids']) <= set(repairs):
            raise ValueError('Invalid blocker identity or dangling repair')
        if item['scope'] == 'applicability_unknown' and item['case_links']:
            raise ValueError('Unknown package scope cannot invent affected cases')
        for link in item['case_links']:
            if link['case_id'] not in cases or not set(link['repair_ids']) <= set(repairs):
                raise ValueError('Dangling blocker/case/repair link')
            if not any(l['blocker_id'] == item['blocker_id'] and all(l[k] == val for k, val in link.items()) for l in cases[link['case_id']]['blocker_links']):
                raise ValueError('Missing reverse blocker link')
            for target, path in link['operation_paths'].items():
                expected_targets = {f"review:{link['claim_id']}/r{link['revision']}", f"financial:{link['claim_id']}/r{link['revision']}"}
                if not path or path[-1] != target or target not in expected_targets:
                    raise ValueError('Dependency path has wrong case endpoint')
                if path[0] not in item['graph_node_ids'] or any(pair not in pairs for pair in zip(path, path[1:])):
                    raise ValueError('Unproven case dependency path')
    for case in cases.values():
        original = next(c for c in snapshot['claim_revision_history'] if (c['claim_id'], c['revision']) == (case['claim_id'], case['revision']))
        if case['business_disposition'] != original['business_disposition']:
            raise ValueError('Case business disposition differs from retained revision evidence')
        expected = sorted([i for i in repairs.values() if i['subject_type'] == 'claim' and
                           (i['subject_id'], i['revision']) == (case['claim_id'], case['revision'])], key=lambda i: i['record_id'])
        if case['requirements'] != expected or case['financial_closure'] != 'unresolved' or case['financial_state'] != ('held' if case['current_at_batch'] else 'historical_revision_no_current_authority'):
            raise ValueError('Case requirements/history or financial state changed')
        if case['remaining_open_repair_ids'] != sorted(i['record_id'] for i in expected if i['state'] == 'open'):
            raise ValueError('Shared clarification cleared a local repair')
        for link in case['blocker_links']:
            record = records.get(link['blocker_id'])
            if not record or not any(all(link.get(k) == val for k, val in forward.items()) for forward in record['case_links']):
                raise ValueError('Unproven reverse link')
    return value['summary']


def case_document(value):
    return {'schema_version': 'omega4-linked-case-views/1', 'through_batch': value['through_batch'],
            'cases': value['cases'], 'repair_mapping': value['repair_mapping'],
            'unscoped_package_blocker_ids': value['unscoped_package_blocker_ids']}


def navigation(value):
    """Local Markdown navigation uses hash anchors, never source-supplied HTML."""
    anchor = lambda ident: 'id-' + v.digest(v.encoded(ident))
    blockers = ['# Shared blockers', '', 'Clarification is not case resolution. See [case views](cases.md) and [full register](shared-blockers.json).', '']
    cases = ['# Linked claim/revision views', '', 'Every requirement and its history is preserved in [case-views.json](case-views.json). See [shared blockers](blockers.md).', '']
    for item in value['blockers']:
        blockers += [f'<a id="{anchor(item["blocker_id"])}"></a>', '', f"## {item['blocker_id']}", '',
                     f"Owner: {item['owner']}. State: {item['state']}. Fact: {item['fact_state']}. Scope: {item['scope']}.", '',
                     item['reason'], '', 'Existing repair IDs: ' + ', '.join(item['direct_repair_ids']), '']
        for link in item['case_links']:
            blockers.append(f"- [{link['claim_id']}/r{link['revision']}](cases.md#{anchor(link['case_id'])}); costs: {', '.join(link['expense_ids']) or 'no certified cost allocation'}; recheck: {link['recheck_state']}.")
        if not item['case_links']:
            blockers += ['No proven current case applicability; do not invent case links.', '']
    for case in value['cases']:
        cases += [f'<a id="{anchor(case["case_id"])}"></a>', '', f"## {case['claim_id']}/r{case['revision']}", '',
                  f"Trip: {case['trip_id']}/r{case['trip_revision']}. Financial state: {case['financial_state']}; closure: {case['financial_closure']}.", '',
                  f"Own repairs: {len(case['requirements'])}; still open: {len(case['remaining_open_repair_ids'])}.", '']
        disposition = case['business_disposition']
        if disposition['value']:
            cases += [f"Business disposition: {disposition['value']}: {disposition['reason']} Evidence: {', '.join(disposition['source_refs'])}. Financial holds and repairs remain in force.", '']
        for link in case['blocker_links']:
            cases.append(f"- [Shared blocker](blockers.md#{anchor(link['blocker_id'])}): {link['blocker_id']}; {link['relationship']}.")
        cases += ['', 'Remaining local repair IDs: ' + ', '.join(case['remaining_open_repair_ids']), '']
    return '\n'.join(blockers).encode(), '\n'.join(cases).encode()


def report_text(run_id, source_summary, projections):
    final = projections[-1]
    rows = ['# Decision 003 operator handoff — ' + run_id, '',
            'Offline projection of the verified retained Decision 002 run. No new stakeholder answer, source access, approval, payment, or financial closure is asserted.', '',
            'Use [blockers.md](blockers.md) and [cases.md](cases.md) for two-way navigation; [shared-blockers.json](shared-blockers.json) and [case-views.json](case-views.json) retain exact IDs, evidence, paths, requirements, and history.', '',
            '| Batch | Central records | Case links | Case views | Current cases | Open repairs |',
            '|---|---:|---:|---:|---:|---:|']
    for value in projections:
        x = value['summary']
        rows.append(f"| {value['through_batch']} | {x['central_records']} | {x['case_links']} | {x['case_views']} | {x['current_cases']} | {x['open_repairs']} |")
    rows += ['', '## Supported current business dispositions', '']
    for case in final['cases']:
        disposition = case['business_disposition']
        if case['current_at_batch'] and disposition['value']:
            rows.append(f"- {case['claim_id']}/r{case['revision']}: {disposition['value']} — {disposition['reason']} Evidence: {', '.join(disposition['source_refs'])}.")
    rows += ['', 'Business disposition is separate from financial readiness: all current claims remain financially held; no repairs are cleared and no payment or closure is authorized.']
    rows += ['', '## Before and after', '',
             f"Repair identities/history: {len(final['repair_mapping'])} -> {len(final['repair_mapping'])}; open repairs: {source_summary['open_repairs']} -> {final['summary']['open_repairs']}. Zero repair records are rewritten, renumbered or cleared by this projection.",
             f"Claim revisions: {source_summary['claim_revisions']} -> {final['summary']['case_views']}; current claims: {source_summary['current_claims']} -> {final['summary']['current_cases']}; financial holds: {source_summary['current_claims']} -> {final['summary']['current_cases']}; financial closures: 0 -> 0.",
             f"Request facts: {source_summary['request_facts']} unchanged; admitted Finance events: {source_summary['admitted_finance_events']} unchanged; settled/refund/net cents: {source_summary['admitted_settled_cents']}/{source_summary['admitted_refund_cents']}/{source_summary['admitted_net_cents']} unchanged.",
             f"Normalization diagnostics: {source_summary['normalization_diagnostics']} unchanged. {final['summary']['unscoped_package_records']} package requirements stay unscoped, with no invented all-case defects. Central states: {json.dumps(final['summary']['central_states'], sort_keys=True)}.", '',
             '## Boundaries and limitations', '',
             'Supported C03/C24 shared checks are not open blockers. Missing shared purchase evidence can create one central record linked to both cases. C08/C114 merchant proof remains separate. TC018 targets original T18/r1, not replacement T18B/r1; REQ-C18 links support family reconciliation only, never certified replacement cost allocation.',
             'A clarification records a supplied note and requests independent case rechecks. Fact support requires a supported retained graph check; it never clears local merchant proof, current approvals, Finance allocation or Decision 001 holds. The retained run supplies no clarification deliveries.',
             'Package applicability and some named owners remain unknown. No owner authority is inferred from coordinator ownership. New native/package definitions still require the responsible source adapter and verified graph re-evaluation; arbitrary clarification text cannot certify them. Missing sources and same-amount corrections remain unresolved as recorded.',
             'Graph purchase identity changes create a new fact identity; old identities/history remain not_observed_recheck_required until an evidenced supersession/merge is supplied. No merge is guessed. Base tables lack arrival labels. Historical revisions retain their own repairs; active claim views do not substitute for historical records.',
             'Retained queues and the full input run are copied byte-for-byte under retained-run/. New snapshots bind their predecessor and the corresponding graph, queue, blocker register and case view. The earlier 703-open-item register is also preserved within retained-run/.', '']
    return '\n'.join(rows).encode()


def build(source_run, output, run_id, clarifications=None):
    source_run, output = source_run.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError('Refusing existing shared-blocker output: ' + str(output))
    if output.is_relative_to(source_run) or source_run.is_relative_to(output):
        raise ValueError('Output must be separate from the retained run')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', run_id):
        raise ValueError('Use a nonempty filesystem-safe run ID')
    b.verify(source_run)
    original = json.loads((source_run / 'operator-manifest.v1.json').read_bytes())
    if not original.get('dependency_containment'):
        raise ValueError('Decision 003 requires a verified Decision 002 run')
    deliveries = json.loads(clarifications.read_bytes()) if clarifications else []
    if not isinstance(deliveries, list):
        raise ValueError('Clarification input must be a list of retained delivery notes')
    projections, states, previous = [], [], None
    for batch in range(1, original['through_batch'] + 1):
        snapshot = json.loads((source_run / f'batches/{batch:03}.json').read_bytes())
        graph = json.loads((source_run / f'dependencies/{batch:03}.json').read_bytes())
        queue = json.loads((source_run / f'queue/{batch:03}.json').read_bytes())
        projection = derive(graph, snapshot, queue, previous, deliveries)
        projections.append(projection); states.append(snapshot); previous = projection
    output.mkdir(parents=True, exist_ok=False)
    for path in sorted(source_run.rglob('*')):
        if path.is_file():
            b.write_once(output, 'retained-run/' + str(path.relative_to(source_run)), path.read_bytes())
    if clarifications:
        b.write_once(output, 'clarifications.original.json', clarifications.read_bytes())
    predecessor = None
    for projection, old in zip(projections, states):
        batch = old['batch_id']
        registry = b.write_once(output, f'shared-blockers/{batch}.json', v.encoded(projection))
        views = b.write_once(output, f'case-views/{batch}.json', v.encoded(case_document(projection)))
        snap = deepcopy(old)
        snap.update(run_id=run_id, predecessor=predecessor, shared_blocker_binding=registry, case_view_binding=views)
        for key in ('source_binding', 'queue_binding', 'dependency_binding'):
            snap[key]['path'] = 'retained-run/' + snap[key]['path']
        b.check_snapshot(snap)
        predecessor = b.write_once(output, f'batches/{batch}.json', v.encoded(snap))
    final = projections[-1]
    b.write_once(output, 'shared-blockers.json', v.encoded(final))
    b.write_once(output, 'case-views.json', v.encoded(case_document(final)))
    b.write_once(output, 'repair-queue.json', (source_run / 'repair-queue.json').read_bytes())
    b.write_once(output, 'claims.csv', (source_run / 'claims.csv').read_bytes())
    blockers_md, cases_md = navigation(final)
    b.write_once(output, 'blockers.md', blockers_md); b.write_once(output, 'cases.md', cases_md)
    b.write_once(output, 'report.md', report_text(run_id, original['summary'], projections))
    paths = [v.ROOT / DECISION, Path(__file__).resolve(), v.ROOT / 'operator_delivery/shared-blockers.md',
             v.ROOT / 'tests/test_shared_blockers.py']
    bindings = deepcopy(original['input_bindings']) + [{'path': b.relative(path), 'sha256': v.digest(path.read_bytes())} for path in paths]
    if clarifications:
        bindings.append({'path': b.relative(clarifications), 'sha256': v.digest(clarifications.read_bytes())})
    sealed = {'schema_version': 'omega4-shared-blocker-manifest/1', 'run_id': run_id,
              'mode': 'offline-retained-projection', 'through_batch': original['through_batch'],
              'source_run': {'path': b.relative(source_run / 'operator-manifest.v1.json'),
                             'sha256': v.digest((source_run / 'operator-manifest.v1.json').read_bytes())},
              'input_bindings': bindings, 'final_batch': predecessor,
              'summary': final['summary'], 'before': original['summary'],
              'files': [{'path': str(path.relative_to(output)), 'sha256': v.digest(path.read_bytes())}
                        for path in sorted(output.rglob('*')) if path.is_file()]}
    b.write_once(output, 'shared-blocker-manifest.v1.json', v.encoded(sealed))
    verify(output)
    return sealed


def verify(output):
    output = output.resolve()
    sealed = json.loads((output / 'shared-blocker-manifest.v1.json').read_bytes())
    names = [entry['path'] for entry in sealed['files']]
    if len(names) != len(set(names)) or 'shared-blocker-manifest.v1.json' in names:
        raise ValueError('Duplicate or self-hashing manifest')
    if {str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()} != set(names) | {'shared-blocker-manifest.v1.json'}:
        raise ValueError('Missing or unbound output file')
    hashes = {}
    for entry in sealed['files']:
        data = b.safe_path(output, entry['path']).read_bytes()
        if v.digest(data) != entry['sha256']:
            raise ValueError('Output hash mismatch: ' + entry['path'])
        hashes[entry['path']] = entry['sha256']
    seen = set()
    for binding in sealed['input_bindings']:
        path = (v.ROOT / binding['path']).resolve()
        if path in seen or v.digest(path.read_bytes()) != binding['sha256']:
            raise ValueError('Changed or duplicate bound input: ' + binding['path'])
        seen.add(path)
    retained = output / 'retained-run'
    b.verify(retained)
    base = json.loads((retained / 'operator-manifest.v1.json').read_bytes())
    if sealed['through_batch'] != base['through_batch'] or v.digest((retained / 'operator-manifest.v1.json').read_bytes()) != sealed['source_run']['sha256'] or base['summary'] != sealed['before']:
        raise ValueError('Retained source-run lineage mismatch')
    deliveries = json.loads((output / 'clarifications.original.json').read_bytes()) if (output / 'clarifications.original.json').exists() else []
    previous = predecessor = None
    projections = []
    for number in range(1, sealed['through_batch'] + 1):
        batch = f'{number:03}'
        graph = json.loads((retained / f'dependencies/{batch}.json').read_bytes())
        old = json.loads((retained / f'batches/{batch}.json').read_bytes())
        queue = json.loads((retained / f'queue/{batch}.json').read_bytes())
        value = json.loads((output / f'shared-blockers/{batch}.json').read_bytes())
        expected = derive(graph, old, queue, previous, deliveries)
        if value != expected:
            raise ValueError('Shared register differs from retained evidence/history')
        view = case_document(value)
        if (output / f'case-views/{batch}.json').read_bytes() != v.encoded(view):
            raise ValueError('Linked case views differ from central register')
        snap = json.loads((output / f'batches/{batch}.json').read_bytes())
        b.check_snapshot(snap)
        expected_snap = deepcopy(old)
        expected_snap.update(run_id=sealed['run_id'], predecessor=predecessor,
                             shared_blocker_binding={'path': f'shared-blockers/{batch}.json', 'sha256': hashes[f'shared-blockers/{batch}.json']},
                             case_view_binding={'path': f'case-views/{batch}.json', 'sha256': hashes[f'case-views/{batch}.json']})
        for key in ('source_binding', 'queue_binding', 'dependency_binding'):
            expected_snap[key]['path'] = 'retained-run/' + expected_snap[key]['path']
        if snap != expected_snap:
            raise ValueError('Snapshot changed financial facts, repair identity or graph bindings')
        for key in ('source_binding', 'queue_binding', 'dependency_binding', 'shared_blocker_binding', 'case_view_binding'):
            binding = snap[key]
            if hashes.get(binding['path']) != binding['sha256']:
                raise ValueError('Broken snapshot binding')
        predecessor = {'path': f'batches/{batch}.json', 'sha256': hashes[f'batches/{batch}.json']}
        projections.append(value); previous = value
    if sealed['final_batch'] != predecessor or sealed['summary'] != previous['summary']:
        raise ValueError('Manifest final summary/chain mismatch')
    for filename in ('repair-queue.json', 'claims.csv'):
        if (output / filename).read_bytes() != (retained / filename).read_bytes():
            raise ValueError('Retained repair/financial output was rewritten')
    expected_files = {'shared-blockers.json': v.encoded(previous), 'case-views.json': v.encoded(case_document(previous)),
                      'report.md': report_text(sealed['run_id'], base['summary'], projections)}
    expected_files['blockers.md'], expected_files['cases.md'] = navigation(previous)
    for name, expected in expected_files.items():
        if (output / name).read_bytes() != expected:
            raise ValueError('Final operator view differs: ' + name)
    return {'run_id': sealed['run_id'], 'verified_snapshots': sealed['through_batch'],
            'verified_files': len(names), **previous['summary']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build')
    create.add_argument('--source-run', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--run-id', required=True)
    create.add_argument('--clarifications', type=Path)
    check = sub.add_parser('verify'); check.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'verify':
            print(json.dumps(verify(args.output), sort_keys=True)); return 0
        sealed = build(args.source_run, args.output, args.run_id, args.clarifications)
        print(json.dumps(sealed['summary'], sort_keys=True)); return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc)); return 1


if __name__ == '__main__':
    raise SystemExit(main())

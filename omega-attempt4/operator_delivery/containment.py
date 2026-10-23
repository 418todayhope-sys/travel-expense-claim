"""Decision 002: evidence-backed directed dependencies, independent of closure.

Edges point from prerequisites to dependent work. Candidate Finance allocations
are annotations, never propagation edges. A completed check is not an approval.
"""
from collections import Counter, deque
from copy import deepcopy
from validation import validate as v

DECISION = 'decisions/decision-002-dependency-based-containment.md'


def claim_key(c):
    return f"{c['claim_id']}/r{c['revision']}"


def propagate(nodes, edges):
    """Deterministic shortest source-to-work paths for every unsatisfied root."""
    adjacent = {n: [] for n in nodes}
    for e in edges:
        adjacent[e['from']].append(e['to'])
    impacts = {}
    for root in sorted(n for n, value in nodes.items() if value['status'] != 'supported'):
        paths, pending = {root: [root]}, deque([root])
        while pending:
            here = pending.popleft()
            for target in sorted(adjacent[here]):
                if target not in paths:
                    paths[target] = paths[here] + [target]
                    pending.append(target)
        for target, path in sorted(paths.items()):
            impacts.setdefault(target, []).append({'root': root, 'path': path})
    return impacts


def evaluate(doc, report, result):
    policy = v.evaluate(doc, report, result['through_batch'])
    nodes, edges = {}, {}

    def node(ident, kind, refs, status='supported', reason='', owner='Administration', **extra):
        entry = {'node_id': ident, 'kind': kind, 'source_refs': sorted(set(refs)),
                 'status': status, 'reason': reason, 'owner': owner, **extra}
        if ident in nodes:
            old = nodes[ident]
            old['source_refs'] = sorted(set(old['source_refs'] + entry['source_refs']))
            if old['status'] != status:
                old['status'] = 'unresolved'
                old['reason'] = 'Conflicting assessments of shared evidence; recheck all occurrences.'
        else:
            nodes[ident] = entry
        return ident

    def edge(source, target, kind, refs):
        refs = sorted(set(refs))
        assert refs, 'A dependency requires retained evidence/rule references'
        ident = v.digest(v.encoded([source, target, kind]))
        edges[ident] = {'edge_id': ident, 'from': source, 'to': target,
                        'kind': kind, 'source_refs': refs, 'proof': 'retained_evidence_and_policy'}

    shared = []
    certification = node('workflow:certification', 'operation', ['policy:clock'])
    for f in result['validation_global_findings']:
        ident = node('requirement:' + f['code'], 'global_requirement', f['source_refs'],
                     f['status'], f['reason'], f['owner'], scope='unresolved_package_requirement')
        edge(ident, certification, 'package_certification_requires_definition', f['source_refs'] or ['policy:clock'])
        shared.append(ident)

    contexts = {}
    for pc in policy['claims']:
        c = next(x for x in doc['claims'] if x['record_id'] == pc['source_ref'])
        rc = next(x for x in result['claims'] if (x['claim_id'], x['revision']) == (c['claim_id'], c['revision']))
        key, refs = claim_key(c), [c['record_id']]
        review = node('review:' + key, 'operation', refs)
        finance = node('financial:' + key, 'operation', refs)
        edge(review, finance, 'current_review_required', refs + ['policy:freshness'])
        check_ids, proof_ids = [], []
        for line in pc['expenses']:
            expense = next(e for e in c['expenses'] if e['record_id'] == line['expense_record_id'])
            # Full retained purchase tuple, not merely employee/amount/cost ID.
            gross = v.number(expense['original_amount'])
            numeric_gross = format(gross.normalize(), 'f') if gross is not None else ['unknown', expense['record_id']]
            identity = [c['employee_id'], c['trip_id'], c['trip_revision'], expense['expense_id'],
                        expense['receipt_id'], expense['currency'], numeric_gross]
            purchase = v.digest(v.encoded(identity))
            eligibility = node('eligibility:' + expense['record_id'], 'operation', [expense['record_id']])
            edge(eligibility, review, 'review_uses_expense', refs + [expense['record_id']])
            for f in line['findings']:
                common = f['code'] in ('receipt_identity', 'merchant_payment', 'receipt_date')
                ident = ('purchase:' + purchase if common else 'expense:' + expense['record_id']) + ':' + f['code']
                check = node(ident, 'evidence_check' if common else 'policy_check', f['source_refs'],
                             f['status'], f['reason'], f['owner'], executed=True, check_code=f['code'])
                edge(check, eligibility, 'expense_requires_check', f['source_refs'])
                check_ids.append(check)
                if f['code'] in ('receipt_identity', 'merchant_payment'):
                    proof_ids.append(check)
        for f in pc['findings']:
            # Cost-ID-only prior obligations remain financial uncertainty, not
            # proof that two distinct purchase identities share evidence.
            ident = node('claim-check:' + key + ':' + f['code'] + ':' + v.digest(v.encoded(f['source_refs'])),
                         'policy_check', f['source_refs'], f['status'], f['reason'], f['owner'], executed=True)
            edge(ident, review if f['code'] != 'original_request_finance_hold' else finance,
                 'claim_basis_requires_check', f['source_refs'])
        for f in pc['claim_review']['findings'] if pc['claim_review'] else []:
            ident = node('review-check:' + key + ':' + v.digest(v.encoded(f)), 'review_check',
                         f['source_refs'], f['status'], f['reason'], f['owner'], executed=True)
            edge(ident, review, 'exact_revision_review', f['source_refs'])
        for f in rc['diagnostics']:
            if f['code'] == 'inherited_validation_limits':
                continue
            ident = node('financial-check:' + key + ':' + v.digest(v.encoded(f)), 'financial_check',
                         f['source_refs'], f['status'], f['reason'], f['owner'])
            edge(ident, finance, 'financial_evidence_required', f['source_refs'] or refs)
        triprows = [t for t in v.rows(doc, 'Trips') if (t['values']['Trip reference'], t['values']['Trip revision']) == (c['trip_id'], c['trip_revision'])]
        trip = node(f"trip:{c['trip_id']}/r{c['trip_revision']}", 'travel_authority', [t['record_id'] for t in triprows] + refs)
        edge(trip, review, 'review_uses_exact_travel_basis', refs + [t['record_id'] for t in triprows])
        for t in triprows:
            tv = t['values']
            if tv['Permit reference']:
                permit = node(f"permit:{tv['Permit reference']}/r{tv['Permit revision']}", 'travel_authority', [t['record_id']])
                edge(permit, trip, 'trip_requires_exact_permit', [t['record_id'], 'policy:permit'])
        contexts[key] = {'claim_id': c['claim_id'], 'revision': c['revision'], 'current_at_batch': pc['current_at_batch'],
                         'review_node': review, 'financial_node': finance, 'check_ids': sorted(set(check_ids)),
                         'proof_ids': sorted(set(proof_ids)), 'trip_node': trip}

    for cancel in result['travel_cancellations']:
        # Invalid/orphan records cannot establish a cancellation dependency.
        if cancel['business_state'] not in ('requested', 'confirmed'):
            continue
        refs = cancel['source_refs']
        ident = node('cancellation:' + cancel['cancellation_id'], 'cancellation', refs, 'blocked',
                     'Exact target arrangements/review readiness paused or retired; no money is erased.', 'Supervisor')
        target = (f"trip:{cancel['trip_id']}/r{cancel['trip_revision']}" if cancel['target_type'] == 'trip'
                  else f"permit:{cancel['permit_id']}/r{cancel['permit_revision']}")
        if target not in nodes:
            node(target, 'travel_authority', refs)
        edge(ident, target, 'exact_cancellation_target', refs + ['policy:cancellation'])
    for request in result['requests']:
        ident = node('request:' + request['request_id'], 'request_attribution', request['source_refs'], 'unresolved',
                     'Request/claim link is explicit; revision/cost attribution remains unresolved.', 'Finance')
        for context in contexts.values():
            if context['claim_id'] == request['claim_id']:
                edge(ident, context['financial_node'], 'claim_family_financial_reconciliation_only', request['source_refs'])
    ordered_edges = [edges[k] for k in sorted(edges)]
    impacts = propagate(nodes, ordered_edges)
    work = []
    for key, ctx in sorted(contexts.items()):
        checks = ctx.pop('check_ids'); proofs = ctx.pop('proof_ids')
        work.append({**ctx, 'claim_key': key, 'evidence_processing_state': 'partial' if any(i in impacts for i in proofs) else 'independently_resumable',
                     'executed_check_ids': checks, 'executed_check_count': len(checks),
                     'missing_proof_ids': [i for i in proofs if i in impacts],
                     'review_state': 'held' if ctx['review_node'] in impacts else 'checked',
                     'financial_state': 'held', 'financial_closure': 'unresolved',
                     'workflow_certification': 'unresolved' if shared else 'checked'})
    value = {'schema_version': 'omega4-dependency-containment/1', 'through_batch': result['through_batch'],
             'decision': {'path': DECISION, 'sha256': v.digest((v.ROOT / DECISION).read_bytes())},
             'nodes': [nodes[k] for k in sorted(nodes)], 'edges': ordered_edges, 'impacts': impacts,
             'claim_work': work, 'global_requirement_ids': sorted(shared),
             'candidate_request_allocations': [{'request_id': q['request_id'], 'basis_links': q['basis_links']} for q in result['requests']],
             'limitations': ['Independent evidence work is not financial readiness or closure.',
                 'Global scope definitions remain unresolved; package certification stays held separately.',
                 'Base tables lack arrival labels; inherited source-availability limitation remains.'],
             'summary': {'nodes': len(nodes), 'edges': len(ordered_edges),
                         'hold_roots': sum(n['status'] != 'supported' for n in nodes.values()),
                         'impacted_nodes': len(impacts), 'global_requirements': len(shared),
                         'current_evidence_states': dict(Counter(w['evidence_processing_state'] for w in work if w['current_at_batch'])),
                         'executed_expense_checks': sum(w['executed_check_count'] for w in work)}}
    verify(value)
    return value


def verify(graph):
    nodes = {n['node_id']: n for n in graph['nodes']}
    if len(nodes) != len(graph['nodes']):
        raise ValueError('Duplicate dependency node')
    edges = graph['edges']
    if len({e['edge_id'] for e in edges}) != len(edges):
        raise ValueError('Duplicate dependency edge')
    for e in edges:
        if e['from'] not in nodes or e['to'] not in nodes or not e['source_refs']:
            raise ValueError('Dangling/unproven dependency')
    if propagate(nodes, edges) != graph['impacts']:
        raise ValueError('Dependency impacts differ from deterministic propagation')
    for w in graph['claim_work']:
        proofs = [n for n in w['missing_proof_ids'] if n in graph['impacts']]
        if proofs != w['missing_proof_ids'] or w['financial_state'] != 'held' or w['financial_closure'] != 'unresolved':
            raise ValueError('Unproven financial release or missing proof impact')
    return {'verified_nodes': len(nodes), 'verified_edges': len(edges)}


def project(result):
    """Remove only blanket global-as-local presentation; retain all other holds."""
    result = deepcopy(result)
    for claim in result['claims']:
        claim['diagnostics'] = [f for f in claim['diagnostics'] if f['code'] != 'inherited_validation_limits']
    return result

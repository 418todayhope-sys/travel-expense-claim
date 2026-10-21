"""Decision 002 propagation, noninterference and sealed replay regressions."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from operator_delivery import build as b, containment as d
from reconciliation import reconcile as r
from validation import validate as v

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / 'artifacts/runs/omega4-live-20261020-attempt002'
N = ROOT / 'artifacts/normalizations/omega4-attempt002-normalization-v1'
V = ROOT / 'artifacts/validations/omega4-attempt002-business-disposition-validation-v1'
R = ROOT / 'artifacts/reconciliations/omega4-attempt002-business-disposition-reconciliation-v1'


class ContainmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc, cls.report, cls.validation, cls.result = b.load_verified(A, N, V, R)
        cls.graph = d.evaluate(cls.doc, cls.report, cls.result)

    def work(self, key, graph=None):
        return next(w for w in (graph or self.graph)['claim_work'] if w['claim_key'] == key)

    def mutate(self, change):
        doc = deepcopy(self.doc)
        change(doc)
        result = r.evaluate(doc, self.report, self.validation)
        return d.evaluate(doc, self.report, result), result

    def remove_payment(self, doc, cost):
        doc['workbook']['Merchant payments']['rows'] = [row for row in v.rows(doc, 'Merchant payments') if row['values']['Expense reference'] != cost]

    def test_exact_graph_counts_states_and_deterministic_order(self):
        self.assertEqual(self.graph['summary']['current_evidence_states'], {'independently_resumable': 119, 'partial': 2})
        self.assertEqual(self.graph, d.evaluate(self.doc, self.report, self.result))
        shuffled = deepcopy(self.doc)
        shuffled['claims'].reverse()
        self.assertEqual(self.graph, d.evaluate(shuffled, self.report, self.result))
        self.assertEqual(d.verify(self.graph)['verified_nodes'], len(self.graph['nodes']))
        self.assertTrue(all(w['financial_state'] == 'held' for w in self.graph['claim_work']))

    def test_c03_c24_shared_proof_hold_has_paths_to_both_claims(self):
        graph, result = self.mutate(lambda doc: self.remove_payment(doc, 'COST-03'))
        a, b24 = self.work('C03/r1', graph), self.work('C24/r1', graph)
        self.assertEqual(a['missing_proof_ids'], b24['missing_proof_ids'])
        self.assertEqual(len(a['missing_proof_ids']), 1)
        root = a['missing_proof_ids'][0]
        for w in [a, b24]:
            self.assertEqual(w['evidence_processing_state'], 'partial')
            self.assertTrue(any(i['root'] == root for i in graph['impacts'][w['review_node']]))
        self.assertEqual([q['request_id'] for q in result['requests']], [q['request_id'] for q in self.result['requests']])
        self.assertEqual(sum(q['admitted_net_cents'] for q in result['requests']), 1203415)
        self.assertEqual(next(c for c in result['claims'] if c['claim_id'] == 'C24')['gross_purchase_cents'], 25000)

    def test_cost24_only_does_not_contaminate_c03(self):
        graph, _ = self.mutate(lambda doc: self.remove_payment(doc, 'COST-24'))
        self.assertEqual(self.work('C03/r1', graph), self.work('C03/r1'))
        root = self.work('C24/r1', graph)['missing_proof_ids'][0]
        self.assertFalse(any(i['root'] == root for i in graph['impacts'][self.work('C03/r1')['financial_node']]))

    def test_c18_exact_old_trip_cancellation_does_not_touch_replacement(self):
        root = 'cancellation:TC018'
        old, replacement = self.work('C18/r1'), self.work('C18/r2')
        self.assertTrue(any(i['root'] == root for i in self.graph['impacts'][old['trip_node']]))
        self.assertNotIn(replacement['trip_node'], self.graph['impacts'])
        self.assertFalse(any(i['root'] == root for i in self.graph['impacts'][replacement['financial_node']]))
        self.assertEqual(replacement['evidence_processing_state'], 'independently_resumable')
        self.assertEqual(replacement['financial_state'], 'held')
        c = next(c for c in self.result['claims'] if (c['claim_id'], c['revision']) == ('C18', 2))
        self.assertEqual(c['selected_current_review_ids'], {})
        self.assertIn('decision_001_original_request_hold', [f['code'] for f in c['diagnostics']])
        self.assertEqual(next(q for q in self.result['requests'] if q['request_id'] == 'REQ-C18')['admitted_net_cents'], 10000)

    def test_missing_merchant_proof_is_owned_and_unrelated_work_executes(self):
        for key in ['C08/r1', 'C114/r1']:
            work = self.work(key)
            self.assertEqual(work['evidence_processing_state'], 'partial')
            self.assertEqual(len(work['missing_proof_ids']), 1)
            root = next(n for n in self.graph['nodes'] if n['node_id'] == work['missing_proof_ids'][0])
            employee = next(c['employee_id'] for c in self.doc['claims'] if (c['claim_id'], c['revision']) == (work['claim_id'], work['revision']))
            self.assertEqual((root['check_code'], root['owner']), ('merchant_payment', employee))
        independent = self.work('C01/r1')
        self.assertEqual(independent['evidence_processing_state'], 'independently_resumable')
        self.assertGreater(independent['executed_check_count'], 0)
        graph, _ = self.mutate(lambda doc: self.remove_payment(doc, 'COST-08'))
        self.assertEqual(independent, self.work('C01/r1', graph))

    def test_global_requirements_have_no_blanket_claim_defect_edges(self):
        globals_ = set(self.graph['global_requirement_ids'])
        self.assertEqual(len(globals_), 4)
        self.assertTrue(all(e['to'] == 'workflow:certification' for e in self.graph['edges'] if e['from'] in globals_))
        projected = d.project(self.result)
        self.assertFalse(any(f['code'] == 'inherited_validation_limits' for c in projected['claims'] for f in c['diagnostics']))
        self.assertEqual(projected['validation_global_findings'], self.result['validation_global_findings'])
        self.assertEqual([c['payment_readiness'] for c in projected['claims']], [c['payment_readiness'] for c in self.result['claims']])

    def test_same_total_correction_cannot_reuse_old_review(self):
        def change(doc):
            for row in v.rows(doc, 'Review ledger'):
                if row['values']['Subject reference'] == 'C09' and row['values']['Revision'] == 2:
                    row['values']['Revision'] = 1
        graph, result = self.mutate(change)
        current = next(c for c in result['claims'] if (c['claim_id'], c['revision']) == ('C09', 2))
        self.assertEqual(current['selected_current_review_ids'], {})
        self.assertEqual(current['gross_purchase_cents'], next(c for c in self.result['claims'] if (c['claim_id'], c['revision']) == ('C09', 2))['gross_purchase_cents'])
        self.assertEqual(self.work('C09/r2', graph)['review_state'], 'held')
        self.assertEqual(self.work('C01/r1', graph), self.work('C01/r1'))

    def test_partial_response_does_not_release_other_repairs(self):
        def change(doc):
            sample = deepcopy(next(row for row in v.rows(doc, 'Merchant payments') if row['values']['Expense reference'] == 'COST-01'))
            sample['record_id'] = 'isolated:merchant:COST-08'
            sample['values'].update({'Expense reference': 'COST-08', 'Receipt reference': 'R-COST-08', 'Trip reference': 'T08', 'Gross amount': '120.00'})
            v.rows(doc, 'Merchant payments').append(sample)
        graph, result = self.mutate(change)
        self.assertEqual(self.work('C08/r1', graph)['missing_proof_ids'], [])
        self.assertEqual(self.work('C08/r1', graph)['financial_state'], 'held')
        self.assertEqual(self.work('C114/r1', graph), self.work('C114/r1'))
        self.assertTrue(next(c for c in result['claims'] if c['claim_id'] == 'C08')['diagnostics'])

    def test_candidate_finance_allocations_never_create_cost_edges(self):
        for e in self.graph['edges']:
            if e['from'].startswith('request:'):
                self.assertTrue(e['to'].startswith('financial:'))
        self.assertTrue(all(q['basis_links']['attributed_revision'] is None for q in self.graph['candidate_request_allocations']))

    def test_permit_only_cancellation_preserves_exact_target(self):
        process = next(p for p in self.result['travel_cancellations'] if p['cancellation_id'] == 'TC121')
        edge = next(e for e in self.graph['edges'] if e['from'] == 'cancellation:TC121')
        self.assertEqual(edge['to'], f"permit:{process['permit_id']}/r{process['permit_revision']}")
        self.assertEqual(edge['kind'], 'exact_cancellation_target')
        self.assertFalse(any(e['from'] == 'cancellation:TC121' and e['to'].startswith('request:') for e in self.graph['edges']))

    def test_same_cost_id_with_different_purchase_tuple_is_not_shared_proof(self):
        def change(doc):
            claim = next(c for c in doc['claims'] if c['claim_id'] == 'C24')
            claim['expenses'][0]['receipt_id'] = 'different-receipt'
        graph, _ = self.mutate(change)
        old = self.work('C03/r1', graph)
        self.assertEqual(old, self.work('C03/r1'))
        new = self.work('C24/r1', graph)
        for root in new['missing_proof_ids']:
            self.assertFalse(any(i['root'] == root for i in graph['impacts'][old['financial_node']]))

    def test_numeric_precision_does_not_break_shared_purchase_identity(self):
        def change(doc):
            claim = next(c for c in doc['claims'] if c['claim_id'] == 'C24')
            claim['expenses'][0]['original_amount'] = '200.0'
            self.remove_payment(doc, 'COST-03')
        graph, _ = self.mutate(change)
        self.assertEqual(self.work('C03/r1', graph)['missing_proof_ids'], self.work('C24/r1', graph)['missing_proof_ids'])
        self.assertEqual(len(self.work('C24/r1', graph)['missing_proof_ids']), 1)

    def test_broken_graph_rejected(self):
        graph = deepcopy(self.graph)
        graph['edges'][0]['to'] = 'nonexistent'
        with self.assertRaises(ValueError): d.verify(graph)
        graph = deepcopy(self.graph)
        graph['impacts'].pop(next(iter(graph['impacts'])))
        with self.assertRaises(ValueError): d.verify(graph)

    def test_versioned_build_chain_preserves_earlier_repairs_and_evidence(self):
        prior = ROOT / 'artifacts/runs/omega4-attempt002-operator-v1'
        old = (prior / 'repair-queue.json').read_bytes()
        with tempfile.TemporaryDirectory() as temp, patch('socket.create_connection', side_effect=AssertionError('Offline')):
            output = Path(temp) / 'new-run'
            sealed = b.build(A, N, V, R, output, 'containment-test', dependency_containment=True, prior_operator=prior)
            self.assertEqual(b.verify(output)['verified_snapshots'], 4)
            self.assertEqual(sealed['summary']['open_repairs'], 582)
            self.assertEqual((output / 'prior-repair-queue.original.json').read_bytes(), old)
            final = json.loads((output / 'batches/004.json').read_bytes())
            self.assertEqual(final['prior_operator']['open_repairs'], 703)
            self.assertEqual(final['dependency_summary'], self.graph['summary'])
            self.assertEqual(len(final['normalization_diagnostics']), 18)
            self.assertTrue(all(c['status'] == 'held' and c['known_paid_cents'] is None for c in final['claims']))
            self.assertEqual(final['actual_financial_closure_count'], 0)
            with self.assertRaises(FileExistsError): b.build(A, N, V, R, output, 'containment-test', dependency_containment=True)
            graph_path = output / 'dependencies/004.json'
            graph_path.write_bytes(b'{}')
            with self.assertRaises(ValueError): b.verify(output)
        self.assertEqual((prior / 'repair-queue.json').read_bytes(), old)

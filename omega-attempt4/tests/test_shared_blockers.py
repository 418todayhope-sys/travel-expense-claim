"""Decision 003 real retained batches and isolated adversarial note/graph tests."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from operator_delivery import shared_blockers as s, containment as d
from validation import validate as v

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'artifacts/runs/omega4-attempt002-business-disposition-containment-v1'


class SharedBlockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graphs = [json.loads((SOURCE / f'dependencies/{n:03}.json').read_bytes()) for n in range(1, 5)]
        cls.snapshots = [json.loads((SOURCE / f'batches/{n:03}.json').read_bytes()) for n in range(1, 5)]
        cls.queues = [json.loads((SOURCE / f'queue/{n:03}.json').read_bytes()) for n in range(1, 5)]
        cls.values = []; previous = None
        for graph, snap, queue in zip(cls.graphs, cls.snapshots, cls.queues):
            previous = s.derive(graph, snap, queue, previous)
            cls.values.append(previous)
        cls.value = cls.values[-1]

    def blocker(self, key, value=None):
        return next(item for item in (value or self.value)['blockers'] if item['fact_key'] == key)

    def case(self, claim_id, revision=1, value=None):
        return next(item for item in (value or self.value)['cases'] if (item['claim_id'], item['revision']) == (claim_id, revision))

    def derive(self, graph=None, snap=None, queue=None, previous=None, deliveries=()):
        return s.derive(graph or self.graphs[-1], snap or self.snapshots[-1], queue or self.queues[-1], previous, deliveries)

    def note(self, record, **fields):
        ref = record['source_refs'][0]
        result = {'event_id': 'isolated:clarification:1', 'arrival_batch': 4,
                  'blocker_id': record['blocker_id'], 'fact_key': record['fact_key'],
                  'owner': record['owner'], 'reason': 'Isolated supplied clarification; no case authority.',
                  'source_refs': [ref], 'source_hashes': {ref: self.snapshots[-1]['source_index'][ref]['sha256']}, 'partial': True}
        result.update(fields)
        return result

    def shared_missing_graph(self):
        # Isolated graph-layer mutation; no retained source or artifact is edited.
        graph = deepcopy(self.graphs[-1])
        node = next(n for n in graph['nodes'] if n.get('check_code') == 'merchant_payment' and
                    'travel-registers:Merchant payments:row:8' in n['source_refs'])
        node['status'] = 'unresolved'; node['reason'] = 'Isolated conflicting shared purchase proof.'
        graph['impacts'] = d.propagate({n['node_id']: n for n in graph['nodes']}, graph['edges'])
        return graph, node

    def test_exact_current_counts_history_and_all_repairs_mapped(self):
        self.assertEqual(self.value['summary']['central_records'], 116)
        self.assertEqual(self.value['summary']['unscoped_package_records'], 6)
        self.assertEqual((self.value['summary']['case_views'], self.value['summary']['current_cases']), (127, 121))
        self.assertEqual((self.value['summary']['mapped_repairs'], self.value['summary']['open_repairs']), (845, 582))
        self.assertEqual(self.value['summary']['case_links'], 118)
        self.assertEqual(Counter(i['state'] for i in self.queues[-1]['items']), {'open': 582, 'cleared_by_recheck': 218, 'superseded': 45})
        self.assertTrue(all(item['history'] for item in self.value['blockers']))
        self.assertTrue(all(c['financial_closure'] == 'unresolved' for c in self.value['cases']))

    def test_c03_c24_supported_checks_are_not_invented_blockers(self):
        shared = set(next(w for w in self.graphs[-1]['claim_work'] if w['claim_key'] == 'C03/r1')['executed_check_ids']) & set(next(w for w in self.graphs[-1]['claim_work'] if w['claim_key'] == 'C24/r1')['executed_check_ids'])
        self.assertEqual(len(shared), 3)
        self.assertFalse(any(set(item['graph_node_ids']) & shared for item in self.value['blockers']))

    def test_c03_c24_missing_shared_cost_produces_one_bidirectional_blocker(self):
        graph, node = self.shared_missing_graph(); value = self.derive(graph=graph)
        record = self.blocker('graph:' + node['node_id'], value)
        self.assertEqual(record['owner'], 'EMP-01')
        self.assertEqual({link['case_id'] for link in record['case_links']}, {'case:C03/r1', 'case:C24/r1'})
        self.assertTrue(all(link['expense_ids'] == ['COST-03'] for link in record['case_links']))
        for claim in ('C03', 'C24'):
            self.assertIn(record['blocker_id'], [link['blocker_id'] for link in self.case(claim, value=value)['blocker_links']])
        self.assertEqual(self.case('C01', value=value), self.case('C01', value=self.derive()))

    def test_c08_c114_same_code_is_two_separate_proof_defects(self):
        records = [item for item in self.value['blockers'] if any(':merchant_payment' in n for n in item['graph_node_ids'])]
        self.assertEqual(len(records), 2)
        owners = {item['owner'] for item in records}
        self.assertEqual(owners, {'EMP-01', 'EMP-03'})
        self.assertEqual({tuple(link['expense_ids']) for item in records for link in item['case_links']}, {('COST-08',), ('COST-114-2',)})
        self.assertTrue(all(link['repair_ids'] for item in records for link in item['case_links']))
        self.assertEqual(len({item['blocker_id'] for item in records}), 2)

    def test_c18_old_trip_cancellation_and_replacement_finance_are_distinct(self):
        cancellation = self.blocker('graph:cancellation:TC018')
        self.assertEqual({link['case_id'] for link in cancellation['case_links']}, {'case:C18/r1'})
        request = self.blocker('graph:request:REQ-C18')
        self.assertEqual({link['case_id'] for link in request['case_links']}, {'case:C18/r1', 'case:C18/r2'})
        self.assertTrue(all(not link['expense_ids'] and link['relationship'] == 'request_claim_family_only_no_cost_attribution' for link in request['case_links']))
        current = self.case('C18', 2)
        self.assertEqual(current['trip_id'], 'T18B')
        self.assertIn('decision_001_original_request_hold', [i['code'] for i in current['requirements'] if i['state'] == 'open'])
        self.assertIn('approval_evidence', [i['code'] for i in current['requirements'] if i['state'] == 'open'])

    def test_unknown_package_scope_has_no_invented_cases_and_all_six_are_kept(self):
        unscoped = [item for item in self.value['blockers'] if item['scope'] == 'applicability_unknown']
        self.assertEqual(len(unscoped), 6)
        self.assertTrue(all(not item['case_links'] for item in unscoped))
        assignment = self.blocker('graph:requirement:assignment_access')
        self.assertIn('input:historical_assignment', assignment['evidence_artifacts'])
        self.assertTrue(assignment['evidence_gap'])

    def test_partial_package_response_does_not_clear_case_requirements(self):
        record = self.blocker('graph:requirement:review_version_token')
        payload = self.note(record)
        value = self.derive(previous=self.value, deliveries=[payload])
        updated = self.blocker(record['fact_key'], value)
        self.assertEqual(updated['clarification_state'], 'partial')
        self.assertEqual(updated['fact_state'], 'unresolved')
        self.assertEqual(updated['state'], 'clarification_received_recheck_required')
        for ident, revision in [('C08', 1), ('C114', 1), ('C18', 2)]:
            self.assertEqual(self.case(ident, revision, value)['requirements'], self.case(ident, revision)['requirements'])
            self.assertEqual(self.case(ident, revision, value)['financial_closure'], 'unresolved')

    def test_shared_fact_support_requires_each_case_recheck(self):
        graph, node = self.shared_missing_graph(); missing = self.derive(graph=graph)
        supported = deepcopy(graph)
        next(n for n in supported['nodes'] if n['node_id'] == node['node_id'])['status'] = 'supported'
        supported['impacts'] = d.propagate({n['node_id']: n for n in supported['nodes']}, supported['edges'])
        value = self.derive(graph=supported, previous=missing)
        record = self.blocker('graph:' + node['node_id'], value)
        self.assertEqual((record['fact_state'], record['state']), ('supported', 'clarified_recheck_required'))
        self.assertEqual(record['required_recheck_case_ids'], ['case:C03/r1', 'case:C24/r1'])
        for claim in ['C03', 'C24']:
            self.assertEqual(self.case(claim, value=value)['requirements'], self.case(claim, value=missing)['requirements'])
            self.assertTrue(self.case(claim, value=value)['remaining_open_repair_ids'])
            self.assertEqual(self.case(claim, value=value)['financial_state'], 'held')

    def test_repeated_delivery_and_same_batch_replay_are_idempotent(self):
        record = self.blocker('graph:requirement:review_version_token'); note = self.note(record)
        once = self.derive(previous=self.value, deliveries=[note])
        repeated = self.derive(previous=once, deliveries=[note, dict(note, arrival_batch=3)])
        self.assertEqual(len(repeated['delivery_ledger']), 1)
        self.assertEqual(len(repeated['delivery_ledger'][0]['variants']), 1)
        self.assertEqual(self.blocker(record['fact_key'], once)['history'], self.blocker(record['fact_key'], repeated)['history'])
        again = self.derive(previous=once, deliveries=[note])
        self.assertEqual(again, once)

    def test_conflicting_delivery_is_retained_without_clearing_cases(self):
        record = self.blocker('graph:requirement:review_version_token'); note = self.note(record)
        value = self.derive(previous=self.value, deliveries=[note, dict(note, reason='Contradicting immutable content')])
        self.assertEqual(value['delivery_ledger'][0]['classification'], 'conflicting_delivery')
        self.assertEqual(len(value['delivery_ledger'][0]['variants']), 2)
        self.assertEqual(self.blocker(record['fact_key'], value)['state'], 'open')
        self.assertEqual(value['cases'], self.value['cases'])

    def test_bad_owner_hash_and_future_deliveries_do_not_establish_fact(self):
        record = self.blocker('graph:requirement:review_version_token')
        for note in [self.note(record, owner='unrelated-owner'), self.note(record, source_hashes={})]:
            value = self.derive(previous=self.value, deliveries=[note])
            self.assertEqual(self.blocker(record['fact_key'], value)['clarification_state'], 'conflicting_or_unverified')
            self.assertEqual(value['cases'], self.value['cases'])
        value = self.derive(previous=self.value, deliveries=[self.note(record, arrival_batch=5)])
        self.assertEqual(value, self.value)
        with self.assertRaises(ValueError): self.derive(deliveries=[self.note(record, arrival_batch=-1)])

    def test_stable_identity_owner_handoff_and_history_across_batches(self):
        fact = 'graph:requirement:review_version_token'
        records = [self.blocker(fact, value) for value in self.values]
        self.assertEqual(len({item['blocker_id'] for item in records}), 1)
        self.assertEqual([h['batch'] for h in records[-1]['history']], [1, 2, 3, 4])
        queue = deepcopy(self.queues[-1])
        for item in queue['items']:
            if item['code'] == 'review_version_token': item['owner'] = 'Isolated supplied new coordinator'
        value = self.derive(queue=queue, previous=self.value)
        changed = self.blocker(fact, value)
        self.assertEqual(changed['blocker_id'], records[-1]['blocker_id'])
        self.assertEqual(changed['owner'], 'Isolated supplied new coordinator')
        self.assertEqual(changed['history'][0]['observation']['owner'], 'Facilitator')

    def test_tc122_no_financial_effect_history_does_not_create_case(self):
        record = self.blocker('graph:cancellation:TC122')
        self.assertEqual(record['state'], 'clarified_no_case_repair')
        self.assertEqual(record['case_links'], [])
        self.assertFalse(any(case['claim_id'] == 'TC122' for case in self.value['cases']))

    def test_changed_fact_identity_keeps_prior_history_without_guessed_merge(self):
        graph, node = self.shared_missing_graph(); old = self.derive(graph=graph)
        value = self.derive(previous=old)
        record = self.blocker('graph:' + node['node_id'], value)
        self.assertEqual(record['state'], 'clarified_recheck_required')
        self.assertEqual(record['blocker_id'], self.blocker('graph:' + node['node_id'], old)['blocker_id'])
        self.assertEqual(self.queues[-1], json.loads((SOURCE / 'queue/004.json').read_bytes()))

    def test_repair_mutation_and_broken_reverse_link_are_rejected(self):
        value = deepcopy(self.value)
        value['cases'][0]['requirements'][0]['state'] = 'cleared_by_recheck'
        with self.assertRaises(ValueError): s.verify_projection(value, self.graphs[-1], self.snapshots[-1], self.queues[-1])
        value = deepcopy(self.value)
        case = next(c for c in value['cases'] if c['blocker_links']); case['blocker_links'].clear()
        with self.assertRaises(ValueError): s.verify_projection(value, self.graphs[-1], self.snapshots[-1], self.queues[-1])

    def test_input_order_deterministic_and_native_data_not_mutated(self):
        graph = deepcopy(self.graphs[-1]); graph['nodes'].reverse(); graph['edges'].reverse()
        queue = deepcopy(self.queues[-1]); queue['items'].reverse()
        once = self.derive(); again = self.derive(graph=graph, queue=queue)
        self.assertNotEqual(once['evidence_index'], again['evidence_index'])
        for key in ['blockers', 'cases', 'repair_mapping', 'summary', 'delivery_ledger', 'source_index']:
            self.assertEqual(once[key], again[key])
        self.assertEqual(self.queues[-1], json.loads((SOURCE / 'queue/004.json').read_bytes()))

    def test_sealed_build_chain_hashes_financial_and_repair_identity(self):
        before = {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*') if p.is_file()}
        with tempfile.TemporaryDirectory() as tmp, patch('socket.create_connection', side_effect=AssertionError('Offline')):
            output = Path(tmp) / 'new-run'
            sealed = s.build(SOURCE, output, 'isolated-shared-test')
            checked = s.verify(output)
            self.assertEqual(checked['verified_snapshots'], 4)
            self.assertEqual(sealed['summary'], self.value['summary'])
            self.assertEqual((output / 'repair-queue.json').read_bytes(), (SOURCE / 'repair-queue.json').read_bytes())
            self.assertEqual((output / 'claims.csv').read_bytes(), (SOURCE / 'claims.csv').read_bytes())
            for n in range(1, 5):
                snap = json.loads((output / f'batches/{n:03}.json').read_bytes())
                self.assertEqual(snap['claims'], self.snapshots[n-1]['claims'])
                self.assertEqual(snap['finance_events'], self.snapshots[n-1]['finance_events'])
                self.assertEqual(snap['issues'], self.snapshots[n-1]['issues'])
            with self.assertRaises(FileExistsError): s.build(SOURCE, output, 'same')
            (output / 'shared-blockers/004.json').write_bytes(b'{}')
            with self.assertRaises(ValueError): s.verify(output)
        after = {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_invalid_input_or_output_location_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'bad'
            with self.assertRaises(ValueError): s.build(SOURCE, out, '../bad')
            self.assertFalse(out.exists())
        with self.assertRaises(ValueError): s.build(SOURCE, SOURCE / 'never-create', 'bad')
        self.assertFalse((SOURCE / 'never-create').exists())

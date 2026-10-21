"""End-to-end projection, schema, sealed chain and adversarial operator tests."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from operator_delivery import build as b
from reconciliation import reconcile as r
from validation import validate as v

ROOT = Path(__file__).resolve().parent.parent
ACQUISITION = ROOT / 'artifacts/runs/omega4-live-20261020-attempt002'
NORMALIZED = ROOT / 'artifacts/normalizations/omega4-attempt002-normalization-v1'
VALIDATED = ROOT / 'artifacts/validations/omega4-attempt002-business-disposition-validation-v1'
RECONCILED = ROOT / 'artifacts/reconciliations/omega4-attempt002-business-disposition-reconciliation-v1'


class OperatorDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name) / 'run'
        with patch('socket.create_connection', side_effect=AssertionError('Offline replay must not access the network')):
            cls.sealed = b.build(ACQUISITION, NORMALIZED, VALIDATED, RECONCILED, cls.output, 'operator-test-v1')
        cls.snapshots = [json.loads((cls.output / f'batches/{i:03}.json').read_bytes()) for i in range(1, 5)]
        cls.queues = [json.loads((cls.output / f'queue/{i:03}.json').read_bytes()) for i in range(1, 5)]
        cls.doc = json.loads((NORMALIZED / 'records.v1.json').read_bytes())
        cls.report = json.loads((NORMALIZED / 'parsing-report.v1.json').read_bytes())
        cls.validation = json.loads((VALIDATED / 'findings.v1.json').read_bytes())

    def claim(self, ident, batch=4, value=None):
        return next(c for c in (value or self.snapshots[batch - 1])['claims'] if c['claim_id'] == ident)

    def projected_mutation(self, change):
        doc = deepcopy(self.doc); change(doc)
        result = r.evaluate(doc, self.report, self.validation, 4)
        processes, work = b.cancellation_projection(doc, result, self.snapshots[2]['travel_cancellations'])
        active = b.active_work(doc, result, work)
        return b.snapshot(result, doc, self.report, 'isolated-test', self.snapshots[-1]['source_binding'],
                          self.snapshots[-1]['predecessor'], self.snapshots[-1]['queue_binding'], active, processes)

    def test_four_snapshots_schema_chain_and_exact_final_inventory(self):
        self.assertEqual(b.verify(self.output)['verified_snapshots'], 4)
        self.assertEqual([s['batch_id'] for s in self.snapshots], ['001', '002', '003', '004'])
        self.assertIsNone(self.snapshots[0]['predecessor'])
        for index, snap in enumerate(self.snapshots):
            b.check_snapshot(snap)
            if index:
                previous = self.output / f'batches/{index:03}.json'
                self.assertEqual(snap['predecessor'], {'path': str(previous.relative_to(self.output)), 'sha256': v.digest(previous.read_bytes())})
        self.assertEqual((len(self.snapshots[-1]['claims']), len(self.snapshots[-1]['claim_revision_history'])), (121, 127))
        self.assertEqual(self.snapshots[-1]['summary']['expense_occurrences'], 208)
        self.assertEqual(len(self.snapshots[-1]['admitted_event_ids']), 219)
        self.assertEqual(len(self.snapshots[-1]['request_facts']), 104)

    def test_source_bytes_and_non_native_provenance_preserved(self):
        self.assertEqual((self.output / 'acquisition-manifest.original.json').read_bytes(), (ACQUISITION / 'sources.json').read_bytes())
        for p in ACQUISITION.rglob('*'):
            if p.is_file() and p.name != 'sources.json':
                self.assertEqual((self.output / p.relative_to(ACQUISITION)).read_bytes(), p.read_bytes())
        source = json.loads((self.output / 'sources.json').read_bytes())
        self.assertEqual(source['replay_mode'], 'offline-retained-replay')
        self.assertEqual(source['acquisition_run_id'], 'omega4-live-20261020-attempt002')
        self.assertEqual(next(f for f in source['files'] if f['source_id'] == 'policy')['status'], 'unavailable')
        self.assertIsNone(source['case_clock'])

    def test_csv_unknown_money_blank_held_and_known_personal_zero(self):
        with (self.output / 'claims.csv').open(newline='') as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, b.CSV_FIELDS)
            rows = list(reader)
        self.assertEqual(len(rows), 121)
        self.assertTrue(all(x['status'] == 'held' and x['paid_cents'] == '' and x['balance_cents'] == '' for x in rows))
        self.assertEqual(next(x for x in rows if x['claim_id'] == 'C15')['allowed_cents'], '0')
        self.assertEqual(next(x for x in rows if x['claim_id'] == 'C08')['allowed_cents'], '')
        self.assertTrue(all(c['known_paid_cents'] is None and c['paid_cents_complete'] is False for c in self.snapshots[-1]['claims']))
        self.assertEqual(self.snapshots[-1]['requests'], [])
        self.assertFalse(self.snapshots[-1]['request_projection_complete'])

    def test_c03_c24_eligibility_gross_and_conditional_increment_not_closure(self):
        old, final = self.claim('C03'), self.claim('C24')
        self.assertEqual(old['gross_purchase_cents'], 20000)
        self.assertEqual((final['gross_purchase_cents'], final['policy_calculated_allowed_cents'], final['incremental_policy_candidate_cents']), (25000, 25000, 5000))
        self.assertEqual([line['cost_id'] for line in final['lines']], ['COST-03', 'COST-24'])
        self.assertEqual(final['financial_closure_status'], 'unresolved')
        self.assertIsNone(final['known_paid_cents'])

    def test_c09_corrected_revision_supersedes_old_reviews_and_queue_work(self):
        self.assertEqual((self.claim('C09', 1)['revision'], self.claim('C09', 3)['revision']), (1, 2))
        self.assertTrue(all('-2-claim-' in ident for ident in self.claim('C09')['decision_ids']))
        old_work = [i for i in self.queues[-1]['items'] if i['subject_type'] == 'claim' and i['subject_id'] == 'C09' and i['revision'] == 1]
        self.assertTrue(old_work)
        self.assertTrue(all(i['state'] == 'superseded' for i in old_work))
        self.assertTrue(any(c['claim_id'] == 'C09' and c['revision'] == 1 for c in self.snapshots[-1]['claim_revision_history']))

    def test_c18_late_original_money_missing_reviews_and_decision001_hold(self):
        final = self.claim('C18')
        self.assertEqual((final['revision'], final['trip_id'], final['status'], final['decision_ids']), (2, 'T18B', 'held', []))
        self.assertEqual(final['travel_cancellation_scope'], 'no_observed_cancellation')
        original = next(q for q in self.snapshots[-1]['request_facts'] if q['request_id'] == 'REQ-C18')
        self.assertEqual((original['original_accepted_cents'], original['accepted_cents'], original['net_confirmed_settled_cents']), (10000, 0, 10000))
        self.assertTrue(any(i['code'] == 'decision_001_original_request_hold' and i['subject_id'] == 'C18' and i['state'] == 'open' for i in self.queues[-1]['items']))
        self.assertIsNone(final['known_paid_cents'])

    def test_c19_c121_request_money_and_cancellation_scope_not_closure(self):
        c19, c121 = self.claim('C19'), self.claim('C121')
        self.assertEqual((c19['gross_purchase_cents'], c19['policy_calculated_allowed_cents']), (10000, 8000))
        request = next(q for q in self.snapshots[-1]['request_facts'] if q['request_id'] == 'REQ-C19')
        self.assertEqual((request['admitted_refund_cents'], request['admitted_net_cents']), (2000, 8000))
        self.assertTrue(request['resolution_assessment']['request_amounts_agree'])
        self.assertEqual((c121['gross_purchase_cents'], c121['policy_calculated_allowed_cents']), (3000, 2000))
        self.assertEqual(c121['travel_cancellation_scope'], 'retired_permit_trip_active')
        self.assertEqual(c121['financial_closure_status'], 'unresolved')

    def test_duplicate_finance_and_tc122_stay_separate(self):
        final = self.snapshots[-1]
        event = next(e for e in final['finance_events'] if e['event_id'] == 'F-C01-1')
        self.assertEqual(len(event['delivery_record_ids']), 2)
        self.assertEqual(len(event['repeated_delivery_record_ids']), 1)
        request = next(q for q in final['request_facts'] if q['request_id'] == 'REQ-C01')
        self.assertEqual(request['admitted_net_cents'], 10000)
        process = next(c for c in final['travel_cancellations'] if c['cancellation_id'] == 'TC122')
        self.assertEqual(process['financial_status'], 'no-financial-effect')
        self.assertEqual(process['affected_claim_ids'], [])
        self.assertEqual(set(process['admitted_cancellation_event_ids']), {'TC122-requested', 'TC122-confirmed'})
        self.assertNotIn('TC122-confirmed', final['admitted_event_ids'])

    def test_missing_merchant_payment_repairs_owned_per_cost(self):
        for claim_id, cost in [('C08', 'COST-08'), ('C114', 'COST-114-2')]:
            claim = self.claim(claim_id)
            self.assertEqual(next(l for l in claim['lines'] if l['cost_id'] == cost)['status'], 'unresolved')
            self.assertIsNone(claim['allowed_cents'])
            item = next(i for i in self.queues[-1]['items'] if i['subject_id'] == claim_id and i['code'] == 'merchant_payment')
            self.assertEqual(item['expense_id'], cost)
            self.assertTrue(item['owner'].startswith('EMP-'))
            self.assertEqual(item['state'], 'open')

    def test_arrival_boundaries_and_normalization_diagnostics(self):
        self.assertFalse(any(c['claim_id'] == 'C18' and c['revision'] == 2 for c in self.snapshots[1]['claim_revision_history']))
        self.assertEqual(len(self.snapshots[-1]['normalization_diagnostics']), 18)
        self.assertFalse(any(i['record_id'].startswith('claim-updates:page:4:') or i['record_id'] == 'claim-updates:page:4:claim' for i in self.snapshots[0]['normalization_diagnostics']))
        self.assertIsNone(next(p for p in self.snapshots[0]['travel_cancellations'] if p['cancellation_id'] == 'TC122')['confirmed_at'])
        self.assertEqual(next(p for p in self.snapshots[1]['travel_cancellations'] if p['cancellation_id'] == 'TC122')['status'], 'confirmed')

    def test_partial_response_clears_only_matching_item(self):
        last = self.queues[-1]['items']
        missing = next(i for i in last if i['subject_type'] == 'request' and i['subject_id'] == 'REQ-C01' and i['code'] == 'missing_settlement_evidence')
        binding = next(i for i in last if i['subject_type'] == 'request' and i['subject_id'] == 'REQ-C01' and i['code'] == 'request_revision_cost_binding')
        self.assertEqual(missing['state'], 'cleared_by_recheck')
        self.assertEqual(binding['state'], 'open')
        self.assertEqual(binding['first_seen_batch'], 1)
        self.assertEqual(binding['last_seen_batch'], 4)
        self.assertTrue(any(h['batch'] == 2 for h in binding['history']))

    def test_adversarial_conflict_keeps_money_and_unknown_exact_net(self):
        def change(doc):
            next(row for row in v.rows(doc, 'Finance activity') if row['source']['row'] == 31)['values']['Amount (EUR)'] = '999.00'
        snap = self.projected_mutation(change)
        req = next(q for q in snap['request_facts'] if q['request_id'] == 'REQ-C01')
        self.assertEqual(req['admitted_net_cents'], 10000)
        self.assertIsNone(req['net_confirmed_settled_cents'])
        self.assertEqual(self.claim('C01', value=snap)['status'], 'held')

    def test_adversarial_missing_payment_or_stale_approval_not_repaired_by_money(self):
        def change(doc):
            doc['workbook']['Merchant payments']['rows'] = [p for p in v.rows(doc, 'Merchant payments') if p['values']['Expense reference'] != 'COST-09B']
            for row in v.rows(doc, 'Review ledger'):
                if row['values']['Subject reference'] == 'C09' and row['values']['Revision'] == 2:
                    row['values']['Revision'] = 1
        snap = self.projected_mutation(change)
        c = self.claim('C09', value=snap)
        self.assertEqual(c['decision_ids'], [])
        self.assertIsNone(c['allowed_cents'])
        self.assertIsNone(c['known_paid_cents'])
        self.assertEqual(c['status'], 'held')

    def test_semantic_guard_rejects_false_closure_stale_reply_and_duplicate_money(self):
        for mode in ['closure', 'paid', 'stale', 'duplicate', 'future']:
            with self.subTest(mode=mode):
                snap = deepcopy(self.snapshots[-1])
                c = self.claim('C18', value=snap)
                if mode == 'closure':
                    c['status'] = 'closed-reimbursed'
                elif mode == 'paid':
                    c['paid_cents'] = 10000
                elif mode == 'stale':
                    c['decision_ids'] = ['D-C18-1-claim-administration-1']
                elif mode == 'duplicate':
                    snap['finance_events'].append(deepcopy(snap['finance_events'][0]))
                else:
                    snap['finance_events'][0]['first_arrival_batch'] = 5
                with self.assertRaises(ValueError):
                    b.check_snapshot(snap)

    def test_tampered_or_missing_snapshot_and_resealed_broken_predecessor_rejected(self):
        for mode in ['corrupt', 'missing', 'broken_link']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as t:
                target = Path(t) / 'copy'; shutil.copytree(self.output, target)
                path = target / 'batches/003.json'
                if mode == 'corrupt':
                    path.write_bytes(path.read_bytes() + b' ')
                elif mode == 'missing':
                    path.unlink()
                else:
                    value = json.loads(path.read_bytes()); value['predecessor']['sha256'] = '0' * 64
                    path.write_bytes(v.encoded(value))
                    manifest = json.loads((target / 'operator-manifest.v1.json').read_bytes())
                    next(f for f in manifest['files'] if f['path'] == 'batches/003.json')['sha256'] = v.digest(path.read_bytes())
                    (target / 'operator-manifest.v1.json').write_bytes(v.encoded(manifest))
                with self.assertRaises((ValueError, OSError)):
                    b.verify(target)

    def test_reconciliation_tampering_fails_before_output(self):
        with tempfile.TemporaryDirectory() as t:
            bad = Path(t) / 'recon'; bad.mkdir()
            data = json.loads((RECONCILED / 'reconciliation.v1.json').read_bytes())
            data['summary']['admitted_net_cents'] = 1
            (bad / 'reconciliation.v1.json').write_bytes(v.encoded(data))
            out = Path(t) / 'operator'
            with self.assertRaises(ValueError):
                b.build(ACQUISITION, NORMALIZED, VALIDATED, bad, out, 'bad-replay')
            self.assertFalse(out.exists())

    def test_replay_deterministic_originals_untouched_and_existing_output_refused(self):
        before = {b['path']: v.digest((ROOT / b['path']).read_bytes()) for b in self.sealed['input_bindings']}
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / 'second'
            b.build(ACQUISITION, NORMALIZED, VALIDATED, RECONCILED, out, 'operator-test-v1')
            for p in self.output.rglob('*'):
                if p.is_file():
                    self.assertEqual(p.read_bytes(), (out / p.relative_to(self.output)).read_bytes())
        self.assertTrue(all(v.digest((ROOT / path).read_bytes()) == sha for path, sha in before.items()))
        with patch.object(b, 'load_verified') as loader, self.assertRaises(FileExistsError):
            b.build(ACQUISITION, NORMALIZED, VALIDATED, RECONCILED, self.output, 'existing')
        loader.assert_not_called()

    def test_all_queue_owners_and_cancellation_issue_links_resolve(self):
        for snap, queue in zip(self.snapshots, self.queues):
            ids = {i['record_id'] for i in snap['issues']}
            self.assertTrue(all(i['owner'] and i['resolution_needed'] and i['history'] for i in queue['items']))
            for process in snap['travel_cancellations']:
                self.assertTrue(set(process['issue_record_ids']) <= ids)
        with (self.output / 'repair-queue.csv').open(newline='') as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), len(self.snapshots[-1]['issues']))


if __name__ == '__main__':
    unittest.main()
